from __future__ import annotations

from dataclasses import dataclass
import json
import os

from repo_harness_lab.agents.base import BaseAgentAdapter
from repo_harness_lab.config.settings import Settings, load_settings
from repo_harness_lab.domain.run_models import (
    AgentExecutionResult,
    ArtifactRef,
    RunRequest,
    RunStatus,
    RunSummary,
    WorkspaceSession,
    WorkspaceStatus,
)
from repo_harness_lab.domain.task_spec import TaskSpec
from repo_harness_lab.domain.trace_models import EventType, RunStage
from repo_harness_lab.domain.verifier_models import VerificationStatus, VerifierResult
from repo_harness_lab.reporting.html import HtmlReporter
from repo_harness_lab.reporting.markdown import MarkdownReporter
from repo_harness_lab.runtime.repo_sources import resolve_workspace_source_repo_root
from repo_harness_lab.runtime.workspace import LocalWorkspaceBackend
from repo_harness_lab.shared.clock import utc_now
from repo_harness_lab.shared.files import build_patch, collect_changed_files, ensure_directory
from repo_harness_lab.shared.serialization import to_jsonable
from repo_harness_lab.storage.json_store import JsonRunStore
from repo_harness_lab.storage.run_store import RunRecordStore
from repo_harness_lab.traces.events import new_trace_event
from repo_harness_lab.traces.sink import JsonlTraceSink
from repo_harness_lab.verifiers.base import BaseVerifier


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    run_dir: Path
    events_path: Path
    verifier_results_path: Path
    patch_path: Path
    report_path: Path
    report_html_path: Path
    summary_path: Path


@dataclass(slots=True)
class RunOutcome:
    summary: RunSummary
    verifier_result: VerifierResult | None
    workspace: WorkspaceSession | None
    artifacts: RunArtifacts


