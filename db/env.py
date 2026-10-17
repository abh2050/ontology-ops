from alembic import context

from ops.db import engine

# Migrations always run as the migration/admin role. Never generated at runtime.


def run_migrations_online() -> None:
    with engine("admin").connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported")
run_migrations_online()
