from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from repo_harness_lab.agents.base import AgentExecutionError, BaseAgentAdapter
from repo_harness_lab.domain.run_models import AgentExecutionResult, RunRequest, WorkspaceSession
from repo_harness_lab.domain.task_spec import TaskSpec
from repo_harness_lab.domain.trace_models import EventType, RunStage
from repo_harness_lab.runtime.executor import CommandExecutor
from repo_harness_lab.traces.events import new_trace_event


@dataclass(slots=True)
class LocalScriptAgentAdapter(BaseAgentAdapter):
    script_command: Sequence[str]
    timeout_seconds: int | None = None
    env: Mapping[str, str] | None = None
    executor: CommandExecutor = field(default_factory=CommandExecutor)

    def execute(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession,
    ) -> AgentExecutionResult:
        record = self.executor.run(
            command=self.script_command,
            cwd=workspace.repo_root,
            timeout_seconds=self.timeout_seconds,
            env=self.env,
        )
        if record.exit_code != 0:
            raise AgentExecutionError(
                f"script agent failed for task {task.task_id} in run {request.run_id}: {record.exit_code}"
            )
        return AgentExecutionResult(
            events=(
                new_trace_event(
                    request.run_id,
                    event_type=EventType.COMMAND_EXECUTED,
                    stage=RunStage.AGENT,
                    payload={
                        "command": list(self.script_command),
                        "cwd": str(workspace.repo_root),
                        "exit_code": record.exit_code,
                    },
                ),
            )
        )
