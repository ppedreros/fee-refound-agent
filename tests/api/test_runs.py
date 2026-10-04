"""GET /cases (the queue) and POST /cases/{id}/run (SPEC-api)."""

import httpx
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
    assert [item["id"] for item in items] == [5008, 5011, 5012]
    ana = items[-1]
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
    first = (await client.get("/cases", params={"limit": 2})).json()
    second = (
        await client.get("/cases", params={"limit": 2, "cursor": first["next_cursor"]})
    ).json()

    assert [i["id"] for i in first["items"]] == [5008, 5011]
    assert [i["id"] for i in second["items"]] == [5012]
    assert second["next_cursor"] is None


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
