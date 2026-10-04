"""Run the app's Alembic migrations on a test engine."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "backend" / "db" / "alembic.ini"


def migrate(engine: Engine, revision: str) -> None:
    """Upgrade to `revision` (`head`), or downgrade when it is `base`."""
    with engine.begin() as connection:
        config = Config(str(ALEMBIC_INI))
        config.attributes["connection"] = connection
        if revision == "base":
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)
