"""The eval report (SPEC-evals, "Output"): a table on stdout, and the same numbers as JSON and
Markdown in `evals/reports/<YYYY-MM-DD>-<mode>`. Every line and file names its mode, and a report
holds statuses, reason codes, check details and call metadata only, never case data such as names.

Latency in live mode is the measured wall clock of each run. In replay mode no model is waited
for, so a case's latency is our code's wall clock plus each model call's recorded time: the time
the same run took live, without retries. Costs are always each call's own (recorded) cost.
"""

import datetime as dt
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from evals.case import Mode
from evals.compare import Comparison, Line
from evals.meter import Call
from evals.scoring import Check

REPORTS_DIR = Path(__file__).resolve().parent / "reports"

MODE_LABEL = {
    "replay": "recorded model answers, not live",
    "live": "live model answers",
}
LATENCY_BASIS = {
    "replay": "our code, plus each model call's recorded time",
    "live": "measured",
}
STEP_ROLES = ("triage", "fee_choice", "clause_choice", "draft")


@dataclass(frozen=True)
class Outcome:
    case_id: str
    kind: str
    skipped: str | None = None  # "not applicable" or "pending review": not counted
    result: dict[str, Any] | None = None
    checks: Sequence[Check] = ()
    wall_ms: int | None = None  # the run, measured around run_case
    calls: Sequence[Call] = ()  # its model calls (see evals/meter.py)

    @property
    def passed(self) -> bool:
        return self.skipped is None and all(check.passed for check in self.checks)


