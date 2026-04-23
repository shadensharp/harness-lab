from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Callable

from repo_harness_lab.domain.eval_models import (
    AggregateMetric,
    CaseResult,
    ComparisonView,
    EvalCase,
    EvalReport,
    EvalSuite,
    EvalTrial,
)
from repo_harness_lab.domain.protocols import TaskLoader
from repo_harness_lab.domain.run_models import RunRequest, RunStatus, RunSummary
from repo_harness_lab.domain.task_spec import HarnessProfile, TaskSpec
from repo_harness_lab.shared.failure_hints import pick_failure_hint
from repo_harness_lab.shared.ids import new_id
from repo_harness_lab.tasks.catalog import TaskCatalogEntry, build_task_recommendation
from repo_harness_lab.tasks.intake_preview import build_task_spec_delivery_preview
from repo_harness_lab.shared.profile_comparisons import default_baseline_profile


@dataclass(slots=True)
class SimpleEvalRunner:
    task_loader: TaskLoader
    run_request_executor: Callable[[TaskSpec, RunRequest], RunSummary]

    def run_case(self, case: EvalCase) -> EvalReport:
        result = self._run_case_result(case, suite_id=case.case_id)
        return EvalReport(
            suite_id=case.case_id,
            case_results=(result,),
            aggregate_metrics=self._build_aggregate_metrics((result,)),
            comparison_views=self._build_comparison_views((result,)),
        )

    def run_suite(self, suite: EvalSuite) -> EvalReport:
        case_results = tuple(self._run_case_result(case, suite_id=suite.suite_id) for case in suite.cases)
        return EvalReport(
            suite_id=suite.suite_id,
            case_results=case_results,
            aggregate_metrics=self._build_aggregate_metrics(case_results),
            comparison_views=self._build_comparison_views(case_results),
        )

    def _run_case_result(self, case: EvalCase, *, suite_id: str) -> CaseResult:
        task = self.task_loader.load(case.task_spec_ref)
        benchmark = task.benchmark_metadata
        recommendation = build_task_recommendation(TaskCatalogEntry(path=Path(case.task_spec_ref), task=task))
        active_profiles = tuple(dict.fromkeys(config.harness_profile.value for config in case.run_matrix))
        delivery_preview = (
            build_task_spec_delivery_preview(task, source_path=Path(case.task_spec_ref))
            if _should_include_profile_delivery_preview(active_profiles)
            else {}
        )
        trials: list[EvalTrial] = []
        durations: list[int] = []
        passed = 0
        status_counts: Counter[str] = Counter()
        verifier_outcomes: Counter[str] = Counter()

        for index, config in enumerate(case.run_matrix, start=1):
            request = self._prepare_request(
                task,
                config.request,
                suite_id=suite_id,
                case=case,
                label=config.label,
                harness_profile=config.harness_profile,
            )
            summary = self.run_request_executor(task, request)
            status_counts[summary.status.value] += 1
            if summary.verifier_outcome:
                verifier_outcomes[summary.verifier_outcome] += 1
            if summary.duration_ms is not None:
                durations.append(summary.duration_ms)
            if summary.status is RunStatus.SUCCEEDED:
                passed += 1
            trials.append(
                EvalTrial(
                    trial_id=f"{case.case_id}-trial-{index}",
                    case_id=case.case_id,
                    run_request=request,
                    run_summary=summary,
                    harness_profile=config.harness_profile,
                    notes=(config.label,),
                )
            )

        total = len(trials)
        pass_rate = (passed / total) if total else 0.0
        summary = {
            "task_spec_ref": case.task_spec_ref,
            "task_title": task.title,
            "task_description": task.description,
            "trial_count": total,
            "passed_trials": passed,
            "pass_rate": pass_rate,
            "average_duration_ms": _mean(durations),
            "median_duration_ms": _median(durations),
            "status_counts": dict(sorted(status_counts.items())),
            "verifier_outcomes": dict(sorted(verifier_outcomes.items())),
            "benchmark_tier": benchmark.tier.value,
            "difficulty": benchmark.difficulty.value,
            "task_tags": list(benchmark.tags),
            "harness_signals": list(benchmark.harness_signals),
            "recommendation_score": recommendation.score,
            "recommendation_reasons": list(recommendation.reasons),
            "comparison_mode": "profile_matrix" if delivery_preview else "current_vs_baseline",
            "notes": list(case.notes),
        }
        if delivery_preview:
            summary["shared_task_information"] = delivery_preview.get("shared_task_information", {})
            summary["harness_delivery_matrix"] = delivery_preview.get("harness_delivery_matrix", {})
            summary["profile_delta_summary"] = delivery_preview.get("profile_delta_summary", ())
        return CaseResult(case_id=case.case_id, trials=tuple(trials), summary=summary)

    def _prepare_request(
        self,
        task: TaskSpec,
        request: RunRequest,
        *,
        suite_id: str,
        case: EvalCase,
        label: str,
        harness_profile: HarnessProfile,
    ) -> RunRequest:
        labels = tuple(
            dict.fromkeys(
                (
                    *request.labels,
                    f"eval_suite:{suite_id}",
                    f"eval_case:{case.case_id}",
                    f"eval_label:{label}",
                    f"harness_profile:{harness_profile.value}",
                )
            )
        )
        metadata = dict(request.metadata)
        metadata["eval_context"] = {
            "suite_id": suite_id,
            "case_id": case.case_id,
            "label": label,
            "harness_profile": harness_profile.value,
        }
        return replace(
            request,
            run_id=request.run_id or new_id("run"),
            task_id=request.task_id or task.task_id,
            labels=labels,
            metadata=metadata,
        )

    def _build_aggregate_metrics(self, case_results: tuple[CaseResult, ...]) -> tuple[AggregateMetric, ...]:
        trials = [trial for case_result in case_results for trial in case_result.trials]
        succeeded_trials = sum(
            1
            for trial in trials
            if trial.run_summary is not None and trial.run_summary.status is RunStatus.SUCCEEDED
        )
        durations = [
            trial.run_summary.duration_ms
            for trial in trials
            if trial.run_summary is not None and trial.run_summary.duration_ms is not None
        ]
        total_trials = len(trials)
        pass_rate = (succeeded_trials / total_trials) if total_trials else 0.0
        return (
            AggregateMetric(name="total_cases", value=float(len(case_results)), unit="count"),
            AggregateMetric(name="total_trials", value=float(total_trials), unit="count"),
            AggregateMetric(name="pass_rate", value=pass_rate, unit="ratio"),
            AggregateMetric(name="average_duration_ms", value=float(_mean(durations) or 0), unit="ms"),
            AggregateMetric(name="median_duration_ms", value=float(_median(durations) or 0), unit="ms"),
        )

    def _build_comparison_views(self, case_results: tuple[CaseResult, ...]) -> tuple[ComparisonView, ...]:
        by_label: dict[str, dict[str, object]] = {}
        by_case: dict[str, dict[str, object]] = {}
        by_profile: dict[str, dict[str, object]] = {}
        by_profile_failure: dict[str, dict[str, object]] = defaultdict(
            lambda: {"failed_trials": 0, "reasons": defaultdict(lambda: {"count": 0, "run_ids": []})}
        )
        by_tag: dict[str, dict[str, object]] = defaultdict(lambda: {"case_ids": [], "profiles": {}})
        by_signal: dict[str, dict[str, object]] = defaultdict(lambda: {"case_ids": [], "profiles": {}})

        for case_result in case_results:
            by_case[case_result.case_id] = dict(case_result.summary)
            task_tags = tuple(case_result.summary.get("task_tags", ()))
            harness_signals = tuple(case_result.summary.get("harness_signals", ()))
            profile_case_metrics = self._case_profile_metrics(case_result)

            for trial in case_result.trials:
                label = trial.notes[0] if trial.notes else "<unlabeled>"
                label_item = by_label.setdefault(
                    label,
                    {
                        "total_trials": 0,
                        "passed_trials": 0,
                        "pass_rate": 0.0,
                        "average_duration_ms": None,
                        "run_ids": [],
                        "harness_profile": trial.harness_profile.value,
                    },
                )
                _accumulate_trial(label_item, trial)

                profile_item = by_profile.setdefault(
                    trial.harness_profile.value,
                    {
                        "total_trials": 0,
                        "passed_trials": 0,
                        "pass_rate": 0.0,
                        "average_duration_ms": None,
                        "run_ids": [],
                    },
                )
                _accumulate_trial(profile_item, trial)

                failure_hint = _trial_failure_hint(trial.run_summary)
                if failure_hint is not None and trial.run_summary is not None:
                    failure_bucket = by_profile_failure[trial.harness_profile.value]
                    failure_bucket["failed_trials"] = int(failure_bucket["failed_trials"]) + 1
                    reason_bucket = failure_bucket["reasons"][failure_hint]
                    reason_bucket["count"] = int(reason_bucket["count"]) + 1
                    reason_bucket["run_ids"] = [*reason_bucket["run_ids"], trial.run_summary.run_id]

            for tag in task_tags:
                tag_item = by_tag[tag]
                tag_item["case_ids"] = sorted({*tag_item["case_ids"], case_result.case_id})
                _merge_case_profile_metrics(tag_item["profiles"], profile_case_metrics)

            for signal in harness_signals:
                signal_item = by_signal[signal]
                signal_item["case_ids"] = sorted({*signal_item["case_ids"], case_result.case_id})
                _merge_case_profile_metrics(signal_item["profiles"], profile_case_metrics)

        for item in by_label.values():
            _finalize_trial_metrics(item)
        for item in by_profile.values():
            _finalize_trial_metrics(item)
        for collection in (by_tag, by_signal):
            for item in collection.values():
                for profile_item in item["profiles"].values():
                    _finalize_case_metrics(profile_item)

        return (
            ComparisonView(name="case_summary", items=by_case),
            ComparisonView(name="label_summary", items=by_label),
            ComparisonView(name="profile_summary", items=by_profile),
            ComparisonView(name="profile_uplift", items=self._build_profile_uplift(by_profile)),
            ComparisonView(name="profile_failure_summary", items=_finalize_profile_failure_summary(by_profile_failure)),
            ComparisonView(name="tag_profile_summary", items=dict(sorted(by_tag.items()))),
            ComparisonView(name="signal_profile_summary", items=dict(sorted(by_signal.items()))),
        )

    def _case_profile_metrics(self, case_result: CaseResult) -> dict[str, dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for trial in case_result.trials:
            profile_item = grouped.setdefault(
                trial.harness_profile.value,
                {
                    "case_count": 0,
                    "pass_rate_total": 0.0,
                    "duration_values": [],
                },
            )
            succeeded = (
                trial.run_summary is not None and trial.run_summary.status is RunStatus.SUCCEEDED
            )
            profile_item["case_count"] = int(profile_item["case_count"]) + 1
            profile_item["pass_rate_total"] = float(profile_item["pass_rate_total"]) + (1.0 if succeeded else 0.0)
            if trial.run_summary is not None and trial.run_summary.duration_ms is not None:
                profile_item["duration_values"] = [*profile_item["duration_values"], trial.run_summary.duration_ms]
        return grouped

    def _build_profile_uplift(self, by_profile: dict[str, dict[str, object]]) -> dict[str, object]:
        if not by_profile:
            return {}
        baseline_profile = default_baseline_profile(by_profile.keys())
        baseline = by_profile[baseline_profile]
        uplift: dict[str, object] = {"baseline_profile": baseline_profile}
        for profile_name, item in sorted(by_profile.items()):
            uplift[profile_name] = {
                "pass_rate": item["pass_rate"],
                "pass_rate_delta": float(item["pass_rate"]) - float(baseline["pass_rate"]),
                "average_duration_ms": item["average_duration_ms"],
                "average_duration_delta_ms": _delta_number(item["average_duration_ms"], baseline["average_duration_ms"]),
                "passed_trials": item["passed_trials"],
                "total_trials": item["total_trials"],
            }
        return uplift



def _accumulate_trial(bucket: dict[str, object], trial: EvalTrial) -> None:
    bucket["total_trials"] = int(bucket["total_trials"]) + 1
    if trial.run_summary is not None and trial.run_summary.status is RunStatus.SUCCEEDED:
        bucket["passed_trials"] = int(bucket["passed_trials"]) + 1
    if trial.run_summary is not None:
        bucket["run_ids"] = [*bucket["run_ids"], trial.run_summary.run_id]
        duration_values = list(bucket.get("duration_values", ()))
        if trial.run_summary.duration_ms is not None:
            duration_values.append(trial.run_summary.duration_ms)
        bucket["duration_values"] = duration_values



def _finalize_trial_metrics(bucket: dict[str, object]) -> None:
    total_trials = int(bucket["total_trials"])
    passed_trials = int(bucket["passed_trials"])
    duration_values = list(bucket.pop("duration_values", ()))
    bucket["pass_rate"] = (passed_trials / total_trials) if total_trials else 0.0
    bucket["average_duration_ms"] = _mean(duration_values)
    bucket["median_duration_ms"] = _median(duration_values)



def _merge_case_profile_metrics(target: dict[str, dict[str, object]], source: dict[str, dict[str, object]]) -> None:
    for profile_name, item in source.items():
        target_item = target.setdefault(
            profile_name,
            {
                "case_count": 0,
                "pass_rate_total": 0.0,
                "duration_values": [],
            },
        )
        target_item["case_count"] = int(target_item["case_count"]) + 1
        target_item["pass_rate_total"] = float(target_item["pass_rate_total"]) + (
            float(item["pass_rate_total"]) / int(item["case_count"])
        )
        target_item["duration_values"] = [*target_item["duration_values"], *item["duration_values"]]



def _finalize_case_metrics(bucket: dict[str, object]) -> None:
    case_count = int(bucket["case_count"])
    duration_values = list(bucket.pop("duration_values", ()))
    bucket["average_case_pass_rate"] = (float(bucket["pass_rate_total"]) / case_count) if case_count else 0.0
    bucket["average_duration_ms"] = _mean(duration_values)
    bucket["median_duration_ms"] = _median(duration_values)
    bucket.pop("pass_rate_total", None)



def _trial_failure_hint(summary: RunSummary | None) -> str | None:
    if summary is None or summary.status is RunStatus.SUCCEEDED:
        return None
    return pick_failure_hint(summary)



def _finalize_profile_failure_summary(
    by_profile_failure: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for profile_name, item in sorted(by_profile_failure.items()):
        reasons = item["reasons"]
        sorted_reasons = sorted(
            reasons.items(),
            key=lambda pair: (-int(pair[1]["count"]), pair[0]),
        )
        summary[profile_name] = {
            "failed_trials": int(item["failed_trials"]),
            "top_reasons": [
                {
                    "reason": reason,
                    "count": int(reason_item["count"]),
                    "run_ids": list(dict.fromkeys(reason_item["run_ids"])),
                }
                for reason, reason_item in sorted_reasons[:3]
            ],
        }
    return summary



def _delta_number(value: object, baseline: object) -> float | None:
    if value is None or baseline is None:
        return None
    return float(value) - float(baseline)



def _mean(values: list[int] | list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)



def _median(values: list[int] | list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _should_include_profile_delivery_preview(profile_names: tuple[str, ...]) -> bool:
    supported_profiles = {
        HarnessProfile.CURRENT.value,
        HarnessProfile.CUSTOM.value,
    }
    return bool(profile_names) and any(profile in supported_profiles for profile in profile_names)


