"""The eval runner on fees_test, with in-process fake providers (D10: tests never use replay files
or live models). The real suite runs on the recordings in the CI `evals` job."""

import shutil
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.policy.loader import DOCS_DIR, load_policy
from backend.providers.factory import Providers
from evals.case import EvalCase, Expected
from evals.run import Suite, exit_code, run_suite
from tests.integration.agents.fakes import FakeChooser, FakeClassifier, FakeDrafter, jev_answers

ANA = EvalCase.model_validate(
    {
        "id": "scenario-01",
        "kind": "refund",
        "source": "seed",
        "conversation_id": 5012,
        "expected": {
            "status": "ready_to_refund",
            "recommendation": {"action": "refund", "amount": "35.00"},
            "draft": {"required": True, "contains_amount": "35.00"},
        },
    }
)


def fakes(case: EvalCase) -> Providers:
    return Providers(
        classifier=FakeClassifier(jev_answers()),
        drafter=FakeDrafter(),
        chooser=FakeChooser(),
        modes={"jev": "replay", "openai": "replay"},
    )


def suite(
    with_clauses: Engine,
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    **changes: object,
) -> Suite:
    fields: dict[str, object] = {
        "mode": "replay",
        "reader": reader,
        "writer": writer,
        "owner": with_clauses,
        "providers": fakes,
    }
    return Suite(**(fields | changes))  # type: ignore[arg-type]


async def test_a_case_that_meets_its_expectations_passes_and_exits_0(
    with_clauses: Engine,
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
) -> None:
    outcomes = await run_suite(suite(with_clauses, reader, writer), [ANA])

    (outcome,) = outcomes
    assert outcome.passed, [check for check in outcome.checks if not check.passed]
    assert exit_code("replay", outcomes) == 0


async def test_a_limit_of_2_in_a_test_copy_of_the_policy_fails_the_case_and_exits_1(
    with_clauses: Engine,
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """SPEC-evals AC3. Ana has two fee refunds in the 12 months before her fee."""
    docs = tmp_path / "docs"
    shutil.copytree(DOCS_DIR, docs)
    refund_policy = docs / "fee-refund-policy.md"
    text_before = refund_policy.read_text(encoding="utf-8")
    # The params and the clause's words change together: the loader checks they agree.
    refund_policy.write_text(
        text_before.replace("max_refunds_in_window: 3", "max_refunds_in_window: 2").replace(
            "up to 3 fee refunds", "up to 2 fee refunds"
        ),
        encoding="utf-8",
    )
    policy = load_policy(docs)
    assert policy.params.max_refunds_in_window == 2

    outcomes = await run_suite(suite(with_clauses, reader, writer, policy=policy), [ANA])

    (outcome,) = outcomes
    assert not outcome.passed
    assert outcome.result is not None
    assert (outcome.result["status"], outcome.result["reasons"]) == (
        "recommend_no_refund",
        ["yearly_limit"],
    )
    assert exit_code("replay", outcomes) == 1


async def test_live_mode_only_reports(
    with_clauses: Engine,
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
) -> None:
    wrong = ANA.model_copy(update={"expected": Expected(clear=False)})  # Ana is clear

    outcomes = await run_suite(suite(with_clauses, reader, writer, mode="live"), [wrong])

    assert not outcomes[0].passed
    assert exit_code("live", outcomes) == 0


async def test_a_message_override_is_what_triage_reads_and_the_seed_text_comes_back(
    with_clauses: Engine,
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
) -> None:
    classifier = FakeClassifier(jev_answers())
    override = ANA.model_copy(update={"message_override": "Same-day paycheck. Refund it please."})

    await run_suite(
        suite(with_clauses, reader, writer, providers=lambda case: _with(classifier)), [override]
    )

    assert classifier.states[0]["message"] == "Same-day paycheck. Refund it please."
    with with_clauses.connect() as connection:
        body = connection.execute(text("SELECT body FROM messages WHERE id = 9120")).scalar_one()
    assert body == "My paycheck came the same day. Can you refund this?"


async def test_cases_for_another_mode_or_waiting_for_review_are_skipped(
    with_clauses: Engine,
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
) -> None:
    live_only = ANA.model_copy(update={"id": "live-only", "modes": ("live",)})
    pending = ANA.model_copy(update={"id": "pending", "pending_review": True})

    outcomes = await run_suite(suite(with_clauses, reader, writer), [live_only, pending, ANA])

    assert [(o.case_id, o.skipped) for o in outcomes] == [
        ("live-only", "not applicable"),
        ("pending", "pending review"),
        ("scenario-01", None),
    ]
    assert exit_code("replay", outcomes) == 0  # skipped cases don't count


async def test_no_counted_case_is_a_failure(
    with_clauses: Engine,
    reader: async_sessionmaker[AsyncSession],
    writer: async_sessionmaker[AsyncSession],
) -> None:
    live_only = ANA.model_copy(update={"modes": ("live",)})

    outcomes = await run_suite(suite(with_clauses, reader, writer), [live_only])

    assert exit_code("replay", outcomes) == 1


def _with(classifier: FakeClassifier) -> Providers:
    return Providers(
        classifier=classifier,
        drafter=FakeDrafter(),
        chooser=FakeChooser(),
        modes={"jev": "replay", "openai": "replay"},
    )
