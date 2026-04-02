from __future__ import annotations

from collections import Counter
import json
from typing import TYPE_CHECKING

from repo_harness_lab.domain.eval_models import EvalReport
from repo_harness_lab.domain.run_models import RunSummary
from repo_harness_lab.reporting.failure_summary import build_failure_summary
from repo_harness_lab.shared.failure_hints import pick_failure_hint

if TYPE_CHECKING:
    from repo_harness_lab.storage.run_store import StoredRunRecord


class MarkdownReporter:
    def render_run(self, summary: RunSummary) -> str:
        lines = [
            f"# Run {summary.run_id}",
            "",
            "## Summary",
            f"- task_id: {summary.task_id}",
            f"- status: {summary.status.value}",
            f"- duration_ms: {summary.duration_ms}",
            f"- verifier_outcome: {summary.verifier_outcome}",
        ]
        if summary.changed_files:
            lines.extend(["", "## Changed Files"])
            lines.extend(f"- {path}" for path in summary.changed_files)
        if summary.notes:
            lines.extend(["", "## Notes"])
            lines.extend(f"- {note}" for note in summary.notes)
        if summary.artifact_index:
            lines.extend(["", "## Artifacts"])
            lines.extend(f"- {artifact.name}: {artifact.path}" for artifact in summary.artifact_index)
        return "\n".join(lines)

    def render_run_record(self, record: StoredRunRecord) -> str:
        lines = [self.render_run(record.summary)]
        failure_summary = build_failure_summary(record)

        if failure_summary:
            lines.extend(["", "## Failure Summary"])
            lines.extend(f"- {item}" for item in failure_summary)

        if record.verifier_result is not None:
            lines.extend(
                [
                    "",
                    "## Verifier",
                    f"- verifier_name: {record.verifier_result.verifier_name}",
                    f"- status: {record.verifier_result.status.value}",
                ]
            )
            if record.verifier_result.errors:
                lines.extend(f"- error: {error}" for error in record.verifier_result.errors)
            if record.verifier_result.evidence:
                lines.extend(["", "## Verification Evidence"])
                lines.extend(f"- {item.summary}" for item in record.verifier_result.evidence)

        if record.patch_diff:
            lines.extend(["", "## Patch Preview", "```diff"])
            lines.extend(_patch_preview_lines(record.patch_diff))
            lines.append("```")

        if record.events:
            counts = Counter(event.event_type.value for event in record.events)
            lines.extend(["", "## Events", f"- total_events: {len(record.events)}"])
            lines.extend(f"- {name}: {count}" for name, count in sorted(counts.items()))
            lines.extend(["", "## Recent Events"])
            lines.extend(
                f"- {event.timestamp.isoformat()} {event.stage.value} {event.event_type.value}"
                for event in record.events[-5:]
            )

        return "\n".join(lines)

    def render_eval(self, report: EvalReport) -> str:
        lines = [
            f"# Eval {report.suite_id}",
            "",
        ]
        if report.aggregate_metrics:
            lines.extend(["## Metrics"])
            lines.extend(f"- {metric.name}: {metric.value}" for metric in report.aggregate_metrics)

        if report.case_results:
            lines.extend(["", "## Cases"])
            for case_result in report.case_results:
                lines.extend(
                    [
                        f"### {case_result.case_id}",
                        f"- summary: {json.dumps(case_result.summary, ensure_ascii=False, sort_keys=True)}",
                    ]
                )
                for trial in case_result.trials:
                    summary = trial.run_summary
                    if summary is None:
                        lines.append(f"- {trial.trial_id}: no summary")
                        continue
                    label = trial.notes[0] if trial.notes else "<unlabeled>"
                    failure_hint = pick_failure_hint(summary)
                    failure_suffix = f", failure_hint={failure_hint}" if failure_hint else ""
                    lines.append(
                        f"- {trial.trial_id}: label={label}, run_id={summary.run_id}, status={summary.status.value}, verifier={summary.verifier_outcome}{failure_suffix}"
                    )

        if report.comparison_views:
            lines.extend(["", "## Comparisons"])
            for view in report.comparison_views:
                lines.append(f"### {view.name}")
                for key, value in sorted(view.items.items()):
                    lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
        return "\n".join(lines)



def _patch_preview_lines(patch_diff: str, max_lines: int = 80) -> list[str]:
    lines = patch_diff.splitlines()
    if len(lines) <= max_lines:
        return lines or ["# empty patch"]
    preview = lines[:max_lines]
    preview.append(f"# ... truncated {len(lines) - max_lines} additional lines")
    return preview
