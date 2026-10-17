"""Server authored SQL for late_open_order(as_of) and the demo as_of scan.

late_open_order(as_of): purchased at or before as_of, date(as_of) is later than
date(estimated_at), and no customer delivery is known at as_of. Orders with no
lines are excluded because no actor can see an order with an empty line set.
This module never reads final order status.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Connection, text

DEMO_WINDOW = (date(2018, 1, 1), date(2018, 8, 31))

# Predicate fragment: o = orders alias, :as_of = timestamp.
LATE_OPEN_PREDICATE = """
    o.purchased_at <= :as_of
    AND o.estimated_at::date < CAST(:as_of AS timestamp)::date
    AND (o.delivered_at IS NULL OR o.delivered_at > :as_of)
"""

DAILY_SCAN_SQL = text("""
WITH days AS (
    SELECT d::date AS day,
           (d::date + interval '1 day' - interval '1 second')::timestamp AS as_of
    FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') AS d
),
late AS (
    SELECT days.day, o.order_id
    FROM days
    JOIN orders o
      ON o.batch_id = :batch_id
     AND o.purchased_at <= days.as_of
     AND o.estimated_at::date < days.day
     AND (o.delivered_at IS NULL OR o.delivered_at > days.as_of)
),
late_sellers AS (
    SELECT DISTINCT late.day, late.order_id, i.seller_id
    FROM late
    JOIN order_items i ON i.batch_id = :batch_id AND i.order_id = late.order_id
),
per_order AS (
    SELECT day, order_id, count(*) AS n_sellers FROM late_sellers GROUP BY day, order_id
),
per_seller AS (
    SELECT day, seller_id, count(*) AS n_orders FROM late_sellers GROUP BY day, seller_id
)
SELECT days.day,
       days.as_of,
       (SELECT count(*) FROM per_order p WHERE p.day = days.day) AS late_open_orders,
       (SELECT count(*) FROM per_seller s WHERE s.day = days.day AND s.n_orders >= 3)
           AS sellers_with_3_plus,
       (SELECT count(*) FROM per_order p WHERE p.day = days.day AND p.n_sellers > 1)
           AS late_open_multi_seller_orders
FROM days
ORDER BY days.day
""")

LATE_OPEN_ORDERS_SQL = text(f"""
SELECT o.order_id
FROM orders o
WHERE o.batch_id = :batch_id
  AND {LATE_OPEN_PREDICATE}
  AND EXISTS (SELECT 1 FROM order_items i
              WHERE i.batch_id = o.batch_id AND i.order_id = o.order_id)
ORDER BY o.order_id
""")

LATE_OPEN_SELLER_COUNTS_SQL = text(f"""
SELECT i.seller_id, count(DISTINCT o.order_id) AS late_open_orders
FROM orders o
JOIN order_items i ON i.batch_id = o.batch_id AND i.order_id = o.order_id
WHERE o.batch_id = :batch_id
  AND {LATE_OPEN_PREDICATE}
GROUP BY i.seller_id
ORDER BY late_open_orders DESC, i.seller_id ASC
""")


def daily_scan(conn: Connection, batch_id: str, start: date, end: date) -> list[dict]:
    result = conn.execute(DAILY_SCAN_SQL, {"batch_id": batch_id, "start": start, "end": end})
    return [dict(r._mapping) for r in result]


def late_open_order_ids(conn: Connection, batch_id: str, as_of: datetime) -> list[str]:
    rows = conn.execute(LATE_OPEN_ORDERS_SQL, {"batch_id": batch_id, "as_of": as_of})
    return [r.order_id for r in rows]


def late_open_seller_counts(conn: Connection, batch_id: str, as_of: datetime) -> list[tuple]:
    rows = conn.execute(LATE_OPEN_SELLER_COUNTS_SQL, {"batch_id": batch_id, "as_of": as_of})
    return [(r.seller_id, r.late_open_orders) for r in rows]


def rank_days(days: list[dict]) -> list[dict]:
    """Most sellers with >= 3 late open orders, then more late orders, then earlier date."""
    return sorted(
        days,
        key=lambda d: (-d["sellers_with_3_plus"], -d["late_open_orders"], d["day"]),
    )
