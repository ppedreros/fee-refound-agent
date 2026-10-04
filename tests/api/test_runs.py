"""GET /cases (the queue) and POST /cases/{id}/run (SPEC-api)."""

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL

from backend.api.main import create_app
from tests.api.conftest import SETTINGS, resources_for, wait_for_runs
from tests.integration.agents.fakes import FakeClassifier


def insert_running_run(engine: Engine, case_id: int) -> str:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO cases (conversation_id, status) VALUES (:c, 'checking')"),
            {"c": case_id},
        )
        return str(
            connection.execute(
                text(
                    "INSERT INTO agent_runs (case_id, status) VALUES (:c, 'running') RETURNING id"
                ),
                {"c": case_id},
            ).scalar_one()
        )


# --- The queue ---


async def test_the_open_queue_lists_conversations_waiting_for_us_oldest_first(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/cases")

    assert response.status_code == 200
    items = response.json()["items"]
    received = [item["received_at"] for item in items]
    assert received == sorted(received)  # oldest unanswered message first
    brief = [item["id"] for item in items if item["id"] < 5100]
    assert brief == [5008, 5011, 5012]  # 5010 waits for the member; 5009 is closed
    ana = next(item for item in items if item["id"] == 5012)
    assert ana == {
        "id": 5012,
        "member_name": "Ana T.",
        "subject": "Overdraft fee",
        "received_at": "2026-09-15T08:12:44Z",
        "status": "not_checked",
        "topic": None,
        "amount": None,
        "checked_at": None,
    }


async def test_the_done_view_lists_closed_conversations(client: httpx.AsyncClient) -> None:
    response = await client.get("/cases", params={"view": "done"})

    assert [item["id"] for item in response.json()["items"]] == [5009]


async def test_the_queue_pages_with_an_opaque_cursor(client: httpx.AsyncClient) -> None:
    everything = [i["id"] for i in (await client.get("/cases")).json()["items"]]
    paged: list[int] = []
    cursor = None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await client.get("/cases", params=params)).json()
        paged += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert paged == everything
    assert len(everything) > 2


async def test_queue_parameters_are_validated(client: httpx.AsyncClient) -> None:
    assert (await client.get("/cases", params={"limit": 0})).status_code == 422
    assert (await client.get("/cases", params={"view": "everything"})).status_code == 422
    assert (await client.get("/cases", params={"cursor": "not-a-cursor"})).status_code == 422


# --- Running a check ---


async def test_a_check_runs_in_the_background_and_the_queue_shows_its_outcome(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    started = await client.post("/cases/5012/run")

    assert started.status_code == 202
    assert started.json()["run_id"]
    await wait_for_runs(app)
    ana = next(i for i in (await client.get("/cases")).json()["items"] if i["id"] == 5012)
    assert (ana["status"], ana["topic"], ana["amount"]) == (
        "ready_to_refund",
        "fee_refund_request",
        "35.00",
    )
    assert ana["checked_at"] is not None


async def test_a_closed_conversation_cannot_run(client: httpx.AsyncClient) -> None:
    response = await client.post("/cases/5009/run")

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "case_not_running", "message": "This conversation is closed."}
    }


async def test_a_conversation_waiting_for_the_member_cannot_run(client: httpx.AsyncClient) -> None:
    response = await client.post("/cases/5010/run")

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "This conversation is waiting for the member."


async def test_a_second_check_during_a_run_points_to_the_active_run(
    client: httpx.AsyncClient, with_clauses: Engine
) -> None:
    running = insert_running_run(with_clauses, 5012)

    response = await client.post("/cases/5012/run")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_in_progress"
    assert response.json()["run_id"] == running


async def test_an_unknown_conversation_is_a_friendly_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/cases/999999/run")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "We couldn't find that conversation."


async def test_a_pinned_fee_must_be_one_of_the_candidates(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    await client.post("/cases/5012/run")
    await wait_for_runs(app)

    response = await client.post("/cases/5012/run", json={"fee_txn_id": 88001})

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "invalid_fee",
        "message": "That fee isn't one of the options for this case.",
    }


