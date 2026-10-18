from botocore.exceptions import NoCredentialsError

from ops.providers import bedrock


class Raising:
    def __init__(self, exc):
        self.exc = exc

    def converse(self, **kw):
        raise self.exc


def call(monkeypatch, exc):
    monkeypatch.setattr(bedrock, "_client", lambda region, timeout: Raising(exc))
    return bedrock.BedrockProvider("us-east-2").converse(
        model_id="m", system="s", user="u", max_tokens=5, timeout_seconds=5)


def test_missing_credentials_is_confirmed_no_generation(monkeypatch):
    out = call(monkeypatch, NoCredentialsError())
    assert out.kind == "known_failure" and out.no_generation and not out.retryable


def test_expired_login_is_confirmed_no_generation(monkeypatch):
    class LoginRefreshRequired(Exception):
        pass

    out = call(monkeypatch, LoginRefreshRequired())
    assert out.kind == "known_failure" and out.error_code.endswith("LoginRefreshRequired")


def test_unexpected_errors_are_unknown(monkeypatch):
    assert call(monkeypatch, RuntimeError("boom")).kind == "unknown"
