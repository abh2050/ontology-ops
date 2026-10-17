import hashlib
import json
from datetime import date, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from ops.data.importer import FIXTURE_BATCH, run_import
from ops.data.manifest import manifest_hash
from ops.data.scenario import WINDOW_END, WINDOW_START, generate
from ops.queries.late_orders import late_open_order_ids, rank_days
from ops.settings import REPO_ROOT

pytestmark = pytest.mark.integration

FIXTURES = REPO_ROOT / "data" / "fixtures"
AS_OF = datetime(2018, 3, 15, 23, 59, 59)
LABELS = json.loads((FIXTURES / "labels.json").read_text())


@pytest.fixture(scope="module")
def fixture_batch(db):
    result = run_import(FIXTURES, FIXTURE_BATCH, download_date=date(2026, 10, 17))
    return result


def test_reimport_is_identical(db, fixture_batch):
    again = run_import(FIXTURES, FIXTURE_BATCH, download_date=date(2026, 10, 17))
    assert again.already_present
    strip = lambda m: {k: v for k, v in m.items() if k != "demo_as_of"}  # noqa: E731
    assert manifest_hash(strip(again.manifest)) == manifest_hash(strip(fixture_batch.manifest))
    on_disk = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest_hash(strip(on_disk)) == manifest_hash(strip(fixture_batch.manifest))


def test_counts_match_manifest(db, fixture_batch):
    with db("import").connect() as conn:
        for table, n in fixture_batch.manifest["loaded_rows"].items():
            assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE batch_id = :b"),
                                {"b": FIXTURE_BATCH}).scalar_one() == n
        quarantine = conn.execute(text(
            "SELECT reason_code, source_file, raw_row FROM quarantine WHERE batch_id = :b"),
            {"b": FIXTURE_BATCH}).all()
    assert sorted(q.reason_code for q in quarantine) == ["BROKEN_FK", "DUPLICATE_IDENTICAL"]
    assert all(isinstance(q.raw_row, dict) and q.raw_row for q in quarantine)


def test_half_up_money_persisted(db, fixture_batch):
    with db("import").connect() as conn:
        prices = conn.execute(text(
            "SELECT price_centavos FROM order_items WHERE batch_id = :b AND order_id = :o "
            "ORDER BY line_no"), {"b": FIXTURE_BATCH, "o": LABELS["same_seller_two_lines"]}
        ).scalars().all()
    assert prices == [1013, 10000]


def test_late_open_semantics_and_masking(db, fixture_batch):
    with db("import").connect() as conn:
        at = set(late_open_order_ids(conn, FIXTURE_BATCH, AS_OF))
        later = set(late_open_order_ids(conn, FIXTURE_BATCH, AS_OF + timedelta(days=3)))
    assert LABELS["delivered_after_as_of"] in at        # delivery after as_of is not known yet
    assert LABELS["delivered_after_as_of"] not in later
    assert LABELS["stale_snapshot_target"] in at and LABELS["stale_snapshot_target"] not in later
    assert LABELS["delivered_on_time"] not in at
    assert LABELS["not_late_00"] not in at
    assert LABELS["single_late_00"] in at
    assert LABELS["long_overdue"] not in at  # more than 30 days past the estimate


def test_overdue_cap_boundary(db, fixture_batch):
    with db("import").connect() as conn:
        estimated = conn.execute(text(
            "SELECT estimated_at FROM orders WHERE batch_id = :b AND order_id = :o"),
            {"b": FIXTURE_BATCH, "o": LABELS["long_overdue"]}).scalar_one()
        on_cap = estimated + timedelta(days=30, hours=23, minutes=59, seconds=59)
        past_cap = on_cap + timedelta(days=1)
        assert LABELS["long_overdue"] in late_open_order_ids(conn, FIXTURE_BATCH, on_cap)
        assert LABELS["long_overdue"] not in late_open_order_ids(conn, FIXTURE_BATCH, past_cap)


