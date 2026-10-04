import asyncio

from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.api.routes_health import database_is_up
from backend.core.settings import Settings


def make_settings(app_database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        app_database_url=app_database_url,
        agent_database_url="postgresql+psycopg://agent_reader:test-password@127.0.0.1:5432/fees",
        masking_salt="test-salt",
    )


UNUSED_DATABASE = "postgresql+psycopg://app_writer:test-password@127.0.0.1:5432/fees"


def test_health_is_ok_when_the_database_answers() -> None:
    app = create_app(make_settings(UNUSED_DATABASE))
    app.dependency_overrides[database_is_up] = lambda: True

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_is_503_when_the_database_does_not_answer() -> None:
    app = create_app(make_settings(UNUSED_DATABASE))
    app.dependency_overrides[database_is_up] = lambda: False

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}


def test_health_echoes_the_request_id() -> None:
    app = create_app(make_settings(UNUSED_DATABASE))
    app.dependency_overrides[database_is_up] = lambda: True
    request_id = "0b6c5d8e-4f3a-4d2b-9c1e-7a8f6e5d4c3b"

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


def test_health_is_503_without_a_trace_when_no_server_listens() -> None:
    # Port 1 on localhost has no Postgres: the real check must fail closed, not raise.
    app = create_app(
        make_settings("postgresql+psycopg://app_writer:test-password@127.0.0.1:1/fees")
    )
    # psycopg's async mode can't run on Windows' default (Proactor) loop. A selector loop makes
    # this test hit a real network failure on every OS instead of that driver error.
    selector_loop = {"loop_factory": asyncio.SelectorEventLoop}

    with TestClient(app, backend_options=selector_loop) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
