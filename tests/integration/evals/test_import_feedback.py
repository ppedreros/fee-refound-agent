"""The feedback loop (SPEC-evals, "Feedback loop"; AC6) and the shadow-mode agreement (D5): Luis's
decisions, made through the API, become pending eval cases and an agreement rate."""

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.main import create_app
from evals.case import ExpectedRecommendation, load_case
from evals.import_feedback import import_feedback
from evals.shadow_report import shadow
from tests.api.conftest import SETTINGS, resources_for, wait_for_runs
from tests.integration.agents.fakes import FakeClassifier, jev_answers

EDITED = (
    "Hi Ana,\n\nYour paycheck and the $35 Courtesy Pay fee landed on the same day, so we "
    "refunded the fee to your Everyday Checking account. Sorry for the trouble.\n"
)


@pytest.fixture
async def app(with_clauses: Engine, test_database_url: URL) -> AsyncIterator[FastAPI]:
    application = create_app(
        SETTINGS, resources=resources_for(test_database_url, FakeClassifier(jev_answers()))
    )
    async with application.router.lifespan_context(application):
        yield application


async def decide(app: FastAPI, case_id: int, action: str, **body: Any) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        await http.post(f"/cases/{case_id}/run")
        await wait_for_runs(app)
        case = (await http.get(f"/cases/{case_id}")).json()
        draft = (case["draft"] or {}).get("text", "Hi Ana,\n\nThanks for writing.\n")
        response = await http.post(
            f"/cases/{case_id}/decision",
            json={"run_id": case["run"]["run_id"], "action": action, "reply_text": draft} | body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, response.text


async def test_an_edit_becomes_a_pending_case_and_is_exported_once(
    app: FastAPI,
    writer: async_sessionmaker[AsyncSession],
    with_clauses: Engine,
    tmp_path: Path,
) -> None:
    await decide(app, 5012, "edit", reply_text=EDITED)

    (path,) = await import_feedback(writer, tmp_path)

    case = load_case(path)
    assert (case.source, case.pending_review, case.conversation_id, case.kind) == (
        "feedback",
        True,
        5012,
        "refund",
    )
    expected = case.expected
    assert expected.status == "ready_to_refund"
    assert expected.recommendation == ExpectedRecommendation(
        action="refund", amount=Decimal("35.00")
    )
    assert expected.draft is not None
    assert (expected.draft.required, expected.draft.contains_amount, expected.draft.language) == (
        True,
        Decimal("35.00"),
        "en",
    )
    assert expected.draft.reference_text is not None
    assert expected.draft.reference_text.startswith("Hi [FIRST_NAME],")
    assert "Ana" not in path.read_text(encoding="utf-8")

    assert await import_feedback(writer, tmp_path) == []  # nothing new the second time
    with with_clauses.connect() as connection:
        exported = connection.execute(
            text("SELECT exported_at IS NOT NULL FROM eval_candidates")
        ).scalar_one()
    assert exported


async def test_a_rejected_refund_expects_luiss_outcome(
    app: FastAPI, writer: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await decide(
        app,
        5012,
        "reject",
        reply_text="Hi Ana,\n\nWe looked into this and can't refund the fee this time.\n",
        reason="Ana asked us to wait for the statement.",
    )

    (path,) = await import_feedback(writer, tmp_path)

    case = load_case(path)
    assert case.kind == "no_refund"
    assert case.expected.recommendation == ExpectedRecommendation(action="no_refund")
    assert "status" not in case.expected.model_fields_set  # what status was right is a review call
    assert case.description is not None
    assert "[FIRST_NAME] asked us to wait" in case.description


async def test_an_approval_as_drafted_is_not_feedback(
    app: FastAPI, writer: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await decide(app, 5012, "approve")

    assert await import_feedback(writer, tmp_path) == []


# --- Shadow mode (D5) ---


async def test_the_shadow_report_compares_would_auto_approve_with_luis(
    app: FastAPI, writer: async_sessionmaker[AsyncSession]
) -> None:
    await decide(app, 5012, "approve")  # clear: auto-approve would have done the same
    await decide(app, 5106, "approve")  # a decline Luis sent as drafted: not a clear case

    report = await shadow(writer)

    assert (report.clear_decided, report.clear_approved_as_drafted) == (1, 1)
    assert (report.other_decided, report.other_approved_as_drafted) == (1, 1)
    assert report.agreement == 1.0


async def test_an_edit_of_a_clear_case_is_the_same_refund_but_not_agreement(
    app: FastAPI, writer: async_sessionmaker[AsyncSession]
) -> None:
    await decide(app, 5012, "edit", reply_text=EDITED)

    report = await shadow(writer)

    assert (report.clear_decided, report.clear_with_edits, report.agreement) == (1, 1, 0.0)
    assert report.same_refund == 1.0
    assert report.lines()[1] == (
        "Decided clear cases: 1   Luis approved as drafted: 0   with edits: 1   declined: 0"
    )


async def test_with_no_decisions_there_is_no_rate_yet(
    with_clauses: Engine, writer: async_sessionmaker[AsyncSession]
) -> None:
    report = await shadow(writer)

    assert report.agreement is None
    assert report.lines()[2] == "Agreement: no decided clear cases yet"
