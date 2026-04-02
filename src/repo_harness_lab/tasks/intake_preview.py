from __future__ import annotations

from pathlib import Path
from typing import Any

from repo_harness_lab.agents.adapters.provider_json_edit import (
    _iter_workspace_files,
    _select_context_files,
    _snapshot_settings,
    _workspace_tree,
)
from repo_harness_lab.domain.task_spec import HarnessProfile, RepoSourceKind, TaskSpec
from repo_harness_lab.tasks.catalog import TaskCatalogEntry, build_task_recommendation
from repo_harness_lab.tasks.intake import TaskIntake, build_task_spec_from_intake


def build_task_intake_preview(
    intake: TaskIntake,
    *,
    source_path: str | Path | None = None,
    repo_root_override: str | Path | None = None,
) -> dict[str, object]:
    task = build_task_spec_from_intake(intake)
    return build_task_spec_delivery_preview(task, source_path=source_path, repo_root_override=repo_root_override)


def build_task_spec_delivery_preview(
    task: TaskSpec,
    *,
    source_path: str | Path | None = None,
    repo_root_override: str | Path | None = None,
) -> dict[str, object]:
    resolved_source_path = Path(source_path).resolve() if source_path is not None else None
    resolved_repo_override = Path(repo_root_override).resolve() if repo_root_override is not None else None
    repo_root = _resolve_repo_root(task, repo_root_override=resolved_repo_override)
    profile_matrix = {
        profile.value: _build_profile_preview(task, repo_root=repo_root, harness_profile=profile)
        for profile in (HarnessProfile.BARE, HarnessProfile.BASIC, HarnessProfile.FULL)
    }
    recommendation = build_task_recommendation(
        TaskCatalogEntry(path=resolved_source_path or repo_root or Path(task.repo_source.path_or_url), task=task)
    )

    return {
        "source_path": str(resolved_source_path) if resolved_source_path is not None else None,
        "task_spec_preview": _build_task_spec_preview(task, repo_root=repo_root),
        "shared_task_information": _build_shared_task_information(task),
        "harness_delivery_matrix": profile_matrix,
        "profile_delta_summary": _build_profile_delta_summary(profile_matrix),
        "uplift_readiness": {
            "recommendation_score": recommendation.score,
            "recommendation_reasons": list(recommendation.reasons),
            "declared_harness_signals": list(task.benchmark_metadata.harness_signals),
            "tags": list(task.benchmark_metadata.tags),
            "difficulty": task.benchmark_metadata.difficulty.value,
            "tier": task.benchmark_metadata.tier.value,
        },
        "risk_warnings": _build_risk_warnings(task, repo_root=repo_root, profile_matrix=profile_matrix),
        "suggested_commands": _build_suggested_commands(
            task_id=task.task_id,
            source_path=resolved_source_path,
        ),
    }


def _build_task_spec_preview(task: TaskSpec, *, repo_root: Path | None) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type.value,
        "repo_source_kind": task.repo_source.kind.value,
        "repo_root": str(repo_root) if repo_root is not None else task.repo_source.path_or_url,
        "editable_paths": list(task.constraints.editable_paths),
        "forbidden_paths": list(task.constraints.forbidden_paths),
        "expected_changed_files": list(task.success_criteria.changed_files),
        "behavioral_checks": list(task.success_criteria.behavioral_checks),
        "input_names": [item.name for item in task.inputs.items],
        "verifier_step_names": [step.name for step in task.verifier_plan.steps],
        "context_paths": list(_context_paths(task)),
        "benchmark_tier": task.benchmark_metadata.tier.value,
        "difficulty": task.benchmark_metadata.difficulty.value,
        "tags": list(task.benchmark_metadata.tags),
        "harness_signals": list(task.benchmark_metadata.harness_signals),
    }


def _build_profile_preview(
    task: TaskSpec,
    *,
    repo_root: Path | None,
    harness_profile: HarnessProfile,
) -> dict[str, object]:
    settings = _snapshot_settings(harness_profile, {})
    tree_preview: list[str] = []
    tree_file_count: int | None = 0 if settings.include_tree else None
    context_files: list[str] = []

    if repo_root is not None and repo_root.exists():
        if settings.include_tree:
            tree_file_count = sum(1 for _ in _iter_workspace_files(repo_root))
            tree_preview = list(_workspace_tree(repo_root, max_entries=min(settings.max_tree_entries, 12)))
        if settings.max_context_files > 0:
            context_files = [
                path.relative_to(repo_root).as_posix()
                for path in _select_context_files(task, repo_root, max_files=settings.max_context_files)
            ]
    elif settings.include_tree:
        tree_file_count = None

    included_inputs = [item.name for item in task.inputs.items] if settings.include_inputs else []
    included_verifier_steps = [step.name for step in task.verifier_plan.steps] if settings.include_verifier_plan else []

    return {
        "includes_repo_tree": settings.include_tree,
        "tree_file_count": tree_file_count,
        "tree_preview": tree_preview,
        "context_file_count": len(context_files),
        "context_files": context_files,
        "max_context_files": settings.max_context_files,
        "max_file_chars": settings.max_file_chars,
        "included_input_names": included_inputs,
        "included_verifier_steps": included_verifier_steps,
        "additional_delivery_items": _build_additional_delivery_items(
            harness_profile=harness_profile,
            tree_file_count=tree_file_count,
            tree_preview=tree_preview,
            context_files=context_files,
            included_inputs=included_inputs,
            included_verifier_steps=included_verifier_steps,
        ),
        "notes": _profile_notes(
            harness_profile=harness_profile,
            context_files=context_files,
            included_inputs=included_inputs,
            included_verifier_steps=included_verifier_steps,
            repo_root=repo_root,
            repo_available=repo_root is not None and repo_root.exists(),
            max_context_files=settings.max_context_files,
        ),
    }


