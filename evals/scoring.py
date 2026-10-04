"""Scores one run's result against a case's `expected` (SPEC-evals, "Case format").

One check per field the case writes, in the order of `Expected`. A case passes only if every check
passes. Checks are deterministic: the draft's language is read from its common words and its
amounts with the post-check's parser, never by a model.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.agents.draft_postcheck import amounts_in
from evals.case import Expected, ExpectedDraft, ExpectedRecommendation


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str  # what was expected and what came back; reports show it for failures


_WORD = re.compile(r"[a-záéíóúñü]+")
_COMMON = {
    "en": {"the", "your", "you", "we", "and", "to", "of", "for", "thanks", "is", "it", "our"},
    "es": {"el", "la", "los", "las", "tu", "que", "de", "gracias", "por", "en", "del", "te", "y"},
}


def score(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    written = expected.model_fields_set
    checks: list[Check] = []
    for name, check in _CHECKS.items():
        if name in written:
            checks.extend(check(expected, result))
    return checks


def draft_language(text: str) -> str | None:
    """ "en" or "es", by which language's common words the text uses more; None if unsure."""
    words = _WORD.findall(text.lower())
    counts = {lang: sum(word in common for word in words) for lang, common in _COMMON.items()}
    (first, top), (_, second) = sorted(counts.items(), key=lambda item: -item[1])
    return first if top > second else None


# --- One function per field of Expected ---


def _equal(name: str, expected: object, got: object) -> Check:
    return Check(name, expected == got, f"expected {expected}, got {got}")


def _includes(name: str, expected: tuple[str, ...], got: list[str]) -> Check:
    wanted = [str(code) for code in expected]
    missing = [code for code in wanted if code not in got]
    return Check(name, not missing, f"expected {wanted} among {got}")


def _status(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    return [_equal("status", expected.status, result["status"])]


def _reasons(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    return [_includes("reasons_include", expected.reasons_include, result["reasons"])]


def _notes(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    return [_includes("notes_include", expected.notes_include, result["notes"])]


def _topic(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    return [_equal("topic", expected.topic, result["topic"])]


def _language(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    return [_equal("language", expected.language, result["language"])]


def _recommendation(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    wanted = expected.recommendation or ExpectedRecommendation()
    got = result["recommendation"]
    checks = []
    if "action" in wanted.model_fields_set:
        checks.append(_equal("recommendation.action", wanted.action, got["action"]))
    if "amount" in wanted.model_fields_set:
        amount = Decimal(got["amount"]) if got["amount"] is not None else None
        checks.append(_equal("recommendation.amount", wanted.amount, amount))
    if "fee_txn_id" in wanted.model_fields_set:
        checks.append(_equal("recommendation.fee_txn_id", wanted.fee_txn_id, got["fee_txn_id"]))
    return checks


def _clause(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    clause = result["clause"]
    return [_equal("clause_id", expected.clause_id, clause["id"] if clause else None)]


def _clear(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    return [_equal("clear", expected.clear, result["clear"])]


def _draft(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    wanted = expected.draft or ExpectedDraft()
    draft = result["draft"]
    text = draft["text"] if draft else None
    written = wanted.model_fields_set
    checks = []
    if "required" in written:
        checks.append(_equal("draft.required", wanted.required, draft is not None))
    if "contains_amount" in written:
        found = amounts_in(text) if text else []
        checks.append(
            Check(
                "draft.contains_amount",
                wanted.contains_amount in found,
                f"expected {wanted.contains_amount} among {[str(amount) for amount in found]}",
            )
        )
    if "language" in written:
        checks.append(_equal("draft.language", wanted.language, text and draft_language(text)))
    if "source" in written:
        checks.append(_equal("draft.source", wanted.source, draft["source"] if draft else None))
    return checks  # reference_text is for reading only


def _must_not_appear(expected: Expected, result: Mapping[str, Any]) -> list[Check]:
    text = json.dumps(result, ensure_ascii=False, default=str)
    found = [needle for needle in expected.must_not_appear if _appears(needle, text)]
    return [Check("must_not_appear", not found, f"found {found}")]


def _appears(needle: str, text: str) -> bool:
    """A number must stand alone ("500" is not in "1500.00" or "90501"); text is matched in any
    case."""
    if re.fullmatch(r"[\d.,]+", needle):
        return re.search(rf"(?<![\d.,]){re.escape(needle)}(?!\d)", text) is not None
    return needle.lower() in text.lower()


_CHECKS: dict[str, Callable[[Expected, Mapping[str, Any]], list[Check]]] = {
    "status": _status,
    "reasons_include": _reasons,
    "notes_include": _notes,
    "topic": _topic,
    "language": _language,
    "recommendation": _recommendation,
    "clause_id": _clause,
    "clear": _clear,
    "draft": _draft,
    "must_not_appear": _must_not_appear,
}
