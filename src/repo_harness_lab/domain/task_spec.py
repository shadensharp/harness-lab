from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class TaskType(StrEnum):
    REQUIREMENT_CHANGE = "requirement_change"
    BUG_FIX = "bug_fix"


class RepoSourceKind(StrEnum):
    LOCAL_PATH = "local_path"
    GIT_URL = "git_url"
    SNAPSHOT = "snapshot"


class RepoCheckoutMode(StrEnum):
    COPY = "copy"
    CLONE = "clone"
    WORKTREE = "worktree"


class TaskInputKind(StrEnum):
    TEXT = "text"
    FILE = "file"
    LOG = "log"
    SCRIPT = "script"
    EXAMPLE = "example"


class VerifierStepKind(StrEnum):
    COMMAND = "command"
    TEST = "test"
    BUILD = "build"
    LINT = "lint"
    ASSERTION = "assertion"


class FailurePolicy(StrEnum):
    STOP_ON_FIRST_FAILURE = "stop_on_first_failure"
    COLLECT_ALL = "collect_all"


class TaskDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class TaskSelectionTier(StrEnum):
    CURATED = "curated"
    ROLLING = "rolling"
    OPEN = "open"


class HarnessProfile(StrEnum):
    BARE = "bare"
    BASIC = "basic"
    FULL = "full"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class RepoSource:
    kind: RepoSourceKind
    path_or_url: str
    default_branch: str = "main"
    checkout_mode: RepoCheckoutMode = RepoCheckoutMode.COPY


@dataclass(frozen=True, slots=True)
class TaskInput:
    name: str
    kind: TaskInputKind
    description: str = ""
    content: str | None = None
    path: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskInputBundle:
    items: tuple[TaskInput, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.items

    def get(self, name: str) -> TaskInput | None:
        for item in self.items:
            if item.name == name:
                return item
        return None


@dataclass(frozen=True, slots=True)
class TaskConstraints:
    allow_network: bool = False
    editable_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    max_runtime_seconds: int | None = None
    max_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class SuccessCriteria:
    required_verifier_steps: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    behavioral_checks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifierStep:
    name: str
    kind: VerifierStepKind
    command: tuple[str, ...] = ()
    required: bool = True
    notes: str = ""


@dataclass(frozen=True, slots=True)
class VerifierPlan:
    steps: tuple[VerifierStep, ...] = ()
    required_passes: int | None = None
    failure_policy: FailurePolicy = FailurePolicy.COLLECT_ALL

    def __post_init__(self) -> None:
        if self.required_passes is None:
            return
        if self.required_passes < 0:
            raise ValueError("required_passes must be non-negative")
        if self.required_passes > len(self.steps):
            raise ValueError("required_passes cannot exceed step count")

    @property
    def effective_required_passes(self) -> int:
        if self.required_passes is not None:
            return self.required_passes
        return sum(1 for step in self.steps if step.required)


@dataclass(frozen=True, slots=True)
class TaskBenchmarkMetadata:
    tier: TaskSelectionTier = TaskSelectionTier.OPEN
    difficulty: TaskDifficulty = TaskDifficulty.MEDIUM
    tags: tuple[str, ...] = ()
    harness_signals: tuple[str, ...] = ()
    owner: str | None = None
    source: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    title: str
    description: str
    task_type: TaskType
    repo_source: RepoSource
    repo_revision: str | None = None
    inputs: TaskInputBundle = field(default_factory=TaskInputBundle)
    constraints: TaskConstraints = field(default_factory=TaskConstraints)
    success_criteria: SuccessCriteria = field(default_factory=SuccessCriteria)
    setup_steps: tuple[str, ...] = ()
    verifier_plan: VerifierPlan = field(default_factory=VerifierPlan)
    benchmark_metadata: TaskBenchmarkMetadata = field(default_factory=TaskBenchmarkMetadata)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def verifier_step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.verifier_plan.steps)
