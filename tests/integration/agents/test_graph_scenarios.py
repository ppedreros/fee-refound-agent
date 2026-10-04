"""The agent graph end to end on the seed, with in-process fake providers (D10: tests never use
replay files or live models). Each scenario asserts the status and what Luis would see."""

import json
from typing import Any
from uuid import uuid4

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agents.deps import AgentDeps
from backend.agents.graph import build_graph
from backend.agents.state import GraphState
from backend.agents.steps import StepRecord
from backend.providers.types import Classifier
from tests.integration.agents.fakes import FakeChooser, FakeClassifier, FakeDrafter, jev_answers

SEEDED_SECRETS = ("Ana", "Torres", "884210", "884211")


async def run(
    case_id: int,
    classifier: FakeClassifier,
    reader: async_sessionmaker[AsyncSession],
    chooser: Classifier | None = None,
    drafter: FakeDrafter | None = None,
    pinned: int | None = None,
) -> tuple[dict[str, Any], list[StepRecord]]:
    graph = build_graph()
    final: dict[str, Any] = {}
    records: list[StepRecord] = []
    async for mode, chunk in graph.astream(
        GraphState(case_id=case_id, run_id=uuid4(), pinned_fee_txn_id=pinned),
        context=AgentDeps(
            reader=reader,
            classifier=classifier,
            drafter=drafter or FakeDrafter(),
            chooser=chooser,
        ),
        stream_mode=["values", "custom"],
    ):
        if mode == "values":
            final = chunk
        elif chunk.get("state") in ("finished", "failed"):
            records.append(chunk["record"])
    return final, records


