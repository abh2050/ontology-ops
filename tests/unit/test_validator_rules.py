import pytest

from ops.agents.validator import causal_sentences, evidence_index


@pytest.mark.parametrize("text", [
    "The delay was caused by the carrier backlog.",
    "Orders were late due to the seller stockout.",
    "Because of the storm event, deliveries slipped.",
    "The backlog resulted from CARRIER_B volume.",
    "Seller 0123456789abcdef0123456789abcdef is responsible for the delay.",
    "Late orders are DUE TO the regional weather event.",
])
def test_causal_claims_detected(text):
    assert causal_sentences(text)


@pytest.mark.parametrize("text", [
    "Orders are temporally and regionally consistent with a synthetic carrier backlog event.",
    "The data does not establish the cause of the delay.",
    "Seller fulfils lines on several late open orders.",
    "The delay was caused by unknown factors.",  # no seller, carrier, or event attached
])
def test_allowed_language(text):
    assert not causal_sentences(text)


def test_numbers_from_evidence_include_reais_formats():
    _, ids, numbers = evidence_index([{
        "tool": "get_seller_exception_scope",
        "evidence": [{"ref": "Seller:" + "a" * 32}],
        "aggregates": {"late_open_orders": 7, "seller_line_value_centavos": 123456},
    }])
    assert {"7", "123456", "1234.56", "1,234.56"} <= numbers
    assert "a" * 32 in ids


def test_thousands_separated_copies_allowed_but_wrong_values_not():
    _, _, numbers = evidence_index([{"evidence": [],
                                     "aggregates": {"seller_line_value_centavos": 162800}}])
    assert "162,800" in numbers and "162800" in numbers
    assert "162,801" not in numbers and "163,000" not in numbers


def test_order_action_may_omit_selection_and_seller_must_not():
    import pytest
    from pydantic import ValidationError

    from ops.agents.contracts import ProposedAction

    a = ProposedAction(kind="CreateInvestigation", target_type="Order", target_id="a" * 32,
                       reason_codes=["LATE_OPEN"])
    assert a.selected_order_ids == []
    with pytest.raises(ValidationError):
        ProposedAction(kind="CreateInvestigation", target_type="Seller", target_id="a" * 32,
                       reason_codes=["SELLER_GROUP"])


def test_select_all_on_order_target_is_accepted_by_contract():
    from ops.agents.contracts import ProposedAction

    a = ProposedAction(kind="CreateInvestigation", target_type="Order", target_id="a" * 32,
                       select_all_late_open=True, reason_codes=["LATE_OPEN"])
    assert a.select_all_late_open


@pytest.mark.parametrize("synthetic,citations,ok", [
    (False, ["Order:" + "a" * 32], False),
    (True, ["Order:" + "a" * 32], False),
    (True, ["DisruptionEvent:demo"], True),
    (False, ["DisruptionEvent:demo"], False),
    (True, [], False),
])
def test_synthetic_finding_requires_its_own_actual_synthetic_citation(
        synthetic, citations, ok, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace

    from ops.agents.contracts import AnalystOutput, Finding, ProposedAction
    from ops.agents.validator import validate

    monkeypatch.setattr("ops.agents.validator.T.check_case_eligibility",
                        lambda *args: SimpleNamespace(reasons=[]))

    output = AnalystOutput(findings=[Finding(
        kind="synthetic_context", text="Synthetic regional context; cause remains unknown.",
        evidence_refs=citations)], action=ProposedAction(
            kind="CreateInvestigation", target_type="Order", target_id="a" * 32,
            selected_order_ids=["a" * 32], reason_codes=["LATE_OPEN"]))
    evidence = [{"tool": "get_order_snapshot", "order": {"order_id": "a" * 32},
                 "evidence_hash": "0" * 64, "evidence": [
        {"ref": "Order:" + "a" * 32, "is_synthetic": False},
        {"ref": "DisruptionEvent:demo", "is_synthetic": synthetic},
    ]}]
    report = validate(None, None, output, evidence, datetime(2018, 3, 15, 23, 59, 59))
    assert report.ok is ok
    assert report.proposal_state == ("pending" if ok else "none")
    assert report.evidence_coverage == (1.0 if ok else 0.0)
    if not ok:
        assert {r.code for r in report.rejections} == {"UNRESOLVABLE_EVIDENCE"}