def _build_shared_task_information(task: TaskSpec) -> dict[str, object]:
    shared_prompt_items = [
        "The same user task title and description go to bare/basic/full.",
        f"Same editable paths: {_join_or_placeholder(task.constraints.editable_paths, '<any>')}",
        f"Same forbidden paths: {_join_or_placeholder(task.constraints.forbidden_paths, '<none>')}",
        f"Same expected changed files: {_join_or_placeholder(task.success_criteria.changed_files, '<none>')}",
        f"Same behavioral checks: {_join_or_placeholder(task.success_criteria.behavioral_checks, '<none>')}",
        "Same response contract: JSON only with summary and writes.",
    ]
    if task.success_criteria.required_verifier_steps:
        shared_prompt_items.append(
            "Same required verifier step names: "
            f"{_join_or_placeholder(task.success_criteria.required_verifier_steps, '<none>')}"
        )
    return {
        "title": task.title,
        "description": task.description,
        "editable_paths": list(task.constraints.editable_paths),
        "forbidden_paths": list(task.constraints.forbidden_paths),
        "expected_changed_files": list(task.success_criteria.changed_files),
        "behavioral_checks": list(task.success_criteria.behavioral_checks),
        "required_verifier_steps": list(task.success_criteria.required_verifier_steps),
        "shared_prompt_sections": [
            "task_brief",
            "constraints",
            "success_criteria",
            "response_contract",
        ],
        "shared_prompt_items": shared_prompt_items,
        "response_contract": '{"summary": "short explanation", "writes": [{"path": "relative/path", "content": "full file content"}]}',
    }


def _build_additional_delivery_items(
    *,
    harness_profile: HarnessProfile,
    tree_file_count: int | None,
    tree_preview: list[str],
    context_files: list[str],
    included_inputs: list[str],
    included_verifier_steps: list[str],
) -> list[str]:
    items: list[str] = []
    if tree_file_count is None:
        items.append("Repository tree is enabled for this profile, but the local repo preview is unavailable.")
    elif harness_profile is HarnessProfile.BARE:
        items.append(f"Extra harness material: repository tree only ({tree_file_count} files discoverable).")
    else:
        preview_count = len(tree_preview)
        items.append(
            f"Repository tree attached ({tree_file_count} files discoverable, preview shows {preview_count} entries)."
        )

    if context_files:
        items.append(f"Repository context files: {', '.join(context_files)}")
    elif harness_profile is not HarnessProfile.BARE:
        items.append("Repository context files: none selected in preview.")

    if included_inputs:
        items.append(f"Injected task inputs: {', '.join(included_inputs)}")
    if included_verifier_steps:
        items.append(f"Injected verifier steps: {', '.join(included_verifier_steps)}")
    return items


def _profile_notes(
    *,
    harness_profile: HarnessProfile,
    context_files: list[str],
    included_inputs: list[str],
    included_verifier_steps: list[str],
    repo_root: Path | None,
    repo_available: bool,
    max_context_files: int,
) -> list[str]:
    notes: list[str] = []
    if harness_profile is HarnessProfile.BARE:
        notes.append("Only the repository tree is attached; task inputs and verifier steps stay hidden.")
    if max_context_files > 0:
        if repo_available:
            notes.append(f"Will attach up to {max_context_files} context files; current preview selects {len(context_files)}.")
        else:
            notes.append("Context-file preview is unavailable because the local repository path could not be inspected.")
    if included_inputs:
        notes.append(f"Will inject task inputs: {', '.join(included_inputs)}")
    elif harness_profile is HarnessProfile.FULL:
        notes.append("This profile can inject task inputs, but the task does not currently declare any.")
    if included_verifier_steps:
        notes.append(f"Will inject verifier steps: {', '.join(included_verifier_steps)}")
    elif harness_profile is HarnessProfile.FULL:
        notes.append("This profile can inject verifier steps, but the task does not currently declare any.")
    if repo_root is None:
        notes.append("Repository preview is structural only because the task does not point to a local_path repo.")
    return notes


