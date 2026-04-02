from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repo_harness_lab.domain.run_models import RunRequest, WorkspaceSession
from repo_harness_lab.domain.task_spec import TaskSpec
from repo_harness_lab.domain.verifier_models import VerificationEvidence, VerificationStatus, VerifierResult
from repo_harness_lab.runtime.repo_sources import resolve_workspace_source_repo_root
from repo_harness_lab.shared.clock import utc_now
from repo_harness_lab.shared.files import build_patch, collect_changed_files
from repo_harness_lab.verifiers.base import BaseVerifier

DRAFT_COMPLETION_STEP_NAME = "draft-completion-check"
DRAFT_COMPLETION_VERIFIER_NAME = "draft_completion_verifier"
DRAFT_COMPLETION_THRESHOLD = 0.67

_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+")
_QUOTED_PATTERN = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{2,80})[\"'“”‘’]")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9@._/-]{4,}")
_STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "along",
    "also",
    "change",
    "changes",
    "ensure",
    "explain",
    "explaining",
    "please",
    "repository",
    "should",
    "that",
    "this",
    "title",
    "update",
    "used",
    "with",
}


@dataclass(frozen=True, slots=True)
class DraftCompletionAssessment:
    score: float
    threshold: float
    passed: bool
    changed_files: tuple[str, ...]
    expected_changed_files: tuple[str, ...]
    matched_expected_changed_files: tuple[str, ...]
    missing_expected_changed_files: tuple[str, ...]
    task_anchors: tuple[str, ...]
    matched_task_anchors: tuple[str, ...]
    missing_task_anchors: tuple[str, ...]
    scope_violations: tuple[str, ...]
    signal_scores: Mapping[str, float]
    signal_weights: Mapping[str, float]
    weak_signals: tuple[str, ...]


class DraftCompletionVerifier(BaseVerifier):
    def __init__(
        self,
        *,
        pass_threshold: float = DRAFT_COMPLETION_THRESHOLD,
        verifier_name: str = DRAFT_COMPLETION_VERIFIER_NAME,
    ) -> None:
        self.pass_threshold = pass_threshold
        self.verifier_name = verifier_name

    def verify(self, task: TaskSpec, request: RunRequest, workspace: WorkspaceSession) -> VerifierResult:
        started_at = utc_now()
        source_repo = resolve_workspace_source_repo_root(task, workspace)
        workspace_repo = workspace.repo_root.resolve()

        if not source_repo.exists():
            return VerifierResult(
                verifier_name=self.verifier_name,
                status=VerificationStatus.ERROR,
                started_at=started_at,
                finished_at=utc_now(),
                errors=(f"source repo does not exist: {source_repo}",),
            )

        assessment = _assess_draft_completion(
            task=task,
            source_repo=source_repo,
            workspace_repo=workspace_repo,
            threshold=self.pass_threshold,
        )
        status = VerificationStatus.PASSED if assessment.passed else VerificationStatus.FAILED
        return VerifierResult(
            verifier_name=self.verifier_name,
            status=status,
            evidence=_build_evidence(assessment),
            started_at=started_at,
            finished_at=utc_now(),
            errors=_build_errors(assessment),
        )


def is_draft_completion_task(task: TaskSpec) -> bool:
    metadata = task.metadata if isinstance(task.metadata, Mapping) else {}
    if bool(metadata.get("portal_used_draft_verifier")):
        return True
    return any(step.name == DRAFT_COMPLETION_STEP_NAME for step in task.verifier_plan.steps)


def is_draft_completion_result(verifier_result: VerifierResult | None) -> bool:
    return verifier_result is not None and verifier_result.verifier_name == DRAFT_COMPLETION_VERIFIER_NAME


