"""The eval runner (SPEC-evals, "Runner"):

    uv run python -m evals.run --mode replay|live [--record] [--only <id> ...]
        [--classifier jev|backup] [--sweep intent=0.60:0.95:0.05]

Each case runs through the real runner and graph (not the HTTP API) on the evals' own database,
rebuilt at the start. `--mode` is required and never "both". In replay mode the exit code is 1
below 100%: that is the CI gate. Live mode always exits 0 and only reports. `--mode live` and
`--record` spend tokens: ask first.

After a run with Jev, the backup is asked the same triage questions, for the classifier
comparison (`evals/compare.py`). `--sweep` runs the replay suite once per threshold value instead,
and reports the pass and manual-review rates of each: the recorded answers, no new calls.
"""

import argparse
import asyncio
import datetime as dt
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import Engine, create_engine, pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.agents.deps import AgentDeps
from backend.agents.runner import RunnerDeps, run_case
from backend.agents.triage_rules import THRESHOLDS, Thresholds
from backend.core.logging import configure_logging
from backend.core.settings import ConfigError, Settings, load_settings
from backend.policy.loader import Policy, current_policy
from backend.providers.config import providers_config
from backend.providers.factory import Providers
from backend.providers.replay import ReplayStore
from evals import providers as eval_providers
from evals.case import EvalCase, Mode, load_cases
from evals.compare import Comparison, compare
from evals.database import (
    EvalDatabase,
    EvalSettings,
    eval_database,
    message_override,
    prepare,
)
from evals.meter import Meter
from evals.report import Outcome, Report, SweepReport, SweepRow
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
    thresholds: Thresholds = THRESHOLDS
    meter: Meter | None = None  # every model call, for cost, latency and the comparison


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
        classifier, drafter, chooser = providers.classifier, providers.drafter, providers.chooser
        if suite.meter is not None:
            suite.meter.case_id = case.id
            classifier, drafter = suite.meter.classifier(classifier), suite.meter.drafter(drafter)
            chooser = suite.meter.classifier(chooser) if chooser is not None else None
        deps = RunnerDeps(
            writer=suite.writer,
            agent=AgentDeps(
                reader=suite.reader,
                classifier=classifier,
                drafter=drafter,
                chooser=chooser,
                policy=suite.policy,
                thresholds=suite.thresholds,
            ),
            provider_modes=providers.modes,
        )
        with message_override(suite.owner, case.conversation_id, case.message_override):
            started = time.monotonic()
            run = await run_case(
                case.conversation_id, deps, pinned_fee_txn_id=case.pinned_fee_txn_id
            )
            wall_ms = round((time.monotonic() - started) * 1000)
        outcomes.append(
            Outcome(
                case.id,
                case.kind,
                result=run.result,
                checks=score(case.expected, run.result),
                wall_ms=wall_ms,
                calls=suite.meter.of(case.id) if suite.meter is not None else (),
            )
        )
    return outcomes


def exit_code(mode: Mode, outcomes: Sequence[Outcome]) -> int:
    """Replay is the gate: every counted case passes, and there is at least one. Live reports."""
    if mode == "live":
        return 0
    counted = [outcome for outcome in outcomes if outcome.skipped is None]
    return 0 if counted and all(outcome.passed for outcome in counted) else 1


def parse_sweep(spec: str) -> tuple[str, list[Decimal]]:
    """`intent=0.60:0.95:0.05` → ("intent_min_confidence", [0.60, 0.65, …, 0.95]). The name is a
    threshold in `thresholds.yaml`, or the start of exactly one."""
    name, equals, bounds = spec.partition("=")
    fields = [f for f in Thresholds.model_fields if f == name or f.startswith(f"{name}_")]
    if not equals or len(fields) != 1:
        raise ValueError(f"sweep: no single threshold is called {name!r}")
    try:
        low, high, step = (Decimal(part) for part in bounds.split(":"))
    except ValueError, InvalidOperation:
        raise ValueError("sweep: write it as name=low:high:step") from None
    if step <= 0 or high < low:
        raise ValueError("sweep: the range must go up, by a positive step")
    count = int((high - low) / step) + 1
    return fields[0], [low + step * i for i in range(count)]


