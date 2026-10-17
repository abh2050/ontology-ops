"""Access token verification (spec 11.1 and 11.2).

Cognito and local mode share one verification path: RS256 signature, issuer,
expiry, token_use=access, and client_id. Only the key source differs: Cognito's
JWKS endpoint, or a locally generated fixture key under .local/ (gitignored).
A valid token grants nothing by itself; the users and seller_grants tables decide.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ops.settings import REPO_ROOT, Settings, get_settings

LOCAL_KEY = REPO_ROOT / ".local" / "auth_rsa.pem"
LOCAL_KID = "local-fixture-key"


class AuthError(Exception):
    """Any verification failure. The message is never shown to clients."""


@dataclass(frozen=True)
class Identity:
    subject: str
    username: str | None


@dataclass(frozen=True)
class TokenConfig:
    issuer: str
    client_id: str


def token_config(settings: Settings) -> TokenConfig:
    if settings.auth_mode == "local":
        return TokenConfig(settings.local_issuer, settings.local_client_id)
    if not (settings.cognito_user_pool_id and settings.cognito_client_id):
        raise AuthError("Cognito user pool and client id must be configured")
    issuer = (f"https://cognito-idp.{settings.aws_region}.amazonaws.com/"
              f"{settings.cognito_user_pool_id}")
    return TokenConfig(issuer, settings.cognito_client_id)


@cache
def _local_private_key() -> rsa.RSAPrivateKey:
    if not LOCAL_KEY.exists():
        LOCAL_KEY.parent.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        LOCAL_KEY.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        LOCAL_KEY.chmod(0o600)
    return serialization.load_pem_private_key(LOCAL_KEY.read_bytes(), password=None)


@cache
def _local_public_key() -> rsa.RSAPublicKey:
    return _local_private_key().public_key()


@cache
def _jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True)


def _signing_key(token: str, settings: Settings, cfg: TokenConfig):
    if settings.auth_mode == "local":
        header = jwt.get_unverified_header(token)
        if header.get("kid") != LOCAL_KID:
            raise AuthError("unknown key id")
        return _local_public_key()
    return _jwks_client(cfg.issuer).get_signing_key_from_jwt(token).key


def verify_access_token(token: str, settings: Settings | None = None) -> Identity:
    settings = settings or get_settings()
    cfg = token_config(settings)
    try:
        key = _signing_key(token, settings, cfg)
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=cfg.issuer,
                            options={"require": ["exp", "iss", "sub", "token_use",
                                                 "client_id"], "verify_aud": False})
    except (jwt.PyJWTError, ValueError) as exc:
        raise AuthError(type(exc).__name__) from None
    if claims.get("token_use") != "access":
        raise AuthError("not an access token")
    if claims.get("client_id") != cfg.client_id:
        raise AuthError("wrong client")
    return Identity(subject=claims["sub"], username=claims.get("username"))


def issue_local_token(subject: str, ttl_seconds: int = 3600, *, token_use: str = "access",
                      issuer: str | None = None, client_id: str | None = None,
                      expires_at: int | None = None) -> str:
    """Local test tokens with Cognito access token claims. Refused outside local mode."""
    settings = get_settings()
    if settings.auth_mode != "local" or settings.deploy_env != "local":
        raise AuthError("local tokens are only issued with AUTH_MODE=local and DEPLOY_ENV=local")
    now = int(time.time())
    claims = {
        "sub": subject, "username": subject, "iss": issuer or settings.local_issuer,
        "client_id": client_id or settings.local_client_id, "token_use": token_use,
        "scope": "openid", "iat": now, "auth_time": now,
        "exp": expires_at if expires_at is not None else now + ttl_seconds,
    }
    return jwt.encode(claims, _local_private_key(), algorithm="RS256",
                      headers={"kid": LOCAL_KID})
