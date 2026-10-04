"""The policy documents (SPEC-policy): the single source of every number the rules use.

Each document is markdown with a YAML front-matter, and each `## N. Title` section is one clause,
`<slug>#<N>`. Loading fails, naming the file and field, when a document is malformed or when its
text and its params disagree.
"""

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Annotated, Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError
from sqlalchemy import Connection, delete
from sqlalchemy.dialects.postgresql import insert

from backend.db.models import Base

DOCS_DIR = Path(__file__).resolve().parent / "docs"
CLAUSE_HEADING = re.compile(r"^## (\d+)\. (.+?)\s*$", re.MULTILINE)


class PolicyError(Exception):
    """A policy document is malformed or contradicts itself. Stops the bootstrap."""


class FeeEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Annotated[Decimal, Field(gt=0)]
    clause: PositiveInt  # the fee-schedule clause that states it


class _Params(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _FeeRefundParams(_Params):
    max_refunds_in_window: PositiveInt
    window_days: PositiveInt


class _FeeScheduleParams(_Params):
    fees: dict[str, FeeEntry]


class _StaffLimitParams(_Params):
    staff_limit_usd: Annotated[Decimal, Field(gt=0)]


PARAMS_BY_SLUG: dict[str, type[_Params]] = {
    "fee-refund-policy": _FeeRefundParams,
    "courtesy-pay-rules": _Params,
    "fee-schedule": _FeeScheduleParams,
    "staff-approval-limits": _StaffLimitParams,
    "member-communication": _Params,
    "account-standing": _Params,
}


class _FrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    version: dt.date
    params: dict[str, Any] = {}


class PolicyParams(BaseModel):
    """Every number the rules use, read from the documents."""

    model_config = ConfigDict(frozen=True)

    max_refunds_in_window: int
    window_days: int
    staff_limit_usd: Decimal
    fees: dict[str, FeeEntry]


@dataclass(frozen=True)
class Clause:
    id: str
    doc_slug: str
    doc_title: str
    number: int
    section: str  # "4. Same-day deposits"
    text: str
    params: dict[str, Any]


@dataclass(frozen=True)
class Document:
    slug: str
    title: str
    params: _Params
    clauses: tuple[Clause, ...]


@dataclass(frozen=True)
class Policy:
    documents: tuple[Document, ...]
    params: PolicyParams
    version: str  # a hash of every document; each run stores it

    @property
    def clauses(self) -> list[Clause]:
        return [clause for document in self.documents for clause in document.clauses]


def load_policy(docs_dir: Path = DOCS_DIR) -> Policy:
    files = sorted(docs_dir.glob("*.md"))
    documents = tuple(_parse(path) for path in files)
    by_slug = {document.slug: document.params for document in documents}
    missing = PARAMS_BY_SLUG.keys() - by_slug.keys()
    if missing:
        raise PolicyError(f"missing policy documents: {', '.join(sorted(missing))}")

    # PARAMS_BY_SLUG validated each document with its own model.
    refund = cast(_FeeRefundParams, by_slug["fee-refund-policy"])
    schedule = cast(_FeeScheduleParams, by_slug["fee-schedule"])
    limits = cast(_StaffLimitParams, by_slug["staff-approval-limits"])
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    policy = Policy(
        documents=documents,
        params=PolicyParams(
            max_refunds_in_window=refund.max_refunds_in_window,
            window_days=refund.window_days,
            staff_limit_usd=limits.staff_limit_usd,
            fees=schedule.fees,
        ),
        version=digest.hexdigest()[:16],
    )

    problems = consistency_problems(policy)
    if problems:
        raise PolicyError("; ".join(problems))
    return policy


@cache
def current_policy() -> Policy:
    """The policy shipped with the app, loaded once."""
    return load_policy()


def fee_schedule_clause(fee_type: str) -> str | None:
    """The fee-schedule clause for a fee type, for example `fee-schedule#4`."""
    entry = current_policy().params.fees.get(fee_type)
    return f"fee-schedule#{entry.clause}" if entry is not None else None


def consistency_problems(policy: Policy) -> list[str]:
    """Clauses whose text doesn't state the number their params hold."""
    text = {clause.id: clause.text for clause in policy.clauses}
    params = policy.params
    window = "12-month" if params.window_days == 365 else f"{params.window_days}-day"
    expected = {
        "fee-refund-policy#2": [
            f"up to {params.max_refunds_in_window} fee refunds",
            f"any {window} period",
        ],
        "staff-approval-limits#1": [f"up to {_money(params.staff_limit_usd)}"],
    }
    for entry in params.fees.values():
        expected.setdefault(f"fee-schedule#{entry.clause}", []).append(_money(entry.amount))

    problems = []
    for clause_id, phrases in expected.items():
        for phrase in phrases:
            if phrase not in text.get(clause_id, ""):
                problems.append(f"{clause_id}: the text should say {phrase!r} to match its params")
    return problems


def load_clauses(connection: Connection, policy: Policy | None = None) -> str:
    """Upsert every clause into policy_clauses and drop clauses no document has any more.
    Runs as the owner (bootstrap). Returns the policy version."""
    policy = policy or load_policy()
    table = Base.metadata.tables["policy_clauses"]
    rows = [
        {
            "id": clause.id,
            "doc_slug": clause.doc_slug,
            "doc_title": clause.doc_title,
            "section": clause.section,
            "text": clause.text,
            "params": clause.params,
            "policy_version": policy.version,
        }
        for clause in policy.clauses
    ]
    upsert = insert(table).values(rows)
    connection.execute(
        upsert.on_conflict_do_update(
            index_elements=[table.c.id],
            set_={column: upsert.excluded[column] for column in rows[0] if column != "id"},
        )
    )
    connection.execute(delete(table).where(table.c.id.not_in([row["id"] for row in rows])))
    return policy.version


def _parse(path: Path) -> Document:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n") or "\n---\n" not in content[4:]:
        raise PolicyError(f"{path.name}: no YAML front-matter between '---' lines")
    header, body = content[4:].split("\n---\n", 1)

    try:
        front = _FrontMatter.model_validate(yaml.safe_load(header))
        if front.slug != path.stem:
            raise PolicyError(f"{path.name}: slug {front.slug!r} must match the file name")
        model = PARAMS_BY_SLUG.get(front.slug)
        if model is None:
            raise PolicyError(f"{path.name}: unknown policy document {front.slug!r}")
        params = model.model_validate(front.params)
    except ValidationError as error:
        fields = ", ".join(_field(detail["loc"]) for detail in error.errors())
        raise PolicyError(f"{path.name}: invalid {fields}") from None

    clauses = _clauses(path, front.slug, front.title, body, params.model_dump(mode="json"))
    return Document(slug=front.slug, title=front.title, params=params, clauses=clauses)


def _clauses(
    path: Path, slug: str, title: str, body: str, params: dict[str, Any]
) -> tuple[Clause, ...]:
    headings = list(CLAUSE_HEADING.finditer(body))
    numbers = [int(heading.group(1)) for heading in headings]
    if numbers != list(range(1, len(headings) + 1)):
        raise PolicyError(f"{path.name}: clauses must be numbered 1, 2, 3… (found {numbers})")

    clauses = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        text = body[heading.end() : end].strip()
        if not text:
            raise PolicyError(f"{path.name}: clause {heading.group(1)} has no text")
        number = int(heading.group(1))
        clauses.append(
            Clause(
                id=f"{slug}#{number}",
                doc_slug=slug,
                doc_title=title,
                number=number,
                section=f"{number}. {heading.group(2)}",
                text=text,
                params=params,
            )
        )
    return tuple(clauses)


def _field(location: tuple[int | str, ...]) -> str:
    return ".".join(str(part) for part in location)


def _money(amount: Decimal) -> str:
    return f"${int(amount)}" if amount == amount.to_integral_value() else f"${amount:.2f}"
