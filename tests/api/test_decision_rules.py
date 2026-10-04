"""The decision's rules (SPEC-api, `POST /cases/{id}/decision`): validation in order, idempotency,
the approval limit, and the record each decision leaves (audit events, eval candidates)."""

import asyncio
import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, text

from backend.api.resources import AppResources
from tests.api.conftest import wait_for_runs

REPLY = "Hi Ana, we've looked at your account and refunded the $35 fee."


async def checked_ana(client: httpx.AsyncClient, app: FastAPI) -> dict[str, Any]:
    await client.post("/cases/5012/run")
    await wait_for_runs(app)
    case: dict[str, Any] = (await client.get("/cases/5012")).json()
    return case


async def decide(
    client: httpx.AsyncClient, body: dict[str, Any], key: str | None = None, case_id: int = 5012
) -> httpx.Response:
    headers = {"Idempotency-Key": key or str(uuid4())}
    return await client.post(f"/cases/{case_id}/decision", json=body, headers=headers)


def body(case: dict[str, Any], action: str = "approve", **changes: Any) -> dict[str, Any]:
    return {
        "run_id": case["run"]["run_id"],
        "action": action,
        "reply_text": REPLY,
        "reason": None,
    } | changes


def rows(engine: Engine, query: str) -> list[Any]:
    with engine.connect() as connection:
        return list(connection.execute(text(query)))


def error(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


# --- Idempotency and order ---


async def test_a_new_key_on_a_decided_case_is_already_decided(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    case = await checked_ana(client, app)
    await decide(client, body(case))

    second = await decide(client, body(case))

    assert error(second) == (409, "already_decided")
    assert second.json()["error"]["message"].startswith("Luis already decided this case at ")


async def test_the_same_key_with_a_different_reply_is_a_mismatch(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    case = await checked_ana(client, app)
    key = str(uuid4())
    await decide(client, body(case), key)

    changed = await decide(client, body(case, reply_text=REPLY + " Thanks!"), key)

    assert error(changed) == (422, "idempotency_mismatch")
    assert changed.json()["error"]["message"] == (
        "This decision was already sent with different details."
    )


async def test_the_same_request_sent_twice_at_once_refunds_once(
    client: httpx.AsyncClient, app: FastAPI, with_clauses: Engine
) -> None:
    case = await checked_ana(client, app)
    key = str(uuid4())

    first, second = await asyncio.gather(
        decide(client, body(case), key), decide(client, body(case), key)
    )

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json() == second.json()
    assert len(rows(with_clauses, "SELECT id FROM refunds")) == 1
    assert len(rows(with_clauses, "SELECT id FROM decisions")) == 1


async def test_a_decision_on_an_older_run_is_stale(client: httpx.AsyncClient, app: FastAPI) -> None:
    older = await checked_ana(client, app)
    await checked_ana(client, app)  # "Check again"

    stale = await decide(client, body(older))

    assert error(stale) == (409, "stale_run")
    assert stale.json()["error"]["message"] == (
        "This case was checked again. Please look at the new result."
    )


async def test_an_action_the_case_does_not_offer_is_refused(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    case = await checked_ana(client, app)

    assert error(await decide(client, body(case, "reply_only"))) == (422, "action_not_allowed")


async def test_an_unknown_case_is_a_friendly_404(client: httpx.AsyncClient) -> None:
    response = await decide(
        client, {"run_id": str(uuid4()), "action": "approve", "reply_text": REPLY}, case_id=424242
    )

    assert error(response) == (404, "not_found")


async def test_a_case_that_was_never_checked_has_no_run_to_decide_on(
    client: httpx.AsyncClient,
) -> None:
    response = await decide(
        client, {"run_id": str(uuid4()), "action": "reply_only", "reply_text": "Hi"}, case_id=5011
    )

    assert error(response) == (409, "stale_run")


# --- The approval limit (D-api-1) ---


async def test_a_refund_above_the_limit_needs_a_supervisor(
    client: httpx.AsyncClient, app: FastAPI, with_clauses: Engine
) -> None:
    case = await checked_ana(client, app)
    resources: AppResources = app.state.resources
    resources.policy_params = resources.policy_params.model_copy(
        update={"staff_limit_usd": Decimal("20")}
    )

    refused = await decide(client, body(case))
    kept = await decide(client, body(case, "reject", reason="The member asked us to wait."))

    assert error(refused) == (403, "over_limit")
    assert refused.json()["error"]["message"] == (
        "A supervisor needs to approve this refund. That happens outside this tool for now."
    )
    assert kept.status_code == 200  # "Don't refund" moves no money, so it stays available
    assert kept.json()["refunded"] is False
    assert rows(with_clauses, "SELECT id FROM refunds") == []


# --- What Luis sends ---


@pytest.mark.parametrize(
    "headers",
    [{}, {"Idempotency-Key": "not-a-uuid"}],
)
async def test_the_idempotency_key_must_be_a_uuid(
    client: httpx.AsyncClient, app: FastAPI, headers: dict[str, str]
) -> None:
    case = await checked_ana(client, app)

    response = await client.post("/cases/5012/decision", json=body(case), headers=headers)

    assert error(response) == (422, "invalid_idempotency_key")


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"reply_text": "   "}, "invalid_reply"),
        ({"reply_text": "x" * 2001}, "invalid_reply"),
        ({"reply_text": "Hi {{first_name}}, done."}, "invalid_reply"),
        ({"reply_text": "Hi Ana\x07, done."}, "invalid_reply"),
        ({"reason": "Looks fine to me."}, "invalid_reason"),  # approve takes no reason
        ({"amount": "500.00"}, "invalid_request"),  # the amount never comes from the client
    ],
)
async def test_what_luis_sends_is_validated(
    client: httpx.AsyncClient, app: FastAPI, changes: dict[str, Any], code: str
) -> None:
    case = await checked_ana(client, app)

    assert error(await decide(client, body(case, **changes)))[1] == code


