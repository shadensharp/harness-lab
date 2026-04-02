from __future__ import annotations

from typing import TYPE_CHECKING

from repo_harness_lab.domain.run_models import RunStatus
from repo_harness_lab.domain.verifier_models import VerificationEvidence, VerificationStatus
from repo_harness_lab.verifiers.draft_completion import build_draft_completion_feedback, is_draft_completion_result

if TYPE_CHECKING:
    from repo_harness_lab.storage.run_store import StoredRunRecord



def build_failure_summary(record: StoredRunRecord) -> tuple[str, ...]:
    summary = record.summary
    verifier = record.verifier_result
    lines: list[str] = []

    if verifier is None:
        if summary.status is RunStatus.SUCCEEDED:
            return ()
        lines.append("The run stopped before deterministic verification produced a result.")
        lines.extend(_note_lines(summary.notes))
        return _dedupe(lines)

    if verifier.status is VerificationStatus.PASSED and summary.status is RunStatus.SUCCEEDED:
        return ()

    if verifier.status is VerificationStatus.FAILED:
        lines.append(f"The verifier `{verifier.verifier_name}` did not pass.")
    elif verifier.status is VerificationStatus.ERROR:
        lines.append(f"The verifier `{verifier.verifier_name}` hit an internal error.")
    elif verifier.status is VerificationStatus.SKIPPED:
        lines.append(f"The verifier `{verifier.verifier_name}` was skipped, so there is no proof of success.")

    if is_draft_completion_result(verifier):
        lines.extend(build_draft_completion_feedback(verifier)[:3])

    if verifier.errors:
        lines.append(f"Direct error: {_normalize(verifier.errors[0])}")

    failed_evidence = _first_failed_evidence(verifier.evidence)
    if failed_evidence is not None:
        lines.append(f"Failed check: {_normalize(failed_evidence.summary)}")

    failed_command = next((item for item in verifier.command_results if item.exit_code != 0), None)
    if failed_command is not None:
        command_text = " ".join(failed_command.command)
        lines.append(f"Command exited with code {failed_command.exit_code}: {command_text}")
        excerpt = failed_command.stderr_excerpt.strip() or failed_command.stdout_excerpt.strip()
        if excerpt:
            lines.append(f"Command output: {_trim(excerpt)}")

    if not summary.changed_files and summary.status is RunStatus.FAILED:
        lines.append("The run did not leave any file changes.")

    lines.extend(_note_lines(summary.notes))
    return _dedupe(lines)



def _first_failed_evidence(evidence: tuple[VerificationEvidence, ...]) -> VerificationEvidence | None:
    for item in evidence:
        summary_text = item.summary.lower()
        if "failed" in summary_text or "missing" in summary_text or item.details.get("exit_code", 0) not in (0, None):
            return item
    return None



def _note_lines(notes: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    for note in notes:
        normalized = _normalize(note)
        if not normalized:
            continue
        lines.append(f"Run note: {normalized}")
    return lines



def _trim(value: str, *, limit: int = 220) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."



def _normalize(value: str) -> str:
    return " ".join(str(value).split())



def _dedupe(items: list[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        ordered.append(item)
        seen.add(item)
    return tuple(ordered)
