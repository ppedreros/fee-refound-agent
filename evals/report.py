"""The eval report (SPEC-evals, "Output"): a table on stdout, and the same numbers as JSON and
Markdown in `evals/reports/<YYYY-MM-DD>-<mode>`. Every line and file names its mode, and a report
holds statuses, reason codes and check details only, never case data such as names.
"""

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.case import Mode
from evals.scoring import Check

REPORTS_DIR = Path(__file__).resolve().parent / "reports"

MODE_LABEL = {
    "replay": "recorded model answers, not live",
    "live": "live model answers",
}


@dataclass(frozen=True)
class Outcome:
    case_id: str
    kind: str
    skipped: str | None = None  # "not applicable" or "pending review": not counted
    result: dict[str, Any] | None = None
    checks: Sequence[Check] = ()

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
            f"Skipped: {', '.join(skipped) if skipped else 'none'}",
        ]

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
