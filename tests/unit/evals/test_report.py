"""The report's numbers (SPEC-evals, "Output"; AC5): cost per case and per step, p50 and p95,
the classifier comparison with Sol marked as an estimate, and the threshold sweep."""

import datetime as dt
from decimal import Decimal

import pytest

from backend.agents.triage_rules import THRESHOLDS
from backend.providers.types import CallMeta
from evals.compare import Comparison, Line
from evals.meter import Call
from evals.report import Outcome, Report, SweepReport, SweepRow, ms, percentile, usd
from evals.run import parse_sweep

DATE = dt.date(2026, 10, 4)
MODELS = {"jev": "jev-1.13.0", "luna": "gpt-6-luna", "sol": "gpt-6.1-sol"}


def call(case_id: str, role: str, latency_ms: int, cost: str | None) -> Call:
    meta = CallMeta(
        provider="openai" if role == "draft" else "jev",
        model="gpt-6.1-sol" if role == "draft" else "jev-1.13.0",
        mode="replay",
        latency_ms=latency_ms,
        tokens_in=100,
        tokens_out=10,
        cost_usd=Decimal(cost) if cost is not None else None,
        attempts=1,
    )
    return Call(case_id=case_id, role=role, meta=meta)


def outcome(case_id: str, wall_ms: int, *calls: Call, status: str = "ready_to_refund") -> Outcome:
    return Outcome(
        case_id,
        "refund",
        result={"status": status, "reasons": [], "clear": False},
        checks=(),
        wall_ms=wall_ms,
        calls=calls,
    )


def report(*outcomes: Outcome, mode: str = "replay", **extra: object) -> Report:
    return Report(
        mode=mode,  # type: ignore[arg-type]
        date=DATE,
        policy_version="0ad3a26dcd79",
        models=MODELS,
        outcomes=outcomes,
        **extra,  # type: ignore[arg-type]
    )


ANA = outcome(
    "a",
    100,
    call("a", "triage", 400, "0.000008"),
    call("a", "draft", 1500, "0.004"),
)
BEN = outcome(
    "b",
    200,
    call("b", "triage", 600, "0.000012"),
    call("b", "fee_choice", 300, "0.000004"),
    call("b", "draft", 2500, "0.006"),
)


def test_percentiles_are_nearest_rank() -> None:
    values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]

    assert (percentile(values, 0.50), percentile(values, 0.95)) == (500, 1000)
    assert percentile([], 0.5) is None


@pytest.mark.parametrize(
    ("amount", "text"),
    [("0", "$0"), ("0.0000326", "$0.000033"), ("0.0041", "$0.0041"), ("1.6", "$1.60")],
)
def test_costs_keep_two_significant_digits(amount: str, text: str) -> None:
    assert usd(Decimal(amount)) == text


def test_latencies_read_in_ms_then_seconds() -> None:
    assert (ms(140), ms(1600)) == ("140 ms", "1.6 s")


def test_in_replay_a_cases_latency_adds_each_calls_recorded_time() -> None:
    replay = report(ANA, BEN)

    assert replay.latencies == [100 + 400 + 1500, 200 + 600 + 300 + 2500]


def test_in_live_mode_a_cases_latency_is_the_measured_wall_clock() -> None:
    assert report(ANA, BEN, mode="live").latencies == [100, 200]


def test_cost_per_case_is_the_average_of_each_cases_calls() -> None:
    assert report(ANA, BEN).cost_per_case == (Decimal("0.004008") + Decimal("0.006016")) / 2


def test_per_step_averages_each_role_over_its_calls() -> None:
    steps = report(ANA, BEN).per_step

    assert list(steps) == ["triage", "fee_choice", "draft"]
    assert steps["triage"] == (2, 500, Decimal("0.00001"))
    assert steps["fee_choice"] == (1, 300, Decimal("0.000004"))


