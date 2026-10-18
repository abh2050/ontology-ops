"""Worker entry point: outbox relay plus bounded consumer in one process.

OPS_FAULT_INJECT enables a labelled failure drill (M5 drills; off by default):
  crash_before_ack       exit the process after a job reaches ready, before the SQS ack
  bedrock_timeout        force a client read timeout on Bedrock calls (unknown outcome)
  bedrock_invalid_model  call Bedrock with an invalid model id (real, non-billed rejection)
"""

from __future__ import annotations

import logging
import os
import signal

from ops.db import engine
from ops.jobs.breaker import CircuitBreaker
from ops.jobs.consumer import Worker, WorkerDeps
from ops.jobs.queues import FixtureQueue, SqsQueue
from ops.settings import get_settings, load_config


def build(queue_kind: str, provider_kind: str) -> Worker:
    settings = get_settings()
    models = load_config("models")
    if queue_kind == "fixture":
        queue = FixtureQueue()
    elif queue_kind == "sqs":
        url = os.environ.get("OPS_QUEUE_URL")
        if not url:
            raise RuntimeError("OPS_QUEUE_URL is required for --queue sqs")
        queue = SqsQueue(url, settings.aws_region)
    else:
        raise RuntimeError("--queue must be fixture or sqs")
    if provider_kind == "fixture":
        from ops.providers.fixture import FixtureProvider

        provider = FixtureProvider()
    elif provider_kind == "bedrock":
        from ops.providers.bedrock import BedrockProvider

        provider = BedrockProvider(models["region"])
    else:
        raise RuntimeError("--provider must be fixture or bedrock")
    deps = WorkerDeps(engine=engine("worker"), provider=provider, breaker=CircuitBreaker(),
                      models=models)
    apply_fault_injection(deps, os.environ.get("OPS_FAULT_INJECT"))
    return Worker(queue, deps)


FAULTS = {"crash_before_ack", "bedrock_timeout", "bedrock_invalid_model"}


def apply_fault_injection(deps: WorkerDeps, fault: str | None) -> None:
    if not fault:
        return
    if fault not in FAULTS:
        raise RuntimeError(f"unknown OPS_FAULT_INJECT value {fault!r}")
    log = logging.getLogger("ops.worker")
    log.warning("FAULT INJECTION ACTIVE: %s (drill only)", fault)
    if fault == "crash_before_ack":
        def crash() -> None:
            log.warning("FAULT INJECTION: exiting after ready, before the queue ack")
            logging.shutdown()
            os._exit(1)
        deps.hooks["before_ack"] = crash  # fires only on the attempt that did the work
        return
    inner = deps.provider

    class Faulty:
        name = inner.name

        def converse(self, *, model_id, system, user, max_tokens, timeout_seconds):
            if fault == "bedrock_timeout":
                from ops.providers import bedrock

                client = bedrock.boto3.client(
                    "bedrock-runtime", config=bedrock.Config(
                        region_name=inner.region, read_timeout=0.001, connect_timeout=5,
                        retries={"total_max_attempts": 1, "mode": "standard"}))
                original = bedrock._client
                bedrock._client = lambda region, read_timeout: client
                try:
                    return inner.converse(model_id=model_id, system=system, user=user,
                                          max_tokens=max_tokens, timeout_seconds=timeout_seconds)
                finally:
                    bedrock._client = original
            return inner.converse(model_id=f"{model_id}-fault-injected", system=system,
                                  user=user, max_tokens=max_tokens,
                                  timeout_seconds=timeout_seconds)

    deps.provider = Faulty()


def run(queue_kind: str, provider_kind: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    worker = build(queue_kind, provider_kind)
    signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
    logging.getLogger("ops.worker").info("worker started queue=%s provider=%s", queue_kind,
                                         provider_kind)
    worker.run()
