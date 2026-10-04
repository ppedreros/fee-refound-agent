"""The brief's one API test (SPEC-api AC1): check Ana's case, approve it, send the same approval
again, and the money moves once."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import Engine, text

from tests.api.conftest import wait_for_runs


def anas_checking(engine: Engine) -> tuple[Decimal, int]:
    """The balance of Ana's checking, and how many refunds the app posted there."""
    with engine.connect() as connection:
        balance = connection.execute(text("SELECT balance FROM sub_accounts WHERE id = 1302"))
        posted = connection.execute(
            text("SELECT count(*) FROM transactions WHERE sub_account_id = 1302 AND id >= 1000000")
        )
        return balance.scalar_one(), posted.scalar_one()


async def test_luis_approves_anas_refund_and_a_second_send_changes_nothing(
    client: httpx.AsyncClient, app: FastAPI, with_clauses: Engine
) -> None:
    await client.post("/cases/5012/run")
    await wait_for_runs(app)
    case: dict[str, Any] = (await client.get("/cases/5012")).json()
    assert case["status"] == "ready_to_refund"
    assert case["fee"]["fee_txn_id"] == 88002
    assert case["evidence"]["fee_day"]["rows"]
    assert case["draft"]["text"].startswith("Hi Ana,")

    approval = {
        "run_id": case["run"]["run_id"],
        "action": "approve",
        "reply_text": case["draft"]["text"],
        "reason": None,
    }
    headers = {"Idempotency-Key": str(uuid4())}
    first = await client.post("/cases/5012/decision", json=approval, headers=headers)
    again = await client.post("/cases/5012/decision", json=approval, headers=headers)

    assert first.status_code == 200
    assert first.json()["refunded"] is True
    assert (first.json()["amount"], first.json()["case_status"]) == ("35.00", "done")
    assert (again.status_code, again.json()) == (200, first.json())
    assert anas_checking(with_clauses) == (Decimal("1360.00"), 1)  # $1,325 + $35, once

    done: dict[str, Any] = (await client.get("/cases/5012")).json()
    assert done["status"] == "done"
    assert done["conversation"]["status"] == "closed"
    assert done["conversation"]["messages"][-1]["author_name"] == "Luis"
    assert done["conversation"]["messages"][-1]["body"] == case["draft"]["text"]
    decision = done["decision"]
    assert (decision["by"], decision["action"], decision["refunded"], decision["amount"]) == (
        "Luis",
        "approve",
        True,
        "35.00",
    )
    assert (done["actions"], done["can_run"]) == ([], False)
