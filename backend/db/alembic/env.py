"""Alembic environment. Migrations always run as the database owner.

A caller can pass an open connection in `config.attributes["connection"]` (bootstrap and the
integration tests do). Otherwise this connects with OWNER_DATABASE_URL.
"""

from alembic import context
from sqlalchemy import Connection, create_engine, pool

from backend.core.settings import load_settings
from backend.db.models import Base


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
        return

    owner_url = load_settings().owner_database_url
    if owner_url is None:
        raise SystemExit("Migrations need OWNER_DATABASE_URL (the owner role).")
    engine = create_engine(owner_url.get_secret_value(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_migrations(connection)


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) migrations are not supported.")
run_online()
