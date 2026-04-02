from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.config.settings import AppPaths, Settings
from repo_harness_lab.domain.run_models import RunStatus, RunSummary
from repo_harness_lab.storage.json_store import JsonRunStore


class JsonRunStoreTests(unittest.TestCase):
    def test_store_saves_and_loads_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            settings = Settings(
                paths=AppPaths(
                    project_root=root,
                    runtime_root=root / "runtime",
                    runs_dir=root / "runtime" / "runs",
                    reports_dir=root / "runtime" / "reports",
                    tmp_dir=root / "runtime" / "tmp",
                    examples_dir=root / "examples",
                    tests_dir=root / "tests",
                ),
                python_executable=sys.executable,
                keep_workspaces=False,
            )
            store = JsonRunStore(settings=settings)
            started_at = datetime(2026, 3, 26, 9, 0, tzinfo=timezone.utc)
            summary = RunSummary(
                run_id="run-001",
                task_id="task-001",
                status=RunStatus.SUCCEEDED,
                started_at=started_at,
                finished_at=started_at,
                verifier_outcome="passed",
            )

            store.save_summary(summary)
            loaded = store.load_summary("run-001")
            listed = store.list_runs(limit=5)

            self.assertEqual(loaded.run_id, summary.run_id)
            self.assertEqual(loaded.verifier_outcome, "passed")
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].run_id, "run-001")


if __name__ == "__main__":
    unittest.main()
