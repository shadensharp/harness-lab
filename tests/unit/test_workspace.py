from __future__ import annotations

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

from repo_harness_lab.config.settings import AppPaths, Settings
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest, WorkspaceStatus
from repo_harness_lab.domain.task_spec import RepoCheckoutMode, RepoSource, RepoSourceKind, TaskSpec, TaskType
from repo_harness_lab.runtime.workspace import LocalWorkspaceBackend


class LocalWorkspaceBackendTests(unittest.TestCase):
    def test_prepare_copies_repo_and_cleanup_removes_workspace(self) -> None:
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
                title="Prepare workspace",
                description="Copy the source repository into an isolated workspace.",
                task_type=TaskType.REQUIREMENT_CHANGE,
                repo_source=RepoSource(
                    kind=RepoSourceKind.LOCAL_PATH,
                    path_or_url=str(source_repo),
                    checkout_mode=RepoCheckoutMode.COPY,
                ),
            )
            request = RunRequest(
                run_id="run-001",
                task_id="task-001",
                agent_profile=AgentProfile(name="dummy"),
            )

            workspace = backend.prepare(task, request)
            copied_file = workspace.repo_root / "README.md"

            self.assertTrue(copied_file.exists())
            self.assertEqual(copied_file.read_text(encoding="utf8"), "hello\n")
            self.assertEqual(workspace.status, WorkspaceStatus.PREPARED)

            command_result = backend.run_command(
                workspace,
                [sys.executable, "-c", "print('workspace-ok')"],
            )
            self.assertEqual(command_result.exit_code, 0)
            self.assertEqual(command_result.stdout_excerpt.strip(), "workspace-ok")

            workspace_root = workspace.repo_root.parent
            backend.cleanup(workspace)

            self.assertFalse(workspace_root.exists())
            self.assertEqual(workspace.status, WorkspaceStatus.CLEANED)

    def test_prepare_clones_git_repo_url_and_cleanup_removes_workspace(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp_root:
            root = Path(temp_root)
            source_repo = _init_git_repo(root / "source-repo", {"README.md": "hello from git\n"})

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
                title="Prepare git workspace",
                description="Clone a git repo into an isolated workspace.",
                task_type=TaskType.REQUIREMENT_CHANGE,
                repo_source=RepoSource(
                    kind=RepoSourceKind.GIT_URL,
                    path_or_url=source_repo.as_uri(),
                    checkout_mode=RepoCheckoutMode.COPY,
                ),
            )
            request = RunRequest(
                run_id="run-git",
                task_id="task-git",
                agent_profile=AgentProfile(name="dummy"),
            )

            workspace = backend.prepare(task, request)
            copied_file = workspace.repo_root / "README.md"
            source_snapshot = Path(str(workspace.metadata.get("source_repo_root") or ""))

            self.assertTrue(copied_file.exists())
            self.assertEqual(copied_file.read_text(encoding="utf8"), "hello from git\n")
            self.assertTrue(source_snapshot.exists())
            self.assertTrue((source_snapshot / "README.md").exists())

            workspace_root = workspace.repo_root.parent
            backend.cleanup(workspace)

            self.assertFalse(workspace_root.exists())
            self.assertEqual(workspace.status, WorkspaceStatus.CLEANED)

    def test_prepare_checks_out_requested_git_revision(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp_root:
            root = Path(temp_root)
            source_repo = _init_git_repo(root / "source-repo", {"README.md": "alpha\n"})
            first_revision = _git_head(source_repo)
            (source_repo / "README.md").write_text("beta\n", encoding="utf8")
            subprocess.run(["git", "add", "README.md"], cwd=source_repo, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
            subprocess.run(["git", "commit", "-m", "second"], cwd=source_repo, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")

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
                task_id="task-git-pin",
                title="Prepare pinned git workspace",
                description="Checkout a pinned git revision into an isolated workspace.",
                task_type=TaskType.REQUIREMENT_CHANGE,
                repo_source=RepoSource(
                    kind=RepoSourceKind.GIT_URL,
                    path_or_url=source_repo.as_uri(),
                    checkout_mode=RepoCheckoutMode.COPY,
                ),
                repo_revision=first_revision,
            )
            request = RunRequest(
                run_id="run-git-pin",
                task_id="task-git-pin",
                agent_profile=AgentProfile(name="dummy"),
            )

            workspace = backend.prepare(task, request)

            self.assertEqual((workspace.repo_root / "README.md").read_text(encoding="utf8"), "alpha\n")
            self.assertEqual(workspace.base_revision, first_revision)
            self.assertEqual(workspace.metadata["resolved_repo_revision"], first_revision)

            workspace_root = workspace.repo_root.parent
            backend.cleanup(workspace)

            self.assertFalse(workspace_root.exists())
            self.assertEqual(workspace.status, WorkspaceStatus.CLEANED)


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


def _git_head(path: Path) -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
