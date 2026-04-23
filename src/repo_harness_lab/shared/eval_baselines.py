from __future__ import annotations

from typing import Mapping, Sequence

from repo_harness_lab.domain.eval_models import ComparisonView, EvalReport
from repo_harness_lab.storage.run_store import StoredEvalCase, StoredEvalReport

BASELINE_KIND_HISTORICAL = "historical"
BASELINE_KIND_CUSTOM = "custom"


def build_report_baseline_view(
    *,
    current_report: EvalReport,
    baseline_report: StoredEvalReport,
    baseline_kind: str,
) -> ComparisonView:
    current_metrics = _metric_map(current_report)
    baseline_metrics = {
        "pass_rate": _optional_float(baseline_report.aggregate_metrics.get("pass_rate")),
        "average_duration_ms": _optional_float(baseline_report.aggregate_metrics.get("average_duration_ms")),
        "total_cases": _optional_float(baseline_report.aggregate_metrics.get("total_cases")),
        "total_trials": _optional_float(baseline_report.aggregate_metrics.get("total_trials")),
    }
    current_cases = _current_case_pass_rates(current_report.case_results)
    baseline_cases = _baseline_case_pass_rates(baseline_report.case_results)
    matched_case_ids = sorted(set(current_cases) & set(baseline_cases))
    improved_case_ids = tuple(
        case_id for case_id in matched_case_ids if _delta(current_cases[case_id], baseline_cases[case_id]) > 0
    )
    regressed_case_ids = tuple(
        case_id for case_id in matched_case_ids if _delta(current_cases[case_id], baseline_cases[case_id]) < 0
    )
    unchanged_case_count = sum(
        1 for case_id in matched_case_ids if _delta(current_cases[case_id], baseline_cases[case_id]) == 0
    )
    return ComparisonView(
        name="report_baseline",
        items={
            "baseline_kind": baseline_kind,
            "baseline_report_id": baseline_report.report_id,
            "baseline_title": baseline_report.title,
            "baseline_suite_id": baseline_report.suite_id,
            "current_suite_id": current_report.suite_id,
            "current_pass_rate": current_metrics["pass_rate"],
            "baseline_pass_rate": baseline_metrics["pass_rate"],
            "pass_rate_delta": _delta(current_metrics["pass_rate"], baseline_metrics["pass_rate"]),
            "current_average_duration_ms": current_metrics["average_duration_ms"],
            "baseline_average_duration_ms": baseline_metrics["average_duration_ms"],
            "average_duration_delta_ms": _delta(
                current_metrics["average_duration_ms"],
                baseline_metrics["average_duration_ms"],
            ),
            "current_total_cases": current_metrics["total_cases"],
            "baseline_total_cases": baseline_metrics["total_cases"],
            "current_total_trials": current_metrics["total_trials"],
            "baseline_total_trials": baseline_metrics["total_trials"],
            "matched_case_count": len(matched_case_ids),
            "improved_case_ids": improved_case_ids,
            "regressed_case_ids": regressed_case_ids,
            "unchanged_case_count": unchanged_case_count,
            "current_only_case_ids": tuple(sorted(set(current_cases) - set(baseline_cases))),
            "baseline_only_case_ids": tuple(sorted(set(baseline_cases) - set(current_cases))),
        },
    )


def _metric_map(report: EvalReport) -> dict[str, float | None]:
    items = {metric.name: _optional_float(metric.value) for metric in report.aggregate_metrics}
    return {
        "pass_rate": items.get("pass_rate"),
        "average_duration_ms": items.get("average_duration_ms"),
        "total_cases": items.get("total_cases"),
        "total_trials": items.get("total_trials"),
    }


def _current_case_pass_rates(case_results: Sequence[object]) -> dict[str, float]:
    result: dict[str, float] = {}
    for case in case_results:
        summary = getattr(case, "summary", {})
        if not isinstance(summary, Mapping):
            summary = {}
        case_id = str(getattr(case, "case_id", "")).strip()
        if not case_id:
            continue
        result[case_id] = float(summary.get("pass_rate", 0.0) or 0.0)
    return result


def _baseline_case_pass_rates(case_results: Sequence[StoredEvalCase]) -> dict[str, float]:
    result: dict[str, float] = {}
    for case in case_results:
        summary = dict(case.summary) if isinstance(case.summary, Mapping) else {}
        case_id = str(case.case_id).strip()
        if not case_id:
            continue
        result[case_id] = float(summary.get("pass_rate", 0.0) or 0.0)
    return result


def _delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return float(current) - float(baseline)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
