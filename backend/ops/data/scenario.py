"""Deterministic synthetic scenario overlay (spec section 7).

Real Olist rows never change. Every row written here has is_synthetic = true.
Carrier rule: CARRIER_{A..E}[sha256(f"{seller_state}|{customer_state}|{seed}") mod 5],
using the seller_state of the order line with the lowest line_no; assigned_at is the
order's carrier_at, and orders without carrier_at (or without lines) get no carrier.
Events are placed relative to the anchor batch's demo as_of from authored templates.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Connection, text

from ops.data.as_of import AsOfError, demo_as_of
from ops.db import engine
from ops.queries.late_orders import DEMO_WINDOW, LATE_OPEN_PREDICATE
from ops.settings import REPO_ROOT

GENERATOR_VERSION = "scenario-gen-1.0.0"
_EVENT_NS = uuid.UUID("0b7f3c1e-2a4d-4e59-8c1a-5d2e6f7a8b90")
WINDOW_START = datetime.combine(DEMO_WINDOW[0], datetime.min.time())
WINDOW_END = datetime.combine(DEMO_WINDOW[1], datetime.max.time()).replace(microsecond=0)

# Obviously fictional names that do not resemble real companies.
CARRIERS = [
    ("CARRIER_A", "Zephyr Otter Fictional Freight"),
    ("CARRIER_B", "Quartz Heron Demo Haulage"),
    ("CARRIER_C", "Mossbank Fictional Couriers"),
    ("CARRIER_D", "Lantern Moth Example Logistics"),
    ("CARRIER_E", "Saffron Kite Sample Transport"),
]


class ScenarioError(Exception):
    pass


def carrier_for(seller_state: str, customer_state: str, seed: int) -> str:
    digest = hashlib.sha256(f"{seller_state}|{customer_state}|{seed}".encode()).hexdigest()
    return CARRIERS[int(digest, 16) % len(CARRIERS)][0]


@dataclass(frozen=True)
class LateOrder:
    order_id: str
    customer_state: str
    sellers: tuple[str, ...]
    carrier: str | None
    interval_start: datetime


ASSIGNMENT_SOURCE_SQL = text("""
SELECT o.batch_id, o.order_id, o.carrier_at, c.state AS customer_state, s.state AS seller_state
FROM orders o
JOIN customers c ON c.batch_id = o.batch_id AND c.customer_id = o.customer_id
JOIN LATERAL (
    SELECT i.seller_id FROM order_items i
    WHERE i.batch_id = o.batch_id AND i.order_id = o.order_id
    ORDER BY i.line_no LIMIT 1
) first_line ON true
JOIN sellers s ON s.batch_id = o.batch_id AND s.seller_id = first_line.seller_id
WHERE o.carrier_at IS NOT NULL
ORDER BY o.batch_id, o.order_id
""")

ANCHOR_LATE_SQL = text(f"""
SELECT o.order_id, c.state AS customer_state, o.purchased_at,
       CASE WHEN o.carrier_at <= :as_of THEN o.carrier_at END AS carrier_known_at,
       array_agg(DISTINCT i.seller_id ORDER BY i.seller_id) AS sellers
