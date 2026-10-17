"""M4: proposals, the independent approval transaction, and approval integrity."""

import threading

import pytest
from sqlalchemy import text

from ops.commands.proposals import CommandError
from ops.data.users import seed_users
from ops.queries import tools as T
from ops.queries.scope import load_principal
from tests.integration.jobhelpers import (
    AS_OF,
    BATCH,
    L,
    cases_for,
    decide,
    proposal_state,
    propose,
    ready_job,
    reset_actions,
    run_jobs,
    submit,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean(db):
    seed_users("local")
    reset_actions(db)
    yield
    reset_actions(db)
    seed_users("local")


def test_approval_creates_one_case_atomically(db):
    p = propose(db, ready_job(db))
    assert p["state"] == "pending" and p["kind"] == "CreateInvestigation"
    assert p["payload"]["metrics"]["selected_orders"] == len(p["payload"]["selected_order_ids"])
    out = decide(db, p)
    assert out["state"] == "executed" and out["case_id"]
    assert proposal_state(db, p["proposal_id"]).state == "executed"
    assert cases_for(db, L("seller_a01")) == 1
    with db("admin").connect() as c:
        case = c.execute(text("SELECT owner_subject, case_key, case_payload FROM cases")).one()
        kinds = c.execute(text("SELECT kind FROM audit_events WHERE object_id IN (:p, :c) "
                               "ORDER BY created_at"),
                          {"p": p["proposal_id"], "c": out["case_id"]}).scalars().all()
    assert case.owner_subject == "operator_a" and case.case_payload["approved_by"] == "reviewer"
    assert case.case_key == p["payload"]["case_key"]
    assert kinds == ["proposal_created", "case_created"]


def test_proposal_creation_is_idempotent_per_job(db):
    job = ready_job(db)
    a, b = propose(db, job), propose(db, job)
    assert a["proposal_id"] == b["proposal_id"]


def test_operator_cannot_approve(db):
    p = propose(db, ready_job(db))
    with pytest.raises(CommandError) as exc:
        decide(db, p, subject="operator_a")
    assert exc.value.code == "REVIEWER_REQUIRED" and cases_for(db, L("seller_a01")) == 0


def test_self_approval_rejected_even_with_reviewer_role(db):
    p = propose(db, ready_job(db))
    with db("admin").begin() as c:  # the proposer is later given the reviewer role
        c.execute(text("UPDATE users SET role = 'reviewer' WHERE subject = 'operator_a'"))
    with pytest.raises(CommandError) as exc:
        decide(db, p, subject="operator_a")
    assert exc.value.code == "SELF_APPROVAL" and exc.value.status == 403
    assert cases_for(db, L("seller_a01")) == 0


def test_viewer_cannot_decide(db):
    p = propose(db, ready_job(db))
    with pytest.raises(CommandError) as exc:
        decide(db, p, subject="viewer")
    assert exc.value.status == 403


def test_stale_revision_rejected(db):
    p = propose(db, ready_job(db))
    with pytest.raises(CommandError) as exc:
        decide(db, p, revision=p["revision"] + 1)
    assert exc.value.code == "STALE_REVISION"
    assert proposal_state(db, p["proposal_id"]).state == "pending"


def test_duplicate_execution_rejected(db):
    p = propose(db, ready_job(db))
    decide(db, p)
    current = proposal_state(db, p["proposal_id"])
    with pytest.raises(CommandError) as exc:
        decide(db, p, revision=current.revision)
    assert exc.value.code == "ALREADY_EXECUTED" and cases_for(db, L("seller_a01")) == 1


def test_concurrent_duplicate_approvals_create_one_case(db):
    p = propose(db, ready_job(db))
    outcomes = []

    def go():
        try:
            outcomes.append(decide(db, p)["state"])
        except CommandError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("executed") == 1 and cases_for(db, L("seller_a01")) == 1


def test_competing_proposals_open_one_investigation(db):
    first = propose(db, ready_job(db))
    second = propose(db, ready_job(db))
    assert first["proposal_id"] != second["proposal_id"]
    assert first["payload"]["case_key"] == second["payload"]["case_key"]
    outcomes = []

    def go(p):
        try:
            outcomes.append(decide(db, p)["state"])
        except CommandError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=go, args=(p,)) for p in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["EQUIVALENT_CASE_EXISTS", "executed"]
    assert cases_for(db, L("seller_a01")) == 1
    states = sorted(proposal_state(db, p["proposal_id"]).state for p in (first, second))
    assert states == ["executed", "stale"]


