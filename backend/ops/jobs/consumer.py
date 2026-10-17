"""Job consumer: lease, scope recheck, planner, tools, analyst, validator (spec 10.2, 12).

Exactly two bounded AI stages and a deterministic validator; no agent loop. The
queue message is acknowledged only after a durable terminal state: ready, failed,
blocked, or an unknown hold that needs `ops recover-job`.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import Engine, text

from ops.agents import analyst, planner
from ops.agents.common import InvalidModelOutput, StageInputTooLarge, parse_strict, request_hash
from ops.agents.contracts import AnalystOutput, ToolPlan
from ops.agents.validator import validate
from ops.jobs import checkpoints as C
from ops.jobs.breaker import CircuitBreaker
from ops.jobs.outbox import relay_once
from ops.providers.base import Outcome, Provider
from ops.queries import tools as T
from ops.queries.evidence import evidence_hash
from ops.queries.scope import load_principal
from ops.settings import load_config

log = logging.getLogger("ops.worker")
DEADLINE_SECONDS = 60
MAX_CONCURRENT_JOBS = 2
RELAY_SECONDS = 2.0


class _Done(Exception):
    """A durable terminal state was written; acknowledge the message."""


@dataclass
class WorkerDeps:
    engine: Engine
    provider: Provider
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    models: dict = field(default_factory=lambda: load_config("models"))
    price_card: dict = field(default_factory=lambda: load_config("price_card"))
    hooks: dict[str, Callable[[], None]] = field(default_factory=dict)
    lease_seconds: int = C.LEASE_SECONDS
    deadline_seconds: float = DEADLINE_SECONDS
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    admission_day: Callable[[], object] = lambda: None  # tests pin a dedicated usage day
    daily_cap: int = C.DAILY_LIVE_CAP

    def hook(self, name: str) -> None:
        if name in self.hooks:
            self.hooks[name]()


def _model_id(deps: WorkerDeps, key: str) -> str:
    return deps.models["default_model_id" if key == "default" else "second_model_id"]


def _price_snapshot(deps: WorkerDeps, key: str, model_id: str) -> dict:
    card = deps.price_card
    rates = card.get("models", {}).get(f"{key}_model_id" if key != "default"
                                       else "default_model_id", {})
    return {"model_id": model_id, "rates": rates, "effective_date": card.get("effective_date"),
            "region": card.get("region")}


def _complete_stage(deps: WorkerDeps, job: C.ClaimedJob, call_id: str, usage: dict,
                    key: str, value: dict) -> None:
    """Mark the call complete and checkpoint its output in one transaction."""
    import json

    with deps.engine.begin() as conn:
        ok = conn.execute(text(
            "UPDATE jobs SET checkpoint = checkpoint || jsonb_build_object(CAST(:key AS text), "
            "CAST(:val AS jsonb)), revision = revision + 1 WHERE job_id = :j "
            "AND lease_token = :t AND lease_until > now() RETURNING job_id"),
            {"key": key, "val": json.dumps(value), "j": job.job_id, "t": job.token}).first()
        if ok is None:
            raise C.LeaseLost(job.job_id)
        conn.execute(text("UPDATE model_calls SET state = 'complete', usage = CAST(:u AS jsonb) "
                          "WHERE call_id = :c"), {"u": json.dumps(usage), "c": call_id})
    job.checkpoint[key] = value


class _Run:
    def __init__(self, deps: WorkerDeps, job: C.ClaimedJob):
        self.deps, self.job = deps, job
        self.started = deps.clock()
        self.model_key = job.input.get("model_key", "default")
        self.model_id = _model_id(deps, self.model_key)
        self.eval_run_id = job.input.get("eval_run_id")

    def fail(self, state: str, reason: str, **extra) -> None:
        C.finish(self.deps.engine, self.job, state, {"reason": reason, **extra})
        raise _Done()

    def check_deadline(self) -> None:
        if self.deps.clock() - self.started > self.deps.deadline_seconds:
            self.fail("failed", "DEADLINE_EXCEEDED")

    def stage(self, stage: str, system: str, user: str, max_tokens: int,
              evidence: str | None = None) -> str:
        deps, job = self.deps, self.job
        rhash = request_hash(self.model_id, system, user, max_tokens)
        cp = job.checkpoint.get(stage)
        if (cp and cp.get("request_hash") == rhash and cp.get("scope_hash") == job.scope_hash
                and cp.get("evidence_hash") == evidence):
            return cp["text"]  # completed stage reused: hashes still match
        if not deps.breaker.allow():
            self.fail("failed", "PROVIDER_UNAVAILABLE", stage=stage,
                      detail="circuit breaker open; no paid call admitted")
        try:
            slot = C.reserve_call(deps.engine, job.job_id, stage, self.model_id,
                                  _price_snapshot(deps, self.model_key, self.model_id), rhash,
                                  eval_run_id=self.eval_run_id, today=deps.admission_day(),
                                  daily_cap=deps.daily_cap)
        except C.AdmissionDenied as exc:
            deps.breaker.release_probe()
            self.fail("failed", exc.code, stage=stage)
        if not slot.new:
            if slot.state != "reserved":
                deps.breaker.release_probe()
            if slot.state in ("sent", "unknown"):
                self.fail("unknown", "RECONCILE_REQUIRED", stage=stage,
                          detail="a paid call may have run; resolve with ops recover-job")
            if slot.state == "complete":
                self.fail("unknown", "RECONCILE_REQUIRED", stage=stage,
                          detail="completed call does not match current inputs")
            if slot.state == "known_failure":
                self.fail("failed", "PROVIDER_REJECTED", stage=stage)
            # 'reserved' and never sent: safe to resume
        C.mark_call(deps.engine, slot.call_id, "sent")
        deps.hook(f"after_sent:{stage}")
        outcome = self._call(system, user, max_tokens)
        deps.hook(f"after_provider:{stage}")
        if outcome.kind == "known_failure" and outcome.retryable:
            deps.breaker.record_known_failure()
            deps.sleep(random.uniform(0.2, 1.0))  # one jittered retry, nothing was generated
            if deps.breaker.allow():
                outcome = self._call(system, user, max_tokens)
        if outcome.kind == "complete":
            deps.breaker.record_success()
            usage = {**outcome.usage, "provider": deps.provider.name}
            _complete_stage(deps, job, slot.call_id, usage, stage, {
                "text": outcome.text, "request_hash": rhash, "scope_hash": job.scope_hash,
                "evidence_hash": evidence, "usage": usage})
            return outcome.text
        if outcome.kind == "known_failure":
            deps.breaker.record_known_failure()
            C.mark_call(deps.engine, slot.call_id, "known_failure",
                        {"error_code": outcome.error_code, "no_generation": True})
            self.fail("failed", "PROVIDER_REJECTED", stage=stage, code=outcome.error_code)
        deps.breaker.release_probe()
        C.mark_call(deps.engine, slot.call_id, "unknown", {"error_code": outcome.error_code})
        self.fail("unknown", "PROVIDER_OUTCOME_UNKNOWN", stage=stage,
                  detail="not retried automatically; resolve with ops recover-job")

    def _call(self, system: str, user: str, max_tokens: int) -> Outcome:
        remaining = max(1.0, self.deps.deadline_seconds - (self.deps.clock() - self.started))
        return self.deps.provider.converse(model_id=self.model_id, system=system, user=user,
                                           max_tokens=max_tokens, timeout_seconds=remaining)


def _run_tools(conn, principal, job: C.ClaimedJob, plan: ToolPlan) -> list[dict]:
    payload = {"target": job.input["target"]}
    as_of = job.as_of.strftime("%Y-%m-%dT%H:%M:%S")
    results: list[dict] = []

    def run(name: str, raw: dict) -> dict:
        try:
            out = T.run_tool(conn, principal, name, {"as_of": as_of, **raw})
            return out.model_dump(mode="json")
        except T.NotVisible:
            return {"tool": name, "error": "not found or not visible"}
        except T.ToolInputError:
            return {"tool": name, "error": "invalid tool request"}

    for r in planner.admissible_requests(plan, payload):
        if r.tool == "get_order_snapshot":
            results.append(run(r.tool, {"order_id": r.target_id}))
        elif r.tool == "get_seller_exception_scope":
            results.append(run(r.tool, {"seller_id": r.target_id}))
        elif r.tool == "find_late_orders":
            seller = payload["target"]["target_id"] if payload["target"]["target_type"] == \
                "Seller" else None
            results.append(run(r.tool, {"seller_id": seller, "limit": 25} if seller
                               else {"limit": 25}))
        elif r.tool == "get_disruption_context":
            results.append(run(r.tool, {"target_type": r.target_type, "target_id": r.target_id,
                                        "scenario_id": job.scenario_id}))
        elif r.tool == "check_case_eligibility":
            snap = next((x for x in results if x.get("evidence_hash")), None)
            if snap is not None:
                results.append(run(r.tool, {
                    "target": payload["target"], "selected_order_ids": [r.target_id]
                    if r.target_type == "Order" else [], "snapshot_hash": snap["evidence_hash"]}))
    # Ontology traversal: Order -> Seller (fulfilled_by) -> related late orders, bounded.
    snapshots = [x for x in results if x.get("tool") == "get_order_snapshot" and "error" not in x]
    have = {x["seller"]["seller_id"] for x in results
            if x.get("tool") == "get_seller_exception_scope" and "error" not in x}
    for snap in snapshots[:1]:
        for seller in sorted({li["seller_id"] for li in snap["lines"]} - have)[:3]:
            results.append(run("get_seller_exception_scope", {"seller_id": seller}))
    return results


def deterministic_metrics(action: dict | None, tool_results: list[dict]) -> dict:
    """Counts and money for the proposed action, computed by code from evidence."""
    if not action:
        return {}
    selected = set(action["selected_order_ids"])
    if action["target_type"] == "Seller":
        scope = next(r for r in tool_results if r.get("tool") == "get_seller_exception_scope"
                     and r.get("seller", {}).get("seller_id") == action["target_id"])
        orders = [o for o in scope["orders"] if o["order_id"] in selected]
        return {"selected_orders": len({o["order_id"] for o in orders}),
                "seller_line_value_centavos": sum(o["seller_line_value_centavos"] for o in orders),
                "multi_seller_orders": sum(1 for o in orders if o["multi_seller"]),
                "seller_late_open_orders_total": scope["aggregates"]["late_open_orders"]}
    snap = next(r for r in tool_results if r.get("tool") == "get_order_snapshot"
                and r.get("order", {}).get("order_id") == action["target_id"])
    return {"selected_orders": 1, "order_value_centavos": snap["metrics"]["order_value_centavos"],
            "days_overdue": snap["order"]["days_overdue"],
            "seller_count": snap["metrics"]["seller_count"]}


def process_job(job_id: str, deps: WorkerDeps) -> str:
    """Return 'ack' after a durable terminal state, or 'retry' to leave the message."""
    claimed = C.claim(deps.engine, job_id, deps.lease_seconds)
    if claimed in ("terminal", "missing"):
        return "ack"  # duplicate delivery of a finished job, or a stray message
    if claimed == "leased":
        return "retry"
    job = claimed
    run = _Run(deps, job)
    try:
        with deps.engine.connect() as conn:
            principal = load_principal(conn, job.subject, job.batch_id)
        if not principal.provisioned or principal.scope_hash != job.scope_hash:
            run.fail("blocked", "SCOPE_CHANGED",
                     detail="seller grants changed after submission; regenerate the job")
        payload = {"target": job.input["target"], "question": job.input.get("question", ""),
                   "scenario_id": job.scenario_id}

        try:
            system, user = planner.build_prompt(payload)
        except StageInputTooLarge:
            run.fail("failed", "INPUT_TOO_LARGE", stage="planner")
        try:
            plan = parse_strict(run.stage("planner", system, user, planner.MAX_OUTPUT_TOKENS),
                                ToolPlan)
        except InvalidModelOutput:
            run.fail("failed", "INVALID_MODEL_OUTPUT", stage="planner")
        run.check_deadline()

        cp = job.checkpoint.get("tools")
        if cp and cp.get("scope_hash") == job.scope_hash and cp.get("plan") == plan.model_dump():
            tool_results = cp["results"]
        else:
            with deps.engine.connect() as conn:
                tool_results = _run_tools(conn, principal, job, plan)
            C.save_checkpoint(deps.engine, job, "tools", {
                "results": tool_results, "scope_hash": job.scope_hash,
                "plan": plan.model_dump(), "evidence_hash": evidence_hash(tool_results)})
        deps.hook("after_tools_checkpoint")
        ev_hash = evidence_hash(tool_results)
        run.check_deadline()

        try:
            system, user = analyst.build_prompt(payload, tool_results,
                                                flat=job.input.get("comparator") == "b1")
        except StageInputTooLarge:
            run.fail("failed", "INPUT_TOO_LARGE", stage="analyst")
        try:
            analysis = parse_strict(run.stage("analyst", system, user, analyst.MAX_OUTPUT_TOKENS,
                                              evidence=ev_hash), AnalystOutput)
        except InvalidModelOutput:
            run.fail("failed", "INVALID_MODEL_OUTPUT", stage="analyst")
        C.set_state(deps.engine, job, "validating")
        with deps.engine.connect() as conn:
            report = validate(conn, principal, analysis, tool_results, job.as_of)
        action = analysis.action.model_dump() if analysis.action else None
        result = {
            "plan": plan.model_dump(),
            "tools_run": [r.get("tool") for r in tool_results],
            "analysis": analysis.model_dump(),
            "validation": report.model_dump(),
            "metrics": deterministic_metrics(action, tool_results) if report.proposal_state
            != "none" else {},
            "snapshot_hashes": {f"{r['tool']}": r.get("evidence_hash") for r in tool_results
                                if r.get("evidence_hash")},
            "target_snapshot_hash": _target_hash(action, tool_results),
            "model_id": run.model_id,
            "comparator": job.input.get("comparator", "candidate"),
            "scenario_id": job.scenario_id,
        }
        C.finish(deps.engine, job, "ready", result, ev_hash)
        deps.hook("before_ack")
        return "ack"
    except _Done:
        deps.hook("before_ack")
        return "ack"
    except C.LeaseLost:
        return "retry"


def _target_hash(action: dict | None, tool_results: list[dict]) -> str | None:
    if not action:
        return None
    for r in tool_results:
        if action["target_type"] == "Order" and r.get("tool") == "get_order_snapshot" and \
                r.get("order", {}).get("order_id") == action["target_id"]:
            return r["evidence_hash"]
        if action["target_type"] == "Seller" and r.get("tool") == \
                "get_seller_exception_scope" and r.get("seller", {}).get("seller_id") == \
                action["target_id"]:
            return r["evidence_hash"]
    return None


class Worker:
    """Outbox relay plus a bounded consumer (at most two concurrent jobs) in one process."""

    def __init__(self, queue, deps: WorkerDeps, relay_seconds: float = RELAY_SECONDS):
        self.queue, self.deps, self.relay_seconds = queue, deps, relay_seconds
        self.stop = threading.Event()
        self.slots = threading.Semaphore(MAX_CONCURRENT_JOBS)
        self.pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)

    def handle(self, message) -> None:
        try:
            if process_job(message.body["job_id"], self.deps) == "ack":
                self.queue.delete(message.receipt)
        except Exception:  # unhandled: leave the message; it reaches the DLQ after 5 receives
            log.exception("job processing failed; message left for redelivery")
        finally:
            self.slots.release()

    def poll_once(self) -> int:
        free = 0
        while free < MAX_CONCURRENT_JOBS and self.slots.acquire(blocking=False):
            free += 1
        if free == 0:
            return 0
        messages = self.queue.receive(max_messages=free)
        for _ in range(free - len(messages)):
            self.slots.release()
        for m in messages:
            self.pool.submit(self.handle, m)
        return len(messages)

    def run(self) -> None:
        next_relay = 0.0
        while not self.stop.is_set():
            now = time.monotonic()
            if now >= next_relay:
                try:
                    relay_once(self.deps.engine, self.queue)
                except Exception:
                    log.exception("outbox relay failed")
                next_relay = now + self.relay_seconds
            if self.poll_once() == 0:
                self.stop.wait(0.5)
        self.pool.shutdown(wait=True)