FROM orders o
JOIN customers c ON c.batch_id = o.batch_id AND c.customer_id = o.customer_id
JOIN order_items i ON i.batch_id = o.batch_id AND i.order_id = o.order_id
WHERE o.batch_id = :batch_id AND {LATE_OPEN_PREDICATE}
GROUP BY o.order_id, c.state, o.purchased_at, o.carrier_at
ORDER BY o.order_id
""")


def _clamp(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start = max(WINDOW_START, min(start, WINDOW_END))
    end = max(start, min(end, WINDOW_END))
    return start, end


def _top(counter: Counter, exclude: set | None = None):
    ranked = sorted(
        ((k, n) for k, n in counter.items() if k not in (exclude or set())),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return ranked[0][0] if ranked else None


def plan_events(scenario_id: str, seed: int, as_of: datetime, late: list[LateOrder]) -> list[dict]:
    """Authored event templates bound to the anchor data. Pure and deterministic."""
    if not late:
        raise ScenarioError("anchor batch has no late open orders at its demo as_of")
    by_carrier = Counter(o.carrier for o in late if o.carrier)
    by_state = Counter(o.customer_state for o in late)
    seller_orders: dict[str, list[LateOrder]] = defaultdict(list)
    for o in late:
        for s in o.sellers:
            seller_orders[s].append(o)
    groups = sorted(
        ((s, os) for s, os in seller_orders.items() if len(os) >= 3),
        key=lambda kv: (-len(kv[1]), kv[0]),
    )
    if len(groups) < 2:
        raise ScenarioError("anchor batch needs at least two sellers with >= 3 late open orders")

    c1 = _top(by_carrier) or CARRIERS[0][0]
    s1 = _top(by_state)
    s2 = _top(by_state, {s1}) or s1

    def no_pattern(orders: list[LateOrder], strict: bool) -> bool:
        if any(o.carrier == c1 for o in orders):
            return False
        return not strict or not any(o.customer_state == s1 for o in orders)

    unknown = next((g for g in groups if no_pattern(g[1], True)), None) \
        or next((g for g in groups if no_pattern(g[1], False)), None) or groups[0]
    decoy = next(g for g in groups if g[0] != unknown[0])
    unknown_start = min(o.interval_start for o in unknown[1])
    decoy_start = min(o.interval_start for o in decoy[1])

    day = timedelta(days=1)
    templates = [
        ("carrier_backlog", "overlaps_as_of", {"carrier_code": c1},
         as_of - 10 * day, as_of + 5 * day,
         f"Synthetic scenario: fictional backlog reported at {c1}."),
        ("regional_weather", "overlaps_as_of", {"affected_states": [s1]},
         as_of - 6 * day, as_of + 2 * day,
         f"Synthetic scenario: fictional storm advisory for customer state {s1}."),
        ("seller_stockout", "cause_unknown", {"seller_id": unknown[0]},
         unknown_start, max(unknown_start + 2 * day, as_of - 3 * day),
         "Synthetic scenario: fictional stock shortage note for one seller. Its late orders "
         "share no backlogged carrier; the data cannot establish a cause."),
        ("system_outage", "temporal_decoy", {"seller_id": decoy[0]},
         decoy_start - 12 * day, decoy_start - 2 * day,
         "Synthetic scenario: fictional order system outage that ended before this "
         "seller's late orders entered transit."),
        ("regional_weather", "future_masked", {"affected_states": [s1]},
         as_of + 3 * day, as_of + 9 * day,
         f"Synthetic scenario: fictional weather alert for {s1} starting after as_of."),
        ("system_outage", "early_window", {"affected_states": ["SP"]},
         WINDOW_START + 35 * day, WINDOW_START + 37 * day,
         "Synthetic scenario: fictional platform outage early in the window."),
        ("regional_weather", "stale_regional_decoy", {"affected_states": [s2]},
         as_of - 45 * day, as_of - 40 * day,
         f"Synthetic scenario: fictional rain advisory for {s2}, ended weeks before as_of."),
    ]
    events = []
    for n, (kind, role, scope, start, end, summary) in enumerate(templates, start=1):
        start, end = _clamp(start, end)
        if role == "future_masked" and start <= as_of:
            continue  # no room inside the window after as_of
        events.append({
            "event_id": str(uuid.uuid5(_EVENT_NS, f"{scenario_id}|{seed}|E{n}")),
            "scenario_id": scenario_id,
            "kind": kind,
            "role": role,
            "carrier_code": scope.get("carrier_code"),
            "seller_id": scope.get("seller_id"),
            "affected_states": scope.get("affected_states", []),
            "starts_at": start,
            "ends_at": end,
            "summary": summary,
        })
    return events


def _anchor_batch(conn: Connection) -> str:
    row = conn.execute(text(
        "SELECT batch_id FROM source_batches WHERE manifest->'demo_as_of' IS NOT NULL "
        "AND jsonb_typeof(manifest->'demo_as_of') = 'object' "
        "ORDER BY (manifest->>'provenance' = 'olist') DESC, imported_at DESC LIMIT 1"
    )).one_or_none()
    if row is None:
        raise ScenarioError("no batch has a demo as_of; run ops data pick-as-of first")
    return row.batch_id


def generate(seed: int, scenario_id: str, anchor_batch: str | None = None) -> str:
    with engine("import").begin() as conn:
        anchor = anchor_batch or _anchor_batch(conn)
        try:
            as_of = demo_as_of(conn, anchor)
        except AsOfError as exc:
            raise ScenarioError(str(exc)) from exc

        assignments = [
            (scenario_id, r.batch_id, r.order_id,
             carrier_for(r.seller_state, r.customer_state, seed), r.carrier_at)
            for r in conn.execute(ASSIGNMENT_SOURCE_SQL)
        ]
        anchor_carrier = {a[2]: a[3] for a in assignments if a[1] == anchor}
        late = [
            LateOrder(
                order_id=r.order_id,
                customer_state=r.customer_state,
                sellers=tuple(r.sellers),
                carrier=anchor_carrier.get(r.order_id) if r.carrier_known_at else None,
                interval_start=r.carrier_known_at or r.purchased_at,
            )
            for r in conn.execute(ANCHOR_LATE_SQL, {"batch_id": anchor, "as_of": as_of})
        ]
        events = plan_events(scenario_id, seed, as_of, late)

        conn.execute(text("DELETE FROM synthetic_scenarios WHERE scenario_id = :s"),
                     {"s": scenario_id})
        conn.execute(
            text("INSERT INTO synthetic_scenarios (scenario_id, seed, generator_version, "
                 "description) VALUES (:s, :seed, :v, :d)"),
            {"s": scenario_id, "seed": seed, "v": GENERATOR_VERSION,
             "d": f"Authored synthetic overlay anchored on batch {anchor} at as_of "
                  f"{as_of:%Y-%m-%d %H:%M:%S} (dataset local). Fictional carriers and events."},
        )
        conn.execute(
            text("INSERT INTO carriers (scenario_id, carrier_code, display_name) "
                 "VALUES (:s, :c, :n)"),
            [{"s": scenario_id, "c": c, "n": n} for c, n in CARRIERS],
        )
        cur_conn = conn.connection.driver_connection
        with cur_conn.cursor() as cur:
            for start in range(0, len(assignments), 1000):
                with cur.copy("COPY carrier_assignments (scenario_id, batch_id, order_id, "
                              "carrier_code, assigned_at) FROM STDIN") as copy:
                    for row in assignments[start : start + 1000]:
                        copy.write_row(row)
        conn.execute(
            text("INSERT INTO disruption_events (event_id, scenario_id, kind, carrier_code, "
                 "seller_id, affected_states, starts_at, ends_at, summary) VALUES "
                 "(CAST(:event_id AS uuid), :scenario_id, :kind, :carrier_code, :seller_id, "
                 ":affected_states, :starts_at, :ends_at, :summary)"),
            [{k: v for k, v in e.items() if k != "role"} for e in events],
        )

    record = {
        "scenario_id": scenario_id,
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "anchor_batch": anchor,
        "anchor_as_of": f"{as_of:%Y-%m-%d %H:%M:%S}",
        "is_synthetic": True,
        "carriers": dict(CARRIERS),
        "assignment_counts": dict(sorted(Counter(a[3] for a in assignments).items())),
        "events": [
            {**e, "starts_at": f"{e['starts_at']:%Y-%m-%d %H:%M:%S}",
             "ends_at": f"{e['ends_at']:%Y-%m-%d %H:%M:%S}"}
            for e in events
        ],
    }
    out = REPO_ROOT / "data" / "scenarios" / f"{scenario_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n")
    return (f"scenario {scenario_id} (seed {seed}) anchored on {anchor} at "
            f"{as_of:%Y-%m-%d %H:%M:%S}: {len(CARRIERS)} carriers, {len(assignments)} "
            f"assignments, {len(events)} events -> {out.relative_to(REPO_ROOT)}")
