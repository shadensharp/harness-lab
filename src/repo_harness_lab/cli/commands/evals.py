from __future__ import annotations

import argparse
from dataclasses import replace
import json
import re
from pathlib import Path

from repo_harness_lab.agents.factory import build_agent_adapter
from repo_harness_lab.cli.commands.common import print_json, write_task_intake_preview_artifacts, write_uplift_dashboard
from repo_harness_lab.config.settings import load_settings
from repo_harness_lab.evals.benchmark_loader import JsonRepoBenchmarkLoader
from repo_harness_lab.evals.benchmark_materializer import materialize_repo_benchmark_eval
from repo_harness_lab.evals.swebench_exporter import export_swebench_manifest
from repo_harness_lab.domain.eval_models import (
    AggregateMetric,
    CaseResult,
    ComparisonView,
    EvalCase,
    EvalReport,
    EvalRunConfig,
    EvalSuite,
    EvalTrial,
)
from repo_harness_lab.domain.official_benchmark_models import OfficialBenchmarkEvaluationReport
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest, RunSummary
from repo_harness_lab.domain.task_spec import HarnessProfile, TaskSpec
from repo_harness_lab.evals.loader import JsonEvalSuiteLoader
from repo_harness_lab.evals.failure_analysis import analyze_official_failures
from repo_harness_lab.evals.official_swebench import grade_swebench_eval_report
from repo_harness_lab.evals.runner import SimpleEvalRunner
from repo_harness_lab.reporting.html import HtmlReporter
from repo_harness_lab.reporting.markdown import MarkdownReporter
from repo_harness_lab.reporting.failure_analysis import render_failure_analysis_markdown
from repo_harness_lab.reporting.official_benchmark import (
    render_official_benchmark_html,
    render_official_benchmark_markdown,
)
from repo_harness_lab.runtime.runner import RunOrchestrator
from repo_harness_lab.runtime.workspace import LocalWorkspaceBackend
from repo_harness_lab.shared.eval_baselines import (
    BASELINE_KIND_CUSTOM,
    BASELINE_KIND_HISTORICAL,
    build_report_baseline_view,
)
from repo_harness_lab.shared.profile_comparisons import build_profile_run_comparisons, default_baseline_profile
from repo_harness_lab.shared.serialization import to_jsonable
from repo_harness_lab.storage.json_store import JsonRunStore
from repo_harness_lab.storage.run_store import RunRecordStore, StoredEvalCase, StoredEvalReport, StoredEvalTrial
from repo_harness_lab.tasks.intake import JsonTaskIntakeLoader, build_task_spec_from_intake
from repo_harness_lab.tasks.intake_preview import build_task_intake_preview
from repo_harness_lab.tasks.loader import JsonTaskLoader
from repo_harness_lab.verifiers.factory import build_verifier


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run_eval = subparsers.add_parser("run-eval", help="Run an eval suite through the local harness")
    run_eval.add_argument("source")
    run_eval.set_defaults(handler=handle_run_eval)

    export_swebench = subparsers.add_parser(
        "export-swebench-manifest",
        help="Convert SWE-bench-style instance files into a repo benchmark manifest",
    )
    export_swebench.add_argument("source")
    export_swebench.add_argument("output")
    export_swebench.add_argument("--repo-url-template", default="https://github.com/{repo}.git")
    export_swebench.add_argument("--benchmark-id", default="swe-bench")
    export_swebench.add_argument("--metric-name", default="resolved_rate")
    export_swebench.add_argument("--default-verifier-command", nargs="+")
    export_swebench.add_argument("--default-verifier-command-json")
    export_swebench.add_argument("--default-editable-path", action="append", default=[])
    export_swebench.add_argument("--default-setup-step", action="append", default=[])
    export_swebench.set_defaults(handler=handle_export_swebench_manifest)

    run_benchmark_eval = subparsers.add_parser(
        "run-benchmark-eval",
        help="Scaffold an external repo benchmark manifest into TaskSpecs and compare the current run against a baseline report",
    )
    run_benchmark_eval.add_argument("source")
    run_benchmark_eval.add_argument("--provider", required=True)
    run_benchmark_eval.add_argument("--model", required=True)
    run_benchmark_eval.add_argument("--agent-name")
    run_benchmark_eval.add_argument("--api-key-env")
    run_benchmark_eval.add_argument("--base-url")
    run_benchmark_eval.add_argument("--system-prompt")
    run_benchmark_eval.add_argument("--suite-id")
    run_benchmark_eval.add_argument("--label-prefix")
    run_benchmark_eval.add_argument("--historical-baseline-report-id")
    run_benchmark_eval.add_argument("--baseline-report-id")
    run_benchmark_eval.set_defaults(handler=handle_run_benchmark_eval)

    grade_swebench_official = subparsers.add_parser(
        "grade-swebench-official",
        help="Export eval-run patches to SWE-bench predictions and grade them with the official harness",
    )
    grade_swebench_official.add_argument("report_id")
    grade_swebench_official.add_argument("--model-name", required=True)
    grade_swebench_official.add_argument("--dataset-name", default="princeton-nlp/SWE-bench_Verified")
    grade_swebench_official.add_argument("--split", default="test")
    grade_swebench_official.add_argument("--instance-id", action="append", default=[])
    grade_swebench_official.add_argument("--max-workers", type=int, default=1)
    grade_swebench_official.add_argument("--cache-level")
    grade_swebench_official.add_argument("--clean", action="store_true")
    grade_swebench_official.add_argument("--force-rebuild", action="store_true")
    grade_swebench_official.add_argument("--open-file-limit", type=int)
    grade_swebench_official.add_argument("--timeout", type=int)
    grade_swebench_official.add_argument("--namespace")
    grade_swebench_official.add_argument("--log-level")
    grade_swebench_official.add_argument("--modal", action="store_true")
    official_runner_command_group = grade_swebench_official.add_mutually_exclusive_group()
    official_runner_command_group.add_argument("--official-runner-command-json")
    official_runner_command_group.add_argument("--official-runner-command-file")
    grade_swebench_official.set_defaults(handler=handle_grade_swebench_official)

    run_intake_eval = subparsers.add_parser(
        "run-intake-eval",
        help="Scaffold a TaskSpec from a business task intake and compare the current run against a baseline report",
    )
    run_intake_eval.add_argument("source")
    run_intake_eval.add_argument("--provider", required=True)
    run_intake_eval.add_argument("--model", required=True)
    run_intake_eval.add_argument("--agent-name")
    run_intake_eval.add_argument("--api-key-env")
    run_intake_eval.add_argument("--base-url")
    run_intake_eval.add_argument("--system-prompt")
    run_intake_eval.add_argument("--suite-id")
    run_intake_eval.add_argument("--label-prefix")
    run_intake_eval.add_argument("--historical-baseline-report-id")
    run_intake_eval.add_argument("--baseline-report-id")
    run_intake_eval.set_defaults(handler=handle_run_intake_eval)

    render_eval = subparsers.add_parser(
        "render-eval-report",
        help="Re-render stored eval report artifacts from the saved suite JSON and run evidence",
    )
    render_eval.add_argument("report_id")
    render_eval.add_argument("--format", choices=("html", "markdown", "both"), default="both")
    render_eval.set_defaults(handler=handle_render_eval_report)


