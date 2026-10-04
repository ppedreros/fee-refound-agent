"""The classifier comparison (SPEC-evals, "Classifier comparison"): triage only, same cases.

For every counted case Jev classified in the run, the backup (Luna) is asked exactly what Jev was
asked: in replay mode from its recordings, in live mode for real. Both answers go through the
same triage rules. A verdict is right when it would route the case as expected: the case's triage
reason codes are all there, a case that should not need Luis gets no extra one, and the topic and
language match where the case states them.

Sol is never called as a classifier (customer text never reaches the drafter). Its line is an
estimate: Luna's token counts (the same tokenizer), priced at Sol's rates, with no accuracy.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from backend.agents.triage_rules import Thresholds, Triage, apply_triage_rules
from backend.policy.reasons import ReasonCode
from backend.providers.config import providers_config
from backend.providers.cost import Usage, compute_cost
from backend.providers.types import CallMeta, Classification, Classifier, ProviderUnavailable
from evals.case import EvalCase, Expected
from evals.meter import Call

TRIAGE_CODES = frozenset(
    {
        ReasonCode.INTENT_UNCLEAR,
        ReasonCode.NOT_FEE_REQUEST,
        ReasonCode.FEE_QUESTION,
        ReasonCode.LANGUAGE_UNSUPPORTED,
        ReasonCode.MANIPULATION,
        ReasonCode.MULTIPLE_REQUESTS,
    }
)


@dataclass(frozen=True)
class Line:
    name: str
    cases: int
    right: int | None  # None: not measured (the Sol estimate)
    latencies_ms: Sequence[int]
    costs: Sequence[Decimal]
    estimate: bool = False


@dataclass(frozen=True)
class Comparison:
    lines: Sequence[Line]


def triage_is_right(expected: Expected, triage: Triage) -> bool:
    written = expected.model_fields_set
    if "topic" in written and triage.topic != expected.topic:
        return False
    if "language" in written and triage.language != expected.language:
        return False
    wanted = {code for code in expected.reasons_include if code in TRIAGE_CODES}
    got = {code for code in triage.reasons if code in TRIAGE_CODES}
    if not wanted <= got:
        return False
    # Any triage code sends a case to Luis (or out of the fee flow): only those that should
    # need him may get one the case didn't name.
    needs_luis = expected.status in (None, "needs_your_call")
    return needs_luis or got == wanted


async def compare(
    cases: Sequence[EvalCase],
    calls: Sequence[Call],
    backup_for: Callable[[EvalCase], Classifier],
    thresholds: Thresholds,
) -> Comparison:
    jev = Line("jev", 0, 0, [], [])
    luna = Line("luna", 0, 0, [], [])
    sol_costs: list[Decimal] = []
    by_id = {case.id: case for case in cases}
    for call in calls:
        case = by_id.get(call.case_id)
        if case is None or call.asked is None or call.answer is None:
            continue  # not a counted case, or not a triage call
        if call.meta.provider != "jev":
            continue  # Jev didn't answer this case's triage: nothing to compare
        jev = _add(jev, case.expected, _verdict(call.answer, thresholds), call.meta)
        try:
            answer = await backup_for(case).classify(
                call.asked.state, call.asked.questions, prompt_version=call.asked.prompt_version
            )
        except ProviderUnavailable:
            luna = _add(luna, case.expected, None, None)  # no answer counts as wrong
            continue
        luna = _add(luna, case.expected, _verdict(answer, thresholds), answer.meta)
        sol_costs.append(_priced_as_sol(answer.meta))
    sol = Line("sol", luna.cases, None, [], sol_costs, estimate=True)
    return Comparison([jev, luna, sol])


def _verdict(answer: Classification, thresholds: Thresholds) -> Triage:
    return apply_triage_rules(answer, last_known_language=None, thresholds=thresholds)


def _add(line: Line, expected: Expected, triage: Triage | None, meta: CallMeta | None) -> Line:
    right = triage is not None and triage_is_right(expected, triage)
    return Line(
        line.name,
        line.cases + 1,
        (line.right or 0) + right,
        [*line.latencies_ms, meta.latency_ms] if meta else line.latencies_ms,
        [*line.costs, meta.cost_usd] if meta and meta.cost_usd is not None else line.costs,
    )


def _priced_as_sol(meta: CallMeta) -> Decimal:
    usage = Usage(meta.tokens_in, meta.tokens_out, meta.tokens_cached, meta.tokens_cache_write)
    return compute_cost(providers_config().sol.model, usage) or Decimal(0)
