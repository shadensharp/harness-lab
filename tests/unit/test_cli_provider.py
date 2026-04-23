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

from repo_harness_lab.agents.providers.base import ProviderResponse, ProviderUsage
from repo_harness_lab.agents.providers.openai_compatible import OpenAICompatibleChatProvider
from repo_harness_lab.cli.main import main


class CliProviderTests(unittest.TestCase):
    def test_run_task_supports_provider_backed_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_repo = root / "source-repo"
            source_repo.mkdir()
            runtime_root = root / "runtime"
            task_path = root / "task.json"
            (source_repo / "README.md").write_text("hello\n", encoding="utf8")
            task_path.write_text(
                json.dumps(
                    {
                        "task_id": "task-001",
                        "title": "Provider run",
                        "description": "Update README.md so that it says updated.",
                        "task_type": "requirement_change",
                        "repo_source": {
                            "kind": "local_path",
                            "path_or_url": str(source_repo),
                            "checkout_mode": "copy"
                        },
                        "success_criteria": {
                            "changed_files": ["README.md"]
                        },
                        "constraints": {
                            "editable_paths": ["README.md"]
                        },
                        "verifier_plan": {
                            "steps": [
                                {
                                    "name": "artifact-check",
                                    "kind": "test",
                                    "command": [
                                        sys.executable,
                                        "-c",
                                        "from pathlib import Path; raise SystemExit(0 if Path('README.md').read_text(encoding='utf8') == 'updated\\n' else 1)"
                                    ]
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            def fake_generate(self, messages):
                return ProviderResponse(
                    content=json.dumps(
                        {
                            "summary": "updated by provider",
                            "writes": [{"path": "README.md", "content": "updated\n"}],
                        },
                        ensure_ascii=False,
                    ),
                    model=self.model,
                    usage=ProviderUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                )

            buffer = io.StringIO()
            env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root)}
            with patch.object(OpenAICompatibleChatProvider, "generate", autospec=True, side_effect=fake_generate):
                with patch.dict(os.environ, env, clear=False):
                    with redirect_stdout(buffer):
                        exit_code = main(
                            [
                                "run-task",
                                str(task_path),
                                "--agent-provider",
                                "qwen",
                                "--agent-model",
                                "qwen-plus",
                                "--agent-api-key",
                                "test-key",
                                "--harness-profile",
                                "current",
                            ]
                        )

            payload = json.loads(buffer.getvalue())
            summary_path = runtime_root / "runs" / payload["run_id"] / "summary.json"

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "succeeded")
            self.assertEqual(payload["cost_summary"]["total_tokens"], 15)
            self.assertIn("README.md", payload["changed_files"])
            self.assertTrue(summary_path.exists())


if __name__ == "__main__":
    unittest.main()
