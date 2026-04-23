from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.official_benchmark_models import (
    OfficialBenchmarkEvaluationReport,
    OfficialBenchmarkProfileReport,
)
from repo_harness_lab.domain.run_models import RunStatus, RunSummary
from repo_harness_lab.evals.failure_analysis import analyze_official_failures
from repo_harness_lab.shared.clock import utc_now
from repo_harness_lab.storage.run_store import StoredEvalCase, StoredEvalReport, StoredEvalTrial, StoredRunRecord


class FailureAnalysisTests(unittest.TestCase):
    def test_analyzer_marks_empty_patch_as_no_modification(self) -> None:
        summary = _summary("run-current", "sympy__sympy-20590", changed_files=())
        eval_report = _eval_report(summary, "current")
        official_report = OfficialBenchmarkEvaluationReport(
            benchmark_kind="swebench_official",
            source_report_id="demo-suite",
            dataset_name="princeton-nlp/SWE-bench_Verified",
            profile_reports=(
                OfficialBenchmarkProfileReport(
                    harness_profile="current",
                    model_name_or_path="demo-model--current",
                    run_id="demo-suite-current-official",
                    submitted_instances=1,
                    empty_patch_instances=1,
                    empty_patch_ids=("sympy__sympy-20590",),
                ),
            ),
        )
        records = {"run-current": StoredRunRecord(summary=summary, patch_diff="")}

        analysis = analyze_official_failures(
            official_report=official_report,
            eval_report=eval_report,
            run_record_loader=lambda run_id: records[run_id],
        )

        item = analysis.profile_reports[0].items[0]
        self.assertEqual(analysis.total_failed_instances, 1)
        self.assertEqual(item.main_label, "没有产出修改")
        self.assertEqual(item.probable_cause, "没找到正确文件")

    def test_analyzer_marks_pass_to_pass_failures_as_regressions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            instance_results_path = root / "instance_results.jsonl"
            instance_results_path.write_text(
                json.dumps(
                    {
                        "instance_id": "sympy__sympy-20590",
                        "pass_to_pass_failed": ["tests/existing.py::test_kept_behavior"],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf8",
            )
            summary = _summary("run-custom", "sympy__sympy-20590", changed_files=("sympy/core.py",))
            eval_report = _eval_report(summary, "custom")
            official_report = OfficialBenchmarkEvaluationReport(
                benchmark_kind="swebench_official",
                source_report_id="demo-suite",
                dataset_name="princeton-nlp/SWE-bench_Verified",
                profile_reports=(
                    OfficialBenchmarkProfileReport(
                        harness_profile="custom",
                        model_name_or_path="demo-model--custom",
                        run_id="demo-suite-custom-official",
                        submitted_instances=1,
                        unresolved_instances=1,
                        unresolved_ids=("sympy__sympy-20590",),
                        instance_results_path=str(instance_results_path),
                    ),
                ),
            )
            records = {"run-custom": StoredRunRecord(summary=summary, patch_diff="diff --git a/a b/a\n")}

            analysis = analyze_official_failures(
                official_report=official_report,
                eval_report=eval_report,
                run_record_loader=lambda run_id: records[run_id],
            )

            item = analysis.profile_reports[0].items[0]
            self.assertEqual(item.main_label, "引入回归")
            self.assertEqual(item.probable_cause, "改动过度伤到别处")


def _eval_report(summary: RunSummary, harness_profile: str) -> StoredEvalReport:
    return StoredEvalReport(
        report_id="demo-suite",
        title="demo",
        suite_id="demo-suite",
        html_path=Path("demo.html"),
        case_results=(
            StoredEvalCase(
                case_id="sympy__sympy-20590",
                summary={},
                trials=(
                    StoredEvalTrial(
                        trial_id=f"{harness_profile}-trial",
                        case_id="sympy__sympy-20590",
                        harness_profile=harness_profile,
                        run_summary=summary,
                    ),
                ),
            ),
        ),
    )


def _summary(run_id: str, instance_id: str, *, changed_files: tuple[str, ...]) -> RunSummary:
    now = utc_now()
    return RunSummary(
        run_id=run_id,
        task_id=instance_id,
        status=RunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        verifier_outcome="passed",
        changed_files=changed_files,
        metadata={"benchmark_context": {"instance_id": instance_id}},
    )


if __name__ == "__main__":
    unittest.main()
