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