def handle_run_eval(args: argparse.Namespace) -> int:
    settings = load_settings()
    settings.paths.ensure_runtime_directories()
    suite = JsonEvalSuiteLoader().load(Path(args.source))
    print_json(_execute_eval_suite(settings=settings, suite=suite))
    return 0


def handle_export_swebench_manifest(args: argparse.Namespace) -> int:
    default_verifier_command = tuple(args.default_verifier_command or ())
    if args.default_verifier_command_json:
        payload = json.loads(args.default_verifier_command_json)
        if not isinstance(payload, list):
            raise ValueError("--default-verifier-command-json must decode to a JSON array")
        default_verifier_command = tuple(str(item) for item in payload if str(item))
    suite = export_swebench_manifest(
        args.source,
        output_path=args.output,
        repo_url_template=args.repo_url_template,
        benchmark_id=args.benchmark_id,
        metric_name=args.metric_name,
        default_verifier_command=default_verifier_command,
        default_editable_paths=tuple(args.default_editable_path or ()),
        default_setup_steps=tuple(args.default_setup_step or ()),
    )
    print_json(
        {
            "ok": True,
            "benchmark_id": suite.benchmark_id,
            "benchmark_metric_name": suite.metric_name,
            "case_count": len(suite.cases),
            "source_path": Path(args.source).resolve(),
            "output_path": Path(args.output).resolve(),
            "used_default_verifier_command": bool(default_verifier_command),
        }
    )
    return 0


