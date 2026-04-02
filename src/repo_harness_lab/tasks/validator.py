from __future__ import annotations

from repo_harness_lab.domain.task_spec import TaskSpec


class TaskValidationError(ValueError):
    pass



def validate_task_spec(task: TaskSpec) -> None:
    errors: list[str] = []

    if not task.task_id.strip():
        errors.append("task_id must not be empty")
    if not task.title.strip():
        errors.append("title must not be empty")
    if not task.description.strip():
        errors.append("description must not be empty")
    if not task.repo_source.path_or_url.strip():
        errors.append("repo_source.path_or_url must not be empty")

    overlap = set(task.constraints.editable_paths) & set(task.constraints.forbidden_paths)
    if overlap:
        errors.append(f"editable_paths and forbidden_paths overlap: {sorted(overlap)}")

    step_names = [step.name for step in task.verifier_plan.steps]
    if len(step_names) != len(set(step_names)):
        errors.append("verifier step names must be unique")

    for step in task.verifier_plan.steps:
        if not step.name.strip():
            errors.append("verifier step name must not be empty")
        if not step.command:
            errors.append(f"verifier step '{step.name}' must define a command")

    required_steps = set(task.success_criteria.required_verifier_steps)
    missing_steps = sorted(required_steps - set(step_names))
    if missing_steps:
        errors.append(f"success_criteria references unknown verifier steps: {missing_steps}")

    for step in task.setup_steps:
        if not step.strip():
            errors.append("setup_steps must not contain empty commands")

    _validate_non_empty_unique(task.benchmark_metadata.tags, field_name="benchmark_metadata.tags", errors=errors)
    _validate_non_empty_unique(
        task.benchmark_metadata.harness_signals,
        field_name="benchmark_metadata.harness_signals",
        errors=errors,
    )

    if errors:
        raise TaskValidationError("; ".join(errors))



def _validate_non_empty_unique(values: tuple[str, ...], *, field_name: str, errors: list[str]) -> None:
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if not item:
            errors.append(f"{field_name} must not contain empty values")
            continue
        normalized.append(item)
    if len(normalized) != len(set(normalized)):
        errors.append(f"{field_name} must not contain duplicates")
