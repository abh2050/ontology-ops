"""Command handlers for proposals and the independent approval transaction (spec 11.5).

Run as the API role. Proposal creation re-validates the ready job's action against
current data and scope. Approval locks the proposal row, takes a transaction-level
advisory lock on the target, and re-checks actor, permissions, revision, evidence
and snapshot hash, ontology version, eligibility, and existing equivalent cases.
CreateInvestigation inserts the case, marks the proposal executed, and appends an
audit event atomically. DraftCustomerUpdate inserts an internal draft instead and
never produces an external side effect.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from sqlalchemy import Connection, text

from ops.ontology.registry import ONTOLOGY_VERSION
from ops.queries import tools as T
from ops.queries.evidence import canonical_json
from ops.queries.scope import Principal, load_principal


class CommandError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail or code


def _audit(conn: Connection, actor: str, kind: str, object_id: str, payload: dict) -> None:
    conn.execute(text("INSERT INTO audit_events (actor, kind, object_id, safe_payload) "
                      "VALUES (:a, :k, :o, CAST(:p AS jsonb))"),
                 {"a": actor, "k": kind, "o": object_id, "p": json.dumps(payload)})


PROPOSAL_COLUMNS = ("proposal_id, job_id, created_by, kind, target_type, target_id, payload, "
                    "evidence_hash, proposal_hash, state, revision, reviewed_by, review_reason, "
                    "created_at")


def _proposal_row(conn: Connection, proposal_id: str, lock: bool = False):
    return conn.execute(text(
        f"SELECT {PROPOSAL_COLUMNS} FROM proposals WHERE proposal_id = CAST(:p AS uuid)"
        + (" FOR UPDATE" if lock else "")), {"p": proposal_id}).one_or_none()


def serialize(row) -> dict:
    return {"proposal_id": str(row.proposal_id), "job_id": str(row.job_id),
            "created_by": row.created_by, "kind": row.kind, "target_type": row.target_type,
            "target_id": row.target_id, "payload": row.payload,
            "evidence_hash": row.evidence_hash, "proposal_hash": row.proposal_hash,
            "state": row.state, "revision": row.revision, "reviewed_by": row.reviewed_by,
            "review_reason": row.review_reason, "created_at": row.created_at.isoformat()}


# ---- create ----------------------------------------------------------------------------


def create_proposal(conn: Connection, principal: Principal, job_id: str) -> tuple[dict, bool]:
    """Return (proposal, created). Caller owns the transaction."""
    if not principal.provisioned or principal.role != "operator":
        raise CommandError(403, "OPERATOR_REQUIRED")
    # The API role cannot lock job rows; serialize proposal creation per job instead.
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                 {"k": f"proposal-for-job|{job_id}"})
    job = conn.execute(text(
        "SELECT job_id, subject, batch_id, scenario_id, ontology_version, as_of, state, result, "
        "scope_hash, evidence_hash FROM jobs WHERE job_id = CAST(:j AS uuid)"),
        {"j": job_id}).one_or_none()
    if job is None or job.subject != principal.subject or job.batch_id != principal.batch_id:
        raise CommandError(404, "NOT_FOUND", "not found or not visible")
    existing = conn.execute(text(f"SELECT {PROPOSAL_COLUMNS} FROM proposals WHERE job_id = "
                                 "CAST(:j AS uuid)"), {"j": job_id}).one_or_none()
    if existing is not None:
        return serialize(existing), False
    if job.state != "ready":
        raise CommandError(409, "JOB_NOT_READY")
    if principal.scope_hash != job.scope_hash:
        raise CommandError(409, "SCOPE_CHANGED", "seller grants changed; regenerate the job")
    if job.ontology_version != ONTOLOGY_VERSION:
        raise CommandError(409, "ONTOLOGY_VERSION_CHANGED")
    result = job.result or {}
    validation = result.get("validation", {})
    action = (result.get("analysis") or {}).get("action")
    if action is None or validation.get("proposal_state") not in ("pending", "needs_review"):
        raise CommandError(409, "NO_VALID_ACTION", "the job produced no proposable action")

    target = T.Target(target_type=action["target_type"], target_id=action["target_id"])
    elig = T.check_case_eligibility(conn, principal, T.EligibilityInput(
        as_of=job.as_of, target=target, kind=action["kind"],
        selected_order_ids=action["selected_order_ids"],
        snapshot_hash=result.get("target_snapshot_hash") or "0" * 64))
    if "TARGET_NOT_VISIBLE" in elig.reasons:
        raise CommandError(404, "NOT_FOUND", "not found or not visible")
    if elig.stale:
        raise CommandError(409, "STALE_EVIDENCE", "evidence changed; regenerate the job")
    blocking = [r for r in elig.reasons if r != "STALE_SNAPSHOT"]
    if blocking:
        raise CommandError(409, "NOT_ELIGIBLE", ",".join(blocking))

    evidence_refs = sorted({r for f in result["analysis"]["findings"] for r in f["evidence_refs"]})
    payload = {
        "kind": action["kind"], "target": target.model_dump(),
        "selected_order_ids": sorted(action["selected_order_ids"]),
        "evidence_refs": evidence_refs, "snapshot_hash": result["target_snapshot_hash"],
        "ontology_version": job.ontology_version, "batch_id": job.batch_id,
        "scenario_id": job.scenario_id, "as_of": job.as_of.isoformat(),
        "reason_codes": action["reason_codes"],
        "unresolved_questions": result["analysis"].get("unresolved_questions", []),
        "findings": result["analysis"]["findings"],
        "metrics": result.get("metrics", {}), "validation": validation,
        "case_key": elig.case_key if action["kind"] == "CreateInvestigation" else None,
        "draft_text": action.get("draft_text"),
        "model_id": result.get("model_id"), "comparator": result.get("comparator"),
        "uses_synthetic_evidence": any(f["kind"] == "synthetic_context"
                                       for f in result["analysis"]["findings"]),
    }
    proposal_hash = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    state = "needs_review" if validation["proposal_state"] == "needs_review" else "pending"
    row = conn.execute(text(
        "INSERT INTO proposals (job_id, created_by, kind, target_type, target_id, payload, "
        "evidence_hash, proposal_hash, state) VALUES (CAST(:j AS uuid), :by, :kind, :tt, :tid, "
        f"CAST(:payload AS jsonb), :eh, :ph, :state) RETURNING {PROPOSAL_COLUMNS}"),
        {"j": job_id, "by": principal.subject, "kind": action["kind"],
         "tt": target.target_type, "tid": target.target_id, "payload": json.dumps(payload),
         "eh": job.evidence_hash, "ph": proposal_hash, "state": state}).one()
    _audit(conn, principal.subject, "proposal_created", str(row.proposal_id),
           {"kind": action["kind"], "state": state, "target_type": target.target_type})
    return serialize(row), True


# ---- visibility for reads ----------------------------------------------------------------


def actor_can_see(conn: Connection, principal: Principal, row) -> bool:
    """Owners see their proposals; reviewers see those whose every object they hold."""
    if not principal.provisioned:
        return False
    if row.created_by == principal.subject:
        return True
    if principal.role != "reviewer" or row.payload.get("batch_id") != principal.batch_id:
        return False
    return _holds_scope(conn, principal, row)


def _holds_scope(conn: Connection, principal: Principal, row) -> bool:
    from datetime import datetime

    payload = row.payload
    target = T.Target(**payload["target"])
    as_of = datetime.fromisoformat(payload["as_of"])
    try:
        T.target_snapshot(conn, principal, target, as_of)
    except T.NotVisible:
        return False
    seller = target.target_id if target.target_type == "Seller" else None
    visible = set(conn.execute(T.SELECTED_ORDERS_SQL, {
        **principal.params(), "order_ids": payload["selected_order_ids"], "as_of": as_of,
        "seller_id": seller}).scalars())
    return visible == set(payload["selected_order_ids"])


# ---- decide ------------------------------------------------------------------------------


def decide(conn: Connection, reviewer: Principal, proposal_id: str,
           decision: Literal["approve", "reject"], expected_revision: int,
           reason: str = "") -> dict:
    """The approval transaction. Caller owns the transaction (one per request)."""
    from datetime import datetime

    if not reviewer.provisioned or reviewer.role != "reviewer":
        raise CommandError(403, "REVIEWER_REQUIRED")
    row = _proposal_row(conn, proposal_id, lock=True)
    if row is None or not actor_can_see(conn, reviewer, row):
        raise CommandError(404, "NOT_FOUND", "not found or not visible")
    if row.created_by == reviewer.subject:
        raise CommandError(403, "SELF_APPROVAL", "a reviewer cannot decide their own proposal")
    if row.revision != expected_revision:
        raise CommandError(409, "STALE_REVISION", "the proposal changed; reload it")
    if row.state == "executed":
        raise CommandError(409, "ALREADY_EXECUTED")
    if row.state == "needs_review" and decision == "approve":
        raise CommandError(409, "NEEDS_REVIEW", "regenerate the job to produce a new proposal")
    if row.state not in ("pending", "needs_review"):
        raise CommandError(409, f"PROPOSAL_{row.state.upper()}")

    payload = row.payload
    if decision == "reject":
        _transition(conn, row, "rejected", reviewer, reason or "rejected by reviewer")
        _audit(conn, reviewer.subject, "proposal_rejected", proposal_id, {"kind": row.kind})
        return {"state": "rejected", "proposal_id": proposal_id}

    target = T.Target(**payload["target"])
    as_of = datetime.fromisoformat(payload["as_of"])
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                 {"k": f"{payload['batch_id']}|{target.target_type}|{target.target_id}"})

    def stale(code: str, detail: str):
        _transition(conn, row, "stale", reviewer, code)
        _audit(conn, reviewer.subject, "proposal_stale", proposal_id, {"code": code})
        return CommandError(409, code, detail)

    if payload["ontology_version"] != ONTOLOGY_VERSION:
        raise stale("ONTOLOGY_VERSION_CHANGED", "regenerate the job")
    job_scope = conn.execute(text("SELECT scope_hash FROM jobs WHERE job_id = :j"),
                             {"j": row.job_id}).scalar_one()
    proposer = load_principal(conn, row.created_by, payload["batch_id"])
    if not proposer.provisioned or proposer.scope_hash != job_scope:
        raise stale("PROPOSER_SCOPE_CHANGED", "the proposer's grants changed; regenerate")
    elig = T.check_case_eligibility(conn, proposer, T.EligibilityInput(
        as_of=as_of, target=target, kind=row.kind,
        selected_order_ids=payload["selected_order_ids"], snapshot_hash=payload["snapshot_hash"]))
    if elig.stale:
        raise stale("STALE_EVIDENCE", "evidence changed since the proposal; regenerate")
    if "CASE_ALREADY_EXISTS" in elig.reasons:
        raise stale("EQUIVALENT_CASE_EXISTS", f"case {elig.existing_case_id} already exists")
    if elig.reasons:
        raise stale("NOT_ELIGIBLE", ",".join(elig.reasons))
    if not _holds_scope(conn, reviewer, row):
        raise CommandError(403, "REVIEWER_SCOPE", "reviewer must hold scope over every target")

    if row.kind == "CreateInvestigation":
        case = conn.execute(text(
            "INSERT INTO cases (proposal_id, case_key, owner_subject, case_payload) "
            "VALUES (:p, :k, :owner, CAST(:payload AS jsonb)) "
            "ON CONFLICT (proposal_id) DO NOTHING RETURNING case_id"),
            {"p": row.proposal_id, "k": elig.case_key, "owner": row.created_by,
             "payload": json.dumps({
                 "target": payload["target"], "selected_order_ids": payload["selected_order_ids"],
                 "metrics": payload["metrics"], "reason_codes": payload["reason_codes"],
                 "evidence_refs": payload["evidence_refs"], "as_of": payload["as_of"],
                 "batch_id": payload["batch_id"], "scenario_id": payload["scenario_id"],
                 "uses_synthetic_evidence": payload["uses_synthetic_evidence"],
                 "unresolved_questions": payload["unresolved_questions"],
                 "approved_by": reviewer.subject, "proposal_hash": row.proposal_hash})}
        ).scalar_one_or_none()
        if case is None:
            raise CommandError(409, "ALREADY_EXECUTED")
        _transition(conn, row, "executed", reviewer, reason or "approved")
        _audit(conn, reviewer.subject, "case_created", str(case),
               {"proposal_id": proposal_id, "target_type": target.target_type})
        return {"state": "executed", "proposal_id": proposal_id, "case_id": str(case)}

    draft = conn.execute(text(
        "INSERT INTO internal_drafts (proposal_id, body) VALUES (:p, CAST(:b AS jsonb)) "
        "ON CONFLICT (proposal_id) DO NOTHING RETURNING draft_id"),
        {"p": row.proposal_id, "b": json.dumps({
            "order_id": target.target_id, "text": payload["draft_text"],
            "internal_only": True, "states_uncertainty": True,
            "approved_by": reviewer.subject})}).scalar_one_or_none()
    if draft is None:
        raise CommandError(409, "ALREADY_EXECUTED")
    _transition(conn, row, "executed", reviewer, reason or "approved")
    _audit(conn, reviewer.subject, "internal_draft_created", str(draft),
           {"proposal_id": proposal_id})
    return {"state": "executed", "proposal_id": proposal_id, "draft_id": str(draft)}


def _transition(conn: Connection, row, state: str, reviewer: Principal, reason: str) -> None:
    conn.execute(text(
        "UPDATE proposals SET state = :s, reviewed_by = :r, review_reason = :why, "
        "revision = revision + 1 WHERE proposal_id = :p"),
        {"s": state, "r": reviewer.subject, "why": reason[:300], "p": row.proposal_id})
