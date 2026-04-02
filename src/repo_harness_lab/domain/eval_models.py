from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from repo_harness_lab.domain.run_models import RunRequest, RunSummary
from repo_harness_lab.domain.task_spec import HarnessProfile


@dataclass(frozen=True, slots=True)
class EvalRunConfig:
    label: str
    request: RunRequest
    harness_profile: HarnessProfile = HarnessProfile.CUSTOM


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    task_spec_ref: str
    run_matrix: tuple[EvalRunConfig, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvalSuite:
    suite_id: str
    cases: tuple[EvalCase, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvalTrial:
    trial_id: str
    case_id: str
    run_request: RunRequest
    run_summary: RunSummary | None = None
    harness_profile: HarnessProfile = HarnessProfile.CUSTOM
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AggregateMetric:
    name: str
    value: float
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class ComparisonView:
    name: str
    items: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    trials: tuple[EvalTrial, ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalReport:
    suite_id: str
    case_results: tuple[CaseResult, ...] = ()
    aggregate_metrics: tuple[AggregateMetric, ...] = ()
    comparison_views: tuple[ComparisonView, ...] = ()
