"""Every error has one friendly shape, and no response ever holds a traceback (SPEC-api,
"Conventions"; AC5, AC6)."""

from collections.abc import AsyncIterator

import httpx
import pytest
import structlog
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.engine import URL

from backend.api.main import create_app
from tests.api.conftest import SETTINGS, resources_for
from tests.integration.agents.fakes import FakeClassifier, jev_answers

TRACE_WORDS = ("Traceback", 'File "', "RuntimeError", "sqlalchemy")


def friendly(response: httpx.Response) -> tuple[int, str, str]:
    body = response.json()
    assert set(body) == {"error"}
    assert not any(word in response.text for word in TRACE_WORDS)
    return response.status_code, body["error"]["code"], body["error"]["message"]


async def test_an_unknown_page_is_a_friendly_404(client: httpx.AsyncClient) -> None:
    assert friendly(await client.get("/nothing-here")) == (
        404,
        "not_found",
        "We couldn't find that page.",
    )


async def test_an_unknown_case_is_a_friendly_404(client: httpx.AsyncClient) -> None:
    assert friendly(await client.get("/cases/999999"))[:2] == (404, "not_found")


async def test_a_non_numeric_id_is_a_friendly_422(client: httpx.AsyncClient) -> None:
    assert friendly(await client.get("/cases/abc")) == (
        422,
        "invalid_request",
        "Something in that request isn't valid.",
    )


async def test_a_wrong_method_is_friendly_too(client: httpx.AsyncClient) -> None:
    assert friendly(await client.delete("/cases/5012"))[:2] == (405, "method_not_allowed")


@pytest.fixture
async def failing_app(with_clauses: Engine, test_database_url: URL) -> AsyncIterator[FastAPI]:
    application = create_app(
        SETTINGS, resources=resources_for(test_database_url, FakeClassifier(jev_answers()))
    )

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("internal detail that names Ana Torres")

    async with application.router.lifespan_context(application):
        yield application


async def test_an_unexpected_error_is_a_calm_500_logged_without_its_message(
    failing_app: FastAPI,
) -> None:
    transport = httpx.ASGITransport(app=failing_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        with structlog.testing.capture_logs() as logs:
            response = await http.get("/boom")

    assert friendly(response) == (
        500,
        "internal_error",
        "Something went wrong on our side. Please try again.",
    )
    assert "Ana Torres" not in response.text
    (entry,) = [log for log in logs if log["event"] == "unhandled_error"]
    assert entry["error"] == "RuntimeError"
    assert "Ana Torres" not in str(entry)


# --- Rate limits (per client) ---


@pytest.fixture
async def strict_client(
    with_clauses: Engine, test_database_url: URL
) -> AsyncIterator[httpx.AsyncClient]:
    settings = SETTINGS.model_copy(update={"rate_limit": "3/minute"})
    application = create_app(
        settings, resources=resources_for(test_database_url, FakeClassifier(jev_answers()))
    )
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_going_over_the_limit_is_a_friendly_429_with_retry_after(
    strict_client: httpx.AsyncClient,
) -> None:
    for _ in range(3):
        assert (await strict_client.get("/cases")).status_code == 200

    response = await strict_client.get("/cases")

    assert friendly(response) == (
        429,
        "rate_limited",
        "You're going a bit fast. Please wait a few seconds.",
    )
    assert 1 <= int(response.headers["Retry-After"]) <= 60


async def test_starting_checks_has_its_own_tighter_limit(client: httpx.AsyncClient) -> None:
    responses = [await client.post("/cases/5009/run") for _ in range(11)]  # 5009 is closed

    assert [r.status_code for r in responses[:10]] == [409] * 10
    assert friendly(responses[10])[:2] == (429, "rate_limited")
    assert (await client.get("/cases")).status_code == 200  # other routes keep their limit
