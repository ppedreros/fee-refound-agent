"""Live steps for each run, in the API process (SPEC-api, `GET /cases/{id}/runs/{run_id}/events`).

While a run is active, every event it emits is kept, so a client that connects late first gets
the whole history (the step in progress included), then the live events until `done`. Once a run
ends its channel goes away, and its history is read back from `agent_steps` instead.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

type Event = dict[str, Any]


@dataclass
class _Channel:
    history: list[Event] = field(default_factory=list)
    followers: set[asyncio.Queue[Event]] = field(default_factory=set)


class RunEvents:
    def __init__(self) -> None:
        self._runs: dict[UUID, _Channel] = {}

    def open(self, run_id: UUID) -> None:
        """Called before the run starts, so no event is missed."""
        self._runs.setdefault(run_id, _Channel())

    async def publish(self, run_id: UUID, event: Event) -> None:
        channel = self._runs.get(run_id)
        if channel is None:
            return
        channel.history.append(event)
        for queue in channel.followers:
            queue.put_nowait(event)
        if event.get("event") == "done":
            del self._runs[run_id]

    def history(self, run_id: UUID) -> list[Event]:
        """What an active run has emitted so far (empty when it isn't active here)."""
        channel = self._runs.get(run_id)
        return list(channel.history) if channel else []

    def follow(self, run_id: UUID) -> AsyncIterator[Event] | None:
        """The run's events so far, then the live ones until `done`; None when the run isn't
        active in this process."""
        channel = self._runs.get(run_id)
        if channel is None:
            return None
        # Snapshot and subscribe in one step (no await between them), so nothing falls in a gap.
        backlog = list(channel.history)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        channel.followers.add(queue)

        async def events() -> AsyncIterator[Event]:
            try:
                for event in backlog:
                    yield event
                while True:
                    event = await queue.get()
                    yield event
                    if event.get("event") == "done":
                        return
            finally:
                channel.followers.discard(queue)

        return events()
