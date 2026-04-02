from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class ModelMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: ModelMessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    content: str
    model: str | None = None
    finish_reason: str | None = None
    response_id: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


class ProviderRequestError(RuntimeError):
    pass


@runtime_checkable
class TextGenerationProvider(Protocol):
    def generate(self, messages: Sequence[ModelMessage]) -> ProviderResponse:
        ...
