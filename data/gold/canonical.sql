-- Canonical gold-set queries (operational-commerce-v1). Written independently of the
-- tool SQL in backend/ops/queries so the benchmark checks the system against a second
-- implementation. Every query applies the same authorization rule: an order is visible
-- to :subject only if it has lines and every line's seller is granted in :batch_id.
-- Late open: purchased <= as_of, 1..30 days past the estimated date, no delivery known.
-- Sections are named "-- name: <query>" and parsed by backend/ops/evals/gold.py.

-- name: late_visible_orders
WITH granted AS (
  SELECT seller_id FROM seller_grants WHERE subject = :subject AND batch_id = :batch_id
), visible AS (
  SELECT i.order_id
  FROM order_items i LEFT JOIN granted g ON g.seller_id = i.seller_id
  WHERE i.batch_id = :batch_id
  GROUP BY i.order_id
  HAVING bool_and(g.seller_id IS NOT NULL)
)
SELECT o.order_id
FROM orders o JOIN visible v ON v.order_id = o.order_id
WHERE o.batch_id = :batch_id
  AND o.purchased_at <= :as_of
  AND (CAST(:as_of AS timestamp)::date - o.estimated_at::date) BETWEEN 1 AND 30
  AND (o.delivered_at IS NULL OR o.delivered_at > :as_of)
  AND o.purchased_at >= CAST(:purchase_from AS date)
  AND o.purchased_at < CAST(:purchase_to AS date) + 1
ORDER BY o.order_id;

-- name: order_facts
WITH granted AS (
  SELECT seller_id FROM seller_grants WHERE subject = :subject AND batch_id = :batch_id
), lines AS (
  SELECT i.line_no, i.seller_id, i.product_id, i.price_centavos,
         (g.seller_id IS NOT NULL) AS granted
  FROM order_items i LEFT JOIN granted g ON g.seller_id = i.seller_id
  WHERE i.batch_id = :batch_id AND i.order_id = :order_id
)
SELECT o.order_id,
       (SELECT count(*) > 0 AND bool_and(granted) FROM lines) AS visible,
       o.purchased_at <= :as_of AS purchased_by_as_of,
       (CAST(:as_of AS timestamp)::date - o.estimated_at::date) AS days_overdue,
       (o.delivered_at IS NOT NULL AND o.delivered_at <= :as_of) AS delivery_known,
       (SELECT array_agg(DISTINCT seller_id ORDER BY seller_id) FROM lines) AS sellers,
       (SELECT array_agg(DISTINCT product_id ORDER BY product_id) FROM lines) AS products,
       (SELECT sum(price_centavos)::bigint FROM lines) AS order_value_centavos,
       (SELECT count(*) FROM lines) AS line_count
FROM orders o
WHERE o.batch_id = :batch_id AND o.order_id = :order_id;

-- name: seller_late_set
WITH granted AS (
  SELECT seller_id FROM seller_grants WHERE subject = :subject AND batch_id = :batch_id
), visible AS (
  SELECT i.order_id
  FROM order_items i LEFT JOIN granted g ON g.seller_id = i.seller_id
  WHERE i.batch_id = :batch_id
  GROUP BY i.order_id
  HAVING bool_and(g.seller_id IS NOT NULL) AND bool_or(i.seller_id = :seller_id)
), late AS (
  SELECT o.order_id FROM orders o JOIN visible v ON v.order_id = o.order_id
  WHERE o.batch_id = :batch_id AND o.purchased_at <= :as_of
    AND (CAST(:as_of AS timestamp)::date - o.estimated_at::date) BETWEEN 1 AND 30
    AND (o.delivered_at IS NULL OR o.delivered_at > :as_of)
)
SELECT array_agg(DISTINCT l.order_id ORDER BY l.order_id) AS order_ids,
       count(DISTINCT l.order_id) AS late_open_orders,
       coalesce(sum(i.price_centavos) FILTER (WHERE i.seller_id = :seller_id), 0)::bigint
         AS seller_line_value_centavos,
       count(DISTINCT l.order_id) FILTER (WHERE i.seller_id <> :seller_id) AS multi_seller_orders
