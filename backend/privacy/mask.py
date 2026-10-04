"""Deterministic masking of personal data (SPEC-providers; D9).

Known values of the member come first, replaced exactly; then generic patterns. Amounts, dates
and merchant names are left alone, because the fee choice and the manipulation check need them.
The mapping from placeholders to values never prints its values and is never logged or stored.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(
    r"(?<![\w+])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-]?)\d{3}[\s.-]?\d{4}(?!\w)"
)
CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
NUMBER = re.compile(r"(?<!\d)\d{6,}(?!\d)")


@dataclass(frozen=True)
class MaskingDictionary:
    """Values of this member, taken from the database. The agent builds it from plain values."""

    first_name: str = field(repr=False)
    last_name: str = field(repr=False)
    account_numbers: list[str] = field(repr=False)

    def __str__(self) -> str:
        return repr(self)


class MaskMapping:
    """Placeholder -> original value. Shown only as a count."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def placeholder(self, kind: str, value: str, *, numbered: bool = False) -> str:
        for placeholder, known in self._values.items():
            if known == value and placeholder.startswith(f"[{kind}"):
                return placeholder
        count = sum(
            1 for p in self._values if p.startswith(f"[{kind}]") or p.startswith(f"[{kind}_")
        )
        name = f"[{kind}_{count + 1}]" if numbered or count else f"[{kind}]"
        self._values[name] = value
        return name

    def items(self) -> list[tuple[str, str]]:
        return list(self._values.items())

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"MaskMapping({len(self._values)} values hidden)"

    __str__ = __repr__


@dataclass(frozen=True)
class Masked:
    text: str
    mapping: MaskMapping


def mask(text: str, dictionary: MaskingDictionary) -> Masked:
    mapping = MaskMapping()

    # Emails go first, so a name inside an address ("ana.t@…") doesn't split it in two.
    text = EMAIL.sub(_replace(mapping, "EMAIL"), text)

    # 1. Known values: names as whole words in any case; accounts numbered by first appearance.
    for kind, value in (("FIRST_NAME", dictionary.first_name), ("LAST_NAME", dictionary.last_name)):
        if value.strip():
            pattern = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)", re.IGNORECASE)
            text = pattern.sub(_replace(mapping, kind), text)
    accounts = [a for a in dictionary.account_numbers if a.strip()]
    if accounts:
        pattern = re.compile(
            r"(?<!\d)(?:"
            + "|".join(re.escape(a) for a in sorted(accounts, key=len, reverse=True))
            + r")(?!\d)"
        )
        text = pattern.sub(_replace(mapping, "ACCOUNT", numbered=True), text)

    # 2-4. Generic patterns, in this order.
    text = PHONE.sub(_replace(mapping, "PHONE"), text)
    text = CARD.sub(_replace_card(mapping), text)
    text = NUMBER.sub(_replace(mapping, "NUMBER"), text)
    return Masked(text=text, mapping=mapping)


def unmask(text: str, mapping: MaskMapping) -> str:
    """Put the real values back. Only for Luis's page, never for a model or a log."""
    for placeholder, value in mapping.items():
        text = text.replace(placeholder, value)
    return text


def _replace(
    mapping: MaskMapping, kind: str, *, numbered: bool = False
) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        return mapping.placeholder(kind, match.group(0), numbered=numbered)

    return replace


def _replace_card(mapping: MaskMapping) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return mapping.placeholder("CARD", match.group(0))
        return match.group(0)  # not a card; a long digit run is still caught as [NUMBER]

    return replace


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0
