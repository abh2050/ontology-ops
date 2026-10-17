"""Save EXPLAIN (ANALYZE, BUFFERS) for every runtime query (M2 check 6).

Runs against the full Olist batch at its demo as_of, as the API role, for two
principals: reviewer (all sellers) and operator_a (partial scope).
Output: docs/evidence/explain/<principal>/<query>.txt and summary.json.

Run: uv run python scripts/explain_queries.py
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from sqlalchemy import text

from ops.data.as_of import demo_as_of, resolve_batch
from ops.db import engine
from ops.queries import late_orders as LQ
from ops.queries import tools as T
from ops.queries.scope import PRINCIPAL_SQL
from ops.settings import REPO_ROOT

OUT = REPO_ROOT / "docs" / "evidence" / "explain"

QUERIES = {
    "principal": PRINCIPAL_SQL,
    **T.QUERIES,
    "daily_scan": LQ.DAILY_SCAN_SQL,
    "late_open_orders": LQ.LATE_OPEN_ORDERS_SQL,
    "late_open_seller_counts": LQ.LATE_OPEN_SELLER_COUNTS_SQL,
}


def sample_params(conn, batch_id: str, subject: str, as_of: datetime) -> dict:
    late = conn.execute(text(f"""
        SELECT o.order_id, o.customer_id, i.seller_id FROM orders o
        JOIN order_items i ON i.batch_id = o.batch_id AND i.order_id = o.order_id
        WHERE o.batch_id = :batch_id AND {LQ.LATE_OPEN_PREDICATE}
          AND EXISTS (SELECT 1 FROM seller_grants g WHERE g.subject = :subject
                      AND g.batch_id = o.batch_id AND g.seller_id = i.seller_id)
        ORDER BY o.order_id LIMIT 1"""),
        {"batch_id": batch_id, "as_of": as_of, "subject": subject}).one()
    seller_orders = conn.execute(text(
        "SELECT DISTINCT order_id FROM order_items WHERE batch_id = :b AND seller_id = :s "
        "ORDER BY order_id LIMIT 20"), {"b": batch_id, "s": late.seller_id}).scalars().all()
    return {
        "batch_id": batch_id, "subject": subject, "as_of": as_of,
        "order_id": late.order_id, "customer_id": late.customer_id, "seller_id": late.seller_id,
        "order_ids": list(seller_orders), "scenario_id": "base-v1",
        "purchase_from": date(2018, 1, 1), "purchase_to": date(2018, 8, 31),
        "customer_state": None, "c_days": None, "c_value": None, "c_order": None,
        "limit_plus_one": 26, "limit": 100, "case_key": "0" * 64,
        "start": LQ.DEMO_WINDOW[0], "end": LQ.DEMO_WINDOW[1],
    }


def main() -> None:
    summary: dict[str, dict] = {}
    with engine("api").connect() as conn:
        batch_id, _ = resolve_batch(conn, None)
        as_of = demo_as_of(conn, batch_id)
        for subject in ("reviewer", "operator_a"):
            params = sample_params(conn, batch_id, subject, as_of)
            target = OUT / subject
            target.mkdir(parents=True, exist_ok=True)
            for name, clause in QUERIES.items():
                if subject == "operator_a" and name == "daily_scan":
                    continue  # import-time query, principal independent
                names = set(re.findall(r"(?<!:):([a-z_]+)", clause.text))
                bound = {k: v for k, v in params.items() if k in names}
                plan = conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) "
                                         + clause.text), bound).scalars().all()
                body = "\n".join(plan)
                header = (f"-- query: {name}\n-- principal: {subject}\n-- batch: {batch_id}\n"
                          f"-- as_of: {as_of}\n-- params: "
                          f"{json.dumps(bound, default=str, sort_keys=True)}\n\n")
                (target / f"{name}.txt").write_text(header + clause.text.strip() + "\n\n"
                                                    + body + "\n")
                exec_ms = float(re.search(r"Execution Time: ([\d.]+) ms", body).group(1))
                summary.setdefault(name, {})[subject] = exec_ms
    (OUT / "summary.json").write_text(json.dumps(
        {"batch_id": batch_id, "as_of": str(as_of), "execution_ms": summary}, indent=2) + "\n")
    for name, times in summary.items():
        print(f"{name:28s} " + "  ".join(f"{k}={v:8.2f} ms" for k, v in times.items()))


if __name__ == "__main__":
    main()