def test_needs_review_cannot_execute_and_stays_in_history(db):
    p = propose(db, ready_job(db, faults={"analyst": "causal"}))
    assert p["state"] == "needs_review"
    with pytest.raises(CommandError) as exc:
        decide(db, p)
    assert exc.value.code == "NEEDS_REVIEW" and cases_for(db, L("seller_a01")) == 0
    assert decide(db, p, decision="reject")["state"] == "rejected"
    with db("admin").connect() as c:
        assert c.execute(text("SELECT state FROM proposals WHERE proposal_id = :p"),
                         {"p": p["proposal_id"]}).scalar_one() == "rejected"


def test_rejected_job_without_valid_action_cannot_be_proposed(db):
    job = ready_job(db, faults={"analyst": "invented_id"})
    with pytest.raises(CommandError) as exc:
        propose(db, job)
    assert exc.value.code == "NO_VALID_ACTION"


def test_stale_evidence_at_execution(db):
    p = propose(db, ready_job(db))
    order = p["payload"]["selected_order_ids"][0]
    with db("admin").begin() as c:  # a source correction changes the seller's evidence
        c.execute(text("UPDATE order_items SET price_centavos = price_centavos + 1 "
                       "WHERE batch_id = :b AND order_id = :o AND seller_id = :s"),
                  {"b": BATCH, "o": order, "s": L("seller_a01")})
    try:
        with pytest.raises(CommandError) as exc:
            decide(db, p)
        assert exc.value.code == "STALE_EVIDENCE" and exc.value.status == 409
        assert proposal_state(db, p["proposal_id"]).state == "stale"
        assert cases_for(db, L("seller_a01")) == 0
    finally:
        with db("admin").begin() as c:
            c.execute(text("UPDATE order_items SET price_centavos = price_centavos - 1 "
                           "WHERE batch_id = :b AND order_id = :o AND seller_id = :s"),
                      {"b": BATCH, "o": order, "s": L("seller_a01")})


def test_proposer_grant_revoked_before_execution(db):
    p = propose(db, ready_job(db))
    with db("admin").begin() as c:
        c.execute(text("DELETE FROM seller_grants WHERE subject = 'operator_a' AND batch_id = :b "
                       "AND seller_id = :s"), {"b": BATCH, "s": L("seller_revoked")})
    with pytest.raises(CommandError) as exc:
        decide(db, p)
    assert exc.value.code == "PROPOSER_SCOPE_CHANGED"
    assert proposal_state(db, p["proposal_id"]).state == "stale"


def test_grant_revoked_between_job_and_proposal(db):
    job = ready_job(db)
    with db("admin").begin() as c:
        c.execute(text("DELETE FROM seller_grants WHERE subject = 'operator_a' AND batch_id = :b "
                       "AND seller_id = :s"), {"b": BATCH, "s": L("seller_revoked")})
    with pytest.raises(CommandError) as exc:
        propose(db, job)
    assert exc.value.code == "SCOPE_CHANGED"


def test_grant_revoked_mid_job_blocks(db):
    job = submit(db, target=("Seller", "seller_revoked"))
    with db("admin").begin() as c:
        c.execute(text("DELETE FROM seller_grants WHERE subject = 'operator_a' AND batch_id = :b "
                       "AND seller_id = :s"), {"b": BATCH, "s": L("seller_revoked")})
    run_jobs(db)
    with db("admin").connect() as c:
        row = c.execute(text("SELECT state, result FROM jobs WHERE job_id = :j"),
                        {"j": job}).one()
    assert row.state == "blocked" and row.result["reason"] == "SCOPE_CHANGED"


def test_reviewer_must_independently_hold_scope(db):
    with db("admin").begin() as c:
        c.execute(text("INSERT INTO users VALUES ('reviewer_a_only', 'reviewer', true) "
                       "ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO seller_grants SELECT 'reviewer_a_only', batch_id, seller_id "
                       "FROM seller_grants WHERE subject = 'operator_a' AND batch_id = :b "
                       "ON CONFLICT DO NOTHING"), {"b": BATCH})
    try:
        p = propose(db, ready_job(db, subject="operator_b", target=("Seller", "seller_b01")),
                    subject="operator_b")
        with pytest.raises(CommandError) as exc:
            decide(db, p, subject="reviewer_a_only")
        assert exc.value.status == 404 and cases_for(db, L("seller_b01")) == 0
        assert decide(db, p)["state"] == "executed"
    finally:
        with db("admin").begin() as c:
            c.execute(text("DELETE FROM seller_grants WHERE subject = 'reviewer_a_only'"))
            c.execute(text("DELETE FROM users WHERE subject = 'reviewer_a_only'"))


