"""Authenticated HTTPS smoke tests against the deployed stack for all four users (M4.5 check 4).

Tokens come from Cognito AdminInitiateAuth (IAM-authenticated; never browser-usable)
with the passwords that `ops seed-users --mode aws` stored in Secrets Manager. Tokens and
passwords are never written or printed. Report: docs/evidence/smoke/smoke-<UTC>.txt

  uv run python scripts/smoke_https.py --outputs cdk.out/outputs.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
LABELS = json.loads((ROOT / "data" / "fixtures" / "labels.json").read_text())


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "deploy.yaml").read_text())
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", default=str(ROOT / "cdk.out" / "outputs.json"))
    args = ap.parse_args()
    os.environ.setdefault("AWS_PROFILE", cfg["aws_profile"])
    out = json.loads(Path(args.outputs).read_text())[cfg["stack_name"]]
    region = cfg["region"]
    base = out["OutAppUrl"].rstrip("/")
    domain = base.removeprefix("https://")
    idp = boto3.client("cognito-idp", region_name=region)
    sm = boto3.client("secretsmanager", region_name=region)
    passwords = json.loads(sm.get_secret_value(SecretId=out["OutDemoUsersSecret"])["SecretString"])
    tokens = {}
    for user, password in passwords.items():
        resp = idp.admin_initiate_auth(
            UserPoolId=out["OutUserPoolId"], ClientId=out["OutUserPoolClientId"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": user, "PASSWORD": password})
        tokens[user] = resp["AuthenticationResult"]["AccessToken"]

    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    with httpx.Client(timeout=20, follow_redirects=False) as c:
        def get(path, user=None, **params):
            h = {"Authorization": f"Bearer {tokens[user]}"} if user else {}
            return c.get(base + path, params=params, headers=h)

        r = c.get(f"http://{domain}/api/health")
        check("HTTP redirects to HTTPS", r.status_code in (301, 302, 307, 308)
              and r.headers.get("location", "").startswith("https://"), str(r.status_code))
        check("health over HTTPS", get("/api/health").status_code == 200)
        check("no token is rejected", get("/api/queue").status_code == 401)
        bad = c.get(base + "/api/queue", headers={"Authorization": "Bearer not-a-token"})
        check("invalid token is rejected", bad.status_code == 401)
        roles = {"operator_a": "operator", "operator_b": "operator", "reviewer": "reviewer",
                 "viewer": "viewer"}
        totals = {}
        for user, role in roles.items():
            me = get("/api/me", user).json()
            check(f"{user}: provisioned as {role}",
                  me.get("provisioned") and me.get("role") == role,
                  f"granted_sellers={me.get('granted_sellers')}")
            q = get("/api/queue", user, limit=5)
            totals[user] = q.json()["aggregates"]["late_open_orders"] if q.status_code == 200 \
                else None
            check(f"{user}: queue readable", q.status_code == 200,
                  f"late_open_orders={totals[user]}")
        check("viewer sees nothing", totals["viewer"] == 0)
        check("operators see their scope", (totals["operator_a"] or 0) > 0)
        check("reviewer sees at least each operator", totals["reviewer"] >= max(
            totals["operator_a"], totals["operator_b"]))
        split = LABELS["split_ab_00"]
        a = get(f"/api/orders/{split}", "operator_a", batch="fixtures-v1")
        b = get(f"/api/orders/{split}", "operator_b", batch="fixtures-v1")
        rv = get(f"/api/orders/{split}", "reviewer", batch="fixtures-v1")
        check("split order invisible to both operators", a.status_code == b.status_code == 404
              and split not in a.text, f"{a.status_code}/{b.status_code}")
        check("split order visible to reviewer", rv.status_code == 200, str(rv.status_code))
        r = get("/api/queue", "operator_a")
        check("entity responses are private, no-store",
              r.headers.get("cache-control") == "private, no-store")

    lines = [f"HTTPS smoke tests ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC) against https://{domain}"]
    lines += [f"[{'PASS' if ok else 'FAIL'}] {name}{': ' + d if d else ''}"
              for name, ok, d in results]
    passed = all(ok for _, ok, _ in results)
    lines.append("SMOKE PASSED" if passed else "SMOKE FAILED")
    report = "\n".join(lines)
    target = ROOT / "docs" / "evidence" / "smoke"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"smoke-{datetime.now(UTC):%Y%m%dT%H%M}.txt").write_text(report + "\n")
    print(report)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
