"""Runtime settings. Local defaults point at the compose.yaml PostgreSQL."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"

_LOCAL = "postgresql+psycopg://{role}:{role}_local@127.0.0.1:5432/ops"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deploy_env: str = "local"
    auth_mode: Literal["local", "cognito"] = "local"
    database_url_admin: str = _LOCAL.format(role="ops_admin")
    database_url_import: str = _LOCAL.format(role="ops_import")
    database_url_api: str = _LOCAL.format(role="ops_api")
    database_url_worker: str = _LOCAL.format(role="ops_worker")
    aws_region: str = "us-east-2"
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    cognito_domain: str | None = None
    local_issuer: str = "https://local.ops.invalid/local-user-pool"
    local_client_id: str = "local-client"

    @model_validator(mode="after")
    def _local_auth_only_locally(self) -> "Settings":
        if self.auth_mode == "local" and self.deploy_env != "local":
            raise ValueError(
                f"AUTH_MODE=local is refused when DEPLOY_ENV={self.deploy_env!r}; "
                "local test tokens are allowed only with DEPLOY_ENV=local"
            )
        return self

    # Deployed: host and per-role credentials arrive from Secrets Manager as env vars.
    ops_db_host: str | None = None
    ops_db_port: int = 5432
    ops_db_name: str = "ops"

    def database_url(self, role: Literal["admin", "import", "api", "worker"]) -> str:
        if self.ops_db_host:
            import os
            from urllib.parse import quote

            user = os.environ.get(f"OPS_DB_{role.upper()}_USER")
            password = os.environ.get(f"OPS_DB_{role.upper()}_PASSWORD")
            if not (user and password):
                raise RuntimeError(f"credentials for the {role} database role are not configured")
            return (f"postgresql+psycopg://{quote(user)}:{quote(password)}@{self.ops_db_host}:"
                    f"{self.ops_db_port}/{self.ops_db_name}?sslmode=require")
        return getattr(self, f"database_url_{role}")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_config(name: str) -> dict:
    with open(CONFIG_DIR / f"{name}.yaml") as fh:
        return yaml.safe_load(fh)
