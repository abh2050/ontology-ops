"""Recover only the interrupted demo job's identifier, using a read-only task.

No database mutation or paid model invocation. The selected job belongs to the
demo operator and the exact recorded interval; normal API authorization follows.
"""
import argparse
import json
import os
import time
from pathlib import Path

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-10-18 22:57:00+00")
    parser.add_argument("--end", default="2026-10-18 22:59:00+00")
    parser.add_argument("--directory", type=Path,
                        default=Path(".local/demo/drill-2026-10-18T22-57-15-650Z"))
    args = parser.parse_args()
    os.environ.setdefault("AWS_PROFILE", "awsnew")
    root = Path(__file__).resolve().parents[1]
    out = json.loads((root / "cdk.out/outputs.json").read_text())["OntologyOpsStack"]
    cfg = Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=20)
    ecs = boto3.client("ecs", region_name="us-east-2", config=cfg)
    idp = boto3.client("cognito-idp", region_name="us-east-2", config=cfg)
    logs = boto3.client("logs", region_name="us-east-2", config=cfg)
    actor = idp.admin_get_user(UserPoolId=out["OutUserPoolId"], Username="operator_a")
    subject = next(a["Value"] for a in actor["UserAttributes"] if a["Name"] == "sub")
    code = "\n".join([
        "import json", "from sqlalchemy import text", "from ops.db import engine",
        "with engine('admin').connect() as conn:",
        "    conn.execute(text('SET TRANSACTION READ ONLY'))",
        "    rows=conn.execute(text(\"SELECT job_id::text, input->>'target_id' AS target_id "
        "FROM jobs WHERE subject=:s AND created_at >= CAST(:start AS timestamptz) "
        "AND created_at < CAST(:end AS timestamptz)\"), {'s':" + repr(subject)
        + ", 'start':" + repr(args.start) + ", 'end':" + repr(args.end) + "}).all()",
        "    assert len(rows)==1, 'Ambiguous demo interval'",
        "    print('RECOVERY '+json.dumps(dict(rows[0]._mapping)),flush=True)",
    ])
    response = ecs.run_task(
        cluster=out["OutClusterName"], taskDefinition=out["OutMigrationTaskDef"],
        launchType="FARGATE", networkConfiguration={"awsvpcConfiguration": {
            "subnets": out["OutPublicSubnets"].split(","),
            "securityGroups": [out["OutOneOffTaskSg"]], "assignPublicIp": "ENABLED"}},
        overrides={"containerOverrides": [{"name": "migrate", "command": ["python", "-c", code]}]},
        tags=[{"key": "project", "value": "ontology-ops"}], propagateTags="TASK_DEFINITION")
    if response.get("failures") or not response.get("tasks"):
        raise RuntimeError("Read-only diagnostic task did not start")
    task = response["tasks"][0]["taskArn"]
    print("Read-only diagnostic started; no identifiers or credentials displayed", flush=True)
    for _ in range(60):
        desc = ecs.describe_tasks(cluster=out["OutClusterName"], tasks=[task])["tasks"][0]
        if desc["lastStatus"] == "STOPPED":
            if desc["containers"][0].get("exitCode") != 0:
                raise RuntimeError("Read-only diagnostic failed")
            break
        time.sleep(5)
    definition = ecs.describe_task_definition(taskDefinition=out["OutMigrationTaskDef"])
    options = definition["taskDefinition"]["containerDefinitions"][0]["logConfiguration"][
        "options"]
    stream = f"{options['awslogs-stream-prefix']}/migrate/{task.rsplit('/', 1)[-1]}"
    for _ in range(12):
        messages = logs.get_log_events(logGroupName=options["awslogs-group"],
                                      logStreamName=stream)["events"]
        found = [e["message"][9:] for e in messages if e["message"].startswith("RECOVERY ")]
        if found:
            directory = root / args.directory
            (directory / "continuation.json").write_text(found[-1] + "\n")
            print("Recovered the single operator-owned job reference for authorized API readback")
            return
        time.sleep(5)
    raise RuntimeError("Diagnostic log not yet available")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Capture recovery stopped: {type(exc).__name__}; details withheld")
        raise SystemExit(1) from None
