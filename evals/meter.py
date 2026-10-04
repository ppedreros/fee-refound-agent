"""Every model call of an eval run, with its role and the call's own metadata (SPEC-evals,
"Output"). In replay mode a call's latency and cost are the recorded live call's, so the report
can price and time a run that made no calls.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from backend.providers.types import (
    CallMeta,
    Classification,
    Classifier,
    Draft,
    Drafter,
    DraftInput,
    Question,
)

# The role of a call, from its prompt version: "triage-v2" is triage.
ROLES = {
    "triage": "triage",
    "fee-choice": "fee_choice",
    "clause-choice": "clause_choice",
    "draft": "draft",
}


@dataclass(frozen=True)
class Asked:
    """What triage was asked, kept so the classifier comparison can ask the backup the same."""

    state: Mapping[str, str]
    questions: Sequence[Question]
    prompt_version: str | None


@dataclass(frozen=True)
class Call:
    case_id: str
    role: str
    meta: CallMeta
    asked: Asked | None = None  # triage only
    answer: Classification | None = None  # triage only


def role_of(prompt_version: str | None) -> str:
    for prefix, role in ROLES.items():
        if prompt_version and prompt_version.startswith(prefix):
            return role
    return "other"


@dataclass
class Meter:
    case_id: str = ""  # the case running now; the suite sets it before each run
    calls: list[Call] = field(default_factory=list)

    def classifier(self, inner: Classifier) -> Classifier:
        return _MeteredClassifier(inner, self)

    def drafter(self, inner: Drafter) -> Drafter:
        return _MeteredDrafter(inner, self)

    def of(self, case_id: str) -> tuple[Call, ...]:
        return tuple(call for call in self.calls if call.case_id == case_id)


class _MeteredClassifier:
    def __init__(self, inner: Classifier, meter: Meter) -> None:
        self._inner = inner
        self._meter = meter

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Classification:
        answer = await self._inner.classify(
            state, questions, prompt_version=prompt_version, deadline=deadline
        )
        role = role_of(prompt_version)
        triage = role == "triage"
        self._meter.calls.append(
            Call(
                case_id=self._meter.case_id,
                role=role,
                meta=answer.meta,
                asked=Asked(dict(state), list(questions), prompt_version) if triage else None,
                answer=answer if triage else None,
            )
        )
        return answer


class _MeteredDrafter:
    def __init__(self, inner: Drafter, meter: Meter) -> None:
        self._inner = inner
        self._meter = meter

    async def draft(
        self,
        payload: DraftInput,
        *,
        instructions: str,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Draft:
        drafted = await self._inner.draft(
            payload, instructions=instructions, prompt_version=prompt_version, deadline=deadline
        )
        self._meter.calls.append(
            Call(case_id=self._meter.case_id, role=role_of(prompt_version), meta=drafted.meta)
        )
        return drafted
