from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from repo_harness_lab.domain.task_spec import (
    FailurePolicy,
    RepoCheckoutMode,
    RepoSource,
    RepoSourceKind,
    SuccessCriteria,
    TaskBenchmarkMetadata,
    TaskConstraints,
    TaskDifficulty,
    TaskInput,
    TaskInputBundle,
    TaskInputKind,
    TaskSelectionTier,
    TaskSpec,
    TaskType,
    VerifierPlan,
    VerifierStep,
    VerifierStepKind,
)
from repo_harness_lab.tasks.validator import validate_task_spec


class TaskIntakeValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TaskIntake:
    task_id: str
    title: str
    business_request: str
    task_type: TaskType
    repo_source: RepoSource
    repo_revision: str | None = None
    business_inputs: TaskInputBundle = field(default_factory=TaskInputBundle)
    context_paths: tuple[str, ...] = ()
    editable_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    allow_network: bool = False
    max_runtime_seconds: int | None = None
    max_cost_usd: float | None = None
    expected_changed_files: tuple[str, ...] = ()
    behavioral_checks: tuple[str, ...] = ()
    setup_steps: tuple[str, ...] = ()
    acceptance_checks: tuple[VerifierStep, ...] = ()
    required_passes: int | None = None
    failure_policy: FailurePolicy = FailurePolicy.COLLECT_ALL
    benchmark_metadata: TaskBenchmarkMetadata = field(default_factory=TaskBenchmarkMetadata)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class JsonTaskIntakeLoader:
    def load(self, source: str | Path) -> TaskIntake:
        path = Path(source).resolve()
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        intake = parse_task_intake(payload, base_dir=path.parent)
        validate_task_intake(intake)
        return intake



def default_task_intake_template() -> dict[str, object]:
    return {
        'task_id': 'billing-release-sync',
        'title': '根据发布单同步配置与摘要',
        'business_request': '请把 config/release.env 和 docs/release_summary.md 更新为业务输入里的准确发布信息。不要改动其他文件。',
        'task_type': 'requirement_change',
        'repo_source': {
            'kind': 'local_path',
            'path_or_url': './repo',
            'checkout_mode': 'copy',
        },
        'business_inputs': {
            'items': [
                {
                    'name': 'release_spec',
                    'kind': 'text',
                    'description': '业务侧给出的 release_version、release_channel、codename',
                    'content': 'release_version=2026.04.0\nrelease_channel=canary\ncodename=Paper Lantern',
                }
            ]
        },
        'context_paths': ['docs/release_contract.md'],
        'editable_paths': ['config/release.env', 'docs/release_summary.md'],
        'forbidden_paths': ['README.md'],
        'expected_changed_files': ['config/release.env', 'docs/release_summary.md'],
        'behavioral_checks': ['配置和摘要中的版本号、发布渠道、代号必须一致'],
        'acceptance_checks': [
            {
                'name': 'release-env-check',
                'kind': 'test',
                'command': ['python', '-c', "print('replace me with a deterministic check')"],
                'notes': 'Replace this command with a real acceptance check before running the task.',
            }
        ],
        'benchmark': {
            'tier': 'open',
            'difficulty': 'medium',
            'tags': ['release_sync'],
            'owner': 'team-name',
            'source': 'task_intake',
            'notes': ['scaffold from business intake'],
        },
        'metadata': {
            'request_ticket': 'PROJ-123',
        },
    }



