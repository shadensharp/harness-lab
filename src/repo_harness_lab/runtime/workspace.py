from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from repo_harness_lab.config.settings import Settings, load_settings
from repo_harness_lab.domain.protocols import SandboxBackend
from repo_harness_lab.domain.run_models import CleanupPolicy, RunRequest, WorkspaceSession, WorkspaceStatus
from repo_harness_lab.domain.task_spec import RepoCheckoutMode, TaskSpec
from repo_harness_lab.domain.trace_models import CommandExecutionRecord
from repo_harness_lab.runtime.executor import CommandExecutor
from repo_harness_lab.runtime.repo_sources import materialize_repo_source
from repo_harness_lab.shared.files import copy_directory, ensure_directory, remove_directory
from repo_harness_lab.shared.ids import new_id


@dataclass(slots=True)
class LocalWorkspaceBackend(SandboxBackend):
    settings: Settings
    executor: CommandExecutor

    def __init__(
        self,
        settings: Settings | None = None,
        executor: CommandExecutor | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.executor = executor or CommandExecutor()
        self.settings.paths.ensure_runtime_directories()

    def prepare(self, task: TaskSpec, request: RunRequest) -> WorkspaceSession:
        if task.repo_source.checkout_mode is not RepoCheckoutMode.COPY:
            raise NotImplementedError("LocalWorkspaceBackend currently supports only copy checkout mode")

        source_materialization = materialize_repo_source(
            task.repo_source,
            repo_revision=task.repo_revision,
            settings=self.settings,
            executor=self.executor,
            temp_label=f"source-{request.run_id}",
        )
        source_repo = source_materialization.repo_root.resolve()
        resolved_revision = source_materialization.resolved_revision or task.repo_revision

        workspace_id = new_id("ws")
        tmp_root = ensure_directory(self.settings.paths.tmp_dir)
        workspace_container = tmp_root / workspace_id
        ensure_directory(workspace_container)
        repo_root = workspace_container / source_repo.name
        copy_directory(source_repo, repo_root)

        if source_materialization.cleanup_root is not None:
            source_snapshot_root = workspace_container / "_source"
            copy_directory(source_repo, source_snapshot_root)
            source_materialization.cleanup()
            source_repo = source_snapshot_root

        cleanup_policy = CleanupPolicy.PRESERVE if self.settings.keep_workspaces else CleanupPolicy.DELETE
        return WorkspaceSession(
            workspace_id=workspace_id,
            repo_root=repo_root,
            base_revision=resolved_revision,
            status=WorkspaceStatus.PREPARED,
            cleanup_policy=cleanup_policy,
            metadata={
                "source_repo": task.repo_source.path_or_url,
                "source_repo_root": str(source_repo),
                "source_repo_kind": task.repo_source.kind.value,
                "requested_repo_revision": task.repo_revision,
                "resolved_repo_revision": resolved_revision,
                "run_id": request.run_id,
                "task_id": task.task_id,
            },
        )

    def run_command(
        self,
        workspace: WorkspaceSession,
        command: Sequence[str],
    ) -> CommandExecutionRecord:
        return self.executor.run(command=command, cwd=workspace.repo_root)

    def cleanup(self, workspace: WorkspaceSession) -> None:
        if workspace.cleanup_policy is CleanupPolicy.PRESERVE:
            workspace.status = WorkspaceStatus.CLEANED
            return
        workspace_root = workspace.repo_root.parent
        remove_directory(workspace_root)
        workspace.status = WorkspaceStatus.CLEANED
