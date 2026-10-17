"""CDK app entry point. Run through cdk.json: `npx aws-cdk@2 synth`.

Context: -c image_tag=<tag> (default latest), -c services_running=true.
No domain or certificate is needed: CloudFront's default domain serves HTTPS (D-024).
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
stack = OntologyOpsStack(
    app, cfg["stack_name"], cfg=cfg, models=models,
    image_tag=app.node.try_get_context("image_tag") or "latest",
    services_running=str(app.node.try_get_context("services_running")).lower() == "true",
    env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=cfg["region"]),
)
cdk.Tags.of(app).add("project", cfg["project_tag"])
app.synth()
