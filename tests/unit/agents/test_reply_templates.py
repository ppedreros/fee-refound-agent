"""The fallback replies (SPEC-agent, "Templates"): every one, in both languages, keeps the name
placeholder, fills every value, and passes the same post-check as Sol's replies."""

from decimal import Decimal

import pytest

from backend.agents.draft_postcheck import check_draft
from backend.agents.prompts import TEMPLATES_DIR, render_template

VALUES = {
    "fee_date": "Sep 14",
    "amount": "$35",
    "fee_type": "Courtesy Pay",
    "sub_account_name": "Everyday Checking",
    "deposit": "your paycheck",
    "max_refunds": "3",
    "refunded_on": "Sep 11",
}
NAMES = [
    "refunded",
    *(
        f"declined_{reason}"
        for reason in (
            "yearly_limit",
            "deposit_not_same_day",
            "not_good_standing",
            "already_refunded",
        )
    ),
]


def test_every_reason_has_a_template_in_both_languages() -> None:
    files = {path.name for path in TEMPLATES_DIR.glob("*.txt")}

    assert files == {f"{name}.{lang}.txt" for name in NAMES for lang in ("en", "es")}


@pytest.mark.parametrize("lang", ["en", "es"])
@pytest.mark.parametrize("name", NAMES)
def test_a_template_reads_as_a_finished_reply(name: str, lang: str) -> None:
    reply = render_template(name, lang, VALUES)

    assert reply is not None
    assert reply.startswith("Hi {{first_name}}," if lang == "en" else "Hola {{first_name}},")
    assert "$" not in reply.replace("$35", "")  # every placeholder was filled
    assert check_draft(reply, amount=Decimal("35.00")) == []