def test_rank_days_tie_breaks():
    days = [
        {"day": date(2018, 3, 2), "sellers_with_3_plus": 5, "late_open_orders": 10},
        {"day": date(2018, 3, 1), "sellers_with_3_plus": 5, "late_open_orders": 10},
        {"day": date(2018, 3, 3), "sellers_with_3_plus": 5, "late_open_orders": 11},
        {"day": date(2018, 3, 4), "sellers_with_3_plus": 6, "late_open_orders": 1},
    ]
    assert [d["day"].day for d in rank_days(days)] == [4, 3, 1, 2]


def _scenario_digest(conn, scenario_id: str) -> str:
    parts = []
    for sql in [
        "SELECT scenario_id, seed, generator_version, description, is_synthetic "
        "FROM synthetic_scenarios WHERE scenario_id = :s",
        "SELECT * FROM carriers WHERE scenario_id = :s ORDER BY carrier_code",
        "SELECT * FROM carrier_assignments WHERE scenario_id = :s ORDER BY batch_id, order_id",
        "SELECT * FROM disruption_events WHERE scenario_id = :s ORDER BY event_id",
    ]:
        parts.append(repr(conn.execute(text(sql), {"s": scenario_id}).all()))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


@pytest.fixture
def scenario_cleanup(db):
    created: list[str] = []
    yield created
    with db("import").begin() as conn:
        for s in created:
            conn.execute(text("DELETE FROM synthetic_scenarios WHERE scenario_id = :s"), {"s": s})


def test_scenario_same_seed_identical_rows(db, fixture_batch, scenario_cleanup):
    scenario_cleanup += ["test-det-a", "test-det-b"]
    generate(seed=42, scenario_id="test-det-a", anchor_batch=FIXTURE_BATCH)
    with db("import").connect() as conn:
        first = _scenario_digest(conn, "test-det-a")
    generate(seed=42, scenario_id="test-det-a", anchor_batch=FIXTURE_BATCH)
    generate(seed=7, scenario_id="test-det-b", anchor_batch=FIXTURE_BATCH)
    with db("import").connect() as conn:
        assert _scenario_digest(conn, "test-det-a") == first
        a = conn.execute(text("SELECT order_id, carrier_code FROM carrier_assignments "
                              "WHERE scenario_id = 'test-det-a' ORDER BY order_id")).all()
        b = conn.execute(text("SELECT order_id, carrier_code FROM carrier_assignments "
                              "WHERE scenario_id = 'test-det-b' ORDER BY order_id")).all()
    assert [r.order_id for r in a] == [r.order_id for r in b]
    assert a != b  # a different seed reassigns carriers


def test_scenario_rules(db, fixture_batch, scenario_cleanup):
    scenario_cleanup.append("test-rules")
    generate(seed=42, scenario_id="test-rules", anchor_batch=FIXTURE_BATCH)
    record = json.loads((REPO_ROOT / "data" / "scenarios" / "test-rules.json").read_text())
    (REPO_ROOT / "data" / "scenarios" / "test-rules.json").unlink()
    ts = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S")  # noqa: E731
    events = record["events"]
    assert 6 <= len(events) <= 8
    for e in events:
        assert WINDOW_START <= ts(e["starts_at"]) <= ts(e["ends_at"]) <= WINDOW_END
    overlapping = [e for e in events if ts(e["starts_at"]) <= AS_OF <= ts(e["ends_at"])]
    assert len(overlapping) >= 2
    roles = {e["role"] for e in events}
    assert {"cause_unknown", "temporal_decoy"} <= roles

    with db("import").connect() as conn:
        # no carrier for orders without a carrier handoff; assigned_at = carrier_at
        no_carrier = conn.execute(text(
            "SELECT count(*) FROM carrier_assignments WHERE scenario_id = 'test-rules' "
            "AND order_id = :o"), {"o": LABELS["no_carrier_late"]}).scalar_one()
        mismatched = conn.execute(text(
            "SELECT count(*) FROM carrier_assignments a JOIN orders o "
            "ON o.batch_id = a.batch_id AND o.order_id = a.order_id "
            "WHERE a.scenario_id = 'test-rules' AND a.assigned_at <> o.carrier_at")).scalar_one()
        decoy = next(e for e in events if e["role"] == "temporal_decoy")
        starts = conn.execute(text(
            "SELECT DISTINCT o.order_id, CASE WHEN o.carrier_at <= :t THEN o.carrier_at "
            "ELSE o.purchased_at END AS start FROM orders o JOIN order_items i "
            "ON i.batch_id = o.batch_id AND i.order_id = o.order_id "
            "WHERE o.batch_id = :b AND i.seller_id = :s AND o.purchased_at <= :t "
            "AND o.estimated_at::date < CAST(:t AS timestamp)::date "
            "AND (o.delivered_at IS NULL OR o.delivered_at > :t)"),
            {"t": AS_OF, "b": FIXTURE_BATCH, "s": decoy["seller_id"]}).all()
        unknown = next(e for e in events if e["role"] == "cause_unknown")
        backlog = next(e for e in events if e["kind"] == "carrier_backlog")
        unknown_carriers = conn.execute(text(
            "SELECT DISTINCT a.carrier_code FROM carrier_assignments a JOIN order_items i "
            "ON i.batch_id = a.batch_id AND i.order_id = a.order_id "
            "JOIN orders o ON o.batch_id = a.batch_id AND o.order_id = a.order_id "
            "WHERE a.scenario_id = 'test-rules' AND i.seller_id = :s AND o.carrier_at <= :t "
            "AND o.estimated_at::date < CAST(:t AS timestamp)::date "
            "AND (o.delivered_at IS NULL OR o.delivered_at > :t)"),
            {"s": unknown["seller_id"], "t": AS_OF}).scalars().all()
    assert no_carrier == 0 and mismatched == 0
    assert len(starts) >= 3 and all(ts(decoy["ends_at"]) < s.start for s in starts)
    assert backlog["carrier_code"] not in unknown_carriers
    assert all(e["summary"].startswith("Synthetic scenario") for e in events)
    banned = ("caused", "due to", "because of", "resulted from", "responsible for")
    assert not any(b in e["summary"].lower() for e in events for b in banned)


