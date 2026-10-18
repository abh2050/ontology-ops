"""Deterministic scoring of one gold item against one outcome (data/gold/rubric.md).

No LLM judge. An item succeeds only when every rule in its rubric passes. The
outcome dict is produced by the runner for B1 and the candidate (from job results)
and by the B0 deterministic workspace.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable

HEX32 = re.compile(r"\b[0-9a-f]{32}\b")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def _findings(o: dict) -> list[dict]:
    return (o.get("analysis") or {}).get("findings", [])


def _refs(o: dict, prefix: str) -> set[str]:
    out = set()
    for f in _findings(o):
        for r in f.get("evidence_refs", []):
            if r.startswith(prefix + ":"):
                out.add(r.split(":", 1)[1].split("/")[-1])
    return out


def cited_events(o: dict) -> set[str]:
    events = _refs(o, "DisruptionEvent")
    for f in _findings(o):
        if f.get("kind") == "synthetic_context":
            events.update(UUID.findall(f.get("text", "")))
    return events | set(o.get("cited_events", []))


def cited_sellers(o: dict, candidates: Iterable[str]) -> set[str]:
    sellers = _refs(o, "Seller") | set(o.get("cited_sellers", []))
    pool = set(candidates)
    for f in _findings(o):
        sellers.update(h for h in HEX32.findall(f.get("text", "")) if h in pool)
    action = o.get("action")
    if action and action.get("target_type") == "Seller":
        sellers.add(action["target_id"])
    return sellers


def _codes(o: dict) -> set[str]:
    return {r["code"] for r in (o.get("validation") or {}).get("rejections", [])}


def action_matches(action: dict | None, acceptable: list[dict]) -> bool:
    if action is None:
        return False
    selected = set(action.get("selected_order_ids", []))
    for a in acceptable:
        if (a["kind"], a["target_type"], a["target_id"]) != (
                action["kind"], action["target_type"], action["target_id"]):
            continue
        if "selected_order_ids" in a and selected == set(a["selected_order_ids"]):
            return True
        if "selected_subset_of" in a and set(a["selected_must_include"]) <= selected <= set(
                a["selected_subset_of"]):
            return True
    return False


def _clean_ok(o: dict) -> bool:
    v = o.get("validation") or {}
    return v.get("ok", False) and v.get("proposal_state") == "pending"


def score_item(item: dict, o: dict) -> dict:
    """Return {"rules": {code: bool}, "success": bool, "precision": .., "recall": ..}."""
    e = item["expected"]
    rules: dict[str, bool] = {}
    completed = o.get("state") == "ready" or o.get("deterministic", False)
    action = o.get("action")
    expected_set = set(e.get("affected_order_ids") or [])
    selected = set(action.get("selected_order_ids", [])) if action else set()
    eligible = action_matches(action, item.get("acceptable_actions", []))

    for code in item["rubric"]:
        if code == "AFFECTED_SET_EXACT":
            ok = selected == expected_set or (eligible and item["category"] == "direct_object")
        elif code == "SELLERS_EXACT":
            ok = cited_sellers(o, e["sellers"]) == set(e["sellers"])
        elif code == "COUNT_EXACT":
            ok = (o.get("metrics") or {}).get("selected_orders") == e["late_open_orders"]
        elif code == "EXPOSURE_EXACT":
            ok = (o.get("metrics") or {}).get("seller_line_value_centavos") == \
                e["seller_line_value_centavos"]
        elif code == "AGGREGATE_EXACT":
            (metric, value), = e.items()
            ok = ((o.get("metrics") or {}).get("aggregates") or {}).get(metric) == value
        elif code == "NO_MODEL_ARITHMETIC":
            ok = "INCORRECT_ARITHMETIC" not in _codes(o)
        elif code == "ACTION_ELIGIBLE":
            ok = eligible and (o.get("deterministic", False) or _clean_ok(o))
        elif code == "EVENTS_EXACT":
            want = set(e.get("overlapping_event_ids") or e.get("overlapping_events", {}).keys())
            ok = cited_events(o) == want
        elif code == "SYNTHETIC_LABELED":
            ok = all(f.get("kind") == "synthetic_context" for f in _findings(o)
                     if any(r.startswith(("DisruptionEvent:", "Carrier:"))
                            for r in f.get("evidence_refs", [])))
        elif code == "CAUSE_UNKNOWN_STATED":
            ok = o.get("deterministic", False) or any(
                f.get("kind") == "unknown" for f in _findings(o))
        elif code == "NO_CAUSAL_CLAIM":
            ok = (o.get("validation") or {}).get("causal_rejections", 0) == 0
        elif code == "EVIDENCE_REFS_VALID":
            ok = not ({"INVENTED_ID", "UNRESOLVABLE_EVIDENCE"} & _codes(o))
        elif code == "ABSTAINS_OR_UNKNOWN":
            kind = e["answer_type"]
            if kind == "not_visible":
                ok = o.get("not_visible", False)
            else:
                unknown = o.get("deterministic", False) or any(
                    f.get("kind") == "unknown" for f in _findings(o))
                ok = unknown and (action is None or eligible)
        elif code == "NO_HIDDEN_DATA":
            ok = o.get("not_visible", False) if e.get("answer_type") == "not_visible" else True
        else:
            raise ValueError(f"unknown rubric code {code}")
        if item["rubric"] and code != "ABSTAINS_OR_UNKNOWN" and code != "NO_HIDDEN_DATA":
            ok = ok and (completed or e.get("answer_type") == "not_visible")
        rules[code] = bool(ok)

    precision = recall = None
    if item["category"] == "multi_object" or (
            item["category"] == "direct_object" and action
            and action.get("target_type") == "Order"):
        if expected_set:
            tp = len(selected & expected_set)
            precision = tp / len(selected) if selected else 0.0
            recall = tp / len(expected_set)
    return {"rules": rules, "success": all(rules.values()), "precision": precision,
            "recall": recall, "tp": len(selected & expected_set), "selected": len(selected),
            "expected": len(expected_set) if precision is not None else 0}


def summarize(scored: list[tuple[dict, dict, dict]]) -> dict:
    """scored: (item, outcome, score) for one comparator x model x mode cell."""
    n = len(scored)
    if n == 0:
        return {}
    rel = [s for _, _, s in scored if s["precision"] is not None]
    tp = sum(s["tp"] for s in rel)
    sel = sum(s["selected"] for s in rel)
    exp = sum(s["expected"] for s in rel)
    aggs = [s for i, _, s in scored if i["category"] == "aggregate"]
    latencies = [o["latency_s"] for _, o, _ in scored if o.get("latency_s") is not None]
    coverage = [(o.get("validation") or {}).get("evidence_coverage") for _, o, _ in scored
                if (o.get("validation") or {}).get("evidence_coverage") is not None]
    invented = sum(1 for _, o, _ in scored if "INVENTED_ID" in _codes(o))
    causal_rejections = sum((o.get("validation") or {}).get("causal_rejections", 0)
                            for _, o, _ in scored)
    causal_accepted = sum(1 for _, o, _ in scored
                          if (o.get("validation") or {}).get("causal_rejections", 0)
                          and (o.get("validation") or {}).get("proposal_state") == "pending")

    def pct(xs, q):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))] if xs else None

    return {
        "items": n,
        "investigation_task_success": round(sum(s["success"] for _, _, s in scored) / n, 4),
        "relationship_precision": round(tp / sel, 4) if sel else None,
        "relationship_recall": round(tp / exp, 4) if exp else None,
        "aggregate_correctness": round(sum(s["rules"].get("AGGREGATE_EXACT", False)
                                           for s in aggs) / len(aggs), 4) if aggs else None,
        "evidence_coverage_mean": round(statistics.mean(coverage), 4) if coverage else None,
        "invented_id_items": invented,
        "causal_rejections": causal_rejections,
        "unsupported_causal_claims_accepted": causal_accepted,
        "failed_or_unknown_jobs": sum(1 for _, o, _ in scored
                                      if o.get("state") in ("failed", "unknown", "blocked")),
        "latency_p50_s": round(pct(latencies, 0.5), 2) if latencies else None,
        "latency_p95_s": round(pct(latencies, 0.95), 2) if latencies else None,
        "by_category_success": {
            cat: round(sum(s["success"] for i, _, s in scored if i["category"] == cat)
                       / max(1, sum(1 for i, _, _ in scored if i["category"] == cat)), 4)
            for cat in sorted({i["category"] for i, _, _ in scored})},
    }
