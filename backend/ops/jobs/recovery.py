"""ops recover-job: explicit reconciliation for jobs held in an unknown paid-call state.

An unknown paid outcome is never retried automatically. An operator of the system
inspects the hold and resolves it by marking the job failed; the user regenerates.
Runs as the admin role.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from ops.db import engine


class RecoveryError(Exception):
    pass


def describe(job_id: str) -> str:
    with engine("admin").connect() as conn:
        job = conn.execute(text("SELECT job_id, state, result FROM jobs WHERE job_id = "
                                "CAST(:j AS uuid)"), {"j": job_id}).one_or_none()
        if job is None:
            raise RecoveryError("job not found")
        calls = conn.execute(text("SELECT stage, state, model_id, usage FROM model_calls "
                                  "WHERE job_id = CAST(:j AS uuid) ORDER BY stage"),
                             {"j": job_id}).all()
    lines = [f"job {job.job_id}: state={job.state} result={json.dumps(job.result)}"]
    lines += [f"  call {c.stage}: state={c.state} model={c.model_id} usage={json.dumps(c.usage)}"
              for c in calls]
    return "\n".join(lines)


def mark_failed(job_id: str, note: str) -> str:
    with engine("admin").begin() as conn:
        job = conn.execute(text("SELECT state FROM jobs WHERE job_id = CAST(:j AS uuid) "
                                "FOR UPDATE"), {"j": job_id}).one_or_none()
        if job is None:
            raise RecoveryError("job not found")
        if job.state != "unknown":
            raise RecoveryError(f"job is {job.state}; only unknown holds are reconciled")
        conn.execute(text(
            "UPDATE jobs SET state = 'failed', result = result || CAST(:r AS jsonb), "
            "revision = revision + 1 WHERE job_id = CAST(:j AS uuid)"),
            {"j": job_id, "r": json.dumps({"reconciled": True, "reconcile_note": note[:200]})})
        conn.execute(text(
            "INSERT INTO audit_events (actor, kind, object_id, safe_payload) VALUES "
            "('ops-recover-job', 'job_reconciled_failed', :j, CAST(:p AS jsonb))"),
            {"j": job_id, "p": json.dumps({"note": note[:200]})})
    return f"job {job_id} marked failed after reconciliation; regenerate to retry"
