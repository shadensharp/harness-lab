from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.evals.benchmark_loader import JsonRepoBenchmarkLoader


class JsonRepoBenchmarkLoaderTests(unittest.TestCase):
    def test_loader_reads_manifest_and_resolves_nested_task_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_root = root / "repo"
            repo_root.mkdir()
            manifest_path = root / "benchmark.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "benchmark_id": "swe-bench-sample",
                        "metric_name": "resolved_rate",
                        "score_semantics": "pass_rate_over_materialized_cases",
                        "official_metric_equivalent": False,
                        "cases": [
                            {
                                "instance_id": "swe-bench-001",
                                "source_url": "https://example.test/swe-bench/001",
                                "task": {
                                    "task_id": "task-001",
                                    "title": "Pinned benchmark task",
                                    "description": "Run a benchmark case from a manifest.",
                                    "task_type": "requirement_change",
                                    "repo_source": {
                                        "kind": "local_path",
                                        "path_or_url": "./repo",
                                        "checkout_mode": "copy"
                                    },
                                    "verifier_plan": {
                                        "steps": [
                                            {
                                                "name": "noop",
                                                "kind": "test",
                                                "command": [sys.executable, "-c", "raise SystemExit(0)"]
                                            }
                                        ]
                                    }
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            suite = JsonRepoBenchmarkLoader().load(manifest_path)

            self.assertEqual(suite.benchmark_id, "swe-bench-sample")
            self.assertEqual(suite.metric_name, "resolved_rate")
            self.assertEqual(suite.score_semantics, "pass_rate_over_materialized_cases")
            self.assertFalse(suite.official_metric_equivalent)
            self.assertEqual(suite.cases[0].instance_id, "swe-bench-001")
            self.assertEqual(suite.cases[0].source_url, "https://example.test/swe-bench/001")
            self.assertEqual(suite.cases[0].task.repo_source.path_or_url, str(repo_root.resolve()))

    def test_loader_supports_task_ref_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_root = root / "repo"
            repo_root.mkdir()
            task_path = root / "tasks" / "task.json"
            task_path.parent.mkdir()
            task_path.write_text(
                json.dumps(
                    {
                        "task_id": "task-ref-001",
                        "title": "Task Ref Benchmark Task",
                        "description": "Load task spec from an external task file.",
                        "task_type": "requirement_change",
                        "repo_source": {
                            "kind": "local_path",
                            "path_or_url": "../repo",
                            "checkout_mode": "copy",
                        },
                        "verifier_plan": {
                            "steps": [
                                {
                                    "name": "noop",
                                    "kind": "test",
                                    "command": [sys.executable, "-c", "raise SystemExit(0)"],
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            manifest_path = root / "benchmark.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "benchmark_id": "task-ref-benchmark",
                        "metric_name": "task_pass_rate",
                        "cases": [
                            {
                                "instance_id": "task-ref-001",
                                "task_ref": "tasks/task.json",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            suite = JsonRepoBenchmarkLoader().load(manifest_path)

            self.assertEqual(suite.benchmark_id, "task-ref-benchmark")
            self.assertEqual(suite.score_semantics, "pass_rate_over_materialized_cases")
            self.assertFalse(suite.official_metric_equivalent)
            self.assertEqual(suite.cases[0].task.task_id, "task-ref-001")
            self.assertEqual(suite.cases[0].task.repo_source.path_or_url, str(repo_root.resolve()))


if __name__ == "__main__":
    unittest.main()
