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
from repo_harness_lab.evals.swebench_exporter import export_swebench_manifest


class SwebenchExporterTests(unittest.TestCase):
    def test_exporter_converts_jsonl_instances_into_benchmark_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_path = root / "swebench.jsonl"
            output_path = root / "swebench.manifest.json"
            source_path.write_text(
                json.dumps(
                    {
                        "instance_id": "django__django-10001",
                        "repo": "django/django",
                        "base_commit": "abc1234",
                        "problem_statement": "Fix the failing behavior in the admin changelist.",
                        "hints_text": "Focus on the queryset construction.",
                        "FAIL_TO_PASS": ["tests/admin_views/test_changelist.py::test_regression"],
                        "PASS_TO_PASS": ["tests/admin_views/test_actions.py::test_existing_behavior"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf8",
            )

            suite = export_swebench_manifest(
                source_path,
                output_path=output_path,
                benchmark_id="swe-bench-verified-sample",
                default_verifier_command=(sys.executable, "-c", "raise SystemExit(0)"),
                default_editable_paths=("django", "tests"),
                default_setup_steps=("python -V",),
            )
            loaded = JsonRepoBenchmarkLoader().load(output_path)
            case = loaded.cases[0]

            self.assertEqual(suite.benchmark_id, "swe-bench-verified-sample")
            self.assertTrue(output_path.exists())
            self.assertEqual(loaded.metric_name, "resolved_rate")
            self.assertEqual(loaded.score_semantics, "pass_rate_over_materialized_cases")
            self.assertFalse(loaded.official_metric_equivalent)
            self.assertEqual(len(loaded.cases), 1)
            self.assertEqual(case.instance_id, "django__django-10001")
            self.assertEqual(case.task.repo_source.path_or_url, "https://github.com/django/django.git")
            self.assertEqual(case.task.repo_revision, "abc1234")
            self.assertEqual(case.task.task_type.value, "bug_fix")
            self.assertEqual(case.task.setup_steps, ("python -V",))
            self.assertEqual(case.task.constraints.editable_paths, ("django", "tests"))
            self.assertEqual(case.task.success_criteria.required_verifier_steps, ("benchmark-check",))
            self.assertEqual(
                case.task.verifier_plan.steps[0].command,
                (sys.executable, "-c", "raise SystemExit(0)"),
            )
            self.assertEqual(case.task.metadata["benchmark_context"]["repo"], "django/django")
            self.assertIn("external_benchmark", case.task.benchmark_metadata.tags)


if __name__ == "__main__":
    unittest.main()
