"""Leases, checkpoints, and paid call admission (spec 12.1 and 12.2). Worker role only.

A worker writes a job only while it owns the lease (random token, 120 s). Before
each paid call one transaction reserves the unique model_calls(job_id, stage) row and
increments the admitted count; state 'sent' is persisted before the external call,
which runs outside any database transaction. Durable limits survive restarts.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine, text

LEASE_SECONDS = 120
DAILY_LIVE_CAP = 100
TERMINAL = {"ready", "failed", "blocked", "unknown"}


class LeaseLost(Exception):
    pass


class AdmissionDenied(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class ClaimedJob:
    job_id: str
    token: str
    subject: str
    batch_id: str
    scenario_id: str | None
    as_of: object
    input: dict
    checkpoint: dict
    scope_hash: str
    state: str


CLAIM_SQL = text("""
UPDATE jobs SET lease_token = :token,
               lease_until = now() + make_interval(secs => :lease),
               state = CASE WHEN state = 'queued' THEN 'running' ELSE state END,
               revision = revision + 1
WHERE job_id = :job_id
  AND state IN ('queued', 'running', 'validating')
  AND (lease_until IS NULL OR lease_until < now())
RETURNING job_id, subject, batch_id, scenario_id, as_of, input, checkpoint, scope_hash, state
""")


def claim(engine: Engine, job_id: str, lease_seconds: int = LEASE_SECONDS
          ) -> ClaimedJob | str:
    """Return a ClaimedJob, or 'terminal' / 'leased' / 'missing'."""
    token = str(uuid.uuid4())
    with engine.begin() as conn:
        row = conn.execute(CLAIM_SQL, {"token": token, "lease": lease_seconds,
                                       "job_id": job_id}).one_or_none()
        if row is None:
            state = conn.execute(text("SELECT state FROM jobs WHERE job_id = :j"),
                                 {"j": job_id}).scalar_one_or_none()
            if state is None:
                return "missing"
            return "terminal" if state in TERMINAL else "leased"
    return ClaimedJob(str(row.job_id), token, row.subject, row.batch_id, row.scenario_id,
                      row.as_of, row.input, row.checkpoint, row.scope_hash, row.state)


def _guarded(engine: Engine, job: ClaimedJob, sets: str, params: dict) -> None:
    with engine.begin() as conn:
        ok = conn.execute(text(
            f"UPDATE jobs SET {sets}, revision = revision + 1 "
            "WHERE job_id = :job_id AND lease_token = :token AND lease_until > now() "
            "RETURNING job_id"), {"job_id": job.job_id, "token": job.token, **params}).first()
    if ok is None:
        raise LeaseLost(job.job_id)


def set_state(engine: Engine, job: ClaimedJob, state: str) -> None:
    _guarded(engine, job, "state = :state", {"state": state})
    job.state = state


def save_checkpoint(engine: Engine, job: ClaimedJob, key: str, value) -> None:
    _guarded(engine, job,
             "checkpoint = checkpoint || "
             "jsonb_build_object(CAST(:key AS text), CAST(:val AS jsonb))",
             {"key": key, "val": json.dumps(value, default=str)})
    job.checkpoint[key] = json.loads(json.dumps(value, default=str))


def finish(engine: Engine, job: ClaimedJob, state: str, result: dict,
           evidence_hash: str | None = None) -> None:
    assert state in TERMINAL
    _guarded(engine, job,
             "state = :state, result = CAST(:result AS jsonb), evidence_hash = :eh, "
             "lease_token = NULL, lease_until = NULL",
             {"state": state, "result": json.dumps(result, default=str), "eh": evidence_hash})
    job.state = state


# ---- paid call admission -------------------------------------------------------------


@dataclass
class CallSlot:
    call_id: str
    state: str          # reserved | sent | complete | known_failure | unknown
    request_hash: str
    usage: dict | None
    new: bool


def reserve_call(engine: Engine, job_id: str, stage: str, model_id: str, price_snapshot: dict,
                 req_hash: str, *, eval_run_id: str | None = None, today: date | None = None,
                 daily_cap: int = DAILY_LIVE_CAP) -> CallSlot:
    with engine.begin() as conn:
        existing = conn.execute(text(
            "SELECT call_id, state, request_hash, usage FROM model_calls "
            "WHERE job_id = :j AND stage = :s FOR UPDATE"), {"j": job_id, "s": stage}
        ).one_or_none()
        if existing is not None:
            return CallSlot(str(existing.call_id), existing.state, existing.request_hash,
                            existing.usage, new=False)
        admitted_day = None
        if eval_run_id is None:
            admitted_day = today or conn.execute(text("SELECT current_date")).scalar_one()
            conn.execute(text("INSERT INTO usage_days (day) VALUES (:d) ON CONFLICT DO NOTHING"),
                         {"d": admitted_day})
            ok = conn.execute(text(
                "UPDATE usage_days SET admitted_calls = admitted_calls + 1 "
                "WHERE day = :d AND admitted_calls < :cap RETURNING day"),
                {"d": admitted_day, "cap": daily_cap}).first()
            if ok is None:
                raise AdmissionDenied("DAILY_CALL_CAP")
        else:
            ok = conn.execute(text(
                "UPDATE eval_runs SET admitted_calls = admitted_calls + 1 "
                "WHERE eval_run_id = :e AND admitted_calls < ceiling RETURNING eval_run_id"),
                {"e": eval_run_id}).first()
            if ok is None:
                raise AdmissionDenied("EVAL_CALL_CEILING")
        call_id = conn.execute(text(
            "INSERT INTO model_calls (job_id, stage, state, model_id, price_snapshot, "
            "request_hash, admitted_day, eval_run_id) VALUES (:j, :s, 'reserved', :m, "
            "CAST(:p AS jsonb), :h, :d, :e) RETURNING call_id"),
            {"j": job_id, "s": stage, "m": model_id, "p": json.dumps(price_snapshot),
             "h": req_hash, "d": admitted_day, "e": eval_run_id}).scalar_one()
    return CallSlot(str(call_id), "reserved", req_hash, None, new=True)


def mark_call(engine: Engine, call_id: str, state: str, usage: dict | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE model_calls SET state = :st, usage = coalesce(CAST(:u AS jsonb), usage) "
            "WHERE call_id = :c"),
            {"st": state, "u": json.dumps(usage) if usage is not None else None, "c": call_id})
