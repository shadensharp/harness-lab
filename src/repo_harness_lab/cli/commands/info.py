from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from repo_harness_lab.cli.commands.common import print_json, write_task_intake_preview_artifacts
from repo_harness_lab.config.settings import load_settings
from repo_harness_lab.domain.task_spec import TaskDifficulty, TaskSelectionTier, TaskType
from repo_harness_lab.shared.serialization import to_jsonable
from repo_harness_lab.tasks.catalog import (
    FileSystemTaskCatalog,
    serialize_catalog_entry,
    serialize_task_recommendation,
)
from repo_harness_lab.tasks.intake import JsonTaskIntakeLoader, build_task_spec_from_intake, default_task_intake_template
from repo_harness_lab.tasks.intake_preview import build_task_intake_preview
from repo_harness_lab.tasks.loader import JsonTaskLoader
from repo_harness_lab.tasks.validator import TaskValidationError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    show_task = subparsers.add_parser('show-task', help='Load and print a task spec as JSON')
    show_task.add_argument('source')
    show_task.set_defaults(handler=handle_show_task)

    show_task_intake_template = subparsers.add_parser('show-task-intake-template', help='Print a business task intake template as JSON')
    show_task_intake_template.set_defaults(handler=handle_show_task_intake_template)

    create_open_task_intake = subparsers.add_parser(
        'create-open-task-intake',
        help='Create a user-owned repo task intake instead of relying on fixed example tasks',
    )
    create_open_task_intake.add_argument('--task-id', required=True)
    create_open_task_intake.add_argument('--title', required=True)
    create_open_task_intake.add_argument('--task', required=True, help='Human-readable business request')
    create_open_task_intake.add_argument('--repo', required=True, help='Local repository path')
    create_open_task_intake.add_argument('--task-type', choices=[item.value for item in TaskType], default=TaskType.REQUIREMENT_CHANGE.value)
    create_open_task_intake.add_argument('--context-path', action='append', default=[])
    create_open_task_intake.add_argument('--editable-path', action='append', default=[])
    create_open_task_intake.add_argument('--forbidden-path', action='append', default=[])
    create_open_task_intake.add_argument('--changed-file', action='append', default=[])
    create_open_task_intake.add_argument('--behavioral-check', action='append', default=[])
    create_open_task_intake.add_argument(
        '--text-input',
        action='append',
        default=[],
        help='Repeatable NAME=CONTENT business input',
    )
    create_open_task_intake.add_argument('--write')
    create_open_task_intake.set_defaults(handler=handle_create_open_task_intake)

    preview_intake = subparsers.add_parser(
        'preview-intake',
        help='Preview how a business task intake maps into TaskSpec fields and the current harness package',
    )
    preview_intake.add_argument('source')
    preview_intake.add_argument('--format', choices=('json', 'html', 'both'), default='json')
    preview_intake.add_argument('--write')
    preview_intake.set_defaults(handler=handle_preview_intake)

    scaffold_task_spec = subparsers.add_parser('scaffold-task-spec', help='Convert a business task intake JSON into a TaskSpec scaffold')
    scaffold_task_spec.add_argument('source')
    scaffold_task_spec.add_argument('--write')
    scaffold_task_spec.set_defaults(handler=handle_scaffold_task_spec)

    validate_task = subparsers.add_parser('validate-task', help='Validate a task spec')
    validate_task.add_argument('source')
    validate_task.set_defaults(handler=handle_validate_task)

    list_task_pool = subparsers.add_parser('list-task-pool', help='Scan a task directory and print structured task pool entries')
    list_task_pool.add_argument('source')
    list_task_pool.add_argument('--tier', choices=[item.value for item in TaskSelectionTier])
    list_task_pool.add_argument('--difficulty', choices=[item.value for item in TaskDifficulty])
    list_task_pool.add_argument('--task-type', choices=[item.value for item in TaskType])
    list_task_pool.add_argument('--tag', action='append', default=[])
    list_task_pool.add_argument('--signal', action='append', default=[])
    list_task_pool.add_argument('--limit', type=int)
    list_task_pool.set_defaults(handler=handle_list_task_pool)

    recommend_tasks = subparsers.add_parser(
        'recommend-tasks',
        help='Recommend tasks that best demonstrate harness uplift without restricting what users can run',
    )
    recommend_tasks.add_argument('source')
    recommend_tasks.add_argument('--tier', choices=[item.value for item in TaskSelectionTier])
    recommend_tasks.add_argument('--difficulty', choices=[item.value for item in TaskDifficulty])
    recommend_tasks.add_argument('--task-type', choices=[item.value for item in TaskType])
    recommend_tasks.add_argument('--tag', action='append', default=[])
    recommend_tasks.add_argument('--signal', action='append', default=[])
    recommend_tasks.add_argument('--prefer-tag', action='append', default=[])
    recommend_tasks.add_argument('--prefer-signal', action='append', default=[])
    recommend_tasks.add_argument('--limit', type=int, default=10)
    recommend_tasks.set_defaults(handler=handle_recommend_tasks)

    show_settings = subparsers.add_parser('show-settings', help='Print resolved settings as JSON')
    show_settings.set_defaults(handler=handle_show_settings)


def handle_show_task(args: argparse.Namespace) -> int:
    task = JsonTaskLoader().load(args.source)
    print_json(task)
    return 0


def handle_show_task_intake_template(args: argparse.Namespace) -> int:
    del args
    settings = load_settings()
    example_template_path = settings.paths.examples_dir / 'intakes' / 'portal_tetris_task_intake.json'
    if example_template_path.exists():
        print_json(json.loads(example_template_path.read_text(encoding='utf8')))
        return 0
    print_json(default_task_intake_template())
    return 0


