"""Reading policy clauses over an `agent_reader` session (SPEC-policy, "Clause store and search").

`get_clause` is the fallback of D7b: the clause the deciding rule declares. Full-text search and
the Jev rerank come in T30.
"""

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
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
