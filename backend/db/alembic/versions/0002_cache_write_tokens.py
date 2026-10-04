"""Prompt-cache writes per step and per run.

OpenAI prices the tokens a call writes to the prompt cache above plain input (SPEC-providers,
"Cost"), so the trace keeps them next to the cached (read) tokens.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("agent_steps", "agent_runs")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("tokens_cache_write", sa.Integer(), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "tokens_cache_write")