def handle_run_benchmark_eval(args: argparse.Namespace) -> int:
    settings = load_settings()
    settings.paths.ensure_runtime_directories()
    benchmark_path = Path(args.source).resolve()
    benchmark = JsonRepoBenchmarkLoader().load(benchmark_path)
    suite_id = args.suite_id or f"{benchmark.benchmark_id}-benchmark-baseline-suite"
    materialized = materialize_repo_benchmark_eval(
        benchmark=benchmark,
        output_dir=settings.paths.tmp_dir / "benchmark-evals",
        suite_id=suite_id,
        agent_profile=_build_current_harness_agent_profile(_build_provider_agent_profile(args)),
        label_prefix=args.label_prefix or benchmark.benchmark_id,
    )
    payload = _execute_eval_suite(
        settings=settings,
        suite=materialized.suite,
        historical_baseline_report_id=args.historical_baseline_report_id,
        baseline_report_id=args.baseline_report_id,
    )
    profile_scores = {
        profile_name: float(profile_payload["pass_rate"])
        for profile_name, profile_payload in payload.get("profile_uplift", {}).items()
        if isinstance(profile_payload, dict) and "pass_rate" in profile_payload
    }
    payload.update(
        {
            "benchmark_id": benchmark.benchmark_id,
            "benchmark_metric_name": benchmark.metric_name,
            "benchmark_score": payload["aggregate_metrics"].get("pass_rate"),
            "benchmark_score_source_metric": "pass_rate",
            "benchmark_score_semantics": benchmark.score_semantics,
            "benchmark_score_matches_official_metric": benchmark.official_metric_equivalent,
            "benchmark_profile_scores": profile_scores,
            "benchmark_profile_score_semantics": benchmark.score_semantics,
            "benchmark_baseline_comparison": payload.get("baseline_comparison", {}),
            "benchmark_source_path": benchmark_path,
            "generated_suite_path": materialized.suite_path,
            "generated_task_spec_paths": [str(path) for path in materialized.task_paths],
        }
    )
    print_json(payload)
    return 0


def handle_grade_swebench_official(args: argparse.Namespace) -> int:
    settings = load_settings()
    settings.paths.ensure_runtime_directories()
    run_store = JsonRunStore(settings=settings)
    record_store = RunRecordStore(settings=settings, json_store=run_store)
    stored_report = record_store.load_eval_report(args.report_id)
    runner_command = _json_array_arg(
        args.official_runner_command_json,
        option_name="--official-runner-command-json",
        file_path=args.official_runner_command_file,
        file_option_name="--official-runner-command-file",
    )
    official_report = grade_swebench_eval_report(
        report_id=args.report_id,
        eval_report=stored_report,
        run_record_loader=record_store.load_run_record,
        output_root=settings.paths.tmp_dir / "official-swebench",
        dataset_name=args.dataset_name,
        split=args.split,
        model_name=args.model_name,
        instance_ids=tuple(args.instance_id or ()),
        max_workers=args.max_workers,
        cache_level=args.cache_level,
        clean=args.clean,
        force_rebuild=args.force_rebuild,
        open_file_limit=args.open_file_limit,
        timeout=args.timeout,
        namespace=args.namespace,
        log_level=args.log_level,
        modal=args.modal,
        runner_command=runner_command,
        python_executable=settings.python_executable,
    )
    failure_analysis = analyze_official_failures(
        official_report=official_report,
        eval_report=stored_report,
        run_record_loader=record_store.load_run_record,
    )
    artifact_paths = _write_official_benchmark_artifacts(settings=settings, report=official_report)
    failure_analysis_paths = _write_failure_analysis_artifacts(settings=settings, report=failure_analysis)
    print_json(
        {
            "ok": True,
            "benchmark_kind": official_report.benchmark_kind,
            "source_report_id": official_report.source_report_id,
            "dataset_name": official_report.dataset_name,
            "split": official_report.split,
            "official_runner": official_report.official_runner,
            "profile_reports": to_jsonable(official_report.profile_reports),
            "failure_analysis": to_jsonable(failure_analysis),
            "artifacts": {
                **artifact_paths,
                **failure_analysis_paths,
            },
        }
    )
    return 0


