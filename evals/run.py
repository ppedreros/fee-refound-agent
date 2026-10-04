"""The eval runner (SPEC-evals, "Runner"):

    uv run python -m evals.run --mode replay|live [--record] [--only <id> ...]
        [--classifier jev|backup]

Each case runs through the real runner and graph (not the HTTP API) on the evals' own database,
rebuilt at the start. `--mode` is required and never "both". In replay mode the exit code is 1
below 100%: that is the CI gate. Live mode always exits 0 and only reports. `--mode live` and
`--record` spend tokens: ask first.
"""

import argparse
import asyncio
import datetime as dt
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, create_engine, pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.agents.deps import AgentDeps
from backend.agents.runner import RunnerDeps, run_case
from backend.core.logging import configure_logging
from backend.core.settings import ConfigError, Settings, load_settings
from backend.policy.loader import Policy, current_policy
from backend.providers.config import providers_config
from backend.providers.factory import Providers
from backend.providers.replay import ReplayStore
from evals import providers as eval_providers
from evals.case import EvalCase, Mode, load_cases
from evals.database import (
    EvalDatabase,
    EvalSettings,
    eval_database,
    message_override,
    prepare,
)
from evals.report import Outcome, Report
from evals.scoring import score

type ProvidersFor = Callable[[EvalCase], Providers]


@dataclass(frozen=True)
class Suite:
    mode: Mode
    reader: async_sessionmaker[AsyncSession]  # agent_reader: all the graph ever gets
    writer: async_sessionmaker[AsyncSession]  # app_writer: the runner records each run with it
    owner: Engine  # sets a case's message override, and puts the seed's text back
    providers: ProvidersFor
    policy: Policy = field(default_factory=current_policy)


async def run_suite(suite: Suite, cases: Sequence[EvalCase]) -> list[Outcome]:
    outcomes = []
    for case in cases:
        if case.pending_review:
            outcomes.append(Outcome(case.id, case.kind, skipped="pending review"))
            continue
        if suite.mode not in case.modes:
            outcomes.append(Outcome(case.id, case.kind, skipped="not applicable"))
            continue
        providers = suite.providers(case)
        deps = RunnerDeps(
            writer=suite.writer,
            agent=AgentDeps(
                reader=suite.reader,
                classifier=providers.classifier,
                drafter=providers.drafter,
                chooser=providers.chooser,
                policy=suite.policy,
            ),
            provider_modes=providers.modes,
        )
        with message_override(suite.owner, case.conversation_id, case.message_override):
            run = await run_case(
                case.conversation_id, deps, pinned_fee_txn_id=case.pinned_fee_txn_id
            )
        outcomes.append(
            Outcome(case.id, case.kind, result=run.result, checks=score(case.expected, run.result))
        )
    return outcomes


def exit_code(mode: Mode, outcomes: Sequence[Outcome]) -> int:
    """Replay is the gate: every counted case passes, and there is at least one. Live reports."""
    if mode == "live":
        return 0
    counted = [outcome for outcome in outcomes if outcome.skipped is None]
    return 0 if counted and all(outcome.passed for outcome in counted) else 1


# --- The command ---


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.run")
    parser.add_argument("--mode", choices=["replay", "live"], required=True)
    parser.add_argument("--record", action="store_true", help="live only: record what's missing")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run these cases only")
    parser.add_argument("--classifier", choices=["jev", "backup"], default="jev")
    args = parser.parse_args(argv)
    if args.record and args.mode != "live":
        parser.error("--record works in live mode only")

    cases = load_cases()
    if args.only:
        unknown = set(args.only) - {case.id for case in cases}
        if unknown:
            parser.error(f"no such case: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.id in args.only]

    try:
        settings = load_settings()
        database = eval_database(settings, EvalSettings())
    except ConfigError as error:
        sys.exit(f"Invalid configuration: {error}")
    if args.mode == "live" and (settings.jev_api_key is None or settings.openai_api_key is None):
        sys.exit("Live mode needs JEV_API_KEY and OPENAI_API_KEY.")
    configure_logging("ERROR", settings.masking_salt)  # the table is the output
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows consoles

    prepare(database, settings)
    # psycopg's async mode needs a selector loop on Windows; Linux doesn't care.
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    outcomes = asyncio.run(_run(args, settings, database, cases), loop_factory=factory)

    config = providers_config()
    report = Report(
        mode=args.mode,
        date=dt.date.today(),
        policy_version=current_policy().version,
        models={"jev": config.jev.model, "luna": config.luna.model, "sol": config.sol.model},
        outcomes=outcomes,
        classifier=args.classifier,
        recording=args.record,
    )
    print("\n".join([*report.case_lines(), "", *report.summary_lines()]))
    if not args.only and not args.record:  # a partial or filling run is not a report
        for path in report.write():
            print(f"Wrote {path.name}")
    sys.exit(exit_code(args.mode, outcomes))


async def _run(
    args: argparse.Namespace,
    settings: Settings,
    database: EvalDatabase,
    cases: Sequence[EvalCase],
) -> list[Outcome]:
    owner = create_engine(database.owner, poolclass=pool.NullPool)
    reader_engine = create_async_engine(database.agent)
    writer_engine = create_async_engine(database.app)
    built: dict[tuple[tuple[str, ...], bool], Providers] = {}

    with tempfile.TemporaryDirectory(prefix="evals-") as temp:

        def providers_for(case: EvalCase) -> Providers:
            record = args.record and case.record
            key = (case.replay_without, record)
            if key not in built:
                store: ReplayStore | None = None
                if case.replay_without:
                    root = Path(temp) / "-".join(case.replay_without)
                    store = eval_providers.store_without(case.replay_without, root)
                built[key] = eval_providers.build(
                    settings,
                    mode=args.mode,
                    record=record,
                    classifier=args.classifier,
                    store=store,
                )
            return built[key]

        suite = Suite(
            mode=args.mode,
            reader=async_sessionmaker(reader_engine, expire_on_commit=False),
            writer=async_sessionmaker(writer_engine, expire_on_commit=False),
            owner=owner,
            providers=providers_for,
        )
        try:
            return await run_suite(suite, cases)
        finally:
            for providers in built.values():
                await providers.close()
            await reader_engine.dispose()
            await writer_engine.dispose()
            owner.dispose()


if __name__ == "__main__":
    main()
