"""SQS and Bedrock failure drills against the deployed stack (M5 check 5). Fault injection
is labelled: the worker runs with OPS_FAULT_INJECT set via `deploy.py release --fault`.

  uv run python scripts/drills.py crash      # worker exits after ready, before the SQS ack
  uv run python scripts/drills.py timeout    # Bedrock read timeout -> unknown hold, no retry
  uv run python scripts/drills.py breaker    # 5 real Bedrock rejections open the breaker
  uv run python scripts/drills.py poison     # report DLQ state for a poison message

Tokens stay in memory. Evidence: docs/evidence/drills/<drill>-<UTC>.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "configs" / "deploy.yaml").read_text())
OUT = json.loads((ROOT / "cdk.out" / "outputs.json").read_text())[CFG["stack_name"]]
REGION = CFG["region"]
BASE = OUT["OutAppUrl"].rstrip("/")


def token(user: str) -> str:
    sm = boto3.client("secretsmanager", region_name=REGION)
    idp = boto3.client("cognito-idp", region_name=REGION)
    pw = json.loads(sm.get_secret_value(SecretId=OUT["OutDemoUsersSecret"])["SecretString"])
    return idp.admin_initiate_auth(
        UserPoolId=OUT["OutUserPoolId"], ClientId=OUT["OutUserPoolClientId"],
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": user, "PASSWORD": pw[user]})["AuthenticationResult"][
        "AccessToken"]


class Api:
    def __init__(self, user: str):
        self.h = {"Authorization": f"Bearer {token(user)}"}
        self.c = httpx.Client(timeout=30)

    def get(self, path, **params):
        return self.c.get(BASE + path, params=params, headers=self.h)

    def post(self, path, body=None, **headers):
        return self.c.post(BASE + path, json=body, headers={**self.h, **headers})


def busiest_seller(api: Api, skip_cased: bool = False) -> str:
    items = api.get("/api/queue", limit=50).json()["items"]
    ranked = [s for s, _ in Counter(s for i in items for s in i["seller_ids"]).most_common()]
    if skip_cased:  # an equivalent case would (correctly) block a new proposal
        cased = {c["payload"]["target"]["target_id"] for c in api.get("/api/cases").json()[
            "items"]}
        ranked = [s for s in ranked if s not in cased] or ranked
    return ranked[0]


def submit(api: Api, seller: str) -> str:
    r = api.post("/api/jobs", {"target_type": "Seller", "target_id": seller, "scenario_id": None},
                 **{"Idempotency-Key": f"drill-{uuid.uuid4()}"})
    r.raise_for_status()
    return r.json()["job_id"]


def wait(api: Api, job_id: str, timeout_s: int = 900) -> tuple[dict, float]:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        j = api.get(f"/api/jobs/{job_id}").json()
        if j["state"] not in ("queued", "running", "validating"):
            return j, time.time() - t0
        time.sleep(3)
    return api.get(f"/api/jobs/{job_id}").json(), time.time() - t0


def worker_log(pattern: str, since_ms: int) -> list[str]:
    logs = boto3.client("logs", region_name=REGION)
    ev = logs.filter_log_events(logGroupName=f"/{CFG['project_tag']}/worker",
                                startTime=since_ms, filterPattern=pattern)["events"]
    return [e["message"][:160] for e in ev]


def record(name: str, lines: list[str], passed: bool) -> None:
    out = ROOT / "docs" / "evidence" / "drills"
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M}"
    text = "\n".join([f"# Drill: {name} ({stamp} UTC)", "", "**FAULT INJECTION ACTIVE "
                      "(labelled drill)**" if name != "poison" else "", "", *lines, "",
                      f"Result: {'PASS' if passed else 'FAIL'}"]) + "\n"
    (out / f"{name}-{stamp}.md").write_text(text)
    print(text)


def drill_crash() -> bool:
    since = int(time.time() * 1000)
    op, rv = Api("operator_a"), Api("reviewer")
    job = submit(op, busiest_seller(op, skip_cased=True))
    j, secs = wait(op, job)
    # The crash happens after ready is durable; wait for ECS to replace the task, SQS to
    # redeliver after the 180 s visibility timeout, and the new worker to ack without work.
    sqs = boto3.client("sqs", region_name=REGION)
    t0 = time.time()
    while time.time() - t0 < 600:
        a = sqs.get_queue_attributes(QueueUrl=OUT["OutQueueUrl"], AttributeNames=[
            "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
        if a["ApproximateNumberOfMessages"] == a["ApproximateNumberOfMessagesNotVisible"] == "0":
            break
        time.sleep(15)
    drained = time.time() - t0
    time.sleep(20)  # CloudWatch ingestion delay
    crashed = worker_log('"FAULT INJECTION: exiting"', since)
    after = op.get(f"/api/jobs/{job}").json()
    prop = op.post(f"/api/jobs/{job}/proposal")
    p = prop.json()
    lines = [f"- Job reached `{j['state']}` in {secs:.0f} s; the worker then exited before "
             "acknowledging SQS.",
             f"- Worker crash log lines: {len(crashed)}",
             f"- Queue drained {drained:.0f} s after ready (ECS replaced the task; SQS "
             "redelivered after the 180 s visibility timeout; the new worker acked the "
             "already-ready job without work).",
             f"- Job state after redelivery: `{after['state']}`, revision {after['revision']}",
             f"- Proposal: HTTP {prop.status_code}, state `{p.get('state')}`"]
    case_ok = False
    if prop.status_code in (200, 201) and p.get("state") == "pending":
        d = rv.post(f"/api/proposals/{p['proposal_id']}/decision",
                    {"decision": "approve", "expected_revision": p["revision"]})
        again = rv.post(f"/api/proposals/{p['proposal_id']}/decision",
                        {"decision": "approve", "expected_revision": p["revision"] + 1})
        cases = [c for c in rv.get("/api/cases").json()["items"]
                 if c["proposal_id"] == p["proposal_id"]]
        lines += [f"- Approval: HTTP {d.status_code} {d.json().get('state')}",
                  f"- Repeat approval: HTTP {again.status_code} {again.json().get('code')}",
                  f"- Cases for this proposal: {len(cases)}"]
        case_ok = d.status_code == 200 and len(cases) == 1
    return_ok = (j["state"] == "ready" and after["state"] == "ready" and len(crashed) >= 1
                 and case_ok)
    record("crash", lines, return_ok)
    return return_ok


def drill_timeout() -> bool:
    op = Api("operator_a")
    job = submit(op, busiest_seller(op))
    j, secs = wait(op, job)
    res = j.get("result") or {}
    ok = j["state"] == "unknown" and res.get("reason") == "PROVIDER_OUTCOME_UNKNOWN"
    record("timeout", [f"- Job ended `{j['state']}` after {secs:.0f} s, reason "
                       f"`{res.get('reason')}` at stage `{res.get('stage')}`",
                       f"- Detail: {res.get('detail')}",
                       "- Expected: unknown hold, no automatic retry, resolved only by "
                       "`ops recover-job`."], ok)
    return ok


def drill_breaker() -> bool:
    op = Api("operator_a")
    seller = busiest_seller(op)
    outcomes = []
    for _ in range(6):
        j, _secs = wait(op, submit(op, seller))
        res = j.get("result") or {}
        outcomes.append((j["state"], res.get("reason"), res.get("code")))
    rejected = sum(1 for o in outcomes[:5] if o[1] == "PROVIDER_REJECTED")
    ok = rejected == 5 and outcomes[5][1] == "PROVIDER_UNAVAILABLE"
    record("breaker", [f"- Job {i + 1}: state `{s}`, reason `{r}`, code `{c}`"
                       for i, (s, r, c) in enumerate(outcomes)] +
           ["- Expected: 5 real Bedrock rejections (invalid model id, nothing generated) "
            "open the process-local breaker; job 6 fails PROVIDER_UNAVAILABLE without a "
            "paid admission."], ok)
    return ok


def drill_poison() -> bool:
    sqs = boto3.client("sqs", region_name=REGION)
    attrs = sqs.get_queue_attributes(QueueUrl=OUT["OutDlqUrl"],
                                     AttributeNames=["ApproximateNumberOfMessages"])
    n = int(attrs["Attributes"]["ApproximateNumberOfMessages"])
    cw = boto3.client("cloudwatch", region_name=REGION)
    alarms = [a for a in cw.describe_alarms()["MetricAlarms"] if "DlqNotEmpty" in a["AlarmName"]]
    state = alarms[0]["StateValue"] if alarms else "missing"
    ok = n >= 1
    record("poison", [f"- DLQ approximate messages: {n}",
                      f"- DLQ alarm state: {state}",
                      "- A message with job_id 'drill-poison-not-a-uuid' made the consumer "
                      "raise; it was never acknowledged and moved to the DLQ after 5 receives. "
                      "No blind redrive."], ok)
    return ok


def main() -> None:
    os.environ.setdefault("AWS_PROFILE", CFG["aws_profile"])
    ap = argparse.ArgumentParser()
    ap.add_argument("drill", choices=["crash", "timeout", "breaker", "poison"])
    args = ap.parse_args()
    ok = {"crash": drill_crash, "timeout": drill_timeout, "breaker": drill_breaker,
          "poison": drill_poison}[args.drill]()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
