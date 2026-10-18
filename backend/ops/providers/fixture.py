"""Deterministic fixture provider for local runs and tests. No network, no cost.

It reads the same prompt Bedrock would receive and returns schema-shaped JSON, so
the whole pipeline (admission, parsing, validation) runs unchanged. Faults can be
injected per stage to exercise failure handling.
"""

from __future__ import annotations

import json
import threading
from collections import Counter

from ops.providers.base import Outcome

FAULTS = {"timeout", "throttle", "throttle_once", "reject", "invalid_json", "causal",
          "invented_id", "arithmetic", "draft"}


class FixtureProvider:
    name = "fixture"

    def __init__(self, faults: dict[str, str] | None = None):
        self.faults = dict(faults or {})
        unknown = set(self.faults.values()) - FAULTS
        if unknown:
            raise ValueError(f"unknown fault(s): {sorted(unknown)}")
        self.calls: Counter = Counter()
        self._lock = threading.Lock()

    def converse(self, *, model_id: str, system: str, user: str, max_tokens: int,
                 timeout_seconds: float) -> Outcome:
        payload = json.loads(user)
        stage = payload["stage"]
        with self._lock:
            self.calls[stage] += 1
            attempt = self.calls[stage]
        fault = self.faults.get(stage)
        if fault == "timeout":
            return Outcome("unknown", error_code="READ_TIMEOUT")
        if fault == "throttle" or (fault == "throttle_once" and attempt == 1):
            return Outcome("known_failure", error_code="ThrottlingException", no_generation=True,
                           retryable=True)
        if fault == "reject":
            return Outcome("known_failure", error_code="ValidationException", no_generation=True)
        if fault == "invalid_json":
            text = "Sure! Here is the plan: get the order."
        elif stage == "planner":
            text = json.dumps(self._plan(payload))
        else:
            text = json.dumps(self._analyse(payload, fault))
        usage = {"input_tokens": (len(system) + len(user)) // 4, "output_tokens": len(text) // 4,
                 "stop_reason": "end_turn"}
        return Outcome("complete", text=text, usage=usage)

    # ---- deterministic "model" behaviour -------------------------------------------

    @staticmethod
    def _plan(payload: dict) -> dict:
        target = payload["job"]["target"]
        if target is None:
            return {"requests": [{"tool": "find_late_orders"}],
                    "rationale": "Question job: query the bounded late order queue."}
        t, tid = target["target_type"], target["target_id"]
        scenario = payload["job"].get("scenario_enabled")
        if t == "Order":
            requests = [{"tool": "get_order_snapshot", "target_type": t, "target_id": tid}]
        else:
            requests = [{"tool": "get_seller_exception_scope", "target_type": t,
                         "target_id": tid}]
        if scenario:
            requests.append({"tool": "get_disruption_context", "target_type": t,
                             "target_id": tid})
        return {"requests": requests, "rationale": "Retrieve the target and its connected "
                                                   "evidence before analysis."}

    @staticmethod
    def _analyse(payload: dict, fault: str | None) -> dict:
        target = payload["job"]["target"] or {"target_type": "Question", "target_id": "queue"}
        evidence = payload["evidence"]
        findings: list[dict] = []
        action = None
        scopes = [e for e in evidence if e.get("tool") == "get_seller_exception_scope"
                  and "error" not in e]
        snapshots = [e for e in evidence if e.get("tool") == "get_order_snapshot"
                     and "error" not in e]
        contexts = [e for e in evidence if e.get("tool") == "get_disruption_context"]
        queues = [e for e in evidence if e.get("tool") == "find_late_orders" and "error" not in e]
        for q in queues:
            findings.append({"kind": "observed_fact",
                             "text": f"The visible queue has {q['aggregates']['late_open_orders']}"
                                     " late open orders.",
                             "evidence_refs": [r for r in q.get("evidence_refs", [])
                                               if r.startswith("Aggregate:")][:1]})

        for snap in snapshots:
            o = snap["order"]
            state = "late open" if o["late_open"] else "not late open"
            findings.append({
                "kind": "observed_fact",
                "text": f"Order {o['order_id']} is {state} at as_of, {o['days_overdue']} days "
                        "after its estimated delivery date.",
                "evidence_refs": [f"Order:{o['order_id']}"]})
        best = max(scopes, key=lambda s: (s["aggregates"]["late_open_orders"],
                                          s["seller"]["seller_id"]), default=None)
        for scope in scopes:
            sid = scope["seller"]["seller_id"]
            findings.append({
                "kind": "observed_fact",
                "text": f"Seller {sid} fulfils lines on {scope['aggregates']['late_open_orders']}"
                        " visible late open orders.",
                "evidence_refs": [f"Seller:{sid}"]})
        for ctx in contexts:
            for event in ctx.get("events", []):
                findings.append({
                    "kind": "synthetic_context",
                    "text": f"Some selected orders are temporally and regionally consistent with "
                            f"a synthetic {event['kind'].replace('_', ' ')} event.",
                    "evidence_refs": [r for r in ctx.get("evidence_refs", [])
                                      if event["event_id"] in r][:1]})
        findings.append({"kind": "unknown",
                         "text": "The data does not establish the cause of the delay.",
                         "evidence_refs": []})

        if best is not None and best["aggregates"]["late_open_orders"] >= 3:
            reasons = ["LATE_OPEN", "SELLER_GROUP", "CAUSE_UNKNOWN"]
            if any(o["multi_seller"] for o in best["orders"]):
                reasons.append("MULTI_SELLER")
            action = {"kind": "CreateInvestigation", "target_type": "Seller",
                      "target_id": best["seller"]["seller_id"], "selected_order_ids": [],
                      "select_all_late_open": True, "reason_codes": reasons}
        elif snapshots and snapshots[0]["order"]["late_open"]:
            oid = snapshots[0]["order"]["order_id"]
            action = {"kind": "CreateInvestigation", "target_type": "Order", "target_id": oid,
                      "selected_order_ids": [oid], "reason_codes": ["LATE_OPEN", "CAUSE_UNKNOWN"]}

        if fault == "draft" and snapshots and snapshots[0]["order"]["late_open"]:
            oid = snapshots[0]["order"]["order_id"]
            action = {"kind": "DraftCustomerUpdate", "target_type": "Order", "target_id": oid,
                      "selected_order_ids": [oid], "reason_codes": ["LATE_OPEN", "CAUSE_UNKNOWN"],
                      "draft_text": "Internal draft: the order is past its estimated delivery "
                                    "date and has no confirmed delivery yet. We do not know the "
                                    "cause and cannot promise a new date."}
        if fault == "causal":
            findings.insert(0, {"kind": "observed_fact",
                                "text": "The delay was caused by the seller's carrier backlog.",
                                "evidence_refs": []})
        elif fault == "invented_id":
            findings.insert(0, {"kind": "observed_fact",
                                "text": "Order 0123456789abcdef0123456789abcdef is also affected.",
                                "evidence_refs": ["Order:0123456789abcdef0123456789abcdef"]})
        elif fault == "arithmetic":
            findings.insert(0, {"kind": "observed_fact",
                                "text": "Total exposure across these orders is 98765.43 reais.",
                                "evidence_refs": [f"{target['target_type']}:"
                                                  f"{target['target_id']}"]})
        return {"findings": findings[:8], "action": action,
                "unresolved_questions": ["Which carrier handled each late order is not in the "
                                         "source data."]}
