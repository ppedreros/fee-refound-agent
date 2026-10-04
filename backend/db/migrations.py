"""Run the Alembic migrations on an open owner connection (bootstrap and the integration tests)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection

ALEMBIC_INI = Path(__file__).with_name("alembic.ini")


def _config(connection: Connection) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = connection
    return config


def upgrade(connection: Connection, revision: str = "head") -> None:
    command.upgrade(_config(connection), revision)


def downgrade(connection: Connection, revision: str) -> None:
    command.downgrade(_config(connection), revision)
