"""Sessions as the two test roles, on the seed with policy clauses, for the agent's and the evals'
integration tests (the graph gets the reader only; the runner records with the writer)."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.integration.roles import TEST_AGENT_ROLE, TEST_APP_ROLE, role_url


@pytest.fixture
async def reader(
    with_clauses: Engine, test_database_url: URL
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(role_url(test_database_url, TEST_AGENT_ROLE))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def writer(
    with_clauses: Engine, test_database_url: URL
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(role_url(test_database_url, TEST_APP_ROLE))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
