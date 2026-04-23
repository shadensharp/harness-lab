from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TMP_ROOT = REPO_ROOT / "runtime" / "test-temp"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)

from repo_harness_lab.agents.providers.base import ProviderResponse, ProviderUsage
from repo_harness_lab.agents.providers.openai_compatible import OpenAICompatibleChatProvider
from repo_harness_lab.config.settings import load_settings
from repo_harness_lab.runtime.portal_live import PortalLiveEntryConfig
from repo_harness_lab.runtime.portal_submission import PORTAL_TEMPLATE_REPO_TOKEN
from repo_harness_lab.runtime.portal_server import build_portal_http_server

_NO_PROXY_OPENER = build_opener(ProxyHandler({}))


class PortalServerTests(unittest.TestCase):
    def test_live_portal_serves_config_and_runs_three_profiles_inline(self) -> None:
        runtime_root = Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT)) / "runtime"
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
                    "summary": "assemble policy bundle from complete repo context",
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
            "REPO_HARNESS_LAB_PROJECT_ROOT": str(REPO_ROOT),
            "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
            "DASHSCOPE_API_KEY": "test-key",
        }
        with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
            with patch.dict(os.environ, env, clear=False):
                settings = load_settings()
                settings.paths.ensure_runtime_directories()
                live_entry = PortalLiveEntryConfig(
                    template_id="provider_policy_bundle",
                    intake_source_path=intake_path,
                    provider="qwen",
                    model="qwen-plus",
                    api_key_env="DASHSCOPE_API_KEY",
                )
                server = build_portal_http_server(settings=settings, live_entry=live_entry, host="127.0.0.1", port=0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    config_status, config_payload = _get_json(f"{base_url}/api/config")
                    self.assertEqual(config_status, 200)
                    self.assertTrue(config_payload["ok"])
                    self.assertTrue(config_payload["api_ready"])
                    self.assertEqual(config_payload["model_display_name"], "\u5343\u95ee / qwen-plus")
                    self.assertEqual(config_payload["run_endpoint"], "/api/run-demo")
                    self.assertEqual(config_payload["run_async_endpoint"], "/api/run-demo-async")
                    self.assertEqual(config_payload["run_status_endpoint"], "/api/run-demo-status")
                    self.assertEqual(config_payload["preview_endpoint"], "/api/preview-demo")
                    self.assertEqual(config_payload["poll_after_ms"], 1500)
                    self.assertIn("form_defaults", config_payload)
                    self.assertIn("task_shape_options", config_payload)
                    self.assertIn("knowledge_pack_options", config_payload)
                    self.assertIn("repo_path", config_payload["form_defaults"])
                    self.assertEqual(config_payload["form_defaults"]["task_shape"], "general")
                    self.assertEqual(config_payload["form_defaults"]["knowledge_pack"], "none")
                    self.assertEqual(config_payload["task_input_label"], "\u4efb\u52a1\u6b63\u6587\uff08\u5fc5\u586b\uff09")
                    self.assertIn("\u4e0d\u9700\u8981\u5148\u5199 intake JSON", config_payload["task_input_help_text"])
                    self.assertIn("\u4efb\u610f repo \u4efb\u52a1", config_payload["repo_source_help_text"])
                    self.assertEqual(config_payload["advanced_settings_summary"], "\u53ef\u9009\u9ad8\u7ea7\u5b57\u6bb5")
                    self.assertIn("\u8349\u7a3f\u5b8c\u6210\u5ea6\u4f30\u7b97", config_payload["acceptance_checks_help_text"])

                    page_status, page_html = _get_text(f"{base_url}/harness-portal.html")
                    self.assertEqual(page_status, 200)
                    self.assertNotIn("portal-live-preview", page_html)
                    self.assertIn("harness-lab", page_html)
                    self.assertIn("portal-live-workbench", page_html)
                    self.assertIn("portal-live-plan-stream", page_html)
                    self.assertIn("portal-live-guidance", page_html)
                    self.assertIn("portal-live-submit", page_html)
                    self.assertIn("portal-live-task-input", page_html)
                    self.assertIn("portal-live-task-shape", page_html)
                    self.assertIn("portal-live-knowledge-pack", page_html)
                    self.assertIn("\u8fd0\u884c\u4efb\u52a1", page_html)
                    self.assertIn("\u7528\u6237\u8f93\u5165", page_html)
                    self.assertIn("\u5de5\u4f5c\u53f0", page_html)
                    self.assertNotIn(">\u4efb\u52a1\u5f62\u6001<", page_html)
                    self.assertNotIn(">\u6750\u6599\u5305<", page_html)
                    self.assertNotIn("\u5de6\u4fa7\u662f\u5de5\u4f5c\u53f0", page_html)
                    self.assertIn("\u5e2e\u6211\u505a\u4e00\u4e2a\u4fc4\u7f57\u65af\u65b9\u5757\u5c0f\u6e38\u620f\uff0c\u8981\u80fd\u76f4\u63a5\u8fd0\u884c\u5f00\u59cb\u73a9", page_html)
                    self.assertIn("portal-live-guidance", page_html)
                    self.assertIn("portal-live-repo-path", page_html)
                    self.assertIn("\u4ed3\u5e93\u6765\u6e90\uff08\u5fc5\u586b", page_html)
                    self.assertIn("portal-live-acceptance-checks", page_html)
                    self.assertIn("\u53ef\u9009\u9ad8\u7ea7\u5b57\u6bb5", page_html)
                    self.assertIn("\u8349\u7a3f\u5b8c\u6210\u5ea6\u4f30\u7b97", page_html)
                    self.assertIn("\u6700\u8fd1\u4efb\u52a1", page_html)
                    self.assertIn("\u5343\u95ee / qwen-plus", page_html)
                    self.assertIn("\u4efb\u52a1\u662f\u4ec0\u4e48", page_html)
                    self.assertIn("\u7cfb\u7edf\u600e\u4e48\u51b3\u5b9a\u8fd9\u6837\u505a", page_html)
                    self.assertIn("\u5b9e\u9645\u600e\u4e48\u6267\u884c", page_html)
                    self.assertIn("\u62ff\u5230\u4e86\u54ea\u4e9b\u5173\u952e\u8bc1\u636e", page_html)
                    self.assertIn("\u6700\u7ec8\u7ed3\u679c\u662f\u4ec0\u4e48", page_html)
                    self.assertIn("\u8fd8\u53ef\u4ee5\u5f80\u4e0b\u770b\u4ec0\u4e48\u7ec6\u8282", page_html)
                    self.assertIn("<details class=\"story-detail\">", page_html)

                    defaults = config_payload["form_defaults"]
                    run_status, run_payload = _post_json(
                        f"{base_url}/api/run-demo",
                        {
                            "task_text": "\u8bf7\u6839\u636e docs \u4e0b\u7684\u653f\u7b56\u8d44\u6599\u5305\uff0c\u66f4\u65b0 docs/policy_notice.md \u548c ops/policy_rollout_checklist.md\uff0c\u4f7f\u516c\u544a\u4e0e\u4e0a\u7ebf\u6e05\u5355\u4fdd\u6301\u4e00\u81f4\u3002",
                            "title": "\u6839\u636e\u653f\u7b56\u8d44\u6599\u5305\u540c\u6b65\u516c\u544a\u4e0e\u4e0a\u7ebf\u6e05\u5355",
                            "repo_path": defaults["repo_path"],
                            "context_paths_text": defaults["context_paths_text"],
                            "editable_paths_text": defaults["editable_paths_text"],
                            "forbidden_paths_text": defaults["forbidden_paths_text"],
                            "expected_changed_files_text": defaults["expected_changed_files_text"],
                            "behavioral_checks_text": defaults["behavioral_checks_text"],
                            "acceptance_checks_text": defaults["acceptance_checks_text"],
                        },
                    )
                    self.assertEqual(run_status, 200)
                    self.assertTrue(run_payload["ok"])
                    self.assertTrue(run_payload["suite_id"].startswith("provider_policy_bundle-portal-"))
                    self.assertTrue(run_payload["suite_id"].endswith("-intake-uplift-suite"))
                    self.assertEqual(len(run_payload["results"]), 1)
                    self.assertIn("trust-ops@example.test", run_payload["results_html"])
                    self.assertIn("/uplift-dashboard.html", run_payload["links_html"])
                    self.assertIn("\u6839\u636e\u653f\u7b56\u8d44\u6599\u5305\u540c\u6b65\u516c\u544a\u4e0e\u4e0a\u7ebf\u6e05\u5355", run_payload["recent_history_html"])
                    self.assertIn("\u91cd\u65b0\u586b\u5165", run_payload["recent_history_html"])

                    result_by_profile = {item["profile"]: item for item in run_payload["results"]}
                    self.assertEqual(result_by_profile["current"]["status"], "succeeded")
                    self.assertEqual(result_by_profile["current"]["verifier"], "passed")
                    self.assertIn("/runs/", result_by_profile["current"]["run_report_path"])
                    self.assertFalse(result_by_profile["current"]["comparison_path"])

                    refreshed_status, refreshed_html = _get_text(f"{base_url}/harness-portal.html")
                    self.assertEqual(refreshed_status, 200)
                    self.assertNotIn("portal-live-preview", refreshed_html)
                    self.assertIn("harness-lab", refreshed_html)
                    self.assertIn("portal-live-plan-stream", refreshed_html)
                    self.assertIn("\u6700\u8fd1\u4efb\u52a1", refreshed_html)
                    self.assertIn("\u91cd\u65b0\u586b\u5165", refreshed_html)
                    self.assertIn("\u6839\u636e\u653f\u7b56\u8d44\u6599\u5305\u540c\u6b65\u516c\u544a\u4e0e\u4e0a\u7ebf\u6e05\u5355", refreshed_html)
                    self.assertIn("portal-live-results", refreshed_html)
                    self.assertIn('<article class="thread-card thread-card-assistant">', refreshed_html)
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()

    def test_hosted_live_portal_uses_example_token_and_rejects_custom_local_repo_sources(self) -> None:
        runtime_root = Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT)) / "runtime"
        intake_path = REPO_ROOT / "examples" / "intakes" / "provider_policy_bundle_task_intake.json"
        repo_root = _init_git_repo(Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT)) / "repo", {"README.md": "# Old Title\n"})

        env = {
            "REPO_HARNESS_LAB_PROJECT_ROOT": str(REPO_ROOT),
            "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
        }
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings()
            settings.paths.ensure_runtime_directories()
            live_entry = PortalLiveEntryConfig(
                template_id="provider_policy_bundle",
                intake_source_path=intake_path,
                provider="qwen",
                model="qwen-plus",
                api_key_env="DASHSCOPE_API_KEY",
                allow_custom_local_repo_paths=False,
            )
            server = build_portal_http_server(settings=settings, live_entry=live_entry, host="127.0.0.1", port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                config_status, config_payload = _get_json(f"{base_url}/api/config")
                self.assertEqual(config_status, 200)
                self.assertTrue(config_payload["hosted_mode"])
                self.assertFalse(config_payload["allow_custom_local_repo_paths"])
                self.assertEqual(config_payload["form_defaults"]["repo_path"], PORTAL_TEMPLATE_REPO_TOKEN)
                self.assertIn("\u516c\u5f00 Git \u5730\u5740", config_payload["repo_source_input_label"])
                self.assertIn("\u4e0d\u9700\u8981\u5148\u5199 intake JSON", config_payload["task_input_help_text"])
                self.assertIn("http/https", config_payload["repo_source_help_text"])

                page_status, page_html = _get_text(f"{base_url}/harness-portal.html")
                self.assertEqual(page_status, 200)
                self.assertIn("\u516c\u5f00 Git \u5730\u5740", page_html)
                self.assertIn("\u7528\u6237\u8f93\u5165", page_html)
                self.assertNotIn(str((REPO_ROOT / "examples" / "repos" / "provider_policy_bundle_uplift_repo").resolve()), page_html)

                preview_status, preview_payload = _post_json_allow_error(
                    f"{base_url}/api/preview-demo",
                    dict(config_payload["form_defaults"]),
                )
                self.assertEqual(preview_status, 200)
                self.assertTrue(preview_payload["ok"])
                self.assertEqual(preview_payload["form_fields"]["repo_path"], PORTAL_TEMPLATE_REPO_TOKEN)

                invalid_payload = {
                    "task_text": "Please update README.md title.",
                    "repo_path": repo_root.as_uri(),
                }
                invalid_preview_status, invalid_preview_payload = _post_json_allow_error(
                    f"{base_url}/api/preview-demo",
                    invalid_payload,
                )
                self.assertEqual(invalid_preview_status, 400)
                self.assertFalse(invalid_preview_payload["ok"])
                self.assertIn("\u516c\u5f00 Git \u4ed3\u5e93\u5730\u5740", invalid_preview_payload["error"])

                async_status, accepted_payload = _post_json_allow_error(
                    f"{base_url}/api/run-demo-async",
                    invalid_payload,
                )
                self.assertEqual(async_status, 202)
                self.assertTrue(accepted_payload["ok"])
                failed_payload = _poll_async_job(base_url, str(accepted_payload["job_id"]))
                self.assertFalse(failed_payload["ok"])
                self.assertTrue(failed_payload["done"])
                self.assertEqual(failed_payload["job_status"], "failed")
                self.assertIn("\u516c\u5f00 Git \u4ed3\u5e93\u5730\u5740", failed_payload["error"])
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_live_portal_previews_and_runs_with_policy_knowledge_pack(self) -> None:
        runtime_root = Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT)) / "runtime"
        intake_path = REPO_ROOT / "examples" / "intakes" / "provider_policy_bundle_task_intake.json"
        repo_root = _init_git_repo(
            Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT)) / "repo",
            {
                "README.md": "# Policy Repo\n",
                "docs/policy_notice.md": "# Old Notice\n- audience: pending\n",
                "ops/policy_rollout_checklist.md": "# Old Checklist\n- route escalations to pending\n",
                "docs/policy_scope.txt": "workspace admins\n",
            },
        )

        def fake_generate(self, messages):
            payload = {
                "summary": "sync policy notice and rollout checklist",
                "writes": [
                    {
                        "path": "docs/policy_notice.md",
                        "content": "# Policy Update\n- audience: workspace admins\n",
                    },
                    {
                        "path": "ops/policy_rollout_checklist.md",
                        "content": "# Rollout Checklist\n- route escalations to trust-ops@example.test\n",
                    },
                ],
            }
            return ProviderResponse(
                content=json.dumps(payload, ensure_ascii=False),
                model=self.model,
                usage=ProviderUsage(prompt_tokens=26, completion_tokens=14, total_tokens=40),
            )

        env = {
            "REPO_HARNESS_LAB_PROJECT_ROOT": str(REPO_ROOT),
            "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
            "DASHSCOPE_API_KEY": "test-key",
        }
        with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
            with patch.dict(os.environ, env, clear=False):
                settings = load_settings()
                settings.paths.ensure_runtime_directories()
                live_entry = PortalLiveEntryConfig(
                    template_id="provider_policy_bundle",
                    intake_source_path=intake_path,
                    provider="qwen",
                    model="qwen-plus",
                    api_key_env="DASHSCOPE_API_KEY",
                )
                server = build_portal_http_server(settings=settings, live_entry=live_entry, host="127.0.0.1", port=0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    payload = {
                        "task_text": "Please align the policy notice and rollout checklist with the policy material package.",
                        "task_shape": "multi_file_sync",
                        "knowledge_pack": "policy_bundle",
                        "repo_path": repo_root.as_uri(),
                    }

                    preview_status, preview_payload = _post_json(f"{base_url}/api/preview-demo", payload)
                    self.assertEqual(preview_status, 200)
                    self.assertTrue(preview_payload["ok"])
                    self.assertEqual(preview_payload["form_fields"]["knowledge_pack"], "policy_bundle")
                    self.assertEqual(len(preview_payload["plan_messages"]), 1)
                    self.assertIn("\u4efb\u52a1\u662f\u4ec0\u4e48", preview_payload["workbench_html"])
                    self.assertIn("\u7cfb\u7edf\u600e\u4e48\u51b3\u5b9a\u8fd9\u6837\u505a", preview_payload["workbench_html"])
                    self.assertIn("\u67e5\u770b\u539f\u59cb Prompt", preview_payload["workbench_html"])
                    self.assertNotIn("\u653f\u7b56\u6750\u6599\u5305", preview_payload["scope_html"])
                    self.assertIn("\u6d89\u53ca\u653f\u7b56\u6750\u6599\u65f6", preview_payload["scope_html"])
                    self.assertIn("\u62ff\u5230\u4e86\u54ea\u4e9b\u5173\u952e\u8bc1\u636e", preview_payload["scope_html"])
                    self.assertIn("docs", preview_payload["form_fields"]["context_paths_text"])
                    self.assertIn("ops", preview_payload["form_fields"]["context_paths_text"])
                    self.assertIn("docs", preview_payload["form_fields"]["editable_paths_text"])
                    self.assertIn("ops", preview_payload["form_fields"]["editable_paths_text"])
                    self.assertIn("\u516c\u544a\u3001\u8303\u56f4\u3001\u65e5\u671f\u548c\u6267\u884c\u6e05\u5355\u5e94\u4fdd\u6301\u4e00\u81f4", preview_payload["form_fields"]["behavioral_checks_text"])

                    run_status, accepted_payload = _post_json(f"{base_url}/api/run-demo-async", payload)
                    self.assertEqual(run_status, 202)
                    self.assertTrue(accepted_payload["ok"])

                    run_payload = _poll_async_job(base_url, str(accepted_payload["job_id"]))
                    self.assertTrue(run_payload["ok"])
                    self.assertTrue(run_payload["done"])
                    self.assertEqual(run_payload["job_status"], "succeeded")
                    self.assertEqual(run_payload["form_fields"]["knowledge_pack"], "policy_bundle")
                    self.assertEqual(len(run_payload["results"]), 1)
                    self.assertTrue(all(item["status"] == "succeeded" for item in run_payload["results"]))
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()

    def test_live_portal_previews_and_runs_freeform_task_with_draft_harness(self) -> None:
        runtime_root = Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT)) / "runtime"
        intake_path = REPO_ROOT / "examples" / "intakes" / "provider_policy_bundle_task_intake.json"
        repo_root = _init_git_repo(Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT)) / "repo", {"README.md": "# Old Title\n"})

        def fake_generate(self, messages):
            payload = {
                "summary": "rewrite readme from freeform task",
                "writes": [
                    {
                        "path": "README.md",
                        "content": "# New Title\n\nThis repo is used for the freeform portal harness demo.\n",
                    }
                ],
            }
            return ProviderResponse(
                content=json.dumps(payload, ensure_ascii=False),
                model=self.model,
                usage=ProviderUsage(prompt_tokens=24, completion_tokens=12, total_tokens=36),
            )

        env = {
            "REPO_HARNESS_LAB_PROJECT_ROOT": str(REPO_ROOT),
            "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
            "DASHSCOPE_API_KEY": "test-key",
        }
        with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
            with patch.dict(os.environ, env, clear=False):
                settings = load_settings()
                settings.paths.ensure_runtime_directories()
                live_entry = PortalLiveEntryConfig(
                    template_id="provider_policy_bundle",
                    intake_source_path=intake_path,
                    provider="qwen",
                    model="qwen-plus",
                    api_key_env="DASHSCOPE_API_KEY",
                )
                server = build_portal_http_server(settings=settings, live_entry=live_entry, host="127.0.0.1", port=0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    minimal_payload = {
                        "task_text": "Please update README.md title and add one line explaining this repo is used for the freeform portal harness demo.",
                        "task_shape": "doc_update",
                        "repo_path": repo_root.as_uri(),
                    }

                    preview_status, preview_payload = _post_json(f"{base_url}/api/preview-demo", minimal_payload)
                    self.assertEqual(preview_status, 200)
                    self.assertTrue(preview_payload["ok"])
                    self.assertIn("\u7cfb\u7edf\u81ea\u52a8\u8349\u62df", preview_payload["scope_html"])
                    self.assertIn("\u7cfb\u7edf\u600e\u4e48\u51b3\u5b9a\u8fd9\u6837\u505a", preview_payload["scope_html"])
                    self.assertIn("README.md", preview_payload["scope_html"])
                    self.assertNotIn("\u6587\u6863\u66f4\u65b0", preview_payload["scope_html"])
                    self.assertEqual(preview_payload["form_fields"]["repo_path"], repo_root.as_uri())
                    self.assertEqual(preview_payload["form_fields"]["task_shape"], "doc_update")
                    self.assertIn("draft-completion-check", preview_payload["form_fields"]["acceptance_checks_text"])
                    self.assertIn("README.md", preview_payload["form_fields"]["editable_paths_text"])
                    self.assertIn("README.md", preview_payload["form_fields"]["expected_changed_files_text"])
                    self.assertIn("\u6587\u6863\u6539\u52a8\u5e94\u4fdd\u6301", preview_payload["form_fields"]["behavioral_checks_text"])

                    run_status, accepted_payload = _post_json(f"{base_url}/api/run-demo-async", minimal_payload)
                    self.assertEqual(run_status, 202)
                    self.assertTrue(accepted_payload["ok"])
                    self.assertFalse(accepted_payload["done"])
                    self.assertEqual(accepted_payload["job_status"], "pending")
                    self.assertEqual(accepted_payload["current_phase"], "queued")
                    self.assertTrue(str(accepted_payload["job_id"]).startswith("portal-job-"))

                    run_payload = _poll_async_job(base_url, str(accepted_payload["job_id"]))
                    self.assertTrue(run_payload["ok"])
                    self.assertTrue(run_payload["done"])
                    self.assertEqual(run_payload["job_status"], "succeeded")
                    self.assertEqual(run_payload["current_phase"], "completed")
                    self.assertEqual(len(run_payload["results"]), 1)
                    self.assertIn("\u8349\u62df\u9a8c\u6536\u4f30\u7b97", run_payload["status_text"])
                    self.assertIn("\u5f53\u524d\u662f\u81ea\u7531\u4efb\u52a1\u8349\u62df\u9a8c\u6536", run_payload["results_html"])
                    self.assertIn("\u6700\u7ec8\u7ed3\u679c\u662f\u4ec0\u4e48", run_payload["workbench_html"])
                    self.assertIn("README.md", run_payload["recent_history_html"])
                    self.assertEqual(run_payload["form_fields"]["task_shape"], "doc_update")
                    self.assertIn("draft-completion-check", run_payload["form_fields"]["acceptance_checks_text"])
                    self.assertTrue(all(item["status"] == "succeeded" for item in run_payload["results"]))
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    server.server_close()

def _get_json(url: str) -> tuple[int, dict[str, object]]:
    with _NO_PROXY_OPENER.open(url) as response:
        return response.getcode(), json.loads(response.read().decode("utf8"))


def _get_text(url: str) -> tuple[int, str]:
    with _NO_PROXY_OPENER.open(url) as response:
        return response.getcode(), response.read().decode("utf8")


def _post_json(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _NO_PROXY_OPENER.open(request) as response:
        return response.getcode(), json.loads(response.read().decode("utf8"))


def _post_json_allow_error(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _NO_PROXY_OPENER.open(request) as response:
            return response.getcode(), json.loads(response.read().decode("utf8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf8"))


def _poll_async_job(base_url: str, job_id: str, *, timeout: float = 15.0) -> dict[str, object]:
    deadline = time.time() + timeout
    last_payload: dict[str, object] | None = None
    while time.time() < deadline:
        status_code, payload = _get_json(f"{base_url}/api/run-demo-status?job_id={job_id}")
        last_payload = payload
        if status_code == 200 and payload.get("done") is True:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"async portal job did not finish in time: {last_payload}")


def _init_git_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    subprocess.run(["git", "config", "user.name", "Repo Harness"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    subprocess.run(["git", "config", "user.email", "repo-harness@example.test"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    for relative_path, content in files.items():
        file_path = path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True, encoding="utf8", errors="replace")
    return path


if __name__ == "__main__":
    unittest.main()

