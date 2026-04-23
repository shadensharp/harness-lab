from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.cli.main import main
from repo_harness_lab.domain.run_models import RunStatus, RunSummary
from repo_harness_lab.domain.task_spec import HarnessProfile
from repo_harness_lab.shared.clock import utc_now
from repo_harness_lab.shared.serialization import to_jsonable


class CliSwebenchOfficialTests(unittest.TestCase):
    def test_grade_swebench_official_exports_predictions_and_writes_reports(self) -> None:
        exit_code, payload, report_payload, artifacts_exist = _run_grade_swebench_official(use_runner_file=False)

        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dataset_name"], "princeton-nlp/SWE-bench_Verified")
        self.assertEqual(len(payload["profile_reports"]), 2)
        self.assertTrue(artifacts_exist["markdown_report_path"])
        self.assertTrue(artifacts_exist["html_report_path"])
        self.assertTrue(artifacts_exist["failure_analysis_json_path"])
        self.assertTrue(artifacts_exist["failure_analysis_markdown_path"])
        self.assertEqual(report_payload["benchmark_kind"], "swebench_official")
        self.assertEqual(report_payload["profile_reports"][0]["resolved_instances"], 1)

    def test_grade_swebench_official_accepts_runner_command_file(self) -> None:
        exit_code, payload, report_payload, _ = _run_grade_swebench_official(use_runner_file=True)

        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(report_payload["benchmark_kind"], "swebench_official")
        self.assertEqual(report_payload["profile_reports"][0]["resolved_instances"], 1)


def _run_grade_swebench_official(
    *,
    use_runner_file: bool,
) -> tuple[int, dict[str, object], dict[str, object], dict[str, bool]]:
    with tempfile.TemporaryDirectory() as temp_root:
        root = Path(temp_root)
        runtime_root = root / "runtime"
        reports_dir = runtime_root / "reports"
        runs_dir = runtime_root / "runs"
        reports_dir.mkdir(parents=True)
        runs_dir.mkdir(parents=True)

        current_summary = _write_run(runs_dir, "run-current", "sympy__sympy-20590", "diff --git a/a b/a\n")
        custom_summary = _write_run(runs_dir, "run-custom", "sympy__sympy-20590", "diff --git a/b b/b\n")
        report_path = reports_dir / "demo-suite.json"
        report_path.write_text(
            json.dumps(
                {
                    "suite_id": "demo-suite",
                    "case_results": [
                        {
                            "case_id": "sympy__sympy-20590",
                            "summary": {},
                            "trials": [
                                {
                                    "trial_id": "trial-current",
                                    "harness_profile": HarnessProfile.CURRENT.value,
                                    "run_summary": to_jsonable(current_summary),
                                    "run_request": {"metadata": {}},
                                },
                                {
                                    "trial_id": "trial-custom",
                                    "harness_profile": HarnessProfile.CUSTOM.value,
                                    "run_summary": to_jsonable(custom_summary),
                                    "run_request": {"metadata": {}},
                                },
                            ],
                        }
                    ],
                    "aggregate_metrics": [],
                    "comparison_views": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf8",
        )
        (reports_dir / "demo-suite.html").write_text("<html></html>", encoding="utf8")

        fake_runner = [
            sys.executable,
            "-c",
            (
                "import json\n"
                "from pathlib import Path\n"
                "preds=[json.loads(line) for line in Path(r'{predictions_path}').read_text(encoding='utf8').splitlines() if line.strip()]\n"
                "root=Path.cwd()/'evaluation_results'/'smoke'\n"
                "root.mkdir(parents=True, exist_ok=True)\n"
                "submitted=[item['instance_id'] for item in preds]\n"
                "report={'submitted_instances': len(submitted), 'completed_instances': len(submitted), 'resolved_instances': len(submitted), 'unresolved_instances': 0, 'error_instances': 0, 'submitted_ids': submitted, 'resolved_ids': submitted, 'unresolved_ids': [], 'error_ids': []}\n"
                "(root/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')\n"
                "(root/'instance_results.jsonl').write_text('\\n'.join(json.dumps({'instance_id': item['instance_id'], 'resolved': True}, ensure_ascii=False) for item in preds) + ('\\n' if preds else ''), encoding='utf8')\n"
            ),
        ]
        command = [
            "grade-swebench-official",
            "demo-suite",
            "--model-name",
            "demo-model",
        ]
        if use_runner_file:
            runner_path = root / "official-runner-command.json"
            runner_path.write_text(json.dumps(fake_runner), encoding="utf-8-sig")
            command.extend(["--official-runner-command-file", str(runner_path)])
        else:
            command.extend(["--official-runner-command-json", json.dumps(fake_runner)])

        env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root)}
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            with patch.dict(os.environ, env, clear=False):
                exit_code = main(command)

        payload = json.loads(buffer.getvalue())
        report_payload = json.loads(Path(payload["artifacts"]["json_report_path"]).read_text(encoding="utf8"))
        artifacts_exist = {
            name: bool(path) and Path(path).exists()
            for name, path in payload["artifacts"].items()
            if isinstance(name, str)
        }
        return exit_code, payload, report_payload, artifacts_exist


def _write_run(runs_dir: Path, run_id: str, instance_id: str, patch_text: str) -> RunSummary:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    now = utc_now()
    summary = RunSummary(
        run_id=run_id,
        task_id=instance_id,
        status=RunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        verifier_outcome="passed",
        metadata={"benchmark_context": {"instance_id": instance_id}},
    )
    (run_dir / "summary.json").write_text(json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2), encoding="utf8")
    (run_dir / "patch.diff").write_text(patch_text, encoding="utf8")
    return summary


if __name__ == "__main__":
    unittest.main()
