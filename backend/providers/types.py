"""Provider-neutral types (SPEC-providers, "Types"). Agents depend on these, never on an SDK."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

MAX_CHOICE_OPTIONS = 255


class Option(BaseModel, frozen=True):
    key: str
    description: str | None = None


class ChoiceQuestion(BaseModel, frozen=True):
    key: str
    prompt: str
    options: list[Option] = Field(min_length=2, max_length=MAX_CHOICE_OPTIONS)


class NoulCriteria(BaseModel, frozen=True):
    """What a "yes" and a "no" mean. Jev reads instructions literally, so stating both helps."""

    yes: str
    no: str


class NoulQuestion(BaseModel, frozen=True):
    key: str
    statement: str
    criteria: NoulCriteria | None = None


type Question = ChoiceQuestion | NoulQuestion


class ChoiceAnswer(BaseModel, frozen=True):
    choice: str
    # None when the classifier has no calibrated distribution (the Luna fallback, D3).
    probabilities: dict[str, float] | None = None
    confidence: float | None = None


class NoulAnswer(BaseModel, frozen=True):
    p_yes: float | None
    label: bool  # for display only; the agent applies the D3 bands to p_yes


class CallMeta(BaseModel, frozen=True):
    provider: Literal["jev", "openai"]
    model: str
    mode: Literal["live", "replay"]
    latency_ms: int
    tokens_in: int
    tokens_out: int
    tokens_cached: int = 0  # read from the prompt cache
    tokens_cache_write: int = 0  # written to the prompt cache (priced higher than plain input)
    cost_usd: Decimal | None = None  # filled from the price table (T15)
    attempts: int


type UnavailableReason = Literal[
    "auth",
    "invalid_request",
    "rate_limited",
    "server_error",
    "timeout",
    "connection",
    "bad_response",
    "replay_miss",
]


class Classification(BaseModel, frozen=True):
    answers: dict[str, ChoiceAnswer | NoulAnswer]
    meta: CallMeta
    fallback_reason: UnavailableReason | None = None  # why the primary classifier did not answer


class ProviderUnavailable(Exception):
    """A provider call failed. `reason` is a code for logs and fallbacks, never shown to Luis.
    `attempts` counts every attempt the call policy made (it is set when the policy gives up)."""

    def __init__(self, reason: UnavailableReason, *, retry_after_s: float | None = None) -> None:
        super().__init__(reason)
        self.reason: UnavailableReason = reason
        self.retry_after_s = retry_after_s
        self.attempts = 1


class Classifier(Protocol):
    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        deadline: float | None = None,  # monotonic seconds: the run's remaining time
    ) -> Classification: ...


class DrafterUnavailable(ProviderUnavailable):
    """Sol couldn't write the reply. The node uses the template and adds `drafter_down`."""


class DraftInput(BaseModel):
    """Everything Sol may know about a case (D2: facts only). There is no field that could hold
    the member's message, and the name is always the placeholder, filled in for Luis later."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    language: Literal["en", "es"]
    tone: Literal["formal", "casual", "upset", "neutral"]
    outcome: Literal["refund", "no_refund"]
    amount: str  # "35.00"
    fee_date: str  # ISO date
    fee_type: str | None
    sub_account_name: str
    facts: list[str]  # verified facts, in plain English, with no other amounts
    policy_clause: str | None  # the clause text, for declines only
    first_name: Literal["{{first_name}}"] = "{{first_name}}"


class Draft(BaseModel, frozen=True):
    reply: str
    meta: CallMeta


class Drafter(Protocol):
    async def draft(
        self,
        payload: DraftInput,
        *,
        instructions: str,  # the static system prompt, sent first so it can be cached
        deadline: float | None = None,
    ) -> Draft: ...
