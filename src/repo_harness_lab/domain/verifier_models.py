from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from repo_harness_lab.domain.trace_models import CommandExecutionRecord


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifierResult:
    verifier_name: str
    status: VerificationStatus
    evidence: tuple[VerificationEvidence, ...] = ()
    command_results: tuple[CommandExecutionRecord, ...] = ()
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status is VerificationStatus.PASSED
