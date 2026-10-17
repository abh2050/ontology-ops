"""Teardown of project-tagged AWS resources (spec 19). Dry run by default.

  uv run python scripts/teardown.py                 # dry run: print the tagged inventory
  uv run python scripts/teardown.py --execute --rds-snapshot keep|delete

Acts only on resources tagged project=<project_tag>. The RDS snapshot choice is
explicit: 'keep' retains a final snapshot (it is NOT free; storage is billed), 'delete'
skips it. After destroy it re-lists tagged resources and reports what remains. Paid
resources are reported stopped only after that verification.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import boto3
import yaml

ROOT = Path(__file__).resolve().parents[1]


def inventory(project: str, region: str) -> list[str]:
    client = boto3.client("resourcegroupstaggingapi", region_name=region)
    arns = []
    for page in client.get_paginator("get_resources").paginate(
            TagFilters=[{"Key": "project", "Values": [project]}]):
        arns += [r["ResourceARN"] for r in page["ResourceTagMappingList"]]
    return sorted(arns)


def masked(arn: str) -> str:
    parts = arn.split(":")
    if len(parts) > 4 and parts[4].isdigit():
        parts[4] = "<account>"
    return ":".join(parts)


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "deploy.yaml").read_text())
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--rds-snapshot", choices=["keep", "delete"])
    args = ap.parse_args()
    os.environ.setdefault("AWS_PROFILE", cfg.get("aws_profile") or "default")
    try:
        before = inventory(cfg["project_tag"], cfg["region"])
    except Exception as exc:  # noqa: BLE001
        print(f"cannot list tagged resources: {type(exc).__name__}: {exc}")
        return 1
    print(f"Tagged inventory (project={cfg['project_tag']}, {cfg['region']}): {len(before)}")
    for arn in before:
        print("  " + masked(arn))
    if not args.execute:
        print("\nDry run only. Re-run with --execute --rds-snapshot keep|delete to destroy.")
        return 0
    if args.rds_snapshot is None:
        print("refusing: choose --rds-snapshot keep or delete explicitly")
        return 1
    ctx = ["-c", f"rds_final_snapshot={args.rds_snapshot}"]
    rc = subprocess.call(["npx", "--yes", "aws-cdk@2", "destroy", cfg["stack_name"], "--force",
                          *ctx], cwd=ROOT)
    after = inventory(cfg["project_tag"], cfg["region"])
    print(f"\nRemaining tagged resources after destroy: {len(after)}")
    for arn in after:
        print("  " + masked(arn))
    if args.rds_snapshot == "keep":
        print("Retained: final RDS snapshot (storage billed per GB-month until deleted).")
    print("Verify billing in Cost Explorer; resources are reported stopped only when the "
          "remaining list is empty or every item is an intentional retention.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
