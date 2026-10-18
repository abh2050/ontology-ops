"""Typed contracts for the two bounded AI stages (spec 10.2 and 10.3).

The planner returns a ToolPlan with at most three allowlisted tool requests. It
names tools and targets only; the server supplies actor, batch, as_of, scenario,
and limits. The analyst returns findings plus an optional action. Counts and
money never come from the model; code computes them from evidence metrics.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Hex32 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
ToolName = Literal["get_order_snapshot", "find_late_orders", "get_seller_exception_scope",
                   "check_case_eligibility", "get_disruption_context"]
Text = Annotated[str, StringConstraints(min_length=1, max_length=400)]
_Strict = ConfigDict(extra="forbid", frozen=True)


class ToolRequest(BaseModel):
    model_config = _Strict
    tool: ToolName
    target_type: Literal["Order", "Seller"] | None = None
    target_id: Hex32 | None = None


class ToolPlan(BaseModel):
    model_config = _Strict
    requests: list[ToolRequest] = Field(min_length=1, max_length=3)
    rationale: Text


class Finding(BaseModel):
    model_config = _Strict
    kind: Literal["observed_fact", "synthetic_context", "unknown"]
    text: Text
    evidence_refs: list[Annotated[str, StringConstraints(max_length=120)]] = Field(
        default_factory=list, max_length=20)


class ProposedAction(BaseModel):
    model_config = _Strict
    kind: Literal["CreateInvestigation", "DraftCustomerUpdate"]
    target_type: Literal["Order", "Seller"]
    target_id: Hex32
    selected_order_ids: list[Hex32] = Field(default_factory=list, max_length=100)
    # Seller groups: let the server select every authorized late open order of the seller
    # from deterministic evidence, so the model never has to enumerate IDs.
    select_all_late_open: bool = False
    reason_codes: list[Literal["LATE_OPEN", "SELLER_GROUP", "MULTI_SELLER",
                               "SYNTHETIC_CONTEXT_CONSISTENT", "CAUSE_UNKNOWN"]] = Field(
        min_length=1, max_length=5)
    draft_text: Annotated[str, StringConstraints(max_length=600)] | None = None

    @model_validator(mode="after")
    def _selection(self):
        # For an Order target the selection is always that order; the server fills it.
        if (not self.select_all_late_open and not self.selected_order_ids
                and self.target_type != "Order"):
            raise ValueError("selected_order_ids is required unless select_all_late_open")
        return self


class AnalystOutput(BaseModel):
    model_config = _Strict
    findings: list[Finding] = Field(min_length=1, max_length=8)
    action: ProposedAction | None = None
    unresolved_questions: list[Text] = Field(default_factory=list, max_length=5)


class Rejection(BaseModel):
    model_config = _Strict
    code: Literal["INVENTED_ID", "UNRESOLVABLE_EVIDENCE", "UNAUTHORIZED_OBJECT",
                  "INCORRECT_ARITHMETIC", "INVALID_ACTION_TARGET", "STALE_EVIDENCE",
                  "UNSUPPORTED_CAUSAL_CLAIM"]
    detail: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    rejections: list[Rejection]
    causal_rejections: int
    evidence_coverage: float  # share of factual findings with valid evidence refs
    proposal_state: Literal["pending", "needs_review", "none"]