FROM late l JOIN order_items i ON i.batch_id = :batch_id AND i.order_id = l.order_id;

-- name: late_aggregates
WITH granted AS (
  SELECT seller_id FROM seller_grants WHERE subject = :subject AND batch_id = :batch_id
), visible AS (
  SELECT i.order_id
  FROM order_items i LEFT JOIN granted g ON g.seller_id = i.seller_id
  WHERE i.batch_id = :batch_id
  GROUP BY i.order_id
  HAVING bool_and(g.seller_id IS NOT NULL)
), late AS (
  SELECT o.order_id FROM orders o
  JOIN visible v ON v.order_id = o.order_id
  JOIN customers c ON c.batch_id = o.batch_id AND c.customer_id = o.customer_id
  WHERE o.batch_id = :batch_id AND o.purchased_at <= :as_of
    AND (CAST(:as_of AS timestamp)::date - o.estimated_at::date) BETWEEN 1 AND 30
    AND (o.delivered_at IS NULL OR o.delivered_at > :as_of)
    AND o.purchased_at >= CAST(:purchase_from AS date)
    AND o.purchased_at < CAST(:purchase_to AS date) + 1
    AND (CAST(:customer_state AS text) IS NULL OR c.state = :customer_state)
), per_order AS (
  SELECT l.order_id, sum(i.price_centavos)::bigint AS value, count(DISTINCT i.seller_id) AS n
  FROM late l JOIN order_items i ON i.batch_id = :batch_id AND i.order_id = l.order_id
  GROUP BY l.order_id
)
SELECT count(*) AS late_open_orders,
       coalesce(sum(value), 0)::bigint AS line_value_centavos,
       count(*) FILTER (WHERE n > 1) AS multi_seller_orders,
       (SELECT count(DISTINCT i.seller_id) FROM late l JOIN order_items i
          ON i.batch_id = :batch_id AND i.order_id = l.order_id) AS distinct_sellers
FROM per_order;

-- name: event_overlaps
-- event_overlap(order, event, as_of): scope match (carrier known at as_of, any seller, or
-- customer state) AND the visible event window intersects [carrier_at known else
-- purchased_at, as_of]. Events starting after as_of are invisible.
WITH target_orders AS (
  SELECT o.order_id, o.purchased_at, c.state AS customer_state,
         CASE WHEN o.carrier_at <= :as_of THEN o.carrier_at END AS carrier_known,
         a.carrier_code
  FROM orders o
  JOIN customers c ON c.batch_id = o.batch_id AND c.customer_id = o.customer_id
  LEFT JOIN carrier_assignments a ON a.scenario_id = :scenario_id AND a.batch_id = o.batch_id
       AND a.order_id = o.order_id AND a.assigned_at <= :as_of
  WHERE o.batch_id = :batch_id AND o.order_id = ANY(CAST(:order_ids AS text[]))
)
SELECT e.event_id::text AS event_id, t.order_id
FROM disruption_events e CROSS JOIN target_orders t
WHERE e.scenario_id = :scenario_id AND e.starts_at <= :as_of
  AND ((e.carrier_code IS NOT NULL AND e.carrier_code = t.carrier_code)
       OR (e.seller_id IS NOT NULL AND EXISTS (
             SELECT 1 FROM order_items i WHERE i.batch_id = :batch_id
               AND i.order_id = t.order_id AND i.seller_id = e.seller_id))
       OR t.customer_state = ANY(e.affected_states))
  AND e.starts_at <= :as_of
  AND LEAST(e.ends_at, :as_of) >= COALESCE(t.carrier_known, t.purchased_at)
ORDER BY e.event_id, t.order_id;
