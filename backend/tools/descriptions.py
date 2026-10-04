"""Transaction kinds from the core system's free-text descriptions (SPEC-data, "Transaction
kinds"). Deterministic: ordered regular expressions from `core/config/descriptions.yaml`."""

import re
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

CONFIG_FILE = Path(__file__).resolve().parents[1] / "core" / "config" / "descriptions.yaml"

type TxnKind = Literal[
    "fee", "fee_refund", "payroll_deposit", "deposit", "card_payment", "withdrawal", "other"
]
KINDS_WITH_A_FEE_TYPE = frozenset({"fee", "fee_refund"})


class TransactionKind(BaseModel, frozen=True):
    kind: TxnKind
    fee_type: str | None = None  # for example "Courtesy Pay"; only fees and fee refunds have one


class _KindRule(BaseModel, frozen=True):
    kind: TxnKind
    pattern: str


class _FeeTypeRule(BaseModel, frozen=True):
    fee_type: str
    pattern: str


class _Config(BaseModel, frozen=True):
    kinds: list[_KindRule]
    fee_types: list[_FeeTypeRule]


@cache
def _config() -> tuple[list[tuple[TxnKind, re.Pattern[str]]], list[tuple[str, re.Pattern[str]]]]:
    config = _Config.model_validate(yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")))
    kinds = [(rule.kind, re.compile(rule.pattern, re.IGNORECASE)) for rule in config.kinds]
    fee_types = [
        (rule.fee_type, re.compile(rule.pattern, re.IGNORECASE)) for rule in config.fee_types
    ]
    return kinds, fee_types


def classify_description(description: str) -> TransactionKind:
    kinds, fee_types = _config()
    text = " ".join(description.split())
    kind: TxnKind = next((k for k, pattern in kinds if pattern.search(text)), "other")
    fee_type = None
    if kind in KINDS_WITH_A_FEE_TYPE:
        fee_type = next((name for name, pattern in fee_types if pattern.search(text)), None)
    return TransactionKind(kind=kind, fee_type=fee_type)


_PAYEE_PREFIX = re.compile(
    r"^(?:Withdrawal(?: Debit Card| ACH)?|Deposit(?: ACH)?)\s+", re.IGNORECASE
)


def payee(description: str) -> str:
    """Who a payment went to, as the member knows it: "CITY POWER & LIGHT"."""
    return _PAYEE_PREFIX.sub("", " ".join(description.split()))
