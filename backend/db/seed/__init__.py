"""Load the seed as the owner (SPEC-data, "Seed").

`seed` is idempotent: rows that already exist are left alone, so a restart never overwrites what
Luis changed (refunds, balances, statuses). `reset` empties every table first, the brief's ones
included, because a refund also changed them.
"""

from typing import Any

from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert

from backend.db.models import Base
from backend.db.seed.scenarios import SCENARIOS, STAFF


def seed(connection: Connection) -> None:
    rows = _rows_by_table()
    for table in Base.metadata.sorted_tables:  # parents before children
        if table.name in rows:
            connection.execute(insert(table).values(rows[table.name]).on_conflict_do_nothing())


def reset(connection: Connection) -> None:
    """Empty every app table and restart identities. Only the owner can do this."""
    quote = connection.dialect.identifier_preparer.quote
    tables = ", ".join(quote(table.name) for table in Base.metadata.sorted_tables)
    connection.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY")


def _rows_by_table() -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {"staff": list(STAFF)}
    for scenario in SCENARIOS:
        for table, table_rows in scenario.rows.items():
            rows.setdefault(table, []).extend(table_rows)
    return rows
