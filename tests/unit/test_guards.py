"""Repository guards: order_status isolation, model IDs, and no AWS identifiers."""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ISOLATED = ["backend/ops/queries", "backend/ops/agents", "backend/ops/commands"]


def references_order_status(source: str) -> bool:
    return re.search(r"order_status", source, re.IGNORECASE) is not None


def test_scanner_detects_reference():
    assert references_order_status("SELECT o.ORDER_STATUS FROM orders o")
    assert not references_order_status("SELECT o.delivered_at FROM orders o")


@pytest.mark.parametrize("package", ISOLATED)
def test_order_status_not_referenced(package):
    root = REPO / package
    assert root.is_dir(), f"{package} must exist so the guard is meaningful"
    offenders = [
        str(p.relative_to(REPO))
        for p in root.rglob("*")
        if p.is_file() and p.suffix in {".py", ".sql", ".yaml", ".json", ".txt", ".md"}
        and references_order_status(p.read_text(errors="ignore"))
    ]
    assert offenders == [], f"order_status referenced in {offenders}"


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [REPO / line for line in out.splitlines() if (REPO / line).is_file()]


def test_model_ids_only_in_models_yaml():
    cfg = yaml.safe_load((REPO / "configs" / "models.yaml").read_text())
    ids = [cfg["default_model_id"], cfg["second_model_id"]]
    code_roots = ("backend/", "frontend/src/", "infra/", "scripts/", "tests/", "configs/",
                  ".github/workflows/")
    offenders = []
    for path in _tracked_files():
        rel = str(path.relative_to(REPO))
        if not rel.startswith(code_roots) or rel == "configs/models.yaml":
            continue
        text = path.read_text(errors="ignore")
        if any(i in text for i in ids) or re.search(r"\bnova-[0-9a-z-]+-v\d", text):
            offenders.append(rel)
    assert offenders == []


def test_no_arns_or_account_numbers():
    offenders = []
    for path in _tracked_files():
        if path.name in {"uv.lock", "package-lock.json"} or path.suffix in {".png", ".svg"}:
            continue
        text = path.read_text(errors="ignore")
        # Concrete ARNs carry an account number; templates built from variables do not.
        concrete_arn = re.search(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:\d{12}:", text)
        if concrete_arn or re.search(r"(?<![\w.])\d{12}(?![\w.])", text):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], offenders
