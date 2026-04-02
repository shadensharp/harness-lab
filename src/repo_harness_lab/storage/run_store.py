from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from repo_harness_lab.config.settings import Settings, load_settings
from repo_harness_lab.domain.run_models import RunSummary
from repo_harness_lab.domain.trace_models import CommandExecutionRecord, TraceEvent
from repo_harness_lab.domain.verifier_models import VerificationEvidence, VerificationStatus, VerifierResult
from repo_harness_lab.storage.json_store import JsonRunStore, deserialize_summary
from repo_harness_lab.traces.sink import parse_trace_event


@dataclass(frozen=True, slots=True)
class StoredRunRecord:
    summary: RunSummary
    events: tuple[TraceEvent, ...] = ()
    verifier_result: VerifierResult | None = None
    report_markdown: str | None = None
    patch_diff: str | None = None


@dataclass(frozen=True, slots=True)
class RunComparison:
    left_run_id: str
    right_run_id: str
    left_status: str
    right_status: str
    left_verifier_outcome: str | None
    right_verifier_outcome: str | None
    status_changed: bool
    verifier_outcome_changed: bool
    duration_ms_delta: int | None
    changed_files_only_in_left: tuple[str, ...]
    changed_files_only_in_right: tuple[str, ...]
    notes_only_in_left: tuple[str, ...]
    notes_only_in_right: tuple[str, ...]
    left_event_count: int
    right_event_count: int


@dataclass(frozen=True, slots=True)
class StoredRunComparison:
    left: StoredRunRecord
    right: StoredRunRecord
    comparison: RunComparison


@dataclass(frozen=True, slots=True)
class ReportArtifactSummary:
    report_id: str
    title: str
    category: str
    html_path: Path
    markdown_path: Path | None = None
    json_path: Path | None = None
    updated_at: datetime | None = None
    is_portal_live: bool = False


