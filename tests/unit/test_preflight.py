import sys
from pathlib import Path

from ops.preflight import _mask, cost_table

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))


def test_cost_table_is_labeled_estimate_inputs():
    rows = dict(cost_table())
    infra = sum(v for k, v in rows.items() if not k.startswith("Inference"))
    assert 60 < infra < 120  # within the spec's provisional band order of magnitude
    assert rows["Inference per 1,000 jobs (second_model_id)"] > rows[
        "Inference per 1,000 jobs (default_model_id)"]


def test_account_numbers_masked():
    account = "".join(str(d % 10) for d in range(1, 13))
    assert _mask(f"sts::{account}:assumed-role/x") == "sts::<account>:assumed-role/x"


def test_foundation_model_id_strips_profile_prefix():
    from stack import foundation_model_id

    assert foundation_model_id("global.vendor.model-v1:0") == "vendor.model-v1:0"
    assert foundation_model_id("vendor.model-v1:0") == "vendor.model-v1:0"