def test_split_order_can_never_become_a_case(db):
    """Owner decision 4: an order spanning operator_a and operator_b sellers is invisible to
    both operators, and the reviewer cannot propose, so no case can be created for it."""
    from ops.jobs.outbox import SubmitError

    split = L("split_ab_00")
    for operator in ("operator_a", "operator_b"):
        with db("api").connect() as c:
            principal = load_principal(c, operator, BATCH)
            with pytest.raises(T.NotVisible):
                T.get_order_snapshot(c, principal, T.OrderSnapshotInput(order_id=split,
                                                                        as_of=AS_OF))
        with pytest.raises(T.NotVisible):
            submit(db, subject=operator, target=("Order", "split_ab_00"))
    with pytest.raises(SubmitError) as exc:
        submit(db, subject="reviewer", target=("Order", "split_ab_00"))
    assert exc.value.status == 403
    # seller-group proposals of either operator never include the split order
    for operator, seller in (("operator_a", "seller_a01"), ("operator_b", "seller_b01")):
        p = propose(db, ready_job(db, subject=operator, target=("Seller", seller)),
                    subject=operator)
        assert split not in p["payload"]["selected_order_ids"]
        decide(db, p)
    with db("admin").connect() as c:
        assert c.execute(text("SELECT count(*) FROM cases WHERE case_payload::text LIKE :s"),
                         {"s": f"%{split}%"}).scalar_one() == 0


def test_draft_customer_update_creates_internal_draft_only(db):
    p = propose(db, ready_job(db, target=("Order", "single_late_00"),
                              faults={"analyst": "draft"}))
    assert p["kind"] == "DraftCustomerUpdate" and p["state"] == "pending"
    out = decide(db, p)
    assert out["state"] == "executed" and out["draft_id"]
    with db("admin").connect() as c:
        assert c.execute(text("SELECT count(*) FROM cases")).scalar_one() == 0
        body = c.execute(text("SELECT body FROM internal_drafts")).scalar_one()
        cols = set(c.execute(text("SELECT column_name FROM information_schema.columns "
                                  "WHERE table_name = 'internal_drafts'")).scalars())
    assert body["internal_only"] is True and "recipient" not in body
    assert not {c for c in cols if "recipient" in c or "email" in c or "phone" in c}


def test_crash_and_redelivery_still_produce_one_case(db):
    """Demo drill: the worker dies after writing ready but before acknowledging SQS."""
    from ops.jobs.breaker import CircuitBreaker
    from ops.jobs.consumer import WorkerDeps, process_job
    from ops.jobs.outbox import relay_once
    from ops.jobs.queues import FixtureQueue
    from ops.providers.fixture import FixtureProvider
    from tests.integration.jobhelpers import TEST_DAY

    class Crash(Exception):
        pass

    clock = [0.0]
    queue = FixtureQueue(clock=lambda: clock[0])
    provider = FixtureProvider()

    def deps(hooks=None):
        return WorkerDeps(engine=db("worker"), provider=provider, breaker=CircuitBreaker(),
                          sleep=lambda s: None, admission_day=lambda: TEST_DAY,
                          hooks=hooks or {})

    def crash():
        raise Crash()

    job = submit(db)
    relay_once(db("worker"), queue)
    first = queue.receive()[0]
    with pytest.raises(Crash):
        process_job(first.body["job_id"], deps({"before_ack": crash}))
    clock[0] += 181  # visibility timeout expires; SQS redelivers the same message
    again = queue.receive()[0]
    assert again.body == first.body and again.receive_count == 2
    assert process_job(again.body["job_id"], deps()) == "ack"
    queue.delete(again.receipt)
    assert queue.pending() == 0 and provider.calls == {"planner": 1, "analyst": 1}
    p = propose(db, job)
    decide(db, p)
    assert cases_for(db, L("seller_a01")) == 1
