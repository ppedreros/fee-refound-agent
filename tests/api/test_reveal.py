"""The full account number, on request, and audited (SPEC-api AC7)."""

from typing import Any

import httpx
from sqlalchemy import Engine, text


def audit(engine: Engine) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT actor, action, case_id, details FROM audit_events ORDER BY id")
        )
        return [tuple(row) for row in rows]


async def test_the_full_number_is_shown_and_the_reveal_is_audited(
    client: httpx.AsyncClient, with_clauses: Engine
) -> None:
    response = await client.get("/cases/5012/accounts/710/number")

    assert (response.status_code, response.json()) == (200, {"account_number": "884210"})
    assert audit(with_clauses) == [("S07", "account_number_revealed", 5012, {"account_id": 710})]


async def test_another_members_account_is_not_found(
    client: httpx.AsyncClient, with_clauses: Engine
) -> None:
    response = await client.get("/cases/5012/accounts/7061/number")  # Grace's account

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "We couldn't find that account."
    assert audit(with_clauses) == []
