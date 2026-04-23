from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parents[2] / "runtime" / "test-temp"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.agents.adapters.local_script import LocalScriptAgentAdapter
from repo_harness_lab.config.settings import AppPaths, Settings
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest, RunStatus
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
from repo_harness_lab.reporting.markdown import MarkdownReporter
from repo_harness_lab.runtime.runner import RunOrchestrator
from repo_harness_lab.runtime.workspace import LocalWorkspaceBackend
from repo_harness_lab.storage.json_store import JsonRunStore
from repo_harness_lab.verifiers.command import CommandVerifier


class RunOrchestratorTests(unittest.TestCase):
    def test_orchestrator_runs_local_task_and_persists_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp_root:
            root = Path(temp_root)
            source_repo = root / "source-repo"
            source_repo.mkdir()
            (source_repo / "README.md").write_text("hello\n", encoding="utf8")

            settings = Settings(
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
            backend = LocalWorkspaceBackend(settings=settings)
            task = TaskSpec(
                task_id="task-001",
                title="Run the harness",
                description="Create a file and verify it.",
                task_type=TaskType.REQUIREMENT_CHANGE,
                repo_source=RepoSource(
                    kind=RepoSourceKind.LOCAL_PATH,
                    path_or_url=str(source_repo),
                    checkout_mode=RepoCheckoutMode.COPY,
                ),
                verifier_plan=VerifierPlan(
                    steps=(
                        VerifierStep(
                            name="artifact-check",
                            kind=VerifierStepKind.TEST,
                            command=(
                                sys.executable,
                                "-c",
                                "from pathlib import Path; raise SystemExit(0 if Path('generated.txt').read_text(encoding='utf8') == 'ok' else 1)",
                            ),
                        ),
                    ),
                ),
            )
            request = RunRequest(
                run_id="run-001",
                task_id="task-001",
                agent_profile=AgentProfile(name="local-script", provider="local"),
            )
            agent = LocalScriptAgentAdapter(
                script_command=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('generated.txt').write_text('ok', encoding='utf8')",
                ),
            )
            orchestrator = RunOrchestrator(
                agent=agent,
                verifier=CommandVerifier(backend=backend),
                backend=backend,
                run_store=JsonRunStore(settings=settings),
                reporter=MarkdownReporter(),
                settings=settings,
            )

            outcome = orchestrator.run(task, request)
            summary = outcome.summary
            events = outcome.artifacts.events_path.read_text(encoding="utf8").strip().splitlines()
            loaded_summary = JsonRunStore(settings=settings).load_summary("run-001")
            verifier_payload = json.loads(outcome.artifacts.verifier_results_path.read_text(encoding="utf8"))
            patch_text = outcome.artifacts.patch_path.read_text(encoding="utf8")

            self.assertEqual(summary.status, RunStatus.SUCCEEDED)
            self.assertIn("generated.txt", summary.changed_files)
            self.assertTrue(outcome.artifacts.patch_path.exists())
            self.assertFalse(outcome.artifacts.report_path.exists())
            self.assertTrue(outcome.artifacts.report_html_path.exists())
            self.assertTrue(outcome.artifacts.summary_path.exists())
            self.assertTrue(outcome.artifacts.verifier_results_path.exists())
            self.assertGreaterEqual(len(events), 5)
            self.assertEqual(loaded_summary.run_id, "run-001")
            self.assertEqual(verifier_payload["status"], "passed")
            self.assertIn("+++ b/generated.txt", patch_text)
            self.assertIn("补丁预览", outcome.artifacts.report_html_path.read_text(encoding="utf8"))
            self.assertFalse(outcome.workspace.repo_root.parent.exists())

    def test_orchestrator_uses_source_snapshots_for_git_repo_tasks(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp_root:
            root = Path(temp_root)
            source_repo = _init_git_repo(root / "source-repo", {"README.md": "hello\n"})

            settings = Settings(
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
            backend = LocalWorkspaceBackend(settings=settings)
            task = TaskSpec(
                task_id="task-git",
                title="Run the harness from git",
                description="Create a file and verify it.",
                task_type=TaskType.REQUIREMENT_CHANGE,
                repo_source=RepoSource(
                    kind=RepoSourceKind.GIT_URL,
                    path_or_url=source_repo.as_uri(),
                    checkout_mode=RepoCheckoutMode.COPY,
                ),
                verifier_plan=VerifierPlan(
                    steps=(
                        VerifierStep(
                            name="artifact-check",
                            kind=VerifierStepKind.TEST,
                            command=(
                                sys.executable,
                                "-c",
                                "from pathlib import Path; raise SystemExit(0 if Path('generated.txt').read_text(encoding='utf8') == 'ok' else 1)",
                            ),
                        ),
                    ),
                ),
            )
            request = RunRequest(
                run_id="run-git",
                task_id="task-git",
                agent_profile=AgentProfile(name="local-script", provider="local"),
            )
            agent = LocalScriptAgentAdapter(
                script_command=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('generated.txt').write_text('ok', encoding='utf8')",
                ),
            )
            orchestrator = RunOrchestrator(
                agent=agent,
                verifier=CommandVerifier(backend=backend),
                backend=backend,
                run_store=JsonRunStore(settings=settings),
                reporter=MarkdownReporter(),
                settings=settings,
            )

            outcome = orchestrator.run(task, request)
            patch_text = outcome.artifacts.patch_path.read_text(encoding="utf8")

            self.assertEqual(outcome.summary.status, RunStatus.SUCCEEDED)
            self.assertIn("generated.txt", outcome.summary.changed_files)
            self.assertIn("+++ b/generated.txt", patch_text)
            self.assertFalse(outcome.workspace.repo_root.parent.exists())


def _init_git_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    subprocess.run(["git", "config", "user.name", "Repo Harness"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    subprocess.run(["git", "config", "user.email", "repo-harness@example.test"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    for relative_path, content in files.items():
        file_path = path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    return path


if __name__ == "__main__":
    unittest.main()
