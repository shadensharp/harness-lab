from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunStage(StrEnum):
    PREPARATION = "preparation"
    WORKSPACE = "workspace"
    AGENT = "agent"
    VERIFICATION = "verification"
    FINALIZATION = "finalization"
    EVALUATION = "evaluation"


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    WORKSPACE_PREPARED = "workspace_prepared"
    AGENT_INVOKED = "agent_invoked"
    MODEL_REQUESTED = "model_requested"
    MODEL_RESPONDED = "model_responded"
    COMMAND_EXECUTED = "command_executed"
    FILE_CHANGED = "file_changed"
    VERIFIER_STARTED = "verifier_started"
    VERIFIER_FINISHED = "verifier_finished"
    RUN_FINISHED = "run_finished"


class ChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class CommandExecutionRecord:
    command: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class FileChangeRecord:
    path: str
    change_type: ChangeType
    diff_excerpt: str = ""
    line_count_delta: int = 0


@dataclass(frozen=True, slots=True)
class TraceEvent:
    event_id: str
    run_id: str
    timestamp: datetime = field(default_factory=_utc_now)
    event_type: EventType = EventType.RUN_STARTED
    stage: RunStage = RunStage.PREPARATION
    payload: Mapping[str, Any] = field(default_factory=dict)