@dataclass(frozen=True)
class Report:
    mode: Mode
    date: dt.date
    policy_version: str
    models: dict[str, str]
    outcomes: Sequence[Outcome]
    classifier: str = "jev"
    recording: bool = False  # a --record run fills missing answers: never a live pass rate
    comparison: Comparison | None = None
    counted: list[Outcome] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "counted", [o for o in self.outcomes if o.skipped is None])

    @property
    def passed(self) -> int:
        return sum(outcome.passed for outcome in self.counted)

    @property
    def pass_rate(self) -> float:
        return self.passed / len(self.counted) if self.counted else 0.0

    @property
    def by_kind(self) -> dict[str, tuple[int, int]]:
        kinds: dict[str, tuple[int, int]] = {}
        for kind in ("refund", "no_refund", "edge"):
            group = [outcome for outcome in self.counted if outcome.kind == kind]
            kinds[kind] = (sum(outcome.passed for outcome in group), len(group))
        return kinds

    @property
    def manual_review_rate(self) -> float:
        """Cases the flow hands to Luis to decide (`needs_your_call`)."""
        manual = sum(_status(outcome) == "needs_your_call" for outcome in self.counted)
        return manual / len(self.counted) if self.counted else 0.0

    @property
    def clear_cases(self) -> int:
        return sum(bool(outcome.result and outcome.result["clear"]) for outcome in self.counted)

    @property
    def latencies(self) -> list[int]:
        values = []
        for outcome in self.counted:
            if outcome.wall_ms is None:
                continue
            recorded = sum(call.meta.latency_ms for call in outcome.calls)
            values.append(outcome.wall_ms + (recorded if self.mode == "replay" else 0))
        return values

    @property
    def cost_per_case(self) -> Decimal | None:
        if not self.counted:
            return None
        totals = [_cost(outcome.calls) for outcome in self.counted]
        return sum(totals, Decimal(0)) / len(totals)

    @property
    def per_step(self) -> dict[str, tuple[int, int, Decimal]]:
        """Each model role: (calls, average latency, average cost)."""
        calls = [call for outcome in self.counted for call in outcome.calls]
        steps = {}
        for role in STEP_ROLES:
            mine = [call for call in calls if call.role == role]
            if mine:
                latency = round(sum(call.meta.latency_ms for call in mine) / len(mine))
                steps[role] = (len(mine), latency, _cost(mine) / len(mine))
        return steps

    @property
    def stem(self) -> str:
        suffix = "-backup" if self.classifier == "backup" else ""
        return f"{self.date.isoformat()}-{self.mode}{suffix}"

    def header(self) -> str:
        label = MODE_LABEL[self.mode]
        if self.recording:
            label = "recording missing answers; not a live pass rate"
        if self.classifier == "backup":
            label += "; triage by the backup classifier"
        models = ", ".join(self.models.values())
        return (
            f"MODE: {self.mode.upper()}  ({label})  {self.date.isoformat()}"
            f"  policy {self.policy_version[:12]}  models {models}"
        )

    def summary_lines(self) -> list[str]:
        kinds = " · ".join(f"{kind} {p}/{n}" for kind, (p, n) in self.by_kind.items())
        skipped = [f"{o.case_id} ({o.skipped})" for o in self.outcomes if o.skipped]
        return [
            self.header(),
            f"Cases: {len(self.counted)}   Passed: {self.passed}   Pass rate: {self.pass_rate:.1%}",
            f"By kind: {kinds}",
            f"Manual-review rate: {self.manual_review_rate:.0%}   Clear cases: {self.clear_cases}",
            *self._cost_and_latency_lines(),
            f"Skipped: {', '.join(skipped) if skipped else 'none'}",
            *(_comparison_lines(self.comparison) if self.comparison else []),
        ]

    def _cost_and_latency_lines(self) -> list[str]:
        lines = []
        p50, p95 = percentile(self.latencies, 0.50), percentile(self.latencies, 0.95)
        if p50 is not None and p95 is not None:
            basis = LATENCY_BASIS[self.mode]
            lines.append(f"Latency p50 / p95: {ms(p50)} / {ms(p95)}   ({basis})")
        if self.cost_per_case is not None:
            lines.append(f"Cost per case: {usd(self.cost_per_case)} (avg)")
        if self.per_step:
            steps = " · ".join(
                f"{role} {ms(latency)} {usd(cost)}"
                for role, (_, latency, cost) in self.per_step.items()
            )
            lines.append(f"Per step (avg): {steps}")
        return lines

    def case_lines(self) -> list[str]:
        tag = f"[{self.mode.upper()}]"
        lines = []
        for outcome in self.outcomes:
            if outcome.skipped:
                lines.append(f"{tag} SKIP  {outcome.case_id}  ({outcome.skipped})")
                continue
            verdict = "PASS" if outcome.passed else "FAIL"
            reasons = ", ".join(outcome.result["reasons"]) if outcome.result else ""
            status = f"{_status(outcome)} ({reasons})" if reasons else _status(outcome)
            lines.append(f"{tag} {verdict}  {outcome.case_id}  {status}")
            lines.extend(
                f"{tag}         {check.name}: {check.detail}"
                for check in outcome.checks
                if not check.passed
            )
        return lines

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "date": self.date.isoformat(),
            "policy_version": self.policy_version,
            "models": self.models,
            "classifier": self.classifier,
            "summary": {
                "cases": len(self.counted),
                "passed": self.passed,
                "pass_rate": round(self.pass_rate, 4),
                "by_kind": {k: {"passed": p, "cases": n} for k, (p, n) in self.by_kind.items()},
                "manual_review_rate": round(self.manual_review_rate, 4),
                "clear_cases": self.clear_cases,
                "latency_ms": {
                    "p50": percentile(self.latencies, 0.50),
                    "p95": percentile(self.latencies, 0.95),
                    "basis": LATENCY_BASIS[self.mode],
                },
                "cost_per_case_usd": _text(self.cost_per_case),
                "per_step": {
                    role: {"calls": calls, "avg_latency_ms": latency, "avg_cost_usd": _text(cost)}
                    for role, (calls, latency, cost) in self.per_step.items()
                },
                "comparison": (
                    [_line_json(line) for line in self.comparison.lines]
                    if self.comparison
                    else None
                ),
            },
            "cases": [_case_json(outcome) for outcome in self.outcomes],
        }

    def to_markdown(self) -> str:
        lines = [f"# Eval report: {self.mode.upper()}, {self.date.isoformat()}", ""]
        lines += [f"    {line}" for line in self.summary_lines()]
        lines += ["", "| Case | Kind | Status | Result |", "|---|---|---|---|"]
        for outcome in self.outcomes:
            verdict = outcome.skipped or ("pass" if outcome.passed else "**fail**")
            status = _status(outcome) or "—"
            lines.append(f"| {outcome.case_id} | {outcome.kind} | {status} | {verdict} |")
        failures = [o for o in self.counted if not o.passed]
        if failures:
            lines += ["", "## Failures", ""]
            for outcome in failures:
                lines += [
                    f"- **{outcome.case_id}**: {check.name}: {check.detail}"
                    for check in outcome.checks
                    if not check.passed
                ]
        return "\n".join(lines) + "\n"

    def write(self, reports_dir: Path = REPORTS_DIR) -> list[Path]:
        reports_dir.mkdir(parents=True, exist_ok=True)
        json_path = reports_dir / f"{self.stem}.json"
        markdown_path = reports_dir / f"{self.stem}.md"
        text = json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n"
        json_path.write_text(text, encoding="utf-8", newline="\n")
        markdown_path.write_text(self.to_markdown(), encoding="utf-8", newline="\n")
        return [json_path, markdown_path]


@dataclass(frozen=True)
class SweepRow:
    value: Decimal
    cases: int
    passed: int
    manual_review_rate: float


