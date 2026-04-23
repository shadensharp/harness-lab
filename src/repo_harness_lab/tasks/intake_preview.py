from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from repo_harness_lab.agents.adapters.provider_json_edit import (
    _iter_workspace_files,
    _select_context_files,
    _snapshot_settings,
    _workspace_tree,
    build_prompt_preview_payload,
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
    current_delivery = _build_current_delivery_preview(task, repo_root=repo_root)
    recommendation = build_task_recommendation(
        TaskCatalogEntry(path=resolved_source_path or repo_root or Path(task.repo_source.path_or_url), task=task)
    )

    return {
        "source_path": str(resolved_source_path) if resolved_source_path is not None else None,
        "task_spec_preview": _build_task_spec_preview(task, repo_root=repo_root),
        "shared_task_information": _build_shared_task_information(task, current_delivery=current_delivery),
        "current_delivery": current_delivery,
        "uplift_readiness": {
            "recommendation_score": recommendation.score,
            "recommendation_reasons": list(recommendation.reasons),
            "declared_harness_signals": list(task.benchmark_metadata.harness_signals),
            "tags": list(task.benchmark_metadata.tags),
            "difficulty": task.benchmark_metadata.difficulty.value,
            "tier": task.benchmark_metadata.tier.value,
        },
        "risk_warnings": _build_risk_warnings(task, repo_root=repo_root, current_delivery=current_delivery),
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


def _build_current_delivery_preview(task: TaskSpec, *, repo_root: Path | None) -> dict[str, object]:
    settings = _snapshot_settings(HarnessProfile.CURRENT, {})
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
    prompt_preview = build_prompt_preview_payload(
        task,
        repo_root=repo_root,
        harness_profile=HarnessProfile.CURRENT,
    )
    additional_items = _build_delivery_items(
        tree_file_count=tree_file_count,
        tree_preview=tree_preview,
        context_files=context_files,
        included_inputs=included_inputs,
        included_verifier_steps=included_verifier_steps,
    )
    notes = _build_delivery_notes(
        context_files=context_files,
        included_inputs=included_inputs,
        included_verifier_steps=included_verifier_steps,
        repo_root=repo_root,
        repo_available=repo_root is not None and repo_root.exists(),
        max_context_files=settings.max_context_files,
    )
    return {
        "profile": HarnessProfile.CURRENT.value,
        "profile_label": "Current package",
        "includes_repo_tree": settings.include_tree,
        "tree_file_count": tree_file_count,
        "tree_preview": tree_preview,
        "context_file_count": len(context_files),
        "context_files": context_files,
        "max_context_files": settings.max_context_files,
        "max_file_chars": settings.max_file_chars,
        "included_input_names": included_inputs,
        "included_verifier_steps": included_verifier_steps,
        "additional_delivery_items": additional_items,
        "notes": notes,
        "prompt_preview": prompt_preview,
        "work_environment": {
            "repo_root": str(repo_root) if repo_root is not None else task.repo_source.path_or_url,
            "repo_source_kind": task.repo_source.kind.value,
            "checkout_mode": task.repo_source.checkout_mode.value,
            "allow_network": task.constraints.allow_network,
            "allowed_tools": list(task.constraints.allowed_tools),
            "max_runtime_seconds": task.constraints.max_runtime_seconds,
            "max_cost_usd": task.constraints.max_cost_usd,
        },
        "boundary": {
            "editable_paths": list(task.constraints.editable_paths),
            "forbidden_paths": list(task.constraints.forbidden_paths),
            "expected_changed_files": list(task.success_criteria.changed_files),
            "behavioral_checks": list(task.success_criteria.behavioral_checks),
            "required_verifier_steps": list(task.success_criteria.required_verifier_steps),
        },
    }


def _build_shared_task_information(task: TaskSpec, *, current_delivery: Mapping[str, object]) -> dict[str, object]:
    prompt_preview = _mapping(current_delivery.get("prompt_preview"))
    shared_prompt_items = [
        "The current run receives the same task title and description.",
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
        "shared_prompt_sections": list(prompt_preview.get("shared_prompt_sections", ())),
        "shared_prompt_items": shared_prompt_items,
        "response_contract": str(prompt_preview.get("response_contract") or ""),
        "system_prompt": str(prompt_preview.get("system_prompt") or ""),
        "environment": {
            "repo_source_kind": task.repo_source.kind.value,
            "checkout_mode": task.repo_source.checkout_mode.value,
            "allow_network": task.constraints.allow_network,
            "allowed_tools": list(task.constraints.allowed_tools),
            "max_runtime_seconds": task.constraints.max_runtime_seconds,
            "max_cost_usd": task.constraints.max_cost_usd,
        },
    }


def _build_delivery_items(
    *,
    tree_file_count: int | None,
    tree_preview: list[str],
    context_files: list[str],
    included_inputs: list[str],
    included_verifier_steps: list[str],
) -> list[str]:
    items: list[str] = []
    if tree_file_count is None:
        items.append("Repository tree preview is unavailable because the local repo could not be inspected.")
    else:
        preview_count = len(tree_preview)
        items.append(
            f"Repository tree attached ({tree_file_count} files discoverable, preview shows {preview_count} entries)."
        )

    if context_files:
        items.append(f"Repository context files: {', '.join(context_files)}")
    else:
        items.append("Repository context files: none selected in preview.")

    if included_inputs:
        items.append(f"Injected task inputs: {', '.join(included_inputs)}")
    if included_verifier_steps:
        items.append(f"Injected verifier steps: {', '.join(included_verifier_steps)}")
    return items


def _build_delivery_notes(
    *,
    context_files: list[str],
    included_inputs: list[str],
    included_verifier_steps: list[str],
    repo_root: Path | None,
    repo_available: bool,
    max_context_files: int,
) -> list[str]:
    notes: list[str] = []
    if repo_available:
        notes.append(f"Will attach up to {max_context_files} context files; current preview selects {len(context_files)}.")
    else:
        notes.append("Context-file preview is unavailable because the local repository path could not be inspected.")
    if included_inputs:
        notes.append(f"Will inject task inputs: {', '.join(included_inputs)}")
    else:
        notes.append("No task inputs are declared, so the current package relies on repository context only.")
    if included_verifier_steps:
        notes.append(f"Will inject verifier steps: {', '.join(included_verifier_steps)}")
    else:
        notes.append("No verifier steps are declared, so completion evidence will rely on changed files and behavior checks.")
    if repo_root is None:
        notes.append("Repository preview is structural only because the task does not point to a local_path repo.")
    return notes


def _build_risk_warnings(
    task: TaskSpec,
    *,
    repo_root: Path | None,
    current_delivery: Mapping[str, object],
) -> list[str]:
    warnings: list[str] = []
    context_paths = _context_paths(task)
    editable_surface = max(len(task.constraints.editable_paths), len(task.success_criteria.changed_files))
    repo_available = repo_root is not None and repo_root.exists()
    context_files = [str(item) for item in current_delivery.get("context_files", ()) if str(item)]

    if not repo_available:
        warnings.append("The repo source could not be inspected, so tree and context-file previews are unavailable.")
    if not context_paths:
        warnings.append(
            "No context_paths are declared, so repository context will be chosen mostly by changed files and editable paths."
        )
    if task.inputs.is_empty:
        warnings.append("No task inputs are declared, so the run will depend on repository context and verifier steps only.")
    if len(task.verifier_plan.steps) <= 1:
        warnings.append("Verifier plan is narrow, so completion evidence may stay weak.")
    if editable_surface <= 1:
        warnings.append("The task mostly changes a single file, so context selection may matter less.")
    if not task.benchmark_metadata.harness_signals:
        warnings.append("No harness signals are declared, so recommendation explanations will be weaker.")
    if not context_files and repo_available:
        warnings.append("No context files were selected for the current preview, so the run will lean on the repository tree and direct task constraints.")
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


def _join_or_placeholder(values: tuple[str, ...], placeholder: str) -> str:
    return ", ".join(values) if values else placeholder


def _quote_for_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _safe_file_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip("-")
    return sanitized or "task-intake-preview"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
