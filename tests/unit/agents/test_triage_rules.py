"""D3 thresholds applied to classifier answers (SPEC-agent, "Triage rules")."""

import pytest

from backend.agents.triage_rules import THRESHOLDS, apply_triage_rules, triage_unavailable
from backend.policy.reasons import ReasonCode
from backend.providers.types import CallMeta, ChoiceAnswer, Classification, NoulAnswer

R = ReasonCode


def jev(
    intent: str = "fee_refund_request",
    intent_conf: float = 0.95,
    language: str = "en",
    language_conf: float = 0.95,
    tone: str = "casual",
    tone_conf: float = 0.9,
    manipulation: float | None = 0.02,
    multiple: float | None = 0.05,
) -> Classification:
    return Classification(
        answers={
            "intent": ChoiceAnswer(choice=intent, probabilities={}, confidence=intent_conf),
            "language": ChoiceAnswer(choice=language, probabilities={}, confidence=language_conf),
            "tone": ChoiceAnswer(choice=tone, probabilities={}, confidence=tone_conf),
            "manipulation": NoulAnswer(
                p_yes=manipulation, label=manipulation is not None and manipulation >= 0.5
            ),
            "multiple_requests": NoulAnswer(
                p_yes=multiple, label=multiple is not None and multiple >= 0.5
            ),
        },
        meta=CallMeta(
            provider="jev",
            model="jev-1.13.0",
            mode="live",
            latency_ms=1,
            tokens_in=1,
            tokens_out=1,
            attempts=1,
        ),
    )


def luna(
    intent: str = "fee_refund_request",
    language: str = "en",
    tone: str = "casual",
    manipulation: bool = False,
    multiple: bool = False,
) -> Classification:
    """Luna gives labels only: no confidence and no p_yes (D3)."""
    return Classification(
        answers={
            "intent": ChoiceAnswer(choice=intent),
            "language": ChoiceAnswer(choice=language),
            "tone": ChoiceAnswer(choice=tone),
            "manipulation": NoulAnswer(p_yes=None, label=manipulation),
            "multiple_requests": NoulAnswer(p_yes=None, label=multiple),
        },
        meta=CallMeta(
            provider="openai",
            model="gpt-6-luna",
            mode="live",
            latency_ms=1,
            tokens_in=1,
            tokens_out=1,
            attempts=1,
        ),
    )


def test_a_confident_refund_request_flags_nothing() -> None:
    triage = apply_triage_rules(jev(), last_known_language=None)

    assert triage.about_fee is True
    assert triage.topic == "fee_refund_request"
    assert triage.reasons == ()
    assert (triage.language, triage.tone, triage.classifier_used) == ("en", "casual", "jev")


@pytest.mark.parametrize(("confidence", "unclear"), [(0.79, True), (0.80, False)])
def test_intent_below_080_is_unclear(confidence: float, unclear: bool) -> None:
    triage = apply_triage_rules(jev(intent_conf=confidence), last_known_language=None)

    assert (R.INTENT_UNCLEAR in triage.reasons) is unclear
    assert triage.about_fee is True


def test_a_confident_other_topic_exits_early() -> None:
    triage = apply_triage_rules(jev(intent="card_issue", intent_conf=0.9), last_known_language=None)

    assert triage.about_fee is False
    assert triage.topic == "card_issue"
    assert triage.reasons == (R.NOT_FEE_REQUEST,)


def test_an_unsure_other_topic_still_prepares_everything() -> None:
    triage = apply_triage_rules(jev(intent="card_issue", intent_conf=0.7), last_known_language=None)

    assert triage.about_fee is True
    assert triage.reasons == (R.INTENT_UNCLEAR,)


def test_a_confident_fee_question_is_flagged() -> None:
    triage = apply_triage_rules(jev(intent="fee_question"), last_known_language=None)

    assert triage.about_fee is True
    assert R.FEE_QUESTION in triage.reasons


@pytest.mark.parametrize(
    ("language", "confidence", "history", "expected", "unsupported"),
    [
        ("es", 0.70, None, "es", False),
        ("es", 0.69, "es", "es", False),  # unsure: the member's last known language
        ("es", 0.69, None, "en", False),  # unsure, no history: English
        ("other", 0.80, None, "other", True),
        ("other", 0.50, "es", "es", False),
    ],
)
def test_language(
    language: str, confidence: float, history: str | None, expected: str, unsupported: bool
) -> None:
    triage = apply_triage_rules(
        jev(language=language, language_conf=confidence), last_known_language=history
    )

    assert triage.language == expected
    assert (R.LANGUAGE_UNSUPPORTED in triage.reasons) is unsupported


@pytest.mark.parametrize(("confidence", "tone"), [(0.60, "upset"), (0.59, "neutral")])
def test_tone_below_060_is_neutral(confidence: float, tone: str) -> None:
    triage = apply_triage_rules(jev(tone="upset", tone_conf=confidence), last_known_language=None)

    assert triage.tone == tone


@pytest.mark.parametrize(
    ("p_yes", "flagged"),
    [(0.15, False), (0.1501, True), (0.92, True), (None, True)],  # missing counts as yes
)
def test_manipulation_uses_the_asymmetric_band(p_yes: float | None, flagged: bool) -> None:
    triage = apply_triage_rules(jev(manipulation=p_yes), last_known_language=None)

    assert (R.MANIPULATION in triage.reasons) is flagged
    assert triage.manipulation_p_yes == p_yes


@pytest.mark.parametrize(("p_yes", "flagged"), [(0.49, False), (0.50, True)])
def test_multiple_requests_from_050(p_yes: float, flagged: bool) -> None:
    triage = apply_triage_rules(jev(multiple=p_yes), last_known_language=None)

    assert (R.MULTIPLE_REQUESTS in triage.reasons) is flagged


# --- Luna, the backup ---


def test_luna_labels_route_the_case_and_add_the_backup_note() -> None:
    triage = apply_triage_rules(luna(), last_known_language=None)

    assert triage.classifier_used == "backup"
    assert triage.reasons == (R.CLASSIFIED_WITH_BACKUP,)
    assert triage.intent_confidence is None


def test_luna_is_never_unclear_and_its_other_topic_exits_early() -> None:
    triage = apply_triage_rules(luna(intent="account_update"), last_known_language=None)

    assert triage.about_fee is False
    assert set(triage.reasons) == {R.NOT_FEE_REQUEST, R.CLASSIFIED_WITH_BACKUP}


def test_luna_flags_come_from_its_labels() -> None:
    triage = apply_triage_rules(
        luna(manipulation=True, multiple=True, language="other"), last_known_language=None
    )

    assert {R.MANIPULATION, R.MULTIPLE_REQUESTS, R.LANGUAGE_UNSUPPORTED} <= set(triage.reasons)
    assert triage.manipulation_p_yes is None


def test_when_every_classifier_is_down_the_case_is_still_prepared() -> None:
    triage = triage_unavailable(last_known_language="es")

    assert triage.about_fee is True
    assert triage.reasons == (R.CLASSIFIER_DOWN,)
    assert (triage.language, triage.tone, triage.topic) == ("es", "neutral", None)
    assert triage.classifier_used is None


def test_thresholds_come_from_the_config_file() -> None:
    assert THRESHOLDS.intent_min_confidence == 0.80
    assert THRESHOLDS.manipulation_clear_max_p_yes == 0.15
