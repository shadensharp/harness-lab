from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.task_spec import RepoSourceKind, TaskDifficulty, TaskSelectionTier, TaskType, TaskInputKind, VerifierStepKind
from repo_harness_lab.tasks.loader import JsonTaskLoader


class JsonTaskLoaderTests(unittest.TestCase):
    def test_loader_reads_json_task_spec(self) -> None:
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "minimal_task.json"
        task = JsonTaskLoader().load(fixture)

        self.assertEqual(task.task_id, "task-001")
        self.assertEqual(task.task_type, TaskType.REQUIREMENT_CHANGE)
        self.assertEqual(task.repo_source.kind, RepoSourceKind.LOCAL_PATH)
        self.assertEqual(task.verifier_plan.steps[0].kind, VerifierStepKind.TEST)
        self.assertEqual(task.success_criteria.required_verifier_steps, ("unit-tests",))
        self.assertEqual(task.benchmark_metadata.tier, TaskSelectionTier.CURATED)
        self.assertEqual(task.benchmark_metadata.difficulty, TaskDifficulty.MEDIUM)
        self.assertIn("cross_file", task.benchmark_metadata.tags)
        self.assertIn("verifier_feedback", task.benchmark_metadata.harness_signals)

    def test_loader_resolves_relative_repo_source_and_input_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_dir = root / "repo"
            repo_dir.mkdir()
            attachment = root / "input.txt"
            attachment.write_text("hello\n", encoding="utf8")
            task_path = root / "task.json"
            task_path.write_text(
                json.dumps(
                    {
                        "task_id": "task-relative",
                        "title": "Relative paths",
                        "description": "Resolve repo and input paths relative to the task file.",
                        "task_type": "requirement_change",
                        "repo_source": {
                            "kind": "local_path",
                            "path_or_url": "./repo",
                            "checkout_mode": "copy"
                        },
                        "inputs": [
                            {
                                "name": "attachment",
                                "kind": "file",
                                "path": "./input.txt"
                            }
                        ],
                        "verifier_plan": {
                            "steps": [
                                {
                                    "name": "unit-tests",
                                    "kind": "test",
                                    "command": [sys.executable, "-V"]
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            task = JsonTaskLoader().load(task_path)

            self.assertEqual(task.repo_source.path_or_url, str(repo_dir.resolve()))
            self.assertEqual(task.inputs.items[0].kind, TaskInputKind.FILE)
            self.assertEqual(task.inputs.items[0].path, str(attachment.resolve()))


if __name__ == "__main__":
    unittest.main()
