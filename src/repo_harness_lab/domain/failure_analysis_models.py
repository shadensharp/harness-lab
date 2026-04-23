from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class FailureAnalysisItem:
    instance_id: str
    task_id: str
    harness_profile: str
    official_status: str
    main_label: str
    stage: str
    key_evidence: tuple[str, ...] = ()
    probable_cause: str = "原因未知"
    cause_confidence: str = "低"
    run_status: str | None = None
    verifier_outcome: str | None = None
    changed_files: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    signals: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FailureAnalysisProfileReport:
    harness_profile: str
    failed_instances: int
    label_counts: Mapping[str, int] = field(default_factory=dict)
    probable_cause_counts: Mapping[str, int] = field(default_factory=dict)
    items: tuple[FailureAnalysisItem, ...] = ()


@dataclass(frozen=True, slots=True)
class FailureAnalysisReport:
    benchmark_kind: str
    source_report_id: str
    dataset_name: str
    notes: tuple[str, ...] = ()
    total_failed_instances: int = 0
    label_counts: Mapping[str, int] = field(default_factory=dict)
    probable_cause_counts: Mapping[str, int] = field(default_factory=dict)
    profile_reports: tuple[FailureAnalysisProfileReport, ...] = ()
