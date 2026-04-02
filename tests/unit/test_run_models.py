from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.run_models import RunStatus, RunSummary


class RunSummaryTests(unittest.TestCase):
    def test_run_summary_derives_duration_when_finished_at_is_present(self) -> None:
        started_at = datetime(2026, 3, 26, 8, 0, tzinfo=timezone.utc)
        finished_at = started_at + timedelta(seconds=3)

        summary = RunSummary(
            run_id="run-001",
            task_id="task-001",
            status=RunStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
        )

        self.assertEqual(summary.duration_ms, 3000)
        self.assertTrue(summary.is_terminal)


if __name__ == "__main__":
    unittest.main()
