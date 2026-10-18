"""Step-by-step deployment driver for the spec 15 sequence. Each step is explicit; paid
steps are run only after the owner approves them.

  uv run python scripts/deploy.py preflight
  uv run python scripts/deploy.py diff
  uv run python scripts/deploy.py infra                    # stack with services at 0
  uv run python scripts/deploy.py image --tag v1           # build arm64, push to ECR
  uv run python scripts/deploy.py upload-data              # five Olist CSVs -> s3 imports/
  uv run python scripts/deploy.py task migrate|import|seed --tag v1
  uv run python scripts/deploy.py release --tag v1         # services to 1
  uv run python scripts/deploy.py smoke

Public HTTPS comes from CloudFront's default domain; no domain or certificate (D-024).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import boto3
import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "configs" / "deploy.yaml").read_text())
OUTPUTS = ROOT / "cdk.out" / "outputs.json"
OLIST_FILES = ["olist_orders_dataset.csv", "olist_order_items_dataset.csv",
               "olist_sellers_dataset.csv", "olist_products_dataset.csv",
               "olist_customers_dataset.csv"]
IMPORT_STEPS = (
    "ops data import --directory data/fixtures --batch fixtures-v1 --download-date 2026-10-17"
    " && ops data import --directory s3://{bucket}/imports/olist --download-date 2026-10-17"
    " && ops data validate && ops data pick-as-of && ops data pick-as-of --batch fixtures-v1"
    " && ops scenario generate --seed 42 --scenario base-v1"
)


def sh(*cmd: str, **kw) -> None:
    print("+ " + " ".join(cmd), flush=True)
    rc = subprocess.call(list(cmd), cwd=ROOT, **kw)
    if rc != 0:
        sys.exit(rc)


def account() -> str:
    return boto3.client("sts", region_name=CFG["region"]).get_caller_identity()["Account"]


def cdk(action: str, *extra: str) -> None:
    env = {**os.environ, "CDK_DEFAULT_ACCOUNT": account(),
           "JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION": "1"}
    sh("npx", "--yes", "aws-cdk@2", action, CFG["stack_name"], *extra, env=env)


def outputs() -> dict:
    return json.loads(OUTPUTS.read_text())[CFG["stack_name"]]


def run_task(kind: str, tag: str) -> None:
    out = outputs()
    ecs = boto3.client("ecs", region_name=CFG["region"])
    task_def = {"migrate": out["OutMigrationTaskDef"], "import": out["OutImportTaskDef"],
                "seed": out["OutSeedTaskDef"]}[kind]
    container = {"migrate": "migrate", "import": "import", "seed": "seed"}[kind]
    overrides = {}
    if kind == "import":
        overrides = {"containerOverrides": [{"name": container, "command": [
            "sh", "-c", IMPORT_STEPS.format(bucket=out["OutBucketName"])]}]}
    resp = ecs.run_task(
        cluster=out["OutClusterName"], taskDefinition=task_def, launchType="FARGATE",
        networkConfiguration={"awsvpcConfiguration": {
            "subnets": out["OutPublicSubnets"].split(","),
            "securityGroups": [out["OutOneOffTaskSg"]], "assignPublicIp": "ENABLED"}},
        overrides=overrides, tags=[{"key": "project", "value": CFG["project_tag"]}],
        propagateTags="TASK_DEFINITION")
    task = resp["tasks"][0]["taskArn"]
    print(f"started {kind} task; waiting (image tag {tag})", flush=True)
    while True:
        desc = ecs.describe_tasks(cluster=out["OutClusterName"], tasks=[task])["tasks"][0]
        if desc["lastStatus"] == "STOPPED":
            code = desc["containers"][0].get("exitCode")
            print(f"{kind} task stopped: exit {code}, reason {desc.get('stoppedReason')}")
            sys.exit(0 if code == 0 else 1)
        time.sleep(10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["preflight", "diff", "infra", "image", "upload-data",
                                     "task", "release", "smoke"])
    ap.add_argument("kind", nargs="?", choices=["migrate", "import", "seed"])
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--fault", default=None,
                    help="release only: worker OPS_FAULT_INJECT drill value (omit to clear)")
    args = ap.parse_args()
    os.environ.setdefault("AWS_PROFILE", CFG["aws_profile"])
    if args.step == "preflight":
        sh("uv", "run", "ops", "preflight", "--cloud", "aws")
    elif args.step == "diff":
        cdk("diff", "-c", f"image_tag={args.tag}")
    elif args.step == "infra":
        cdk("deploy", "-c", f"image_tag={args.tag}", "--require-approval", "never",
            "--outputs-file", str(OUTPUTS))
    elif args.step == "image":
        repo = outputs()["OutRepositoryUri"]
        registry = repo.split("/")[0]
        pw = subprocess.run(["aws", "ecr", "get-login-password", "--region", CFG["region"]],
                            capture_output=True, text=True, check=True).stdout
        subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin", registry],
                       input=pw, text=True, check=True)
        sh("docker", "build", "--platform", "linux/arm64", "-t", f"{repo}:{args.tag}", ".")
        sh("docker", "push", f"{repo}:{args.tag}")
    elif args.step == "upload-data":
        bucket = outputs()["OutBucketName"]
        for f in OLIST_FILES:
            sh("aws", "s3", "cp", str(ROOT / "data" / "raw" / "olist" / f),
               f"s3://{bucket}/imports/olist/{f}", "--region", CFG["region"])
    elif args.step == "task":
        if not args.kind:
            sys.exit("task needs migrate, import, or seed")
        run_task(args.kind, args.tag)
    elif args.step == "release":
        fault = ["-c", f"fault_inject={args.fault}"] if args.fault else []
        cdk("deploy", "-c", f"image_tag={args.tag}", "-c", "services_running=true", *fault,
            "--require-approval", "never", "--outputs-file", str(OUTPUTS))
    elif args.step == "smoke":
        sh("uv", "run", "python", "scripts/smoke_https.py", "--outputs", str(OUTPUTS))


if __name__ == "__main__":
    main()