@dataclass(frozen=True, slots=True)
class StoredEvalTrial:
    trial_id: str
    case_id: str
    label: str = "unlabeled"
    harness_profile: str = "custom"
    run_summary: RunSummary | None = None
    notes: tuple[str, ...] = ()
    run_request_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StoredEvalCase:
    case_id: str
    summary: Mapping[str, Any] = field(default_factory=dict)
    trials: tuple[StoredEvalTrial, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredEvalReport:
    report_id: str
    title: str
    suite_id: str
    html_path: Path
    markdown_path: Path | None = None
    json_path: Path | None = None
    updated_at: datetime | None = None
    aggregate_metrics: Mapping[str, Any] = field(default_factory=dict)
    comparison_views: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    case_count: int = 0
    task_tags: tuple[str, ...] = ()
    harness_signals: tuple[str, ...] = ()
    case_results: tuple[StoredEvalCase, ...] = ()
    is_portal_live: bool = False


class RunRecordStore:
    def __init__(
        self,
        settings: Settings | None = None,
        json_store: JsonRunStore | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.json_store = json_store or JsonRunStore(settings=self.settings)

    def has_run(self, run_id: str) -> bool:
        return self.json_store.summary_path(run_id).exists()

    def load_events(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        event_type: str | None = None,
        stage: str | None = None,
    ) -> tuple[TraceEvent, ...]:
        path = self.json_store.events_path(run_id)
        if not path.exists():
            return ()

        events: list[TraceEvent] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            event = parse_trace_event(json.loads(line))
            if event_type is not None and event.event_type.value != event_type:
                continue
            if stage is not None and event.stage.value != stage:
                continue
            events.append(event)

        if limit is not None and limit >= 0:
            events = events[-limit:]
        return tuple(events)

    def load_verifier_result(self, run_id: str) -> VerifierResult | None:
        path = self.json_store.verifier_results_path(run_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return _deserialize_verifier_result(payload)

    def load_report(self, run_id: str) -> str | None:
        path = self.json_store.report_path(run_id)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8-sig")

    def load_patch(self, run_id: str) -> str | None:
        path = self.json_store.patch_path(run_id)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8-sig")

    def load_run_record(self, run_id: str) -> StoredRunRecord:
        summary = self.json_store.load_summary(run_id)
        return StoredRunRecord(
            summary=summary,
            events=self.load_events(run_id),
            verifier_result=self.load_verifier_result(run_id),
            report_markdown=self.load_report(run_id),
            patch_diff=self.load_patch(run_id),
        )

    def load_run_comparison(self, left_run_id: str, right_run_id: str) -> StoredRunComparison:
        left = self.load_run_record(left_run_id)
        right = self.load_run_record(right_run_id)

        left_changed = set(left.summary.changed_files)
        right_changed = set(right.summary.changed_files)
        left_notes = set(left.summary.notes)
        right_notes = set(right.summary.notes)

        duration_ms_delta: int | None = None
        if left.summary.duration_ms is not None and right.summary.duration_ms is not None:
            duration_ms_delta = right.summary.duration_ms - left.summary.duration_ms

        comparison = RunComparison(
            left_run_id=left.summary.run_id,
            right_run_id=right.summary.run_id,
            left_status=left.summary.status.value,
            right_status=right.summary.status.value,
            left_verifier_outcome=left.summary.verifier_outcome,
            right_verifier_outcome=right.summary.verifier_outcome,
            status_changed=left.summary.status != right.summary.status,
            verifier_outcome_changed=left.summary.verifier_outcome != right.summary.verifier_outcome,
            duration_ms_delta=duration_ms_delta,
            changed_files_only_in_left=tuple(sorted(left_changed - right_changed)),
            changed_files_only_in_right=tuple(sorted(right_changed - left_changed)),
            notes_only_in_left=tuple(sorted(left_notes - right_notes)),
            notes_only_in_right=tuple(sorted(right_notes - left_notes)),
            left_event_count=len(left.events),
            right_event_count=len(right.events),
        )
        return StoredRunComparison(left=left, right=right, comparison=comparison)

    def compare_runs(self, left_run_id: str, right_run_id: str) -> RunComparison:
        return self.load_run_comparison(left_run_id, right_run_id).comparison

    def list_report_artifacts(
        self,
        *,
        limit: int = 20,
        categories: tuple[str, ...] | None = None,
    ) -> tuple[ReportArtifactSummary, ...]:
        reports: list[ReportArtifactSummary] = []
        for html_path in sorted(
            self.settings.paths.reports_dir.glob("*.html"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            report = _build_report_artifact_summary(html_path)
            if report is None:
                continue
            if categories is not None and report.category not in categories:
                continue
            reports.append(report)
            if len(reports) >= limit:
                break
        return tuple(reports)

    def load_eval_report(self, report_id: str) -> StoredEvalReport:
        category, title = _report_category_and_title(report_id)
        if category != "eval":
            raise FileNotFoundError(f"eval report not found: {report_id}")

        html_path = self.settings.paths.reports_dir / f"{report_id}.html"
        markdown_path = self.settings.paths.reports_dir / f"{report_id}.md"
        json_path = self.settings.paths.reports_dir / f"{report_id}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"eval report json not found: {report_id}")

        updated_source = html_path if html_path.exists() else json_path
        artifact = ReportArtifactSummary(
            report_id=report_id,
            title=title,
            category=category,
            html_path=html_path,
            markdown_path=markdown_path if markdown_path.exists() else None,
            json_path=json_path,
            updated_at=datetime.fromtimestamp(updated_source.stat().st_mtime, tz=timezone.utc),
        )
        payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
        return _deserialize_eval_report(artifact, payload)

    def list_eval_report_records(self, *, limit: int = 20) -> tuple[StoredEvalReport, ...]:
        reports: list[StoredEvalReport] = []
        for json_path in sorted(
            self.settings.paths.reports_dir.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            report_id = json_path.stem
            category, title = _report_category_and_title(report_id)
            if category != "eval":
                continue
            html_path = self.settings.paths.reports_dir / f"{report_id}.html"
            markdown_path = self.settings.paths.reports_dir / f"{report_id}.md"
            updated_source = html_path if html_path.exists() else json_path
            artifact = ReportArtifactSummary(
                report_id=report_id,
                title=title,
                category=category,
                html_path=html_path,
                markdown_path=markdown_path if markdown_path.exists() else None,
                json_path=json_path,
                updated_at=datetime.fromtimestamp(updated_source.stat().st_mtime, tz=timezone.utc),
            )
            payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
            reports.append(_deserialize_eval_report(artifact, payload))
            if len(reports) >= limit:
                break
        return tuple(reports)


def _is_portal_live_eval_id(*values: str) -> bool:
    return any("-portal-" in str(value) for value in values if value)


def _deserialize_verifier_result(payload: dict[str, object]) -> VerifierResult:
    evidence = tuple(
        VerificationEvidence(
            summary=str(item["summary"]),
            details=item.get("details", {}),
            artifacts=tuple(item.get("artifacts", ())),
        )
        for item in payload.get("evidence", ())
    )
    command_results = tuple(
        CommandExecutionRecord(
            command=tuple(item["command"]),
            cwd=str(item["cwd"]),
            exit_code=int(item["exit_code"]),
            stdout_excerpt=str(item.get("stdout_excerpt", "")),
            stderr_excerpt=str(item.get("stderr_excerpt", "")),
            duration_ms=int(item["duration_ms"]) if item.get("duration_ms") is not None else None,
        )
        for item in payload.get("command_results", ())
    )
    started_at = datetime.fromisoformat(payload["started_at"])
    finished_at = datetime.fromisoformat(payload["finished_at"]) if payload.get("finished_at") else None
    return VerifierResult(
        verifier_name=str(payload["verifier_name"]),
        status=VerificationStatus(payload["status"]),
        evidence=evidence,
        command_results=command_results,
        started_at=started_at,
        finished_at=finished_at,
        errors=tuple(payload.get("errors", ())),
    )


def _build_report_artifact_summary(html_path: Path) -> ReportArtifactSummary | None:
    report_id = html_path.stem
    category, title = _report_category_and_title(report_id)

    markdown_path = html_path.with_suffix(".md")
    json_path = html_path.with_suffix(".json")
    return ReportArtifactSummary(
        report_id=report_id,
        title=title,
        category=category,
        html_path=html_path,
        markdown_path=markdown_path if markdown_path.exists() else None,
        json_path=json_path if json_path.exists() else None,
        updated_at=datetime.fromtimestamp(html_path.stat().st_mtime, tz=timezone.utc),
        is_portal_live=category == "eval" and _is_portal_live_eval_id(report_id),
    )



def _report_category_and_title(report_id: str) -> tuple[str, str]:
    category = "eval"
    title = report_id

    if report_id == "runs-dashboard":
        category = "dashboard"
        title = "运行记录总览"
    elif report_id == "uplift-dashboard":
        category = "uplift"
        title = "同模型 Harness 总览"
    elif report_id == "harness-portal":
        category = "portal"
        title = "同模型 Harness 门户"
    elif report_id.startswith("compare-"):
        category = "comparison"
        title = report_id.removeprefix("compare-").replace("-vs-", " vs ")
    elif report_id.startswith("intake-preview-"):
        category = "intake"
        title = f"任务入口预览 - {report_id.removeprefix('intake-preview-')}"

    return category, title


def _deserialize_eval_trials(case_id: str, payload: Mapping[str, Any]) -> tuple[StoredEvalTrial, ...]:
    stored_trials: list[StoredEvalTrial] = []
    for item in payload.get("trials", ()):
        if not isinstance(item, Mapping):
            continue
        notes = tuple(str(note) for note in item.get("notes", ()) if str(note))
        run_summary_payload = item.get("run_summary")
        run_summary = deserialize_summary(dict(run_summary_payload)) if isinstance(run_summary_payload, Mapping) else None
        run_request = item.get("run_request")
        run_request_metadata = {}
        if isinstance(run_request, Mapping):
            metadata_payload = run_request.get("metadata")
            if isinstance(metadata_payload, Mapping):
                run_request_metadata = dict(metadata_payload)
        stored_trials.append(
            StoredEvalTrial(
                trial_id=str(item.get("trial_id", "")),
                case_id=case_id,
                label=notes[0] if notes else "unlabeled",
                harness_profile=str(item.get("harness_profile") or "custom"),
                run_summary=run_summary,
                notes=notes,
                run_request_metadata=run_request_metadata,
            )
        )
    return tuple(stored_trials)


def _deserialize_eval_report(
    artifact: ReportArtifactSummary,
    payload: Mapping[str, Any],
) -> StoredEvalReport:
    aggregate_metrics = {
        str(item["name"]): item.get("value")
        for item in payload.get("aggregate_metrics", ())
        if isinstance(item, Mapping) and "name" in item
    }
    comparison_views = {
        str(item["name"]): dict(item.get("items", {}))
        for item in payload.get("comparison_views", ())
        if isinstance(item, Mapping) and "name" in item
    }
    tags: set[str] = set()
    signals: set[str] = set()
    stored_cases: list[StoredEvalCase] = []
    for case_result in payload.get("case_results", ()):
        if not isinstance(case_result, Mapping):
            continue
        summary_payload = case_result.get("summary", {})
        summary = dict(summary_payload) if isinstance(summary_payload, Mapping) else {}
        tags.update(str(item) for item in summary.get("task_tags", ()) if str(item))
        signals.update(str(item) for item in summary.get("harness_signals", ()) if str(item))
        case_id = str(case_result.get("case_id", "unknown-case"))
        stored_cases.append(
            StoredEvalCase(
                case_id=case_id,
                summary=summary,
                trials=_deserialize_eval_trials(case_id, case_result),
            )
        )
    return StoredEvalReport(
        report_id=artifact.report_id,
        title=artifact.title,
        suite_id=str(payload.get("suite_id", artifact.report_id)),
        html_path=artifact.html_path,
        markdown_path=artifact.markdown_path,
        json_path=artifact.json_path,
        updated_at=artifact.updated_at,
        aggregate_metrics=aggregate_metrics,
        comparison_views=comparison_views,
        case_count=len(stored_cases),
        task_tags=tuple(sorted(tags)),
        harness_signals=tuple(sorted(signals)),
        case_results=tuple(stored_cases),
        is_portal_live=_is_portal_live_eval_id(artifact.report_id, str(payload.get("suite_id", ""))),
    )



