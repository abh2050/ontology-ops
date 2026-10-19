"""Launch live browser capture with credentials delivered only over stdin."""

import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.environ.setdefault("AWS_PROFILE", "awsnew")
    outputs = json.loads((ROOT / "cdk.out/outputs.json").read_text())["OntologyOpsStack"]
    client = boto3.client("secretsmanager", region_name="us-east-2",
                          config=Config(retries={"total_max_attempts": 1},
                                        connect_timeout=5, read_timeout=20))
    try:
        passwords = client.get_secret_value(SecretId=outputs["OutDemoUsersSecret"])["SecretString"]
    except Exception as exc:
        print(f"Demo credentials unavailable: {type(exc).__name__}; no secrets displayed")
        return 1
    return subprocess.run(["node", "scripts/record_demo.mjs", *sys.argv[1:]], cwd=ROOT,
                          input=passwords, text=True).returncode


if __name__ == "__main__":
    raise SystemExit(main())
