"""The deterministic post-check on Sol's reply (SPEC-agent, "Post-check"; D2).

A reply passes only if it keeps the `{{first_name}}` placeholder, names no amount but the decided
one (or one the quoted policy clause states), has no run of six or more digits, and is at most
800 characters. It returns the problems found, in that order, so the trace says why it failed.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Literal

type Problem = Literal["placeholder", "amount", "digits", "length"]

PLACEHOLDER = "{{first_name}}"
MAX_CHARS = 800
_NUMBER = r"\d[\d.,]*\d|\d"
# "$35", "$35.00", "$1,360", "US$35"; and "35,00 $", "35 dollars", "500 dólares", "35 USD".
_MONEY = (
    re.compile(rf"(?:US)?\$\s?({_NUMBER})"),
    re.compile(rf"({_NUMBER})\s?(?:\$|USD\b|dollars?\b|d[oó]lares\b)", re.IGNORECASE),
)
_LONG_DIGITS = re.compile(r"\d{6,}")


def check_draft(reply: str, *, amount: Decimal, policy_clause: str | None = None) -> list[Problem]:
    problems: list[Problem] = []
    if PLACEHOLDER not in reply:
        problems.append("placeholder")
    allowed = {amount, *amounts_in(policy_clause or "")}
    if any(value not in allowed for value in amounts_in(reply)):
        problems.append("amount")
    if _LONG_DIGITS.search(reply):
        problems.append("digits")
    if len(reply) > MAX_CHARS:
        problems.append("length")
    return problems


def amounts_in(text: str) -> list[Decimal]:
    """Every amount of money the text names, in English or Spanish number formats."""
    found = []
    for pattern in _MONEY:
        for match in pattern.finditer(text):
            value = _parse(match.group(1))
            if value is not None:
                found.append(value)
    return found


def _parse(number: str) -> Decimal | None:
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", number):  # 1,360.00
        number = number.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", number):  # 1.360,00
        number = number.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d{1,2}", number):  # 35,00
        number = number.replace(",", ".")
    try:
        return Decimal(number)
    except InvalidOperation:
        return None
