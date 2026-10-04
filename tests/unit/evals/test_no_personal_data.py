"""SPEC-evals AC7: no case or report holds a seeded name or account number. The scan is the one
SPEC-providers runs over the recordings."""

import yaml

from backend.providers.replay import find_personal_data
from evals.case import CASES_DIR
from evals.report import REPORTS_DIR
from tests.unit.providers.test_recordings_have_no_pii import ACCOUNT_NUMBERS, NAMES, texts


def test_no_case_holds_personal_data() -> None:
    """Every text of every case, one per line (ids and amounts are numbers, not scanned)."""
    findings = {
        path.name: found
        for path in sorted(CASES_DIR.rglob("*.yaml"))
        if (
            found := find_personal_data(
                "\n".join(texts(yaml.safe_load(path.read_text(encoding="utf-8")))),
                names=NAMES,
                account_numbers=ACCOUNT_NUMBERS,
            )
        )
    }

    assert findings == {}


def test_no_report_names_a_member_or_an_account() -> None:
    """Reports hold costs and latencies, which are runs of digits by design, so only names and
    account numbers are looked for."""
    findings = {
        path.name: found
        for path in sorted(REPORTS_DIR.glob("*.*"))
        if (
            found := [
                kind
                for kind in find_personal_data(
                    path.read_text(encoding="utf-8"), names=NAMES, account_numbers=ACCOUNT_NUMBERS
                )
                if kind in ("name", "account_number")
            ]
        )
    }

    assert findings == {}


def test_the_scan_reads_case_texts() -> None:
    case = {"message_override": "I am Ana Torres", "expected": {"must_not_appear": ["884210"]}}

    found = find_personal_data("\n".join(texts(case)), names=NAMES, account_numbers=ACCOUNT_NUMBERS)

    assert set(found) >= {"name", "account_number"}
