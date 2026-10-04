"""The policy search query is built from the case's facts, never from the member's text (D7b)."""

from backend.policy.search import build_policy_query


def test_the_query_names_the_fee_and_the_topic_of_each_rule_deciding_rule_first() -> None:
    query = build_policy_query(
        fee_type="Courtesy Pay", rules=["verify_posting_order", "check_yearly_limit"]
    )

    words = query.split(" OR ")
    assert words[:4] == ["courtesy", "pay", "fee", "refund"]
    assert words.index("same") < words.index("month")  # the deciding rule's words come first
    assert len(words) == len(set(words))


def test_words_are_joined_with_or_so_one_clause_need_not_hold_them_all() -> None:
    query = build_policy_query(fee_type=None, rules=["check_good_standing"])

    assert query == "fee OR refund OR good OR standing OR unpaid OR balance"


def test_a_question_about_a_fee_searches_for_the_fee_not_a_refund() -> None:
    query = build_policy_query(fee_type="Savings below minimum", rules=[], refund=False)

    assert query == "savings OR below OR minimum OR fee"
