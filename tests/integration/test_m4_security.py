"""M4: database role permissions (spec 11.6) and seeded grants (spec 11.3), on PostgreSQL."""

import math
from datetime import datetime

import pytest
from sqlalchemy import text

from ops.data.users import seed_users

pytestmark = pytest.mark.integration

SOURCE = ["source_batches", "sellers", "customers", "products", "orders", "order_items"]
SYNTHETIC = ["synthetic_scenarios", "carriers", "carrier_assignments", "disruption_events"]
IDENTITY = ["users", "seller_grants"]
APP = ["jobs", "outbox", "proposals", "cases", "internal_drafts", "audit_events",
       "usage_days", "eval_runs", "model_calls"]
ALL = SOURCE + ["quarantine"] + SYNTHETIC + IDENTITY + APP
OPS = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"]


def expected() -> dict[tuple[str, str], set[str]]:
    """(role, table) -> table-level privileges that must be held; everything else denied."""
    e: dict[tuple[str, str], set[str]] = {}
    for t in SOURCE + ["quarantine"]:
        e[("ops_import", t)] = {"SELECT", "INSERT"}
    for t in SYNTHETIC:
        e[("ops_import", t)] = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    for t in SOURCE + SYNTHETIC + IDENTITY + APP:
        e[("ops_api", t)] = {"SELECT"}
    for t in ("jobs", "outbox", "proposals", "cases", "internal_drafts", "audit_events"):
        e[("ops_api", t)] = {"SELECT", "INSERT"}
    worker_reads = SOURCE + SYNTHETIC + IDENTITY + ["jobs", "outbox", "model_calls",
                                                    "usage_days", "eval_runs", "cases",
                                                    "proposals", "internal_drafts"]
    for t in worker_reads:
        e[("ops_worker", t)] = {"SELECT"}
    e[("ops_worker", "model_calls")] = {"SELECT", "INSERT", "UPDATE"}
    e[("ops_worker", "usage_days")] = {"SELECT", "INSERT", "UPDATE"}
    e[("ops_worker", "eval_runs")] = {"SELECT", "INSERT"}
    return e


COLUMN_UPDATES = {
    ("ops_import", "source_batches"): {"manifest"},
    ("ops_api", "proposals"): {"state", "revision", "reviewed_by", "review_reason"},
    ("ops_worker", "jobs"): {"state", "checkpoint", "result", "evidence_hash", "lease_token",
                             "lease_until", "revision"},
    ("ops_worker", "outbox"): {"sent_at"},
    ("ops_worker", "eval_runs"): {"admitted_calls"},
}


@pytest.mark.parametrize("role", ["ops_import", "ops_api", "ops_worker"])
def test_table_privileges_match_policy(db, role):
    exp = expected()
    mismatches = []
    with db("admin").connect() as c:
        for table in ALL:
            want = exp.get((role, table), set())
            for op in OPS:
                has = c.execute(text("SELECT has_table_privilege(:r, :t, :p)"),
                                {"r": role, "t": table, "p": op}).scalar_one()
                if has != (op in want):
                    mismatches.append((table, op, has))
    assert mismatches == []


@pytest.mark.parametrize("role", ["ops_import", "ops_api", "ops_worker"])
def test_column_update_privileges_match_policy(db, role):
    mismatches = []
    with db("admin").connect() as c:
        for table in ALL:
            table_level = c.execute(text("SELECT has_table_privilege(:r, :t, 'UPDATE')"),
                                    {"r": role, "t": table}).scalar_one()
            cols = c.execute(text("SELECT column_name FROM information_schema.columns "
                                  "WHERE table_schema = 'public' AND table_name = :t"),
                             {"t": table}).scalars().all()
            allowed = COLUMN_UPDATES.get((role, table), set())
            for col in cols:
                has = c.execute(text("SELECT has_column_privilege(:r, :t, :c, 'UPDATE')"),
                                {"r": role, "t": table, "c": col}).scalar_one()
                if has != (table_level or col in allowed):
                    mismatches.append((table, col, has))
    assert mismatches == []


