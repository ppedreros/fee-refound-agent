"""The graph's nodes (SPEC-agent, "Nodes"). Each takes the state and the deps and returns its update
plus a StepReport for the run trace. Load nodes only read; every decision is plain code.

At this stage more than one fee candidate gives `fee_ambiguous` until the Jev fee choice lands
(T32).
"""

import datetime as dt
from typing import Any

import structlog
from pydantic import TypeAdapter

from backend.agents.decide import Decision, case_status, decide
from backend.agents.deps import AgentDeps
from backend.agents.draft_postcheck import Problem, check_draft
from backend.agents.prompts import (
    load_choice_prompt,
    load_prompt,
    load_questions,
    render_template,
)
from backend.agents.state import ClauseRef, DraftReply, GraphState
from backend.agents.steps import StepReport, run_tool
from backend.agents.triage_rules import Triage, apply_triage_rules, triage_unavailable
from backend.policy.facts import Fact
from backend.policy.loader import fee_schedule_clause
from backend.policy.reasons import (
    GROUPS,
    Language,
    ReasonCode,
    ReasonGroup,
    format_date,
    format_money,
    render_reason,
    render_summary,
)
from backend.policy.rules import (
    check_approval_limit,
    check_good_standing,
    check_not_already_refunded,
    check_yearly_limit,
    find_fee_candidates,
    verify_posting_order,
)
from backend.policy.search import build_policy_query, get_clause, search_clauses
from backend.privacy.mask import MaskingDictionary, mask
from backend.privacy.sanitize import sanitize
from backend.providers.chain import ClassifierUnavailable
from backend.providers.types import (
    CallMeta,
    ChoiceAnswer,
    ChoiceQuestion,
    DraftInput,
    Option,
    ProviderUnavailable,
)
from backend.tools import queries
from backend.tools.errors import ToolError
from backend.tools.models import Message, Transaction

TRIAGE_PROMPT = "triage-v1"
DRAFT_PROMPT = "draft-v1"
CLAUSE_PROMPT = "clause-choice-v1"
DRAFT_TRIES = 2  # a reply that fails the post-check is asked for once more (§6)
DECLINE_TEMPLATES = frozenset(
    {
        ReasonCode.YEARLY_LIMIT,
        ReasonCode.DEPOSIT_NOT_SAME_DAY,
        ReasonCode.NOT_GOOD_STANDING,
        ReasonCode.ALREADY_REFUNDED,
    }
)
SOMEONE = "The member"  # how the facts for Sol refer to the member: never by name
TRANSACTIONS_LOOKBACK_DAYS = 30  # find_fee_candidates looks this far back from the message
REFUNDS_LOOKBACK_DAYS = 400  # covers the 365-day limit window ending on any candidate fee
READS = ["load_accounts", "load_transactions", "load_refund_history"]
_FACTS = TypeAdapter(dict[str, Fact])

log = structlog.get_logger()

type Update = dict[str, Any]


# --- Loads ---


