"""M3: outbox, relay, consumer, leases, checkpoints, paid call admission, failure handling,
and the deterministic validator. Fixture queue and fixture provider only; no paid calls."""

import json
import uuid
from datetime import date, datetime

import pytest
from botocore.exceptions import ReadTimeoutError
from sqlalchemy import text

from ops.data.users import seed_users
from ops.jobs import checkpoints as C
from ops.jobs.breaker import CircuitBreaker
from ops.jobs.consumer import Worker, WorkerDeps, process_job
from ops.jobs.outbox import JobRequest, SubmitError, relay_once, submit_job
from ops.jobs.queues import FixtureQueue
from ops.jobs.recovery import mark_failed
from ops.providers.fixture import FixtureProvider
from ops.queries.scope import load_principal
from ops.settings import REPO_ROOT

pytestmark = pytest.mark.integration

LABELS = json.loads((REPO_ROOT / "data" / "fixtures" / "labels.json").read_text())
BATCH = "fixtures-v1"
AS_OF = datetime(2018, 3, 15, 23, 59, 59)
TEST_DAY = date(2099, 1, 1)


class Crash(Exception):
    """Simulated worker process death."""


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(scope="module", autouse=True)
def seeded(db):
    seed_users("local")


@pytest.fixture(autouse=True)
def clean_jobs(db):
    with db("admin").begin() as c:
        c.execute(text("DELETE FROM usage_days WHERE day = :d"), {"d": TEST_DAY})
        # isolate tests: older unsent outbox rows belong to other tests' jobs
        c.execute(text("UPDATE outbox SET sent_at = now() WHERE sent_at IS NULL"))
    yield
    with db("admin").begin() as c:
        c.execute(text("DELETE FROM model_calls WHERE admitted_day = :d"), {"d": TEST_DAY})
        c.execute(text("DELETE FROM usage_days WHERE day = :d"), {"d": TEST_DAY})


def submit(db, subject="operator_a", target=("Seller", "seller_a01"), scenario=None, key=None,
           **kw):
    ttype, label = target
    req = JobRequest(target_type=ttype, target_id=LABELS[label], as_of=AS_OF,
                     scenario_id=scenario, **kw)
    with db("api").begin() as conn:
        p = load_principal(conn, subject, BATCH)
        return submit_job(conn, p, req, key or str(uuid.uuid4()))


def deps(db, provider=None, clock=None, **kw):
    clock = clock or Clock()
    return WorkerDeps(engine=db("worker"), provider=provider or FixtureProvider(),
                      breaker=CircuitBreaker(clock=clock), clock=clock, sleep=lambda s: None,
                      admission_day=lambda: TEST_DAY, **kw)


def job_row(db, job_id):
    with db("admin").connect() as c:
        return c.execute(text("SELECT * FROM jobs WHERE job_id = :j"), {"j": job_id}).one()


def calls(db, job_id):
    with db("admin").connect() as c:
        return {r.stage: r for r in c.execute(text(
            "SELECT stage, state, usage, admitted_day FROM model_calls WHERE job_id = :j"),
            {"j": job_id})}


def expire_lease(db, job_id):
    with db("admin").begin() as c:
        c.execute(text("UPDATE jobs SET lease_until = now() - interval '1 second' "
                       "WHERE job_id = :j"), {"j": job_id})


def drain(db, queue, d):
    """Relay, then process every visible message; return outcomes."""
    relay_once(db("worker"), queue)
    outcomes = []
    for m in queue.receive(max_messages=10):
        outcome = process_job(m.body["job_id"], d)
        if outcome == "ack":
            queue.delete(m.receipt)
        outcomes.append(outcome)
    return outcomes


# ---- happy path ----------------------------------------------------------------------


def test_end_to_end_ready_with_valid_proposal(db):
    job_id, created = submit(db, scenario="base-v1")
    assert created
    queue, d = FixtureQueue(), deps(db)
    assert drain(db, queue, d) == ["ack"]
    row = job_row(db, job_id)
    assert row.state == "ready" and row.lease_token is None and row.evidence_hash
    v = row.result["validation"]
    assert v["ok"] and v["proposal_state"] == "pending" and v["evidence_coverage"] >= 0.95
    action = row.result["analysis"]["action"]
    assert action["target_type"] == "Seller" and action["target_id"] == LABELS["seller_a01"]
    assert row.result["metrics"]["selected_orders"] == len(action["selected_order_ids"])
    assert {s: c.state for s, c in calls(db, job_id).items()} == {"planner": "complete",
                                                                  "analyst": "complete"}
    assert queue.pending() == 0
    with db("admin").connect() as c:
        assert c.execute(text("SELECT count(*) FROM outbox WHERE job_id = :j AND sent_at IS "
                              "NOT NULL"), {"j": job_id}).scalar_one() == 1


