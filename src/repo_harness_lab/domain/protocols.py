from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from repo_harness_lab.domain.eval_models import EvalCase, EvalReport
from repo_harness_lab.domain.run_models import AgentExecutionResult, RunRequest, RunSummary, WorkspaceSession
from repo_harness_lab.domain.task_spec import TaskSpec
from repo_harness_lab.domain.trace_models import CommandExecutionRecord, TraceEvent
from repo_harness_lab.domain.verifier_models import VerifierResult


@runtime_checkable
class TaskLoader(Protocol):
    def load(self, source: str | Path) -> TaskSpec:
        ...


@runtime_checkable
class SandboxBackend(Protocol):
    def prepare(self, task: TaskSpec, request: RunRequest) -> WorkspaceSession:
        ...

    def run_command(
        self,
        workspace: WorkspaceSession,
        command: Sequence[str],
    ) -> CommandExecutionRecord:
        ...

    def cleanup(self, workspace: WorkspaceSession) -> None:
        ...


@runtime_checkable
class AgentAdapter(Protocol):
    def execute(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession,
    ) -> AgentExecutionResult:
        ...


@runtime_checkable
class Verifier(Protocol):
    def verify(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession,
    ) -> VerifierResult:
        ...


@runtime_checkable
class TraceSink(Protocol):
    def append(self, event: TraceEvent) -> None:
        ...


@runtime_checkable
class RunStore(Protocol):
    def save_summary(self, summary: RunSummary) -> None:
        ...

    def load_summary(self, run_id: str) -> RunSummary:
        ...

    def list_runs(self, limit: int = 20) -> list[RunSummary]:
        ...


@runtime_checkable
class EvalRunner(Protocol):
    def run_case(self, case: EvalCase) -> EvalReport:
        ...


@runtime_checkable
class Reporter(Protocol):
    def render_run(self, summary: RunSummary) -> str:
        ...

    def render_eval(self, report: EvalReport) -> str:
        ...