def handle_run_intake_eval(args: argparse.Namespace) -> int:
    settings = load_settings()
    settings.paths.ensure_runtime_directories()
    intake_path = Path(args.source).resolve()
    intake = JsonTaskIntakeLoader().load(intake_path)
    task = build_task_spec_from_intake(intake)
    preview = build_task_intake_preview(intake, source_path=intake_path)

    suite_id = args.suite_id or f"{task.task_id}-intake-baseline-suite"
    task_path = settings.paths.tmp_dir / f"{_safe_file_stem(task.task_id)}.task.json"
    suite_path = settings.paths.tmp_dir / f"{_safe_file_stem(suite_id)}.suite.json"
    _write_json_artifact(task_path, task)
    preview_html_path, preview_json_path = write_task_intake_preview_artifacts(
        settings,
        preview,
        task_id=task.task_id,
    )

    suite = _build_intake_eval_suite(
        task=task,
        task_path=task_path,
        suite_id=suite_id,
        agent_profile=_build_current_harness_agent_profile(_build_provider_agent_profile(args)),
        intake_path=intake_path,
        label_prefix=args.label_prefix or args.provider,
    )
    _write_json_artifact(suite_path, suite)

    payload = _execute_eval_suite(
        settings=settings,
        suite=suite,
        historical_baseline_report_id=args.historical_baseline_report_id,
        baseline_report_id=args.baseline_report_id,
    )
    payload.update(
        {
            "intake_source_path": intake_path,
            "scaffolded_task_spec_path": task_path,
            "generated_suite_path": suite_path,
            "intake_preview": {
                "html_path": preview_html_path,
                "json_path": preview_json_path,
                "profile_delta_summary": preview.get("profile_delta_summary", ()),
                "suggested_commands": preview.get("suggested_commands", {}),
            },
        }
    )
    print_json(payload)
    return 0


def handle_render_eval_report(args: argparse.Namespace) -> int:
    settings = load_settings()
    settings.paths.ensure_runtime_directories()
    run_store = JsonRunStore(settings=settings)
    record_store = RunRecordStore(settings=settings, json_store=run_store)
    stored_report = record_store.load_eval_report(args.report_id)
    report = _restore_eval_report(stored_report)
    markdown_reporter = MarkdownReporter()
    html_reporter = HtmlReporter(run_record_loader=record_store.load_run_record)

    markdown_path: Path | None = None
    html_path: Path | None = None
    if args.format in {"markdown", "both"}:
        markdown_path = settings.paths.reports_dir / f"{stored_report.report_id}.md"
        markdown_path.write_text(markdown_reporter.render_eval(report), encoding="utf8")
    if args.format in {"html", "both"}:
        html_path = settings.paths.reports_dir / f"{stored_report.report_id}.html"
        html_path.write_text(html_reporter.render_eval(report), encoding="utf8")

    comparison_paths = _write_profile_comparison_artifacts(
        reports_dir=settings.paths.reports_dir,
        report=report,
        record_store=record_store,
        html_reporter=html_reporter,
    )
    uplift_dashboard_path, _ = write_uplift_dashboard(settings, record_store, limit=20)
    print_json(
        {
            "ok": True,
            "report_id": stored_report.report_id,
            "suite_id": report.suite_id,
            "format": args.format,
            "artifacts": {
                "json_report_path": stored_report.json_path,
                "markdown_report_path": markdown_path,
                "html_report_path": html_path,
                "uplift_dashboard_path": uplift_dashboard_path,
                "comparison_html_paths": comparison_paths,
            },
        }
    )
    return 0


