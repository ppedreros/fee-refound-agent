"""Database roles, set up by the owner during bootstrap (SPEC-data, "Database roles").

`agent_reader` can only read what the agent needs; `app_writer` can make exactly the writes the
app does. Every run revokes everything first and grants again, so the grants never drift.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from backend.core.settings import ROLE_FOR_URL, Settings

CONNECT_TIMEOUT_S = 5
READER_STATEMENT_TIMEOUT = "3s"

READER_TABLES = (
    "conversations",
    "messages",
    "accounts",
    "sub_accounts",
    "transactions",
    "member_profiles",
    "policy_clauses",
    "cases",
    "agent_runs",
    "refunds",
)

# On top of SELECT on every table. Nothing may DELETE or TRUNCATE.
WRITER_GRANTS = {
    "conversations": ("UPDATE (status)",),
    "messages": ("INSERT",),
    "sub_accounts": ("UPDATE (balance, available)",),  # core-banking adapter only
    "transactions": ("INSERT",),  # core-banking adapter only
    "cases": ("INSERT", "UPDATE"),
    "agent_runs": ("INSERT", "UPDATE"),
    "refunds": ("INSERT", "UPDATE (refund_txn_id)"),
    "agent_steps": ("INSERT",),
    "decisions": ("INSERT",),
    "audit_events": ("INSERT",),
    "eval_candidates": ("INSERT", "UPDATE (exported_at)"),
}


@dataclass(frozen=True)
class LoginRole:
    name: str
    password: str = field(repr=False)


def login_roles(settings: Settings) -> list[LoginRole]:
    """The roles to create, each with the password from its own URL (checked by Settings)."""
    roles = []
    for field_name, role in ROLE_FOR_URL.items():
        url = make_url(getattr(settings, field_name).get_secret_value())
        roles.append(LoginRole(name=role, password=url.password or ""))
    return roles


@contextmanager
def _owner_connection(owner_url: SecretStr) -> Iterator[psycopg.Connection]:
    conninfo = make_url(owner_url.get_secret_value()).set(drivername="postgresql")
    with psycopg.connect(
        conninfo.render_as_string(hide_password=False), connect_timeout=CONNECT_TIMEOUT_S
    ) as connection:
        yield connection


def ensure_login_roles(owner_url: SecretStr, roles: list[LoginRole]) -> None:
    """Create any missing role and (re)set every password. Safe to run on every start."""
    with _owner_connection(owner_url) as connection:
        for role in roles:
            exists = connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (role.name,)
            ).fetchone()
            if exists is None:
                connection.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role.name)))
            connection.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(role.name), sql.Literal(role.password)
                )
            )


def grant_privileges(owner_url: SecretStr, *, app_role: str, agent_role: str) -> None:
    """Reset both roles to exactly the grants in SPEC-data, in one transaction."""
    app, agent = sql.Identifier(app_role), sql.Identifier(agent_role)
    with _owner_connection(owner_url) as connection:
        for objects in ("TABLES", "SEQUENCES"):
            connection.execute(
                sql.SQL("REVOKE ALL ON ALL {} IN SCHEMA public FROM {}, {}").format(
                    sql.SQL(objects), app, agent
                )
            )

        for table in READER_TABLES:
            connection.execute(
                sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(table), agent)
            )
        connection.execute(
            sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(agent)
        )
        connection.execute(
            sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(
                agent, sql.Literal(READER_STATEMENT_TIMEOUT)
            )
        )

        connection.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(app))
        for table, privileges in WRITER_GRANTS.items():
            connection.execute(
                sql.SQL("GRANT {} ON {} TO {}").format(
                    sql.SQL(", ").join(sql.SQL(privilege) for privilege in privileges),
                    sql.Identifier(table),
                    app,
                )
            )
