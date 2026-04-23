from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class OfficialBenchmarkProfileReport:
    harness_profile: str
    model_name_or_path: str
    run_id: str
    submitted_instances: int
    completed_instances: int | None = None
    resolved_instances: int | None = None
    unresolved_instances: int | None = None
    error_instances: int | None = None
    empty_patch_instances: int | None = None
    incomplete_instances: int | None = None
    resolution_rate: float | None = None
    predictions_path: str = ""
    command: tuple[str, ...] = ()
    command_exit_code: int | None = None
    results_path: str | None = None
    instance_results_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    submitted_ids: tuple[str, ...] = ()
    resolved_ids: tuple[str, ...] = ()
    unresolved_ids: tuple[str, ...] = ()
    error_ids: tuple[str, ...] = ()
    empty_patch_ids: tuple[str, ...] = ()
    incomplete_ids: tuple[str, ...] = ()
    raw_summary: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OfficialBenchmarkEvaluationReport:
    benchmark_kind: str
    source_report_id: str
    dataset_name: str
    split: str = "test"
    official_runner: str = ""
    notes: tuple[str, ...] = ()
    profile_reports: tuple[OfficialBenchmarkProfileReport, ...] = ()