@dataclass(frozen=True)
class SweepReport:
    """The threshold sweep (`--sweep`): the replay suite once per value, with no new calls."""

    date: dt.date
    field: str
    current: Decimal
    rows: Sequence[SweepRow]

    @property
    def stem(self) -> str:
        return f"{self.date.isoformat()}-replay-sweep-{self.field}"

    def lines(self) -> list[str]:
        lines = [
            f"MODE: REPLAY  ({MODE_LABEL['replay']})  {self.date.isoformat()}"
            f"  sweep of {self.field}, no new calls",
            "  value   pass rate   manual review",
        ]
        for row in self.rows:
            rate = row.passed / row.cases if row.cases else 0.0
            current = "   (current)" if row.value == self.current else ""
            lines.append(
                f"  {row.value!s:<5}  {rate:>8.1%}  {row.manual_review_rate:>11.0%}{current}"
            )
        return lines

    def to_json(self) -> dict[str, Any]:
        return {
            "mode": "replay",
            "date": self.date.isoformat(),
            "sweep": self.field,
            "current": str(self.current),
            "rows": [
                {
                    "value": str(row.value),
                    "cases": row.cases,
                    "passed": row.passed,
                    "manual_review_rate": round(row.manual_review_rate, 4),
                }
                for row in self.rows
            ],
        }

    def write(self, reports_dir: Path = REPORTS_DIR) -> list[Path]:
        reports_dir.mkdir(parents=True, exist_ok=True)
        json_path = reports_dir / f"{self.stem}.json"
        markdown_path = reports_dir / f"{self.stem}.md"
        text = json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n"
        json_path.write_text(text, encoding="utf-8", newline="\n")
        title = f"# Threshold sweep: {self.field}, {self.date.isoformat()}"
        body = "\n".join([title, "", *(f"    {line}" for line in self.lines())]) + "\n"
        markdown_path.write_text(body, encoding="utf-8", newline="\n")
        return [json_path, markdown_path]


# --- Formatting ---


def percentile(values: Sequence[int], p: float) -> int | None:
    """Nearest rank: the smallest value with at least `p` of the values at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def usd(amount: Decimal) -> str:
    """Two significant digits, as the page shows costs ("$0.000032", "$0.0041", "$1.60")."""
    if amount == 0:
        return "$0"
    places = max(2, 1 - math.floor(math.log10(float(amount))))
    return f"${amount:.{places}f}"


def ms(value: int) -> str:
    return f"{value} ms" if value < 1000 else f"{value / 1000:.1f} s"


def _cost(calls: Sequence[Call]) -> Decimal:
    return sum((c.meta.cost_usd for c in calls if c.meta.cost_usd is not None), Decimal(0))


def _text(amount: Decimal | None) -> str | None:
    return None if amount is None else str(amount)


def _line_cost(line: Line) -> Decimal | None:
    return sum(line.costs, Decimal(0)) / len(line.costs) if line.costs else None


def _line_json(line: Line) -> dict[str, Any]:
    return {
        "classifier": line.name,
        "cases": line.cases,
        "right": line.right,
        "p50_latency_ms": percentile(line.latencies_ms, 0.50),
        "cost_per_case_usd": _text(_line_cost(line)),
        "estimate": line.estimate,
    }


def _comparison_lines(comparison: Comparison) -> list[str]:
    lines = [
        "Classifier comparison (triage only, same cases):",
        "            right   p50 latency   cost / case",
    ]
    for line in comparison.lines:
        cost = _line_cost(line)
        cost_text = usd(cost) if cost is not None else "—"
        if line.estimate:
            note = "  (estimate: Luna's tokens at Sol's prices)"
            lines.append(f"  {line.name:<6}{'not measured':>9}{'—':>11}{cost_text:>14}{note}")
            continue
        latency = percentile(line.latencies_ms, 0.50)
        right = f"{line.right}/{line.cases}"
        latency_text = ms(latency) if latency is not None else "—"
        lines.append(f"  {line.name:<6}{right:>9}{latency_text:>14}{cost_text:>14}")
    lines.append(_savings(comparison))
    return lines


def _savings(comparison: Comparison) -> str:
    by_name = {line.name: line for line in comparison.lines}
    jev, luna, sol = by_name["jev"], by_name["luna"], by_name["sol"]
    jev_cost, luna_cost, sol_cost = _line_cost(jev), _line_cost(luna), _line_cost(sol)
    jev_p50, luna_p50 = percentile(jev.latencies_ms, 0.5), percentile(luna.latencies_ms, 0.5)
    parts = []
    if jev_cost is not None and luna_cost and jev_p50 is not None and luna_p50:
        parts.append(
            f"vs luna {1 - jev_cost / luna_cost:.0%} cost,"
            f" {1 - jev_p50 / luna_p50:.0%} latency (measured)"
        )
    if jev_cost is not None and sol_cost:
        parts.append(f"vs sol ~{1 - jev_cost / sol_cost:.1%} cost (estimated)")
    return "Triage savings of jev: " + (" · ".join(parts) if parts else "not enough answers")


def _status(outcome: Outcome) -> str | None:
    return outcome.result["status"] if outcome.result else None


def _case_json(outcome: Outcome) -> dict[str, Any]:
    result = outcome.result or {}
    clause = result.get("clause")
    draft = result.get("draft")
    return {
        "id": outcome.case_id,
        "kind": outcome.kind,
        "skipped": outcome.skipped,
        "passed": outcome.passed,
        "status": result.get("status"),
        "reasons": result.get("reasons"),
        "notes": result.get("notes"),
        "recommendation": result.get("recommendation"),
        "clause_id": clause["id"] if clause else None,
        "draft_source": draft["source"] if draft else None,
        "failed": [
            {"check": check.name, "detail": check.detail}
            for check in outcome.checks
            if not check.passed
        ],
    }
