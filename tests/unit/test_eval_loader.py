from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.task_spec import HarnessProfile
from repo_harness_lab.evals.loader import JsonEvalSuiteLoader


class JsonEvalSuiteLoaderTests(unittest.TestCase):
    def test_loader_reads_suite_and_resolves_relative_task_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            task_path = root / "tasks" / "task.json"
            task_path.parent.mkdir()
            task_path.write_text("{}", encoding="utf8")
            suite_path = root / "suite.json"
            suite_path.write_text(
                json.dumps(
                    {
                        "suite_id": "suite-001",
                        "cases": [
                            {
                                "case_id": "case-001",
                                "task_spec_ref": "tasks/task.json",
                                "run_matrix": [
                                    {
                                        "label": "noop",
                                        "harness_profile": "bare",
                                        "request": {
                                            "agent_profile": {
                                                "name": "noop-agent",
                                                "provider": "local",
                                            }
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            suite = JsonEvalSuiteLoader().load(suite_path)

            self.assertEqual(suite.suite_id, "suite-001")
            self.assertEqual(suite.cases[0].case_id, "case-001")
            self.assertEqual(suite.cases[0].task_spec_ref, str(task_path.resolve()))
            self.assertEqual(suite.cases[0].run_matrix[0].request.agent_profile.name, "noop-agent")
            self.assertEqual(suite.cases[0].run_matrix[0].harness_profile, HarnessProfile.BARE)


if __name__ == "__main__":
    unittest.main()
