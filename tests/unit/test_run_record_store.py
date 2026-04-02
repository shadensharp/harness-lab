from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.config.settings import AppPaths, Settings
from repo_harness_lab.domain.run_models import RunStatus, RunSummary
from repo_harness_lab.domain.trace_models import EventType, RunStage
from repo_harness_lab.storage.json_store import JsonRunStore
from repo_harness_lab.storage.run_store import RunRecordStore
from repo_harness_lab.traces.events import new_trace_event
from repo_harness_lab.traces.sink import JsonlTraceSink


class RunRecordStoreTests(unittest.TestCase):
    def test_load_run_record_compare_runs_and_catalog_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            settings = Settings(
                paths=AppPaths(
                    project_root=root,
                    runtime_root=root / "runtime",
                    runs_dir=root / "runtime" / "runs",
                    reports_dir=root / "runtime" / "reports",
                    tmp_dir=root / "runtime" / "tmp",
                    examples_dir=root / "examples",
                    tests_dir=root / "tests",
                ),
                python_executable=sys.executable,
                keep_workspaces=False,
            )
            json_store = JsonRunStore(settings=settings)
            record_store = RunRecordStore(settings=settings, json_store=json_store)
            started_at = datetime(2026, 3, 26, 11, 0, tzinfo=timezone.utc)

            left = RunSummary(
                run_id="run-left",
                task_id="task-001",
                status=RunStatus.SUCCEEDED,
                started_at=started_at,
                finished_at=started_at,
                changed_files=("a.py",),
                verifier_outcome="passed",
                notes=("left-note",),
            )
            right = RunSummary(
                run_id="run-right",
                task_id="task-001",
                status=RunStatus.FAILED,
                started_at=started_at,
                finished_at=started_at,
                changed_files=("b.py",),
                verifier_outcome="failed",
                notes=("right-note",),
            )
            json_store.save_summary(left)
            json_store.save_summary(right)

            left_sink = JsonlTraceSink(json_store.events_path("run-left"))
            left_sink.append(new_trace_event("run-left", EventType.RUN_STARTED, RunStage.PREPARATION))
            left_sink.append(new_trace_event("run-left", EventType.RUN_FINISHED, RunStage.FINALIZATION))
            right_sink = JsonlTraceSink(json_store.events_path("run-right"))
            right_sink.append(new_trace_event("run-right", EventType.RUN_STARTED, RunStage.PREPARATION))

            json_store.verifier_results_path("run-left").write_text(
                json.dumps(
                    {
                        "verifier_name": "command_verifier",
                        "status": "passed",
                        "evidence": [{"summary": "unit-tests: passed", "details": {}, "artifacts": []}],
                        "command_results": [],
                        "started_at": started_at.isoformat(),
                        "finished_at": started_at.isoformat(),
                        "errors": []
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            json_store.report_path("run-left").write_text("# existing report\n", encoding="utf8")
            json_store.patch_path("run-left").write_text("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n", encoding="utf8")
            settings.paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (settings.paths.reports_dir / "runs-dashboard.html").write_text("<html>dashboard</html>", encoding="utf8")
            (settings.paths.reports_dir / "uplift-dashboard.html").write_text("<html>uplift</html>", encoding="utf8")
            (settings.paths.reports_dir / "suite-alpha.html").write_text("<html>eval</html>", encoding="utf8")
            (settings.paths.reports_dir / "suite-alpha.md").write_text("# eval\n", encoding="utf8")
            (settings.paths.reports_dir / "intake-preview-demo-task.html").write_text("<html>intake</html>", encoding="utf8")
            (settings.paths.reports_dir / "intake-preview-demo-task.json").write_text(
                json.dumps(
                    {
                        "source_path": "demo-intake.json",
                        "task_spec_preview": {"task_id": "demo-task"},
                        "harness_delivery_matrix": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            (settings.paths.reports_dir / "suite-alpha.json").write_text(
                json.dumps(
                    {
                        "suite_id": "suite-alpha",
                        "case_results": [
                            {
                                "case_id": "case-001",
                                "trials": [
                                    {
                                        "trial_id": "case-001-trial-1",
                                        "harness_profile": "basic",
                                        "notes": ["basic-pass"],
                                        "run_summary": {
                                            "run_id": "run-left",
                                            "task_id": "task-001",
                                            "status": "succeeded",
                                            "started_at": started_at.isoformat(),
                                            "finished_at": started_at.isoformat(),
                                            "duration_ms": 1200,
                                            "cost_summary": {},
                                            "changed_files": ["a.py"],
                                            "verifier_outcome": "passed",
                                            "artifact_index": [],
                                            "notes": ["left-note"]
                                        }
                                    }
                                ],
                                "summary": {
                                    "task_tags": ["cross_file"],
                                    "harness_signals": ["verifier_feedback"]
                                }
                            }
                        ],
                        "aggregate_metrics": [
                            {"name": "pass_rate", "value": 0.5, "unit": "ratio"}
                        ],
                        "comparison_views": [
                            {
                                "name": "profile_summary",
                                "items": {
                                    "bare": {"pass_rate": 0.0, "average_duration_ms": 2400, "passed_trials": 0, "total_trials": 1},
                                    "basic": {"pass_rate": 1.0, "average_duration_ms": 1200, "passed_trials": 1, "total_trials": 1}
                                }
                            },
                            {
                                "name": "profile_uplift",
                                "items": {
                                    "baseline_profile": "bare",
                                    "basic": {"pass_rate": 1.0, "pass_rate_delta": 1.0, "average_duration_ms": 1200, "average_duration_delta_ms": -1200, "passed_trials": 1, "total_trials": 1}
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            (settings.paths.reports_dir / "demo-portal-archive-suite.html").write_text("<html>portal</html>", encoding="utf8")
            (settings.paths.reports_dir / "demo-portal-archive-suite.json").write_text(
                json.dumps(
                    {
                        "suite_id": "demo-portal-archive-suite",
                        "case_results": [],
                        "aggregate_metrics": [],
                        "comparison_views": []
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            (settings.paths.reports_dir / "compare-run-left-vs-run-right.html").write_text("<html>compare</html>", encoding="utf8")
            (settings.paths.reports_dir / "suite-json-only.json").write_text(
                json.dumps(
                    {
                        "suite_id": "suite-json-only",
                        "case_results": [],
                        "aggregate_metrics": [
                            {"name": "total_cases", "value": 0.0, "unit": "count"}
                        ],
                        "comparison_views": []
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            record = record_store.load_run_record("run-left")
            bundle = record_store.load_run_comparison("run-left", "run-right")
            comparison = record_store.compare_runs("run-left", "run-right")
            filtered_events = record_store.load_events("run-left", event_type="run_finished")
            reports = record_store.list_report_artifacts(limit=10)
            eval_reports = record_store.list_eval_report_records(limit=10)

            self.assertEqual(record.summary.run_id, "run-left")
            self.assertEqual(len(record.events), 2)
            self.assertIsNotNone(record.verifier_result)
            self.assertEqual(record.verifier_result.status.value, "passed")
            self.assertEqual(record.report_markdown, "# existing report\n")
            self.assertIn("+++ b/a.py", record.patch_diff)
            self.assertEqual(len(filtered_events), 1)
            self.assertEqual(bundle.left.summary.run_id, "run-left")
            self.assertEqual(bundle.right.summary.run_id, "run-right")
            self.assertTrue(bundle.comparison.status_changed)
            self.assertTrue(comparison.status_changed)
            self.assertEqual(comparison.changed_files_only_in_left, ("a.py",))
            self.assertEqual(comparison.changed_files_only_in_right, ("b.py",))
            categories = {report.category for report in reports}
            self.assertTrue({"comparison", "eval", "dashboard", "uplift", "intake"}.issubset(categories))
            comparison_report = next(report for report in reports if report.category == "comparison")
            intake_report = next(report for report in reports if report.category == "intake")
            eval_report = next(report for report in reports if report.report_id == "suite-alpha")
            portal_artifact = next(report for report in reports if report.report_id == "demo-portal-archive-suite")
            self.assertEqual(comparison_report.title, "run-left vs run-right")
            self.assertEqual(intake_report.title, "任务入口预览 - demo-task")
            self.assertIsNotNone(eval_report.markdown_path)
            self.assertIsNotNone(eval_report.json_path)
            self.assertFalse(eval_report.is_portal_live)
            self.assertTrue(portal_artifact.is_portal_live)
            suite_alpha = next(report for report in eval_reports if report.suite_id == "suite-alpha")
            portal_eval = next(report for report in eval_reports if report.suite_id == "demo-portal-archive-suite")
            self.assertEqual(suite_alpha.task_tags, ("cross_file",))
            self.assertEqual(suite_alpha.case_results[0].trials[0].label, "basic-pass")
            self.assertEqual(suite_alpha.case_results[0].trials[0].harness_profile, "basic")
            self.assertEqual(suite_alpha.case_results[0].trials[0].run_summary.run_id, "run-left")
            self.assertEqual(suite_alpha.comparison_views["profile_uplift"]["baseline_profile"], "bare")
            self.assertTrue(portal_eval.is_portal_live)
            self.assertTrue(any(report.suite_id == "suite-json-only" for report in eval_reports))


if __name__ == "__main__":
    unittest.main()