async def test_ana_is_ready_to_refund_with_a_drafted_reply(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, _ = await run(5012, FakeClassifier(jev_answers()), reader)
    result = final["result"]

    assert result["status"] == "ready_to_refund"
    assert result["recommendation"] == {"action": "refund", "amount": "35.00", "fee_txn_id": 88002}
    assert result["clear"] is True
    assert result["would_auto_approve"] is True
    assert result["clause"]["id"] == "fee-refund-policy#4"
    assert result["clause"]["found_by"] == "rule_fallback"
    assert "{{first_name}}" in result["draft"]["text"]
    assert "$35" in result["draft"]["text"]
    assert result["draft"]["source"] == "model"


async def test_ana_runs_every_node_once_and_the_reads_in_parallel(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    _, records = await run(5012, FakeClassifier(jev_answers()), reader)

    nodes = [record.node for record in records]
    assert nodes[:2] == ["load_conversation", "triage"]
    assert set(nodes[2:5]) == {"load_accounts", "load_transactions", "load_refund_history"}
    assert nodes[5:] == [
        "identify_fee",
        "run_checks",
        "decide",
        "find_policy",
        "draft",
        "finalize",
    ]
    assert all(record.status == "finished" for record in records)


async def test_no_step_input_holds_a_name_or_an_account_number(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    classifier = FakeClassifier(jev_answers())

    _, records = await run(5012, classifier, reader)

    for record in records:
        text = json.dumps(record.input_masked, default=str)
        assert not any(secret in text for secret in SEEDED_SECRETS), record.node
    assert classifier.states == [
        {
            "subject": "Overdraft fee",
            "message": "My paycheck came the same day. Can you refund this?",
        }
    ]


@pytest.mark.parametrize(
    ("case_id", "topic"),
    [(5011, "card_issue"), (5010, "account_update"), (5009, "statement_question")],
)
async def test_a_message_that_is_not_about_a_fee_loads_no_balances(
    reader: async_sessionmaker[AsyncSession], case_id: int, topic: str
) -> None:
    """SPEC-data scenarios 2, 3 and 4."""
    final, records = await run(case_id, FakeClassifier(jev_answers(topic)), reader)

    assert final["result"]["status"] == "not_about_fee"
    assert final["result"]["topic"] == topic
    assert final["result"]["reasons"] == ["not_fee_request"]  # routing: the page shows no banner
    assert [r.node for r in records] == ["load_conversation", "triage", "finalize"]


async def test_with_every_classifier_down_the_case_is_still_prepared(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, records = await run(5012, FakeClassifier(None), reader)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["classifier_down"]
    assert result["recommendation"]["action"] == "refund"
    assert next(r for r in records if r.node == "triage").status == "failed"


# --- find_policy: search, Jev's clause choice, and the cross-check with the deciding rule (D7b) ---


def policy_step(records: list[StepRecord]) -> StepRecord:
    return next(record for record in records if record.node == "find_policy")


async def test_ana_quotes_the_clause_search_found_and_jev_confirmed(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    chooser = FakeChooser(clause="fee-refund-policy#4")

    final, records = await run(5012, FakeClassifier(jev_answers()), reader, chooser)

    clause = final["result"]["clause"]
    assert (clause["id"], clause["found_by"]) == ("fee-refund-policy#4", "search_confirmed")
    options = chooser.options["clause"]
    assert {"fee-refund-policy#2", "fee-refund-policy#4"} <= set(options)
    (state,) = chooser.states
    assert state == {
        "decision": "Refund the $35 Courtesy Pay fee.",
        "facts": "The paycheck arrived the same day and the bill posted before it.",
    }
    step = policy_step(records)
    assert (step.kind, step.status, step.prompt_version) == ("jev", "finished", "clause-choice-v1")
    assert step.output is not None
    assert (step.output["chosen"], step.output["mismatch"]) == ("fee-refund-policy#4", False)


async def test_ana_with_a_mismatched_choice_quotes_the_rules_clause_and_logs_it(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    chooser = FakeChooser(clause="fee-refund-policy#2")

    with structlog.testing.capture_logs() as logs:
        final, records = await run(5012, FakeClassifier(jev_answers()), reader, chooser)

    clause = final["result"]["clause"]
    assert (clause["id"], clause["found_by"]) == ("fee-refund-policy#4", "rule_fallback")
    mismatch = next(log for log in logs if log["event"] == "clause_mismatch")
    assert (mismatch["expected"], mismatch["chosen"]) == (
        "fee-refund-policy#4",
        "fee-refund-policy#2",
    )
    output = policy_step(records).output
    assert output is not None and output["mismatch"] is True


async def test_ana_with_a_low_confidence_choice_quotes_the_rules_clause(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    chooser = FakeChooser(clause="fee-refund-policy#4", confidence=0.5)

    final, _ = await run(5012, FakeClassifier(jev_answers()), reader, chooser)

    assert final["result"]["clause"]["found_by"] == "rule_fallback"
    assert final["result"]["status"] == "ready_to_refund"  # the quote never changes the outcome


async def test_ana_with_jev_down_for_the_clause_choice_still_quotes_the_rules_clause(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, records = await run(5012, FakeClassifier(jev_answers()), reader, FakeChooser())

    clause = final["result"]["clause"]
    assert (clause["id"], clause["found_by"]) == ("fee-refund-policy#4", "rule_fallback")
    step = policy_step(records)
    assert step.status == "finished"
    assert step.output is not None and step.output["rerank_error"] == "timeout"


# --- When the policy says no (SPEC-data scenarios 6, 7, 8, 11 and 17) ---


@pytest.mark.parametrize(
    ("case_id", "status", "reason", "clause", "amount"),
    [
        (5106, "recommend_no_refund", "yearly_limit", "fee-refund-policy#2", "35.00"),
        (5107, "recommend_no_refund", "deposit_not_same_day", "fee-refund-policy#4", "35.00"),
        (5108, "recommend_no_refund", "not_good_standing", "fee-refund-policy#3", "35.00"),
        (5111, "recommend_no_refund", "already_refunded", "fee-refund-policy#5", "35.00"),
        (5117, "needs_supervisor", "over_limit", "staff-approval-limits#1", "60.00"),
    ],
)
async def test_when_the_policy_says_no_the_case_says_why_and_quotes_the_rule(
    reader: async_sessionmaker[AsyncSession],
    case_id: int,
    status: str,
    reason: str,
    clause: str,
    amount: str,
) -> None:
    final, _ = await run(case_id, FakeClassifier(jev_answers()), reader)
    result = final["result"]

    assert result["status"] == status
    assert result["reasons"] == [reason]
    assert result["clause"]["id"] == clause
    assert result["recommendation"]["amount"] == amount
    assert result["clear"] is False


async def test_a_decline_draft_is_told_the_clause_in_plain_facts(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    drafter = FakeDrafter()

    final, _ = await run(5106, FakeClassifier(jev_answers()), reader, drafter=drafter)

    (payload,) = drafter.payloads
    assert payload.outcome == "no_refund"
    assert payload.policy_clause == final["result"]["clause"]["text"]
    assert payload.facts == ["The member already had 3 refunds in the last 12 months."]
    assert final["result"]["draft"]["source"] == "model"


async def test_above_the_limit_nothing_is_drafted_and_jev_hears_about_the_limit(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    """Luis can't refund it here (D-api-1), so there is no refund reply to write."""
    drafter, chooser = FakeDrafter(), FakeChooser(clause="staff-approval-limits#1")

    final, records = await run(5117, FakeClassifier(jev_answers()), reader, chooser, drafter)

    assert final["result"]["status"] == "needs_supervisor"
    assert final["result"]["draft"] is None
    assert drafter.payloads == []
    assert "draft" not in [record.node for record in records]
    (state,) = chooser.states
    assert state == {
        "decision": "Refund the $60 Extended overdraft fee, above the staff approval limit.",
        "facts": "The policy allows this $60 refund, but it is above your $50 limit.",
    }
    assert final["result"]["clause"]["found_by"] == "search_confirmed"


# --- Which fee (SPEC-data scenarios 9, 10 and 15; SPEC-agent AC5) ---

ELECTRIC_BILL_FEE, STREAMING_FEE = 90902, 90904  # scenario 9's two $35 fees on Sep 14


async def test_two_fees_and_a_vague_message_ask_luis_to_pick_the_fee(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    chooser = FakeChooser()  # Jev can't answer the fee choice

    final, _ = await run(5109, FakeClassifier(jev_answers()), reader, chooser)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["fee_ambiguous"]
    assert result["recommendation"]["action"] == "none"
    assert [c["id"] for c in result["candidates"]] == [ELECTRIC_BILL_FEE, STREAMING_FEE]
    assert [c["after"] for c in result["candidates"]] == [
        {"payee": "CITY POWER & LIGHT", "amount": "-60.00"},
        {"payee": "STREAMFLIX", "amount": "-15.99"},
    ]
    assert chooser.options["fee"] == [str(ELECTRIC_BILL_FEE), str(STREAMING_FEE)]


async def test_an_unsure_fee_choice_is_still_luis_s_to_make(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    chooser = FakeChooser(fee=str(ELECTRIC_BILL_FEE), confidence=0.6)

    final, _ = await run(5109, FakeClassifier(jev_answers()), reader, chooser)

    assert final["result"]["reasons"] == ["fee_ambiguous"]


async def test_jev_picks_the_fee_the_message_names(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    chooser = FakeChooser(fee="91002", clause="fee-refund-policy#4")  # the electric bill's fee

    final, records = await run(5110, FakeClassifier(jev_answers()), reader, chooser)
    result = final["result"]

    assert result["status"] == "ready_to_refund"
    assert (result["fee"]["id"], result["fee"]["source"]) == (91002, "jev")
    assert result["clear"] is False  # Jev chose the fee: Luis still checks
    state = chooser.states[0]
    assert set(state) == {"subject", "message"}
    assert "electric bill" in state["message"]
    identify = next(record for record in records if record.node == "identify_fee")
    assert (identify.kind, identify.prompt_version) == ("jev", "fee-choice-v1")


async def test_a_refund_request_with_no_fee_in_the_window_is_fee_not_found(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, _ = await run(5115, FakeClassifier(jev_answers()), reader)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["fee_not_found"]
    assert result["recommendation"]["action"] == "none"
    assert result["draft"] is None


async def test_the_fee_luis_picks_is_checked_as_staff_input(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, _ = await run(
        5109, FakeClassifier(jev_answers()), reader, FakeChooser(), pinned=STREAMING_FEE
    )
    result = final["result"]

    assert (result["fee"]["id"], result["fee"]["source"]) == (STREAMING_FEE, "staff")
    assert "fee_ambiguous" not in result["reasons"]
    assert result["status"] == "ready_to_refund"


async def test_a_pinned_fee_that_is_not_a_candidate_is_refused(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, _ = await run(5109, FakeClassifier(jev_answers()), reader, pinned=88002)

    assert final["result"]["reasons"] == ["fee_not_found"]
    assert final["result"]["fee"] is None


async def test_the_ambiguous_fee_reason_has_the_day_the_fees_share(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    final, _ = await run(5109, FakeClassifier(jev_answers()), reader)

    assert final["result"]["facts"] == {"candidate_count": 2, "fee_date": "2026-09-14"}


async def test_a_question_about_a_fee_gets_the_evidence_and_the_schedule_but_no_draft(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    """SPEC-data scenario 5 (5008); SPEC-agent AC1 and D-agent-1."""
    classifier = FakeClassifier(jev_answers("fee_question"))
    chooser = FakeChooser(clause="fee-schedule#4")

    final, records = await run(5008, classifier, reader, chooser)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["fee_question"]
    assert result["recommendation"] == {"action": "none", "amount": None, "fee_txn_id": 90501}
    assert (result["fee"]["id"], result["fee"]["fee_type"]) == (90501, "Savings below minimum")
    assert (result["clause"]["id"], result["clause"]["found_by"]) == (
        "fee-schedule#4",
        "search_confirmed",
    )
    assert result["draft"] is None
    assert "draft" not in [record.node for record in records]
    assert [check["rule"] for check in result["checks"]] == [  # every rule, as evidence
        "verify_posting_order",
        "check_not_already_refunded",
        "check_yearly_limit",
        "check_good_standing",
        "check_approval_limit",
    ]


# --- Injection, Spanish and more than one request (SPEC-data scenarios 12, 13 and 14) ---


async def test_an_injection_is_flagged_and_changes_nothing_but_the_status(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    """SPEC-agent AC3: the message can't move the amount, the rules or the decision."""
    drafter = FakeDrafter()
    classifier = FakeClassifier(jev_answers(manipulation=0.98))

    final, records = await run(5112, classifier, reader, drafter=drafter)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["manipulation"]
    assert result["recommendation"] == {"action": "refund", "amount": "35.00", "fee_txn_id": 91202}
    assert "500" not in json.dumps(result)
    assert "500" not in result["draft"]["text"]
    (payload,) = drafter.payloads
    assert "500" not in payload.model_dump_json()  # Sol never sees the message (D2)
    triage = next(record for record in records if record.node == "triage")
    assert triage.input_masked is not None
    assert "$500" in json.dumps(triage.input_masked)  # Jev did see it, as data to judge


async def test_a_spanish_message_gets_a_spanish_reply(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    drafter = FakeDrafter()

    final, _ = await run(5113, FakeClassifier(jev_answers(language="es")), reader, drafter=drafter)

    assert final["result"]["status"] == "ready_to_refund"
    assert final["result"]["language"] == "es"
    (payload,) = drafter.payloads
    assert payload.language == "es"


async def test_a_spanish_reply_falls_back_to_the_spanish_template(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    classifier = FakeClassifier(jev_answers(language="es"))

    final, _ = await run(5113, classifier, reader, drafter=FakeDrafter([None]))

    draft = final["result"]["draft"]
    assert (draft["source"], draft["text"][:22]) == ("template", "Hola {{first_name}}, g")
    assert "la nómina" in draft["text"]


async def test_more_than_one_request_needs_your_call_and_keeps_the_refund(
    reader: async_sessionmaker[AsyncSession],
) -> None:
    classifier = FakeClassifier(jev_answers(multiple_requests=0.9))

    final, _ = await run(5114, classifier, reader)
    result = final["result"]

    assert result["status"] == "needs_your_call"
    assert result["reasons"] == ["multiple_requests"]
    assert result["recommendation"]["action"] == "refund"
    assert result["draft"] is not None  # it answers the refund; Luis adds the rest
