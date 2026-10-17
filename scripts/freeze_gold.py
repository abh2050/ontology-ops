"""Freeze the reviewed gold set (spec 14.3). Run by the project owner after reviewing
every item, then commit data/gold/FREEZE.json together with the reviewed files.

  uv run python scripts/freeze_gold.py --reviewer "Full Name" [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

import yaml

from ops.evals.gold import FREEZE, GOLD, gold_hash, summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewer", required=True, help="identity of the owner who reviewed it")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()
    path = GOLD / "gold_set.yaml"
    gold = yaml.safe_load(path.read_text())
    gold["status"] = "frozen"
    gold["reviewer"] = args.reviewer
    gold["review_date"] = args.date
    path.write_text(yaml.safe_dump(gold, sort_keys=False, width=100, allow_unicode=True))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[1]).stdout.strip()
    meta = {"reviewer": args.reviewer, "review_date": args.date, "gold_hash": gold_hash(),
            "based_on_commit": commit, "summary": summary(gold)}
    FREEZE.write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    print("Commit data/gold/ now; ops eval verifies this hash before every run.")


if __name__ == "__main__":
    main()
