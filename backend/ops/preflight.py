"""ops preflight --cloud aws (spec 15). Fails with a clear message when any input is missing.

Checks: account and region match configuration, the CloudFront default-domain HTTPS
entry point (no custom domain or ACM certificate, D-024), access to
every configured Bedrock model from the project region (one tiny call each), ECR repository
exists or can be created, required services are not blocked by policy, CDK bootstrap,
and project tags on every taggable resource in the synthesized template. Prints an
estimated monthly cost table from configs/price_card.yaml, every value an estimate.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ops.settings import REPO_ROOT, load_config

PROBES = {
    "ec2 (VPC, subnets, security groups)": ("ec2", "describe_availability_zones", {}),
    "ecs (Fargate cluster and services)": ("ecs", "list_clusters", {"maxResults": 1}),
    "rds (PostgreSQL 16)": ("rds", "describe_db_instances", {"MaxRecords": 20}),
    "elbv2 (Application Load Balancer)": ("elbv2", "describe_load_balancers", {"PageSize": 1}),
    "cognito-idp (user pool)": ("cognito-idp", "list_user_pools", {"MaxResults": 1}),
    "sqs (queue and DLQ)": ("sqs", "list_queues", {"MaxResults": 1}),
    "ecr (image repository)": ("ecr", "describe_repositories", {"maxResults": 1}),
    "cloudformation (CDK deploys)": ("cloudformation", "list_stacks", {}),
    "secretsmanager (credentials)": ("secretsmanager", "list_secrets", {"MaxResults": 1}),
    "s3 (imports and exports)": ("s3", "list_buckets", {}),
    "logs (CloudWatch)": ("logs", "describe_log_groups", {"limit": 1}),
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _mask(text: str) -> str:
    import re

    return re.sub(r"\b\d{12}\b", "<account>", text)


def _client(service: str, region: str):
    import boto3
    from botocore.config import Config

    return boto3.client(service, region_name=region,
                        config=Config(retries={"total_max_attempts": 2, "mode": "standard"}))


def _err(exc: Exception) -> str:
    from botocore.exceptions import ClientError

    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        msg = exc.response.get("Error", {}).get("Message", "")
        scp = " (explicit deny in a service control policy)" if "service control policy" in msg \
            else ""
        return f"{code}{scp}"
    return type(exc).__name__


def check_identity(cfg: dict) -> tuple[Check, str | None]:
    try:
        ident = _client("sts", cfg["region"]).get_caller_identity()
    except Exception as exc:  # noqa: BLE001
        return Check("AWS credentials", False, f"cannot resolve identity: {_err(exc)}; run "
                     f"`aws login` and set AWS_PROFILE={cfg.get('aws_profile')}"), None
    account = ident["Account"]
    expected = os.environ.get("OPS_AWS_ACCOUNT_ID")
    if not expected:
        return Check("account and region match configuration", False,
                     "set OPS_AWS_ACCOUNT_ID to the intended account (not committed); "
                     f"resolved region {cfg['region']}"), account
    ok = expected == account
    return Check("account and region match configuration", ok,
                 f"account {'matches' if ok else 'DOES NOT match'} OPS_AWS_ACCOUNT_ID; region "
                 f"{cfg['region']}"), account


def check_public_endpoint(cfg: dict) -> Check:
    """No custom domain (D-024): HTTPS comes from CloudFront's default domain and certificate."""
    try:
        _client("cloudfront", "us-east-1").list_functions(MaxItems="1")
    except Exception as exc:  # noqa: BLE001
        return Check("public HTTPS endpoint (CloudFront default domain)", False, _err(exc))
    return Check("public HTTPS endpoint (CloudFront default domain)", True,
                 "CloudFront API allowed; app URL and Cognito callback are "
                 "https://<distribution>.cloudfront.net (stack output OutAppUrl)")


def check_models(models: dict) -> list[Check]:
    from ops.providers.bedrock import BedrockProvider

    region = models["region"]
    provider = BedrockProvider(region)
    out = []
    for key in ("default_model_id", "second_model_id"):
        mid = models[key]
        detail = []
        if mid.split(".", 1)[0] in {"global", "us", "eu", "apac"}:
            try:
                prof = _client("bedrock", region).get_inference_profile(
                    inferenceProfileIdentifier=mid)
                detail.append(f"profile {prof['status']}")
            except Exception as exc:  # noqa: BLE001
                out.append(Check(f"Bedrock access: {mid}", False, f"profile lookup {_err(exc)}"))
                continue
        outcome = provider.converse(model_id=mid, system="Reply with the single word OK.",
                                    user="OK?", max_tokens=5, timeout_seconds=30)
        ok = outcome.kind == "complete"
        detail.append(f"invoked from {region}: {outcome.kind}"
                      + (f" ({outcome.error_code})" if outcome.error_code else "")
                      + (f", usage {outcome.usage.get('input_tokens')} in / "
                         f"{outcome.usage.get('output_tokens')} out" if ok else ""))
        out.append(Check(f"Bedrock access: {mid}", ok, "; ".join(detail)))
    return out