def test_the_summary_prints_latency_cost_and_steps() -> None:
    lines = report(ANA, BEN).summary_lines()

    assert (
        "Latency p50 / p95: 2.0 s / 3.6 s   (our code, plus each model call's recorded time)"
        in lines
    )
    assert "Cost per case: $0.0050 (avg)" in lines
    assert (
        "Per step (avg): triage 500 ms $0.000010 · fee_choice 300 ms $0.0000040"
        " · draft 2.0 s $0.0050"
    ) in lines


COMPARISON = Comparison(
    [
        Line("jev", 2, 2, [400, 600], [Decimal("0.000008"), Decimal("0.000012")]),
        Line("luna", 2, 1, [800, 1200], [Decimal("0.00002"), Decimal("0.00002")]),
        Line("sol", 2, None, [], [Decimal("0.003"), Decimal("0.003")], estimate=True),
    ]
)


def test_the_comparison_measures_jev_and_luna_and_estimates_sol() -> None:
    lines = report(ANA, BEN, comparison=COMPARISON).summary_lines()

    table = lines[lines.index("Classifier comparison (triage only, same cases):") :]
    assert table[1:5] == [
        "            right   p50 latency   cost / case",
        "  jev         2/2        400 ms     $0.000010",
        "  luna        1/2        800 ms     $0.000020",
        "  sol   not measured          —       $0.0030  (estimate: Luna's tokens at Sol's prices)",
    ]
    assert table[5] == (
        "Triage savings of jev: vs luna 50% cost, 50% latency (measured)"
        " · vs sol ~99.7% cost (estimated)"
    )


def test_the_json_report_holds_the_new_numbers() -> None:
    summary = report(ANA, BEN, comparison=COMPARISON).to_json()["summary"]

    assert summary["latency_ms"] == {
        "p50": 2000,
        "p95": 3600,
        "basis": "our code, plus each model call's recorded time",
    }
    assert summary["cost_per_case_usd"] == "0.005012"
    assert summary["per_step"]["draft"] == {
        "calls": 2,
        "avg_latency_ms": 2000,
        "avg_cost_usd": "0.005",
    }
    assert summary["comparison"][2] == {
        "classifier": "sol",
        "cases": 2,
        "right": None,
        "p50_latency_ms": None,
        "cost_per_case_usd": "0.003",
        "estimate": True,
    }


# --- The threshold sweep ---


def test_a_sweep_names_a_threshold_and_a_range() -> None:
    field, values = parse_sweep("intent=0.60:0.95:0.05")

    assert field == "intent_min_confidence"
    assert values == [
        Decimal("0.60"),
        Decimal("0.65"),
        Decimal("0.70"),
        Decimal("0.75"),
        Decimal("0.80"),
        Decimal("0.85"),
        Decimal("0.90"),
        Decimal("0.95"),
    ]
    assert parse_sweep("manipulation=0.10:0.20:0.05")[0] == "manipulation_clear_max_p_yes"


@pytest.mark.parametrize("spec", ["nothing=0.1:0.2:0.1", "intent=0.9:0.6:0.1", "intent"])
def test_a_bad_sweep_is_refused(spec: str) -> None:
    with pytest.raises(ValueError, match="sweep"):
        parse_sweep(spec)


def test_the_sweep_table_marks_the_current_value() -> None:
    sweep = SweepReport(
        date=DATE,
        field="intent_min_confidence",
        current=Decimal(str(THRESHOLDS.intent_min_confidence)),
        rows=[
            SweepRow(Decimal("0.75"), cases=37, passed=36, manual_review_rate=0.41),
            SweepRow(Decimal("0.80"), cases=37, passed=37, manual_review_rate=0.43),
        ],
    )

    assert sweep.lines() == [
        "MODE: REPLAY  (recorded model answers, not live)  2026-10-04"
        "  sweep of intent_min_confidence, no new calls",
        "  value   pass rate   manual review",
        "  0.75      97.3%          41%",
        "  0.80     100.0%          43%   (current)",
    ]