def _build_profile_delta_summary(
    profile_matrix: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    transitions = (
        (HarnessProfile.BARE.value, HarnessProfile.BASIC.value),
        (HarnessProfile.BASIC.value, HarnessProfile.FULL.value),
    )
    items: list[dict[str, object]] = []
    for from_profile, to_profile in transitions:
        left = profile_matrix[from_profile]
        right = profile_matrix[to_profile]
        left_context = int(left.get("context_file_count", 0))
        right_context = int(right.get("context_file_count", 0))
        left_cap = int(left.get("max_context_files", 0))
        right_cap = int(right.get("max_context_files", 0))
        left_inputs = [str(item) for item in left.get("included_input_names", ()) if str(item)]
        right_inputs = [str(item) for item in right.get("included_input_names", ()) if str(item)]
        left_steps = [str(item) for item in left.get("included_verifier_steps", ()) if str(item)]
        right_steps = [str(item) for item in right.get("included_verifier_steps", ()) if str(item)]
        new_inputs = [item for item in right_inputs if item not in left_inputs]
        new_steps = [item for item in right_steps if item not in left_steps]
        summary_lines = [
            f"context files: {left_context} -> {right_context} ({_format_signed_int(right_context - left_context)})",
        ]
        if left_cap != right_cap:
            summary_lines.append(f"context cap: {left_cap} -> {right_cap} ({_format_signed_int(right_cap - left_cap)})")
        if new_inputs:
            summary_lines.append(f"new task inputs: {', '.join(new_inputs)}")
        if new_steps:
            summary_lines.append(f"new verifier steps: {', '.join(new_steps)}")
        if not new_inputs and not new_steps and left_cap == right_cap and left_context == right_context:
            summary_lines.append("No material delivery difference detected between these profiles.")
        items.append(
            {
                "from_profile": from_profile,
                "to_profile": to_profile,
                "context_file_count_delta": right_context - left_context,
                "context_cap_delta": right_cap - left_cap,
                "new_input_names": new_inputs,
                "new_verifier_steps": new_steps,
                "summary_lines": summary_lines,
            }
        )
    return items


def _build_risk_warnings(
    task: TaskSpec,
    *,
    repo_root: Path | None,
    profile_matrix: dict[str, dict[str, object]],
) -> list[str]:
    warnings: list[str] = []
    context_paths = _context_paths(task)
    editable_surface = max(len(task.constraints.editable_paths), len(task.success_criteria.changed_files))
    repo_available = repo_root is not None and repo_root.exists()
    basic_context = list(profile_matrix[HarnessProfile.BASIC.value]["context_files"])
    full_context = list(profile_matrix[HarnessProfile.FULL.value]["context_files"])

    if not repo_available:
        warnings.append("The repo source could not be inspected, so tree and context-file previews are unavailable.")

    if not context_paths:
        warnings.append("No context_paths are declared, so basic/full will choose repo files mostly by changed files and editable paths.")
    if task.inputs.is_empty:
        warnings.append("No task inputs are declared, so full will not demonstrate input-injection uplift.")
    if len(task.verifier_plan.steps) <= 1:
        warnings.append("Verifier plan is narrow, so the extra value of verifier-aware delivery may be harder to see.")
    if editable_surface <= 1:
        warnings.append("The task mostly changes a single file, so harness differences may be less visually obvious.")
    if not task.benchmark_metadata.harness_signals:
        warnings.append("No harness signals are declared, so recommendation explanations will be weaker.")
    if basic_context == full_context and task.inputs.is_empty and not task.verifier_plan.steps:
        warnings.append("Basic and full currently deliver almost the same evidence, so uplift between them may stay small.")

    return warnings


def _build_suggested_commands(
    *,
    task_id: str,
    source_path: Path | None,
) -> dict[str, str]:
    if source_path is None:
        return {}

    quoted_source = _quote_for_powershell(str(source_path))
    task_path = f"runtime/tmp/{_safe_file_stem(task_id)}.task.json"
    return {
        "preview_intake": f"python -m repo_harness_lab.cli.main preview-intake {quoted_source} --format both",
        "scaffold_task_spec": f"python -m repo_harness_lab.cli.main scaffold-task-spec {quoted_source} --write {task_path}",
        "run_intake_eval": f"python -m repo_harness_lab.cli.main run-intake-eval {quoted_source} --provider <provider> --model <model> --api-key-env <API_KEY_ENV>",
    }


def _resolve_repo_root(task: TaskSpec, *, repo_root_override: Path | None = None) -> Path | None:
    if repo_root_override is not None:
        return repo_root_override.resolve()
    if task.repo_source.kind is not RepoSourceKind.LOCAL_PATH:
        return None
    return Path(task.repo_source.path_or_url).resolve()


def _context_paths(task: TaskSpec) -> tuple[str, ...]:
    raw = task.metadata.get("context_paths") if isinstance(task.metadata, dict) else ()
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(item) for item in raw)


def _format_signed_int(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def _join_or_placeholder(values: tuple[str, ...], placeholder: str) -> str:
    return ", ".join(values) if values else placeholder


def _quote_for_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _safe_file_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip("-")
    return sanitized or "task-intake-preview"
