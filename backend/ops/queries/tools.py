"""The five allowlisted tools (spec 10.1).

Every tool takes a strict Pydantic input, runs only server authored,
parameterized SQL from this module, applies the principal's scope before any
join or aggregate, masks events after as_of, and returns a typed result with
evidence references and a canonical evidence hash. A hidden or nonexistent
target raises the same NotVisible error, so callers cannot probe for IDs.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import Connection, text

from ops.ontology.registry import ONTOLOGY_VERSION
from ops.queries.derived import (
    EventScope,
    OrderContext,
    days_overdue,
    event_overlap,
    known_delivery_state,
    late_open,
)
from ops.queries.evidence import EvidenceRef, evidence_hash, ref_for
from ops.queries.late_orders import DEMO_WINDOW, LATE_OPEN_PREDICATE
from ops.queries.scope import GRANTED_SELLER, VISIBLE_ORDER, Principal

Hex32 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
Hex64 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
State = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
ScenarioId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
TargetType = Literal["Order", "Seller"]
ActionKind = Literal["CreateInvestigation", "DraftCustomerUpdate"]
MAX_PAGE = 100
SORT_NOTE = ("Prioritization heuristic: days overdue descending, line value descending, "
             "then order_id. Not a learned estimate of intervention value.")
CAUSAL_NOTE = ("Synthetic scenario. Temporal and regional consistency only; this does not "
               "establish a cause of delay.")


class NotVisible(LookupError):
    """Target does not exist, is outside the actor's scope, or is not known at as_of."""

    def __init__(self, what: str = "target"):
        super().__init__(f"{what} not found or not visible")


