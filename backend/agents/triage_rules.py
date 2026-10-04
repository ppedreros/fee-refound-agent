"""D3: what a classifier's answers mean for the case (SPEC-agent, "Triage rules").

Jev answers carry calibrated numbers, so thresholds apply. Luna (the backup) gives labels only:
its `None` confidence is never treated as a number, its labels route the case, and its cases carry
the `classified_with_backup` note.
"""

from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from backend.policy.reasons import ReasonCode
from backend.providers.types import ChoiceAnswer, Classification, NoulAnswer

CONFIG_FILE = Path(__file__).resolve().parents[1] / "core" / "config" / "thresholds.yaml"
FEE_INTENTS = frozenset({"fee_refund_request", "fee_question"})

type Language = Literal["en", "es", "other"]
type Tone = Literal["formal", "casual", "upset", "neutral"]


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_min_confidence: float
    language_min_confidence: float
    tone_min_confidence: float
    fee_choice_min_confidence: float
    clause_choice_min_confidence: float
    manipulation_clear_max_p_yes: float
    multiple_requests_min_p_yes: float
    clear_max_amount_usd: Decimal


@cache
def load_thresholds() -> Thresholds:
    return Thresholds.model_validate(yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")))


THRESHOLDS = load_thresholds()


class Triage(BaseModel):
    model_config = ConfigDict(frozen=True)

    about_fee: bool  # False is the early exit to `not_about_fee`
    topic: str | None  # the intent label, also the inbox topic; None when no classifier answered
    classifier_used: Literal["jev", "backup"] | None
    intent_confidence: float | None  # None for Luna or when no classifier answered
    language: Language
    tone: Tone
    manipulation_p_yes: float | None
    reasons: tuple[ReasonCode, ...]


def apply_triage_rules(
    classification: Classification,
    *,
    last_known_language: str | None,
    thresholds: Thresholds = THRESHOLDS,
) -> Triage:
    backup = classification.meta.provider != "jev"
    answers = classification.answers
    intent = _choice(answers["intent"])
    language = _choice(answers["language"])
    tone = _choice(answers["tone"])
    manipulation = _noul(answers["manipulation"])
    multiple = _noul(answers["multiple_requests"])
    reasons: list[ReasonCode] = []

    if backup:
        confident_intent = True  # Luna is the trusted backup (D-agent-5)
    else:
        confident_intent = _at_least(intent.confidence, thresholds.intent_min_confidence)
        if not confident_intent:
            reasons.append(ReasonCode.INTENT_UNCLEAR)

    about_fee = intent.choice in FEE_INTENTS or not confident_intent
    if not about_fee:
        reasons.append(ReasonCode.NOT_FEE_REQUEST)
    if intent.choice == "fee_question" and confident_intent:
        reasons.append(ReasonCode.FEE_QUESTION)

    if backup or _at_least(language.confidence, thresholds.language_min_confidence):
        chosen_language: Language = _language(language.choice)
        if chosen_language == "other":
            reasons.append(ReasonCode.LANGUAGE_UNSUPPORTED)
    else:
        chosen_language = _fallback_language(last_known_language)

    if backup or _at_least(tone.confidence, thresholds.tone_min_confidence):
        chosen_tone: Tone = _tone(tone.choice)
    else:
        chosen_tone = "neutral"

    if backup:
        flagged = manipulation.label
    else:  # two-sided band: only a low P(yes) is a clear "no"; a missing one counts as yes
        flagged = not _at_most(manipulation.p_yes, thresholds.manipulation_clear_max_p_yes)
    if flagged:
        reasons.append(ReasonCode.MANIPULATION)

    if backup:
        several = multiple.label
    else:
        several = _at_least(multiple.p_yes, thresholds.multiple_requests_min_p_yes)
    if several:
        reasons.append(ReasonCode.MULTIPLE_REQUESTS)

    if backup:
        reasons.append(ReasonCode.CLASSIFIED_WITH_BACKUP)

    return Triage(
        about_fee=about_fee,
        topic=intent.choice,
        classifier_used="backup" if backup else "jev",
        intent_confidence=None if backup else intent.confidence,
        language=chosen_language,
        tone=chosen_tone,
        manipulation_p_yes=None if backup else manipulation.p_yes,
        reasons=tuple(reasons),
    )


def triage_unavailable(*, last_known_language: str | None) -> Triage:
    """Every classifier failed: treat the message as a possible fee request and keep going."""
    return Triage(
        about_fee=True,
        topic=None,
        classifier_used=None,
        intent_confidence=None,
        language=_fallback_language(last_known_language),
        tone="neutral",
        manipulation_p_yes=None,
        reasons=(ReasonCode.CLASSIFIER_DOWN,),
    )


def _choice(answer: ChoiceAnswer | NoulAnswer) -> ChoiceAnswer:
    if not isinstance(answer, ChoiceAnswer):
        raise TypeError("expected a Choice answer")
    return answer


def _noul(answer: ChoiceAnswer | NoulAnswer) -> NoulAnswer:
    if not isinstance(answer, NoulAnswer):
        raise TypeError("expected a Noul answer")
    return answer


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _at_most(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


_LANGUAGES: dict[str, Language] = {"en": "en", "es": "es"}
_TONES: dict[str, Tone] = {"formal": "formal", "casual": "casual", "upset": "upset"}


def _language(label: str) -> Language:
    return _LANGUAGES.get(label, "other")


def _tone(label: str) -> Tone:
    return _TONES.get(label, "neutral")


def _fallback_language(last_known: str | None) -> Language:
    return _LANGUAGES.get(last_known or "", "en")