# --- The command ---


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.run")
    parser.add_argument("--mode", choices=["replay", "live"], required=True)
    parser.add_argument("--record", action="store_true", help="live only: record what's missing")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run these cases only")
    parser.add_argument("--classifier", choices=["jev", "backup"], default="jev")
    parser.add_argument("--sweep", metavar="NAME=LOW:HIGH:STEP", help="replay only")
    args = parser.parse_args(argv)
    if args.record and args.mode != "live":
        parser.error("--record works in live mode only")
    sweep = None
    if args.sweep:
        if args.mode != "replay" or args.classifier != "jev":
            parser.error("--sweep replays Jev's recorded answers: use it with --mode replay")
        try:
            sweep = parse_sweep(args.sweep)
        except ValueError as error:
            parser.error(str(error))

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
    if sweep is not None:
        name, values = sweep
        rows = asyncio.run(
            _sweep(args, settings, database, cases, name, values), loop_factory=factory
        )
        current = Decimal(str(getattr(THRESHOLDS, name)))
        sweep_report = SweepReport(date=dt.date.today(), field=name, current=current, rows=rows)
        print("\n".join(sweep_report.lines()))
        if not args.only:
            for path in sweep_report.write():
                print(f"Wrote {path.name}")
        sys.exit(0)

    outcomes, comparison = asyncio.run(
        _report_run(args, settings, database, cases), loop_factory=factory
    )
    report = Report(
        mode=args.mode,
        date=dt.date.today(),
        policy_version=current_policy().version,
        models=_models(),
        outcomes=outcomes,
        classifier=args.classifier,
        recording=args.record,
        comparison=comparison,
    )
    print("\n".join([*report.case_lines(), "", *report.summary_lines()]))
    if not args.only and not args.record:  # a partial or filling run is not a report
        for path in report.write():
            print(f"Wrote {path.name}")
    sys.exit(exit_code(args.mode, outcomes))


async def _report_run(
    args: argparse.Namespace,
    settings: Settings,
    database: EvalDatabase,
    cases: Sequence[EvalCase],
) -> tuple[list[Outcome], Comparison | None]:
    async with _suite(args, settings, database) as suite:
        outcomes = await run_suite(suite, cases)
        if args.classifier != "jev" or args.record or suite.meter is None:
            return outcomes, None
        counted = {outcome.case_id for outcome in outcomes if outcome.skipped is None}
        comparison = await compare(
            [case for case in cases if case.id in counted],
            suite.meter.calls,
            lambda case: eval_providers.chain_of(suite.providers(case)).backup,
            suite.thresholds,
        )
        return outcomes, comparison


async def _sweep(
    args: argparse.Namespace,
    settings: Settings,
    database: EvalDatabase,
    cases: Sequence[EvalCase],
    name: str,
    values: Sequence[Decimal],
) -> list[SweepRow]:
    rows = []
    for value in values:
        thresholds = Thresholds.model_validate(THRESHOLDS.model_dump() | {name: value})
        async with _suite(args, settings, database, thresholds=thresholds) as suite:
            outcomes = await run_suite(suite, cases)
        report = Report(
            mode="replay",
            date=dt.date.today(),
            policy_version="",
            models={},
            outcomes=outcomes,
        )
        rows.append(SweepRow(value, len(report.counted), report.passed, report.manual_review_rate))
    return rows


@asynccontextmanager
async def _suite(
    args: argparse.Namespace,
    settings: Settings,
    database: EvalDatabase,
    *,
    thresholds: Thresholds = THRESHOLDS,
) -> AsyncIterator[Suite]:
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

        try:
            yield Suite(
                mode=args.mode,
                reader=async_sessionmaker(reader_engine, expire_on_commit=False),
                writer=async_sessionmaker(writer_engine, expire_on_commit=False),
                owner=owner,
                providers=providers_for,
                thresholds=thresholds,
                meter=Meter(),
            )
        finally:
            for providers in built.values():
                await providers.close()
            await reader_engine.dispose()
            await writer_engine.dispose()
            owner.dispose()


def _models() -> dict[str, str]:
    config = providers_config()
    return {"jev": config.jev.model, "luna": config.luna.model, "sol": config.sol.model}


if __name__ == "__main__":
    main()
