from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.evals.official_swebench import (
    build_official_runner_command,
    build_profile_report,
    discover_swebench_result_files,
    export_swebench_predictions,
)
from repo_harness_lab.storage.run_store import StoredEvalCase, StoredEvalReport, StoredEvalTrial, StoredRunRecord
from repo_harness_lab.domain.run_models import RunStatus, RunSummary
from repo_harness_lab.domain.task_spec import HarnessProfile
from repo_harness_lab.shared.clock import utc_now


class SwebenchOfficialIntegrationTests(unittest.TestCase):
    def test_export_predictions_groups_runs_by_profile(self) -> None:
        summary_current = _summary("run-current", "case-001", "sympy__sympy-20590")
        summary_custom = _summary("run-custom", "case-001", "sympy__sympy-20590")
        report = StoredEvalReport(
            report_id="demo-suite",
            title="demo",
            suite_id="demo-suite",
            html_path=Path("demo.html"),
            case_results=(
                StoredEvalCase(
                    case_id="sympy__sympy-20590",
                    trials=(
                        StoredEvalTrial(
                            trial_id="current",
                            case_id="sympy__sympy-20590",
                            harness_profile=HarnessProfile.CURRENT.value,
                            run_summary=summary_current,
                        ),
                        StoredEvalTrial(
                            trial_id="custom",
                            case_id="sympy__sympy-20590",
                            harness_profile=HarnessProfile.CUSTOM.value,
                            run_summary=summary_custom,
                        ),
                    ),
                ),
            ),
        )
        records = {
            "run-current": StoredRunRecord(summary=summary_current, patch_diff="diff --git a/a b/a\n"),
            "run-custom": StoredRunRecord(summary=summary_custom, patch_diff="diff --git a/b b/b\n"),
        }

        with tempfile.TemporaryDirectory() as temp_root:
            bundles = export_swebench_predictions(
                eval_report=report,
                run_record_loader=lambda run_id: records[run_id],
                output_root=Path(temp_root),
                model_name="demo-model",
            )

            self.assertEqual(len(bundles), 2)
            payloads = {
                bundle.harness_profile: [
                    json.loads(line)
                    for line in bundle.predictions_path.read_text(encoding="utf8").splitlines()
                    if line.strip()
                ]
                for bundle in bundles
            }
            self.assertEqual(payloads["current"][0]["instance_id"], "sympy__sympy-20590")
            self.assertEqual(payloads["current"][0]["model_name_or_path"], "demo-model--current")
            self.assertIn("diff --git", payloads["custom"][0]["model_patch"])

    def test_build_official_runner_command_converts_predictions_path_for_wsl_runner(self) -> None:
        command = build_official_runner_command(
            predictions_path=PureWindowsPath(r"E:\repo-harness-lab\runtime\tmp\official-swebench\predictions\current\predictions.jsonl"),
            dataset_name="princeton-nlp/SWE-bench_Verified",
            split="test",
            run_id="demo-suite-current-official",
            instance_ids=("sympy__sympy-20590",),
            max_workers=1,
            cache_level=None,
            clean=False,
            force_rebuild=False,
            open_file_limit=None,
            timeout=None,
            namespace=None,
            log_level=None,
            modal=False,
            runner_command=(
                "wsl.exe",
                "-d",
                "Ubuntu",
                "bash",
                "-lc",
                "python -m swebench.harness.run_evaluation --predictions_path {predictions_path} --run_id {run_id}",
            ),
            python_executable="python",
        )

        self.assertEqual(command[0], "wsl.exe")
        self.assertIn(
            "/mnt/e/repo-harness-lab/runtime/tmp/official-swebench/predictions/current/predictions.jsonl",
            command[-1],
        )
        self.assertNotIn(r"E:\repo-harness-lab", command[-1])

    def test_discover_and_parse_official_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            evaluation_root = root / "evaluation_results" / "demo-run"
            evaluation_root.mkdir(parents=True)
            results_path = evaluation_root / "results.json"
            results_path.write_text(
                json.dumps(
                    {
                        "submitted_instances": 2,
                        "completed_instances": 2,
                        "resolved_instances": 1,
                        "unresolved_instances": 1,
                        "error_instances": 0,
                        "empty_patch_instances": 1,
                        "empty_patch_ids": ["b"],
                        "submitted_ids": ["a", "b"],
                        "resolved_ids": ["a"],
                        "unresolved_ids": ["b"],
                        "error_ids": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            instance_results_path = evaluation_root / "instance_results.jsonl"
            instance_results_path.write_text('{"instance_id":"a","resolved":true}\n', encoding="utf8")

            found_results, found_instance_results = discover_swebench_result_files(
                profile_root=root,
                model_name_or_path="demo-model--current",
                run_id="demo-suite-current-official",
            )
            profile_report = build_profile_report(
                bundle=type("Bundle", (), {
                    "harness_profile": "current",
                    "model_name_or_path": "demo-model--current",
                    "predictions_path": root / "predictions.jsonl",
                    "submitted_ids": ("a", "b"),
                })(),
                run_id="demo-suite-current-official",
                command=("python", "-m", "swebench.harness.run_evaluation"),
                command_exit_code=0,
                stdout_path=root / "stdout.txt",
                stderr_path=root / "stderr.txt",
                results_path=found_results,
                instance_results_path=found_instance_results,
                summary_payload=json.loads(results_path.read_text(encoding="utf8")),
            )

            self.assertEqual(found_results, results_path)
            self.assertEqual(found_instance_results, instance_results_path)
            self.assertEqual(profile_report.resolved_instances, 1)
            self.assertEqual(profile_report.unresolved_instances, 1)
            self.assertEqual(profile_report.empty_patch_instances, 1)
            self.assertEqual(profile_report.empty_patch_ids, ("b",))
            self.assertAlmostEqual(profile_report.resolution_rate or 0.0, 0.5)


def _summary(run_id: str, task_id: str, instance_id: str) -> RunSummary:
    now = utc_now()
    return RunSummary(
        run_id=run_id,
        task_id=task_id,
        status=RunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        verifier_outcome="passed",
        metadata={"benchmark_context": {"instance_id": instance_id}},
    )


if __name__ == "__main__":
    unittest.main()