def test_order_target_traverses_to_sellers(db):
    job_id, _ = submit(db, target=("Order", "single_late_00"))
    drain(db, FixtureQueue(), deps(db))
    row = job_row(db, job_id)
    assert row.state == "ready"
    assert "get_seller_exception_scope" in row.result["tools_run"]  # Order -> Seller traversal


def test_worker_thread_processes_job(db):
    import threading

    job_id, _ = submit(db)
    queue = FixtureQueue()
    w = Worker(queue, deps(db), relay_seconds=0.05)
    t = threading.Thread(target=w.run)
    t.start()
    for _ in range(100):
        if job_row(db, job_id).state == "ready":
            break
        w.stop.wait(0.05)
    w.stop.set()
    t.join(timeout=10)
    assert job_row(db, job_id).state == "ready" and queue.pending() == 0


# ---- submission ------------------------------------------------------------------------


def test_idempotent_submission(db):
    key = str(uuid.uuid4())
    a, created = submit(db, key=key)
    b, again = submit(db, key=key)
    assert a == b and created and not again
    with pytest.raises(SubmitError) as exc:
        submit(db, key=key, target=("Seller", "seller_a02"))
    assert exc.value.status == 409
    with db("admin").connect() as c:
        assert c.execute(text("SELECT count(*) FROM outbox WHERE job_id = :j"),
                         {"j": a}).scalar_one() == 1


@pytest.mark.parametrize(("subject", "target", "status"), [
    ("viewer", ("Seller", "seller_a01"), 403),
    ("reviewer", ("Seller", "seller_a01"), 403),
])
def test_submission_requires_operator(db, subject, target, status):
    with pytest.raises(SubmitError) as exc:
        submit(db, subject=subject, target=target)
    assert exc.value.status == status


def test_submission_of_hidden_target_is_not_found(db):
    from ops.queries.tools import NotVisible

    with pytest.raises(NotVisible):
        submit(db, target=("Order", "split_ab_00"))


def test_queue_messages_carry_ids_only():
    q = FixtureQueue()
    with pytest.raises(ValueError):
        q.send({"job_id": "x", "event_id": "y", "prompt": "secret"})


# ---- duplicate delivery and crashes --------------------------------------------------


def test_crash_between_send_and_mark_duplicates_but_one_result(db):
    job_id, _ = submit(db)
    queue = FixtureQueue()

    def crash(_):
        raise Crash()

    with pytest.raises(Crash):
        relay_once(db("worker"), queue, after_send=crash)
    assert queue.pending() == 1  # sent, but the outbox row was not marked
    provider = FixtureProvider()
    d = deps(db, provider)
    assert drain(db, queue, d) == ["ack", "ack"]  # duplicate message is acknowledged harmlessly
    assert job_row(db, job_id).state == "ready"
    assert provider.calls == {"planner": 1, "analyst": 1}
    assert len(calls(db, job_id)) == 2 and queue.pending() == 0


def test_duplicate_message_after_ready_is_acked_without_work(db):
    job_id, _ = submit(db)
    provider = FixtureProvider()
    d = deps(db, provider)
    drain(db, FixtureQueue(), d)
    assert process_job(job_id, d) == "ack"
    assert provider.calls == {"planner": 1, "analyst": 1}


def test_crash_after_paid_call_sent_holds_without_second_call(db):
    job_id, _ = submit(db)
    clock = Clock()
    queue = FixtureQueue(clock=clock)
    provider = FixtureProvider()

    def crash():
        raise Crash()

    relay_once(db("worker"), queue)
    msg = queue.receive()[0]
    with pytest.raises(Crash):
        process_job(msg.body["job_id"], deps(db, provider, clock, hooks={
            "after_provider:planner": crash}))
    assert calls(db, job_id)["planner"].state == "sent"
    # visibility timeout passes and the lease expires; SQS redelivers
    clock.t += 181
    expire_lease(db, job_id)
    redelivered = queue.receive()[0]
    assert redelivered.receive_count == 2
    assert process_job(job_id, deps(db, provider, clock)) == "ack"
    row = job_row(db, job_id)
    assert row.state == "unknown" and row.result["reason"] == "RECONCILE_REQUIRED"
    assert provider.calls["planner"] == 1 and provider.calls["analyst"] == 0
    print(mark_failed(job_id, "test reconciliation"))
    assert job_row(db, job_id).state == "failed"


