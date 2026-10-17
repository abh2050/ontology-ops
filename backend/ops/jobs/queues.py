"""Queue adapters. Messages carry IDs only: never prompts or customer records."""

from __future__ import annotations

import itertools
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

MAX_RECEIVES = 5
VISIBILITY_SECONDS = 180


@dataclass(frozen=True)
class Message:
    receipt: str
    body: dict
    receive_count: int


class Queue(Protocol):
    def send(self, body: dict) -> str: ...
    def receive(self, max_messages: int = 2) -> list[Message]: ...
    def delete(self, receipt: str) -> None: ...


def _check_body(body: dict) -> str:
    if set(body) != {"job_id", "event_id"}:
        raise ValueError("queue messages carry job_id and event_id only")
    return json.dumps(body, sort_keys=True)


class FixtureQueue:
    """In-process stand-in with SQS semantics: at-least-once delivery, a visibility
    timeout, receive counts, and a dead-letter list after MAX_RECEIVES receives."""

    def __init__(self, visibility_seconds: float = VISIBILITY_SECONDS,
                 max_receives: int = MAX_RECEIVES, clock: Callable[[], float] = time.monotonic):
        self.visibility_seconds = visibility_seconds
        self.max_receives = max_receives
        self.clock = clock
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.messages: dict[str, dict] = {}
        self.dead_letters: list[dict] = []

    def send(self, body: dict) -> str:
        raw = _check_body(body)
        with self._lock:
            mid = f"m{next(self._ids)}"
            self.messages[mid] = {"body": raw, "receives": 0, "visible_at": 0.0}
            return mid

    def receive(self, max_messages: int = 2) -> list[Message]:
        now = self.clock()
        out: list[Message] = []
        with self._lock:
            for mid, m in list(self.messages.items()):
                if len(out) >= max_messages:
                    break
                if m["visible_at"] > now:
                    continue
                if m["receives"] >= self.max_receives:
                    self.dead_letters.append({"message_id": mid, **m})
                    del self.messages[mid]
                    continue
                m["receives"] += 1
                m["visible_at"] = now + self.visibility_seconds
                receipt = f"{mid}:{m['receives']}"
                out.append(Message(receipt, json.loads(m["body"]), m["receives"]))
        return out

    def delete(self, receipt: str) -> None:
        mid, count = receipt.split(":")
        with self._lock:
            m = self.messages.get(mid)
            if m is not None and str(m["receives"]) == count:
                del self.messages[mid]

    def pending(self) -> int:
        with self._lock:
            return len(self.messages)


class SqsQueue:
    """Amazon SQS Standard queue. The redrive policy (5 receives to the DLQ) and
    retention live on the queue itself (infra/stack.py)."""

    def __init__(self, queue_url: str, region: str, wait_seconds: int = 10):
        import boto3

        self.url = queue_url
        self.wait_seconds = wait_seconds
        self.client = boto3.client("sqs", region_name=region)

    def send(self, body: dict) -> str:
        return self.client.send_message(QueueUrl=self.url, MessageBody=_check_body(body))[
            "MessageId"]

    def receive(self, max_messages: int = 2) -> list[Message]:
        resp = self.client.receive_message(
            QueueUrl=self.url, MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=self.wait_seconds,
            MessageSystemAttributeNames=["ApproximateReceiveCount"])
        return [Message(m["ReceiptHandle"], json.loads(m["Body"]),
                        int(m["Attributes"]["ApproximateReceiveCount"]))
                for m in resp.get("Messages", [])]

    def delete(self, receipt: str) -> None:
        self.client.delete_message(QueueUrl=self.url, ReceiptHandle=receipt)
