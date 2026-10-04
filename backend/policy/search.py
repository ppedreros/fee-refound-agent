"""Reading policy clauses over an `agent_reader` session (SPEC-policy, "Clause store and search").

D7b: `find_policy` builds a query from the case's facts (never the member's text), takes the top
clauses from Postgres full-text search, and lets Jev pick one; `get_clause` is the fallback, the
clause the deciding rule declares.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import models as db
from backend.tools.errors import ToolError
from backend.tools.queries import read_tool


class ClauseText(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    doc_title: str
    section: str
    text: str


@read_tool
async def get_clause(session: AsyncSession, clause_id: str) -> ClauseText:
    row = (
        await session.execute(
            select(
                db.PolicyClause.id,
                db.PolicyClause.doc_title,
                db.PolicyClause.section,
                db.PolicyClause.text,
            ).where(db.PolicyClause.id == clause_id)
        )
    ).one_or_none()
    if row is None:
        raise ToolError("not_found")
    return ClauseText.model_validate(row._asdict())


SEARCH_LIMIT = 5

# The topic of each rule, in the words its clauses use.
RULE_TERMS: dict[str, str] = {
    "verify_posting_order": "same day deposit posted covered",
    "check_not_already_refunded": "refunded once",
    "check_yearly_limit": "refunds 12 month period",
    "check_good_standing": "good standing unpaid balance",
    "check_approval_limit": "staff approve",
}


def build_policy_query(*, fee_type: str | None, rules: Sequence[str]) -> str:
    """The fee type, then the topic of each rule that ran, the deciding rule first. Joined with
    OR: `websearch_to_tsquery` would otherwise ask for every word in one clause."""
    words = [*(fee_type or "").lower().split(), "fee", "refund"]
    for rule in rules:
        words += RULE_TERMS.get(rule, "").split()
    return " OR ".join(dict.fromkeys(words))


@read_tool
async def search_clauses(
    session: AsyncSession, query: str, limit: int = SEARCH_LIMIT
) -> list[ClauseText]:
    """The best-matching clauses, ranked by `ts_rank_cd` (ties by id, so the order is stable)."""
    tsquery = func.websearch_to_tsquery("english", query)
    rows = await session.execute(
        select(
            db.PolicyClause.id,
            db.PolicyClause.doc_title,
            db.PolicyClause.section,
            db.PolicyClause.text,
        )
        .where(db.PolicyClause.search.op("@@")(tsquery))
        .order_by(func.ts_rank_cd(db.PolicyClause.search, tsquery).desc(), db.PolicyClause.id)
        .limit(limit)
    )
    return [ClauseText.model_validate(row._asdict()) for row in rows]
