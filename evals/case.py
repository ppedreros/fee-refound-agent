"""The eval case format (SPEC-evals, "Case format"): one YAML file per case in `evals/cases/`.

Every field a case writes under `expected` is an assertion, and a field left out is not checked.
An explicit `null` is an assertion too: `amount: null` means "no amount".
"""

from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.policy.reasons import ReasonCode

CASES_DIR = Path(__file__).resolve().parent / "cases"

type Mode = Literal["replay", "live"]
type Kind = Literal["refund", "no_refund", "edge"]
type Source = Literal["seed", "synthetic", "feedback"]
# The recordings a fallback case removes from its temp copy: Jev's, or Luna's or Sol's (openai).
type Recording = Literal["jev", "luna", "sol"]
type RunStatus = Literal[
    "ready_to_refund", "recommend_no_refund", "needs_your_call", "needs_supervisor", "not_about_fee"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedRecommendation(_Strict):
    action: Literal["refund", "no_refund", "none"] | None = None
    amount: Decimal | None = None
    fee_txn_id: int | None = None


class ExpectedDraft(_Strict):
    required: bool | None = None  # true: there is a draft; false: there is none
    contains_amount: Decimal | None = None
    language: Literal["en", "es"] | None = None
    source: Literal["model", "template"] | None = None
    reference_text: str | None = None  # feedback cases: Luis's own reply, for reading only


class Expected(_Strict):
    status: RunStatus | None = None
    reasons_include: tuple[ReasonCode, ...] = ()
    notes_include: tuple[ReasonCode, ...] = ()
    topic: str | None = None
    language: str | None = None
    recommendation: ExpectedRecommendation | None = None
    clause_id: str | None = None
    clear: bool | None = None  # would the case be approved automatically (shadow mode, D5)
    draft: ExpectedDraft | None = None
    must_not_appear: tuple[str, ...] = ()  # anywhere in the result or the draft


class EvalCase(_Strict):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    kind: Kind
    source: Source
    description: str | None = None
    conversation_id: int
    message_override: str | None = None  # replaces the member's latest message, same data
    pinned_fee_txn_id: int | None = None  # "Pick the fee": the run Luis starts after picking
    modes: tuple[Mode, ...] = ("replay", "live")
    record: bool = True  # false: --record never writes recordings for this case
    replay_without: tuple[Recording, ...] = ()  # fallback cases: recordings removed on purpose
    pending_review: bool = False  # feedback cases wait for a person before they count
    expected: Expected

    @model_validator(mode="after")
    def _fallbacks_are_replay_only(self) -> Self:
        if self.replay_without and (self.modes != ("replay",) or self.record):
            raise ValueError("a case with replay_without needs modes: [replay] and record: false")
        return self


def load_case(path: Path) -> EvalCase:
    return EvalCase.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_cases(cases_dir: Path = CASES_DIR) -> list[EvalCase]:
    """Every case, in path order."""
    return [load_case(path) for path in sorted(cases_dir.rglob("*.yaml"))]
