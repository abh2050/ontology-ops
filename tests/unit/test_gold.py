import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from ops.cli import app
from ops.evals import gold as G

REPO = Path(__file__).resolve().parents[2]


def items():
    return G.load_gold()["items"]


def test_gold_shape_matches_spec():
    s = G.summary(G.load_gold())
    assert s["items"] == 60
    assert s["by_category"] == {"direct_object": 20, "multi_object": 20, "aggregate": 10,
                                "unanswerable": 10}
    assert s["requires_scenario"] >= 15
    assert s["real_only_answerable"] >= 20


def test_every_item_is_tagged_and_scored():
    for it in items():
        assert isinstance(it["requires_scenario"], bool)
        assert (it["scenario_id"] is not None) == it["requires_scenario"]
        assert it["rubric"] and it["question"] and it["as_of"] and it["subject"].startswith(
            "operator_")
        assert "NO_CAUSAL_CLAIM" in it["rubric"]


def test_planned_calls_within_ceiling():
    plan = G.load_gold()["run_plan"]
    assert plan["planned_model_calls"] <= plan["ceiling_calls"] == 1500


def test_canonical_queries_parse():
    assert set(G.canonical_queries()) == {"late_visible_orders", "order_facts",
                                          "seller_late_set", "late_aggregates",
                                          "event_overlaps"}


@pytest.mark.parametrize("name", ["security_scenarios.yaml", "reliability_scenarios.yaml"])
def test_scenarios_reference_existing_tests(name):
    data = yaml.safe_load((G.GOLD / name).read_text())
    expected = 20 if name.startswith("security") else 15
    assert len(data["scenarios"]) == expected
    for sc in data["scenarios"]:
        for node in sc["tests"]:
            path, func = node.split("::")
            source = (REPO / path).read_text()
            assert re.search(rf"def {re.escape(func)}\(", source), node


def test_eval_refuses_draft_gold_set():
    result = CliRunner().invoke(app, ["eval", "--suite", "frozen"])
    assert result.exit_code == 1 and "refusing to evaluate" in result.output


def test_freeze_hash_detects_changes(tmp_path, monkeypatch):
    copy = tmp_path / "gold"
    shutil.copytree(G.GOLD, copy)
    monkeypatch.setattr(G, "GOLD", copy)
    monkeypatch.setattr(G, "FREEZE", copy / "FREEZE.json")
    data = yaml.safe_load((copy / "gold_set.yaml").read_text())
    data["status"] = "frozen"
    (copy / "gold_set.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    (copy / "FREEZE.json").write_text(json.dumps({"reviewer": "Owner", "review_date": "x",
                                                  "gold_hash": G.gold_hash()}))
    assert G.verify_frozen()["reviewer"] == "Owner"
    with open(copy / "rubric.md", "a") as fh:
        fh.write("\nedited after freeze\n")
    with pytest.raises(G.GoldNotFrozen, match="hash mismatch"):
        G.verify_frozen()
    (copy / "FREEZE.json").write_text(json.dumps({"gold_hash": G.gold_hash()}))
    with pytest.raises(G.GoldNotFrozen, match="reviewer"):
        G.verify_frozen()
