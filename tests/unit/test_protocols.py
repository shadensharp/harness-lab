from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.eval_models import EvalCase, EvalReport
from repo_harness_lab.domain.protocols import (
    AgentAdapter,
    EvalRunner,
    Reporter,
    RunStore,
    SandboxBackend,
    TaskLoader,
    TraceSink,
    Verifier,
)
from repo_harness_lab.domain.run_models import (
    AgentExecutionResult,
    AgentProfile,
    RunRequest,
    RunStatus,
    RunSummary,
    WorkspaceSession,
)
from repo_harness_lab.domain.task_spec import RepoSource, RepoSourceKind, TaskSpec, TaskType
from repo_harness_lab.domain.trace_models import CommandExecutionRecord, TraceEvent
from repo_harness_lab.domain.verifier_models import VerificationStatus, VerifierResult


TASK = TaskSpec(
    task_id="task-001",
    title="Seed skeleton",
    description="Initialize the project skeleton.",
    task_type=TaskType.REQUIREMENT_CHANGE,
    repo_source=RepoSource(kind=RepoSourceKind.LOCAL_PATH, path_or_url="E:/repo-harness-lab"),
)
REQUEST = RunRequest(
    run_id="run-001",
    task_id="task-001",
    agent_profile=AgentProfile(name="dummy"),
)
WORKSPACE = WorkspaceSession(workspace_id="ws-001", repo_root=Path("E:/repo-harness-lab"))


class DummyTaskLoader:
    def load(self, source: str | Path) -> TaskSpec:
        return TASK


class DummySandbox:
    def prepare(self, task: TaskSpec, request: RunRequest) -> WorkspaceSession:
        return WORKSPACE

    def run_command(
        self,
        workspace: WorkspaceSession,
        command: list[str],
    ) -> CommandExecutionRecord:
        return CommandExecutionRecord(command=tuple(command), cwd=str(workspace.repo_root), exit_code=0)

    def cleanup(self, workspace: WorkspaceSession) -> None:
        return None


class DummyAgent:
    def execute(self, task: TaskSpec, request: RunRequest, workspace: WorkspaceSession) -> AgentExecutionResult:
        return AgentExecutionResult()


class DummyVerifier:
    def verify(self, task: TaskSpec, request: RunRequest, workspace: WorkspaceSession) -> VerifierResult:
        return VerifierResult(verifier_name="dummy", status=VerificationStatus.PASSED)


class DummyTraceSink:
    def append(self, event: TraceEvent) -> None:
        return None


class DummyRunStore:
    def save_summary(self, summary: RunSummary) -> None:
        return None

    def load_summary(self, run_id: str) -> RunSummary:
        return RunSummary(
            run_id=run_id,
            task_id="task-001",
            status=RunStatus.SUCCEEDED,
            started_at=WORKSPACE.created_at,
            finished_at=WORKSPACE.created_at,
        )

    def list_runs(self, limit: int = 20) -> list[RunSummary]:
        return []


class DummyEvalRunner:
    def run_case(self, case: EvalCase) -> EvalReport:
        return EvalReport(suite_id="suite-001")


class DummyReporter:
    def render_run(self, summary: RunSummary) -> str:
        return summary.run_id

    def render_eval(self, report: EvalReport) -> str:
        return report.suite_id


class ProtocolTests(unittest.TestCase):
    def test_runtime_checkable_protocols_accept_shape_compatible_implementations(self) -> None:
        self.assertIsInstance(DummyTaskLoader(), TaskLoader)
        self.assertIsInstance(DummySandbox(), SandboxBackend)
        self.assertIsInstance(DummyAgent(), AgentAdapter)
        self.assertIsInstance(DummyVerifier(), Verifier)
        self.assertIsInstance(DummyTraceSink(), TraceSink)
        self.assertIsInstance(DummyRunStore(), RunStore)
        self.assertIsInstance(DummyEvalRunner(), EvalRunner)
        self.assertIsInstance(DummyReporter(), Reporter)


if __name__ == "__main__":
    unittest.main()
