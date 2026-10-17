"""Create or rotate the runtime login roles on a fresh database (deployed migration task).

Locally compose.yaml creates the roles. On RDS the migration task runs as the master
user (named ops_admin, not a superuser) and calls this before Alembic when
OPS_BOOTSTRAP_ROLES=1. Passwords come from Secrets Manager via environment variables.
"""

from __future__ import annotations

import os

from sqlalchemy import text

from ops.db import engine

RUNTIME_ROLES = {"import": "ops_import", "api": "ops_api", "worker": "ops_worker"}


def bootstrap_roles() -> list[str]:
    done = []
    with engine("admin").begin() as conn:
        db = conn.execute(text("SELECT current_database()")).scalar_one()
        conn.execute(text(f'REVOKE ALL ON DATABASE "{db}" FROM PUBLIC'))
        conn.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
        for key, role in RUNTIME_ROLES.items():
            password = os.environ.get(f"OPS_DB_{key.upper()}_PASSWORD")
            if not password:
                raise RuntimeError(f"OPS_DB_{key.upper()}_PASSWORD is not set")
            exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
                                  {"r": role}).first()
            verb = "ALTER" if exists else "CREATE"
            # Role names are fixed constants; the password is bound via format() server side.
            stmt = conn.execute(text(f"SELECT format('{verb} ROLE {role} LOGIN PASSWORD %L', :p)"),
                                {"p": password}).scalar_one()
            conn.execute(text(stmt))
            conn.execute(text(f'GRANT CONNECT ON DATABASE "{db}" TO {role}'))
            done.append(role)
    return done
