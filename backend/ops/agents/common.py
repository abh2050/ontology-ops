"""Shared helpers for the two AI stages: token budgets and strict JSON parsing."""

from __future__ import annotations

import hashlib
import json
import math

from pydantic import BaseModel, ValidationError


class StageInputTooLarge(Exception):
    pass


class InvalidModelOutput(Exception):
    """The model returned text that is not valid JSON for the stage contract. No repair."""


def estimate_tokens(*texts: str) -> int:
    # Conservative estimate: 3.0 characters per token. 3.5 under-counted Nova's tokenizer
    # on ID-heavy JSON (a 4,083-token input passed the 4,000 budget, 2026-10-18).
    return math.ceil(sum(len(t) for t in texts) / 3.0)


def request_hash(model_id: str, system: str, user: str, max_tokens: int) -> str:
    raw = json.dumps([model_id, system, user, max_tokens], separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_strict(text: str, model: type[BaseModel]):
    body = text.strip()
    if body.startswith("```"):
        # Accept one surrounding code fence; anything else is invalid. Not a repair loop.
        lines = body.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1]).strip()
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise InvalidModelOutput(
            f"{model.__name__}: {exc.error_count()} validation errors") from None