def test_crash_after_checkpoint_resumes_and_reuses_completed_stage(db):
    job_id, _ = submit(db)
    clock = Clock()
    queue = FixtureQueue(clock=clock)
    provider = FixtureProvider()

    def crash():
        raise Crash()

    relay_once(db("worker"), queue)
    msg = queue.receive()[0]
    with pytest.raises(Crash):
        process_job(msg.body["job_id"], deps(db, provider, clock,
                                             hooks={"after_tools_checkpoint": crash}))
    clock.t += 181
    expire_lease(db, job_id)
    again = queue.receive()[0]
    assert process_job(again.body["job_id"], deps(db, provider, clock)) == "ack"
    queue.delete(again.receipt)
    assert job_row(db, job_id).state == "ready"
    assert provider.calls == {"planner": 1, "analyst": 1}  # planner reused from checkpoint


def test_reserved_but_never_sent_stage_resumes(db):
    job_id, _ = submit(db)
    provider = FixtureProvider()
    d = deps(db, provider)
    claimed = C.claim(db("worker"), job_id)
    C.reserve_call(db("worker"), job_id, "planner", "m", {}, "h", today=TEST_DAY)
    expire_lease(db, job_id)
    assert claimed.token
    assert process_job(job_id, d) == "ack"
    assert job_row(db, job_id).state == "ready" and provider.calls["planner"] == 1


def test_lease_blocks_second_worker_and_guards_writes(db):
    job_id, _ = submit(db)
    first = C.claim(db("worker"), job_id)
    assert C.claim(db("worker"), job_id) == "leased"
    assert process_job(job_id, deps(db)) == "retry"
    expire_lease(db, job_id)
    second = C.claim(db("worker"), job_id)
    with pytest.raises(C.LeaseLost):
        C.save_checkpoint(db("worker"), first, "x", {"stale": True})
    C.save_checkpoint(db("worker"), second, "x", {"ok": True})


def test_poison_message_reaches_dlq_after_five_receives(db):
    clock = Clock()
    queue = FixtureQueue(clock=clock)
    queue.send({"job_id": "not-a-uuid", "event_id": str(uuid.uuid4())})
    w = Worker(queue, deps(db, clock=clock))
    for _ in range(6):
        w.poll_once()
        w.pool.shutdown(wait=True)
        w.pool = __import__("concurrent.futures").futures.ThreadPoolExecutor(max_workers=2)
        clock.t += 181
    queue.receive()
    assert len(queue.dead_letters) == 1 and queue.pending() == 0
    assert queue.dead_letters[0]["receives"] == 5


# ---- provider outcomes, admission, breaker -------------------------------------------


def test_unknown_outcome_holds_and_never_retries(db):
    job_id, _ = submit(db)
    provider = FixtureProvider({"planner": "timeout"})
    assert drain(db, FixtureQueue(), deps(db, provider)) == ["ack"]
    row = job_row(db, job_id)
    assert row.state == "unknown" and row.result["reason"] == "PROVIDER_OUTCOME_UNKNOWN"
    assert provider.calls["planner"] == 1 and calls(db, job_id)["planner"].state == "unknown"


