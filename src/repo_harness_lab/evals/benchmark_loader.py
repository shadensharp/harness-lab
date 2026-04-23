from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from repo_harness_lab.domain.benchmark_models import RepoBenchmarkCase, RepoBenchmarkSuite
from repo_harness_lab.domain.task_spec import TaskSpec
from repo_harness_lab.tasks.loader import JsonTaskLoader, parse_task_spec
from repo_harness_lab.tasks.validator import validate_task_spec


class JsonRepoBenchmarkLoader:
    def load(self, source: str | Path) -> RepoBenchmarkSuite:
        path = Path(source).resolve()
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return parse_repo_benchmark_suite(payload, base_dir=path.parent)


def parse_repo_benchmark_suite(
    data: Mapping[str, Any],
    *,
    base_dir: Path | None = None,
) -> RepoBenchmarkSuite:
    suite = RepoBenchmarkSuite(
        benchmark_id=str(data["benchmark_id"]),
        metric_name=str(data.get("metric_name", "pass_rate")),
        score_semantics=str(data.get("score_semantics", "pass_rate_over_materialized_cases")),
        official_metric_equivalent=_bool(data.get("official_metric_equivalent", False), field_name="official_metric_equivalent"),
        cases=tuple(_parse_case(_mapping(item), base_dir=base_dir) for item in data.get("cases", ())),
        notes=_tuple_of_str(data.get("notes")),
        metadata=_mapping(data.get("metadata")),
    )
    validate_repo_benchmark_suite(suite)
    return suite


def validate_repo_benchmark_suite(suite: RepoBenchmarkSuite) -> None:
    errors: list[str] = []
    if not suite.benchmark_id.strip():
        errors.append("benchmark_id must not be empty")
    if not suite.metric_name.strip():
        errors.append("metric_name must not be empty")
    if not suite.score_semantics.strip():
        errors.append("score_semantics must not be empty")
    if not suite.cases:
        errors.append("benchmark suite must define at least one case")

    seen_instance_ids: set[str] = set()
    seen_task_ids: set[str] = set()
    for case in suite.cases:
        if not case.instance_id.strip():
            errors.append("instance_id must not be empty")
        elif case.instance_id in seen_instance_ids:
            errors.append(f"duplicate instance_id: {case.instance_id}")
        else:
            seen_instance_ids.add(case.instance_id)

        if not case.task.task_id.strip():
            errors.append(f"case {case.instance_id or '<unknown>'} must define task.task_id")
        elif case.task.task_id in seen_task_ids:
            errors.append(f"duplicate task.task_id in benchmark suite: {case.task.task_id}")
        else:
            seen_task_ids.add(case.task.task_id)

    if errors:
        raise ValueError("; ".join(errors))


def _parse_case(data: Mapping[str, Any], *, base_dir: Path | None) -> RepoBenchmarkCase:
    task = _load_case_task(data, base_dir=base_dir)
    return RepoBenchmarkCase(
        instance_id=str(data["instance_id"]),
        task=task,
        source_url=_optional_str(data.get("source_url")),
        notes=_tuple_of_str(data.get("notes")),
        metadata=_mapping(data.get("metadata")),
    )


def _load_case_task(data: Mapping[str, Any], *, base_dir: Path | None) -> TaskSpec:
    task_payload = _mapping(data.get("task"))
    if task_payload:
        task = parse_task_spec(task_payload, base_dir=base_dir)
        validate_task_spec(task)
        return task

    task_ref = _optional_str(data.get("task_ref"))
    if not task_ref:
        raise ValueError("benchmark case must define either task or task_ref")
    task_path = Path(task_ref)
    if base_dir is not None and not task_path.is_absolute():
        task_path = (base_dir / task_path).resolve()
    return JsonTaskLoader().load(task_path)


def _mapping(data: Any) -> Mapping[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TypeError(f"expected mapping, got {type(data).__name__}")
    return dict(data)


def _tuple_of_str(data: Any) -> tuple[str, ...]:
    if data is None:
        return ()
    return tuple(str(item) for item in data)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise TypeError(f"{field_name} must be a boolean")
