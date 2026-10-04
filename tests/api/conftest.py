"""API tests run the real app against fees_test, with the test roles and in-process fake providers.
Settings insist on the real role names, so the database resources are injected here."""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from backend.api.main import create_app
from backend.api.resources import AppResources
from backend.core.settings import Settings
from backend.providers.types import Classifier
from tests.integration.agents.fakes import FakeClassifier, FakeDrafter, jev_answers
from tests.integration.roles import TEST_AGENT_ROLE, TEST_APP_ROLE, role_url

SETTINGS = Settings(
    _env_file=None,
    app_database_url="postgresql+psycopg://app_writer:unused@127.0.0.1:1/unused",
    agent_database_url="postgresql+psycopg://agent_reader:unused@127.0.0.1:1/unused",
    masking_salt="test-salt",
)


def resources_for(
    test_database_url: URL, classifier: Classifier
) -> Callable[[Settings], AppResources]:
    def build(settings: Settings) -> AppResources:
        return AppResources(
            writer_engine=create_async_engine(role_url(test_database_url, TEST_APP_ROLE)),
            reader_engine=create_async_engine(role_url(test_database_url, TEST_AGENT_ROLE)),
            classifier=classifier,
            drafter=FakeDrafter(),
            provider_modes={"jev": "live", "openai": "replay"},
        )

    return build


@pytest.fixture
def classifier() -> FakeClassifier:
    return FakeClassifier(jev_answers())


@pytest.fixture
async def app(
    with_clauses: Engine, test_database_url: URL, classifier: FakeClassifier
) -> AsyncIterator[FastAPI]:
    application = create_app(SETTINGS, resources=resources_for(test_database_url, classifier))
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def wait_for_runs(app: FastAPI) -> None:
    """Background runs are asyncio tasks in the API process; tests wait for them to end."""
    tasks: set[asyncio.Task[Any]] = app.state.run_tasks
    if tasks:
        await asyncio.gather(*tasks)