def test_bedrock_timeout_is_unknown_with_one_call(db, monkeypatch):
    from ops.providers import bedrock

    attempts = []

    class FakeClient:
        def converse(self, **kw):
            attempts.append(kw["modelId"])
            raise ReadTimeoutError(endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com")

    monkeypatch.setattr(bedrock, "_client", lambda region, timeout: FakeClient())
    job_id, _ = submit(db)
    drain(db, FixtureQueue(), deps(db, bedrock.BedrockProvider("us-east-1")))
    row = job_row(db, job_id)
    assert row.state == "unknown" and len(attempts) == 1


def test_bedrock_client_has_sdk_retries_disabled(monkeypatch):
    from ops.providers import bedrock

    for var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")

    bedrock._client.cache_clear()
    client = bedrock._client("us-east-1", 30)
    assert client.meta.config.retries["total_max_attempts"] == 1
    bedrock._client.cache_clear()


def test_confirmed_throttle_retried_once(db):
    job_id, _ = submit(db)
    provider = FixtureProvider({"planner": "throttle_once"})
    drain(db, FixtureQueue(), deps(db, provider))
    assert job_row(db, job_id).state == "ready"
    assert provider.calls["planner"] == 2 and calls(db, job_id)["planner"].state == "complete"


def test_persistent_rejection_fails_and_breaker_opens(db):
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    bad = FixtureProvider({"planner": "reject"})
    d = deps(db, bad, clock)
    d.breaker = breaker
    for _ in range(5):
        job_id, _ = submit(db)
        drain(db, FixtureQueue(), d)
        assert job_row(db, job_id).result["reason"] == "PROVIDER_REJECTED"
    assert breaker.state == "open"
    healthy = FixtureProvider()
    d2 = deps(db, healthy, clock)
    d2.breaker = breaker
    blocked, _ = submit(db)
    drain(db, FixtureQueue(), d2)
    assert job_row(db, blocked).result["reason"] == "PROVIDER_UNAVAILABLE"
    assert healthy.calls == {} and calls(db, blocked) == {}  # no admission, no paid call
    clock.t += 60
    probe, _ = submit(db)
    drain(db, FixtureQueue(), d2)
    assert job_row(db, probe).state == "ready" and breaker.state == "closed"


def test_breaker_half_open_allows_one_probe():
    clock = Clock()
    b = CircuitBreaker(clock=clock)
    for _ in range(5):
        b.record_known_failure()
    assert not b.allow()
    clock.t += 60
    assert b.allow() and not b.allow()  # one probe only
    b.record_known_failure()
    assert b.state == "open"


def test_daily_cap_blocks_admission(db):
    with db("admin").begin() as c:
        c.execute(text("INSERT INTO usage_days (day, admitted_calls) VALUES (:d, 100)"),
                  {"d": TEST_DAY})
    job_id, _ = submit(db)
    provider = FixtureProvider()
    drain(db, FixtureQueue(), deps(db, provider))
    assert job_row(db, job_id).result["reason"] == "DAILY_CALL_CAP"
    assert provider.calls == {}


def test_invalid_json_fails_without_repair(db):
    job_id, _ = submit(db)
    provider = FixtureProvider({"planner": "invalid_json"})
    drain(db, FixtureQueue(), deps(db, provider))
    row = job_row(db, job_id)
    assert row.state == "failed" and row.result["reason"] == "INVALID_MODEL_OUTPUT"
    assert provider.calls == {"planner": 1}


def test_scope_change_mid_job_blocks(db):
    job_id, _ = submit(db, target=("Seller", "seller_revoked"))
    with db("admin").begin() as c:
        c.execute(text("DELETE FROM seller_grants WHERE subject = 'operator_a' AND batch_id = :b "
                       "AND seller_id = :s"), {"b": BATCH, "s": LABELS["seller_revoked"]})
    try:
        provider = FixtureProvider()
        drain(db, FixtureQueue(), deps(db, provider))
        row = job_row(db, job_id)
        assert row.state == "blocked" and row.result["reason"] == "SCOPE_CHANGED"
        assert provider.calls == {}
    finally:
        seed_users("local")


# ---- validator ------------------------------------------------------------------------


@pytest.mark.parametrize(("fault", "codes", "proposal_state"), [
    ("causal", {"UNSUPPORTED_CAUSAL_CLAIM"}, "needs_review"),
    ("invented_id", {"INVENTED_ID", "UNRESOLVABLE_EVIDENCE"}, "none"),
    ("arithmetic", {"INCORRECT_ARITHMETIC"}, "none"),
])
def test_validator_rejections(db, fault, codes, proposal_state):
    job_id, _ = submit(db)
    drain(db, FixtureQueue(), deps(db, FixtureProvider({"analyst": fault})))
    v = job_row(db, job_id).result["validation"]
    assert not v["ok"] and codes <= {r["code"] for r in v["rejections"]}
    assert v["proposal_state"] == proposal_state
    if fault == "causal":
        assert v["causal_rejections"] >= 1


def test_analyst_input_respects_token_budget(db):
    from ops.agents import analyst
    from ops.agents.common import estimate_tokens

    with db("worker").connect() as c:
        batch = c.execute(text("SELECT batch_id FROM source_batches WHERE "
                               "manifest->>'provenance' = 'olist'")).scalar_one_or_none()
        if batch is None:
            pytest.skip("Olist batch not imported")
        from ops.queries import tools as T

        p = load_principal(c, "reviewer", batch)
        as_of = datetime(2018, 3, 30, 23, 59, 59)
        page = T.find_late_orders(c, p, T.FindLateOrdersInput(as_of=as_of, limit=100))
        big = max({s for i in page.items for s in i.seller_ids},
                  key=lambda s: sum(s in i.seller_ids for i in page.items))
        scope = T.get_seller_exception_scope(c, p, T.SellerScopeInput(seller_id=big,
                                                                      as_of=as_of))
        results = [scope.model_dump(mode="json"), page.model_dump(mode="json")]
    system, user = analyst.build_prompt({"target": {"target_type": "Seller",
                                                    "target_id": big}}, results)
    assert estimate_tokens(system, user) <= analyst.MAX_INPUT_TOKENS
