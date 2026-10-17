"""Shared helpers for job, proposal, and approval tests (fixture queue and provider)."""

import json
import uuid
from datetime import date, datetime

from sqlalchemy import text

from ops.commands import proposals as P
from ops.jobs.breaker import CircuitBreaker
from ops.jobs.consumer import WorkerDeps, process_job
from ops.jobs.outbox import JobRequest, relay_once, submit_job
from ops.jobs.queues import FixtureQueue
from ops.providers.fixture import FixtureProvider
from ops.queries.scope import load_principal
from ops.settings import REPO_ROOT

LABELS = json.loads((REPO_ROOT / "data" / "fixtures" / "labels.json").read_text())
BATCH = "fixtures-v1"
AS_OF = datetime(2018, 3, 15, 23, 59, 59)
TEST_DAY = date(2099, 1, 1)


def L(label: str) -> str:
    return LABELS[label]


def submit(db, subject="operator_a", target=("Seller", "seller_a01"), scenario=None, key=None):
    ttype, label = target
    req = JobRequest(target_type=ttype, target_id=L(label), as_of=AS_OF, scenario_id=scenario)
    with db("api").begin() as conn:
        p = load_principal(conn, subject, BATCH)
        return submit_job(conn, p, req, key or str(uuid.uuid4()))[0]


def run_jobs(db, faults=None, hooks=None):
    queue = FixtureQueue()
    d = WorkerDeps(engine=db("worker"), provider=FixtureProvider(faults or {}),
                   breaker=CircuitBreaker(), sleep=lambda s: None,
                   admission_day=lambda: TEST_DAY, hooks=hooks or {})
    relay_once(db("worker"), queue)
    for m in queue.receive(max_messages=10):
        if process_job(m.body["job_id"], d) == "ack":
            queue.delete(m.receipt)
    return queue


def ready_job(db, subject="operator_a", target=("Seller", "seller_a01"), faults=None,
              scenario=None):
    job_id = submit(db, subject, target, scenario)
    run_jobs(db, faults)
    with db("admin").connect() as c:
        state = c.execute(text("SELECT state FROM jobs WHERE job_id = :j"),
                          {"j": job_id}).scalar_one()
    assert state == "ready", state
    return job_id


def propose(db, job_id, subject="operator_a"):
    with db("api").begin() as conn:
        return P.create_proposal(conn, load_principal(conn, subject, BATCH), job_id)[0]


def decide(db, proposal, subject="reviewer", decision="approve", revision=None):
    """Mirror the API: the transaction commits even when the command reports an error."""
    error = None
    with db("api").begin() as conn:
        try:
            out = P.decide(conn, load_principal(conn, subject, BATCH), proposal["proposal_id"],
                           decision, proposal["revision"] if revision is None else revision)
        except P.CommandError as exc:
            error = exc
    if error is not None:
        raise error
    return out


def proposal_state(db, proposal_id):
    with db("admin").connect() as c:
        return c.execute(text("SELECT state, revision FROM proposals WHERE proposal_id = :p"),
                         {"p": proposal_id}).one()


def cases_for(db, target_id):
    with db("admin").connect() as c:
        return c.execute(text("SELECT count(*) FROM cases WHERE "
                              "case_payload->'target'->>'target_id' = :t"),
                         {"t": target_id}).scalar_one()


def reset_actions(db):
    """Clear cases and proposals so tests start from a known state (admin role)."""
    with db("admin").begin() as c:
        c.execute(text("DELETE FROM internal_drafts"))
        c.execute(text("DELETE FROM cases"))
        c.execute(text("DELETE FROM proposals"))
        c.execute(text("DELETE FROM model_calls WHERE admitted_day = :d"), {"d": TEST_DAY})
        c.execute(text("DELETE FROM usage_days WHERE day = :d"), {"d": TEST_DAY})
        c.execute(text("UPDATE outbox SET sent_at = now() WHERE sent_at IS NULL"))
