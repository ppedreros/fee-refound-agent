"""The feedback loop (SPEC-evals, "Feedback loop"):

    uv run python -m evals.import_feedback [--out evals/cases/feedback]

Every decision where Luis changed what the flow prepared (`edit`, `reject`, `reply_only`) left an
`eval_candidates` row. This writes each new one as a YAML case marked `pending_review: true` and
sets its `exported_at`, so a second run exports nothing new. The runner skips pending cases until
a person reviews one, sets the flag to false and commits it.

What the case expects is what Luis did. For an edit, the status and recommendation the flow gave
(he kept the outcome and rewrote the reply), plus what can be checked in a reply: required, its
amount and its language; his text is kept as `reference_text`, masked. For a reject or a reply
only, his outcome is the expected recommendation; which status was right is left to the review.
The case data stays by reference: the conversation, and the fee when Luis picked it.
"""

import argparse
import asyncio
import datetime as dt
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.settings import ConfigError, load_settings
from backend.db.models import AgentRun, Decision, EvalCandidate, Refund
from evals.case import CASES_DIR, EvalCase
from evals.database import EvalSettings, app_database

FEEDBACK_DIR = CASES_DIR / "feedback"
KIND = {"refund": "refund", "no_refund": "no_refund", "none": "edge"}


async def import_feedback(
    writer: async_sessionmaker[AsyncSession], out_dir: Path = FEEDBACK_DIR
) -> list[Path]:
    written: list[Path] = []
    async with writer() as session, session.begin():
        rows = (
            await session.execute(
                select(EvalCandidate, AgentRun.result, Decision.created_at)
                .join(AgentRun, AgentRun.id == EvalCandidate.run_id)
                .join(Decision, Decision.id == EvalCandidate.decision_id)
                .where(EvalCandidate.exported_at.is_(None))
                .order_by(EvalCandidate.id)
            )
        ).all()
        for candidate, result, decided_at in rows:
            refunded = await session.scalar(
                select(Refund.amount).where(Refund.decision_id == candidate.decision_id)
            )
            case = feedback_case(candidate, result or {}, decided_at, refunded)
            written.append(_write(case, out_dir))
        if rows:
            ids = [candidate.id for candidate, _, _ in rows]
            await session.execute(
                update(EvalCandidate)
                .where(EvalCandidate.id.in_(ids))
                .values(exported_at=dt.datetime.now(dt.UTC))
            )
    return written


def feedback_case(
    candidate: EvalCandidate,
    result: dict[str, Any],
    decided_at: dt.datetime,
    refunded: Decimal | None,
) -> dict[str, Any]:
    wanted = candidate.expected
    outcome = wanted["recommendation"]
    recommendation: dict[str, Any] = {"action": outcome}
    if refunded is not None:
        recommendation["amount"] = str(refunded)
    expected: dict[str, Any] = {}
    if candidate.kind == "edit":
        expected["status"] = wanted["status"]
    expected["recommendation"] = recommendation
    if candidate.kind == "edit":
        draft: dict[str, Any] = {"required": True}
        if refunded is not None:
            draft["contains_amount"] = str(refunded)
        if result.get("language") in ("en", "es"):
            draft["language"] = result["language"]
        draft["reference_text"] = wanted["reference_text"]
        expected["draft"] = draft

    description = f"Luis chose {candidate.kind} on {decided_at:%Y-%m-%d}."
    if wanted.get("reason"):
        description += f" Reason given: {wanted['reason']}"
    case: dict[str, Any] = {
        "id": f"feedback-{candidate.case_id}-{candidate.id}",
        "kind": KIND[outcome],
        "source": "feedback",
        "description": description,
        "conversation_id": candidate.case_id,
    }
    fee = result.get("fee") or {}
    if fee.get("source") == "staff":  # Luis picked the fee: the case runs with it pinned
        case["pinned_fee_txn_id"] = fee["id"]
    case["pending_review"] = True
    case["expected"] = expected
    EvalCase.model_validate(case)  # what is written always loads
    return case


class _Dumper(yaml.SafeDumper):
    """Writes a reply with line breaks as a `|` block, so a reviewer reads it as Luis wrote it."""


def _text(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _text)


def _write(case: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{case['id']}.yaml"
    text = yaml.dump(case, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.import_feedback")
    parser.add_argument("--out", type=Path, default=FEEDBACK_DIR, help="where the YAML goes")
    args = parser.parse_args(argv)
    try:
        url = app_database(load_settings(), EvalSettings())
    except ConfigError as error:
        sys.exit(f"Invalid configuration: {error}")

    async def run() -> list[Path]:
        engine = create_async_engine(url)
        try:
            return await import_feedback(async_sessionmaker(engine), args.out)
        finally:
            await engine.dispose()

    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    written = asyncio.run(run(), loop_factory=factory)
    for path in written:
        print(f"Wrote {path.name} (pending review)")
    print(f"{len(written)} new feedback case(s).")


if __name__ == "__main__":
    main()
