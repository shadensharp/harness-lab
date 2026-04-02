from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from repo_harness_lab.domain.protocols import TraceSink
from repo_harness_lab.domain.trace_models import EventType, RunStage, TraceEvent
from repo_harness_lab.shared.files import ensure_directory
from repo_harness_lab.shared.serialization import to_jsonable


class JsonlTraceSink(TraceSink):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        ensure_directory(self.path.parent)

    def append(self, event: TraceEvent) -> None:
        payload = to_jsonable(event)
        with self.path.open("a", encoding="utf8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")



def parse_trace_event(data: dict[str, Any]) -> TraceEvent:
    return TraceEvent(
        event_id=str(data["event_id"]),
        run_id=str(data["run_id"]),
        timestamp=datetime.fromisoformat(data["timestamp"]),
        event_type=EventType(data["event_type"]),
        stage=RunStage(data["stage"]),
        payload=data.get("payload", {}),
    )
