from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkspaceStatus(StrEnum):
    PENDING = "pending"
    PREPARED = "prepared"
    ACTIVE = "active"
    CLEANED = "cleaned"
    FAILED = "failed"


class CleanupPolicy(StrEnum):
    PRESERVE = "preserve"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class AgentProfile:
    name: str
    provider: str | None = None
    version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SandboxProfile:
    backend_name: str = "local"
    environment: Mapping[str, str] = field(default_factory=dict)
    read_only_paths: tuple[str, ...] = ()
    install_dependencies: bool = False


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    max_steps: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    run_timeout_seconds: int | None = None
    command_timeout_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    allow_shell: bool = True
    allow_network: bool = False
    allowed_tools: tuple[str, ...] = ()
    blocked_tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunRequest:
    run_id: str
    task_id: str
    agent_profile: AgentProfile
    sandbox_profile: SandboxProfile = field(default_factory=SandboxProfile)
    budget_policy: BudgetPolicy = field(default_factory=BudgetPolicy)
    timeout_policy: TimeoutPolicy = field(default_factory=TimeoutPolicy)
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy)
    labels: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkspaceSession:
    workspace_id: str
    repo_root: Path
    base_revision: str | None = None
    status: WorkspaceStatus = WorkspaceStatus.PREPARED
    created_at: datetime = field(default_factory=_utc_now)
    cleanup_policy: CleanupPolicy = CleanupPolicy.DELETE
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    name: str
    path: str
    media_type: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class CostSummary:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    cost_summary: CostSummary = field(default_factory=CostSummary)
    notes: tuple[str, ...] = ()
    events: tuple[TraceEvent, ...] = ()


@dataclass(slots=True)
class RunSummary:
    run_id: str
    task_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    cost_summary: CostSummary = field(default_factory=CostSummary)
    changed_files: tuple[str, ...] = ()
    verifier_outcome: str | None = None
    artifact_index: tuple[ArtifactRef, ...] = ()
    notes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.duration_ms is None and self.finished_at is not None:
            delta = self.finished_at - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
