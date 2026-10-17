"""Principal scope. Role never implies seller scope; explicit grants decide visibility.

VISIBLE_ORDER is the single authorization predicate. Every query that touches
orders applies it in its first CTE or WHERE clause, before joins, counts, totals,
graph construction, or serialization:
  - the actor is a provisioned, active user, and
  - the order has at least one line, and
  - every line's seller is granted to the actor in this batch.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import Connection, text

# Alias contract: the enclosing query names the orders row `o` and binds
# :subject and :batch_id.
VISIBLE_ORDER = """
    EXISTS (SELECT 1 FROM users u WHERE u.subject = :subject AND u.active)
    AND EXISTS (SELECT 1 FROM order_items vi
                WHERE vi.batch_id = o.batch_id AND vi.order_id = o.order_id)
    AND NOT EXISTS (
        SELECT 1 FROM order_items vi
        WHERE vi.batch_id = o.batch_id AND vi.order_id = o.order_id
          AND NOT EXISTS (SELECT 1 FROM seller_grants g
                          WHERE g.subject = :subject AND g.batch_id = vi.batch_id
                            AND g.seller_id = vi.seller_id))
"""

GRANTED_SELLER = """
    EXISTS (SELECT 1 FROM users u WHERE u.subject = :subject AND u.active)
    AND EXISTS (SELECT 1 FROM seller_grants g
                WHERE g.subject = :subject AND g.batch_id = :batch_id
                  AND g.seller_id = :seller_id)
"""

PRINCIPAL_SQL = text("""
SELECT u.role, u.active,
       (SELECT encode(sha256(convert_to(
                  coalesce(string_agg(g.seller_id, '|' ORDER BY g.seller_id), ''), 'UTF8')),
               'hex')
        FROM seller_grants g
        WHERE g.subject = u.subject AND g.batch_id = :batch_id) AS grants_digest
FROM users u WHERE u.subject = :subject
""")


@dataclass(frozen=True)
class Principal:
    subject: str
    batch_id: str
    role: str | None
    active: bool
    scope_hash: str

    @property
    def provisioned(self) -> bool:
        return self.role is not None and self.active

    def params(self) -> dict[str, str]:
        return {"subject": self.subject, "batch_id": self.batch_id}


def load_principal(conn: Connection, subject: str, batch_id: str) -> Principal:
    """Resolve the current scope from the database. Never cached across requests."""
    row = conn.execute(PRINCIPAL_SQL, {"subject": subject, "batch_id": batch_id}).one_or_none()
    role = row.role if row else None
    active = bool(row and row.active)
    grants = row.grants_digest if row and active else "-"
    digest = hashlib.sha256("|".join([subject, batch_id, role or "-", grants]).encode()
                            ).hexdigest()
    return Principal(subject, batch_id, role, active, digest)
