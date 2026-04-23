from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable, Mapping, Sequence

from repo_harness_lab.domain.official_benchmark_models import (
    OfficialBenchmarkEvaluationReport,
    OfficialBenchmarkProfileReport,
)
from repo_harness_lab.storage.run_store import StoredEvalReport, StoredRunRecord


@dataclass(frozen=True, slots=True)
class OfficialPredictionBundle:
    harness_profile: str
    model_name_or_path: str
    predictions_path: Path
    submitted_ids: tuple[str, ...]


def grade_swebench_eval_report(
    *,
    report_id: str,
    eval_report: StoredEvalReport,
    run_record_loader: Callable[[str], StoredRunRecord],
    output_root: Path,
    dataset_name: str,
    split: str,
    model_name: str,
    instance_ids: Sequence[str] = (),
    max_workers: int = 1,
    cache_level: str | None = None,
    clean: bool = False,
    force_rebuild: bool = False,
    open_file_limit: int | None = None,
    timeout: int | None = None,
    namespace: str | None = None,
    log_level: str | None = None,
    modal: bool = False,
    runner_command: Sequence[str] = (),
    python_executable: str = "python",
) -> OfficialBenchmarkEvaluationReport:
    target_root = output_root / _safe_file_stem(report_id)
    target_root.mkdir(parents=True, exist_ok=True)
    bundles = export_swebench_predictions(
        eval_report=eval_report,
        run_record_loader=run_record_loader,
        output_root=target_root / "predictions",
        model_name=model_name,
        instance_ids=instance_ids,
    )
    if not bundles:
        raise ValueError("no SWE-bench predictions could be exported from the eval report")

    profile_reports: list[OfficialBenchmarkProfileReport] = []
    for bundle in bundles:
        profile_root = target_root / bundle.harness_profile
        profile_root.mkdir(parents=True, exist_ok=True)
        run_id = f"{_safe_file_stem(report_id)}-{bundle.harness_profile}-official"
        command = build_official_runner_command(
            predictions_path=bundle.predictions_path,
            dataset_name=dataset_name,
            split=split,
            run_id=run_id,
            instance_ids=bundle.submitted_ids,
            max_workers=max_workers,
            cache_level=cache_level,
            clean=clean,
            force_rebuild=force_rebuild,
            open_file_limit=open_file_limit,
            timeout=timeout,
            namespace=namespace,
            log_level=log_level,
            modal=modal,
            runner_command=runner_command,
            python_executable=python_executable,
        )
        completed = subprocess.run(
            command,
            cwd=profile_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf8",
            errors="replace",
        )
        stdout_path = profile_root / "official_runner.stdout.txt"
        stderr_path = profile_root / "official_runner.stderr.txt"
        stdout_path.write_text(completed.stdout, encoding="utf8")
        stderr_path.write_text(completed.stderr, encoding="utf8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"official SWE-bench runner failed for profile {bundle.harness_profile} "
                f"with exit code {completed.returncode}: {completed.stderr.strip() or completed.stdout.strip()}"
            )
        results_path, instance_results_path = discover_swebench_result_files(
            profile_root=profile_root,
            model_name_or_path=bundle.model_name_or_path,
            run_id=run_id,
        )
        summary_payload = load_swebench_results(results_path) if results_path is not None else {}
        profile_reports.append(
            build_profile_report(
                bundle=bundle,
                run_id=run_id,
                command=command,
                command_exit_code=completed.returncode,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                results_path=results_path,
                instance_results_path=instance_results_path,
                summary_payload=summary_payload,
            )
        )

    return OfficialBenchmarkEvaluationReport(
        benchmark_kind="swebench_official",
        source_report_id=report_id,
        dataset_name=dataset_name,
        split=split,
        official_runner=" ".join(runner_command) if runner_command else f"{python_executable} -m swebench.harness.run_evaluation",
        notes=(
            "官方统一判分结果用于对外公信力结论",
            "项目内部 aggregate_metrics 仍保留为研发诊断指标",
        ),
        profile_reports=tuple(profile_reports),
    )


