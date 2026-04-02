from __future__ import annotations

from repo_harness_lab.domain.run_models import RunStatus, RunSummary

_GENERIC_FAILURE_PATTERNS = (
    "command exited with code",
    "missing verifier command",
    "no verifier steps selected",
    ": failed",
)



def pick_failure_hint(summary: RunSummary) -> str | None:
    if summary.status is RunStatus.SUCCEEDED:
        return None

    normalized_notes = tuple(note.strip() for note in summary.notes if str(note).strip())
    for note in normalized_notes:
        if not _is_generic_failure_note(note):
            return note
    if normalized_notes:
        return normalized_notes[0]
    if summary.verifier_outcome and summary.verifier_outcome != "passed":
        return f"verifier={summary.verifier_outcome}"
    return summary.status.value



def _is_generic_failure_note(note: str) -> bool:
    lowered = note.lower()
    return any(pattern in lowered for pattern in _GENERIC_FAILURE_PATTERNS)
