from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.run_models import RunStatus, RunSummary
from repo_harness_lab.domain.trace_models import CommandExecutionRecord
from repo_harness_lab.domain.verifier_models import VerificationEvidence, VerificationStatus, VerifierResult
from repo_harness_lab.reporting.failure_summary import build_failure_summary
from repo_harness_lab.reporting.html import HtmlReporter
from repo_harness_lab.reporting.markdown import MarkdownReporter
from repo_harness_lab.storage.run_store import StoredRunRecord


class FailureReportingTests(unittest.TestCase):
    def test_build_failure_summary_explains_failed_verifier(self) -> None:
        record = self._failed_record()

        summary = build_failure_summary(record)

        self.assertIn("The verifier `command_verifier` did not pass.", summary)
        self.assertIn("Direct error: readme-check: command exited with code 1", summary)
        self.assertIn("Failed check: readme-check: failed", summary)
        self.assertIn("Command exited with code 1: python -m pytest tests/test_readme.py", summary)

    def test_markdown_and_html_reports_surface_failure_summary(self) -> None:
        record = self._failed_record()

        markdown = MarkdownReporter().render_run_record(record)
        html = HtmlReporter().render_run_record(record)

        self.assertIn("## Failure Summary", markdown)
        self.assertIn("readme-check: failed", markdown)
        self.assertIn("失败摘要", html)
        self.assertIn("readme-check: failed", html)
        self.assertIn("README title mismatch", html)

    @staticmethod
    def _failed_record() -> StoredRunRecord:
        started_at = datetime(2026, 3, 27, 3, 0, tzinfo=timezone.utc)
        summary = RunSummary(
            run_id="run-failed-001",
            task_id="task-001",
            status=RunStatus.FAILED,
            started_at=started_at,
            finished_at=started_at,
            verifier_outcome="failed",
            notes=("README title mismatch",),
        )
        verifier = VerifierResult(
            verifier_name="command_verifier",
            status=VerificationStatus.FAILED,
            evidence=(
                VerificationEvidence(
                    summary="readme-check: failed",
                    details={"exit_code": 1, "required": True},
                ),
            ),
            command_results=(
                CommandExecutionRecord(
                    command=("python", "-m", "pytest", "tests/test_readme.py"),
                    cwd=str(Path("E:/repo-harness-lab/runtime/tmp/run-failed-001")),
                    exit_code=1,
                    stdout_excerpt="",
                    stderr_excerpt="AssertionError: README title mismatch",
                    duration_ms=420,
                ),
            ),
            started_at=started_at,
            finished_at=started_at,
            errors=("readme-check: command exited with code 1",),
        )
        return StoredRunRecord(summary=summary, verifier_result=verifier)


if __name__ == "__main__":
    unittest.main()