async def load_conversation(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    """The member's messages since the last staff reply, sanitised and masked. No balances."""
    where = {"conversation_id": state.case_id}

    async def read(session: Any) -> tuple[Any, Any, list[str], str | None]:
        conversation = await queries.get_conversation(session, state.case_id)
        member = conversation.member_id
        profile = await queries.get_member_profile(session, member)
        numbers = await queries.list_account_numbers(session, member)
        language = await queries.get_last_known_language(
            session, member, exclude_case_id=state.case_id
        )
        return conversation, profile, numbers, language

    try:
        conversation, profile, numbers, language = await run_tool(deps, read)
    except ToolError as error:
        failed = StepReport(kind="tool", input_masked=where, error_code=error.reason)
        return {"reasons": [ReasonCode.DATA_TIMEOUT]}, failed

    messages = _since_last_staff_reply(conversation.messages)
    dictionary = MaskingDictionary(
        first_name=profile.first_name, last_name=profile.last_name, account_numbers=numbers
    )
    message = sanitize("\n".join(m.body for m in messages))
    subject = sanitize(conversation.subject)
    update: Update = {
        "member_id": conversation.member_id,
        "message_at": messages[-1].created_at if messages else conversation.created_at,
        "masked_subject": mask(subject.text, dictionary).text,
        "masked_message": mask(message.text, dictionary).text,
        "message_truncated": message.truncated,
        "masking": dictionary,
        "last_known_language": language,
    }
    output = {"member_messages": len(messages), "truncated": message.truncated}
    return update, StepReport(kind="tool", input_masked=where, output=output)


async def load_accounts(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    member = _member(state)
    asked = {"tool": "list_member_accounts"}
    try:
        accounts = await run_tool(deps, lambda s: queries.list_member_accounts(s, member))
    except ToolError as error:
        return _data_timeout(asked, error)
    subs = sum(len(account.sub_accounts) for account in accounts)
    output = {"accounts": len(accounts), "sub_accounts": subs}
    return {"accounts": accounts}, StepReport(kind="tool", input_masked=asked, output=output)


async def load_transactions(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    member, last = _member(state), _message_date(state)
    first = last - dt.timedelta(days=TRANSACTIONS_LOOKBACK_DAYS)
    asked = {"tool": "list_transactions", "from": first.isoformat(), "to": last.isoformat()}
    try:
        transactions = await run_tool(
            deps, lambda s: queries.list_transactions(s, member, first, last)
        )
    except ToolError as error:
        return _data_timeout(asked, error)
    output = {"transactions": len(transactions)}
    return {"transactions": transactions}, StepReport(
        kind="tool", input_masked=asked, output=output
    )


async def load_refund_history(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    member = _member(state)
    since = _message_date(state) - dt.timedelta(days=REFUNDS_LOOKBACK_DAYS)
    asked = {"tool": "list_fee_refunds+list_our_refunds", "since": since.isoformat()}

    async def read(session: Any) -> tuple[list[Transaction], Any]:
        core = await queries.list_fee_refunds(session, member, since=since)
        ours = await queries.list_our_refunds(session, member)
        return core, ours

    try:
        core, ours = await run_tool(deps, read)
    except ToolError as error:
        return _data_timeout(asked, error)
    output = {"core_refunds": len(core), "our_refunds": len(ours)}
    update = {"refunds": core, "our_refunds": ours}
    return update, StepReport(kind="tool", input_masked=asked, output=output)


# --- Classification ---


async def triage(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    questions = load_questions(TRIAGE_PROMPT)
    jev_state = {"subject": state.masked_subject or "", "message": state.masked_message or ""}
    asked = {"state": jev_state}
    try:
        classification = await deps.classifier.classify(
            jev_state,
            questions.questions,
            prompt_version=questions.version,
            deadline=deps.deadline,
        )
    except ProviderUnavailable as error:
        result = triage_unavailable(last_known_language=state.last_known_language)
        failed: dict[str, Any] = {"reasons": list(result.reasons)}
        if isinstance(error, ClassifierUnavailable):  # Jev failed, then Luna did too
            failed["fallback"] = {"from": "jev", "reason": error.primary_reason}
        report = StepReport(
            kind="jev",
            input_masked=asked,
            output=failed,
            prompt_version=questions.version,
            error_code=error.reason,
        )
        return {"triage": result}, report

    result = apply_triage_rules(
        classification, last_known_language=state.last_known_language, thresholds=deps.thresholds
    )
    answers = {key: a.model_dump(mode="json") for key, a in classification.answers.items()}
    output: dict[str, Any] = {"answers": answers, "reasons": list(result.reasons)}
    if classification.fallback_reason is not None:
        output["fallback"] = {"from": "jev", "reason": classification.fallback_reason}
    report = StepReport(
        kind="jev" if classification.meta.provider == "jev" else "llm",
        input_masked=asked,
        output=output,
        meta=classification.meta,
        prompt_version=questions.version,
    )
    return {"triage": result}, report


# --- Rules ---


async def identify_fee(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    if ReasonCode.DATA_TIMEOUT in state.reasons:
        return {}, StepReport(kind="rule", output={"skipped": "data_timeout"})
    candidates = find_fee_candidates(state.transactions, _message_at(state))
    asked = {"candidates": [c.id for c in candidates], "pinned": state.pinned_fee_txn_id}

    if state.pinned_fee_txn_id is not None:  # Luis picked it: staff input is trusted
        pinned = next((c for c in candidates if c.id == state.pinned_fee_txn_id), None)
        if pinned is None:
            update: Update = {"candidates": candidates, "reasons": [ReasonCode.FEE_NOT_FOUND]}
            return update, StepReport(kind="rule", input_masked=asked, error_code="invalid_fee")
        found: Update = {"fee": pinned, "fee_source": "staff", "candidates": candidates}
        return found, StepReport(
            kind="rule", input_masked=asked, output=_fee_output(pinned, "staff")
        )

    if len(candidates) == 1:
        fee = candidates[0]
        found = {"fee": fee, "fee_source": "rule", "candidates": candidates}
        return found, StepReport(kind="rule", input_masked=asked, output=_fee_output(fee, "rule"))
    code = ReasonCode.FEE_NOT_FOUND if not candidates else ReasonCode.FEE_AMBIGUOUS
    output = {"reason": code.value}
    return {"candidates": candidates, "reasons": [code]}, StepReport(
        kind="rule", input_masked=asked, output=output
    )


async def run_checks(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    fee, params = _fee(state), deps.policy.params
    same_day = [t for t in state.transactions if t.date == fee.date]
    following = [t for t in state.transactions if t.date > fee.date]
    checks = [
        verify_posting_order(fee, same_day, following),
        check_not_already_refunded(fee, state.our_refunds, state.refunds),
        check_yearly_limit(
            [t.date for t in state.refunds],
            fee.date,
            params.max_refunds_in_window,
            params.window_days,
        ),
        check_good_standing([sub for account in state.accounts for sub in account.sub_accounts]),
        check_approval_limit(-fee.amount, params.staff_limit_usd),
    ]
    output = {"checks": [{"rule": c.rule, "passed": c.passed} for c in checks]}
    return {"checks": checks}, StepReport(
        kind="rule", input_masked={"fee_txn_id": fee.id}, output=output
    )


async def decide_case(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    decision = decide(
        triage=_triage(state),
        fee=state.fee,
        fee_source=state.fee_source,
        checks=state.checks,
        reasons=state.reasons,
        thresholds=deps.thresholds,
    )
    output = {
        "status": decision.status,
        "recommendation": decision.recommendation.model_dump(mode="json"),
        "decisive_rule": decision.decisive_rule,
        "clear": decision.clear,
    }
    return {"decision": decision}, StepReport(kind="rule", output=output)


# --- Policy and reply ---


async def find_policy(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    """D7b: search the clauses with words from the case's facts (never the member's text), let
    Jev pick the one behind the decision, and quote it only when it is the deciding rule's clause
    and Jev is sure. Otherwise, or when anything fails, quote the rule's clause; a disagreement is
    logged as an eval signal. The quote never changes the outcome."""
    decision, fee = _decision(state), state.fee
    clause_id = decision.decisive_clause_id
    if ReasonCode.FEE_QUESTION in decision.reasons and fee:
        clause_id = fee_schedule_clause(fee.fee_type or "")
    if clause_id is None:
        return {}, StepReport(kind="tool", output={"clause_id": None})

    rules = [decision.decisive_rule] if decision.decisive_rule else []
    rules += [check.rule for check in state.checks if check.rule not in rules]
    query = build_policy_query(fee_type=fee.fee_type if fee else None, rules=rules)
    try:
        found = await run_tool(deps, lambda s: search_clauses(s, query))
    except ToolError:
        found = []
    summary = {
        "decision": _decision_sentence(decision, fee),
        "facts": " ".join(_case_facts(state, decision)),
    }
    asked: dict[str, Any] = {"query": query, "state": summary, "options": [c.id for c in found]}
    output: dict[str, Any] = {"search": [c.id for c in found], "clause_id": clause_id}

    meta, chosen, confidence = None, None, None
    if found and deps.ranker is not None:
        prompt = load_choice_prompt(CLAUSE_PROMPT)
        question = ChoiceQuestion(
            key="clause",
            prompt=prompt.prompt,
            options=[Option(key=clause.id, description=clause.text) for clause in found],
        )
        try:
            answer = await deps.ranker.classify(
                summary, [question], prompt_version=prompt.version, deadline=deps.deadline
            )
        except ProviderUnavailable as error:
            output["rerank_error"] = error.reason
        else:
            meta = answer.meta
            pick = answer.answers.get("clause")
            if isinstance(pick, ChoiceAnswer):
                chosen = next((clause for clause in found if clause.id == pick.choice), None)
                confidence = pick.confidence
                output |= {"chosen": pick.choice, "confidence": confidence}

    sure = confidence is not None and confidence >= deps.thresholds.clause_choice_min_confidence
    if chosen is not None and chosen.id == clause_id and sure:
        ref = ClauseRef(**chosen.model_dump(), found_by="search_confirmed")
    else:
        if "chosen" in output:
            log.warning(
                "clause_mismatch",
                expected=clause_id,
                chosen=output["chosen"],
                confidence=confidence,
            )
        try:
            clause = await run_tool(deps, lambda s: get_clause(s, clause_id))
        except ToolError as error:
            failed = StepReport(
                kind="jev" if meta else "tool",
                input_masked=asked,
                output=output,
                meta=meta,
                prompt_version=CLAUSE_PROMPT if meta else None,
                error_code=error.reason,
            )
            return {}, failed
        ref = ClauseRef(**clause.model_dump(), found_by="rule_fallback")

    if "chosen" in output:
        output["mismatch"] = ref.found_by == "rule_fallback"
    output["found_by"] = ref.found_by
    return {"clause": ref}, StepReport(
        kind="jev" if meta else "tool",
        input_masked=asked,
        output=output,
        meta=meta,
        prompt_version=CLAUSE_PROMPT if meta else None,
    )


def _decision_sentence(decision: Decision, fee: Transaction | None) -> str:
    """What was decided, in words, for the clause choice."""
    if fee is None:
        return "No fee was identified."
    what = format_money(-fee.amount) + (f" {fee.fee_type} fee" if fee.fee_type else " fee")
    match decision.recommendation.action:
        case "refund" if ReasonCode.OVER_LIMIT in decision.reasons:
            return f"Refund the {what}, above the staff approval limit."
        case "refund":
            return f"Refund the {what}."
        case "no_refund":
            return f"Don't refund the {what}."
        case _:
            return f"Explain the {what}; no refund was asked for."


async def draft(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    """The reply, by Sol, from the facts only (D2): the member's message is never an input here.
    A reply that fails the post-check is asked for once more; Sol failing, or a second failed
    post-check, gives the template and `drafter_down`, so Luis still has a reply to send."""
    decision, fee, triage_ = _decision(state), _fee(state), _triage(state)
    language: Language = "es" if triage_.language == "es" else "en"
    action = decision.recommendation.action
    amount = -fee.amount
    payload = DraftInput(
        language=language,
        tone=triage_.tone,
        outcome=action,
        amount=f"{amount:.2f}",
        fee_date=fee.date.isoformat(),
        fee_type=fee.fee_type,
        sub_account_name=fee.sub_account_name,
        facts=_case_facts(state, decision),
        policy_clause=state.clause.text if action == "no_refund" and state.clause else None,
    )
    asked = payload.model_dump(mode="json")
    metas: list[CallMeta] = []
    problems: list[Problem] = []
    failure: str | None = None
    for _ in range(DRAFT_TRIES):
        try:
            drafted = await deps.drafter.draft(
                payload,
                instructions=load_prompt(DRAFT_PROMPT),
                prompt_version=DRAFT_PROMPT,
                deadline=deps.deadline,
            )
        except ProviderUnavailable as error:
            failure = error.reason
            break
        metas.append(drafted.meta)
        problems = check_draft(drafted.reply, amount=amount, policy_clause=payload.policy_clause)
        if not problems:
            output = {"source": "model", "chars": len(drafted.reply), "tries": len(metas)}
            return {"draft": DraftReply(text=drafted.reply, source="model")}, StepReport(
                kind="llm",
                input_masked=asked,
                output=output,
                meta=_combined(metas),
                prompt_version=DRAFT_PROMPT,
            )

    template = _template_reply(state, language)
    update: Update = {"reasons": [ReasonCode.DRAFTER_DOWN]}
    if template is not None:
        update["draft"] = DraftReply(text=template, source="template")
    output = {"source": "template" if template else None, "postcheck": list(problems)}
    return update, StepReport(
        kind="llm",
        input_masked=asked,
        output=output,
        meta=_combined(metas) if metas else None,
        prompt_version=DRAFT_PROMPT,
        error_code=failure or "postcheck_failed",
    )


def _case_facts(state: GraphState, decision: Decision) -> list[str]:
    """What happened, as plain sentences, for Sol and the clause choice. The member is never
    named (the reply uses the placeholder). A refund within the limit names no amount, because
    the post-check allows only the decided one; above the limit there is no draft, and the
    sentence says the limit."""
    facts = _merged_facts(state)
    if decision.recommendation.action == "refund":
        status = (
            "needs_supervisor" if ReasonCode.OVER_LIMIT in decision.reasons else "ready_to_refund"
        )
        summary = render_summary(status, facts, "en", first_name=SOMEONE)
        return [summary] if summary else []
    reason = next((c for c in decision.reasons if GROUPS[c] is ReasonGroup.POLICY), None)
    return [render_reason(reason, facts, "en", first_name=SOMEONE).message] if reason else []


def _template_reply(state: GraphState, language: Language) -> str | None:
    """The fallback reply, from the same facts: "refunded", or one per decline reason."""
    decision, fee = _decision(state), _fee(state)
    facts = _merged_facts(state)
    values = {
        "fee_date": format_date(fee.date, language),
        "amount": format_money(-fee.amount),
        "fee_type": fee.fee_type or "service",
        "sub_account_name": fee.sub_account_name,
    }
    if decision.recommendation.action == "refund":
        payroll = facts.get("deposit_kind") == "payroll_deposit"
        values["deposit"] = {
            "en": "your paycheck" if payroll else "your deposit",
            "es": "la nómina" if payroll else "el depósito",
        }[language]
        return render_template("refunded", language, values)

    reason = next((c for c in decision.reasons if GROUPS[c] is ReasonGroup.POLICY), None)
    if reason not in DECLINE_TEMPLATES:
        return None
    refunded_on = facts.get("refunded_on")
    values["max_refunds"] = str(facts.get("max_refunds", ""))
    values["refunded_on"] = (
        format_date(refunded_on, language) if isinstance(refunded_on, dt.date) else ""
    )
    return render_template(f"declined_{reason}", language, values)


def _combined(metas: list[CallMeta]) -> CallMeta:
    """One step, several calls (a post-check retry): the trace keeps all their cost."""
    last = metas[-1]
    costs = [m.cost_usd for m in metas]
    return last.model_copy(
        update={
            "latency_ms": sum(m.latency_ms for m in metas),
            "tokens_in": sum(m.tokens_in for m in metas),
            "tokens_out": sum(m.tokens_out for m in metas),
            "tokens_cached": sum(m.tokens_cached for m in metas),
            "tokens_cache_write": sum(m.tokens_cache_write for m in metas),
            "cost_usd": None if None in costs else sum(c for c in costs if c is not None),
            "attempts": sum(m.attempts for m in metas),
        }
    )


async def finalize(state: GraphState, deps: AgentDeps) -> tuple[Update, StepReport]:
    """Recompute the status with every reason (a reason can appear after `decide`) and build the
    run's `result`, which the runner stores and the API serves."""
    triage_, decision = state.triage, state.decision
    # Luis reads them in this order: what triage saw, what decided the case, then what happened
    # after the decision (a drafter failure).
    codes = list(
        dict.fromkeys(
            [
                *(triage_.reasons if triage_ else ()),
                *((*decision.reasons, *decision.notes) if decision else ()),
                *state.reasons,
            ]
        )
    )
    action = decision.recommendation.action if decision else "none"
    status = case_status(codes, action, about_fee=triage_.about_fee if triage_ else True)
    result = _result(state, status, codes)
    output = {"status": status, "reasons": result["reasons"], "notes": result["notes"]}
    return {"result": result}, StepReport(kind="rule", output=output)


# --- Routing ---


def after_load_conversation(state: GraphState) -> str:
    return "triage" if state.masked_message is not None else "finalize"


def after_triage(state: GraphState) -> list[str] | str:
    return READS if _triage(state).about_fee else "finalize"


def after_identify_fee(state: GraphState) -> str:
    return "run_checks" if state.fee is not None else "finalize"


def after_find_policy(state: GraphState) -> str:
    """Draft only when there is a recommendation to send, to a refund request (or an unknown
    intent), in a language we write. A refund above the limit gets no draft: nothing in this app
    can send it (D-api-1)."""
    decision, triage_ = _decision(state), _triage(state)
    wants_reply = triage_.topic in ("fee_refund_request", None)
    writable = triage_.language in ("en", "es")
    has_outcome = decision.recommendation.action in ("refund", "no_refund")
    over_limit = ReasonCode.OVER_LIMIT in decision.reasons
    return "draft" if has_outcome and wants_reply and writable and not over_limit else "finalize"


# --- Helpers ---


def _since_last_staff_reply(messages: tuple[Message, ...]) -> list[Message]:
    last_staff = max((i for i, m in enumerate(messages) if m.author == "staff"), default=-1)
    recent = [m for m in messages[last_staff + 1 :] if m.author == "member"]
    if recent:
        return recent
    members = [m for m in messages if m.author == "member"]
    return members[-1:]


def _data_timeout(asked: dict[str, Any], error: ToolError) -> tuple[Update, StepReport]:
    report = StepReport(kind="tool", input_masked=asked, error_code=error.reason)
    return {"reasons": [ReasonCode.DATA_TIMEOUT]}, report


def _fee_output(fee: Transaction, source: str) -> dict[str, Any]:
    return {"fee_txn_id": fee.id, "fee_source": source}


def _merged_facts(state: GraphState) -> dict[str, Fact]:
    facts: dict[str, Fact] = {}
    for check in state.checks:
        facts.update(check.facts)
    if state.fee is not None:
        facts["fee_date"] = state.fee.date
    if len(state.candidates) > 1:
        facts["candidate_count"] = len(state.candidates)
    return facts


def _result(state: GraphState, status: str, codes: list[ReasonCode]) -> dict[str, Any]:
    triage_, decision, fee = state.triage, state.decision, state.fee
    recommendation = (
        decision.recommendation.model_dump(mode="json")
        if decision
        else {"action": "none", "amount": None, "fee_txn_id": fee.id if fee else None}
    )
    fee_day = (
        [
            t
            for t in state.transactions
            if t.date == fee.date and t.sub_account_id == fee.sub_account_id
        ]
        if fee
        else []
    )
    clear = bool(decision and decision.clear and status == "ready_to_refund")
    return {
        "status": status,
        "reasons": [c.value for c in codes if GROUPS[c] is not ReasonGroup.NOTE],
        "notes": [c.value for c in codes if GROUPS[c] is ReasonGroup.NOTE],
        "topic": triage_.topic if triage_ else None,
        "language": triage_.language if triage_ else None,
        "tone": triage_.tone if triage_ else None,
        "classifier_used": triage_.classifier_used if triage_ else None,
        "recommendation": recommendation,
        "fee": _txn_json(fee) | {"source": state.fee_source} if fee else None,
        "candidates": [_txn_json(c) for c in state.candidates],
        "facts": _FACTS.dump_python(_merged_facts(state), mode="json"),
        "checks": [
            {
                "rule": c.rule,
                "passed": c.passed,
                "reason": c.reason,
                "clause_id": c.clause_id,
                "facts": _FACTS.dump_python(c.facts, mode="json"),
            }
            for c in state.checks
        ],
        "decisive_rule": decision.decisive_rule if decision else None,
        "clause": state.clause.model_dump(mode="json") if state.clause else None,
        "draft": state.draft.model_dump(mode="json") if state.draft else None,
        "clear": clear,
        "would_auto_approve": clear,
        "evidence": {
            "fee_day": [_txn_json(t) for t in fee_day],
            "refunds": [_txn_json(t) for t in state.refunds],
            "sub_accounts": [
                sub.model_dump(mode="json")
                for account in state.accounts
                for sub in account.sub_accounts
            ],
        },
    }


def _txn_json(txn: Transaction) -> dict[str, Any]:
    return txn.model_dump(mode="json", exclude={"sub_account_id"})


def _member(state: GraphState) -> int:
    if state.member_id is None:
        raise ValueError("the conversation was not loaded")
    return state.member_id


def _message_at(state: GraphState) -> dt.datetime:
    if state.message_at is None:
        raise ValueError("the conversation was not loaded")
    return state.message_at


def _message_date(state: GraphState) -> dt.date:
    return _message_at(state).date()


def _triage(state: GraphState) -> Triage:
    if state.triage is None:
        raise ValueError("triage did not run")
    return state.triage


def _fee(state: GraphState) -> Transaction:
    if state.fee is None:
        raise ValueError("no fee was identified")
    return state.fee


def _decision(state: GraphState) -> Any:
    if state.decision is None:
        raise ValueError("decide did not run")
    return state.decision
