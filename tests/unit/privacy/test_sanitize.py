"""sanitize(): what customer text goes through before any model sees it (SPEC-providers)."""

import pytest

from backend.privacy.sanitize import MAX_CHARS, sanitize

ANA = "My paycheck came the same day. Can you refund this?"


def test_an_ordinary_message_is_unchanged() -> None:
    result = sanitize(ANA)

    assert result.text == ANA
    assert result.truncated is False


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("\uff52\uff45\uff46\uff55\uff4e\uff44 \uff4d\uff45", "refund me"),  # full-width (NFKC)
        ("\ufb01x the \ufb01le", "fix the file"),  # ligatures (NFKC)
        ("refund\u202e me", "refund me"),  # right-to-left override
        ("re\u200bfund", "refund"),  # zero-width space
        ("\ufeffrefund", "refund"),  # byte-order mark
        ("re\u2060fund\u2064", "refund"),  # word joiner and invisible plus
        ("\u2067refund me\u2069", "refund me"),  # bidi isolates ("Trojan Source")
        ("re\u2066fund\u2068 me", "refund me"),  # left-to-right and first-strong isolates
        ("refund\u061c me", "refund me"),  # Arabic letter mark
        ("refund\x00\x07 me", "refund me"),  # control characters
        ("refund\t\t   me", "refund me"),  # runs of spaces and tabs
        ("line one\n\n\n  line two  ", "line one\nline two"),  # blank lines and edges
    ],
)
def test_invisible_and_control_characters_go_and_whitespace_collapses(raw: str, clean: str) -> None:
    assert sanitize(raw).text == clean


def test_long_text_is_capped_and_flagged() -> None:
    result = sanitize("a" * (MAX_CHARS + 50))

    assert len(result.text) == MAX_CHARS == 2000
    assert result.truncated is True


def test_text_at_the_cap_is_not_flagged() -> None:
    result = sanitize("a" * MAX_CHARS)

    assert result.truncated is False
