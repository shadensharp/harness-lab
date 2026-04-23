from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re

from repo_harness_lab.domain.benchmark_models import RepoBenchmarkCase, RepoBenchmarkSuite
from repo_harness_lab.domain.eval_models import EvalCase, EvalRunConfig, EvalSuite
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest
from repo_harness_lab.domain.task_spec import HarnessProfile, TaskSpec
from repo_harness_lab.shared.files import ensure_directory
from repo_harness_lab.shared.serialization import to_jsonable


@dataclass(frozen=True, slots=True)
class MaterializedBenchmarkEval:
    benchmark: RepoBenchmarkSuite
    suite: EvalSuite
    suite_path: Path
    task_paths: tuple[Path, ...] = ()


def materialize_repo_benchmark_eval(
    *,
    benchmark: RepoBenchmarkSuite,
    output_dir: Path,
    suite_id: str,
    agent_profile: AgentProfile,
    label_prefix: str,
) -> MaterializedBenchmarkEval:
    target_root = ensure_directory(output_dir / _safe_file_stem(suite_id))
    tasks_dir = ensure_directory(target_root / "tasks")

    task_paths: list[Path] = []
    eval_cases: list[EvalCase] = []
    for case in benchmark.cases:
        benchmark_context = _benchmark_context(benchmark=benchmark, case=case)
        task = replace(case.task, metadata={**dict(case.task.metadata), "benchmark_context": benchmark_context})
        task_path = tasks_dir / f"{_safe_file_stem(case.instance_id)}.task.json"
        _write_json(task_path, task)
        task_paths.append(task_path)
        eval_cases.append(
            EvalCase(
                case_id=case.instance_id,
                task_spec_ref=str(task_path),
                run_matrix=_build_run_matrix(
                    task=task,
                    task_path=task_path,
                    agent_profile=agent_profile,
                    label_prefix=label_prefix,
                    benchmark_context=benchmark_context,
                ),
                notes=(
                    *case.notes,
                    f"benchmark_id={benchmark.benchmark_id}",
                    f"benchmark_metric_name={benchmark.metric_name}",
                    f"benchmark_score_semantics={benchmark.score_semantics}",
                    f"official_metric_equivalent={benchmark.official_metric_equivalent}",
                ),
            )
        )

    suite = EvalSuite(
        suite_id=suite_id,
        notes=(
            *benchmark.notes,
            "scaffolded from external repo benchmark manifest",
            f"benchmark_metric_name={benchmark.metric_name}",
            f"benchmark_score_semantics={benchmark.score_semantics}",
            f"official_metric_equivalent={benchmark.official_metric_equivalent}",
            "single current harness run; compare against baseline reports instead of legacy multi-run tiers",
        ),
        cases=tuple(eval_cases),
    )
    suite_path = target_root / f"{_safe_file_stem(suite_id)}.suite.json"
    _write_json(suite_path, suite)
    return MaterializedBenchmarkEval(
        benchmark=benchmark,
        suite=suite,
        suite_path=suite_path,
        task_paths=tuple(task_paths),
    )


def _build_run_matrix(
    *,
    task: TaskSpec,
    task_path: Path,
    agent_profile: AgentProfile,
    label_prefix: str,
    benchmark_context: dict[str, object],
) -> tuple[EvalRunConfig, ...]:
    return (
        EvalRunConfig(
            label=f"{label_prefix}-current",
            harness_profile=HarnessProfile.CURRENT,
            request=RunRequest(
                run_id="",
                task_id=task.task_id,
                agent_profile=agent_profile,
                metadata={
                    "benchmark_context": benchmark_context,
                    "scaffolded_task_spec_path": str(task_path),
                },
            ),
        ),
    )


def _benchmark_context(
    *,
    benchmark: RepoBenchmarkSuite,
    case: RepoBenchmarkCase,
) -> dict[str, object]:
    context: dict[str, object] = {
        "benchmark_id": benchmark.benchmark_id,
        "metric_name": benchmark.metric_name,
        "score_semantics": benchmark.score_semantics,
        "official_metric_equivalent": benchmark.official_metric_equivalent,
        "instance_id": case.instance_id,
    }
    if case.source_url:
        context["source_url"] = case.source_url
    if case.metadata:
        context["case_metadata"] = dict(case.metadata)
    return context


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf8")


def _safe_file_stem(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "benchmark-eval"