def build_draft_completion_feedback(verifier_result: VerifierResult | None) -> tuple[str, ...]:
    if not is_draft_completion_result(verifier_result):
        return ()
    payload = _overview_payload(verifier_result)
    if not payload:
        return ()

    score = _float(payload.get("score"))
    threshold = _float(payload.get("threshold"))
    changed_files = _string_tuple(payload.get("changed_files"))
    expected_files = _string_tuple(payload.get("expected_changed_files"))
    matched_expected = _string_tuple(payload.get("matched_expected_changed_files"))
    missing_expected = _string_tuple(payload.get("missing_expected_changed_files"))
    task_anchors = _string_tuple(payload.get("task_anchors"))
    matched_anchors = _string_tuple(payload.get("matched_task_anchors"))
    missing_anchors = _string_tuple(payload.get("missing_task_anchors"))
    scope_violations = _string_tuple(payload.get("scope_violations"))
    weak_signals = _string_tuple(payload.get("weak_signals"))

    lines: list[str] = []
    if score is not None and threshold is not None:
        lines.append(f"draft completion score: {score:.2f} / 1.00 (threshold {threshold:.2f})")
    if expected_files:
        matched_label = ", ".join(matched_expected) if matched_expected else "<none>"
        lines.append(
            f"expected files matched: {len(matched_expected)}/{len(expected_files)} ({matched_label})"
        )
    elif changed_files:
        lines.append(f"changed files detected: {', '.join(changed_files[:4])}")
    if task_anchors:
        matched_label = ", ".join(matched_anchors) if matched_anchors else "<none>"
        lines.append(f"task anchors matched: {len(matched_anchors)}/{len(task_anchors)} ({matched_label})")
    if missing_expected:
        lines.append(f"missing expected changed files: {', '.join(missing_expected)}")
    if missing_anchors:
        lines.append(f"task anchors not reflected in changed content: {', '.join(missing_anchors)}")
    if scope_violations:
        lines.append(f"changed files escaped drafted scope: {', '.join(scope_violations)}")
    if weak_signals:
        lines.append(f"draft completion confidence is weak: {'; '.join(weak_signals)}")
    return tuple(lines)


def _assess_draft_completion(
    *,
    task: TaskSpec,
    source_repo: Path,
    workspace_repo: Path,
    threshold: float,
) -> DraftCompletionAssessment:
    changed_files = tuple(_normalize_path(item) for item in collect_changed_files(source_repo, workspace_repo))
    expected_changed_files = tuple(_normalize_path(item) for item in task.success_criteria.changed_files if _normalize_path(item))
    matched_expected_changed_files = tuple(item for item in expected_changed_files if item in changed_files)
    missing_expected_changed_files = tuple(item for item in expected_changed_files if item not in changed_files)

    editable_paths = tuple(_normalize_path(item) for item in task.constraints.editable_paths if _normalize_path(item))
    forbidden_paths = tuple(_normalize_path(item) for item in task.constraints.forbidden_paths if _normalize_path(item))
    scope_violations = _scope_violations(
        changed_files=changed_files,
        editable_paths=editable_paths,
        forbidden_paths=forbidden_paths,
    )

    patch_diff = build_patch(source_repo, workspace_repo)
    changed_corpus = _changed_corpus(workspace_repo, changed_files, patch_diff=patch_diff)
    task_anchors = _task_anchors(task)
    matched_task_anchors = tuple(anchor for anchor in task_anchors if _anchor_in_corpus(anchor, changed_corpus))
    missing_task_anchors = tuple(anchor for anchor in task_anchors if anchor not in matched_task_anchors)

    signal_weights = _active_signal_weights(
        has_expected_files=bool(expected_changed_files),
        has_task_anchors=bool(task_anchors),
        has_scope_rules=bool(editable_paths or forbidden_paths),
    )
    signal_scores = {
        "file_change_presence": 1.0 if changed_files else 0.0,
        "expected_file_coverage": (
            len(matched_expected_changed_files) / len(expected_changed_files)
            if expected_changed_files
            else 0.0
        ),
        "task_anchor_coverage": (
            len(matched_task_anchors) / len(task_anchors)
            if task_anchors
            else 0.0
        ),
        "scope_adherence": 1.0 if changed_files and not scope_violations else 0.0,
    }
    weighted_total = 0.0
    total_weight = 0.0
    for name, weight in signal_weights.items():
        total_weight += weight
        weighted_total += signal_scores.get(name, 0.0) * weight
    score = weighted_total / total_weight if total_weight else 0.0

    weak_signals: list[str] = []
    if not expected_changed_files:
        weak_signals.append("no expected_changed_files were drafted from the task text")
    if not task_anchors:
        weak_signals.append("task text did not yield stable completion anchors")
    if not changed_files:
        weak_signals.append("workspace produced no file changes")

    passed = bool(changed_files) and not scope_violations and score >= threshold
    return DraftCompletionAssessment(
        score=score,
        threshold=threshold,
        passed=passed,
        changed_files=changed_files,
        expected_changed_files=expected_changed_files,
        matched_expected_changed_files=matched_expected_changed_files,
        missing_expected_changed_files=missing_expected_changed_files,
        task_anchors=task_anchors,
        matched_task_anchors=matched_task_anchors,
        missing_task_anchors=missing_task_anchors,
        scope_violations=scope_violations,
        signal_scores={key: round(value, 4) for key, value in signal_scores.items() if key in signal_weights},
        signal_weights={key: round(value, 4) for key, value in signal_weights.items()},
        weak_signals=tuple(weak_signals),
    )


