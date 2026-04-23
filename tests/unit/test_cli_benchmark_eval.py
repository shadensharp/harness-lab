from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.agents.adapters.local_script import LocalScriptAgentAdapter
from repo_harness_lab.cli.main import main


class CliBenchmarkEvalTests(unittest.TestCase):
    def test_run_benchmark_eval_scaffolds_suite_and_pins_repo_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            runtime_root = root / "runtime"
            source_repo = _init_git_repo(root / "source-repo", {"README.md": "alpha\n"})
            first_revision = _git_head(source_repo)
            (source_repo / "README.md").write_text("beta\n", encoding="utf8")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=source_repo,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf8",
                errors="replace",
            )
            subprocess.run(
                ["git", "commit", "-m", "second"],
                cwd=source_repo,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf8",
                errors="replace",
            )

            benchmark_path = root / "benchmark.json"
            benchmark_path.write_text(
                json.dumps(
                    {
                        "benchmark_id": "swe-bench-sample",
                        "metric_name": "resolved_rate",
                        "cases": [
                            {
                                "instance_id": "swe-bench-001",
                                "source_url": "https://example.test/swe-bench/001",
                                "task": {
                                    "task_id": "swe-bench-001-task",
                                    "title": "Pinned revision task",
                                    "description": "Read the pinned README.md and copy its content into observed.txt.",
                                    "task_type": "requirement_change",
                                    "repo_source": {
                                        "kind": "git_url",
                                        "path_or_url": source_repo.as_uri(),
                                        "checkout_mode": "copy"
                                    },
                                    "repo_revision": first_revision,
                                    "constraints": {
                                        "editable_paths": ["observed.txt"]
                                    },
                                    "verifier_plan": {
                                        "steps": [
                                            {
                                                "name": "pinned-readme-check",
                                                "kind": "test",
                                                "command": [
                                                    sys.executable,
                                                    "-c",
                                                    "from pathlib import Path; expected='alpha'; observed=Path('observed.txt').read_text(encoding='utf8').strip(); raise SystemExit(0 if observed == expected else 1)"
                                                ]
                                            }
                                        ]
                                    },
                                    "benchmark_metadata": {
                                        "tier": "curated",
                                        "difficulty": "medium",
                                        "tags": ["external_benchmark"],
                                        "harness_signals": ["repo_context", "verifier_plan"],
                                        "source": "swe-bench-sample"
                                    }
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root)}
            buffer = io.StringIO()
            agent = LocalScriptAgentAdapter(
                script_command=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('observed.txt').write_text(Path('README.md').read_text(encoding='utf8').strip(), encoding='utf8')",
                ),
            )
            with patch("repo_harness_lab.cli.commands.evals.build_agent_adapter", return_value=agent):
                with patch.dict(os.environ, env, clear=False):
                    with redirect_stdout(buffer):
                        exit_code = main(
                            [
                                "run-benchmark-eval",
                                str(benchmark_path),
                                "--provider",
                                "local",
                                "--model",
                                "deterministic-agent",
                            ]
                        )

            payload = json.loads(buffer.getvalue())
            report_payload = json.loads(Path(payload["artifacts"]["json_report_path"]).read_text(encoding="utf8"))
            generated_task = json.loads(Path(payload["generated_task_spec_paths"][0]).read_text(encoding="utf8"))
            trials = report_payload["case_results"][0]["trials"]

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["benchmark_id"], "swe-bench-sample")
            self.assertEqual(payload["benchmark_metric_name"], "resolved_rate")
            self.assertEqual(payload["benchmark_score"], 1.0)
            self.assertEqual(payload["benchmark_score_source_metric"], "pass_rate")
            self.assertEqual(payload["benchmark_score_semantics"], "pass_rate_over_materialized_cases")
            self.assertFalse(payload["benchmark_score_matches_official_metric"])
            self.assertEqual(Path(payload["generated_suite_path"]).name, "swe-bench-sample-benchmark-baseline-suite.suite.json")
            self.assertEqual(payload["benchmark_profile_scores"]["current"], 1.0)
            self.assertEqual(payload["benchmark_profile_score_semantics"], "pass_rate_over_materialized_cases")
            self.assertTrue(Path(payload["generated_suite_path"]).exists())
            self.assertEqual(len(payload["generated_task_spec_paths"]), 1)
            self.assertEqual(generated_task["repo_revision"], first_revision)
            self.assertEqual(generated_task["metadata"]["benchmark_context"]["instance_id"], "swe-bench-001")
            self.assertEqual(
                generated_task["metadata"]["benchmark_context"]["score_semantics"],
                "pass_rate_over_materialized_cases",
            )
            self.assertFalse(generated_task["metadata"]["benchmark_context"]["official_metric_equivalent"])
            self.assertEqual(len(trials), 1)
            self.assertEqual(trials[0]["harness_profile"], "current")
            self.assertEqual(trials[0]["notes"], ["swe-bench-sample-current"])
            self.assertEqual(trials[0]["run_summary"]["status"], "succeeded")
            self.assertTrue(
                trials[0]["run_summary"]["metadata"]["resolved_repo_revision"] == first_revision
            )
            self.assertTrue(
                trials[0]["run_summary"]["metadata"]["benchmark_context"]["metric_name"] == "resolved_rate"
            )
            self.assertTrue(
                trials[0]["run_summary"]["metadata"]["benchmark_context"]["score_semantics"]
                == "pass_rate_over_materialized_cases"
            )
            self.assertTrue(
                trials[0]["run_summary"]["metadata"]["benchmark_context"]["official_metric_equivalent"] is False
            )

    def test_run_benchmark_eval_supports_custom_baseline_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            runtime_root = root / "runtime"
            reports_dir = runtime_root / "reports"
            reports_dir.mkdir(parents=True)
            (reports_dir / "baseline-suite.json").write_text(
                json.dumps(
                    {
                        "suite_id": "baseline-suite",
                        "aggregate_metrics": [
                            {"name": "pass_rate", "value": 0.0, "unit": "ratio"},
                            {"name": "average_duration_ms", "value": 1500.0, "unit": "ms"},
                            {"name": "total_cases", "value": 1.0, "unit": "count"},
                            {"name": "total_trials", "value": 1.0, "unit": "count"},
                        ],
                        "comparison_views": [],
                        "case_results": [
                            {
                                "case_id": "swe-bench-001",
                                "summary": {"pass_rate": 0.0},
                                "trials": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            source_repo = _init_git_repo(root / "source-repo", {"README.md": "alpha\n"})
            first_revision = _git_head(source_repo)
            benchmark_path = root / "benchmark.json"
            benchmark_path.write_text(
                json.dumps(
                    {
                        "benchmark_id": "swe-bench-sample",
                        "metric_name": "resolved_rate",
                        "cases": [
                            {
                                "instance_id": "swe-bench-001",
                                "task": {
                                    "task_id": "swe-bench-001-task",
                                    "title": "Pinned revision task",
                                    "description": "Read the pinned README.md and copy its content into observed.txt.",
                                    "task_type": "requirement_change",
                                    "repo_source": {
                                        "kind": "git_url",
                                        "path_or_url": source_repo.as_uri(),
                                        "checkout_mode": "copy"
                                    },
                                    "repo_revision": first_revision,
                                    "constraints": {
                                        "editable_paths": ["observed.txt"]
                                    },
                                    "verifier_plan": {
                                        "steps": [
                                            {
                                                "name": "pinned-readme-check",
                                                "kind": "test",
                                                "command": [
                                                    sys.executable,
                                                    "-c",
                                                    "from pathlib import Path; expected='alpha'; observed=Path('observed.txt').read_text(encoding='utf8').strip(); raise SystemExit(0 if observed == expected else 1)"
                                                ]
                                            }
                                        ]
                                    },
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            env = {"REPO_HARNESS_LAB_RUNTIME_ROOT": str(runtime_root)}
            buffer = io.StringIO()
            agent = LocalScriptAgentAdapter(
                script_command=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('observed.txt').write_text(Path('README.md').read_text(encoding='utf8').strip(), encoding='utf8')",
                ),
            )
            with patch("repo_harness_lab.cli.commands.evals.build_agent_adapter", return_value=agent):
                with patch.dict(os.environ, env, clear=False):
                    with redirect_stdout(buffer):
                        exit_code = main(
                            [
                                "run-benchmark-eval",
                                str(benchmark_path),
                                "--provider",
                                "local",
                                "--model",
                                "deterministic-agent",
                                "--suite-id",
                                "current-suite",
                                "--baseline-report-id",
                                "baseline-suite",
                            ]
                        )

            payload = json.loads(buffer.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["baseline_comparison"]["baseline_kind"], "custom")
            self.assertEqual(payload["baseline_comparison"]["baseline_report_id"], "baseline-suite")
            self.assertEqual(payload["baseline_comparison"]["pass_rate_delta"], 1.0)


def _init_git_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
    )
    subprocess.run(
        ["git", "config", "user.name", "Repo Harness"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
    )
    subprocess.run(
        ["git", "config", "user.email", "repo-harness@example.test"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
    )
    for relative_path, content in files.items():
        file_path = path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf8")
    subprocess.run(
        ["git", "add", "."],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
    )
    return path


def _git_head(path: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
