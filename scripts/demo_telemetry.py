"""Read-only, sanitized live telemetry for the labelled video fault drill."""

import json
import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config


def main():
    os.environ.setdefault("AWS_PROFILE", "awsnew")
    root = Path(__file__).resolve().parents[1]
    out = json.loads((root / "cdk.out/outputs.json").read_text())["OntologyOpsStack"]
    config = Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=15)
    sqs = boto3.client("sqs", region_name="us-east-2", config=config)
    logs = boto3.client("logs", region_name="us-east-2", config=config)
    attributes = sqs.get_queue_attributes(QueueUrl=out["OutQueueUrl"], AttributeNames=[
        "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    events = logs.filter_log_events(logGroupName="/ontology-ops/worker", startTime=int(sys.argv[1]),
                                   filterPattern='"FAULT INJECTION: exiting"')["events"]
    print(json.dumps({"visible": int(attributes["ApproximateNumberOfMessages"]),
                      "in_flight": int(attributes["ApproximateNumberOfMessagesNotVisible"]),
                      "crash_events": len(events)}))


if __name__ == "__main__":
    main()
