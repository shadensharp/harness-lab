from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.config.settings import AppPaths, Settings
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest
from repo_harness_lab.domain.task_spec import (
    RepoCheckoutMode,
    RepoSource,
    RepoSourceKind,
    TaskSpec,
    TaskType,
    VerifierPlan,
    VerifierStep,
    VerifierStepKind,
)
from repo_harness_lab.domain.verifier_models import VerificationStatus
from repo_harness_lab.runtime.workspace import LocalWorkspaceBackend
from repo_harness_lab.verifiers.command import CommandVerifier


class CommandVerifierTests(unittest.TestCase):
    def test_command_verifier_runs_selected_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_repo = root / "source-repo"
            source_repo.mkdir()
            (source_repo / "README.md").write_text("hello\n", encoding="utf8")

            settings = self._build_settings(root)
            backend = LocalWorkspaceBackend(settings=settings)
            task = TaskSpec(
                task_id="task-001",
                title="Verify workspace",
                description="Run a deterministic command verifier.",
                task_type=TaskType.REQUIREMENT_CHANGE,
                repo_source=RepoSource(
                    kind=RepoSourceKind.LOCAL_PATH,
                    path_or_url=str(source_repo),
                    checkout_mode=RepoCheckoutMode.COPY,
                ),
                verifier_plan=VerifierPlan(
                    steps=(
                        VerifierStep(
                            name="unit-tests",
                            kind=VerifierStepKind.TEST,
                            command=(sys.executable, "-c", "print('verified')"),
                        ),
                    ),
                ),
            )
            request = RunRequest(
                run_id="run-001",
                task_id="task-001",
                agent_profile=AgentProfile(name="dummy"),
            )
            workspace = backend.prepare(task, request)

            result = CommandVerifier(backend=backend).verify(task, request, workspace)

            self.assertEqual(result.status, VerificationStatus.PASSED)
            self.assertEqual(len(result.command_results), 1)
            self.assertEqual(result.command_results[0].stdout_excerpt.strip(), "verified")

            backend.cleanup(workspace)

    def test_command_verifier_records_failed_command_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_repo = root / "source-repo"
            source_repo.mkdir()
            (source_repo / "README.md").write_text("hello\n", encoding="utf8")

            settings = self._build_settings(root)
            backend = LocalWorkspaceBackend(settings=settings)
            task = TaskSpec(
                task_id="task-002",
                title="Fail verification",
                description="Capture verifier failure reasons.",
                task_type=TaskType.REQUIREMENT_CHANGE,
                repo_source=RepoSource(
                    kind=RepoSourceKind.LOCAL_PATH,
                    path_or_url=str(source_repo),
                    checkout_mode=RepoCheckoutMode.COPY,
                ),
                verifier_plan=VerifierPlan(
                    steps=(
                        VerifierStep(
                            name="unit-tests",
                            kind=VerifierStepKind.TEST,
                            command=(sys.executable, "-c", "raise SystemExit(1)"),
                        ),
                    ),
                ),
            )
            request = RunRequest(
                run_id="run-002",
                task_id="task-002",
                agent_profile=AgentProfile(name="dummy"),
            )
            workspace = backend.prepare(task, request)

            result = CommandVerifier(backend=backend).verify(task, request, workspace)

            self.assertEqual(result.status, VerificationStatus.FAILED)
            self.assertEqual(result.errors, ("unit-tests: command exited with code 1",))
            self.assertEqual(result.command_results[0].exit_code, 1)

            backend.cleanup(workspace)

    @staticmethod
    def _build_settings(root: Path) -> Settings:
        return Settings(
            paths=AppPaths(
                project_root=root,
                runtime_root=root / "runtime",
                runs_dir=root / "runtime" / "runs",
                reports_dir=root / "runtime" / "reports",
                tmp_dir=root / "runtime" / "tmp",
                examples_dir=root / "examples",
                tests_dir=root / "tests",
            ),
            python_executable=sys.executable,
            keep_workspaces=False,
        )


if __name__ == "__main__":
    unittest.main()
