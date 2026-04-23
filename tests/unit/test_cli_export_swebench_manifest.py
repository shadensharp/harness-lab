from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.cli.main import main
from repo_harness_lab.evals.benchmark_loader import JsonRepoBenchmarkLoader


class CliExportSwebenchManifestTests(unittest.TestCase):
    def test_export_swebench_manifest_command_writes_loadable_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_path = root / "instances.json"
            output_path = root / "exported.manifest.json"
            source_path.write_text(
                json.dumps(
                    {
                        "instances": [
                            {
                                "instance_id": "psf__requests-42",
                                "repo": "psf/requests",
                                "base_commit": "deadbeef",
                                "problem_statement": "Fix the redirect regression.",
                                "FAIL_TO_PASS": ["tests/test_requests.py::test_redirect_regression"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "export-swebench-manifest",
                        str(source_path),
                        str(output_path),
                        "--benchmark-id",
                        "swe-bench-lite",
                        "--metric-name",
                        "resolved_rate",
                        "--default-verifier-command-json",
                        json.dumps([sys.executable, "-c", "raise SystemExit(0)"]),
                        "--default-editable-path",
                        "src",
                        "--default-setup-step",
                        "python -V",
                    ]
                )

            payload = json.loads(buffer.getvalue())
            suite = JsonRepoBenchmarkLoader().load(output_path)
            case = suite.cases[0]

            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["benchmark_id"], "swe-bench-lite")
            self.assertEqual(payload["benchmark_metric_name"], "resolved_rate")
            self.assertEqual(payload["case_count"], 1)
            self.assertTrue(payload["used_default_verifier_command"])
            self.assertTrue(output_path.exists())
            self.assertEqual(suite.score_semantics, "pass_rate_over_materialized_cases")
            self.assertFalse(suite.official_metric_equivalent)
            self.assertEqual(case.task.repo_source.path_or_url, "https://github.com/psf/requests.git")
            self.assertEqual(case.task.repo_revision, "deadbeef")
            self.assertEqual(case.task.constraints.editable_paths, ("src",))
            self.assertEqual(case.task.setup_steps, ("python -V",))
            self.assertEqual(
                case.task.verifier_plan.steps[0].command,
                (sys.executable, "-c", "raise SystemExit(0)"),
            )


if __name__ == "__main__":
    unittest.main()
