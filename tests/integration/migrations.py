"""Move a test database up (`head`) or down (`base`) with the app's own migrations."""

from sqlalchemy import Engine

from backend.db.migrations import downgrade, upgrade


def migrate(engine: Engine, revision: str) -> None:
    with engine.begin() as connection:
        if revision == "base":
            downgrade(connection, revision)
        else:
            upgrade(connection, revision)