@dataclass(slots=True)
class RunOrchestrator:
    agent: BaseAgentAdapter
    verifier: BaseVerifier
    backend: LocalWorkspaceBackend
    run_store: JsonRunStore
    reporter: MarkdownReporter
    html_reporter: HtmlReporter
    settings: Settings

    def __init__(
        self,
        agent: BaseAgentAdapter,
        verifier: BaseVerifier,
        backend: LocalWorkspaceBackend | None = None,
        run_store: JsonRunStore | None = None,
        reporter: MarkdownReporter | None = None,
        html_reporter: HtmlReporter | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.backend = backend or LocalWorkspaceBackend(settings=self.settings)
        self.run_store = run_store or JsonRunStore(settings=self.settings)
        self.reporter = reporter or MarkdownReporter()
        self.html_reporter = html_reporter or HtmlReporter()
        self.agent = agent
        self.verifier = verifier
        self.settings.paths.ensure_runtime_directories()

    def run(self, task: TaskSpec, request: RunRequest) -> RunOutcome:
        started_at = utc_now()
        run_dir = ensure_directory(self.settings.paths.runs_dir / request.run_id)
        artifacts = RunArtifacts(
            run_dir=run_dir,
            events_path=run_dir / "events.jsonl",
            verifier_results_path=run_dir / "verifier_results.json",
            patch_path=run_dir / "patch.diff",
            report_path=run_dir / "report.md",
            report_html_path=run_dir / "report.html",
            summary_path=run_dir / "summary.json",
        )
        trace_sink = JsonlTraceSink(artifacts.events_path)
        trace_sink.append(
            new_trace_event(
                request.run_id,
                event_type=EventType.RUN_STARTED,
                stage=RunStage.PREPARATION,
            )
        )

        workspace: WorkspaceSession | None = None
        verifier_result: VerifierResult | None = None
        changed_files: tuple[str, ...] = ()
        patch_diff = ""
        status = RunStatus.RUNNING
        verifier_outcome = "not_run"
        agent_result = AgentExecutionResult()
        agent_notes: list[str] = []
        verifier_notes: list[str] = []
        runtime_notes: list[str] = []

        try:
            workspace = self.backend.prepare(task, request)
            workspace.status = WorkspaceStatus.ACTIVE
            trace_sink.append(
                new_trace_event(
                    request.run_id,
                    event_type=EventType.WORKSPACE_PREPARED,
                    stage=RunStage.WORKSPACE,
                    payload={"workspace_id": workspace.workspace_id, "repo_root": str(workspace.repo_root)},
                )
            )

            self._run_setup_steps(task, request, workspace, trace_sink)

            trace_sink.append(
                new_trace_event(
                    request.run_id,
                    event_type=EventType.AGENT_INVOKED,
                    stage=RunStage.AGENT,
                    payload={"agent": request.agent_profile.name},
                )
            )
            agent_result = self.agent.execute(task, request, workspace)
            for event in agent_result.events:
                trace_sink.append(event)
            agent_notes.extend(agent_result.notes)

            changed_files = self._collect_changed_files(task, workspace)
            for relative_path in changed_files:
                trace_sink.append(
                    new_trace_event(
                        request.run_id,
                        event_type=EventType.FILE_CHANGED,
                        stage=RunStage.AGENT,
                        payload={"path": relative_path},
                    )
                )

            trace_sink.append(
                new_trace_event(
                    request.run_id,
                    event_type=EventType.VERIFIER_STARTED,
                    stage=RunStage.VERIFICATION,
                )
            )
            verifier_result = self.verifier.verify(task, request, workspace)
            verifier_outcome = verifier_result.status.value
            self._write_json(artifacts.verifier_results_path, verifier_result)
            trace_sink.append(
                new_trace_event(
                    request.run_id,
                    event_type=EventType.VERIFIER_FINISHED,
                    stage=RunStage.VERIFICATION,
                    payload={"status": verifier_result.status.value},
                )
            )
            if verifier_result.status is not VerificationStatus.PASSED:
                verifier_notes.extend(_verifier_failure_notes(verifier_result))
            status = RunStatus.SUCCEEDED if verifier_result.status is VerificationStatus.PASSED else RunStatus.FAILED
        except Exception as exc:
            status = RunStatus.FAILED
            runtime_notes.append(str(exc))
        finally:
            if workspace is not None:
                try:
                    if not changed_files:
                        changed_files = self._collect_changed_files(task, workspace)
                    patch_diff = self._build_patch(task, workspace)
                except Exception as exc:
                    runtime_notes.append(f"patch diff failed: {exc}")
                try:
                    self.backend.cleanup(workspace)
                except Exception as exc:
                    runtime_notes.append(f"cleanup failed: {exc}")

        self._write_text(artifacts.patch_path, patch_diff)
        finished_at = utc_now()
        artifact_index = self._build_artifact_index(artifacts, verifier_result)
        notes = _dedupe_notes((*verifier_notes, *runtime_notes, *agent_notes))
        summary = RunSummary(
            run_id=request.run_id,
            task_id=task.task_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            cost_summary=agent_result.cost_summary,
            changed_files=changed_files,
            verifier_outcome=verifier_outcome,
            artifact_index=artifact_index,
            notes=notes,
            metadata=self._build_summary_metadata(task, request, workspace),
        )
        self.run_store.save_summary(summary)
        trace_sink.append(
            new_trace_event(
                request.run_id,
                event_type=EventType.RUN_FINISHED,
                stage=RunStage.FINALIZATION,
                payload={"status": status.value, "notes": list(notes)},
            )
        )
        self._write_reports(request.run_id, artifacts)
        return RunOutcome(summary=summary, verifier_result=verifier_result, workspace=workspace, artifacts=artifacts)

    def _run_setup_steps(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession,
        trace_sink: JsonlTraceSink,
    ) -> None:
        for step in task.setup_steps:
            record = self.backend.run_command(workspace, _shell_command(step))
            trace_sink.append(
                new_trace_event(
                    request.run_id,
                    event_type=EventType.COMMAND_EXECUTED,
                    stage=RunStage.WORKSPACE,
                    payload=to_jsonable(record),
                )
            )
            if record.exit_code != 0:
                raise RuntimeError(f"setup step failed with exit code {record.exit_code}: {step}")

    def _collect_changed_files(self, task: TaskSpec, workspace: WorkspaceSession) -> tuple[str, ...]:
        source_repo = resolve_workspace_source_repo_root(task, workspace)
        if not source_repo.exists() or not workspace.repo_root.exists():
            return ()
        return collect_changed_files(source_repo, workspace.repo_root)

    def _build_patch(self, task: TaskSpec, workspace: WorkspaceSession) -> str:
        source_repo = resolve_workspace_source_repo_root(task, workspace)
        if not source_repo.exists() or not workspace.repo_root.exists():
            return ""
        return build_patch(source_repo, workspace.repo_root)

    def _build_artifact_index(
        self,
        artifacts: RunArtifacts,
        verifier_result: VerifierResult | None,
    ) -> tuple[ArtifactRef, ...]:
        refs = [
            ArtifactRef(name="events", path=str(artifacts.events_path), media_type="application/jsonl"),
            ArtifactRef(name="patch", path=str(artifacts.patch_path), media_type="text/x-diff"),
            ArtifactRef(name="report_html", path=str(artifacts.report_html_path), media_type="text/html"),
            ArtifactRef(name="summary", path=str(artifacts.summary_path), media_type="application/json"),
        ]
        if verifier_result is not None:
            refs.append(
                ArtifactRef(
                    name="verifier_results",
                    path=str(artifacts.verifier_results_path),
                    media_type="application/json",
                )
            )
        return tuple(refs)

    def _write_reports(self, run_id: str, artifacts: RunArtifacts) -> None:
        record_store = RunRecordStore(settings=self.settings, json_store=self.run_store)
        record = record_store.load_run_record(run_id)
        artifacts.report_html_path.write_text(self.html_reporter.render_run_record(record), encoding="utf8")

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf8")

    def _write_text(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf8")

    def _build_summary_metadata(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession | None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "repo_source": task.repo_source.path_or_url,
            "repo_source_kind": task.repo_source.kind.value,
        }
        if task.repo_revision:
            metadata["requested_repo_revision"] = task.repo_revision

        request_metadata = dict(request.metadata)
        eval_context = request_metadata.get("eval_context")
        if isinstance(eval_context, dict) and eval_context:
            metadata["eval_context"] = dict(eval_context)
        benchmark_context = request_metadata.get("benchmark_context")
        if isinstance(benchmark_context, dict) and benchmark_context:
            metadata["benchmark_context"] = dict(benchmark_context)

        if workspace is None:
            return metadata

        workspace_metadata = dict(workspace.metadata)
        source_repo_root = workspace_metadata.get("source_repo_root")
        if source_repo_root:
            metadata["source_repo_root"] = str(source_repo_root)
        requested_revision = workspace_metadata.get("requested_repo_revision")
        if requested_revision:
            metadata["requested_repo_revision"] = str(requested_revision)
        resolved_revision = workspace_metadata.get("resolved_repo_revision") or workspace.base_revision
        if resolved_revision:
            metadata["resolved_repo_revision"] = str(resolved_revision)
        return metadata



def _verifier_failure_notes(verifier_result: VerifierResult) -> tuple[str, ...]:
    notes: list[str] = [str(error) for error in verifier_result.errors if str(error).strip()]
    for item in verifier_result.evidence:
        summary = str(item.summary).strip()
        if not summary:
            continue
        lowered = summary.lower()
        if "failed" in lowered or "missing" in lowered:
            notes.append(summary)
            break
    return _dedupe_notes(notes)



def _dedupe_notes(items: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item).strip()
        if not normalized or normalized in seen:
            continue
        ordered.append(normalized)
        seen.add(normalized)
    return tuple(ordered)



def _shell_command(command: str) -> tuple[str, ...]:
    if os.name == "nt":
        return ("powershell", "-Command", command)
    return ("bash", "-lc", command)
