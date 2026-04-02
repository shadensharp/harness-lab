from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.trace_models import EventType, RunStage
from repo_harness_lab.traces.events import new_trace_event
from repo_harness_lab.traces.sink import JsonlTraceSink


class JsonlTraceSinkTests(unittest.TestCase):
    def test_sink_appends_jsonl_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            path = Path(temp_root) / "events.jsonl"
            sink = JsonlTraceSink(path)
            event = new_trace_event(
                run_id="run-001",
                event_type=EventType.RUN_STARTED,
                stage=RunStage.PREPARATION,
                payload={"message": "started"},
            )

            sink.append(event)
            lines = path.read_text(encoding="utf8").strip().splitlines()
            payload = json.loads(lines[0])

            self.assertEqual(len(lines), 1)
            self.assertEqual(payload["run_id"], "run-001")
            self.assertEqual(payload["event_type"], "run_started")
            self.assertEqual(payload["payload"]["message"], "started")


if __name__ == "__main__":
    unittest.main()
