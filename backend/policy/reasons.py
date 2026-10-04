"""The reason catalogue (SPEC-policy; D4a in docs/agent-design.md).

Every code Luis can be shown, with its group, its English and Spanish templates and one next
step. Codes live in the database and in evals; Luis only ever sees the rendered text.

Template rules, enforced by tests: plain language with no internal terms, never a gendered
pronoun (the first name or "the message" instead), and every placeholder filled from the facts.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from backend.policy.facts import Fact

type Language = Literal["en", "es"]
type Facts = Mapping[str, Fact]


class ReasonGroup(StrEnum):
    UNCERTAINTY = "uncertainty"
    FAILURE = "failure"
    POLICY = "policy"
    NOTE = "note"
    ROUTING = "routing"


class ReasonCode(StrEnum):
    # Uncertainty
    INTENT_UNCLEAR = "intent_unclear"
    FEE_AMBIGUOUS = "fee_ambiguous"
    FEE_NOT_FOUND = "fee_not_found"
    MANIPULATION = "manipulation"
    MULTIPLE_REQUESTS = "multiple_requests"
    LANGUAGE_UNSUPPORTED = "language_unsupported"
    FEE_QUESTION = "fee_question"
    # Failures
    CLASSIFIER_DOWN = "classifier_down"
    DATA_TIMEOUT = "data_timeout"
    DATA_MISMATCH = "data_mismatch"
    DRAFTER_DOWN = "drafter_down"
    # Policy
    ALREADY_REFUNDED = "already_refunded"
    YEARLY_LIMIT = "yearly_limit"
    NOT_GOOD_STANDING = "not_good_standing"
    DEPOSIT_NOT_SAME_DAY = "deposit_not_same_day"
    OVER_LIMIT = "over_limit"
    # Notes (they never change the status)
    CLASSIFIED_WITH_BACKUP = "classified_with_backup"
    # Routing
    NOT_FEE_REQUEST = "not_fee_request"

    @property
    def group(self) -> ReasonGroup:
        return GROUPS[self]


GROUPS: dict[ReasonCode, ReasonGroup] = {
    **dict.fromkeys(
        [
            ReasonCode.INTENT_UNCLEAR,
            ReasonCode.FEE_AMBIGUOUS,
            ReasonCode.FEE_NOT_FOUND,
            ReasonCode.MANIPULATION,
            ReasonCode.MULTIPLE_REQUESTS,
            ReasonCode.LANGUAGE_UNSUPPORTED,
            ReasonCode.FEE_QUESTION,
        ],
        ReasonGroup.UNCERTAINTY,
    ),
    **dict.fromkeys(
        [
            ReasonCode.CLASSIFIER_DOWN,
            ReasonCode.DATA_TIMEOUT,
            ReasonCode.DATA_MISMATCH,
            ReasonCode.DRAFTER_DOWN,
        ],
        ReasonGroup.FAILURE,
    ),
    **dict.fromkeys(
        [
            ReasonCode.ALREADY_REFUNDED,
            ReasonCode.YEARLY_LIMIT,
            ReasonCode.NOT_GOOD_STANDING,
            ReasonCode.DEPOSIT_NOT_SAME_DAY,
            ReasonCode.OVER_LIMIT,
        ],
        ReasonGroup.POLICY,
    ),
    ReasonCode.CLASSIFIED_WITH_BACKUP: ReasonGroup.NOTE,
    ReasonCode.NOT_FEE_REQUEST: ReasonGroup.ROUTING,
}


@dataclass(frozen=True)
class RenderedReason:
    code: ReasonCode
    message: str
    next_step: str | None  # None only for routing, which shows no banner


_DECLINE_NEXT: dict[Language, str] = {
    "en": "Send the reply, or refund anyway",
    "es": "Envía la respuesta, o reembolsa igualmente",
}

# code -> language -> (message, next step), as str.format templates over {name} and the facts.
# NOT_GOOD_STANDING and DEPOSIT_NOT_SAME_DAY depend on the facts and are rendered by functions.
_TEMPLATES: dict[ReasonCode, dict[Language, tuple[str, str | None]]] = {
    ReasonCode.INTENT_UNCLEAR: {
        "en": ("I'm not sure {name} is asking for a refund.", "Read the message and decide"),
        "es": ("No tengo claro si {name} pide un reembolso.", "Lee el mensaje y decide"),
    },
    ReasonCode.FEE_AMBIGUOUS: {
        "en": (
            "{name} has {candidate_count} fees on {fee_date} and the message doesn't say "
            "which one.",
            "Pick the fee",
        ),
        "es": (
            "{name} tiene {candidate_count} cargos el {fee_date} y el mensaje no dice cuál.",
            "Elige el cargo",
        ),
    },
    ReasonCode.FEE_NOT_FOUND: {
        "en": ("I couldn't find a fee that matches the message.", "Check {name}'s transactions"),
        "es": (
            "No encontré un cargo que coincida con el mensaje.",
            "Revisa los movimientos de {name}",
        ),
    },
    ReasonCode.MANIPULATION: {
        "en": (
            "The message includes instructions aimed at us. I ignored them; the numbers below "
            "come from {name}'s account only.",
            "Review before approving",
        ),
        "es": (
            "El mensaje incluye instrucciones dirigidas a nosotros. Las ignoré; las cifras de "
            "abajo salen solo de la cuenta de {name}.",
            "Revisa antes de aprobar",
        ),
    },
    ReasonCode.MULTIPLE_REQUESTS: {
        "en": ("{name} is asking for more than one thing.", "Answer the rest yourself"),
        "es": ("{name} pide más de una cosa.", "Responde tú el resto"),
    },
    ReasonCode.LANGUAGE_UNSUPPORTED: {
        "en": ("The message isn't in English or Spanish.", "Reply yourself"),
        "es": ("El mensaje no está en inglés ni en español.", "Responde tú"),
    },
    ReasonCode.FEE_QUESTION: {
        "en": (
            "{name} is asking why a fee was charged, not for a refund.",
            "Write a reply, or refund anyway",
        ),
        "es": (
            "{name} pregunta por qué se cobró un cargo; no pide un reembolso.",
            "Escribe una respuesta, o reembolsa igualmente",
        ),
    },
    ReasonCode.CLASSIFIER_DOWN: {
        "en": (
            "The automatic check isn't available right now. Everything below comes from "
            "{name}'s account.",
            "Decide, or try again",
        ),
        "es": (
            "La revisión automática no está disponible ahora. Todo lo de abajo sale de la "
            "cuenta de {name}.",
            "Decide, o vuelve a intentarlo",
        ),
    },
    ReasonCode.DATA_TIMEOUT: {
        "en": ("I couldn't load {name}'s transactions in time.", "Try again"),
        "es": ("No pude cargar los movimientos de {name} a tiempo.", "Vuelve a intentarlo"),
    },
    ReasonCode.DATA_MISMATCH: {
        "en": ("Balances for that day don't add up.", "Check the core system"),
        "es": ("Los saldos de ese día no cuadran.", "Revisa el sistema principal"),
    },
    ReasonCode.DRAFTER_DOWN: {
        "en": ("Reply written from a standard template.", "Review before sending"),
        "es": ("Respuesta escrita con una plantilla estándar.", "Revisa antes de enviar"),
    },
    ReasonCode.ALREADY_REFUNDED: {
        "en": ("This fee was already refunded on {refunded_on}.", "Reply and close"),
        "es": ("Este cargo ya se reembolsó el {refunded_on}.", "Responde y cierra"),
    },
    ReasonCode.YEARLY_LIMIT: {
        "en": (
            "{name} already had {refunds_in_window} refunds in the last 12 months.",
            _DECLINE_NEXT["en"],
        ),
        "es": (
            "{name} ya tuvo {refunds_in_window} reembolsos en los últimos 12 meses.",
            _DECLINE_NEXT["es"],
        ),
    },
    ReasonCode.OVER_LIMIT: {
        "en": ("This is above your approval limit.", "Send to supervisor"),
        "es": ("Supera tu límite de aprobación.", "Envíalo a un supervisor"),
    },
    ReasonCode.CLASSIFIED_WITH_BACKUP: {
        "en": ("Checked with our backup system.", "Confirm before approving"),
        "es": ("Revisado con nuestro sistema de respaldo.", "Confirma antes de aprobar"),
    },
    ReasonCode.NOT_FEE_REQUEST: {
        "en": ("This conversation isn't about a fee.", None),
        "es": ("Esta conversación no trata de un cargo.", None),
    },
}


def render_reason(
    code: ReasonCode, facts: Facts, lang: Language, *, first_name: str
) -> RenderedReason:
    if code is ReasonCode.NOT_GOOD_STANDING:
        message = _not_good_standing(facts, lang, first_name)
        return RenderedReason(code, message, _DECLINE_NEXT[lang])
    if code is ReasonCode.DEPOSIT_NOT_SAME_DAY:
        return RenderedReason(code, _deposit_not_same_day(facts, lang), _DECLINE_NEXT[lang])
    message, next_step = _TEMPLATES[code][lang]
    values = {key: _show(value, lang) for key, value in facts.items()}
    values["name"] = first_name
    return RenderedReason(
        code,
        message.format_map(values),
        next_step.format_map(values) if next_step is not None else None,
    )


def render_summary(
    status: str,
    facts: Facts,
    lang: Language,
    *,
    first_name: str,
    reason: ReasonCode | None = None,
) -> str | None:
    """The one-sentence "why" on the decision card, or None when the card lists reasons."""
    if status == "ready_to_refund" and "deposit_kind" in facts:
        deposit = _deposit_word(facts.get("deposit_kind"), lang, capital=True)
        cause = _cause_word(facts.get("cause_kind"), lang)
        if lang == "es":
            return f"{deposit} llegó el mismo día y {cause} se cobró antes."
        return f"{deposit} arrived the same day and {cause} posted before it."
    if status == "recommend_no_refund" and reason is not None:
        return render_reason(reason, facts, lang, first_name=first_name).message
    if status == "needs_supervisor":
        amount, limit = facts.get("amount"), facts.get("staff_limit")
        if isinstance(amount, Decimal) and isinstance(limit, Decimal):
            if lang == "es":
                return (
                    f"La política permite este reembolso de {_money(amount)}, pero supera tu "
                    f"límite de {_money(limit)}."
                )
            return (
                f"The policy allows this {_money(amount)} refund, but it is above your "
                f"{_money(limit)} limit."
            )
    return None


def render_counterfactual(facts: Facts, lang: Language) -> str | None:
    """The fee-day sentence: the balance if the same-day deposit had posted first."""
    balance = facts.get("balance_if_deposit_first")
    if not isinstance(balance, Decimal):
        return None
    deposit = _deposit_word(facts.get("deposit_kind"), lang, capital=False)
    if lang == "es":
        if balance >= 0:
            return (
                f"Si {deposit} se hubiera registrado primero, el saldo se habría quedado "
                f"en {_money(balance)}."
            )
        return (
            f"Aunque {deposit} se hubiera registrado primero, el saldo habría seguido por "
            f"debajo de cero ({_money(balance)})."
        )
    if balance >= 0:
        return f"If {deposit} had posted first, the balance would have stayed at {_money(balance)}."
    return (
        f"Even if {deposit} had posted first, the balance would still have been below zero "
        f"({_money(balance)})."
    )


def _not_good_standing(facts: Facts, lang: Language, name: str) -> str:
    types = facts.get("overdue_types", [])
    if isinstance(types, list) and "LOAN" in types:
        if lang == "es":
            return f"{name} tiene un pago de préstamo vencido."
        return f"{name} has an overdue loan balance."
    accounts = facts.get("overdue_accounts", [])
    where = ", ".join(accounts) if isinstance(accounts, list) and accounts else ""
    if lang == "es":
        return (
            f"{name} tiene saldo negativo en {where}." if where else f"{name} tiene saldo negativo."
        )
    if where:
        return f"{name} has a balance below zero on {where}."
    return f"{name} has a balance below zero."


def _deposit_not_same_day(facts: Facts, lang: Language) -> str:
    fee_date, next_date = facts.get("fee_date"), facts.get("next_deposit_date")
    if isinstance(fee_date, dt.date) and isinstance(next_date, dt.date):
        deposit = _deposit_word(facts.get("next_deposit_kind"), lang, capital=True)
        gap = _days(next_date - fee_date, lang)
        if lang == "es":
            return f"{deposit} llegó el {_date(next_date, lang)}, {gap} después del cargo."
        return f"{deposit} arrived on {_date(next_date, lang)}, {gap} after the fee."
    if "deposit_date" in facts:
        deposit = _deposit_word(facts.get("deposit_kind"), lang, capital=True)
        if lang == "es":
            return f"{deposit} de ese día no habría cubierto el pago."
        return f"{deposit} that day wouldn't have covered the payment."
    if lang == "es":
        return "No llegó ningún depósito el día del cargo."
    return "No deposit arrived on the day of the fee."


def _deposit_word(kind: Fact | None, lang: Language, *, capital: bool) -> str:
    payroll = kind == "payroll_deposit"
    if lang == "es":
        word = "la nómina" if payroll else "el depósito"
    else:
        word = "the paycheck" if payroll else "the deposit"
    return word[0].upper() + word[1:] if capital else word


def _cause_word(kind: Fact | None, lang: Language) -> str:
    bill = kind == "card_payment"
    if lang == "es":
        return "la factura" if bill else "el pago"
    return "the bill" if bill else "the payment"


_MONTHS: dict[Language, list[str]] = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "es": [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ],
}
_NUMBER_WORDS: dict[Language, list[str]] = {
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"],
    "es": [
        "cero",
        "un",
        "dos",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
    ],
}


def _date(value: dt.date, lang: Language) -> str:
    month = _MONTHS[lang][value.month - 1]
    return f"{value.day} de {month}" if lang == "es" else f"{month} {value.day}"


def _days(delta: dt.timedelta, lang: Language) -> str:
    count = delta.days
    words = _NUMBER_WORDS[lang]
    number = words[count] if 0 <= count < len(words) else str(count)
    if lang == "es":
        return f"{number} día" if count == 1 else f"{number} días"
    return f"{number} day" if count == 1 else f"{number} days"


def _money(amount: Decimal) -> str:
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    text = f"{amount:,.0f}" if amount == amount.to_integral_value() else f"{amount:,.2f}"
    return f"{sign}${text}"


def _show(value: Fact, lang: Language) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, dt.date):
        return _date(value, lang)
    if isinstance(value, Decimal):
        return _money(value)
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)
