"""Database roles, created by the owner during bootstrap (SPEC-data, "Database roles").

For now this only makes sure each role can log in with the password from its URL. Grants and
role settings (read-only default, statement timeout) come in T8.
"""

from dataclasses import dataclass, field

import psycopg
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from backend.core.settings import ROLE_FOR_URL, Settings

CONNECT_TIMEOUT_S = 5


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


def ensure_login_roles(owner_url: SecretStr, roles: list[LoginRole]) -> None:
    """Create any missing role and (re)set every password. Safe to run on every start."""
    conninfo = make_url(owner_url.get_secret_value()).set(drivername="postgresql")
    with psycopg.connect(
        conninfo.render_as_string(hide_password=False), connect_timeout=CONNECT_TIMEOUT_S
    ) as connection:
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
