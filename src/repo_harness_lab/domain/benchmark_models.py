from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from repo_harness_lab.domain.task_spec import TaskSpec


@dataclass(frozen=True, slots=True)
class RepoBenchmarkCase:
    instance_id: str
    task: TaskSpec
    source_url: str | None = None
    notes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RepoBenchmarkSuite:
    benchmark_id: str
    metric_name: str = "pass_rate"
    score_semantics: str = "pass_rate_over_materialized_cases"
    official_metric_equivalent: bool = False
    cases: tuple[RepoBenchmarkCase, ...] = ()
    notes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
