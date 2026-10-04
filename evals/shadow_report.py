"""Shadow mode (D5): `uv run python -m evals.shadow_report`.

Auto-approve is off. Every run still stores `would_auto_approve`, and this compares it with what
Luis then did. Over the decided clear cases, agreement is the share he approved as drafted, which
is what auto-approve would have sent. An edit keeps the refund but changes the reply, so it
counts toward "same refund" and not toward agreement. Cases the flow didn't call clear but Luis
approved as drafted are counted too: they are what a looser rule could automate.
Decisions by SYSTEM (auto-approve itself, never on in the shipped config) are left out.
"""

import asyncio
import datetime as dt
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.auto_approve import SYSTEM
from backend.core.settings import ConfigError, load_settings
from backend.db.models import AgentRun, Decision
from evals.database import EvalSettings, app_database


@dataclass(frozen=True)
class Shadow:
    date: dt.date
    clear_decided: int = 0
    clear_approved_as_drafted: int = 0
    clear_with_edits: int = 0
    clear_declined: int = 0
    other_decided: int = 0
    other_approved_as_drafted: int = 0

    @property
    def agreement(self) -> float | None:
        if not self.clear_decided:
            return None
        return self.clear_approved_as_drafted / self.clear_decided

    @property
    def same_refund(self) -> float | None:
        if not self.clear_decided:
            return None
        return (self.clear_approved_as_drafted + self.clear_with_edits) / self.clear_decided

    def lines(self) -> list[str]:
        lines = [
            "SHADOW MODE  (auto-approve is off: what it would have done, against what Luis did)"
            f"  {self.date.isoformat()}",
            f"Decided clear cases: {self.clear_decided}"
            f"   Luis approved as drafted: {self.clear_approved_as_drafted}"
            f"   with edits: {self.clear_with_edits}   declined: {self.clear_declined}",
        ]
        if self.agreement is None or self.same_refund is None:
            lines.append("Agreement: no decided clear cases yet")
        else:
            lines.append(
                f"Agreement: {self.agreement:.0%} (approved as drafted)"
                f"   Same refund: {self.same_refund:.0%} (approved, with or without edits)"
            )
        lines.append(
            f"Other decided cases: {self.other_decided}"
            f"   approved as drafted anyway: {self.other_approved_as_drafted}"
        )
        return lines


async def shadow(reader: async_sessionmaker[AsyncSession]) -> Shadow:
    async with reader() as session:
        rows = (
            await session.execute(
                select(Decision.action, AgentRun.would_auto_approve)
                .join(AgentRun, AgentRun.id == Decision.run_id)
                .where(Decision.staff_id != SYSTEM)
            )
        ).all()
    clear = [action for action, would in rows if would]
    other = [action for action, would in rows if not would]
    return Shadow(
        date=dt.date.today(),
        clear_decided=len(clear),
        clear_approved_as_drafted=clear.count("approve"),
        clear_with_edits=clear.count("edit"),
        clear_declined=len(clear) - clear.count("approve") - clear.count("edit"),
        other_decided=len(other),
        other_approved_as_drafted=other.count("approve"),
    )


def main() -> None:
    try:
        url = app_database(load_settings(), EvalSettings())
    except ConfigError as error:
        sys.exit(f"Invalid configuration: {error}")

    async def run() -> Shadow:
        engine = create_async_engine(url)
        try:
            return await shadow(async_sessionmaker(engine))
        finally:
            await engine.dispose()

    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows consoles
    print("\n".join(asyncio.run(run(), loop_factory=factory).lines()))


if __name__ == "__main__":
    main()
