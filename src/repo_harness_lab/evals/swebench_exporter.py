from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from repo_harness_lab.domain.benchmark_models import RepoBenchmarkCase, RepoBenchmarkSuite
from repo_harness_lab.domain.task_spec import (
    RepoCheckoutMode,
    RepoSource,
    RepoSourceKind,
    SuccessCriteria,
    TaskBenchmarkMetadata,
    TaskConstraints,
    TaskDifficulty,
    TaskSelectionTier,
    TaskSpec,
    TaskType,
    VerifierPlan,
    VerifierStep,
    VerifierStepKind,
)
from repo_harness_lab.shared.serialization import to_jsonable


def export_swebench_manifest(
    source: str | Path,
    *,
    output_path: str | Path,
    repo_url_template: str = "https://github.com/{repo}.git",
    benchmark_id: str = "swe-bench",
    metric_name: str = "resolved_rate",
    default_verifier_command: Sequence[str] = (),
    default_editable_paths: Sequence[str] = (),
    default_setup_steps: Sequence[str] = (),
) -> RepoBenchmarkSuite:
    source_path = Path(source).resolve()
    suite = RepoBenchmarkSuite(
        benchmark_id=benchmark_id,
        metric_name=metric_name,
        score_semantics="pass_rate_over_materialized_cases",
        official_metric_equivalent=False,
        cases=tuple(
            _build_case(
                item,
                repo_url_template=repo_url_template,
                default_verifier_command=tuple(str(part) for part in default_verifier_command),
                default_editable_paths=tuple(str(part) for part in default_editable_paths),
                default_setup_steps=tuple(str(part) for part in default_setup_steps),
            )
            for item in _load_instances(source_path)
        ),
        notes=(
            f"exported from {source_path.name}",
            "generated from SWE-bench style instances",
            "metric name preserved without claiming official grader parity",
        ),
        metadata={
            "source_path": str(source_path),
            "source_format": "swebench_style_instances",
        },
    )
    target_path = Path(output_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(to_jsonable(suite), ensure_ascii=False, indent=2), encoding="utf8")
    return suite


def _load_instances(source_path: Path) -> tuple[Mapping[str, Any], ...]:
    if source_path.suffix.lower() == ".jsonl":
        items: list[Mapping[str, Any]] = []
        for raw_line in source_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            items.append(_mapping(payload))
        return tuple(items)

    payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return tuple(_mapping(item) for item in payload)
    if isinstance(payload, Mapping) and isinstance(payload.get("instances"), Sequence):
        return tuple(_mapping(item) for item in payload.get("instances", ()))
    raise ValueError("SWE-bench export source must be a JSON array, a JSON object with 'instances', or JSONL")


def _build_case(
    item: Mapping[str, Any],
    *,
    repo_url_template: str,
    default_verifier_command: tuple[str, ...],
    default_editable_paths: tuple[str, ...],
    default_setup_steps: tuple[str, ...],
) -> RepoBenchmarkCase:
    instance_id = str(item["instance_id"])
    repo_name = str(item["repo"])
    base_commit = str(item["base_commit"])
    problem_statement = str(item["problem_statement"]).strip()
    verifier_command = _command(item.get("verifier_command")) or default_verifier_command
    setup_steps = _tuple_of_str(item.get("setup_steps")) or default_setup_steps
    editable_paths = _tuple_of_str(item.get("editable_paths")) or default_editable_paths
    verifier_step_name = str(item.get("verifier_step_name") or "benchmark-check")
    benchmark_tags = ("external_benchmark", "swe_bench", repo_name.replace("/", "_"))
    success_criteria = (
        SuccessCriteria(required_verifier_steps=(verifier_step_name,))
        if verifier_command
        else SuccessCriteria()
    )
    verifier_plan = (
        VerifierPlan(
            steps=(
                VerifierStep(
                    name=verifier_step_name,
                    kind=VerifierStepKind.TEST,
                    command=verifier_command,
                ),
            )
        )
        if verifier_command
        else VerifierPlan()
    )
    metadata = {
        "benchmark_context": {
            "instance_id": instance_id,
            "repo": repo_name,
            "base_commit": base_commit,
            "problem_statement": problem_statement,
            "hints_text": _optional_str(item.get("hints_text")),
            "fail_to_pass": _tuple_of_str(item.get("FAIL_TO_PASS")),
            "pass_to_pass": _tuple_of_str(item.get("PASS_TO_PASS")),
            "test_patch": _optional_str(item.get("test_patch")),
            "patch": _optional_str(item.get("patch")),
        }
    }
    task = TaskSpec(
        task_id=instance_id,
        title=f"SWE-bench {instance_id}",
        description=problem_statement,
        task_type=TaskType.BUG_FIX,
        repo_source=RepoSource(
            kind=RepoSourceKind.GIT_URL,
            path_or_url=repo_url_template.format(repo=repo_name),
            checkout_mode=RepoCheckoutMode.COPY,
        ),
        repo_revision=base_commit,
        constraints=TaskConstraints(editable_paths=editable_paths),
        success_criteria=success_criteria,
        setup_steps=setup_steps,
        verifier_plan=verifier_plan,
        benchmark_metadata=TaskBenchmarkMetadata(
            tier=TaskSelectionTier.CURATED,
            difficulty=TaskDifficulty.HARD,
            tags=benchmark_tags,
            harness_signals=("repo_context", "verifier_plan"),
            source="SWE-bench",
        ),
        metadata=metadata,
    )
    return RepoBenchmarkCase(
        instance_id=instance_id,
        task=task,
        source_url=_optional_str(item.get("instance_url")),
        notes=_tuple_of_str(item.get("notes")),
        metadata={key: value for key, value in item.items() if key not in {"problem_statement", "patch", "test_patch"}},
    )


def _mapping(data: Any) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError(f"expected mapping, got {type(data).__name__}")
    return dict(data)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _tuple_of_str(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
        return tuple(str(item) for item in values if str(item))
    text = str(values).strip()
    return (text,) if text else ()


def _command(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value if str(item))
    text = str(value).strip()
    return (text,) if text else ()