@pytest.mark.parametrize("reason", [None, "too short", "x" * 501])
async def test_acting_against_the_recommendation_needs_a_reason(
    client: httpx.AsyncClient, app: FastAPI, reason: str | None
) -> None:
    case = await checked_ana(client, app)

    response = await decide(client, body(case, "reject", reason=reason))

    assert error(response) == (422, "invalid_reason")


async def test_a_reply_keeps_its_line_breaks(client: httpx.AsyncClient, app: FastAPI) -> None:
    case = await checked_ana(client, app)

    response = await decide(client, body(case, "edit", reply_text="Hi Ana,\n\nAll done.\n"))

    assert response.status_code == 200
    done = (await client.get("/cases/5012")).json()
    assert done["conversation"]["messages"][-1]["body"] == "Hi Ana,\n\nAll done."


# --- The record a decision leaves ---


async def test_an_approval_writes_its_audit_events_without_personal_data(
    client: httpx.AsyncClient, app: FastAPI, with_clauses: Engine
) -> None:
    case = await checked_ana(client, app)

    await decide(client, body(case))

    events = rows(
        with_clauses, "SELECT actor, action, case_id, details FROM audit_events ORDER BY id"
    )
    assert [(e.actor, e.action, e.case_id) for e in events] == [
        ("S07", "decision_made", 5012),
        ("S07", "refund_posted", 5012),
        ("S07", "reply_sent", 5012),
    ]
    details = json.dumps([e.details for e in events])
    assert "Ana" not in details and "884210" not in details
    assert rows(with_clauses, "SELECT id FROM eval_candidates") == []  # approve is not feedback


async def test_dont_refund_leaves_an_eval_candidate_with_masked_text(
    client: httpx.AsyncClient, app: FastAPI, with_clauses: Engine
) -> None:
    case = await checked_ana(client, app)

    response = await decide(
        client,
        body(
            case,
            "reject",
            reply_text="Hi Ana, we can't refund this fee.",
            reason="Ana Torres asked about a different fee.",
        ),
    )

    assert response.json()["refunded"] is False
    actions = [e.action for e in rows(with_clauses, "SELECT action FROM audit_events")]
    assert "refund_posted" not in actions
    (candidate,) = rows(with_clauses, "SELECT kind, masked_input, expected FROM eval_candidates")
    assert candidate.kind == "reject"
    assert candidate.expected["recommendation"] == "no_refund"  # what Luis did
    stored = json.dumps([candidate.masked_input, candidate.expected])
    assert "Ana" not in stored and "Torres" not in stored


# --- When the policy says no (SPEC-data scenarios 6 and 17) ---


async def checked(client: httpx.AsyncClient, app: FastAPI, case_id: int) -> dict[str, Any]:
    await client.post(f"/cases/{case_id}/run")
    await wait_for_runs(app)
    case: dict[str, Any] = (await client.get(f"/cases/{case_id}")).json()
    return case


async def test_above_the_limit_approving_needs_a_supervisor_and_no_refund_is_offered(
    client: httpx.AsyncClient, app: FastAPI, with_clauses: Engine
) -> None:
    case = await checked(client, app, 5117)

    assert case["status"] == "needs_supervisor"
    assert case["actions"] == ["reject", "reply_only"]
    refused = await decide(client, body(case), case_id=5117)
    assert error(refused) == (403, "over_limit")
    kept = await decide(
        client,
        body(case, "reject", reason="Waiting for the supervisor to review it."),
        case_id=5117,
    )
    assert (kept.status_code, kept.json()["refunded"]) == (200, False)
    assert rows(with_clauses, "SELECT id FROM refunds") == []


async def test_a_decline_sends_the_reply_and_refund_anyway_refunds(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    case = await checked(client, app, 5106)
    assert case["status"] == "recommend_no_refund"
    assert case["actions"] == ["approve", "edit", "reject"]

    response = await decide(
        client,
        body(case, "reject", reason="A long-standing member; one more refund is fine."),
        case_id=5106,
    )

    result = response.json()
    assert (result["refunded"], result["amount"]) == (True, "35.00")
