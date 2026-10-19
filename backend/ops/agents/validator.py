"""Deterministic validator that runs after the analyst (spec 10.4 and 10.5). Code, not an LLM.

Rejections: invented IDs, unresolvable evidence, unauthorized objects, incorrect
(model-authored) arithmetic, invalid action targets, stale evidence, and
unsupported causal claims. A causal rejection sets the proposal to needs_review.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from ops.agents.contracts import AnalystOutput, Rejection, ValidationReport
from ops.queries import tools as T
from ops.queries.scope import Principal

HEX32 = re.compile(r"\b[0-9a-f]{32}\b")
ISO_DT = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])")
CAUSAL = re.compile(r"\b(caused|causes|cause[sd]? by|due to|because of|resulted from|"
                    r"results? from|responsible for)\b", re.IGNORECASE)
SUBJECT_WORDS = re.compile(r"\b(seller|sellers|carrier|carriers|event|events|backlog|stockout|"
                           r"outage|weather|storm|disruption|advisory|CARRIER_[A-E])\b",
                           re.IGNORECASE)
SENTENCE = re.compile(r"[^.!?;\n]+")


def _walk(value: Any):
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _walk(v)
    else:
        yield value


def evidence_index(tool_results: list[dict]) -> tuple[set[str], set[str], set[str]]:
    """Return (evidence refs, known IDs, allowed numeric strings) from tool results."""
    refs: set[str] = set()
    ids: set[str] = set()
    numbers: set[str] = set()
    for result in tool_results:
        for ref in result.get("evidence", []):
            refs.add(ref["ref"])
        blob = json.dumps(result)
        ids.update(HEX32.findall(blob))
        for v in _walk(result):
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                numbers.update({str(v), f"{v:,}"})  # copied values may carry separators
                if abs(v) >= 100:  # centavos may be quoted as reais
                    reais = Decimal(v) / 100
                    numbers.update({f"{reais:.2f}", f"{reais:,.2f}",
                                    f"{reais:.2f}".replace(".", ",")})
            elif isinstance(v, str):
                numbers.update(m for m in NUMBER.findall(ISO_DT.sub(" ", HEX32.sub(" ", v))))
    return refs, ids, numbers


def causal_sentences(text: str) -> list[str]:
    hits = []
    for sentence in SENTENCE.findall(text):
        if CAUSAL.search(sentence) and (SUBJECT_WORDS.search(sentence) or HEX32.search(sentence)):
            hits.append(sentence.strip())
    return hits


def _texts(out: AnalystOutput) -> list[str]:
    texts = [f.text for f in out.findings] + list(out.unresolved_questions)
    if out.action and out.action.draft_text:
        texts.append(out.action.draft_text)
    return texts


def validate(conn: Connection, principal: Principal, out: AnalystOutput,
             tool_results: list[dict], as_of) -> ValidationReport:
    refs, ids, numbers = evidence_index(tool_results)
    synthetic_refs = {ref["ref"] for result in tool_results
                      for ref in result.get("evidence", [])
                      if ref.get("is_synthetic") is True}
    rejections: list[Rejection] = []

    def reject(code: str, detail: str) -> None:
        rejections.append(Rejection(code=code, detail=detail[:200]))

    # invented IDs anywhere in model output
    model_blob = out.model_dump_json()
    invented = sorted(set(HEX32.findall(model_blob)) - ids)
    if invented:
        reject("INVENTED_ID", f"{len(invented)} identifier(s) not present in tool results")

    # evidence references must resolve; coverage over factual findings
    factual = [f for f in out.findings if f.kind != "unknown"]
    covered = 0
    for f in out.findings:
        bad = [r for r in f.evidence_refs if r not in refs]
        if bad:
            reject("UNRESOLVABLE_EVIDENCE", f"{len(bad)} evidence reference(s) do not resolve")
        unsupported_synthetic = (f.kind == "synthetic_context"
                                 and not synthetic_refs.intersection(f.evidence_refs))
        if unsupported_synthetic:
            reject("UNRESOLVABLE_EVIDENCE", "synthetic context must cite synthetic evidence "
                   "returned by an authorized tool")
        if f.kind != "unknown" and f.evidence_refs and not bad and not unsupported_synthetic:
            covered += 1
    coverage = covered / len(factual) if factual else 1.0

    # model-authored arithmetic: every number must be copied from deterministic evidence
    for text in _texts(out):
        cleaned = ISO_DT.sub(" ", HEX32.sub(" ", text))
        for n in NUMBER.findall(cleaned):
            if n not in numbers:
                reject("INCORRECT_ARITHMETIC", "a number in the analysis is not a deterministic "
                       "evidence value")
                break

    # causal language attached to a seller, carrier, or event
    causal = [s for text in _texts(out) for s in causal_sentences(text)]
    for _ in causal:
        reject("UNSUPPORTED_CAUSAL_CLAIM", "causal construction attached to a seller, carrier, "
               "or event")

    # action target, authorization, eligibility, and staleness
    action = out.action
    if action is not None:
        if action.kind == "DraftCustomerUpdate" and (action.target_type != "Order"
                                                      or not action.draft_text):
            reject("INVALID_ACTION_TARGET", "a draft targets one order and carries draft text")
        if f"{action.target_type}:{action.target_id}" not in refs:
            reject("UNRESOLVABLE_EVIDENCE", "action target has no supporting tool evidence")
        if not action.selected_order_ids:
            reject("INVALID_ACTION_TARGET", "the action selects no orders the evidence supports")
            return _report(rejections, out, coverage, causal)
        supporting = next((r for r in tool_results if _is_snapshot_of(r, action)), None)
        target = T.Target(target_type=action.target_type, target_id=action.target_id)
        snapshot_hash = supporting["evidence_hash"] if supporting else "0" * 64
        elig = T.check_case_eligibility(conn, principal, T.EligibilityInput(
            as_of=as_of, target=target, kind=action.kind,
            selected_order_ids=list(action.selected_order_ids), snapshot_hash=snapshot_hash))
        mapping = {
            "TARGET_NOT_VISIBLE": "UNAUTHORIZED_OBJECT",
            "STALE_SNAPSHOT": "STALE_EVIDENCE",
            "SELECTED_ORDER_NOT_ELIGIBLE": "INVALID_ACTION_TARGET",
            "ORDER_TARGET_SELECTS_ONLY_ITSELF": "INVALID_ACTION_TARGET",
            "DRAFT_TARGET_MUST_BE_ORDER": "INVALID_ACTION_TARGET",
            "DUPLICATE_SELECTED_ORDER": "INVALID_ACTION_TARGET",
            "CASE_ALREADY_EXISTS": "INVALID_ACTION_TARGET",
        }
        for reason in elig.reasons:
            if supporting is None and reason == "STALE_SNAPSHOT":
                continue  # already reported as unresolvable evidence
            reject(mapping[reason], reason)

    return _report(rejections, out, coverage, causal)


def _report(rejections, out: AnalystOutput, coverage: float, causal: list) -> ValidationReport:
    action = out.action
    codes = {r.code for r in rejections}
    if action is None:
        state = "none"
    elif "UNSUPPORTED_CAUSAL_CLAIM" in codes:
        state = "needs_review"
    elif codes:
        state = "none"
    else:
        state = "pending"
    return ValidationReport(ok=not rejections, rejections=rejections,
                            causal_rejections=len(causal), evidence_coverage=round(coverage, 4),
                            proposal_state=state)


def _is_snapshot_of(result: dict, action) -> bool:
    if action.target_type == "Order":
        return (result.get("tool") == "get_order_snapshot"
                and result.get("order", {}).get("order_id") == action.target_id)
    return (result.get("tool") == "get_seller_exception_scope"
            and result.get("seller", {}).get("seller_id") == action.target_id)