def export_swebench_predictions(
    *,
    eval_report: StoredEvalReport,
    run_record_loader: Callable[[str], StoredRunRecord],
    output_root: Path,
    model_name: str,
    instance_ids: Sequence[str] = (),
) -> tuple[OfficialPredictionBundle, ...]:
    selected_ids = {str(item) for item in instance_ids if str(item).strip()}
    profile_predictions: dict[str, list[dict[str, str]]] = {}
    profile_instance_ids: dict[str, list[str]] = {}
    seen_by_profile: dict[str, set[str]] = {}
    for case in eval_report.case_results:
        for trial in case.trials:
            summary = trial.run_summary
            if summary is None:
                continue
            benchmark_context = _mapping(summary.metadata.get("benchmark_context"))
            instance_id = str(benchmark_context.get("instance_id") or case.case_id).strip()
            if not instance_id:
                continue
            if selected_ids and instance_id not in selected_ids:
                continue
            harness_profile = str(getattr(trial.harness_profile, "value", trial.harness_profile) or "custom")
            seen = seen_by_profile.setdefault(harness_profile, set())
            if instance_id in seen:
                raise ValueError(f"duplicate instance_id {instance_id} in harness profile {harness_profile}")
            record = run_record_loader(summary.run_id)
            profiled_model_name = f"{model_name}--{harness_profile}"
            prediction = {
                "instance_id": instance_id,
                "model_name_or_path": profiled_model_name,
                "model_patch": record.patch_diff or "",
            }
            profile_predictions.setdefault(harness_profile, []).append(prediction)
            profile_instance_ids.setdefault(harness_profile, []).append(instance_id)
            seen.add(instance_id)

    if selected_ids:
        exported_ids = {instance_id for ids in profile_instance_ids.values() for instance_id in ids}
        missing = sorted(selected_ids - exported_ids)
        if missing:
            raise ValueError(f"requested instance_ids are missing from the eval report: {', '.join(missing)}")

    output_root.mkdir(parents=True, exist_ok=True)
    bundles: list[OfficialPredictionBundle] = []
    for harness_profile, predictions in sorted(profile_predictions.items()):
        profile_root = output_root / _safe_file_stem(harness_profile)
        profile_root.mkdir(parents=True, exist_ok=True)
        predictions_path = profile_root / "predictions.jsonl"
        predictions_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in predictions) + "\n",
            encoding="utf8",
        )
        bundles.append(
            OfficialPredictionBundle(
                harness_profile=harness_profile,
                model_name_or_path=predictions[0]["model_name_or_path"],
                predictions_path=predictions_path,
                submitted_ids=tuple(profile_instance_ids[harness_profile]),
            )
        )
    return tuple(bundles)


def build_official_runner_command(
    *,
    predictions_path: Path,
    dataset_name: str,
    split: str,
    run_id: str,
    instance_ids: Sequence[str],
    max_workers: int,
    cache_level: str | None,
    clean: bool,
    force_rebuild: bool,
    open_file_limit: int | None,
    timeout: int | None,
    namespace: str | None,
    log_level: str | None,
    modal: bool,
    runner_command: Sequence[str],
    python_executable: str,
) -> tuple[str, ...]:
    predictions_path_text = str(predictions_path)
    predictions_path_wsl = _to_wsl_path(predictions_path)
    use_wsl_placeholders = _command_targets_wsl(runner_command)
    format_payload = {
        "predictions_path": predictions_path_wsl if use_wsl_placeholders else predictions_path_text,
        "predictions_path_windows": predictions_path_text,
        "predictions_path_posix": predictions_path.as_posix(),
        "predictions_path_wsl": predictions_path_wsl,
        "predictions_path_sh": shlex.quote(predictions_path_wsl if use_wsl_placeholders else predictions_path_text),
        "dataset_name": dataset_name,
        "split": split,
        "run_id": run_id,
        "max_workers": str(max_workers),
        "instance_ids": " ".join(instance_ids),
    }
    if runner_command:
        return tuple(_apply_command_placeholders(str(part), format_payload) for part in runner_command)

    command: list[str] = [
        python_executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        "--predictions_path",
        str(predictions_path),
        "--max_workers",
        str(max_workers),
        "--run_id",
        run_id,
    ]
    if instance_ids:
        command.extend(["--instance_ids", *instance_ids])
    if cache_level:
        command.extend(["--cache_level", cache_level])
    if clean:
        command.extend(["--clean", "True"])
    if force_rebuild:
        command.extend(["--force_rebuild", "True"])
    if open_file_limit is not None:
        command.extend(["--open_file_limit", str(open_file_limit)])
    if timeout is not None:
        command.extend(["--timeout", str(timeout)])
    if namespace:
        command.extend(["--namespace", namespace])
    if log_level:
        command.extend(["--log_level", log_level])
    if modal:
        command.extend(["--modal", "True"])
    return tuple(command)


def discover_swebench_result_files(
    *,
    profile_root: Path,
    model_name_or_path: str,
    run_id: str,
) -> tuple[Path | None, Path | None]:
    safe_model_name = model_name_or_path.replace("/", "__")
    direct_report = profile_root / f"{safe_model_name}.{run_id}.json"
    if direct_report.exists():
        instance_results = _latest_file(profile_root.glob("evaluation_results/**/instance_results.jsonl"))
        return direct_report, instance_results

    evaluation_root = profile_root / "evaluation_results"
    if not evaluation_root.exists():
        return None, None
    results_path = _latest_file(evaluation_root.rglob("results.json"))
    if results_path is None:
        results_path = _latest_file(evaluation_root.rglob(f"{safe_model_name}.{run_id}.json"))
    instance_results_path = _latest_file(evaluation_root.rglob("instance_results.jsonl"))
    return results_path, instance_results_path


