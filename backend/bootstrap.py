"""Entrypoint: `python -m backend.bootstrap`. Prepares the database as its owner.

Idempotent, so the `migrate` job runs it on every start: migrations, then the login roles and
their grants. The seed (T9) and the policy clauses (T11) are added here.
"""

import sys

import psycopg
import structlog
from sqlalchemy import create_engine, pool
from sqlalchemy.exc import OperationalError

from backend.core.logging import configure_logging
from backend.core.settings import ROLE_FOR_URL, ConfigError, load_settings
from backend.db.migrations import upgrade
from backend.db.roles import ensure_login_roles, grant_privileges, login_roles

log = structlog.get_logger()


def main() -> None:
    try:
        settings = load_settings()
        owner_url = settings.owner_database_url
        if owner_url is None:
            raise ConfigError("OWNER_DATABASE_URL is required to run bootstrap")
    except ConfigError as error:
        sys.exit(f"Invalid configuration: {error}")
    configure_logging(settings.log_level, settings.masking_salt)

    try:
        engine = create_engine(owner_url.get_secret_value(), poolclass=pool.NullPool)
        with engine.begin() as connection:
            upgrade(connection)
        log.info("bootstrap_step_done", step="migrations")

        ensure_login_roles(owner_url, login_roles(settings))
        grant_privileges(
            owner_url,
            app_role=ROLE_FOR_URL["app_database_url"],
            agent_role=ROLE_FOR_URL["agent_database_url"],
        )
        log.info("bootstrap_step_done", step="roles")
    except OperationalError, psycopg.OperationalError:
        sys.exit("Bootstrap could not reach the database as its owner.")


if __name__ == "__main__":
    main()