class ToolInputError(ValueError):
    pass


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def _naive(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            raise ValueError("as_of is dataset local and must not carry a timezone")
        return v


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    ontology_version: str = ONTOLOGY_VERSION
    batch_id: str
    as_of: datetime
    evidence: list[EvidenceRef]
    evidence_hash: str = ""

    def seal(self):
        self.evidence_hash = evidence_hash(self)
        return self


def _p(principal: Principal, **extra) -> dict:
    return {**principal.params(), **extra}


def _require_provisioned(principal: Principal) -> None:
    if not principal.provisioned:
        raise NotVisible()


# ---------------------------------------------------------------------------------
# 1. get_order_snapshot
# ---------------------------------------------------------------------------------

ORDER_SNAPSHOT_SQL = text(f"""
SELECT o.order_id, o.customer_id, o.provenance, o.purchased_at, o.approved_at,
       o.carrier_at, o.delivered_at, o.estimated_at, c.state AS customer_state
FROM orders o
JOIN customers c ON c.batch_id = o.batch_id AND c.customer_id = o.customer_id
WHERE o.batch_id = :batch_id AND o.order_id = :order_id
  AND o.purchased_at <= :as_of
  AND {VISIBLE_ORDER}
""")

ORDER_LINES_SQL = text("""
SELECT i.line_no, i.product_id, p.category, i.seller_id, s.state AS seller_state,
       i.shipping_limit_at, i.price_centavos, i.freight_centavos
FROM order_items i
JOIN products p ON p.batch_id = i.batch_id AND p.product_id = i.product_id
JOIN sellers s ON s.batch_id = i.batch_id AND s.seller_id = i.seller_id
WHERE i.batch_id = :batch_id AND i.order_id = :order_id
ORDER BY i.line_no
""")

CUSTOMER_VISIBLE_ORDERS_SQL = text(f"""
SELECT o.order_id
FROM orders o
WHERE o.batch_id = :batch_id AND o.customer_id = :customer_id AND o.order_id <> :order_id
  AND o.purchased_at <= :as_of
  AND {VISIBLE_ORDER}
ORDER BY o.order_id
LIMIT 20
""")


class OrderSnapshotInput(_In):
    order_id: Hex32


class SnapshotOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str
    provenance: str
    purchased_at: datetime
    approved_at: datetime | None
    carrier_at: datetime | None
    delivered_at: datetime | None
    estimated_delivery_date: date
    delivery_state: str
    late_open: bool
    days_overdue: int


class SnapshotLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_no: int
    product_id: str
    category: str | None  # source text; untrusted, never instructions
    seller_id: str
    seller_state: str
    shipping_limit_at: datetime
    price_centavos: int
    freight_centavos: int


class SnapshotMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_count: int
    seller_count: int
    order_value_centavos: int
    freight_centavos: int
    value_by_seller_centavos: dict[str, int]


class OrderSnapshot(_Out):
    tool: Literal["get_order_snapshot"] = "get_order_snapshot"
    order: SnapshotOrder
    customer: dict[str, str]
    lines: list[SnapshotLine]
    metrics: SnapshotMetrics
    customer_other_visible_orders: list[str]


def get_order_snapshot(conn: Connection, principal: Principal,
                       inp: OrderSnapshotInput) -> OrderSnapshot:
    _require_provisioned(principal)
    params = _p(principal, order_id=inp.order_id, as_of=inp.as_of)
    row = conn.execute(ORDER_SNAPSHOT_SQL, params).one_or_none()
    if row is None:
        raise NotVisible("order")
    lines = [SnapshotLine(**r._mapping) for r in conn.execute(ORDER_LINES_SQL, params)]
    others = conn.execute(CUSTOMER_VISIBLE_ORDERS_SQL,
                          {**params, "customer_id": row.customer_id}).scalars().all()
    by_seller: dict[str, int] = {}
    for line in lines:
        by_seller[line.seller_id] = by_seller.get(line.seller_id, 0) + line.price_centavos
    as_of = inp.as_of
    overdue = days_overdue(row.estimated_at, as_of)
    masked_delivery = row.delivered_at if row.delivered_at and row.delivered_at <= as_of else None
    order = SnapshotOrder(
        order_id=row.order_id,
        provenance=row.provenance,
        purchased_at=row.purchased_at,
        approved_at=row.approved_at if row.approved_at and row.approved_at <= as_of else None,
        carrier_at=row.carrier_at if row.carrier_at and row.carrier_at <= as_of else None,
        delivered_at=masked_delivery,
        estimated_delivery_date=row.estimated_at.date(),
        delivery_state=known_delivery_state(row.approved_at, row.carrier_at, row.delivered_at,
                                            as_of),
        late_open=late_open(row.purchased_at, row.estimated_at, row.delivered_at, as_of),
        days_overdue=overdue,
    )
    b, prov = principal.batch_id, row.provenance
    evidence = [ref_for("Order", row.order_id, b, prov),
                ref_for("Customer", row.customer_id, b, prov)]
    for line in lines:
        evidence += [ref_for("OrderLine", f"{row.order_id}#{line.line_no}", b, prov),
                     ref_for("Seller", line.seller_id, b, prov),
                     ref_for("Product", line.product_id, b, prov)]
    return OrderSnapshot(
        batch_id=b, as_of=as_of, order=order,
        customer={"customer_id": row.customer_id, "state": row.customer_state},
        lines=lines,
        metrics=SnapshotMetrics(
            line_count=len(lines), seller_count=len(by_seller),
            order_value_centavos=sum(line.price_centavos for line in lines),
            freight_centavos=sum(line.freight_centavos for line in lines),
            value_by_seller_centavos=dict(sorted(by_seller.items())),
        ),
        customer_other_visible_orders=list(others),
        evidence=_dedupe(evidence),
    ).seal()


def _dedupe(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: dict[str, EvidenceRef] = {}
    for r in refs:
        seen.setdefault(r.ref, r)
    return list(seen.values())


# ---------------------------------------------------------------------------------
# 2. find_late_orders
# ---------------------------------------------------------------------------------

_LATE_FILTERED_CTE = f"""
late AS (
    SELECT o.order_id, o.purchased_at, o.estimated_at, o.provenance,
           (CAST(:as_of AS date) - o.estimated_at::date) AS days_overdue
    FROM orders o
    WHERE o.batch_id = :batch_id
      AND {LATE_OPEN_PREDICATE}
      AND o.purchased_at >= CAST(:purchase_from AS date)
      AND o.purchased_at < CAST(:purchase_to AS date) + 1
      AND (CAST(:customer_state AS text) IS NULL OR EXISTS (
            SELECT 1 FROM customers fc WHERE fc.batch_id = o.batch_id
              AND fc.customer_id = o.customer_id AND fc.state = :customer_state))
      AND (CAST(:seller_id AS text) IS NULL OR EXISTS (
            SELECT 1 FROM order_items fi WHERE fi.batch_id = o.batch_id
              AND fi.order_id = o.order_id AND fi.seller_id = :seller_id))
      AND {VISIBLE_ORDER}
),
lined AS (
    SELECT l.order_id, l.purchased_at, l.estimated_at, l.provenance, l.days_overdue,
           sum(i.price_centavos)::bigint AS line_value,
           count(*) AS line_count,
           count(DISTINCT i.seller_id) AS seller_count,
           array_agg(DISTINCT i.seller_id ORDER BY i.seller_id) AS seller_ids
    FROM late l
    JOIN order_items i ON i.batch_id = :batch_id AND i.order_id = l.order_id
    GROUP BY l.order_id, l.purchased_at, l.estimated_at, l.provenance, l.days_overdue
)
"""

LATE_QUEUE_PAGE_SQL = text(f"""
WITH {_LATE_FILTERED_CTE}
SELECT * FROM lined
WHERE CAST(:c_days AS integer) IS NULL
   OR days_overdue < :c_days
   OR (days_overdue = :c_days AND (line_value < :c_value
       OR (line_value = :c_value AND order_id > :c_order)))
ORDER BY days_overdue DESC, line_value DESC, order_id ASC
LIMIT :limit_plus_one
""")

LATE_QUEUE_AGGREGATES_SQL = text(f"""
WITH {_LATE_FILTERED_CTE}
SELECT (SELECT count(*) FROM lined) AS late_open_orders,
       (SELECT count(*) FROM lined WHERE seller_count > 1) AS multi_seller_orders,
       (SELECT coalesce(sum(line_value), 0)::bigint FROM lined) AS line_value_centavos,
       (SELECT count(DISTINCT i.seller_id) FROM late l
        JOIN order_items i ON i.batch_id = :batch_id AND i.order_id = l.order_id)
           AS distinct_sellers
""")


class FindLateOrdersInput(_In):
    purchase_from: date = DEMO_WINDOW[0]
    purchase_to: date = DEMO_WINDOW[1]
    seller_id: Hex32 | None = None
    customer_state: State | None = None
    limit: int = Field(default=25, ge=1, le=MAX_PAGE)
    cursor: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _window(self):
        if self.purchase_from > self.purchase_to:
            raise ValueError("purchase_from must not be after purchase_to")
        return self


class QueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str
    provenance: str
    purchased_at: datetime
    estimated_delivery_date: date
    days_overdue: int
    line_count: int
    seller_ids: list[str]
    multi_seller: bool
    line_value_centavos: int


class QueueAggregates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    late_open_orders: int
    distinct_sellers: int
    multi_seller_orders: int
    line_value_centavos: int


class LateOrdersPage(_Out):
    tool: Literal["find_late_orders"] = "find_late_orders"
    filters: dict
    items: list[QueueItem]
    aggregates: QueueAggregates
    next_cursor: str | None
    sort_note: str = SORT_NOTE


def _encode_cursor(item: QueueItem) -> str:
    raw = json.dumps([item.days_overdue, item.line_value_centavos, item.order_id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[int, int, str]:
    try:
        days, value, order_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not (isinstance(days, int) and isinstance(value, int) and isinstance(order_id, str)
                and len(order_id) == 32):
            raise ValueError
        return days, value, order_id
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ToolInputError("invalid cursor") from None


def find_late_orders(conn: Connection, principal: Principal,
                     inp: FindLateOrdersInput) -> LateOrdersPage:
    filters = {"purchase_from": inp.purchase_from, "purchase_to": inp.purchase_to,
               "seller_id": inp.seller_id, "customer_state": inp.customer_state}
    if not principal.provisioned:
        agg = QueueAggregates(late_open_orders=0, distinct_sellers=0, multi_seller_orders=0,
                              line_value_centavos=0)
        return LateOrdersPage(batch_id=principal.batch_id, as_of=inp.as_of, filters=filters,
                              items=[], aggregates=agg, next_cursor=None, evidence=[]).seal()
    c_days = c_value = c_order = None
    if inp.cursor:
        c_days, c_value, c_order = _decode_cursor(inp.cursor)
    params = _p(principal, as_of=inp.as_of, **filters, c_days=c_days, c_value=c_value,
                c_order=c_order, limit_plus_one=inp.limit + 1)
    rows = conn.execute(LATE_QUEUE_PAGE_SQL, params).all()
    items = [
        QueueItem(order_id=r.order_id, provenance=r.provenance, purchased_at=r.purchased_at,
                  estimated_delivery_date=r.estimated_at.date(), days_overdue=r.days_overdue,
                  line_count=r.line_count, seller_ids=list(r.seller_ids),
                  multi_seller=r.seller_count > 1, line_value_centavos=r.line_value)
        for r in rows[: inp.limit]
    ]
    a = conn.execute(LATE_QUEUE_AGGREGATES_SQL, params).one()
    aggregates = QueueAggregates(late_open_orders=a.late_open_orders,
                                 distinct_sellers=a.distinct_sellers,
                                 multi_seller_orders=a.multi_seller_orders,
                                 line_value_centavos=a.line_value_centavos)
    b = principal.batch_id
    evidence = [ref_for("Aggregate", "find_late_orders", b, "derived")]
    evidence += [ref_for("Order", i.order_id, b, i.provenance) for i in items]
    return LateOrdersPage(
        batch_id=b, as_of=inp.as_of, filters=filters, items=items, aggregates=aggregates,
        next_cursor=_encode_cursor(items[-1]) if len(rows) > inp.limit else None,
        evidence=evidence,
    ).seal()


# ---------------------------------------------------------------------------------
# 3. get_seller_exception_scope
# ---------------------------------------------------------------------------------

SELLER_SQL = text(f"""
SELECT s.seller_id, s.state, s.provenance FROM sellers s
WHERE s.batch_id = :batch_id AND s.seller_id = :seller_id AND {GRANTED_SELLER}
""")

_SELLER_LATE_CTE = f"""
seller_late AS (
    SELECT o.order_id, o.provenance,
           (CAST(:as_of AS date) - o.estimated_at::date) AS days_overdue
    FROM orders o
    WHERE o.batch_id = :batch_id
      AND o.order_id IN (SELECT si.order_id FROM order_items si
                         WHERE si.batch_id = :batch_id AND si.seller_id = :seller_id)
      AND {LATE_OPEN_PREDICATE}
      AND {VISIBLE_ORDER}
)
"""

SELLER_SCOPE_LINES_SQL = text(f"""
WITH {_SELLER_LATE_CTE}
SELECT sl.order_id, sl.provenance, sl.days_overdue, i.line_no, i.product_id, i.seller_id,
       i.price_centavos, i.freight_centavos
FROM seller_late sl
JOIN order_items i ON i.batch_id = :batch_id AND i.order_id = sl.order_id
WHERE sl.order_id IN (SELECT order_id FROM seller_late
                      ORDER BY days_overdue DESC, order_id LIMIT :limit)
ORDER BY sl.days_overdue DESC, sl.order_id, i.line_no
""")

SELLER_SCOPE_AGGREGATES_SQL = text(f"""
WITH {_SELLER_LATE_CTE}
SELECT count(DISTINCT sl.order_id) AS late_open_orders,
       coalesce(sum(i.price_centavos) FILTER (WHERE i.seller_id = :seller_id), 0)::bigint
           AS seller_line_value_centavos,
       coalesce(sum(i.freight_centavos) FILTER (WHERE i.seller_id = :seller_id), 0)::bigint
           AS seller_freight_centavos,
       count(DISTINCT sl.order_id) FILTER (WHERE i.seller_id <> :seller_id)
           AS multi_seller_orders
FROM seller_late sl
JOIN order_items i ON i.batch_id = :batch_id AND i.order_id = sl.order_id
""")


class SellerScopeInput(_In):
    seller_id: Hex32
    limit: int = Field(default=MAX_PAGE, ge=1, le=MAX_PAGE)


class SellerLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_no: int
    product_id: str
    price_centavos: int
    freight_centavos: int


class SellerOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str
    days_overdue: int
    multi_seller: bool
    seller_lines: list[SellerLine]
    seller_line_value_centavos: int
    other_seller_ids: list[str]


class SellerAggregates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    late_open_orders: int
    seller_line_value_centavos: int
    seller_freight_centavos: int
    multi_seller_orders: int


class SellerScope(_Out):
    tool: Literal["get_seller_exception_scope"] = "get_seller_exception_scope"
    seller: dict[str, str]
    orders: list[SellerOrder]
    aggregates: SellerAggregates
    truncated: bool
    attribution_note: str = ("Exposure sums only this seller's own order lines. A seller "
                             "relationship records fulfilment, not fault.")


def get_seller_exception_scope(conn: Connection, principal: Principal,
                               inp: SellerScopeInput) -> SellerScope:
    _require_provisioned(principal)
    params = _p(principal, seller_id=inp.seller_id, as_of=inp.as_of, limit=inp.limit)
    seller = conn.execute(SELLER_SQL, params).one_or_none()
    if seller is None:
        raise NotVisible("seller")
    orders: dict[str, SellerOrder] = {}
    provenance: dict[str, str] = {}
    for r in conn.execute(SELLER_SCOPE_LINES_SQL, params):
        o = orders.setdefault(r.order_id, SellerOrder(
            order_id=r.order_id, days_overdue=r.days_overdue, multi_seller=False,
            seller_lines=[], seller_line_value_centavos=0, other_seller_ids=[]))
        provenance[r.order_id] = r.provenance
        if r.seller_id == inp.seller_id:
            o.seller_lines.append(SellerLine(line_no=r.line_no, product_id=r.product_id,
                                             price_centavos=r.price_centavos,
                                             freight_centavos=r.freight_centavos))
            o.seller_line_value_centavos += r.price_centavos
        elif r.seller_id not in o.other_seller_ids:
            o.other_seller_ids.append(r.seller_id)
            o.multi_seller = True
    a = conn.execute(SELLER_SCOPE_AGGREGATES_SQL, params).one()
    aggregates = SellerAggregates(**a._mapping)
    b = principal.batch_id
    evidence = [ref_for("Seller", seller.seller_id, b, seller.provenance),
                ref_for("Aggregate", f"seller_scope:{seller.seller_id}", b, "derived")]
    for o in orders.values():
        evidence.append(ref_for("Order", o.order_id, b, provenance[o.order_id]))
        evidence += [ref_for("OrderLine", f"{o.order_id}#{line.line_no}", b,
                             provenance[o.order_id]) for line in o.seller_lines]
    return SellerScope(
        batch_id=b, as_of=inp.as_of,
        seller={"seller_id": seller.seller_id, "state": seller.state,
                "provenance": seller.provenance},
        orders=list(orders.values()), aggregates=aggregates,
        truncated=aggregates.late_open_orders > len(orders), evidence=evidence,
    ).seal()


# ---------------------------------------------------------------------------------
# 4. check_case_eligibility
# ---------------------------------------------------------------------------------

SELECTED_ORDERS_SQL = text(f"""
SELECT o.order_id
FROM orders o
WHERE o.batch_id = :batch_id
  AND o.order_id = ANY(CAST(:order_ids AS text[]))
  AND {LATE_OPEN_PREDICATE}
  AND (CAST(:seller_id AS text) IS NULL OR EXISTS (
        SELECT 1 FROM order_items si WHERE si.batch_id = o.batch_id
          AND si.order_id = o.order_id AND si.seller_id = :seller_id))
  AND {VISIBLE_ORDER}
""")

EXISTING_CASE_SQL = text("SELECT case_id FROM cases WHERE case_key = :case_key")


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    target_type: TargetType
    target_id: Hex32


class EligibilityInput(_In):
    target: Target
    kind: ActionKind = "CreateInvestigation"
    selected_order_ids: list[Hex32] = Field(min_length=1, max_length=MAX_PAGE)
    snapshot_hash: Hex64


class Eligibility(_Out):
    tool: Literal["check_case_eligibility"] = "check_case_eligibility"
    target: Target
    kind: ActionKind
    eligible: bool
    reasons: list[str]
    stale: bool
    current_snapshot_hash: str | None
    case_key: str
    existing_case_id: str | None


def case_key(batch_id: str, target: Target, as_of: datetime, kind: str) -> str:
    raw = f"{batch_id}|{target.target_type}|{target.target_id}|{as_of.isoformat()}|{kind}"
    return hashlib.sha256(raw.encode()).hexdigest()


def target_snapshot(conn: Connection, principal: Principal, target: Target,
                    as_of: datetime) -> OrderSnapshot | SellerScope:
    if target.target_type == "Order":
        return get_order_snapshot(conn, principal,
                                  OrderSnapshotInput(order_id=target.target_id, as_of=as_of))
    return get_seller_exception_scope(conn, principal,
                                      SellerScopeInput(seller_id=target.target_id, as_of=as_of))


def check_case_eligibility(conn: Connection, principal: Principal,
                           inp: EligibilityInput) -> Eligibility:
    reasons: list[str] = []
    current: str | None = None
    try:
        snapshot = target_snapshot(conn, principal, inp.target, inp.as_of)
        current = snapshot.evidence_hash
    except NotVisible:
        snapshot = None
        reasons.append("TARGET_NOT_VISIBLE")

    selected = sorted(set(inp.selected_order_ids))
    if len(selected) != len(inp.selected_order_ids):
        reasons.append("DUPLICATE_SELECTED_ORDER")
    if inp.kind == "DraftCustomerUpdate" and inp.target.target_type != "Order":
        reasons.append("DRAFT_TARGET_MUST_BE_ORDER")
    if inp.target.target_type == "Order" and selected != [inp.target.target_id]:
        reasons.append("ORDER_TARGET_SELECTS_ONLY_ITSELF")
    if snapshot is not None and principal.provisioned:
        seller = inp.target.target_id if inp.target.target_type == "Seller" else None
        ok = set(conn.execute(SELECTED_ORDERS_SQL, _p(
            principal, order_ids=selected, as_of=inp.as_of, seller_id=seller)).scalars())
        if inp.kind == "CreateInvestigation" and ok != set(selected):
            reasons.append("SELECTED_ORDER_NOT_ELIGIBLE")
    stale = current is not None and current != inp.snapshot_hash
    if stale:
        reasons.append("STALE_SNAPSHOT")
    key = case_key(principal.batch_id, inp.target, inp.as_of, inp.kind)
    existing = None
    if inp.kind == "CreateInvestigation":
        found = conn.execute(EXISTING_CASE_SQL, {"case_key": key}).scalar_one_or_none()
        if found is not None:
            existing = str(found)
            reasons.append("CASE_ALREADY_EXISTS")
    evidence = snapshot.evidence if snapshot is not None else []
    return Eligibility(
        batch_id=principal.batch_id, as_of=inp.as_of, target=inp.target, kind=inp.kind,
        eligible=not reasons, reasons=reasons, stale=stale, current_snapshot_hash=current,
        case_key=key, existing_case_id=existing, evidence=evidence,
    ).seal()


# ---------------------------------------------------------------------------------
# 5. get_disruption_context
# ---------------------------------------------------------------------------------

SCENARIO_EXISTS_SQL = text("SELECT 1 FROM synthetic_scenarios WHERE scenario_id = :scenario_id")

VISIBLE_EVENTS_SQL = text("""
SELECT e.event_id::text AS event_id, e.kind, e.carrier_code, e.seller_id, e.affected_states,
       e.starts_at, e.ends_at, e.summary
FROM disruption_events e
WHERE e.scenario_id = :scenario_id AND e.starts_at <= :as_of
ORDER BY e.starts_at, e.event_id
""")

ORDER_CONTEXT_SQL = text(f"""
SELECT o.order_id, o.purchased_at,
       CASE WHEN o.carrier_at <= :as_of THEN o.carrier_at END AS carrier_at_known,
       c.state AS customer_state,
       a.carrier_code, k.display_name AS carrier_name,
       (SELECT array_agg(DISTINCT i.seller_id ORDER BY i.seller_id) FROM order_items i
        WHERE i.batch_id = o.batch_id AND i.order_id = o.order_id) AS seller_ids
FROM orders o
JOIN customers c ON c.batch_id = o.batch_id AND c.customer_id = o.customer_id
LEFT JOIN carrier_assignments a
       ON a.scenario_id = :scenario_id AND a.batch_id = o.batch_id
      AND a.order_id = o.order_id AND a.assigned_at <= :as_of
LEFT JOIN carriers k ON k.scenario_id = a.scenario_id AND k.carrier_code = a.carrier_code
WHERE o.batch_id = :batch_id AND o.order_id = ANY(CAST(:order_ids AS text[]))
  AND o.purchased_at <= :as_of
  AND {VISIBLE_ORDER}
ORDER BY o.order_id
""")


class DisruptionContextInput(_In):
    target_type: TargetType
    target_id: Hex32
    scenario_id: ScenarioId | None


class Overlap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str
    scope: str
    matched_value: str
    order_interval: tuple[datetime, datetime]
    overlap: tuple[datetime, datetime]


class ContextEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    is_synthetic: Literal[True] = True
    kind: str
    carrier_code: str | None
    seller_id: str | None
    affected_states: list[str]
    starts_at: datetime
    ends_at_known: datetime | None  # masked when the event had not ended by as_of
    ongoing_at_as_of: bool
    summary: str
    overlaps: list[Overlap]


class DisruptionContext(_Out):
    tool: Literal["get_disruption_context"] = "get_disruption_context"
    scenario_id: str | None
    is_synthetic: bool
    target: Target
    orders_considered: list[str]
    carriers: dict[str, dict[str, str]]
    events: list[ContextEvent]
    note: str


def get_disruption_context(conn: Connection, principal: Principal,
                           inp: DisruptionContextInput) -> DisruptionContext:
    target = Target(target_type=inp.target_type, target_id=inp.target_id)
    base = {"batch_id": principal.batch_id, "as_of": inp.as_of, "target": target}
    if inp.scenario_id is None:
        # Real-only mode: no synthetic table is read.
        return DisruptionContext(**base, scenario_id=None, is_synthetic=False,
                                 orders_considered=[], carriers={}, events=[], evidence=[],
                                 note="Real data only: no synthetic scenario selected.").seal()
    _require_provisioned(principal)
    if conn.execute(SCENARIO_EXISTS_SQL, {"scenario_id": inp.scenario_id}).first() is None:
        raise ToolInputError("unknown scenario")
    if inp.target_type == "Order":
        get_order_snapshot(conn, principal, OrderSnapshotInput(order_id=inp.target_id,
                                                               as_of=inp.as_of))
        order_ids = [inp.target_id]
    else:
        scope = get_seller_exception_scope(conn, principal, SellerScopeInput(
            seller_id=inp.target_id, as_of=inp.as_of))
        order_ids = [o.order_id for o in scope.orders]
    params = _p(principal, scenario_id=inp.scenario_id, as_of=inp.as_of, order_ids=order_ids)
    ctx_rows = conn.execute(ORDER_CONTEXT_SQL, params).all()
    contexts = [OrderContext(order_id=r.order_id, purchased_at=r.purchased_at,
                             carrier_at_known=r.carrier_at_known, carrier_code=r.carrier_code,
                             seller_ids=tuple(r.seller_ids or ()),
                             customer_state=r.customer_state) for r in ctx_rows]
    carriers = {r.order_id: {"carrier_code": r.carrier_code, "display_name": r.carrier_name}
                for r in ctx_rows if r.carrier_code}
    events: list[ContextEvent] = []
    for e in conn.execute(VISIBLE_EVENTS_SQL, params):
        scope_ = EventScope(e.event_id, e.carrier_code, e.seller_id,
                            tuple(e.affected_states or ()), e.starts_at, e.ends_at)
        overlaps = []
        for ctx in contexts:
            basis = event_overlap(ctx, scope_, inp.as_of)
            if basis:
                overlaps.append(Overlap(
                    order_id=ctx.order_id, scope=basis.scope, matched_value=basis.matched_value,
                    order_interval=(basis.interval_start, basis.interval_end),
                    overlap=(basis.overlap_start, basis.overlap_end)))
        if overlaps:
            events.append(ContextEvent(
                event_id=e.event_id, kind=e.kind, carrier_code=e.carrier_code,
                seller_id=e.seller_id, affected_states=list(e.affected_states or []),
                starts_at=e.starts_at,
                ends_at_known=e.ends_at if e.ends_at <= inp.as_of else None,
                ongoing_at_as_of=e.ends_at > inp.as_of, summary=e.summary, overlaps=overlaps))
    b = principal.batch_id
    evidence = [ref_for("DisruptionEvent", f"{inp.scenario_id}/{e.event_id}", None,
                        "synthetic", synthetic=True) for e in events]
    evidence += [ref_for("Carrier", f"{inp.scenario_id}/{c['carrier_code']}", None,
                         "synthetic", synthetic=True)
                 for c in {v["carrier_code"]: v for v in carriers.values()}.values()]
    evidence += [ref_for("Order", ctx.order_id, b, "derived") for ctx in contexts]
    return DisruptionContext(
        **base, scenario_id=inp.scenario_id, is_synthetic=True,
        orders_considered=[c.order_id for c in contexts], carriers=carriers, events=events,
        evidence=_dedupe(evidence), note=CAUSAL_NOTE,
    ).seal()


# ---------------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------------

TOOLS = {
    "get_order_snapshot": (OrderSnapshotInput, get_order_snapshot),
    "find_late_orders": (FindLateOrdersInput, find_late_orders),
    "get_seller_exception_scope": (SellerScopeInput, get_seller_exception_scope),
    "check_case_eligibility": (EligibilityInput, check_case_eligibility),
    "get_disruption_context": (DisruptionContextInput, get_disruption_context),
}

QUERIES = {
    "order_snapshot": ORDER_SNAPSHOT_SQL,
    "order_lines": ORDER_LINES_SQL,
    "customer_visible_orders": CUSTOMER_VISIBLE_ORDERS_SQL,
    "late_queue_page": LATE_QUEUE_PAGE_SQL,
    "late_queue_aggregates": LATE_QUEUE_AGGREGATES_SQL,
    "seller": SELLER_SQL,
    "seller_scope_lines": SELLER_SCOPE_LINES_SQL,
    "seller_scope_aggregates": SELLER_SCOPE_AGGREGATES_SQL,
    "selected_orders": SELECTED_ORDERS_SQL,
    "existing_case": EXISTING_CASE_SQL,
    "scenario_exists": SCENARIO_EXISTS_SQL,
    "visible_events": VISIBLE_EVENTS_SQL,
    "order_context": ORDER_CONTEXT_SQL,
}


def run_tool(conn: Connection, principal: Principal, name: str, raw_input: dict):
    """Validate raw JSON input against the strict schema and run an allowlisted tool."""
    if name not in TOOLS:
        raise ToolInputError(f"unknown tool {name!r}")
    schema, fn = TOOLS[name]
    try:
        inp = schema.model_validate_json(json.dumps(raw_input))
    except ValidationError as exc:
        raise ToolInputError(f"invalid input for {name}: {exc.error_count()} errors") from None
    return fn(conn, principal, inp)