def check_services(region: str) -> list[Check]:
    denied, allowed = [], []
    for label, (service, op, kwargs) in PROBES.items():
        try:
            getattr(_client(service, region), op)(**kwargs)
            allowed.append(label)
        except Exception as exc:  # noqa: BLE001
            denied.append(f"{label}: {_err(exc)}")
    checks = [Check("required services reachable (read-only probes)", not denied,
                    "all allowed" if not denied else "blocked -> " + "; ".join(denied))]
    try:
        _client("ecr", region).describe_repositories(repositoryNames=[
            load_config("deploy")["project_tag"]])
        checks.append(Check("ECR repository exists or can be created", True, "exists"))
    except Exception as exc:  # noqa: BLE001
        code = _err(exc)
        checks.append(Check("ECR repository exists or can be created",
                            code == "RepositoryNotFoundException",
                            "will be created by the stack" if code ==
                            "RepositoryNotFoundException" else code))
    try:
        _client("ssm", region).get_parameter(Name="/cdk-bootstrap/hnb659fds/version")
        checks.append(Check("CDK bootstrap", True, "bootstrap stack present"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("CDK bootstrap", False, f"{_err(exc)}; run `npx aws-cdk@2 bootstrap "
                            f"aws://<account>/{region}` (creates the CDK staging bucket, "
                            "ECR repo, and roles)"))
    return checks


def check_tags(cfg: dict) -> Check:
    template = REPO_ROOT / "cdk.out" / f"{cfg['stack_name']}.template.json"
    if not template.exists():
        return Check("project tags on all resources", False,
                     "run `npx aws-cdk@2 synth` first (cdk.out missing)")
    resources = json.loads(template.read_text())["Resources"]
    taggable = {k: r for k, r in resources.items() if "Tags" in r.get("Properties", {})}
    missing = []
    for key, r in taggable.items():
        tags = r["Properties"]["Tags"]
        values = (tags if isinstance(tags, list) else [{"Key": k, "Value": v}
                                                       for k, v in tags.items()])
        if not any(t.get("Key") == "project" and t.get("Value") == cfg["project_tag"]
                   for t in values):
            missing.append(key)
    return Check("project tags on all resources", not missing,
                 f"{len(taggable)} taggable resources tagged project={cfg['project_tag']}"
                 if not missing else f"untagged: {', '.join(missing[:10])}")


def cost_table() -> list[tuple[str, float]]:
    card = load_config("price_card")
    i, a = card["infrastructure"], card["assumptions"]
    h = a["hours_per_month"]
    api, wk = a["api_task"], a["worker_task"]
    rows = [
        ("Fargate API task (ARM)", h * (api["vcpu"] * i["fargate_arm_vcpu_hour_usd"]
                                        + api["memory_gb"] * i["fargate_arm_gb_hour_usd"])),
        ("Fargate worker task (ARM)", h * (wk["vcpu"] * i["fargate_arm_vcpu_hour_usd"]
                                           + wk["memory_gb"] * i["fargate_arm_gb_hour_usd"])),
        ("RDS db.t4g.micro single AZ", h * i["rds_db_t4g_micro_postgres_single_az_hour_usd"]),
        ("RDS gp3 storage", a["rds"]["storage_gb"] * i["rds_gp3_storage_gb_month_usd"]),
        ("ALB hours", h * i["alb_hour_usd"]),
        ("ALB LCU (assumed average)", h * a["alb_lcu_average"] * i["alb_lcu_hour_usd"]),
        ("Public IPv4 addresses", h * a["public_ipv4_addresses"] * i["public_ipv4_hour_usd"]),
        ("Secrets Manager secrets", a["secrets"] * i["secrets_manager_secret_month_usd"]),
    ]
    t = a["tokens_per_job"]
    for key in ("default_model_id", "second_model_id"):
        m = card["models"][key]
        per_job = ((t["planner_in"] + t["analyst_in"]) * m["input_per_1k_tokens_usd"]
                   + (t["planner_out"] + t["analyst_out"]) * m["output_per_1k_tokens_usd"]) / 1000
        rows.append((f"Inference per 1,000 jobs ({key})", per_job * 1000))
    return rows


def run_preflight(cloud: str, *, invoke_models: bool = True) -> tuple[bool, str]:
    if cloud != "aws":
        return False, "only --cloud aws is supported"
    cfg, models = load_config("deploy"), load_config("models")
    if os.environ.get("AWS_PROFILE") is None and cfg.get("aws_profile"):
        os.environ["AWS_PROFILE"] = cfg["aws_profile"]
    checks: list[Check] = []
    ident, account = check_identity(cfg)
    checks.append(ident)
    if account is not None:
        checks.append(check_public_endpoint(cfg))
        checks += check_models(models) if invoke_models else []
        checks += check_services(cfg["region"])
    checks.append(check_tags(cfg))

    lines = [f"ops preflight --cloud aws  ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)", ""]
    for c in checks:
        lines.append(f"[{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    lines += ["", "Estimated monthly cost (ESTIMATE, list prices from configs/price_card.yaml, "
              f"effective {load_config('price_card')['effective_date']}):"]
    rows = cost_table()
    infra = 0.0
    for name, usd in rows:
        lines.append(f"  {name:45s} ~${usd:8.2f}  (estimate)")
        if not name.startswith("Inference"):
            infra += usd
    lines += [f"  {'Infrastructure subtotal':45s} ~${infra:8.2f}  (estimate; excludes "
              "CloudFront, CloudWatch, SQS, S3, ECR, Cognito: unknown, expected small)", ""]
    ok = all(c.ok for c in checks)
    lines.append("PREFLIGHT PASSED" if ok else
                 f"PREFLIGHT FAILED: {sum(not c.ok for c in checks)} check(s) need attention")
    report = _mask("\n".join(lines))
    out = REPO_ROOT / "docs" / "evidence" / "preflight"
    out.mkdir(parents=True, exist_ok=True)
    Path(out / f"preflight-{datetime.now(UTC):%Y%m%dT%H%M}.txt").write_text(report + "\n")
    return ok, report
