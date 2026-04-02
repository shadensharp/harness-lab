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


class CliEvalTests(unittest.TestCase):
    def test_run_eval_executes_suite_and_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            runtime_root = root / "runtime"
            source_repo = root / "source-repo"
            source_repo.mkdir()
            (source_repo / "README.md").write_text("hello\n", encoding="utf8")

            task_path = root / "task.json"
            task_path.write_text(
                json.dumps(
                    {
                        "task_id": "task-001",
                        "title": "Eval task",
                        "description": "Run through eval CLI",
                        "task_type": "requirement_change",
                        "repo_source": {
                            "kind": "local_path",
                            "path_or_url": str(source_repo),
                            "checkout_mode": "copy",
                        },
                        "verifier_plan": {
                            "steps": [
                                {
                                    "name": "artifact-check",
                                    "kind": "test",
                                    "command": [
                                        sys.executable,
                                        "-c",
                                        "from pathlib import Path; raise SystemExit(0 if Path('generated.txt').read_text(encoding='utf8') == 'ok' else 1)",
                                    ],
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            suite_path = root / "suite.json"
            suite_path.write_text(
                json.dumps(
                    {
                        "suite_id": "suite-001",
                        "cases": [
                            {
                                "case_id": "case-001",
                                "task_spec_ref": str(task_path),
                                "run_matrix": [
                                    {
                                        "label": "pass-script",
                                        "harness_profile": "basic",
                                        "request": {
                                            "agent_profile": {
                                                "name": "local-script",
                                                "provider": "local_script",
                                                "metadata": {
                                                    "command": [
                                                        sys.executable,
                                                        "-c",
                                                        "from pathlib import Path; Path('generated.txt').write_text('ok', encoding='utf8')",
                                                    ]
                                                },
                                            }
                                        },
                                    },
                                    {
                                        "label": "noop",
                                        "harness_profile": "bare",
                                        "request": {
                                            "agent_profile": {
                                                "name": "noop-agent",
                                                "provider": "local",
                                            }
                                        },
                                    },
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root)}
            buffer = io.StringIO()
            with patch.dict(os.environ, env, clear=False):
                with redirect_stdout(buffer):
                    exit_code = main(["run-eval", str(suite_path)])

            payload = json.loads(buffer.getvalue())
            artifacts = payload["artifacts"]
            comparison_paths = [Path(item) for item in artifacts["comparison_html_paths"]]
            html_report = Path(artifacts["html_report_path"]).read_text(encoding="utf8")

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["suite_id"], "suite-001")
            self.assertEqual(payload["case_count"], 1)
            self.assertEqual(payload["aggregate_metrics"]["total_trials"], 2.0)
            self.assertEqual(payload["profile_uplift"]["baseline_profile"], "bare")
            self.assertEqual(payload["profile_uplift"]["basic"]["pass_rate_delta"], 1.0)
            self.assertTrue(Path(artifacts["json_report_path"]).exists())
            self.assertTrue(Path(artifacts["markdown_report_path"]).exists())
            self.assertTrue(Path(artifacts["html_report_path"]).exists())
            self.assertTrue(Path(artifacts["uplift_dashboard_path"]).exists())
            self.assertEqual(len(comparison_paths), 1)
            self.assertTrue(comparison_paths[0].exists())
            self.assertIn("流程时间线对比", comparison_paths[0].read_text(encoding="utf8"))
            self.assertIn("# Eval suite-001", Path(artifacts["markdown_report_path"]).read_text(encoding="utf8"))
            self.assertIn("评测结果 suite-001", html_report)
            self.assertIn("用户任务与结果", html_report)
            self.assertIn("任务输出", html_report)
            self.assertIn("generated.txt", html_report)
            uplift_html = Path(artifacts["uplift_dashboard_path"]).read_text(encoding="utf8")
            self.assertIn("同模型 Harness 结果页", uplift_html)
            self.assertIn("用户任务", uplift_html)
            self.assertIn("三档结果", uplift_html)
            self.assertIn("打开运行报告", uplift_html)
            self.assertIn("任务输出", uplift_html)
            self.assertIn("generated.txt", uplift_html)

    def test_run_eval_supports_provider_backed_uplift_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            runtime_root = root / "runtime"
            repo_root = root / "repo"
            docs_dir = repo_root / "docs"
            docs_dir.mkdir(parents=True)
            (repo_root / "README.md").write_text("# Placeholder\n", encoding="utf8")
            (docs_dir / "target_title.txt").write_text("Golden Title\n", encoding="utf8")

            task_path = root / "task.json"
            task_path.write_text(
                json.dumps(
                    {
                        "task_id": "task-provider-001",
                        "title": "Provider eval task",
                        "description": "请把 README.md 的第一行更新为 docs/target_title.txt 中给出的准确标题。",
                        "task_type": "requirement_change",
                        "repo_source": {
                            "kind": "local_path",
                            "path_or_url": "./repo",
                            "checkout_mode": "copy"
                        },
                        "constraints": {
                            "editable_paths": ["README.md"],
                            "forbidden_paths": ["docs"]
                        },
                        "success_criteria": {
                            "required_verifier_steps": ["readme-title-check"],
                            "changed_files": ["README.md"]
                        },
                        "verifier_plan": {
                            "steps": [
                                {
                                    "name": "readme-title-check",
                                    "kind": "test",
                                    "command": [
                                        sys.executable,
                                        "-c",
                                        "from pathlib import Path; target = Path('docs/target_title.txt').read_text(encoding='utf8').strip(); readme = Path('README.md').read_text(encoding='utf8').splitlines()[0].lstrip('#').strip(); raise SystemExit(0 if readme == target else 1)"
                                    ]
                                }
                            ]
                        },
                        "benchmark_metadata": {
                            "tier": "curated",
                            "difficulty": "medium",
                            "tags": ["provider_uplift"],
                            "harness_signals": ["repo_context"]
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )
            suite_path = root / "suite.json"
            suite_path.write_text(
                json.dumps(
                    {
                        "suite_id": "suite-provider-001",
                        "cases": [
                            {
                                "case_id": "case-provider-001",
                                "task_spec_ref": str(task_path),
                                "run_matrix": [
                                    {
                                        "label": "qwen-bare",
                                        "harness_profile": "bare",
                                        "request": {
                                            "agent_profile": {
                                                "name": "qwen-plus",
                                                "provider": "qwen",
                                                "metadata": {
                                                    "model": "qwen-plus",
                                                    "api_key_env": "DASHSCOPE_API_KEY"
                                                }
                                            }
                                        }
                                    },
                                    {
                                        "label": "qwen-basic",
                                        "harness_profile": "basic",
                                        "request": {
                                            "agent_profile": {
                                                "name": "qwen-plus",
                                                "provider": "qwen",
                                                "metadata": {
                                                    "model": "qwen-plus",
                                                    "api_key_env": "DASHSCOPE_API_KEY"
                                                }
                                            }
                                        }
                                    },
                                    {
                                        "label": "qwen-full",
                                        "harness_profile": "full",
                                        "request": {
                                            "agent_profile": {
                                                "name": "qwen-plus",
                                                "provider": "qwen",
                                                "metadata": {
                                                    "model": "qwen-plus",
                                                    "api_key_env": "DASHSCOPE_API_KEY"
                                                }
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            def fake_generate(self, messages):
                user_prompt = messages[1].content
                title = "Golden Title" if "Golden Title" in user_prompt else "Guess Title"
                return ProviderResponse(
                    content=json.dumps(
                        {
                            "summary": f"set title to {title}",
                            "writes": [{"path": "README.md", "content": f"# {title}\n"}],
                        },
                        ensure_ascii=False,
                    ),
                    model=self.model,
                    usage=ProviderUsage(prompt_tokens=20, completion_tokens=8, total_tokens=28),
                )

            buffer = io.StringIO()
            env = {
                "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
                "DASHSCOPE_API_KEY": "test-key",
            }
            with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
                with patch.dict(os.environ, env, clear=False):
                    with redirect_stdout(buffer):
                        exit_code = main(["run-eval", str(suite_path)])

            payload = json.loads(buffer.getvalue())
            profile_uplift = payload["profile_uplift"]
            artifacts = payload["artifacts"]
            comparison_paths = [Path(item) for item in artifacts["comparison_html_paths"]]
            html_report = Path(artifacts["html_report_path"]).read_text(encoding="utf8")
            uplift_html = Path(artifacts["uplift_dashboard_path"]).read_text(encoding="utf8")

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["suite_id"], "suite-provider-001")
            self.assertEqual(payload["aggregate_metrics"]["total_trials"], 3.0)
            self.assertEqual(profile_uplift["baseline_profile"], "bare")
            self.assertEqual(profile_uplift["bare"]["pass_rate"], 0.0)
            self.assertEqual(profile_uplift["basic"]["pass_rate"], 1.0)
            self.assertEqual(profile_uplift["full"]["pass_rate"], 1.0)
            self.assertEqual(profile_uplift["basic"]["pass_rate_delta"], 1.0)
            self.assertEqual(profile_uplift["full"]["pass_rate_delta"], 1.0)
            self.assertTrue(Path(artifacts["html_report_path"]).exists())
            self.assertTrue(Path(artifacts["uplift_dashboard_path"]).exists())
            self.assertEqual(len(comparison_paths), 3)
            self.assertTrue(all(path.exists() for path in comparison_paths))
            self.assertIn("同模型 Harness 抬升", html_report)
            self.assertIn("用户任务与结果", html_report)
            self.assertIn("任务输出", html_report)
            self.assertIn("同模型 Harness 结果页", uplift_html)
            self.assertIn("用户任务", uplift_html)
            self.assertIn("三档结果", uplift_html)
            self.assertIn("打开对比页面", uplift_html)
            self.assertIn("打开公平对比页面", uplift_html)
            self.assertIn("打开抬升对比页面", uplift_html)
            self.assertIn("上下文文件：0", uplift_html)
            self.assertIn("上下文文件：2", uplift_html)
            self.assertIn("Token：提示 20，生成 8，总计 28", uplift_html)
            self.assertTrue(any("Harness 差异" in path.read_text(encoding="utf8") for path in comparison_paths))
            self.assertTrue(any("上下文文件: 0 -&gt; 2 (+2)" in path.read_text(encoding="utf8") for path in comparison_paths))
            self.assertIn("set title to Guess Title", uplift_html)
            self.assertIn("Golden Title", uplift_html)

            Path(artifacts["html_report_path"]).unlink()
            Path(artifacts["markdown_report_path"]).unlink()
            for path in comparison_paths:
                path.unlink()

            rerender_buffer = io.StringIO()
            with patch.dict(os.environ, env, clear=False):
                with redirect_stdout(rerender_buffer):
                    rerender_exit = main(["render-eval-report", "suite-provider-001"])

            rerender_payload = json.loads(rerender_buffer.getvalue())
            rerender_html_path = Path(rerender_payload["artifacts"]["html_report_path"])
            rerender_markdown_path = Path(rerender_payload["artifacts"]["markdown_report_path"])
            rerender_comparison_paths = [Path(item) for item in rerender_payload["artifacts"]["comparison_html_paths"]]
            rerender_html = rerender_html_path.read_text(encoding="utf8")

            self.assertEqual(rerender_exit, 0)
            self.assertTrue(rerender_html_path.exists())
            self.assertTrue(rerender_markdown_path.exists())
            self.assertEqual(len(rerender_comparison_paths), 3)
            self.assertTrue(all(path.exists() for path in rerender_comparison_paths))
            self.assertIn("用户任务与结果", rerender_html)
            self.assertIn("任务输出", rerender_html)
            self.assertIn("同模型 Harness 抬升", rerender_html)
            self.assertTrue(any("Harness 差异" in path.read_text(encoding="utf8") for path in rerender_comparison_paths))
            self.assertTrue(any("上下文文件: 0 -&gt; 2 (+2)" in path.read_text(encoding="utf8") for path in rerender_comparison_paths))


    def test_run_eval_supports_example_multi_signal_provider_uplift_suite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            runtime_root = Path(temp_root) / "runtime"
            suite_path = REPO_ROOT / "examples" / "evals" / "qwen_provider_multi_signal_uplift_suite.json"

            def fake_generate(self, messages):
                user_prompt = messages[1].content
                if "provider-readme-title-sync" in user_prompt:
                    title = "Golden Title" if "Golden Title" in user_prompt else "Guess Title"
                    payload = {
                        "summary": f"set readme title to {title}",
                        "writes": [
                            {
                                "path": "README.md",
                                "content": f"# {title}\n\nThis repository is used by the provider uplift example.\n",
                            }
                        ],
                    }
                elif "release-input-sync" in user_prompt:
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
                            "summary": "guess release spec from repo context",
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
                else:
                    raise AssertionError(f"unexpected provider prompt: {user_prompt}")

                return ProviderResponse(
                    content=json.dumps(payload, ensure_ascii=False),
                    model=self.model,
                    usage=ProviderUsage(prompt_tokens=32, completion_tokens=14, total_tokens=46),
                )

            buffer = io.StringIO()
            env = {
                "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
                "DASHSCOPE_API_KEY": "test-key",
            }
            with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
                with patch.dict(os.environ, env, clear=False):
                    with redirect_stdout(buffer):
                        exit_code = main(["run-eval", str(suite_path)])

            payload = json.loads(buffer.getvalue())
            profile_uplift = payload["profile_uplift"]
            artifacts = payload["artifacts"]
            comparison_paths = [Path(item) for item in artifacts["comparison_html_paths"]]
            html_report = Path(artifacts["html_report_path"]).read_text(encoding="utf8")
            uplift_html = Path(artifacts["uplift_dashboard_path"]).read_text(encoding="utf8")

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["suite_id"], "qwen-provider-multi-signal-uplift-suite")
            self.assertEqual(payload["case_count"], 2)
            self.assertEqual(payload["aggregate_metrics"]["total_trials"], 6.0)
            self.assertEqual(profile_uplift["baseline_profile"], "bare")
            self.assertEqual(profile_uplift["bare"]["pass_rate"], 0.0)
            self.assertEqual(profile_uplift["basic"]["pass_rate"], 0.5)
            self.assertEqual(profile_uplift["full"]["pass_rate"], 1.0)
            self.assertEqual(profile_uplift["basic"]["pass_rate_delta"], 0.5)
            self.assertEqual(profile_uplift["full"]["pass_rate_delta"], 1.0)
            self.assertEqual(len(comparison_paths), 6)
            self.assertTrue(all(path.exists() for path in comparison_paths))
            self.assertIn("release-input-sync", html_report)
            self.assertIn("用户任务", html_report)
            self.assertIn("任务输出", html_report)
            self.assertIn("同模型 Harness 抬升", html_report)
            self.assertIn("Paper Lantern", html_report)
            self.assertIn("同模型 Harness 结果页", uplift_html)
            self.assertIn("用户任务", uplift_html)
            self.assertIn("三档结果", uplift_html)
            self.assertIn("打开运行报告", html_report)
            self.assertIn("打开当前套件", uplift_html)
            self.assertIn("更多证据", uplift_html)
            self.assertIn("推荐任务", uplift_html)
            self.assertIn("release-input-sync", uplift_html)
            self.assertIn("Golden Title", uplift_html)
            self.assertIn("guess release spec from repo context", uplift_html)
            self.assertIn("release_sync", uplift_html)
            self.assertIn("声明了 Harness 信号：multi_file_edit, task_inputs, verifier_plan", uplift_html)
            self.assertIn("Token：提示 32，生成 14，总计 46", uplift_html)
            self.assertTrue(any("上下文文件: 0 -&gt; 3 (+3)" in path.read_text(encoding="utf8") for path in comparison_paths))
            self.assertTrue(any("Paper Lantern" in path.read_text(encoding="utf8") for path in comparison_paths))
    def test_run_eval_supports_example_extended_provider_uplift_suite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            runtime_root = Path(temp_root) / "runtime"
            suite_path = REPO_ROOT / "examples" / "evals" / "qwen_provider_extended_uplift_suite.json"

            def fake_generate(self, messages):
                user_prompt = messages[1].content
                if "provider-readme-title-sync" in user_prompt:
                    title = "Golden Title" if "Golden Title" in user_prompt else "Guess Title"
                    payload = {
                        "summary": f"set readme title to {title}",
                        "writes": [
                            {
                                "path": "README.md",
                                "content": f"# {title}\n\nThis repository is used by the provider uplift example.\n",
                            }
                        ],
                    }
                elif "provider-release-input-sync" in user_prompt:
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
                            "summary": "guess release spec from repo context",
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
                elif "provider-policy-bundle-sync" in user_prompt:
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
                else:
                    raise AssertionError(f"unexpected provider prompt: {user_prompt}")

                return ProviderResponse(
                    content=json.dumps(payload, ensure_ascii=False),
                    model=self.model,
                    usage=ProviderUsage(prompt_tokens=40, completion_tokens=18, total_tokens=58),
                )

            buffer = io.StringIO()
            env = {
                "REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root),
                "DASHSCOPE_API_KEY": "test-key",
            }
            with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
                with patch.dict(os.environ, env, clear=False):
                    with redirect_stdout(buffer):
                        exit_code = main(["run-eval", str(suite_path)])

            payload = json.loads(buffer.getvalue())
            profile_uplift = payload["profile_uplift"]
            artifacts = payload["artifacts"]
            comparison_paths = [Path(item) for item in artifacts["comparison_html_paths"]]
            html_report = Path(artifacts["html_report_path"]).read_text(encoding="utf8")
            uplift_html = Path(artifacts["uplift_dashboard_path"]).read_text(encoding="utf8")

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["suite_id"], "qwen-provider-extended-uplift-suite")
            self.assertEqual(payload["case_count"], 3)
            self.assertEqual(payload["aggregate_metrics"]["total_trials"], 9.0)
            self.assertEqual(profile_uplift["baseline_profile"], "bare")
            self.assertEqual(profile_uplift["bare"]["pass_rate"], 0.0)
            self.assertAlmostEqual(profile_uplift["basic"]["pass_rate"], 1 / 3)
            self.assertEqual(profile_uplift["full"]["pass_rate"], 1.0)
            self.assertAlmostEqual(profile_uplift["basic"]["pass_rate_delta"], 1 / 3)
            self.assertEqual(profile_uplift["full"]["pass_rate_delta"], 1.0)
            self.assertEqual(len(comparison_paths), 9)
            self.assertTrue(all(path.exists() for path in comparison_paths))
            self.assertIn("policy-bundle-sync", html_report)
            self.assertIn("trust-ops@example.test", html_report)
            self.assertIn("repo_context", html_report)
            self.assertIn("共同任务信息", html_report)
            self.assertIn("三档额外交付", html_report)
            self.assertIn("同模型 Harness 结果页", uplift_html)
            self.assertIn("用户任务", uplift_html)
            self.assertIn("共同任务信息", uplift_html)
            self.assertIn("三档结果", uplift_html)
            self.assertIn("assemble policy bundle from partial repo context", uplift_html)
            self.assertIn("policy-bundle-sync", uplift_html)
            self.assertIn("policy_sync", uplift_html)
            self.assertTrue(any("trust-ops@example.test" in path.read_text(encoding="utf8") for path in comparison_paths))
            self.assertTrue(any("上下文文件: 0 -&gt; 8 (+8)" in path.read_text(encoding="utf8") for path in comparison_paths))
            self.assertTrue(any("新增任务输入" in path.read_text(encoding="utf8") for path in comparison_paths))

if __name__ == "__main__":
    unittest.main()










