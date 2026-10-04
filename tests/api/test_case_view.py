"""GET /cases/{id}: everything Luis's case pane reads, and nothing it must not show (SPEC-api)."""

import json
from typing import Any

import httpx
from fastapi import FastAPI

from backend.policy.reasons import ReasonCode
from tests.api.conftest import wait_for_runs
from tests.integration.agents.fakes import FakeClassifier


async def checked_ana(client: httpx.AsyncClient, app: FastAPI) -> dict[str, Any]:
    await client.post("/cases/5012/run")
    await wait_for_runs(app)
    response = await client.get("/cases/5012")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def test_anas_case_has_the_decision_card(client: httpx.AsyncClient, app: FastAPI) -> None:
    case = await checked_ana(client, app)

    assert case["status"] == "ready_to_refund"
    assert case["topic"] == "fee_refund_request"
    assert case["language"] == "en"
    assert case["summary"] == "The paycheck arrived the same day and the bill posted before it."
    assert case["reasons"] == []
    assert case["notes"] == []
    assert case["recommendation"] == {"action": "refund", "amount": "35.00"}
    assert case["actions"] == ["approve", "edit", "reject"]
    assert case["can_run"] is True
    assert case["can_pick_fee"] is False


async def test_anas_case_has_the_member_and_the_conversation(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    case = await checked_ana(client, app)

    assert case["member"]["name"] == "Ana Torres"
    assert [a["masked_number"] for a in case["member"]["accounts"]] == ["••4210", "••4211"]
    checking = case["member"]["accounts"][0]["sub_accounts"][1]
    assert (checking["name"], checking["balance"]) == ("Everyday Checking", "1325.00")
    assert case["conversation"]["subject"] == "Overdraft fee"
    (message,) = case["conversation"]["messages"]
    assert (message["author"], message["author_name"]) == ("member", "Ana Torres")


async def test_anas_case_has_the_fee_and_the_evidence(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    case = await checked_ana(client, app)
    evidence = case["evidence"]

    assert case["fee"]["fee_txn_id"] == 88002
    assert (case["fee"]["fee_type"], case["fee"]["source"]) == ("Courtesy Pay", "rule")
    day = evidence["fee_day"]
    assert [(r["position"], r["amount"], r["is_fee"], r["is_deposit"]) for r in day["rows"]] == [
        (1, "-60.00", False, False),
        (2, "-35.00", True, False),
        (3, "1400.00", False, True),
    ]
    assert day["summary"] == (
        "If the paycheck had posted first, the balance would have stayed at $1,360."
    )
    window = evidence["refunds_in_window"]
    assert (window["start"], window["end"], window["count"], window["max_allowed"]) == (
        "2025-09-15",
        "2026-09-14",
        2,
        3,
    )
    assert evidence["standing"] == {"ok": True, "below_zero": []}
    assert all(check["passed"] for check in evidence["checks"])
    assert evidence["checks"][0]["label"] == "A same-day deposit would have covered the payment"


async def test_anas_case_quotes_the_clause_and_fills_in_the_reply(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    case = await checked_ana(client, app)

    assert case["clause"]["doc_title"] == "Fee Refund Policy"
    assert case["clause"]["section"] == "4. Same-day deposits"
    assert case["clause"]["text"].startswith("We refund a Courtesy Pay fee")
    assert case["draft"]["text"].startswith("Hi Ana, thanks for reaching out.")
    assert "$35" in case["draft"]["text"]
    assert case["draft"]["source"] == "model"


async def test_anas_case_shows_how_it_was_prepared(client: httpx.AsyncClient, app: FastAPI) -> None:
    run = (await checked_ana(client, app))["run"]

    assert run["provider_mode"] == {"jev": "live", "openai": "replay"}
    assert run["cost_usd"] == "0.001742"  # Jev $0.000032 and Sol $0.001710
    assert run["duration_ms"] >= 0
    assert len(run["steps"]) == 11
    assert run["steps"][0] == {
        "node": "load_conversation",
        "state": "finished",
        "latency_ms": run["steps"][0]["latency_ms"],
    }


async def test_nothing_internal_or_personal_beyond_the_page_leaks(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    case = await checked_ana(client, app)
    text = json.dumps(case)

    assert "{{first_name}}" not in text
    assert "[ACCOUNT" not in text
    assert "884210" not in text and "884211" not in text
    codes = {f'"{code.value}"' for code in ReasonCode}
    assert not any(code in text for code in codes)


async def test_with_jev_down_the_reasons_are_sentences_with_a_next_step(
    client: httpx.AsyncClient, app: FastAPI, classifier: FakeClassifier
) -> None:
    classifier.answers = None

    case = await checked_ana(client, app)

    assert case["status"] == "needs_your_call"
    assert case["summary"] is None
    assert case["reasons"] == [
        {
            "message": "The automatic check isn't available right now. Everything below comes "
            "from Ana's account.",
            "next_step": "Decide, or try again",
        }
    ]
    assert case["recommendation"] == {"action": "refund", "amount": "35.00"}
    assert case["draft"]["text"].startswith("Hi Ana,")
    assert case["actions"] == ["approve", "edit", "reject"]


async def test_a_case_not_checked_yet(client: httpx.AsyncClient) -> None:
    case = (await client.get("/cases/5011")).json()

    assert case["status"] == "not_checked"
    assert case["topic"] is None
    assert case["run"] is None
    assert case["actions"] == []
    assert case["can_run"] is True
    assert [m["author"] for m in case["conversation"]["messages"]] == ["member", "staff"]
    assert case["conversation"]["messages"][1]["author_name"] == "Sam"


async def test_a_closed_conversation_cannot_be_checked(client: httpx.AsyncClient) -> None:
    assert (await client.get("/cases/5009")).json()["can_run"] is False


async def test_an_unknown_case_is_a_friendly_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/cases/424242")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "We couldn't find that conversation."
