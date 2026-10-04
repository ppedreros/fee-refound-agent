"""Record live model answers for the seed scenarios (D10: replay mode). "Ask first": it spends
tokens. Run it inside the backend container, which has the keys and the database:

    docker compose run --rm -v ./backend/providers/recordings:/app/backend/providers/recordings \
        backend python -m backend.record

It runs the graph for every scenario but 18, the one that shows the fallback in replay, plus
both ways of "Pick the fee" for scenario 9, with each provider wrapped in a recorder. It writes
nothing to the database: runs here are not cases. The evals runner (`evals.run --record`) will
reuse `record_cases`.
"""

import asyncio
import sys
from collections.abc import Sequence
from uuid import uuid4

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.agents.deps import AgentDeps
from backend.agents.graph import build_graph
from backend.agents.state import GraphState
from backend.core.logging import configure_logging
from backend.core.settings import Settings, load_settings
from backend.providers.factory import build_providers

# (conversation, pinned fee): the brief's conversations, then scenarios 6-17 (5100 + n).
CASES: list[tuple[int, int | None]] = [
    (5012, None),
    (5011, None),
    (5010, None),
    (5009, None),
    (5008, None),
    *((5100 + n, None) for n in range(6, 18)),
    (5109, 90902),  # "Pick the fee": the electric bill's fee
    (5109, 90904),  # ... or the streaming service's
]
NEVER_RECORDED = {5118}  # scenario 18: its answers stay unrecorded, to show the fallback

log = structlog.get_logger()


async def record_cases(
    deps: AgentDeps, cases: Sequence[tuple[int, int | None]]
) -> list[tuple[int, int | None, str]]:
    """Run each case through the graph with `deps` (recording providers when recording)."""
    graph = build_graph()
    outcomes = []
    for case_id, pinned in cases:
        state = GraphState(case_id=case_id, run_id=uuid4(), pinned_fee_txn_id=pinned)
        final = await graph.ainvoke(state, context=deps)
        status = final["result"]["status"]
        log.info("recorded", case_id=case_id, pinned_fee_txn_id=pinned, status=status)
        outcomes.append((case_id, pinned, status))
    return outcomes


async def record(settings: Settings) -> list[tuple[int, int | None, str]]:
    modes = settings.provider_modes
    if modes.jev != "live" or modes.openai != "live":
        raise SystemExit("Recording needs both keys (JEV_API_KEY, OPENAI_API_KEY) and live mode.")
    providers = build_providers(settings, record=True)
    engine = create_async_engine(settings.agent_database_url.get_secret_value())
    deps = AgentDeps(
        reader=async_sessionmaker(engine, expire_on_commit=False),
        classifier=providers.classifier,
        drafter=providers.drafter,
        chooser=providers.chooser,
    )
    try:
        return await record_cases(deps, CASES)
    finally:
        await providers.close()
        await engine.dispose()


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level, settings.masking_salt)
    # psycopg's async mode needs a selector loop on Windows; Linux (the container) doesn't care.
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    for case_id, pinned, status in asyncio.run(record(settings), loop_factory=factory):
        pick = f" (fee {pinned})" if pinned else ""
        print(f"{case_id}{pick}: {status}")


if __name__ == "__main__":
    main()