@pytest.mark.parametrize("role", ["ops_import", "ops_api", "ops_worker"])
def test_runtime_roles_cannot_touch_identity_or_audit_history(db, role):
    with db("admin").connect() as c:
        for table in IDENTITY:
            for op in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not c.execute(text("SELECT has_table_privilege(:r, :t, :p)"),
                                     {"r": role, "t": table, "p": op}).scalar_one()
        for op in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not c.execute(text("SELECT has_table_privilege(:r, 'audit_events', :p)"),
                                 {"r": role, "p": op}).scalar_one()
        attrs = c.execute(text("SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
                               "FROM pg_roles WHERE rolname = :r"), {"r": role}).one()
        assert not any(attrs)


def test_worker_cannot_approve_or_create_cases(db):
    import sqlalchemy as sa

    for sql in ("UPDATE proposals SET state = 'executed'",
                "INSERT INTO cases (proposal_id, case_key, owner_subject, case_payload) "
                "VALUES (gen_random_uuid(), 'k', 'reviewer', '{}')",
                "INSERT INTO internal_drafts (proposal_id, body) VALUES (gen_random_uuid(), '{}')",
                "INSERT INTO audit_events (actor, kind, object_id) VALUES ('w', 'x', 'y')"):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"), \
                db("worker").begin() as c:
            c.execute(text(sql))


def test_only_import_role_writes_synthetic_tables(db):
    import sqlalchemy as sa

    for role in ("api", "worker"):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"), \
                db(role).begin() as c:
            c.execute(text("UPDATE carrier_assignments SET carrier_code = 'CARRIER_A'"))


# ---- seeded grants -------------------------------------------------------------------


INDEPENDENT_RANK_SQL = text("""
WITH late AS (
  SELECT o.order_id FROM orders o
  WHERE o.batch_id = :b AND o.purchased_at <= :t
    AND (:t)::date - o.estimated_at::date BETWEEN 1 AND 30
    AND (o.delivered_at IS NULL OR o.delivered_at > :t)
)
SELECT i.seller_id, count(DISTINCT i.order_id) AS n
FROM order_items i JOIN late USING (order_id)
WHERE i.batch_id = :b
GROUP BY i.seller_id
""")


def test_seeded_grants_match_spec(db):
    seed_users("local")
    with db("admin").connect() as c:
        users = dict(c.execute(text("SELECT subject, role FROM users WHERE subject IN "
                                    "('operator_a','operator_b','reviewer','viewer') "
                                    "AND active")).all())
        assert users == {"operator_a": "operator", "operator_b": "operator",
                         "reviewer": "reviewer", "viewer": "viewer"}
        batch = c.execute(text("SELECT batch_id, manifest->'demo_as_of'->>'as_of' FROM "
                               "source_batches WHERE manifest->>'provenance' = 'olist'")
                          ).one_or_none()
        if batch is None:
            pytest.skip("Olist batch not imported")
        b, as_of = batch[0], datetime.strptime(batch[1], "%Y-%m-%d %H:%M:%S")
        ranked = sorted(c.execute(INDEPENDENT_RANK_SQL, {"b": b, "t": as_of}).all(),
                        key=lambda r: (-r.n, r.seller_id))
        top = {r.seller_id for r in ranked[: math.ceil(len(ranked) / 2)]}
        everyone = set(c.execute(text("SELECT seller_id FROM sellers WHERE batch_id = :b"),
                                 {"b": b}).scalars())

        def grants(subject):
            return set(c.execute(text("SELECT seller_id FROM seller_grants WHERE subject = :s "
                                      "AND batch_id = :b"), {"s": subject, "b": b}).scalars())

        assert grants("operator_a") == top
        assert grants("operator_b") == everyone - top
        assert grants("reviewer") == everyone
        assert grants("viewer") == set()
        assert len(ranked) % 2 == 0 or len(top) == len(ranked) // 2 + 1  # odd middle to A


def test_fixture_multi_seller_order_spans_both_operators(db):
    seed_users("local")
    with db("admin").connect() as c:
        spanning = c.execute(text("""
            SELECT count(*) FROM (
              SELECT i.order_id FROM order_items i
              LEFT JOIN seller_grants a ON a.subject = 'operator_a' AND a.batch_id = i.batch_id
                   AND a.seller_id = i.seller_id
              LEFT JOIN seller_grants b ON b.subject = 'operator_b' AND b.batch_id = i.batch_id
                   AND b.seller_id = i.seller_id
              WHERE i.batch_id = 'fixtures-v1'
              GROUP BY i.order_id
              HAVING bool_or(a.seller_id IS NOT NULL) AND bool_or(b.seller_id IS NOT NULL)
            ) x""")).scalar_one()
    assert spanning >= 1