async def test_luis_picks_one_of_two_fees_and_the_check_runs_again_with_it(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    await client.post("/cases/5109/run")  # scenario 9: two fees, a vague message
    await wait_for_runs(app)
    case = (await client.get("/cases/5109")).json()
    assert (case["status"], case["can_pick_fee"]) == ("needs_your_call", True)
    minus = chr(0x2212)  # labels use a real minus sign, as on a statement
    assert [c["label"] for c in case["candidates"]] == [
        f"Sep 14 · {minus}$35.00 · Courtesy Pay fee · after CITY POWER & LIGHT {minus}$60.00",
        f"Sep 14 · {minus}$35.00 · Courtesy Pay fee · after STREAMFLIX {minus}$15.99",
    ]

    started = await client.post("/cases/5109/run", json={"fee_txn_id": 90904})
    await wait_for_runs(app)
    picked = (await client.get("/cases/5109")).json()

    assert started.status_code == 202
    assert (picked["fee"]["fee_txn_id"], picked["fee"]["source"]) == (90904, "staff")
    assert (picked["status"], picked["can_pick_fee"]) == ("ready_to_refund", False)


async def test_startup_interrupts_runs_left_running(
    with_clauses: Engine, test_database_url: URL, classifier: FakeClassifier
) -> None:
    insert_running_run(with_clauses, 5012)
    application = create_app(SETTINGS, resources=resources_for(test_database_url, classifier))

    async with application.router.lifespan_context(application):
        pass

    with with_clauses.connect() as connection:
        run_status = connection.execute(text("SELECT status FROM agent_runs")).scalar_one()
        case_status = connection.execute(text("SELECT status FROM cases")).scalar_one()
    assert (run_status, case_status) == ("interrupted", "not_checked")


# --- Live steps (server-sent events) ---

NODES = {
    "load_conversation",
    "triage",
    "load_accounts",
    "load_transactions",
    "load_refund_history",
    "identify_fee",
    "run_checks",
    "decide",
    "find_policy",
    "draft",
    "finalize",
}


def sse_events(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def assert_every_node_starts_then_finishes(events: list[dict[str, Any]]) -> None:
    steps = [(e["node"], e["state"]) for e in events if e["event"] == "step"]
    assert {node for node, _ in steps} == NODES
    for node in NODES:
        assert steps.index((node, "started")) < steps.index((node, "finished"))
    assert steps[:2] == [("load_conversation", "started"), ("load_conversation", "finished")]


async def test_a_finished_run_streams_its_whole_history_then_done(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    run_id = (await client.post("/cases/5012/run")).json()["run_id"]
    await wait_for_runs(app)

    response = await client.get(f"/cases/5012/runs/{run_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    assert_every_node_starts_then_finishes(events)
    assert events[-1] == {"event": "done", "status": "ready_to_refund"}


async def test_a_late_follower_gets_the_steps_so_far_then_the_live_ones(
    client: httpx.AsyncClient,
    app: FastAPI,
    classifier: FakeClassifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    answer = classifier.classify

    async def held(*args: Any, **kwargs: Any) -> Any:
        await gate.wait()  # the run stops inside triage until the follower is there
        return await answer(*args, **kwargs)

    monkeypatch.setattr(classifier, "classify", held)
    run_id = (await client.post("/cases/5012/run")).json()["run_id"]
    while not app.state.run_events.history(UUID(run_id)):
        await asyncio.sleep(0.01)

    follower = asyncio.create_task(client.get(f"/cases/5012/runs/{run_id}/events"))
    await asyncio.sleep(0.1)
    gate.set()
    events = sse_events((await follower).text)
    await wait_for_runs(app)

    assert_every_node_starts_then_finishes(events)
    assert events[-1] == {"event": "done", "status": "ready_to_refund"}


async def test_a_run_of_another_case_has_no_events(client: httpx.AsyncClient, app: FastAPI) -> None:
    run_id = (await client.post("/cases/5012/run")).json()["run_id"]
    await wait_for_runs(app)

    other_case = await client.get(f"/cases/5011/runs/{run_id}/events")
    unknown = await client.get(f"/cases/5012/runs/{uuid4()}/events")

    assert (other_case.status_code, unknown.status_code) == (404, 404)
    assert other_case.json()["error"]["message"] == "We couldn't find that check."
