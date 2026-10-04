"""Live steps for one run, in the API process (SPEC-api, `GET /cases/{id}/runs/{run_id}/events`).
A client that arrives late still gets every event from the start, then the live ones."""

import asyncio
from typing import Any
from uuid import uuid4

from backend.api.events import RunEvents


def step(node: str, state: str) -> dict[str, Any]:
    return {"event": "step", "node": node, "state": state}


async def collect(events: Any) -> list[dict[str, Any]]:
    return [event async for event in events]


async def test_a_late_follower_gets_the_history_then_the_live_events_until_done() -> None:
    hub, run = RunEvents(), uuid4()
    hub.open(run)
    await hub.publish(run, step("load_conversation", "started"))
    await hub.publish(run, step("load_conversation", "finished"))

    follower = hub.follow(run)
    assert follower is not None
    task = asyncio.create_task(collect(follower))
    await hub.publish(run, step("triage", "started"))
    await hub.publish(run, {"event": "done", "status": "ready_to_refund"})

    assert await task == [
        step("load_conversation", "started"),
        step("load_conversation", "finished"),
        step("triage", "started"),
        {"event": "done", "status": "ready_to_refund"},
    ]


async def test_a_finished_run_has_no_live_channel() -> None:
    hub, run = RunEvents(), uuid4()
    hub.open(run)
    await hub.publish(run, {"event": "done", "status": "ready_to_refund"})

    assert hub.follow(run) is None  # its history is read back from the run trace instead
    assert hub.follow(uuid4()) is None


async def test_every_follower_gets_every_event() -> None:
    hub, run = RunEvents(), uuid4()
    hub.open(run)
    first, second = hub.follow(run), hub.follow(run)
    assert first is not None and second is not None
    tasks = [asyncio.create_task(collect(first)), asyncio.create_task(collect(second))]
    await asyncio.sleep(0)

    await hub.publish(run, step("triage", "started"))
    await hub.publish(run, {"event": "done", "status": "not_about_fee"})

    one, two = await asyncio.gather(*tasks)
    assert one == two == [step("triage", "started"), {"event": "done", "status": "not_about_fee"}]