def parse_task_intake(data: Mapping[str, Any], *, base_dir: Path | None = None) -> TaskIntake:
    verifier_payload = _mapping(data.get('verifier_plan'))
    benchmark_payload = data.get('benchmark')
    if benchmark_payload is None:
        benchmark_payload = data.get('benchmark_metadata')
    context_payload = data.get('context_paths')
    if context_payload is None:
        context_payload = data.get('related_paths')
    inputs_payload = data.get('business_inputs')
    if inputs_payload is None:
        inputs_payload = data.get('inputs')
    checks_payload = data.get('acceptance_checks')
    if checks_payload is None:
        checks_payload = verifier_payload.get('steps', ())

    return TaskIntake(
        task_id=str(data['task_id']),
        title=str(data['title']),
        business_request=str(data.get('business_request') or data.get('description') or ''),
        task_type=TaskType(data['task_type']),
        repo_source=_parse_repo_source(_mapping(data['repo_source']), base_dir=base_dir),
        repo_revision=_optional_str(data.get('repo_revision')),
        business_inputs=_parse_task_input_bundle(inputs_payload, base_dir=base_dir),
        context_paths=_tuple_of_str(context_payload),
        editable_paths=_tuple_of_str(data.get('editable_paths')),
        forbidden_paths=_tuple_of_str(data.get('forbidden_paths')),
        allowed_tools=_tuple_of_str(data.get('allowed_tools')),
        allow_network=bool(data.get('allow_network', False)),
        max_runtime_seconds=_optional_int(data.get('max_runtime_seconds')),
        max_cost_usd=_optional_float(data.get('max_cost_usd')),
        expected_changed_files=_tuple_of_str(data.get('expected_changed_files') or data.get('changed_files')),
        behavioral_checks=_tuple_of_str(data.get('behavioral_checks')),
        setup_steps=_tuple_of_str(data.get('setup_steps')),
        acceptance_checks=tuple(_parse_verifier_step(_mapping(item)) for item in checks_payload),
        required_passes=_optional_int(data.get('required_passes', verifier_payload.get('required_passes'))),
        failure_policy=FailurePolicy(data.get('failure_policy', verifier_payload.get('failure_policy', FailurePolicy.COLLECT_ALL.value))),
        benchmark_metadata=_parse_benchmark_metadata(benchmark_payload),
        metadata=_mapping(data.get('metadata')),
    )



def build_task_spec_from_intake(intake: TaskIntake) -> TaskSpec:
    inferred_signals = _infer_harness_signals(intake)
    benchmark = intake.benchmark_metadata
    metadata = dict(intake.metadata)
    context_paths = _merge_unique(metadata.get('context_paths'), intake.context_paths)
    if context_paths:
        metadata['context_paths'] = list(context_paths)
    metadata.setdefault('intake_schema', 'business_task_intake/v1')
    metadata.setdefault('scaffolded_from_intake', True)

    task = TaskSpec(
        task_id=intake.task_id,
        title=intake.title,
        description=intake.business_request,
        task_type=intake.task_type,
        repo_source=intake.repo_source,
        repo_revision=intake.repo_revision,
        inputs=intake.business_inputs,
        constraints=TaskConstraints(
            allow_network=intake.allow_network,
            editable_paths=intake.editable_paths,
            forbidden_paths=intake.forbidden_paths,
            allowed_tools=intake.allowed_tools,
            max_runtime_seconds=intake.max_runtime_seconds,
            max_cost_usd=intake.max_cost_usd,
        ),
        success_criteria=SuccessCriteria(
            required_verifier_steps=tuple(step.name for step in intake.acceptance_checks if step.required),
            changed_files=intake.expected_changed_files,
            behavioral_checks=intake.behavioral_checks,
        ),
        setup_steps=intake.setup_steps,
        verifier_plan=VerifierPlan(
            steps=intake.acceptance_checks,
            required_passes=intake.required_passes,
            failure_policy=intake.failure_policy,
        ),
        benchmark_metadata=TaskBenchmarkMetadata(
            tier=benchmark.tier,
            difficulty=benchmark.difficulty,
            tags=benchmark.tags,
            harness_signals=_merge_unique(benchmark.harness_signals, inferred_signals),
            owner=benchmark.owner,
            source=benchmark.source or 'task_intake',
            notes=_merge_unique(benchmark.notes, ('scaffolded from business task intake',)),
        ),
        metadata=metadata,
    )
    validate_task_spec(task)
    return task



def validate_task_intake(intake: TaskIntake) -> None:
    errors: list[str] = []
    if not intake.task_id.strip():
        errors.append('task_id must not be empty')
    if not intake.title.strip():
        errors.append('title must not be empty')
    if not intake.business_request.strip():
        errors.append('business_request must not be empty')
    if not intake.repo_source.path_or_url.strip():
        errors.append('repo_source.path_or_url must not be empty')
    if not intake.editable_paths:
        errors.append('editable_paths must not be empty')
    if not intake.acceptance_checks:
        errors.append('acceptance_checks must not be empty')

    overlap = set(intake.editable_paths) & set(intake.forbidden_paths)
    if overlap:
        errors.append(f'editable_paths and forbidden_paths overlap: {sorted(overlap)}')

    _validate_non_empty_unique(intake.context_paths, field_name='context_paths', errors=errors)
    _validate_non_empty_unique(intake.editable_paths, field_name='editable_paths', errors=errors)
    _validate_non_empty_unique(intake.forbidden_paths, field_name='forbidden_paths', errors=errors)
    _validate_non_empty_unique(intake.expected_changed_files, field_name='expected_changed_files', errors=errors)

    step_names = [step.name for step in intake.acceptance_checks]
    if len(step_names) != len(set(step_names)):
        errors.append('acceptance_checks names must be unique')
    for step in intake.acceptance_checks:
        if not step.name.strip():
            errors.append('acceptance_checks name must not be empty')
        if not step.command:
            errors.append(f"acceptance_checks '{step.name}' must define a command")

    if errors:
        raise TaskIntakeValidationError('; '.join(errors))



