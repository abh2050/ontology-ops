"""Provider interface. Outcomes distinguish confirmed non-generation from unknown results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

OutcomeKind = Literal["complete", "known_failure", "unknown"]


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    text: str = ""
    usage: dict = field(default_factory=dict)
    error_code: str | None = None
    # True only when the provider confirms that no generation occurred.
    no_generation: bool = False
    # True when a confirmed non-generation may be retried once (throttling, not ready).
    retryable: bool = False


class Provider(Protocol):
    name: str

    def converse(self, *, model_id: str, system: str, user: str, max_tokens: int,
                 timeout_seconds: float) -> Outcome: ...
