from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.cli.main import main
from repo_harness_lab.config.settings import AppPaths, Settings
from repo_harness_lab.domain.run_models import RunStatus, RunSummary
from repo_harness_lab.domain.trace_models import EventType, RunStage
from repo_harness_lab.storage.json_store import JsonRunStore
from repo_harness_lab.traces.events import new_trace_event
from repo_harness_lab.traces.sink import JsonlTraceSink


class CliRunsTests(unittest.TestCase):
    def test_list_runs_and_show_run_return_saved_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            settings = self._build_settings(root)
            store = JsonRunStore(settings=settings)
            summary = RunSummary(
                run_id="run-001",
                task_id="task-001",
                status=RunStatus.SUCCEEDED,
                started_at=datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 3, 26, 10, 0, 1, tzinfo=timezone.utc),
                verifier_outcome="passed",
            )
            store.save_summary(summary)

            env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(settings.paths.runtime_root)}
            with patch.dict(os.environ, env, clear=False):
                list_buffer = io.StringIO()
                with redirect_stdout(list_buffer):
                    list_exit = main(["list-runs", "--limit", "5"])

                show_buffer = io.StringIO()
                with redirect_stdout(show_buffer):
                    show_exit = main(["show-run", "run-001"])

            listed = json.loads(list_buffer.getvalue())
            shown = json.loads(show_buffer.getvalue())

            self.assertEqual(list_exit, 0)
            self.assertEqual(show_exit, 0)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["run_id"], "run-001")
            self.assertEqual(shown["run_id"], "run-001")

    def test_render_report_prints_and_writes_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            settings = self._build_settings(root)
            store = JsonRunStore(settings=settings)
            summary = RunSummary(
                run_id="run-001",
                task_id="task-001",
                status=RunStatus.SUCCEEDED,
                started_at=datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 3, 26, 10, 0, 1, tzinfo=timezone.utc),
                verifier_outcome="passed",
                changed_files=("generated.txt",),
            )
            store.save_summary(summary)
            sink = JsonlTraceSink(store.events_path("run-001"))
            sink.append(new_trace_event("run-001", EventType.RUN_STARTED, RunStage.PREPARATION))
            store.patch_path("run-001").write_text("diff --git a/generated.txt b/generated.txt\n+++ b/generated.txt\n", encoding="utf8")

            env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(settings.paths.runtime_root)}
            with patch.dict(os.environ, env, clear=False):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    exit_code = main(["render-report", "run-001", "--write"])

            report_text = buffer.getvalue()
            report_path = store.report_path("run-001")

            self.assertEqual(exit_code, 0)
            self.assertIn("# Run run-001", report_text)
            self.assertIn("Patch Preview", report_text)
            self.assertTrue(report_path.exists())
            self.assertIn("generated.txt", report_path.read_text(encoding="utf8"))

    def test_render_report_html_dashboard_and_portal_write_html_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            settings = self._build_settings(root)
            store = JsonRunStore(settings=settings)
            summary = RunSummary(
                run_id="run-001",
                task_id="task-001",
                status=RunStatus.SUCCEEDED,
                started_at=datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 3, 26, 10, 0, 1, tzinfo=timezone.utc),
                verifier_outcome="passed",
            )
            store.save_summary(summary)
            sink = JsonlTraceSink(store.events_path("run-001"))
            sink.append(new_trace_event("run-001", EventType.RUN_STARTED, RunStage.PREPARATION))
            sink.append(new_trace_event("run-001", EventType.RUN_FINISHED, RunStage.FINALIZATION))
            store.patch_path("run-001").write_text("diff --git a/generated.txt b/generated.txt\n+++ b/generated.txt\n", encoding="utf8")
            settings.paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (settings.paths.reports_dir / "demo-suite.html").write_text("<html>eval</html>", encoding="utf8")
            (settings.paths.reports_dir / "demo-suite.md").write_text("# eval\n", encoding="utf8")
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
            (settings.paths.reports_dir / "demo-suite.json").write_text(
                json.dumps(
                    {
                        "suite_id": "demo-suite",
                        "aggregate_metrics": [],
                        "comparison_views": [],
                        "case_results": [
                            {
                                "case_id": "recommended-case",
                                "summary": {
                                    "difficulty": "medium",
                                    "task_tags": ["provider_uplift"],
                                    "harness_signals": ["task_inputs", "verifier_plan"],
                                    "recommendation_score": 86,
                                    "recommendation_reasons": [
                                        "声明了 Harness 信号：task_inputs, verifier_plan",
                                        "包含确定性 verifier 步骤，成败原因更容易解释"
                                    ]
                                },
                                "trials": []
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
                        "aggregate_metrics": [],
                        "comparison_views": [],
                        "case_results": []
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            (settings.paths.reports_dir / "compare-run-001-vs-run-002.html").write_text("<html>compare</html>", encoding="utf8")

            env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(settings.paths.runtime_root)}
            with patch.dict(os.environ, env, clear=False):
                html_buffer = io.StringIO()
                with redirect_stdout(html_buffer):
                    html_exit = main(["render-report", "run-001", "--format", "html"])

                dashboard_buffer = io.StringIO()
                with redirect_stdout(dashboard_buffer):
                    dashboard_exit = main(["render-dashboard", "--limit", "5"])

                uplift_buffer = io.StringIO()
                with redirect_stdout(uplift_buffer):
                    uplift_exit = main(["render-uplift-dashboard", "--limit", "5"])

                portal_buffer = io.StringIO()
                with redirect_stdout(portal_buffer):
                    portal_exit = main([
                        "render-portal",
                        "--limit", "5",
                        "--live-portal-url", "https://demo.example.com/harness-portal.html",
                        "--live-portal-command", "python -m repo_harness_lab.cli.main serve-portal --host 0.0.0.0 --public-base-url https://demo.example.com",
                    ])

            html_payload = json.loads(html_buffer.getvalue())
            dashboard_payload = json.loads(dashboard_buffer.getvalue())
            uplift_payload = json.loads(uplift_buffer.getvalue())
            portal_payload = json.loads(portal_buffer.getvalue())
            html_report_path = store.html_report_path("run-001")
            dashboard_path = Path(dashboard_payload["path"])
            uplift_path = Path(uplift_payload["path"])
            portal_path = Path(portal_payload["path"])

            self.assertEqual(html_exit, 0)
            self.assertEqual(dashboard_exit, 0)
            self.assertEqual(uplift_exit, 0)
            self.assertEqual(portal_exit, 0)
            self.assertEqual(html_payload["format"], "html")
            self.assertTrue(html_report_path.exists())
            self.assertIn("补丁预览", html_report_path.read_text(encoding="utf8"))
            self.assertTrue(dashboard_path.exists())
            self.assertIn("打开运行报告", dashboard_path.read_text(encoding="utf8"))
            self.assertTrue(uplift_path.exists())
            uplift_html = uplift_path.read_text(encoding="utf8")
            self.assertIn("同模型 Harness 结果页", uplift_html)
            self.assertIn("用户任务", uplift_html)
            self.assertIn("三档结果", uplift_html)
            self.assertIn("推荐任务", uplift_html)
            self.assertIn("包含确定性 verifier 步骤，成败原因更容易解释", uplift_html)
            self.assertIn("Portal 试跑归档", uplift_html)
            uplift_suite_section = uplift_html.split("<h2>套件概览</h2>", 1)[1].split("<h2>失败汇总</h2>", 1)[0]
            uplift_archive_section = uplift_html.split("<h2>Portal 试跑归档</h2>", 1)[1]
            self.assertIn("demo-suite", uplift_suite_section)
            self.assertNotIn("demo-portal-archive-suite", uplift_suite_section)
            self.assertIn("demo-portal-archive-suite", uplift_archive_section)
            self.assertTrue(portal_path.exists())
            portal_html = portal_path.read_text(encoding="utf8")
            self.assertIn("同模型 Harness 演示台", portal_html)
            self.assertIn("用户任务", portal_html)
            self.assertIn("三档结果", portal_html)
            self.assertIn("更多证据", portal_html)
            self.assertIn("正式证据页", portal_html)
            self.assertIn("Portal 试跑归档", portal_html)
            portal_primary_section = portal_html.split("<h2>正式证据页</h2>", 1)[1].split("<h2>Portal 试跑归档</h2>", 1)[0]
            portal_archive_section = portal_html.split("<h2>Portal 试跑归档</h2>", 1)[1]
            self.assertIn("demo-suite", portal_primary_section)
            self.assertIn("任务入口预览 - demo-task", portal_primary_section)
            self.assertIn("run-001 vs run-002", portal_primary_section)
            self.assertNotIn("demo-portal-archive-suite", portal_primary_section)
            self.assertIn("demo-portal-archive-suite", portal_archive_section)
            self.assertEqual(Path(portal_payload["uplift_dashboard_path"]), uplift_path)

    def test_serve_portal_reports_public_and_local_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            settings = self._build_settings(root)
            env = {
                "REPO_HARNESS_LAB_PROJECT_ROOT": str(Path(__file__).resolve().parents[2]),
                "REPO_HARNESS_LAB_RUNTIME_ROOT": str(settings.paths.runtime_root),
            }

            class _DummyServer:
                server_address = ("0.0.0.0", 4321)

                def serve_forever(self) -> None:
                    raise KeyboardInterrupt()

                def server_close(self) -> None:
                    return None

            with patch.dict(os.environ, env, clear=False):
                with patch("repo_harness_lab.cli.commands.runs.build_portal_http_server", return_value=_DummyServer()):
                    buffer = io.StringIO()
                    with redirect_stdout(buffer):
                        exit_code = main([
                            "serve-portal",
                            "--host", "0.0.0.0",
                            "--port", "4321",
                            "--public-base-url", "https://demo.example.com",
                        ])

            payload = json.loads(buffer.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["host"], "0.0.0.0")
            self.assertEqual(payload["local_portal_url"], "http://127.0.0.1:4321/harness-portal.html")
            self.assertEqual(payload["portal_url"], "https://demo.example.com/harness-portal.html")
            self.assertEqual(payload["public_base_url"], "https://demo.example.com")
            self.assertTrue(payload["hosted_mode"])

    def test_show_events_show_verifier_results_compare_runs_json_and_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            settings = self._build_settings(root)
            store = JsonRunStore(settings=settings)
            started_at = datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc)

            left = RunSummary(
                run_id="run-left",
                task_id="task-001",
                status=RunStatus.SUCCEEDED,
                started_at=started_at,
                finished_at=started_at,
                changed_files=("left.py",),
                verifier_outcome="passed",
            )
            right = RunSummary(
                run_id="run-right",
                task_id="task-001",
                status=RunStatus.FAILED,
                started_at=started_at,
                finished_at=started_at,
                changed_files=("right.py",),
                verifier_outcome="failed",
                notes=("boom",),
            )
            store.save_summary(left)
            store.save_summary(right)

            left_sink = JsonlTraceSink(store.events_path("run-left"))
            left_sink.append(new_trace_event("run-left", EventType.RUN_STARTED, RunStage.PREPARATION))
            left_sink.append(
                new_trace_event(
                    "run-left",
                    EventType.MODEL_REQUESTED,
                    RunStage.AGENT,
                    {
                        "provider": "qwen",
                        "model": "qwen-plus",
                        "harness_profile": "bare",
                        "context_file_count": 0,
                        "tree_entry_count": 2,
                        "truncated_file_count": 0,
                    },
                )
            )
            left_sink.append(
                new_trace_event(
                    "run-left",
                    EventType.MODEL_RESPONDED,
                    RunStage.AGENT,
                    {
                        "provider": "qwen",
                        "model": "qwen-plus",
                        "finish_reason": "stop",
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                        "write_count": 1,
                    },
                )
            )
            left_sink.append(new_trace_event("run-left", EventType.RUN_FINISHED, RunStage.FINALIZATION))
            right_sink = JsonlTraceSink(store.events_path("run-right"))
            right_sink.append(new_trace_event("run-right", EventType.RUN_STARTED, RunStage.PREPARATION))
            right_sink.append(
                new_trace_event(
                    "run-right",
                    EventType.MODEL_REQUESTED,
                    RunStage.AGENT,
                    {
                        "provider": "qwen",
                        "model": "qwen-plus",
                        "harness_profile": "basic",
                        "context_file_count": 2,
                        "tree_entry_count": 2,
                        "truncated_file_count": 0,
                    },
                )
            )
            right_sink.append(
                new_trace_event(
                    "run-right",
                    EventType.MODEL_RESPONDED,
                    RunStage.AGENT,
                    {
                        "provider": "qwen",
                        "model": "qwen-plus",
                        "finish_reason": "stop",
                        "prompt_tokens": 140,
                        "completion_tokens": 22,
                        "total_tokens": 162,
                        "write_count": 1,
                    },
                )
            )
            right_sink.append(new_trace_event("run-right", EventType.RUN_FINISHED, RunStage.FINALIZATION))
            store.verifier_results_path("run-left").write_text(
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
            store.patch_path("run-left").write_text("diff --git a/left.py b/left.py\n+++ b/left.py\n", encoding="utf8")
            store.patch_path("run-right").write_text("diff --git a/right.py b/right.py\n+++ b/right.py\n", encoding="utf8")

            env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(settings.paths.runtime_root)}
            with patch.dict(os.environ, env, clear=False):
                events_buffer = io.StringIO()
                with redirect_stdout(events_buffer):
                    events_exit = main(["show-events", "run-left", "--event-type", "run_finished"])

                verifier_buffer = io.StringIO()
                with redirect_stdout(verifier_buffer):
                    verifier_exit = main(["show-verifier-results", "run-left"])

                compare_buffer = io.StringIO()
                with redirect_stdout(compare_buffer):
                    compare_exit = main(["compare-runs", "run-left", "run-right"])

                compare_html_buffer = io.StringIO()
                with redirect_stdout(compare_html_buffer):
                    compare_html_exit = main(["compare-runs", "run-left", "run-right", "--format", "html"])

            events_payload = json.loads(events_buffer.getvalue())
            verifier_payload = json.loads(verifier_buffer.getvalue())
            compare_payload = json.loads(compare_buffer.getvalue())
            compare_html_payload = json.loads(compare_html_buffer.getvalue())
            compare_html_path = Path(compare_html_payload["path"])

            self.assertEqual(events_exit, 0)
            self.assertEqual(verifier_exit, 0)
            self.assertEqual(compare_exit, 0)
            self.assertEqual(compare_html_exit, 0)
            self.assertEqual(len(events_payload), 1)
            self.assertEqual(events_payload[0]["event_type"], "run_finished")
            self.assertEqual(verifier_payload["status"], "passed")
            self.assertTrue(compare_payload["status_changed"])
            self.assertEqual(compare_payload["changed_files_only_in_left"], ["left.py"])
            self.assertEqual(compare_payload["changed_files_only_in_right"], ["right.py"])
            self.assertTrue(compare_html_path.exists())
            compare_html = compare_html_path.read_text(encoding="utf8")
            self.assertIn("运行对比", compare_html)
            self.assertIn("补丁预览", compare_html)
            self.assertIn("Harness 差异", compare_html)
            self.assertIn("Harness 差异", compare_html)
            self.assertIn("运行对比", compare_html)
            self.assertIn("上下文文件：0", compare_html)
            self.assertIn("上下文文件: 0 -&gt; 2 (+2)", compare_html)
            self.assertIn("提示 Token: 100 -&gt; 140 (+40)", compare_html)

    @staticmethod
    def _build_settings(root: Path) -> Settings:
        return Settings(
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


if __name__ == "__main__":
    unittest.main()