def _infer_harness_signals(intake: TaskIntake) -> tuple[str, ...]:
    signals: list[str] = []
    if intake.context_paths:
        signals.append('repo_context')
    if not intake.business_inputs.is_empty:
        signals.append('task_inputs')
    editable_surface = max(len(intake.editable_paths), len(intake.expected_changed_files))
    if editable_surface >= 2:
        signals.append('multi_file_edit')
    if intake.acceptance_checks:
        signals.append('verifier_plan')
    return tuple(signals)



def _parse_repo_source(data: Mapping[str, Any], *, base_dir: Path | None) -> RepoSource:
    kind = RepoSourceKind(data['kind'])
    path_or_url = str(data['path_or_url'])
    if kind is RepoSourceKind.LOCAL_PATH:
        path_or_url = _resolve_relative_path(path_or_url, base_dir=base_dir)
    return RepoSource(
        kind=kind,
        path_or_url=path_or_url,
        default_branch=str(data.get('default_branch', 'main')),
        checkout_mode=RepoCheckoutMode(data.get('checkout_mode', RepoCheckoutMode.COPY.value)),
    )



def _parse_task_input_bundle(data: Any, *, base_dir: Path | None) -> TaskInputBundle:
    if data is None:
        return TaskInputBundle()
    if isinstance(data, Mapping):
        raw_items = data.get('items', ())
    else:
        raw_items = data
    items = tuple(_parse_task_input(_mapping(item), base_dir=base_dir) for item in raw_items)
    return TaskInputBundle(items=items)



def _parse_task_input(data: Mapping[str, Any], *, base_dir: Path | None) -> TaskInput:
    raw_path = _optional_str(data.get('path'))
    resolved_path = _resolve_relative_path(raw_path, base_dir=base_dir) if raw_path else None
    return TaskInput(
        name=str(data['name']),
        kind=TaskInputKind(data['kind']),
        description=str(data.get('description', '')),
        content=_optional_str(data.get('content')),
        path=resolved_path,
        metadata=_mapping(data.get('metadata')),
    )



def _parse_verifier_step(data: Mapping[str, Any]) -> VerifierStep:
    return VerifierStep(
        name=str(data['name']),
        kind=VerifierStepKind(data.get('kind', VerifierStepKind.TEST.value)),
        command=_tuple_of_str(data.get('command')),
        required=bool(data.get('required', True)),
        notes=str(data.get('notes', '')),
    )



def _parse_benchmark_metadata(data: Any) -> TaskBenchmarkMetadata:
    payload = _mapping(data)
    return TaskBenchmarkMetadata(
        tier=TaskSelectionTier(payload.get('tier', TaskSelectionTier.OPEN.value)),
        difficulty=TaskDifficulty(payload.get('difficulty', TaskDifficulty.MEDIUM.value)),
        tags=_tuple_of_str(payload.get('tags')),
        harness_signals=_tuple_of_str(payload.get('harness_signals')),
        owner=_optional_str(payload.get('owner')),
        source=_optional_str(payload.get('source')),
        notes=_tuple_of_str(payload.get('notes')),
    )



def _merge_unique(*values: object) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            candidates = (value,)
        else:
            candidates = value
        for item in candidates:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return tuple(merged)



def _resolve_relative_path(value: str | None, *, base_dir: Path | None) -> str:
    if value is None:
        return ''
    path = Path(value)
    if path.is_absolute() or base_dir is None:
        return str(path)
    return str((base_dir / path).resolve())



def _mapping(data: Any) -> Mapping[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TypeError(f'expected mapping, got {type(data).__name__}')
    return data



def _tuple_of_str(data: Any) -> tuple[str, ...]:
    if data is None:
        return ()
    return tuple(str(item) for item in data)



def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)



def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)



def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)



def _validate_non_empty_unique(values: tuple[str, ...], *, field_name: str, errors: list[str]) -> None:
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if not item:
            errors.append(f'{field_name} must not contain empty values')
            continue
        normalized.append(item)
    if len(normalized) != len(set(normalized)):
        errors.append(f'{field_name} must not contain duplicates')