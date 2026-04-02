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
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest
from repo_harness_lab.domain.task_spec import (
    RepoCheckoutMode,
    RepoSource,
    RepoSourceKind,
    SuccessCriteria,
    TaskConstraints,
    TaskSpec,
    TaskType,
)
from repo_harness_lab.domain.verifier_models import VerificationStatus
from repo_harness_lab.runtime.workspace import LocalWorkspaceBackend
from repo_harness_lab.verifiers.draft_completion import (
    DraftCompletionVerifier,
    build_draft_completion_feedback,
)


class DraftCompletionVerifierTests(unittest.TestCase):
    def test_draft_completion_verifier_passes_when_expected_file_and_task_anchors_match(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp_root:
            root = Path(temp_root)
            source_repo = root / "source-repo"
            source_repo.mkdir()
            (source_repo / "README.md").write_text("# Old Title\n", encoding="utf8")

            settings = self._build_settings(root)
            backend = LocalWorkspaceBackend(settings=settings)
            task = self._build_task(source_repo)
            request = RunRequest(
                run_id="run-001",
                task_id=task.task_id,
                agent_profile=AgentProfile(name="dummy"),
            )
            workspace = backend.prepare(task, request)
            (workspace.repo_root / "README.md").write_text(
                "# New Title\n\nThis repo is used for the freeform portal harness demo.\n",
                encoding="utf8",
            )

            result = DraftCompletionVerifier().verify(task, request, workspace)

            self.assertEqual(result.status, VerificationStatus.PASSED)
            feedback = build_draft_completion_feedback(result)
            self.assertTrue(any("expected files matched: 1/1" in item for item in feedback))
            self.assertTrue(any("task anchors matched:" in item and "freeform" in item for item in feedback))

            backend.cleanup(workspace)

    def test_draft_completion_verifier_fails_when_content_does_not_reflect_task_anchors(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp_root:
            root = Path(temp_root)
            source_repo = root / "source-repo"
            source_repo.mkdir()
            (source_repo / "README.md").write_text("# Old Title\n", encoding="utf8")

            settings = self._build_settings(root)
            backend = LocalWorkspaceBackend(settings=settings)
            task = self._build_task(source_repo)
            request = RunRequest(
                run_id="run-002",
                task_id=task.task_id,
                agent_profile=AgentProfile(name="dummy"),
            )
            workspace = backend.prepare(task, request)
            (workspace.repo_root / "README.md").write_text(
                "# New Title\n\nUnrelated summary.\n",
                encoding="utf8",
            )

            result = DraftCompletionVerifier().verify(task, request, workspace)

            self.assertEqual(result.status, VerificationStatus.FAILED)
            self.assertTrue(any("completion score" in item for item in result.errors))
            self.assertTrue(any("task anchors not reflected in changed content" in item for item in result.errors))

            backend.cleanup(workspace)

    @staticmethod
    def _build_task(source_repo: Path) -> TaskSpec:
        sentence = (
            "Please update README.md title and add one line explaining this repo is used for the "
            "freeform portal harness demo."
        )
        return TaskSpec(
            task_id="task-001",
            title="Draft README update",
            description=sentence,
            task_type=TaskType.REQUIREMENT_CHANGE,
            repo_source=RepoSource(
                kind=RepoSourceKind.LOCAL_PATH,
                path_or_url=str(source_repo),
                checkout_mode=RepoCheckoutMode.COPY,
            ),
            constraints=TaskConstraints(editable_paths=("README.md",)),
            success_criteria=SuccessCriteria(
                changed_files=("README.md",),
                behavioral_checks=(sentence,),
            ),
            metadata={"portal_used_draft_verifier": True},
        )

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

    def test_draft_completion_verifier_supports_git_repo_sources(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temp_root:
            root = Path(temp_root)
            source_repo = _init_git_repo(root / "source-repo", {"README.md": "# Old Title\n"})

            settings = self._build_settings(root)
            backend = LocalWorkspaceBackend(settings=settings)
            task = self._build_git_task(source_repo)
            request = RunRequest(
                run_id="run-git",
                task_id=task.task_id,
                agent_profile=AgentProfile(name="dummy"),
            )
            workspace = backend.prepare(task, request)
            (workspace.repo_root / "README.md").write_text(
                "# New Title\n\nThis repo is used for the freeform portal harness demo.\n",
                encoding="utf8",
            )

            result = DraftCompletionVerifier().verify(task, request, workspace)

            self.assertEqual(result.status, VerificationStatus.PASSED)
            self.assertTrue(any("expected files matched: 1/1" in item for item in build_draft_completion_feedback(result)))

            backend.cleanup(workspace)


    @staticmethod
    def _build_git_task(source_repo: Path) -> TaskSpec:
        sentence = (
            "Please update README.md title and add one line explaining this repo is used for the "
            "freeform portal harness demo."
        )
        return TaskSpec(
            task_id="task-git",
            title="Draft README update from git",
            description=sentence,
            task_type=TaskType.REQUIREMENT_CHANGE,
            repo_source=RepoSource(
                kind=RepoSourceKind.GIT_URL,
                path_or_url=source_repo.as_uri(),
                checkout_mode=RepoCheckoutMode.COPY,
            ),
            constraints=TaskConstraints(editable_paths=("README.md",)),
            success_criteria=SuccessCriteria(
                changed_files=("README.md",),
                behavioral_checks=(sentence,),
            ),
            metadata={"portal_used_draft_verifier": True},
        )


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
