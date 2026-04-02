from __future__ import annotations

from typing import Any, Mapping

from repo_harness_lab.domain.trace_models import EventType, RunStage, TraceEvent
from repo_harness_lab.shared.ids import new_id


def new_trace_event(
    run_id: str,
    event_type: EventType,
    stage: RunStage,
    payload: Mapping[str, Any] | None = None,
) -> TraceEvent:
    return TraceEvent(
        event_id=new_id("evt"),
        run_id=run_id,
        event_type=event_type,
        stage=stage,
        payload=payload or {},
    )
