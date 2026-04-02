from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from repo_harness_lab.domain.protocols import TaskLoader
from repo_harness_lab.domain.task_spec import (
    FailurePolicy,
    RepoCheckoutMode,
    RepoSource,
    RepoSourceKind,
    SuccessCriteria,
    TaskBenchmarkMetadata,
    TaskConstraints,
    TaskDifficulty,
    TaskInput,
    TaskInputBundle,
    TaskInputKind,
    TaskSelectionTier,
    TaskSpec,
    TaskType,
    VerifierPlan,
    VerifierStep,
    VerifierStepKind,
)
from repo_harness_lab.tasks.validator import validate_task_spec


class JsonTaskLoader(TaskLoader):
    def load(self, source: str | Path) -> TaskSpec:
        path = Path(source).resolve()
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        task = parse_task_spec(data, base_dir=path.parent)
        validate_task_spec(task)
        return task



def parse_task_spec(data: Mapping[str, Any], *, base_dir: Path | None = None) -> TaskSpec:
    return TaskSpec(
        task_id=str(data["task_id"]),
        title=str(data["title"]),
        description=str(data["description"]),
        task_type=TaskType(data["task_type"]),
        repo_source=_parse_repo_source(_mapping(data["repo_source"]), base_dir=base_dir),
        repo_revision=_optional_str(data.get("repo_revision")),
        inputs=_parse_task_input_bundle(data.get("inputs"), base_dir=base_dir),
        constraints=_parse_constraints(data.get("constraints")),
        success_criteria=_parse_success_criteria(data.get("success_criteria")),
        setup_steps=_tuple_of_str(data.get("setup_steps")),
        verifier_plan=_parse_verifier_plan(data.get("verifier_plan")),
        benchmark_metadata=_parse_benchmark_metadata(data.get("benchmark_metadata")),
        metadata=_mapping(data.get("metadata")),
    )



def _parse_repo_source(data: Mapping[str, Any], *, base_dir: Path | None) -> RepoSource:
    kind = RepoSourceKind(data["kind"])
    path_or_url = str(data["path_or_url"])
    if kind is RepoSourceKind.LOCAL_PATH:
        path_or_url = _resolve_relative_path(path_or_url, base_dir=base_dir)
    return RepoSource(
        kind=kind,
        path_or_url=path_or_url,
        default_branch=str(data.get("default_branch", "main")),
        checkout_mode=RepoCheckoutMode(data.get("checkout_mode", RepoCheckoutMode.COPY.value)),
    )



def _parse_task_input_bundle(data: Any, *, base_dir: Path | None) -> TaskInputBundle:
    if data is None:
        return TaskInputBundle()

    if isinstance(data, Mapping):
        raw_items = data.get("items", ())
    else:
        raw_items = data

    items = tuple(_parse_task_input(_mapping(item), base_dir=base_dir) for item in raw_items)
    return TaskInputBundle(items=items)



def _parse_task_input(data: Mapping[str, Any], *, base_dir: Path | None) -> TaskInput:
    raw_path = _optional_str(data.get("path"))
    resolved_path = _resolve_relative_path(raw_path, base_dir=base_dir) if raw_path else None
    return TaskInput(
        name=str(data["name"]),
        kind=TaskInputKind(data["kind"]),
        description=str(data.get("description", "")),
        content=_optional_str(data.get("content")),
        path=resolved_path,
        metadata=_mapping(data.get("metadata")),
    )



def _parse_constraints(data: Any) -> TaskConstraints:
    payload = _mapping(data)
    return TaskConstraints(
        allow_network=bool(payload.get("allow_network", False)),
        editable_paths=_tuple_of_str(payload.get("editable_paths")),
        forbidden_paths=_tuple_of_str(payload.get("forbidden_paths")),
        allowed_tools=_tuple_of_str(payload.get("allowed_tools")),
        max_runtime_seconds=_optional_int(payload.get("max_runtime_seconds")),
        max_cost_usd=_optional_float(payload.get("max_cost_usd")),
    )



def _parse_success_criteria(data: Any) -> SuccessCriteria:
    payload = _mapping(data)
    return SuccessCriteria(
        required_verifier_steps=_tuple_of_str(payload.get("required_verifier_steps")),
        changed_files=_tuple_of_str(payload.get("changed_files")),
        behavioral_checks=_tuple_of_str(payload.get("behavioral_checks")),
    )



def _parse_verifier_plan(data: Any) -> VerifierPlan:
    payload = _mapping(data)
    raw_steps = payload.get("steps", ())
    steps = tuple(_parse_verifier_step(_mapping(step)) for step in raw_steps)
    return VerifierPlan(
        steps=steps,
        required_passes=_optional_int(payload.get("required_passes")),
        failure_policy=FailurePolicy(payload.get("failure_policy", FailurePolicy.COLLECT_ALL.value)),
    )



def _parse_verifier_step(data: Mapping[str, Any]) -> VerifierStep:
    return VerifierStep(
        name=str(data["name"]),
        kind=VerifierStepKind(data["kind"]),
        command=_tuple_of_str(data.get("command")),
        required=bool(data.get("required", True)),
        notes=str(data.get("notes", "")),
    )



def _parse_benchmark_metadata(data: Any) -> TaskBenchmarkMetadata:
    payload = _mapping(data)
    return TaskBenchmarkMetadata(
        tier=TaskSelectionTier(payload.get("tier", TaskSelectionTier.OPEN.value)),
        difficulty=TaskDifficulty(payload.get("difficulty", TaskDifficulty.MEDIUM.value)),
        tags=_tuple_of_str(payload.get("tags")),
        harness_signals=_tuple_of_str(payload.get("harness_signals")),
        owner=_optional_str(payload.get("owner")),
        source=_optional_str(payload.get("source")),
        notes=_tuple_of_str(payload.get("notes")),
    )



def _resolve_relative_path(value: str | None, *, base_dir: Path | None) -> str:
    if value is None:
        return ""
    path = Path(value)
    if path.is_absolute() or base_dir is None:
        return str(path)
    return str((base_dir / path).resolve())



def _mapping(data: Any) -> Mapping[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TypeError(f"expected mapping, got {type(data).__name__}")
    return data



def _tuple_of_str(data: Any) -> tuple[str, ...]:
    if data is None:
        return ()
    return tuple(str(item) for item in data)



def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)



def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)



def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
