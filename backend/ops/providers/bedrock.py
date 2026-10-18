"""Amazon Bedrock Converse provider. SDK automatic retries are disabled.

Output is plain text that the caller validates with strict Pydantic models; native
constrained JSON is not assumed. Error classification:
  - confirmed no generation, retryable once: ThrottlingException, ModelNotReadyException,
    connection failures before the request was sent
  - confirmed no generation, not retryable: ValidationException, AccessDeniedException,
    ResourceNotFoundException, ServiceQuotaExceededException
  - unknown outcome (never retried automatically): read timeouts, dropped connections,
    model timeouts, internal and service-unavailable errors
"""

from __future__ import annotations

from functools import cache

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    CredentialRetrievalError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
    ReadTimeoutError,
)

from ops.providers.base import Outcome

RETRYABLE_NO_GENERATION = {"ThrottlingException", "ModelNotReadyException"}
FINAL_NO_GENERATION = {"ValidationException", "AccessDeniedException",
                       "ResourceNotFoundException", "ServiceQuotaExceededException"}


@cache
def _client(region: str, read_timeout: int):
    config = Config(region_name=region, retries={"total_max_attempts": 1, "mode": "standard"},
                    connect_timeout=5, read_timeout=read_timeout)
    return boto3.client("bedrock-runtime", config=config)


class BedrockProvider:
    name = "bedrock"

    def __init__(self, region: str):
        self.region = region

    def converse(self, *, model_id: str, system: str, user: str, max_tokens: int,
                 timeout_seconds: float) -> Outcome:
        client = _client(self.region, max(1, int(timeout_seconds)))
        try:
            response = client.converse(
                modelId=model_id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
            )
        except (NoCredentialsError, PartialCredentialsError, CredentialRetrievalError) as exc:
            # Credentials failed before the request was signed: nothing was sent.
            return Outcome("known_failure", error_code=f"CREDENTIALS:{type(exc).__name__}",
                           no_generation=True)
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "LoginRefreshRequired":  # aws login session expired
                return Outcome("known_failure", error_code="CREDENTIALS:LoginRefreshRequired",
                               no_generation=True)
            if isinstance(exc, EndpointConnectionError | ConnectTimeoutError):
                return Outcome("known_failure", error_code="CONNECT_FAILED", no_generation=True,
                               retryable=True)
            if isinstance(exc, ReadTimeoutError | ConnectionClosedError):
                return Outcome("unknown", error_code="READ_TIMEOUT")
            if isinstance(exc, ClientError):
                code = exc.response.get("Error", {}).get("Code", "ClientError")
                if code in RETRYABLE_NO_GENERATION:
                    return Outcome("known_failure", error_code=code, no_generation=True,
                                   retryable=True)
                if code in FINAL_NO_GENERATION:
                    return Outcome("known_failure", error_code=code, no_generation=True)
                return Outcome("unknown", error_code=code)
            return Outcome("unknown", error_code=type(exc).__name__)
        content = response.get("output", {}).get("message", {}).get("content", [])
        text = "".join(part.get("text", "") for part in content)
        usage = response.get("usage", {})
        return Outcome("complete", text=text, usage={
            "input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens"),
            "stop_reason": response.get("stopReason")})
