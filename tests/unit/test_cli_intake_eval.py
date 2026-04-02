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
REPO_ROOT = Path(__file__).resolve().parents[2]

from repo_harness_lab.agents.providers.base import ProviderResponse, ProviderUsage
from repo_harness_lab.agents.providers.openai_compatible import OpenAICompatibleChatProvider
from repo_harness_lab.cli.main import main


class CliIntakeEvalTests(unittest.TestCase):
    def test_run_intake_eval_scaffolds_task_preview_and_runs_default_uplift_matrix(self) -> None:
        runtime_root = Path(tempfile.mkdtemp()) / "runtime"
        intake_path = REPO_ROOT / "examples" / "intakes" / "provider_release_input_task_intake.json"

        def fake_generate(self, messages):
            user_prompt = messages[1].content
            has_release_inputs = all(
                token in user_prompt
                for token in (
                    "release_version=2026.04.0",
                    "release_channel=canary",
                    "codename=Paper Lantern",
                    "release-summary-check",
                )
            )
            if has_release_inputs:
                payload = {
                    "summary": "apply release spec 2026.04.0 canary Paper Lantern",
                    "writes": [
                        {
                            "path": "config/release.env",
                            "content": "VERSION=2026.04.0\nCHANNEL=canary\n",
                        },
                        {
                            "path": "docs/release_summary.md",
                            "content": "# Release 2026.04.0\n- channel: canary\n- codename: Paper Lantern\n",
                        },
                    ],
                }
            else:
                payload = {
                    "summary": "guess release spec from repo tree",
                    "writes": [
                        {
                            "path": "config/release.env",
                            "content": "VERSION=0.0.1\nCHANNEL=stable\n",
                        },
                        {
                            "path": "docs/release_summary.md",
                            "content": "# Pending Release\n- channel: stable\n- codename: Guess\n",
                        },
                    ],
                }
            return ProviderResponse(
                content=json.dumps(payload, ensure_ascii=False),
                model=self.model,
                usage=ProviderUsage(prompt_tokens=24, completion_tokens=12, total_tokens=36),
            )

        env = {
            "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
            "DASHSCOPE_API_KEY": "test-key",
        }
        buffer = io.StringIO()
        with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
            with patch.dict(os.environ, env, clear=False):
                with redirect_stdout(buffer):
                    exit_code = main(
                        [
                            "run-intake-eval",
                            str(intake_path),
                            "--provider",
                            "qwen",
                            "--model",
                            "qwen-plus",
                            "--api-key-env",
                            "DASHSCOPE_API_KEY",
                        ]
                    )

        payload = json.loads(buffer.getvalue())
        profile_uplift = payload["profile_uplift"]
        task_path = Path(payload["scaffolded_task_spec_path"])
        suite_path = Path(payload["generated_suite_path"])
        preview_html_path = Path(payload["intake_preview"]["html_path"])
        preview_json_path = Path(payload["intake_preview"]["json_path"])
        html_report = Path(payload["artifacts"]["html_report_path"]).read_text(encoding="utf8")
        preview_html = preview_html_path.read_text(encoding='utf8')
        comparison_paths = [Path(item) for item in payload["artifacts"]["comparison_html_paths"]]

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["suite_id"], "provider-release-input-sync-intake-uplift-suite")
        self.assertEqual(payload["case_count"], 1)
        self.assertEqual(profile_uplift["baseline_profile"], "bare")
        self.assertEqual(profile_uplift["bare"]["pass_rate"], 0.0)
        self.assertEqual(profile_uplift["basic"]["pass_rate"], 0.0)
        self.assertEqual(profile_uplift["full"]["pass_rate"], 1.0)
        self.assertEqual(profile_uplift["full"]["pass_rate_delta"], 1.0)
        self.assertTrue(task_path.exists())
        self.assertTrue(suite_path.exists())
        self.assertTrue(preview_html_path.exists())
        self.assertTrue(preview_json_path.exists())
        self.assertEqual(len(comparison_paths), 3)
        self.assertTrue(all(path.exists() for path in comparison_paths))

        task_payload = json.loads(task_path.read_text(encoding="utf8"))
        suite_payload = json.loads(suite_path.read_text(encoding="utf8"))
        preview_payload = json.loads(preview_json_path.read_text(encoding='utf8'))

        self.assertEqual(task_payload["task_id"], "provider-release-input-sync")
        self.assertEqual(
            task_payload["benchmark_metadata"]["harness_signals"],
            ["task_inputs", "multi_file_edit", "verifier_plan"],
        )
        self.assertEqual(suite_payload["suite_id"], "provider-release-input-sync-intake-uplift-suite")
        self.assertEqual(suite_payload["cases"][0]["case_id"], "provider-release-input-sync")
        self.assertEqual(
            [item["label"] for item in suite_payload["cases"][0]["run_matrix"]],
            ["qwen-bare", "qwen-basic", "qwen-full"],
        )
        self.assertEqual(
            suite_payload["cases"][0]["task_spec_ref"],
            str(task_path),
        )
        self.assertEqual(preview_payload['task_spec_preview']['task_id'], 'provider-release-input-sync')
        self.assertIn('new task inputs: release_spec', preview_payload['profile_delta_summary'][1]['summary_lines'])
        self.assertIn('run-intake-eval', preview_payload['suggested_commands']['run_intake_eval'])
        self.assertIn("Paper Lantern", html_report)
        self.assertIn("同模型 Harness 抬升", html_report)
        self.assertIn("用户任务", html_report)
        self.assertIn("共同任务信息", html_report)
        self.assertIn("三档额外交付", html_report)
        self.assertIn("任务输出", html_report)
        self.assertIn("guess release spec from repo tree", html_report)
        self.assertIn("任务入口预览", preview_html)
        self.assertIn("三档交付", preview_html)
        self.assertIn("运行 Intake Eval", preview_html)
        self.assertTrue(any("新增任务输入" in path.read_text(encoding="utf8") for path in comparison_paths))
        self.assertTrue(any("Paper Lantern" in path.read_text(encoding="utf8") for path in comparison_paths))

    def test_run_intake_eval_for_policy_bundle_refreshes_portal_and_dashboard(self) -> None:
        runtime_root = Path(tempfile.mkdtemp()) / "runtime"
        intake_path = REPO_ROOT / "examples" / "intakes" / "provider_policy_bundle_task_intake.json"

        def fake_generate(self, messages):
            user_prompt = messages[1].content
            has_full_bundle = all(
                token in user_prompt
                for token in (
                    "workspace admins",
                    "2026-05-01",
                    "staged over 14 days",
                    "legacy EU tenants stay on previous policy until migration completes",
                    "trust-ops@example.test",
                    "policy-checklist-check",
                )
            )
            if has_full_bundle:
                payload = {
                    "summary": "assemble policy bundle from full repo context",
                    "writes": [
                        {
                            "path": "docs/policy_notice.md",
                            "content": "# Policy Update\n- audience: workspace admins\n- effective_date: 2026-05-01\n- rollout_window: staged over 14 days\n- exception: legacy EU tenants stay on previous policy until migration completes\n- escalation: trust-ops@example.test\n",
                        },
                        {
                            "path": "ops/policy_rollout_checklist.md",
                            "content": "# Rollout Checklist\n- announce to workspace admins\n- start staged rollout on 2026-05-01\n- keep legacy EU tenants on previous policy until migration completes\n- route escalations to trust-ops@example.test\n",
                        },
                    ],
                }
            else:
                payload = {
                    "summary": "assemble policy bundle from partial repo context",
                    "writes": [
                        {
                            "path": "docs/policy_notice.md",
                            "content": "# Policy Update\n- audience: workspace admins\n- effective_date: 2026-05-01\n- rollout_window: staged over 14 days\n- exception: legacy EU tenants stay on previous policy until migration completes\n- escalation: pending\n",
                        },
                        {
                            "path": "ops/policy_rollout_checklist.md",
                            "content": "# Rollout Checklist\n- announce to workspace admins\n- start staged rollout on 2026-05-01\n- keep legacy EU tenants on previous policy until migration completes\n- route escalations to pending\n",
                        },
                    ],
                }
            return ProviderResponse(
                content=json.dumps(payload, ensure_ascii=False),
                model=self.model,
                usage=ProviderUsage(prompt_tokens=40, completion_tokens=18, total_tokens=58),
            )

        env = {
            "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
            "DASHSCOPE_API_KEY": "test-key",
        }
        eval_buffer = io.StringIO()
        portal_buffer = io.StringIO()
        with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
            with patch.dict(os.environ, env, clear=False):
                with redirect_stdout(eval_buffer):
                    exit_code = main(
                        [
                            "run-intake-eval",
                            str(intake_path),
                            "--provider",
                            "qwen",
                            "--model",
                            "qwen-plus",
                            "--api-key-env",
                            "DASHSCOPE_API_KEY",
                        ]
                    )
                with redirect_stdout(portal_buffer):
                    portal_exit = main(["render-portal", "--limit", "20"])

        payload = json.loads(eval_buffer.getvalue())
        portal_payload = json.loads(portal_buffer.getvalue())
        profile_uplift = payload["profile_uplift"]
        artifacts = payload["artifacts"]
        comparison_paths = [Path(item) for item in artifacts["comparison_html_paths"]]
        html_report = Path(artifacts["html_report_path"]).read_text(encoding="utf8")
        uplift_html = Path(artifacts["uplift_dashboard_path"]).read_text(encoding="utf8")
        portal_html = Path(portal_payload["path"]).read_text(encoding="utf8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(portal_exit, 0)
        self.assertEqual(payload["suite_id"], "provider-policy-bundle-sync-intake-uplift-suite")
        self.assertEqual(profile_uplift["baseline_profile"], "bare")
        self.assertEqual(profile_uplift["bare"]["pass_rate"], 0.0)
        self.assertEqual(profile_uplift["basic"]["pass_rate"], 0.0)
        self.assertEqual(profile_uplift["full"]["pass_rate"], 1.0)
        self.assertEqual(profile_uplift["full"]["pass_rate_delta"], 1.0)
        self.assertEqual(len(comparison_paths), 3)
        self.assertTrue(all(path.exists() for path in comparison_paths))
        self.assertIn("provider-policy-bundle-sync", html_report)
        self.assertIn("任务输出", html_report)
        self.assertIn("处理结果", html_report)
        self.assertIn("共同任务信息", html_report)
        self.assertIn("三档额外交付", html_report)
        self.assertIn("trust-ops@example.test", html_report)
        self.assertIn("根据政策资料包同步公告与上线清单", html_report)
        self.assertIn("同模型 Harness 结果页", uplift_html)
        self.assertIn("用户任务", uplift_html)
        self.assertIn("共同任务信息", uplift_html)
        self.assertIn("三档结果", uplift_html)
        self.assertIn("trust-ops@example.test", uplift_html)
        self.assertIn("根据政策资料包同步公告与上线清单", uplift_html)
        self.assertIn("同模型 Harness 演示台", portal_html)
        self.assertIn("用户任务", portal_html)
        self.assertIn("共同任务信息", portal_html)
        self.assertIn("三档结果", portal_html)
        self.assertIn("根据政策资料包同步公告与上线清单", portal_html)
        self.assertIn("http://127.0.0.1:8765/harness-portal.html", portal_html)
        self.assertIn("python -m repo_harness_lab.cli.main serve-portal", portal_html)
        self.assertTrue(any("上下文文件: 0 -&gt; 8 (+8)" in path.read_text(encoding="utf8") for path in comparison_paths))
        self.assertTrue(any("trust-ops@example.test" in path.read_text(encoding="utf8") for path in comparison_paths))
        self.assertTrue(any("trust-ops@example.test" in path.read_text(encoding="utf8") for path in comparison_paths))
        self.assertEqual(Path(portal_payload["uplift_dashboard_path"]), Path(artifacts["uplift_dashboard_path"]))

if __name__ == "__main__":
    unittest.main()


