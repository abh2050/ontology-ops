"""Named derived functions of operational-commerce-v1 that run in Python.

late_open_order and seller_associated_late_orders run in SQL (late_orders.py,
tools.py). Changing any function here requires a new ontology version and a
regression test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ops.queries.late_orders import MAX_OVERDUE_DAYS


def mask(ts: datetime | None, as_of: datetime) -> datetime | None:
    """Reveal an event timestamp only when it occurred at or before as_of."""
    return ts if ts is not None and ts <= as_of else None


DeliveryState = Literal["placed", "approved", "with_carrier", "delivered"]


def known_delivery_state(approved: datetime | None, carrier: datetime | None,
                         delivered: datetime | None, as_of: datetime) -> DeliveryState:
    """Input timestamps may be unmasked; the result only uses events known at as_of."""
    if mask(delivered, as_of):
        return "delivered"
    if mask(carrier, as_of):
        return "with_carrier"
    if mask(approved, as_of):
        return "approved"
    return "placed"


def days_overdue(estimated_at: datetime, as_of: datetime) -> int:
    return (as_of.date() - estimated_at.date()).days


def late_open(purchased: datetime, estimated: datetime, delivered: datetime | None,
              as_of: datetime) -> bool:
    """Python mirror of the SQL late_open_order predicate, used in tests and checks."""
    overdue = days_overdue(estimated, as_of)
    return (purchased <= as_of and 1 <= overdue <= MAX_OVERDUE_DAYS
            and mask(delivered, as_of) is None)


@dataclass(frozen=True)
class OrderContext:
    order_id: str
    purchased_at: datetime
    carrier_at_known: datetime | None   # already masked at as_of
    carrier_code: str | None            # only when the assignment is known at as_of
    seller_ids: tuple[str, ...]
    customer_state: str


@dataclass(frozen=True)
class EventScope:
    event_id: str
    carrier_code: str | None
    seller_id: str | None
    affected_states: tuple[str, ...]
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class OverlapBasis:
    scope: Literal["carrier", "seller", "customer_state"]
    matched_value: str
    interval_start: datetime
    interval_end: datetime
    overlap_start: datetime
    overlap_end: datetime


def event_overlap(order: OrderContext, event: EventScope, as_of: datetime) -> OverlapBasis | None:
    """True (with its basis) only when scope matches AND the windows intersect.

    The order interval starts at carrier_at when known at as_of, otherwise at
    purchased_at, and ends at as_of. Events starting after as_of are invisible.
    """
    if event.starts_at > as_of:
        return None
    if event.carrier_code and order.carrier_code == event.carrier_code:
        scope, value = "carrier", event.carrier_code
    elif event.seller_id and event.seller_id in order.seller_ids:
        scope, value = "seller", event.seller_id
    elif order.customer_state in event.affected_states:
        scope, value = "customer_state", order.customer_state
    else:
        return None
    start = order.carrier_at_known or order.purchased_at
    end = as_of
    event_end = min(event.ends_at, as_of)
    lo, hi = max(start, event.starts_at), min(end, event_end)
    if lo > hi:
        return None
    return OverlapBasis(scope, value, start, end, lo, hi)
