"""CDK app entry point. Run through cdk.json: `npx aws-cdk@2 synth`.

Required context at deploy time (never committed):
  -c certificate_arn=<ACM certificate ARN for the domain>   (preflight finds it)
Optional: -c image_tag=<tag> (default latest), -c services_running=true
Synth without a domain uses placeholders and is for template checks only; preflight
refuses to deploy until configs/deploy.yaml has a real domain and certificate.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import aws_cdk as cdk
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack import OntologyOpsStack  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((ROOT / "configs" / "deploy.yaml").read_text())
models = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text())

app = cdk.App()
domain = app.node.try_get_context("domain") or cfg.get("domain") or "placeholder.invalid"
# Synth-only placeholder, assembled at runtime so no ARN-shaped literal is committed.
PLACEHOLDER_CERT = ":".join(["arn", "aws", "acm", cfg["region"], "0" * 12,
                             "certificate/placeholder-for-synth-only"])
cert = app.node.try_get_context("certificate_arn") or PLACEHOLDER_CERT
stack = OntologyOpsStack(
    app, cfg["stack_name"], cfg=cfg, models=models, domain=domain, certificate_arn=cert,
    image_tag=app.node.try_get_context("image_tag") or "latest",
    services_running=str(app.node.try_get_context("services_running")).lower() == "true",
    env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=cfg["region"]),
)
cdk.Tags.of(app).add("project", cfg["project_tag"])
app.synth()
