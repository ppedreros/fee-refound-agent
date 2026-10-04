"""SPEC-providers AC9: no recording holds personal data. Recordings are committed, so this scan
runs over every file, for the seed's names and account numbers and the masking patterns."""

import json
from pathlib import Path
from typing import Any

from backend.db.seed.scenarios import SCENARIOS
from backend.providers.replay import RECORDINGS_DIR, find_personal_data

NAMES = [
    value
    for scenario in SCENARIOS
    for profile in scenario.rows.get("member_profiles", [])
    for value in (profile["first_name"], profile["last_name"])
]
ACCOUNT_NUMBERS = [
    account["account_number"]
    for scenario in SCENARIOS
    for account in scenario.rows.get("accounts", [])
]


def test_the_seed_gives_names_and_account_numbers_to_look_for() -> None:
    assert {"Ana", "Torres"} <= set(NAMES)
    assert "884210" in ACCOUNT_NUMBERS


def recorded_text(path: Path) -> str:
    """Every text a recording holds from the case and the model: the masked request and the
    answer. Personal data is text; numbers are not scanned, because a key (sha256), a cost
    (0.000032) or a probability (0.8099999999999999) is a run of digits by design."""
    record = json.loads(path.read_text(encoding="utf-8"))
    # One text per line: joined by spaces, ids side by side ("90902 90904") would read as a card.
    return "\n".join(texts([record["request"], record["response"]]))


def texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [*value.keys(), *(text for item in value.values() for text in texts(item))]
    if isinstance(value, list):
        return [text for item in value for text in texts(item)]
    return []


def test_there_are_recordings_to_scan() -> None:
    assert len(list(RECORDINGS_DIR.rglob("*.json"))) > 0


def test_no_recording_holds_personal_data() -> None:
    findings = {
        str(path.relative_to(RECORDINGS_DIR)): found
        for path in sorted(RECORDINGS_DIR.rglob("*.json"))
        if (
            found := find_personal_data(
                recorded_text(path), names=NAMES, account_numbers=ACCOUNT_NUMBERS
            )
        )
    }

    assert findings == {}


def test_the_scan_finds_what_it_looks_for(tmp_path: Path) -> None:
    leaked = (
        '{"message": "I am Ana Torres, account 884210, ana.t@example.com, '
        'call 555-201-3344, card 4111 1111 1111 1111"}'
    )

    found = find_personal_data(leaked, names=NAMES, account_numbers=ACCOUNT_NUMBERS)

    assert set(found) >= {"name", "account_number", "email", "phone", "card"}


def test_masked_text_and_amounts_are_not_personal_data() -> None:
    masked = (
        '{"message": "Hi, I am [FIRST_NAME] [LAST_NAME], account [ACCOUNT_1]. Refund the $35 '
        'from Sep 14 at CITY POWER & LIGHT."}'
    )

    assert find_personal_data(masked, names=NAMES, account_numbers=ACCOUNT_NUMBERS) == []
