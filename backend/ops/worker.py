"""Worker entry point: outbox relay plus bounded consumer in one process."""

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
    return Worker(queue, deps)


def run(queue_kind: str, provider_kind: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    worker = build(queue_kind, provider_kind)
    signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
    logging.getLogger("ops.worker").info("worker started queue=%s provider=%s", queue_kind,
                                         provider_kind)
    worker.run()
