from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.eval_models import AggregateMetric, CaseResult, ComparisonView, EvalReport
from repo_harness_lab.shared.eval_baselines import BASELINE_KIND_CUSTOM, build_report_baseline_view
from repo_harness_lab.storage.run_store import StoredEvalCase, StoredEvalReport


class EvalBaselineTests(unittest.TestCase):
    def test_build_report_baseline_view_summarizes_metric_and_case_deltas(self) -> None:
        current_report = EvalReport(
            suite_id="current-suite",
            case_results=(
                CaseResult(case_id="case-a", summary={"pass_rate": 1.0}),
                CaseResult(case_id="case-b", summary={"pass_rate": 0.0}),
            ),
            aggregate_metrics=(
                AggregateMetric(name="pass_rate", value=0.5, unit="ratio"),
                AggregateMetric(name="average_duration_ms", value=1200.0, unit="ms"),
                AggregateMetric(name="total_cases", value=2.0, unit="count"),
                AggregateMetric(name="total_trials", value=2.0, unit="count"),
            ),
            comparison_views=(ComparisonView(name="profile_uplift", items={}),),
        )
        baseline_report = StoredEvalReport(
            report_id="baseline-suite",
            title="baseline",
            suite_id="baseline-suite",
            html_path=Path("baseline.html"),
            aggregate_metrics={
                "pass_rate": 0.0,
                "average_duration_ms": 1500.0,
                "total_cases": 2.0,
                "total_trials": 2.0,
            },
            case_results=(
                StoredEvalCase(case_id="case-a", summary={"pass_rate": 0.0}),
                StoredEvalCase(case_id="case-b", summary={"pass_rate": 0.0}),
            ),
        )

        comparison = build_report_baseline_view(
            current_report=current_report,
            baseline_report=baseline_report,
            baseline_kind=BASELINE_KIND_CUSTOM,
        )

        self.assertEqual(comparison.name, "report_baseline")
        self.assertEqual(comparison.items["baseline_report_id"], "baseline-suite")
        self.assertEqual(comparison.items["baseline_kind"], "custom")
        self.assertEqual(comparison.items["pass_rate_delta"], 0.5)
        self.assertEqual(comparison.items["average_duration_delta_ms"], -300.0)
        self.assertEqual(comparison.items["matched_case_count"], 2)
        self.assertEqual(comparison.items["improved_case_ids"], ("case-a",))
        self.assertEqual(comparison.items["regressed_case_ids"], ())


if __name__ == "__main__":
    unittest.main()
