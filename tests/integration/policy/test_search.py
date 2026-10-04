"""Full-text search over the policy clauses, as the agent's read-only role (SPEC-policy AC4)."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.policy.search import build_policy_query, search_clauses
from tests.integration.roles import TEST_AGENT_ROLE, role_url

ANA_RULES = [
    "verify_posting_order",  # the rule that decided Ana's case comes first
    "check_not_already_refunded",
    "check_yearly_limit",
    "check_good_standing",
    "check_approval_limit",
]


@pytest.fixture
async def reader(with_clauses: Engine, test_database_url: URL) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(role_url(test_database_url, TEST_AGENT_ROLE))
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


async def test_anas_facts_find_the_refund_limit_and_the_same_day_clauses(
    reader: AsyncSession,
) -> None:
    query = build_policy_query(fee_type="Courtesy Pay", rules=ANA_RULES)

    found = await search_clauses(reader, query)

    ids = [clause.id for clause in found]
    assert len(ids) == 5
    assert {"fee-refund-policy#2", "fee-refund-policy#4"} <= set(ids)
    assert found[0].text  # verbatim text, ready to quote


async def test_nothing_matching_gives_nothing(reader: AsyncSession) -> None:
    assert await search_clauses(reader, "zebra OR xylophone") == []