def _execute_eval_suite(
    *,
    settings,
    suite: EvalSuite,
    historical_baseline_report_id: str | None = None,
    baseline_report_id: str | None = None,
) -> dict[str, object]:
    backend = LocalWorkspaceBackend(settings=settings)
    run_store = JsonRunStore(settings=settings)
    record_store = RunRecordStore(settings=settings, json_store=run_store)
    markdown_reporter = MarkdownReporter()
    html_reporter = HtmlReporter(run_record_loader=record_store.load_run_record)

    def execute_run(task: TaskSpec, request: RunRequest) -> RunSummary:
        orchestrator = RunOrchestrator(
            agent=build_agent_adapter(request.agent_profile),
            verifier=build_verifier(task=task, backend=backend),
            backend=backend,
            run_store=run_store,
            reporter=markdown_reporter,
            html_reporter=html_reporter,
            settings=settings,
        )
        return orchestrator.run(task, request).summary

    runner = SimpleEvalRunner(
        task_loader=JsonTaskLoader(),
        run_request_executor=execute_run,
    )
    baseline_report, baseline_kind = _resolve_requested_baseline_report(
        record_store=record_store,
        current_report_id=suite.suite_id,
        historical_baseline_report_id=historical_baseline_report_id,
        baseline_report_id=baseline_report_id,
    )
    report = runner.run_suite(suite)
    if baseline_report is not None and baseline_kind is not None:
        report = replace(
            report,
            comparison_views=(
                *report.comparison_views,
                build_report_baseline_view(
                    current_report=report,
                    baseline_report=baseline_report,
                    baseline_kind=baseline_kind,
                ),
            ),
        )
    json_path, markdown_path, html_path = _write_eval_artifacts(
        settings.paths.reports_dir,
        suite.suite_id,
        report,
        markdown_reporter,
        html_reporter,
    )
    comparison_paths = _write_profile_comparison_artifacts(
        reports_dir=settings.paths.reports_dir,
        report=report,
        record_store=record_store,
        html_reporter=html_reporter,
    )
    uplift_dashboard_path, _ = write_uplift_dashboard(settings, record_store, limit=20)
    comparison_views = {view.name: to_jsonable(view.items) for view in report.comparison_views}
    return {
        "suite_id": report.suite_id,
        "case_count": len(report.case_results),
        "aggregate_metrics": {metric.name: to_jsonable(metric.value) for metric in report.aggregate_metrics},
        "profile_uplift": comparison_views.get("profile_uplift", {}),
        "baseline_comparison": comparison_views.get("report_baseline", {}),
        "artifacts": {
            "json_report_path": json_path,
            "markdown_report_path": markdown_path,
            "html_report_path": html_path,
            "uplift_dashboard_path": uplift_dashboard_path,
            "comparison_html_paths": comparison_paths,
        },
    }


def _write_eval_artifacts(
    reports_dir: Path,
    artifact_stem: str,
    report: EvalReport,
    markdown_reporter: MarkdownReporter,
    html_reporter: HtmlReporter,
) -> tuple[Path, Path, Path]:
    stem = _safe_file_stem(artifact_stem)
    json_path = reports_dir / f"{stem}.json"
    markdown_path = reports_dir / f"{stem}.md"
    html_path = reports_dir / f"{stem}.html"
    json_path.write_text(json.dumps(to_jsonable(report), ensure_ascii=False, indent=2), encoding="utf8")
    markdown_path.write_text(markdown_reporter.render_eval(report), encoding="utf8")
    html_path.write_text(html_reporter.render_eval(report), encoding="utf8")
    return json_path, markdown_path, html_path


