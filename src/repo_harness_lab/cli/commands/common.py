from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repo_harness_lab.config.settings import Settings, load_settings
from repo_harness_lab.reporting.intake_html import render_task_intake_preview
from repo_harness_lab.reporting.markdown import MarkdownReporter
from repo_harness_lab.reporting.uplift_html import UpliftHtmlReporter
from repo_harness_lab.shared.serialization import to_jsonable
from repo_harness_lab.storage.json_store import JsonRunStore
from repo_harness_lab.storage.run_store import RunRecordStore


def print_json(payload: Any) -> None:
    print(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2))


def print_error(message: str) -> int:
    print_json({"ok": False, "error": message})
    return 1


def load_runtime_context(
    settings: Settings | None = None,
) -> tuple[Settings, JsonRunStore, RunRecordStore, MarkdownReporter]:
    resolved = settings or load_settings()
    resolved.paths.ensure_runtime_directories()
    json_store = JsonRunStore(settings=resolved)
    return resolved, json_store, RunRecordStore(settings=resolved, json_store=json_store), MarkdownReporter()


def resolve_report_path(store: JsonRunStore, run_id: str) -> Path:
    return store.report_path(run_id)


def write_task_intake_preview_artifacts(
    settings: Settings,
    preview: Any,
    *,
    task_id: str,
    output_path: Path | None = None,
) -> tuple[Path, Path]:
    settings.paths.ensure_runtime_directories()
    html_path = output_path or settings.paths.reports_dir / f"intake-preview-{_safe_file_stem(task_id)}.html"
    json_path = html_path.with_suffix(".json")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_task_intake_preview(preview), encoding="utf8")
    json_path.write_text(json.dumps(to_jsonable(preview), ensure_ascii=False, indent=2), encoding="utf8")
    return html_path, json_path


def write_uplift_dashboard(
    settings: Settings,
    record_store: RunRecordStore,
    *,
    limit: int = 20,
) -> tuple[Path, int]:
    eval_reports = record_store.list_eval_report_records(limit=limit)
    dashboard_path = settings.paths.reports_dir / "uplift-dashboard.html"
    dashboard_path.write_text(
        UpliftHtmlReporter(run_record_loader=record_store.load_run_record, run_comparison_loader=record_store.load_run_comparison).render_dashboard(eval_reports, title="同模型 Harness 总览"),
        encoding="utf8",
    )
    return dashboard_path, len(eval_reports)


def _safe_file_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip("-")
    return sanitized or "task-intake-preview"