def _build_evidence(assessment: DraftCompletionAssessment) -> tuple[VerificationEvidence, ...]:
    overview_details = {
        "score": round(assessment.score, 4),
        "threshold": round(assessment.threshold, 4),
        "changed_files": list(assessment.changed_files),
        "expected_changed_files": list(assessment.expected_changed_files),
        "matched_expected_changed_files": list(assessment.matched_expected_changed_files),
        "missing_expected_changed_files": list(assessment.missing_expected_changed_files),
        "task_anchors": list(assessment.task_anchors),
        "matched_task_anchors": list(assessment.matched_task_anchors),
        "missing_task_anchors": list(assessment.missing_task_anchors),
        "scope_violations": list(assessment.scope_violations),
        "signal_scores": dict(assessment.signal_scores),
        "signal_weights": dict(assessment.signal_weights),
        "weak_signals": list(assessment.weak_signals),
    }
    overview = VerificationEvidence(
        summary=f"draft completion heuristic: {'passed' if assessment.passed else 'failed'}",
        details=overview_details,
    )
    expected_summary = (
        f"expected files: matched {len(assessment.matched_expected_changed_files)}/{len(assessment.expected_changed_files)}"
        if assessment.expected_changed_files
        else "expected files: none drafted"
    )
    anchors_summary = (
        f"task anchors: matched {len(assessment.matched_task_anchors)}/{len(assessment.task_anchors)}"
        if assessment.task_anchors
        else "task anchors: none drafted"
    )
    scope_summary = (
        "scope check: passed"
        if not assessment.scope_violations
        else f"scope check: failed ({len(assessment.scope_violations)} violations)"
    )
    return (
        overview,
        VerificationEvidence(
            summary=expected_summary,
            details={
                "matched": list(assessment.matched_expected_changed_files),
                "missing": list(assessment.missing_expected_changed_files),
            },
        ),
        VerificationEvidence(
            summary=anchors_summary,
            details={
                "matched": list(assessment.matched_task_anchors),
                "missing": list(assessment.missing_task_anchors),
            },
        ),
        VerificationEvidence(
            summary=scope_summary,
            details={
                "changed_files": list(assessment.changed_files),
                "violations": list(assessment.scope_violations),
            },
        ),
    )


def _build_errors(assessment: DraftCompletionAssessment) -> tuple[str, ...]:
    errors: list[str] = []
    if not assessment.changed_files:
        errors.append("no file changes detected in workspace")
    if assessment.score < assessment.threshold:
        errors.append(
            f"completion score {assessment.score:.2f} is below threshold {assessment.threshold:.2f}"
        )
    if assessment.missing_expected_changed_files:
        errors.append("missing expected changed files: " + ", ".join(assessment.missing_expected_changed_files))
    if assessment.missing_task_anchors:
        errors.append("task anchors not reflected in changed content: " + ", ".join(assessment.missing_task_anchors))
    if assessment.scope_violations:
        errors.append("changed files escaped drafted scope: " + ", ".join(assessment.scope_violations))
    return tuple(errors)


