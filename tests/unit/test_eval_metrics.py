from ops.evals.metrics import action_matches, score_item

A, B, C = "a" * 32, "b" * 32, "c" * 32
SELLER = "d" * 32


def seller_item():
    return {"category": "multi_object", "rubric": ["AFFECTED_SET_EXACT", "COUNT_EXACT",
                                                   "ACTION_ELIGIBLE", "NO_CAUSAL_CLAIM"],
            "expected": {"affected_order_ids": [A, B], "late_open_orders": 2},
            "acceptable_actions": [{"kind": "CreateInvestigation", "target_type": "Seller",
                                    "target_id": SELLER, "selected_order_ids": [A, B]}]}


def outcome(selected, causal=0, ok=True):
    return {"state": "ready", "metrics": {"selected_orders": len(selected)},
            "action": {"kind": "CreateInvestigation", "target_type": "Seller",
                       "target_id": SELLER, "selected_order_ids": selected},
            "validation": {"ok": ok, "proposal_state": "pending" if ok else "none",
                           "rejections": [], "causal_rejections": causal},
            "analysis": {"findings": []}}


def test_exact_selection_succeeds_with_full_precision_and_recall():
    s = score_item(seller_item(), outcome([A, B]))
    assert s["success"] and s["precision"] == 1.0 and s["recall"] == 1.0


def test_partial_selection_fails_and_lowers_recall():
    s = score_item(seller_item(), outcome([A]))
    assert not s["success"] and s["precision"] == 1.0 and s["recall"] == 0.5


def test_extra_order_lowers_precision():
    s = score_item(seller_item(), outcome([A, B, C]))
    assert not s["success"] and round(s["precision"], 3) == 0.667


def test_causal_claim_fails_item():
    s = score_item(seller_item(), outcome([A, B], causal=1))
    assert not s["rules"]["NO_CAUSAL_CLAIM"] and not s["success"]


def test_failed_job_fails_every_rule():
    o = outcome([A, B])
    o["state"] = "failed"
    assert not score_item(seller_item(), o)["success"]


def test_subset_acceptance_for_direct_items():
    acceptable = [{"kind": "CreateInvestigation", "target_type": "Seller", "target_id": SELLER,
                   "selected_must_include": [A], "selected_subset_of": [A, B]}]
    good = {"kind": "CreateInvestigation", "target_type": "Seller", "target_id": SELLER,
            "selected_order_ids": [A]}
    bad = {**good, "selected_order_ids": [B]}
    assert action_matches(good, acceptable) and not action_matches(bad, acceptable)
