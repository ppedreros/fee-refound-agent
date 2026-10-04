"""The evals' own database (SPEC-evals, "Runner"): `EVAL_DATABASE_NAME` (fees_eval), on the app's
server and with the app's roles, rebuilt at the start of every run.

The server is the owner's: `OWNER_DATABASE_URL`, or the URL compose builds from `POSTGRES_*`, on
the port compose publishes on 127.0.0.1 (`DB_HOST_PORT`). Both role URLs keep their user and
password from `APP_DATABASE_URL` and `AGENT_DATABASE_URL` and move to that server and database,
so the runner works the same from the host, in CI and inside compose.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine, pool, text
from sqlalchemy.engine import URL, make_url

from backend.core.settings import ROLE_FOR_URL, ConfigError, Settings
from backend.db.migrations import upgrade
from backend.db.roles import ensure_login_roles, grant_privileges, login_roles
from backend.db.seed import seed
from backend.policy.loader import load_clauses


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    eval_database_name: str = Field(default="fees_eval", pattern=r"^[a-z_][a-z0-9_]*$")
    owner_database_url: SecretStr | None = None
    postgres_user: str = "fees"
    postgres_password: SecretStr | None = None
    postgres_db: str = "fees"
    db_host_port: int = 5432

    @field_validator("owner_database_url", "postgres_password", mode="before")
    @classmethod
    def _blank_is_missing(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    def server_url(self) -> URL:
        if self.owner_database_url is not None:
            return make_url(self.owner_database_url.get_secret_value())
        if self.postgres_password is None:
            raise ConfigError("OWNER_DATABASE_URL (or POSTGRES_PASSWORD)")
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host="127.0.0.1",
            port=self.db_host_port,
            database=self.postgres_db,
        )


@dataclass(frozen=True)
class EvalDatabase:
    name: str
    server: URL  # the owner, on the server's own database: creates and drops the eval database
    owner: URL  # the owner, on the eval database: migrations, seed, message overrides
    app: URL
    agent: URL

    def settings(self, settings: Settings) -> Settings:
        """The app's settings, pointed at the eval database (for the role passwords)."""
        return settings.model_copy(
            update={
                "app_database_url": SecretStr(_render(self.app)),
                "agent_database_url": SecretStr(_render(self.agent)),
            }
        )


def eval_database(settings: Settings, eval_settings: EvalSettings) -> EvalDatabase:
    server = eval_settings.server_url()
    name = eval_settings.eval_database_name
    app = make_url(settings.app_database_url.get_secret_value())
    if name in (server.database, app.database):
        raise ConfigError("EVAL_DATABASE_NAME (it must not be the app's database)")

    def moved(url: URL) -> URL:
        return url.set(host=server.host, port=server.port, database=name)

    return EvalDatabase(
        name=name,
        server=server,
        owner=server.set(database=name),
        app=moved(app),
        agent=moved(make_url(settings.agent_database_url.get_secret_value())),
    )


def prepare(database: EvalDatabase, settings: Settings) -> None:
    """Drop and recreate the eval database, then bootstrap it as `backend.bootstrap` does."""
    admin = create_engine(database.server, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database.name}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{database.name}"'))
    finally:
        admin.dispose()

    owner = SecretStr(_render(database.owner))
    engine = create_engine(database.owner, poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            upgrade(connection)
        ensure_login_roles(owner, login_roles(database.settings(settings)))
        grant_privileges(
            owner,
            app_role=ROLE_FOR_URL["app_database_url"],
            agent_role=ROLE_FOR_URL["agent_database_url"],
        )
        with engine.begin() as connection:
            seed(connection)
            load_clauses(connection)
    finally:
        engine.dispose()


_LATEST_MEMBER_MESSAGE = text(
    "SELECT id, body FROM messages WHERE conversation_id = :conversation_id"
    " AND author_id NOT IN (SELECT id FROM staff) ORDER BY created_at DESC, id DESC LIMIT 1"
)
_SET_BODY = text("UPDATE messages SET body = :body WHERE id = :id")


@contextmanager
def message_override(owner: Engine, conversation_id: int, body: str | None) -> Iterator[None]:
    """Replace the member's latest message for one run, then put the seed's text back."""
    if body is None:
        yield
        return
    with owner.begin() as connection:
        message_id, original = connection.execute(
            _LATEST_MEMBER_MESSAGE, {"conversation_id": conversation_id}
        ).one()
        connection.execute(_SET_BODY, {"id": message_id, "body": body})
    try:
        yield
    finally:
        with owner.begin() as connection:
            connection.execute(_SET_BODY, {"id": message_id, "body": original})


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)