def _scope_violations(
    *,
    changed_files: Sequence[str],
    editable_paths: Sequence[str],
    forbidden_paths: Sequence[str],
) -> tuple[str, ...]:
    violations: list[str] = []
    for path in changed_files:
        if editable_paths and not any(_path_matches_prefix(path, prefix) for prefix in editable_paths):
            violations.append(path)
            continue
        if any(_path_matches_prefix(path, prefix) for prefix in forbidden_paths):
            violations.append(path)
    return tuple(violations)


def _task_anchors(task: TaskSpec) -> tuple[str, ...]:
    seen: set[str] = set()
    anchors: list[str] = []
    expected_paths = {_normalize_path(item) for item in task.success_criteria.changed_files if _normalize_path(item)}

    def add(value: str) -> None:
        normalized = _normalize_anchor(value)
        if not normalized or normalized in seen or normalized in expected_paths:
            return
        seen.add(normalized)
        anchors.append(normalized)

    source_text = "\n".join((task.description, *task.success_criteria.behavioral_checks))
    for match in _PATH_PATTERN.findall(source_text):
        add(match)
        basename = PurePosixPath(_normalize_path(match)).name
        if basename:
            add(basename)
    for quoted in _QUOTED_PATTERN.findall(source_text):
        add(quoted)
    for token in _TOKEN_PATTERN.findall(source_text):
        lowered = token.lower()
        if lowered in _STOPWORDS:
            continue
        if not _looks_like_anchor(token):
            continue
        add(token)

    if len(anchors) > 10:
        anchors = anchors[:10]
    return tuple(anchors)


def _active_signal_weights(
    *,
    has_expected_files: bool,
    has_task_anchors: bool,
    has_scope_rules: bool,
) -> dict[str, float]:
    weights = {"file_change_presence": 0.15}
    if has_expected_files:
        weights["expected_file_coverage"] = 0.35
    if has_task_anchors:
        weights["task_anchor_coverage"] = 0.40
    if has_scope_rules:
        weights["scope_adherence"] = 0.10
    return weights


def _changed_corpus(workspace_repo: Path, changed_files: Sequence[str], *, patch_diff: str) -> str:
    chunks: list[str] = [patch_diff]
    for relative in changed_files[:8]:
        path = workspace_repo / Path(relative)
        chunks.append(relative)
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf8")
        except UnicodeDecodeError:
            continue
        chunks.append(text[:4000])
    return "\n".join(chunks).lower()


def _anchor_in_corpus(anchor: str, corpus: str) -> bool:
    normalized = anchor.lower()
    if not normalized:
        return False
    if normalized in corpus:
        return True
    return normalized.replace("\\", "/") in corpus


def _normalize_anchor(value: str) -> str:
    text = " ".join(str(value).split()).strip().strip(",.;:!?")
    if not text:
        return ""
    if "/" in text or "\\" in text:
        return _normalize_path(text)
    return text


def _looks_like_anchor(token: str) -> bool:
    lowered = token.lower()
    if "/" in token or "\\" in token or "@" in token:
        return True
    if any(char.isdigit() for char in token):
        return True
    if "." in token or "_" in token or "-" in token:
        return True
    return len(lowered) >= 6 and lowered not in _STOPWORDS


def _path_matches_prefix(path: str, prefix: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_prefix = _normalize_path(prefix)
    if not normalized_prefix:
        return False
    return normalized_path == normalized_prefix or normalized_path.startswith(normalized_prefix + "/")


def _normalize_path(value: str) -> str:
    return PurePosixPath(str(value).replace("\\", "/")).as_posix().lstrip("./")


def _overview_payload(verifier_result: VerifierResult) -> Mapping[str, object]:
    if not verifier_result.evidence:
        return {}
    details = verifier_result.evidence[0].details
    if isinstance(details, Mapping):
        return details
    return {}


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
