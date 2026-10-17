"""ops seed-users: provision the four demo users and their explicit seller grants (spec 11.3).

Runs as the migration/admin role; runtime roles cannot modify users or grants.
Olist batch (decisions.md D-011): rank sellers with >= 1 late open order at the
default as_of by late open count desc, then seller_id asc. operator_a gets the
top half (odd middle seller included), operator_b every other seller in the
batch, reviewer all sellers, viewer none. fixtures-v1 grants are authored in
data/fixtures/grants.json.
"""

from __future__ import annotations

import json
import math

from sqlalchemy import text

from ops.data.as_of import AsOfError, demo_as_of
from ops.db import engine
from ops.queries.late_orders import late_open_seller_counts
from ops.settings import REPO_ROOT

USERS = {"operator_a": "operator", "operator_b": "operator", "reviewer": "reviewer",
         "viewer": "viewer"}
FIXTURES = REPO_ROOT / "data" / "fixtures"


class SeedError(Exception):
    pass


def olist_grants(conn, batch_id: str) -> dict[str, list[str]]:
    as_of = demo_as_of(conn, batch_id)
    ranked = [s for s, _ in late_open_seller_counts(conn, batch_id, as_of)]
    if not ranked:
        raise SeedError(f"batch {batch_id} has no sellers with late open orders at {as_of}")
    top = ranked[: math.ceil(len(ranked) / 2)]
    everyone = conn.execute(text("SELECT seller_id FROM sellers WHERE batch_id = :b "
                                 "ORDER BY seller_id"), {"b": batch_id}).scalars().all()
    top_set = set(top)
    return {"operator_a": sorted(top), "operator_b": [s for s in everyone if s not in top_set],
            "reviewer": list(everyone), "viewer": []}


def fixture_grants() -> dict[str, list[str]]:
    labels = json.loads((FIXTURES / "labels.json").read_text())
    authored = json.loads((FIXTURES / "grants.json").read_text())["grants_by_label"]
    return {user: sorted(labels[label] for label in sellers) for user, sellers in authored.items()}


def seed_users(mode: str) -> str:
    if mode == "aws":
        raise SeedError("--mode aws needs the Cognito user pool; not implemented until M4.5")
    if mode != "local":
        raise SeedError("--mode must be local or aws")
    lines = []
    with engine("admin").begin() as conn:
        batches = conn.execute(text(
            "SELECT batch_id, manifest->>'provenance' AS provenance FROM source_batches "
            "ORDER BY batch_id")).all()
        if not batches:
            raise SeedError("no batches imported; run ops data import first")
        conn.execute(text(
            "INSERT INTO users (subject, role, active) VALUES (:s, :r, true) "
            "ON CONFLICT (subject) DO UPDATE SET role = EXCLUDED.role, active = true"),
            [{"s": s, "r": r} for s, r in USERS.items()])
        conn.execute(text("DELETE FROM seller_grants WHERE subject = ANY(:subjects)"),
                     {"subjects": list(USERS)})
        for b in batches:
            try:
                grants = (fixture_grants() if b.provenance == "authored"
                          else olist_grants(conn, b.batch_id))
            except AsOfError as exc:
                raise SeedError(str(exc)) from exc
            rows = [{"s": user, "b": b.batch_id, "seller": seller}
                    for user, sellers in grants.items() for seller in sellers]
            if rows:
                conn.execute(text("INSERT INTO seller_grants (subject, batch_id, seller_id) "
                                  "VALUES (:s, :b, :seller)"), rows)
            lines.append(f"{b.batch_id}: " + ", ".join(
                f"{u}={len(grants[u])}" for u in USERS))
            split = conn.execute(text("""
                SELECT count(*) FROM (
                  SELECT i.order_id FROM order_items i
                  WHERE i.batch_id = :b GROUP BY i.order_id
                  HAVING bool_or(i.seller_id = ANY(:a)) AND bool_or(i.seller_id = ANY(:bb))
                ) x"""), {"b": b.batch_id, "a": grants["operator_a"],
                          "bb": grants["operator_b"]}).scalar_one()
            lines.append(f"  orders spanning operator_a and operator_b sellers: {split}")
    return "seeded users " + ", ".join(USERS) + "\n" + "\n".join(lines)
