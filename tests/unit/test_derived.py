from datetime import datetime, timedelta

from ops.queries.derived import (
    EventScope,
    OrderContext,
    event_overlap,
    known_delivery_state,
    late_open,
    mask,
)

AS_OF = datetime(2018, 3, 30, 23, 59, 59)
D = timedelta(days=1)


def order(carrier_at=AS_OF - 10 * D, carrier="CARRIER_B", sellers=("s1",), state="SP"):
    return OrderContext("o1", AS_OF - 20 * D, carrier_at, carrier, sellers, state)


def ev(start, end, carrier=None, seller=None, states=()):
    return EventScope("e1", carrier, seller, tuple(states), start, end)


def test_carrier_match_with_overlap():
    basis = event_overlap(order(), ev(AS_OF - 5 * D, AS_OF + 5 * D, carrier="CARRIER_B"), AS_OF)
    assert basis.scope == "carrier" and basis.overlap_end == AS_OF


def test_seller_and_state_match():
    assert event_overlap(order(), ev(AS_OF - 3 * D, AS_OF, seller="s1"), AS_OF).scope == "seller"
    assert event_overlap(order(), ev(AS_OF - 3 * D, AS_OF, states=["SP"]),
                         AS_OF).scope == "customer_state"


def test_scope_mismatch_is_false():
    assert event_overlap(order(), ev(AS_OF - 3 * D, AS_OF, carrier="CARRIER_A"), AS_OF) is None
    assert event_overlap(order(), ev(AS_OF - 3 * D, AS_OF, states=["RJ"]), AS_OF) is None


def test_temporal_decoy_before_interval_is_false():
    # interval starts at carrier_at (AS_OF - 10d); event ended two days before that
    decoy = ev(AS_OF - 20 * D, AS_OF - 12 * D, carrier="CARRIER_B")
    assert event_overlap(order(), decoy, AS_OF) is None


def test_interval_starts_at_purchase_when_carrier_unknown():
    no_carrier = order(carrier_at=None, carrier=None)
    early = ev(AS_OF - 18 * D, AS_OF - 15 * D, seller="s1")
    assert event_overlap(no_carrier, early, AS_OF).interval_start == AS_OF - 20 * D
    assert event_overlap(order(), early, AS_OF) is None  # with carrier_at, it no longer overlaps


def test_future_event_invisible():
    assert event_overlap(order(), ev(AS_OF + D, AS_OF + 5 * D, carrier="CARRIER_B"), AS_OF) is None


def test_masking_helpers():
    assert mask(AS_OF + D, AS_OF) is None and mask(AS_OF, AS_OF) == AS_OF
    assert known_delivery_state(AS_OF - D, AS_OF - D, AS_OF + D, AS_OF) == "with_carrier"
    assert known_delivery_state(AS_OF - D, None, None, AS_OF) == "approved"


def test_late_open_cap_and_masking():
    est = datetime(2018, 3, 1)
    assert late_open(est - 10 * D, est, None, datetime(2018, 3, 31, 23, 59, 59))  # 30 days
    assert not late_open(est - 10 * D, est, None, datetime(2018, 4, 1, 23, 59, 59))  # 31
    assert not late_open(est - 10 * D, est, None, datetime(2018, 3, 1, 23, 59, 59))  # 0 days
    assert late_open(est - 10 * D, est, datetime(2018, 4, 2), datetime(2018, 3, 10))
