"""Auto-approve (SPEC-api, "Auto-approve"; D5): off in the shipped config, and exercised only
here. With the flag on, a clear case is approved by SYSTEM through the decision service."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL

from backend.api.main import create_app
from backend.core.settings import Settings
from tests.api.conftest import SETTINGS, resources_for, wait_for_runs
from tests.integration.agents.fakes import FakeClassifier, jev_answers


def test_the_flag_is_off_unless_it_is_set() -> None:
    assert Settings.model_fields["auto_approve_enabled"].default is False


@pytest.fixture
async def auto_app(with_clauses: Engine, test_database_url: URL) -> AsyncIterator[FastAPI]:
    settings = SETTINGS.model_copy(update={"auto_approve_enabled": True})
    application = create_app(
        settings, resources=resources_for(test_database_url, FakeClassifier(jev_answers()))
    )
    async with application.router.lifespan_context(application):
        yield application


async def checked(app: FastAPI, case_id: int) -> dict[str, Any]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await http.post(f"/cases/{case_id}/run")
        await wait_for_runs(app)
        case: dict[str, Any] = (await http.get(f"/cases/{case_id}")).json()
        return case


async def test_with_the_flag_on_a_clear_case_is_approved_by_the_system(
    auto_app: FastAPI, with_clauses: Engine
) -> None:
    case = await checked(auto_app, 5012)

    assert case["status"] == "done"
    decision = case["decision"]
    assert (decision["by"], decision["action"], decision["refunded"]) == (
        "Automatic approval",
        "approve",
        True,
    )
    with with_clauses.connect() as connection:
        key = connection.execute(text("SELECT idempotency_key::text FROM decisions")).scalar_one()
    assert key == case["run"]["run_id"]  # the run id is the idempotency key


async def test_with_the_flag_on_a_case_that_is_not_clear_waits_for_luis(
    auto_app: FastAPI,
) -> None:
    case = await checked(auto_app, 5106)  # a decline is never clear

    assert case["status"] == "recommend_no_refund"
    assert case["decision"] is None


async def test_with_the_flag_off_nothing_is_approved(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    await client.post("/cases/5012/run")
    await wait_for_runs(app)

    case = (await client.get("/cases/5012")).json()
    assert (case["status"], case["decision"]) == ("ready_to_refund", None)