def test_synthetic_flag_cannot_be_false(db, fixture_batch, scenario_cleanup):
    scenario_cleanup.append("test-flag")
    with pytest.raises(sa.exc.IntegrityError), db("import").begin() as conn:
        conn.execute(text("INSERT INTO synthetic_scenarios (scenario_id, seed, "
                          "generator_version, description, is_synthetic) "
                          "VALUES ('test-flag', 1, 'x', 'x', false)"))


@pytest.mark.parametrize(
    ("role", "sql"),
    [
        ("api", "INSERT INTO orders (batch_id, order_id, customer_id, purchased_at, "
                "estimated_at, provenance) VALUES ('x','x','x', now(), now(), 'olist')"),
        ("api", "DELETE FROM carriers"),
        ("api", "DELETE FROM audit_events"),
        ("api", "UPDATE users SET role = 'reviewer'"),
        ("api", "INSERT INTO seller_grants VALUES ('a','b','c')"),
        ("worker", "INSERT INTO cases (proposal_id, case_key, owner_subject, case_payload) "
                   "VALUES (gen_random_uuid(), 'k', 's', '{}')"),
        ("worker", "UPDATE proposals SET state = 'executed'"),
        ("worker", "INSERT INTO disruption_events (event_id, scenario_id, kind, starts_at, "
                   "ends_at, summary) VALUES (gen_random_uuid(), 'x', 'system_outage', now(), "
                   "now(), 'x')"),
        ("import", "INSERT INTO cases (proposal_id, case_key, owner_subject, case_payload) "
                   "VALUES (gen_random_uuid(), 'k', 's', '{}')"),
        ("import", "DELETE FROM orders"),
    ],
)
def test_role_permission_denied(db, role, sql):
    with pytest.raises(sa.exc.ProgrammingError, match="permission denied"), \
            db(role).begin() as conn:
        conn.execute(text(sql))


@pytest.mark.parametrize("role", ["import", "api", "worker", "admin"])
def test_no_superuser(db, role):
    with db(role).connect() as conn:
        assert conn.execute(text(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar_one() is False


@pytest.mark.parametrize("role", ["api", "worker"])
def test_runtime_roles_read_source_and_synthetic(db, fixture_batch, role):
    with db(role).connect() as conn:
        conn.execute(text("SELECT count(*) FROM orders"))
        conn.execute(text("SELECT count(*) FROM disruption_events"))
