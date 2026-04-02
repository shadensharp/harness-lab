from __future__ import annotations

from abc import ABC, abstractmethod

from repo_harness_lab.domain.run_models import RunRequest, WorkspaceSession
from repo_harness_lab.domain.task_spec import TaskSpec
from repo_harness_lab.domain.verifier_models import VerifierResult


class BaseVerifier(ABC):
    @abstractmethod
    def verify(self, task: TaskSpec, request: RunRequest, workspace: WorkspaceSession) -> VerifierResult:
        ...
