"""Entrypoint: `python -m backend.bootstrap`. Prepares the database as its owner.

Idempotent, so the `migrate` job runs it on every start. Today it creates the login roles;
migrations (T7), grants (T8), the seed (T9) and the policy clauses (T11) are added here.
"""

import sys

import psycopg

from backend.core.settings import ConfigError, load_settings
from backend.db.roles import ensure_login_roles, login_roles


def main() -> None:
    try:
        settings = load_settings()
        if settings.owner_database_url is None:
            raise ConfigError("OWNER_DATABASE_URL is required to run bootstrap")
    except ConfigError as error:
        sys.exit(f"Invalid configuration: {error}")

    try:
        ensure_login_roles(settings.owner_database_url, login_roles(settings))
    except psycopg.OperationalError:
        sys.exit("Bootstrap could not reach the database as its owner.")


if __name__ == "__main__":
    main()
