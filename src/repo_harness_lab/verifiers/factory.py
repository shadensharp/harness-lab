from __future__ import annotations

from repo_harness_lab.domain.protocols import SandboxBackend
from repo_harness_lab.domain.task_spec import TaskSpec
from repo_harness_lab.verifiers.base import BaseVerifier
from repo_harness_lab.verifiers.command import CommandVerifier
from repo_harness_lab.verifiers.draft_completion import DraftCompletionVerifier, is_draft_completion_task


def build_verifier(
    *,
    task: TaskSpec,
    backend: SandboxBackend,
    step_names: tuple[str, ...] = (),
) -> BaseVerifier:
    if step_names:
        return CommandVerifier(backend=backend, step_names=step_names)
    if is_draft_completion_task(task):
        return DraftCompletionVerifier()
    return CommandVerifier(backend=backend)