def load_swebench_results(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise TypeError(f"official SWE-bench results must be a JSON object, got {type(payload).__name__}")
    return dict(payload)


def build_profile_report(
    *,
    bundle: OfficialPredictionBundle,
    run_id: str,
    command: Sequence[str],
    command_exit_code: int,
    stdout_path: Path,
    stderr_path: Path,
    results_path: Path | None,
    instance_results_path: Path | None,
    summary_payload: Mapping[str, Any],
) -> OfficialBenchmarkProfileReport:
    submitted_ids = _tuple_of_str(summary_payload.get("submitted_ids")) or bundle.submitted_ids
    resolved_ids = _tuple_of_str(summary_payload.get("resolved_ids"))
    unresolved_ids = _tuple_of_str(summary_payload.get("unresolved_ids"))
    error_ids = _tuple_of_str(summary_payload.get("error_ids"))
    empty_patch_ids = _tuple_of_str(summary_payload.get("empty_patch_ids"))
    incomplete_ids = _tuple_of_str(summary_payload.get("incomplete_ids"))
    submitted_instances = _optional_int(summary_payload.get("submitted_instances")) or len(bundle.submitted_ids)
    resolved_instances = _optional_int(summary_payload.get("resolved_instances"))
    if resolved_instances is None and resolved_ids:
        resolved_instances = len(resolved_ids)
    unresolved_instances = _optional_int(summary_payload.get("unresolved_instances"))
    if unresolved_instances is None and unresolved_ids:
        unresolved_instances = len(unresolved_ids)
    error_instances = _optional_int(summary_payload.get("error_instances"))
    if error_instances is None and error_ids:
        error_instances = len(error_ids)
    empty_patch_instances = _optional_int(summary_payload.get("empty_patch_instances"))
    if empty_patch_instances is None and empty_patch_ids:
        empty_patch_instances = len(empty_patch_ids)
    incomplete_instances = _optional_int(summary_payload.get("incomplete_instances"))
    if incomplete_instances is None and incomplete_ids:
        incomplete_instances = len(incomplete_ids)
    completed_instances = _optional_int(summary_payload.get("completed_instances"))
    if completed_instances is None:
        pieces = [value for value in (resolved_instances, unresolved_instances, error_instances) if value is not None]
        completed_instances = sum(pieces) if pieces else None
    resolution_rate = _optional_float(summary_payload.get("resolution_rate"))
    if resolution_rate is None and submitted_instances:
        numerator = resolved_instances or 0
        resolution_rate = numerator / submitted_instances

    return OfficialBenchmarkProfileReport(
        harness_profile=bundle.harness_profile,
        model_name_or_path=bundle.model_name_or_path,
        run_id=run_id,
        submitted_instances=submitted_instances,
        completed_instances=completed_instances,
        resolved_instances=resolved_instances,
        unresolved_instances=unresolved_instances,
        error_instances=error_instances,
        empty_patch_instances=empty_patch_instances,
        incomplete_instances=incomplete_instances,
        resolution_rate=resolution_rate,
        predictions_path=str(bundle.predictions_path),
        command=tuple(str(item) for item in command),
        command_exit_code=command_exit_code,
        results_path=str(results_path) if results_path is not None else None,
        instance_results_path=str(instance_results_path) if instance_results_path is not None else None,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        submitted_ids=tuple(submitted_ids),
        resolved_ids=tuple(resolved_ids),
        unresolved_ids=tuple(unresolved_ids),
        error_ids=tuple(error_ids),
        empty_patch_ids=tuple(empty_patch_ids),
        incomplete_ids=tuple(incomplete_ids),
        raw_summary=dict(summary_payload),
    )


def _latest_file(paths: Sequence[Path] | Any) -> Path | None:
    items = [Path(item) for item in paths]
    if not items:
        return None
    return max(items, key=lambda item: item.stat().st_mtime)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _apply_command_placeholders(template: str, values: Mapping[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _command_targets_wsl(command: Sequence[str]) -> bool:
    for part in command:
        normalized = str(part).strip().lower().replace("/", "\\")
        if normalized in {"wsl", "wsl.exe"} or normalized.endswith("\\wsl.exe"):
            return True
    return False


def _to_wsl_path(path: Path) -> str:
    path_text = str(path)
    drive_match = re.match(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$", path_text)
    if not drive_match:
        return path.as_posix()
    drive = drive_match.group("drive").lower()
    rest = drive_match.group("rest").replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def _safe_file_stem(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "official-swebench"

