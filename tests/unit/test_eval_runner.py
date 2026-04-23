from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.eval_models import EvalCase, EvalRunConfig, EvalSuite
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest, RunStatus, RunSummary
from repo_harness_lab.domain.task_spec import (
    HarnessProfile,
    RepoSource,
    RepoSourceKind,
    TaskBenchmarkMetadata,
    TaskDifficulty,
    TaskSelectionTier,
    TaskSpec,
    TaskType,
)
from repo_harness_lab.evals.runner import SimpleEvalRunner


class DummyTaskLoader:
    def load(self, source: str | Path) -> TaskSpec:
        return TaskSpec(
            task_id="task-001",
            title="Task",
            description="Test task",
            task_type=TaskType.REQUIREMENT_CHANGE,
            repo_source=RepoSource(kind=RepoSourceKind.LOCAL_PATH, path_or_url=str(source)),
            benchmark_metadata=TaskBenchmarkMetadata(
                tier=TaskSelectionTier.CURATED,
                difficulty=TaskDifficulty.HARD,
                tags=("cross_file", "repo_search"),
                harness_signals=("context_management", "verifier_feedback"),
            ),
        )


class SimpleEvalRunnerTests(unittest.TestCase):
    def test_run_suite_aggregates_trials_by_case_label_and_profile(self) -> None:
        captured_requests: list[RunRequest] = []
        started_at = datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc)

        def execute_run(task: TaskSpec, request: RunRequest) -> RunSummary:
            captured_requests.append(request)
            profile = request.metadata["eval_context"]["harness_profile"]
            succeeded = profile != HarnessProfile.CURRENT.value
            duration_ms = 2400 if profile == HarnessProfile.CURRENT.value else 1200
            notes = ("missing repository context to find the target file",) if not succeeded else ()
            return RunSummary(
                run_id=request.run_id,
                task_id=task.task_id,
                status=RunStatus.SUCCEEDED if succeeded else RunStatus.FAILED,
                started_at=started_at,
                finished_at=started_at,
                duration_ms=duration_ms,
                verifier_outcome="passed" if succeeded else "failed",
                notes=notes,
            )

        suite = EvalSuite(
            suite_id="suite-001",
            cases=(
                EvalCase(
                    case_id="case-001",
                    task_spec_ref="task.json",
                    run_matrix=(
                        EvalRunConfig(
                            label="baseline",
                            harness_profile=HarnessProfile.CURRENT,
                            request=RunRequest(
                                run_id="",
                                task_id="",
                                agent_profile=AgentProfile(name="same-model", provider="local"),
                            ),
                        ),
                        EvalRunConfig(
                            label="custom",
                            harness_profile=HarnessProfile.CUSTOM,
                            request=RunRequest(
                                run_id="",
                                task_id="",
                                agent_profile=AgentProfile(name="same-model", provider="local"),
                            ),
                        ),
                    ),
                ),
            ),
        )

        report = SimpleEvalRunner(task_loader=DummyTaskLoader(), run_request_executor=execute_run).run_suite(suite)

        self.assertEqual(report.suite_id, "suite-001")
        self.assertEqual(len(report.case_results), 1)
        self.assertEqual(report.case_results[0].summary["trial_count"], 2)
        self.assertEqual(report.case_results[0].summary["passed_trials"], 1)
        self.assertEqual(report.case_results[0].summary["benchmark_tier"], "curated")
        self.assertIn("cross_file", report.case_results[0].summary["task_tags"])
        metrics = {metric.name: metric.value for metric in report.aggregate_metrics}
        self.assertEqual(metrics["total_trials"], 2.0)
        self.assertAlmostEqual(metrics["pass_rate"], 0.5)
        self.assertEqual(len(captured_requests), 2)
        self.assertEqual(captured_requests[0].task_id, "task-001")
        self.assertTrue(captured_requests[0].run_id.startswith("run-"))
        self.assertIn("eval_suite:suite-001", captured_requests[0].labels)
        self.assertIn("harness_profile:current", captured_requests[0].labels)

        comparison_views = {view.name: view.items for view in report.comparison_views}
        label_view = comparison_views["label_summary"]
        profile_view = comparison_views["profile_summary"]
        uplift_view = comparison_views["profile_uplift"]
        failure_view = comparison_views["profile_failure_summary"]
        tag_view = comparison_views["tag_profile_summary"]
        signal_view = comparison_views["signal_profile_summary"]

        self.assertEqual(label_view["baseline"]["harness_profile"], "current")
        self.assertEqual(profile_view["current"]["passed_trials"], 0)
        self.assertEqual(profile_view["custom"]["passed_trials"], 1)
        self.assertEqual(uplift_view["baseline_profile"], "current")
        self.assertEqual(uplift_view["custom"]["pass_rate_delta"], 1.0)
        self.assertEqual(uplift_view["custom"]["average_duration_delta_ms"], -1200.0)
        self.assertEqual(failure_view["current"]["failed_trials"], 1)
        self.assertEqual(
            failure_view["current"]["top_reasons"][0]["reason"],
            "missing repository context to find the target file",
        )
        self.assertEqual(tag_view["cross_file"]["profiles"]["custom"]["average_case_pass_rate"], 1.0)
        self.assertEqual(signal_view["context_management"]["profiles"]["current"]["average_case_pass_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