def _write_json_artifact(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf8")


def _write_official_benchmark_artifacts(*, settings, report: OfficialBenchmarkEvaluationReport) -> dict[str, Path]:
    stem = _safe_file_stem(f"official-swebench-{report.source_report_id}")
    json_path = settings.paths.reports_dir / f"{stem}.json"
    markdown_path = settings.paths.reports_dir / f"{stem}.md"
    html_path = settings.paths.reports_dir / f"{stem}.html"
    json_path.write_text(json.dumps(to_jsonable(report), ensure_ascii=False, indent=2), encoding="utf8")
    markdown_path.write_text(render_official_benchmark_markdown(report), encoding="utf8")
    html_path.write_text(render_official_benchmark_html(report), encoding="utf8")
    return {
        "json_report_path": json_path,
        "markdown_report_path": markdown_path,
        "html_report_path": html_path,
    }


def _write_failure_analysis_artifacts(*, settings, report) -> dict[str, Path]:
    stem = _safe_file_stem(f"official-swebench-failures-{report.source_report_id}")
    json_path = settings.paths.reports_dir / f"{stem}.json"
    markdown_path = settings.paths.reports_dir / f"{stem}.md"
    json_path.write_text(json.dumps(to_jsonable(report), ensure_ascii=False, indent=2), encoding="utf8")
    markdown_path.write_text(render_failure_analysis_markdown(report), encoding="utf8")
    return {
        "failure_analysis_json_path": json_path,
        "failure_analysis_markdown_path": markdown_path,
    }


def _build_intake_eval_suite(
    *,
    task: TaskSpec,
    task_path: Path,
    suite_id: str,
    agent_profile: AgentProfile,
    intake_path: Path,
    label_prefix: str,
) -> EvalSuite:
    run_matrix = (
        EvalRunConfig(
            label=f"{label_prefix}-current",
            harness_profile=HarnessProfile.CURRENT,
            request=RunRequest(
                run_id="",
                task_id=task.task_id,
                agent_profile=agent_profile,
                metadata={
                    "intake_source_path": str(intake_path),
                    "scaffolded_task_spec_path": str(task_path),
                },
            ),
        ),
    )
    return EvalSuite(
        suite_id=suite_id,
        notes=(
            "scaffolded from business task intake",
            "single current harness run; compare against baseline reports instead of the legacy matrix",
        ),
        cases=(
            EvalCase(
                case_id=task.task_id,
                task_spec_ref=str(task_path),
                run_matrix=run_matrix,
                notes=(
                    "generated from task intake",
                    "single current harness run for baseline comparison",
                ),
            ),
        ),
    )


def _json_array_arg(
    raw: str | None,
    *,
    option_name: str,
    file_path: str | None = None,
    file_option_name: str | None = None,
) -> tuple[str, ...]:
    if file_path:
        payload = json.loads(Path(file_path).read_text(encoding="utf-8-sig"))
        source_name = file_option_name or option_name
    elif raw:
        payload = json.loads(raw)
        source_name = option_name
    else:
        return ()
    if not isinstance(payload, list):
        raise ValueError(f"{source_name} must decode to a JSON array")
    return tuple(str(item) for item in payload)


def _build_provider_agent_profile(args: argparse.Namespace) -> AgentProfile:
    metadata: dict[str, object] = {"model": args.model}
    if args.api_key_env:
        metadata["api_key_env"] = args.api_key_env
    if args.base_url:
        metadata["base_url"] = args.base_url
    if args.system_prompt:
        metadata["system_prompt"] = args.system_prompt
    return AgentProfile(
        name=args.agent_name or args.model,
        provider=args.provider,
        metadata=metadata,
    )


def _build_current_harness_agent_profile(agent_profile: AgentProfile) -> AgentProfile:
    return replace(
        agent_profile,
        metadata={
            **dict(agent_profile.metadata),
            "include_tree": True,
            "include_inputs": True,
            "include_verifier_plan": True,
            "max_context_files": 12,
            "max_file_chars": 8000,
        },
    )


def _resolve_requested_baseline_report(
    *,
    record_store: RunRecordStore,
    current_report_id: str,
    historical_baseline_report_id: str | None,
    baseline_report_id: str | None,
) -> tuple[StoredEvalReport | None, str | None]:
    explicit_report_id = str(baseline_report_id or "").strip()
    historical_report_id = str(historical_baseline_report_id or "").strip()
    if explicit_report_id:
        if explicit_report_id == current_report_id:
            raise ValueError("baseline report cannot be the same as the current report id")
        return record_store.load_eval_report(explicit_report_id), BASELINE_KIND_CUSTOM
    if historical_report_id:
        if historical_report_id == current_report_id:
            raise ValueError("historical baseline report cannot be the same as the current report id")
        return record_store.load_eval_report(historical_report_id), BASELINE_KIND_HISTORICAL
    return None, None


def _write_profile_comparison_artifacts(
    *,
    reports_dir: Path,
    report: EvalReport,
    record_store: RunRecordStore,
    html_reporter: HtmlReporter,
) -> list[Path]:
    generated_paths: list[Path] = []
    seen_pairs: set[tuple[str, str]] = set()

    for case_result in report.case_results:
        baseline_profile = _case_baseline_profile(case_result)
        profile_runs = {
            trial.harness_profile.value: trial.run_summary.run_id
            for trial in case_result.trials
            if trial.run_summary is not None
        }
        for comparison in build_profile_run_comparisons(profile_runs, baseline_profile=baseline_profile):
            pair = (comparison.left_run_id, comparison.right_run_id)
            if pair in seen_pairs:
                continue
            bundle = record_store.load_run_comparison(comparison.left_run_id, comparison.right_run_id)
            compare_path = reports_dir / _compare_filename(comparison.left_run_id, comparison.right_run_id)
            compare_path.write_text(html_reporter.render_run_comparison(bundle), encoding="utf8")
            generated_paths.append(compare_path)
            seen_pairs.add(pair)

    return generated_paths

def _restore_eval_report(stored_report: StoredEvalReport) -> EvalReport:
    return EvalReport(
        suite_id=stored_report.suite_id,
        case_results=tuple(_restore_case_result(case) for case in stored_report.case_results),
        aggregate_metrics=tuple(
            AggregateMetric(name=name, value=float(value), unit=_restore_metric_unit(name))
            for name, value in stored_report.aggregate_metrics.items()
        ),
        comparison_views=tuple(
            ComparisonView(name=name, items=dict(items))
            for name, items in stored_report.comparison_views.items()
        ),
    )


def _restore_case_result(case: StoredEvalCase) -> CaseResult:
    return CaseResult(
        case_id=case.case_id,
        trials=tuple(_restore_eval_trial(trial) for trial in case.trials),
        summary=dict(case.summary),
    )


def _restore_eval_trial(trial: StoredEvalTrial) -> EvalTrial:
    harness_profile = _restore_harness_profile(trial.harness_profile)
    run_summary = trial.run_summary
    run_id = run_summary.run_id if run_summary is not None else trial.trial_id
    task_id = run_summary.task_id if run_summary is not None else trial.case_id
    notes = trial.notes or ((trial.label,) if trial.label else ())
    return EvalTrial(
        trial_id=trial.trial_id,
        case_id=trial.case_id,
        run_request=RunRequest(
            run_id=run_id,
            task_id=task_id,
            agent_profile=AgentProfile(name="restored-agent", provider="stored_eval"),
            labels=(f"harness_profile:{harness_profile.value}",),
            metadata={"restored_from": "stored_eval_report", **dict(trial.run_request_metadata)},
        ),
        run_summary=run_summary,
        harness_profile=harness_profile,
        notes=notes,
    )


def _restore_harness_profile(value: str) -> HarnessProfile:
    try:
        return HarnessProfile(str(value))
    except ValueError:
        return HarnessProfile.CUSTOM


def _restore_metric_unit(name: str) -> str | None:
    if name.endswith("_duration_ms"):
        return "ms"
    if name.endswith("rate"):
        return "ratio"
    if name.startswith("total_") or name.endswith("_count") or name.endswith("_trials"):
        return "count"
    return None


def _case_baseline_profile(case_result: CaseResult) -> str:
    available_profiles = (
        trial.harness_profile.value
        for trial in case_result.trials
        if trial.run_summary is not None
    )
    return default_baseline_profile(available_profiles)


def _compare_filename(left_run_id: str, right_run_id: str) -> str:
    left = _safe_file_stem(left_run_id)
    right = _safe_file_stem(right_run_id)
    return f"compare-{left}-vs-{right}.html"


def _safe_file_stem(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "eval-report"


