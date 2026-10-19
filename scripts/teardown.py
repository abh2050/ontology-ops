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
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
import yaml
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
SDK_CONFIG = Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=20)


def inventory(project: str, region: str) -> list[str]:
    client = boto3.client("resourcegroupstaggingapi", region_name=region, config=SDK_CONFIG)
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


def snapshot_template(template: dict, choice: str) -> dict:
    """Change only the deletion policy of the one project DB, never its properties."""
    if choice not in {"keep", "delete"}:
        raise ValueError("an explicit snapshot choice is required")
    body = copy.deepcopy(template)
    databases = [r for r in body["Resources"].values()
                 if r.get("Type") == "AWS::RDS::DBInstance"]
    if len(databases) != 1:
        raise ValueError("refusing: expected exactly one RDS instance in the project stack")
    databases[0]["DeletionPolicy"] = "Snapshot" if choice == "keep" else "Delete"
    return body


def prepare_snapshot_policy(client, stack_name: str, project: str, choice: str) -> None:
    """Only called behind --execute; preserve the deployed template and parameters.

    CDK context supplied to `destroy` cannot update an already deployed deletion
    policy. Update the live template's one RDS DeletionPolicy first, verify the
    update, and only then let CDK destroy the stack.
    """
    stack = client.describe_stacks(StackName=stack_name)["Stacks"][0]
    if {t["Key"]: t["Value"] for t in stack.get("Tags", [])}.get("project") != project:
        raise ValueError("refusing: stack is not tagged for this project")
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE",
                                    "UPDATE_ROLLBACK_COMPLETE"}:
        raise ValueError("refusing: stack must be stable before changing its deletion policy")
    original = client.get_template(StackName=stack_name, TemplateStage="Original")["TemplateBody"]
    if isinstance(original, str):
        original = json.loads(original)
    template = snapshot_template(original, choice)
    if template != original:
        compact = json.dumps(template, separators=(",", ":"))
        if len(compact.encode()) > 51200:
            raise ValueError("refusing: template exceeds inline update limit; review separately")
        client.update_stack(
            StackName=stack_name, TemplateBody=compact,
            Parameters=[{"ParameterKey": p["ParameterKey"], "UsePreviousValue": True}
                        for p in stack.get("Parameters", [])],
            Capabilities=stack.get("Capabilities") or ["CAPABILITY_NAMED_IAM"])
        client.get_waiter("stack_update_complete").wait(
            StackName=stack_name, WaiterConfig={"Delay": 5, "MaxAttempts": 180})
        verified = client.get_template(
            StackName=stack_name, TemplateStage="Original")["TemplateBody"]
        if isinstance(verified, str):
            verified = json.loads(verified)
        if verified != template:
            raise ValueError("refusing: updated deletion policy was not verified")
    print(f"RDS deletion policy verified: {'Snapshot' if choice == 'keep' else 'Delete'}")


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
    cfn = boto3.client("cloudformation", region_name=cfg["region"], config=SDK_CONFIG)
    prepare_snapshot_policy(cfn, cfg["stack_name"], cfg["project_tag"], args.rds_snapshot)
    rc = subprocess.call(["npx", "--yes", "aws-cdk@2", "destroy", cfg["stack_name"], "--force"],
                         cwd=ROOT)
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