def handle_create_open_task_intake(args: argparse.Namespace) -> int:
    payload = _build_open_task_intake_payload(args)
    if not args.write:
        print_json(payload)
        return 0

    output_path = Path(args.write).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf8')
    print_json(
        {
            'ok': True,
            'path': str(output_path),
            'task_id': payload['task_id'],
            'next_commands': {
                'preview_intake': f"python -m repo_harness_lab.cli.main preview-intake '{output_path}' --format both",
                'run_intake_eval': f"python -m repo_harness_lab.cli.main run-intake-eval '{output_path}' --provider <provider> --model <model> --api-key-env <API_KEY_ENV>",
            },
        }
    )
    return 0


def handle_preview_intake(args: argparse.Namespace) -> int:
    intake = JsonTaskIntakeLoader().load(args.source)
    preview = build_task_intake_preview(intake, source_path=args.source)
    if args.format == 'json':
        print_json(preview)
        return 0

    settings = load_settings()
    settings.paths.ensure_runtime_directories()
    task_preview = preview.get('task_spec_preview', {}) if isinstance(preview, dict) else {}
    task_id = str(task_preview.get('task_id', 'task-intake-preview'))
    output_path = Path(args.write).resolve() if args.write else None
    html_path, json_path = write_task_intake_preview_artifacts(
        settings,
        preview,
        task_id=task_id,
        output_path=output_path,
    )

    payload: dict[str, object] = {
        'ok': True,
        'format': args.format,
        'task_id': task_id,
        'artifacts': {
            'html_path': str(html_path),
            'json_path': str(json_path),
        },
    }
    if args.format == 'both':
        payload['preview'] = preview
    print_json(payload)
    return 0


def handle_scaffold_task_spec(args: argparse.Namespace) -> int:
    task = build_task_spec_from_intake(JsonTaskIntakeLoader().load(args.source))
    if not args.write:
        print_json(task)
        return 0

    output_path = Path(args.write).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(to_jsonable(task), ensure_ascii=False, indent=2), encoding='utf8')
    print_json(
        {
            'ok': True,
            'task_id': task.task_id,
            'path': str(output_path),
            'harness_signals': list(task.benchmark_metadata.harness_signals),
        }
    )
    return 0


def handle_validate_task(args: argparse.Namespace) -> int:
    try:
        task = JsonTaskLoader().load(args.source)
    except TaskValidationError as exc:
        print_json({'valid': False, 'error': str(exc)})
        return 1

    print_json({'valid': True, 'task_id': task.task_id})
    return 0


def handle_list_task_pool(args: argparse.Namespace) -> int:
    catalog = FileSystemTaskCatalog()
    entries = catalog.select(
        args.source,
        tier=TaskSelectionTier(args.tier) if args.tier else None,
        difficulty=TaskDifficulty(args.difficulty) if args.difficulty else None,
        task_type=TaskType(args.task_type) if args.task_type else None,
        tags=tuple(args.tag),
        harness_signals=tuple(args.signal),
        limit=args.limit,
    )
    print_json([serialize_catalog_entry(entry) for entry in entries])
    return 0


def handle_recommend_tasks(args: argparse.Namespace) -> int:
    catalog = FileSystemTaskCatalog()
    recommendations = catalog.recommend(
        args.source,
        tier=TaskSelectionTier(args.tier) if args.tier else None,
        difficulty=TaskDifficulty(args.difficulty) if args.difficulty else None,
        task_type=TaskType(args.task_type) if args.task_type else None,
        tags=tuple(args.tag),
        harness_signals=tuple(args.signal),
        prefer_tags=tuple(args.prefer_tag),
        prefer_harness_signals=tuple(args.prefer_signal),
        limit=args.limit,
    )
    print_json([serialize_task_recommendation(item) for item in recommendations])
    return 0


def handle_show_settings(args: argparse.Namespace) -> int:
    del args
    settings = load_settings()
    print_json(settings)
    return 0


def _build_open_task_intake_payload(args: argparse.Namespace) -> dict[str, object]:
    repo_path = str(Path(args.repo).resolve())
    return {
        'task_id': args.task_id,
        'title': args.title,
        'business_request': args.task,
        'task_type': args.task_type,
        'repo_source': {
            'kind': 'local_path',
            'path_or_url': repo_path,
            'checkout_mode': 'copy',
        },
        'business_inputs': {
            'items': [_parse_text_input(item) for item in args.text_input],
        },
        'context_paths': list(args.context_path),
        'editable_paths': list(args.editable_path),
        'forbidden_paths': list(args.forbidden_path),
        'expected_changed_files': list(args.changed_file),
        'behavioral_checks': list(args.behavioral_check),
        'acceptance_checks': [
            {
                'name': 'replace-me-with-a-real-check',
                'kind': 'test',
                'command': [
                    sys.executable,
                    '-c',
                    "print('replace acceptance_checks before running this intake'); raise SystemExit(1)",
                ],
                'notes': 'Replace this placeholder with deterministic checks before running evals.',
            }
        ],
        'benchmark': {
            'tier': 'open',
            'difficulty': 'medium',
            'tags': ['user_supplied_task'],
            'owner': 'user',
            'source': 'open_task_entry',
            'notes': [
                'created from open task entry',
                'replace placeholder acceptance check before running evals',
            ],
        },
        'metadata': {
            'open_task_entry': True,
            'task_origin': 'user_input',
        },
    }


def _parse_text_input(raw: str) -> dict[str, object]:
    name, separator, content = raw.partition('=')
    if not separator or not name.strip():
        raise ValueError(f"invalid --text-input value: {raw!r}; expected NAME=CONTENT")
    return {
        'name': name.strip(),
        'kind': 'text',
        'description': 'user-supplied business input',
        'content': content,
    }
