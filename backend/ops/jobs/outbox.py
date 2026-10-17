"""Job submission (API role) and the outbox relay (worker role), spec 12.1.

Submission writes the job and its outbox row in one transaction. The relay polls
committed outbox rows, publishes IDs to the queue, and marks a row sent only after
a successful send; a crash between send and mark can therefore duplicate a message,
which the consumer tolerates.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy import Connection, Engine, text

from ops.ontology.registry import ONTOLOGY_VERSION
from ops.queries import tools as T
from ops.queries.scope import Principal

MAX_QUEUED_PER_USER = 20
Hex32 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_type: Literal["Order", "Seller"]
    target_id: Hex32
    as_of: datetime
    scenario_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")] | None
    model_key: Literal["default", "second"] = "default"
    comparator: Literal["candidate", "b1"] = "candidate"
    question: Annotated[str, StringConstraints(max_length=300)] = ""

    @field_validator("as_of")
    @classmethod
    def _naive(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            raise ValueError("as_of is dataset local")
        return v


class SubmitError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def request_hash(req: JobRequest) -> str:
    return hashlib.sha256(req.model_dump_json().encode()).hexdigest()


INSERT_JOB_SQL = text("""
INSERT INTO jobs (subject, idempotency_key, request_hash, batch_id, scenario_id,
                  ontology_version, as_of, state, input, scope_hash)
VALUES (:subject, :key, :hash, :batch_id, :scenario_id, :ontology, :as_of, 'queued',
        CAST(:input AS jsonb), :scope_hash)
ON CONFLICT (subject, idempotency_key) DO NOTHING
RETURNING job_id
""")


def submit_job(conn: Connection, principal: Principal, req: JobRequest,
               idempotency_key: str) -> tuple[str, bool]:
    """Return (job_id, created). Caller owns the transaction."""
    if not principal.provisioned or principal.role != "operator":
        raise SubmitError(403, "only provisioned operators submit investigation jobs")
    if not (1 <= len(idempotency_key) <= 128):
        raise SubmitError(422, "Idempotency-Key header must be 1 to 128 characters")
    rhash = request_hash(req)
    existing = conn.execute(text(
        "SELECT job_id, request_hash FROM jobs WHERE subject = :s AND idempotency_key = :k"),
        {"s": principal.subject, "k": idempotency_key}).one_or_none()
    if existing is not None:
        if existing.request_hash != rhash:
            raise SubmitError(409, "Idempotency-Key reused with a different request")
        return str(existing.job_id), False

    # Validate identity and scope before anything is persisted.
    target = T.Target(target_type=req.target_type, target_id=req.target_id)
    T.target_snapshot(conn, principal, target, req.as_of)  # raises NotVisible
    if req.scenario_id is not None and conn.execute(
            T.SCENARIO_EXISTS_SQL, {"scenario_id": req.scenario_id}).first() is None:
        raise SubmitError(422, "unknown scenario")
    active = conn.execute(text(
        "SELECT count(*) FROM jobs WHERE subject = :s AND state IN "
        "('queued','running','validating')"), {"s": principal.subject}).scalar_one()
    if active >= MAX_QUEUED_PER_USER:
        raise SubmitError(429, "queued job limit reached (20 per user)")

    payload = {"target": {"target_type": req.target_type, "target_id": req.target_id},
               "model_key": req.model_key, "comparator": req.comparator,
               "question": req.question}
    row = conn.execute(INSERT_JOB_SQL, {
        "subject": principal.subject, "key": idempotency_key, "hash": rhash,
        "batch_id": principal.batch_id, "scenario_id": req.scenario_id,
        "ontology": ONTOLOGY_VERSION, "as_of": req.as_of, "input": json.dumps(payload),
        "scope_hash": principal.scope_hash}).one_or_none()
    if row is None:  # a concurrent submission with the same key won the race
        winner = conn.execute(text(
            "SELECT job_id, request_hash FROM jobs WHERE subject = :s AND idempotency_key = :k"),
            {"s": principal.subject, "k": idempotency_key}).one()
        if winner.request_hash != rhash:
            raise SubmitError(409, "Idempotency-Key reused with a different request")
        return str(winner.job_id), False
    job_id = str(row.job_id)
    conn.execute(text("INSERT INTO outbox (job_id) VALUES (:j)"), {"j": job_id})
    conn.execute(text(
        "INSERT INTO audit_events (actor, kind, object_id, safe_payload) "
        "VALUES (:a, 'job_submitted', :o, CAST(:p AS jsonb))"),
        {"a": principal.subject, "o": job_id,
         "p": json.dumps({"target_type": req.target_type, "comparator": req.comparator,
                          "model_key": req.model_key,
                          "scenario": req.scenario_id is not None})})
    return job_id, True


RELAY_SELECT_SQL = text("""
SELECT event_id, job_id FROM outbox WHERE sent_at IS NULL
ORDER BY created_at LIMIT :limit FOR UPDATE SKIP LOCKED
""")


def relay_once(worker_engine: Engine, queue, limit: int = 20,
               after_send: Callable[[str], None] | None = None) -> int:
    """Publish committed, unsent outbox rows. Returns the number marked sent."""
    sent = 0
    with worker_engine.begin() as conn:
        for row in conn.execute(RELAY_SELECT_SQL, {"limit": limit}).all():
            queue.send({"job_id": str(row.job_id), "event_id": str(row.event_id)})
            if after_send is not None:
                after_send(str(row.event_id))  # fault injection point (crash after send)
            conn.execute(text("UPDATE outbox SET sent_at = now() WHERE event_id = :e"),
                         {"e": row.event_id})
            sent += 1
    return sent
