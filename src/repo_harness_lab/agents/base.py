from __future__ import annotations

from abc import ABC, abstractmethod

from repo_harness_lab.domain.run_models import AgentExecutionResult, RunRequest, WorkspaceSession
from repo_harness_lab.domain.task_spec import TaskSpec


class AgentExecutionError(RuntimeError):
    pass


class BaseAgentAdapter(ABC):
    @abstractmethod
    def execute(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession,
    ) -> AgentExecutionResult:
        ...


class NoOpAgentAdapter(BaseAgentAdapter):
    def execute(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession,
    ) -> AgentExecutionResult:
        return AgentExecutionResult()
