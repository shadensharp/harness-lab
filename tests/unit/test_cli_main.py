from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SRC_ROOT = Path(__file__).resolve().parents[2] / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.cli.main import main
from repo_harness_lab.tasks.loader import JsonTaskLoader


class CliMainTests(unittest.TestCase):
    def test_show_settings_renders_json_serializable_output(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(['show-settings'])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertIn('paths', payload)
        self.assertIn('project_root', payload['paths'])

    def test_show_task_intake_template_and_scaffold_task_spec(self) -> None:
        template_buffer = io.StringIO()
        with redirect_stdout(template_buffer):
            template_exit = main(['show-task-intake-template'])

        template_payload = json.loads(template_buffer.getvalue())
        self.assertEqual(template_exit, 0)
        self.assertIn('business_request', template_payload)
        self.assertIn('acceptance_checks', template_payload)

        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_dir = root / 'repo'
            repo_dir.mkdir()
            output_path = root / 'scaffolded-task.json'
            intake_path = root / 'intake.json'
            intake_path.write_text(
                json.dumps(
                    {
                        'task_id': 'task-intake-001',
                        'title': 'Scaffold task',
                        'business_request': '根据业务输入同步 config/release.env 和 docs/release_summary.md。',
                        'task_type': 'requirement_change',
                        'repo_source': {
                            'kind': 'local_path',
                            'path_or_url': './repo',
                            'checkout_mode': 'copy'
                        },
                        'business_inputs': {
                            'items': [
                                {
                                    'name': 'release_spec',
                                    'kind': 'text',
                                    'content': 'release_version=2026.04.0'
                                }
                            ]
                        },
                        'context_paths': ['docs/release_contract.md'],
                        'editable_paths': ['config/release.env', 'docs/release_summary.md'],
                        'forbidden_paths': ['README.md'],
                        'expected_changed_files': ['config/release.env', 'docs/release_summary.md'],
                        'acceptance_checks': [
                            {
                                'name': 'release-env-check',
                                'kind': 'test',
                                'command': [sys.executable, '-V']
                            }
                        ],
                        'benchmark': {
                            'tier': 'open',
                            'difficulty': 'medium',
                            'tags': ['release_sync']
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding='utf8',
            )

            scaffold_buffer = io.StringIO()
            with redirect_stdout(scaffold_buffer):
                scaffold_exit = main(['scaffold-task-spec', str(intake_path), '--write', str(output_path)])

            scaffold_payload = json.loads(scaffold_buffer.getvalue())
            task = JsonTaskLoader().load(output_path)

            self.assertEqual(scaffold_exit, 0)
            self.assertTrue(scaffold_payload['ok'])
            self.assertEqual(task.task_id, 'task-intake-001')
            self.assertIn('task_inputs', task.benchmark_metadata.harness_signals)
            self.assertIn('multi_file_edit', task.benchmark_metadata.harness_signals)
            self.assertIn('verifier_plan', task.benchmark_metadata.harness_signals)
            self.assertIn('repo_context', task.benchmark_metadata.harness_signals)
            self.assertEqual(task.success_criteria.required_verifier_steps, ('release-env-check',))
            self.assertEqual(task.metadata['context_paths'], ['docs/release_contract.md'])

    def test_create_open_task_intake_builds_user_owned_intake_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_dir = root / 'repo'
            repo_dir.mkdir()
            output_path = root / 'open-task.intake.json'

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        'create-open-task-intake',
                        '--task-id',
                        'playable-tetris',
                        '--title',
                        '实现可玩的俄罗斯方块',
                        '--task',
                        '请在当前仓库中实现一个用户可以直接运行和游玩的俄罗斯方块小游戏。',
                        '--repo',
                        str(repo_dir),
                        '--editable-path',
                        'src',
                        '--changed-file',
                        'src/game.py',
                        '--context-path',
                        'README.md',
                        '--behavioral-check',
                        '游戏应该可以启动并响应键盘输入',
                        '--text-input',
                        'target_fps=60',
                        '--write',
                        str(output_path),
                    ]
                )

            payload = json.loads(buffer.getvalue())
            intake_payload = json.loads(output_path.read_text(encoding='utf8'))

            self.assertEqual(exit_code, 0)
            self.assertTrue(payload['ok'])
            self.assertEqual(intake_payload['task_id'], 'playable-tetris')
            self.assertEqual(intake_payload['title'], '实现可玩的俄罗斯方块')
            self.assertEqual(intake_payload['repo_source']['path_or_url'], str(repo_dir.resolve()))
            self.assertEqual(intake_payload['editable_paths'], ['src'])
            self.assertEqual(intake_payload['expected_changed_files'], ['src/game.py'])
            self.assertEqual(intake_payload['context_paths'], ['README.md'])
            self.assertEqual(intake_payload['business_inputs']['items'][0]['name'], 'target_fps')
            self.assertEqual(intake_payload['business_inputs']['items'][0]['content'], '60')
            self.assertTrue(intake_payload['metadata']['open_task_entry'])
            self.assertIn('preview-intake', payload['next_commands']['preview_intake'])

    def test_validate_task_reports_invalid_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            task_path = Path(temp_root) / 'invalid-task.json'
            task_path.write_text(
                json.dumps(
                    {
                        'task_id': 'task-001',
                        'title': 'Invalid task',
                        'description': 'Broken verifier references',
                        'task_type': 'requirement_change',
                        'repo_source': {
                            'kind': 'local_path',
                            'path_or_url': 'E:/repo-harness-lab',
                            'checkout_mode': 'copy'
                        },
                        'success_criteria': {
                            'required_verifier_steps': ['missing-step']
                        },
                        'verifier_plan': {
                            'steps': [
                                {
                                    'name': 'unit-tests',
                                    'kind': 'test',
                                    'command': ['python', '-V']
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding='utf8',
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(['validate-task', str(task_path)])

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertFalse(payload['valid'])
            self.assertIn('missing-step', payload['error'])

    def test_list_task_pool_filters_by_tier_tag_and_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            tasks_dir = root / 'tasks'
            tasks_dir.mkdir()
            _write_task(
                tasks_dir / 'task-a.json',
                task_id='task-a',
                title='Task A',
                task_type='bug_fix',
                tier='curated',
                difficulty='hard',
                tags=['cross_file'],
                harness_signals=['verifier_feedback'],
            )
            _write_task(
                tasks_dir / 'task-b.json',
                task_id='task-b',
                title='Task B',
                task_type='requirement_change',
                tier='open',
                difficulty='easy',
                tags=['single_file'],
                harness_signals=['repo_search'],
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        'list-task-pool',
                        str(tasks_dir),
                        '--tier',
                        'curated',
                        '--tag',
                        'cross_file',
                        '--signal',
                        'verifier_feedback',
                    ]
                )

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]['task_id'], 'task-a')

    def test_recommend_tasks_returns_ranked_reasons_without_restricting_open_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            tasks_dir = root / 'tasks'
            tasks_dir.mkdir()
            _write_task(
                tasks_dir / 'task-a.json',
                task_id='task-a',
                title='Task A',
                task_type='requirement_change',
                tier='curated',
                difficulty='medium',
                tags=['provider_uplift'],
                harness_signals=['repo_context', 'verifier_feedback'],
                editable_paths=['README.md', 'docs/guide.md'],
                changed_files=['README.md', 'docs/guide.md'],
                include_input=True,
            )
            _write_task(
                tasks_dir / 'task-b.json',
                task_id='task-b',
                title='Task B',
                task_type='requirement_change',
                tier='open',
                difficulty='easy',
                tags=['single_file'],
                harness_signals=[],
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        'recommend-tasks',
                        str(tasks_dir),
                        '--prefer-tag',
                        'provider_uplift',
                        '--prefer-signal',
                        'repo_context',
                        '--prefer-signal',
                        'verifier_feedback',
                    ]
                )

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(payload), 2)
            self.assertEqual(payload[0]['task_id'], 'task-a')
            self.assertEqual(payload[1]['task_id'], 'task-b')
            self.assertGreater(payload[0]['recommendation_score'], payload[1]['recommendation_score'])
            self.assertIn('provider_uplift', payload[0]['matched_preferred_tags'])
            self.assertIn('repo_context', payload[0]['matched_preferred_signals'])
            self.assertTrue(payload[0]['recommendation_reasons'])

    def test_run_task_executes_local_harness_and_prints_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_repo = root / 'source-repo'
            source_repo.mkdir()
            task_path = root / 'task.json'
            runtime_root = root / 'runtime'
            (source_repo / 'README.md').write_text('hello\n', encoding='utf8')
            task_path.write_text(
                json.dumps(
                    {
                        'task_id': 'task-001',
                        'title': 'CLI run',
                        'description': 'Run through CLI',
                        'task_type': 'requirement_change',
                        'repo_source': {
                            'kind': 'local_path',
                            'path_or_url': str(source_repo),
                            'checkout_mode': 'copy'
                        },
                        'setup_steps': [],
                        'verifier_plan': {
                            'steps': [
                                {
                                    'name': 'artifact-check',
                                    'kind': 'test',
                                    'command': [
                                        sys.executable,
                                        '-c',
                                        "from pathlib import Path; raise SystemExit(0 if Path('generated.txt').read_text(encoding='utf8') == 'ok' else 1)"
                                    ]
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding='utf8',
            )

            buffer = io.StringIO()
            env = {'REPO_HARNESS_LAB_RUNTIME_ROOT': str(runtime_root)}
            with patch.dict(os.environ, env, clear=False):
                with redirect_stdout(buffer):
                    exit_code = main(
                        [
                            'run-task',
                            str(task_path),
                            '--agent-command',
                            sys.executable,
                            '-c',
                            "from pathlib import Path; Path('generated.txt').write_text('ok', encoding='utf8')"
                        ]
                    )

            payload = json.loads(buffer.getvalue())
            summary_path = runtime_root / 'runs' / payload['run_id'] / 'summary.json'

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['status'], 'succeeded')
            self.assertTrue(summary_path.exists())



def _write_task(
    path: Path,
    *,
    task_id: str,
    title: str,
    task_type: str,
    tier: str,
    difficulty: str,
    tags: list[str],
    harness_signals: list[str],
    editable_paths: list[str] | None = None,
    changed_files: list[str] | None = None,
    include_input: bool = False,
) -> None:
    payload = {
        'task_id': task_id,
        'title': title,
        'description': title,
        'task_type': task_type,
        'repo_source': {
            'kind': 'local_path',
            'path_or_url': str(path.parent),
            'checkout_mode': 'copy'
        },
        'verifier_plan': {
            'steps': [
                {
                    'name': 'unit-tests',
                    'kind': 'test',
                    'command': [sys.executable, '-V']
                }
            ]
        },
        'benchmark_metadata': {
            'tier': tier,
            'difficulty': difficulty,
            'tags': tags,
            'harness_signals': harness_signals,
        },
        'constraints': {
            'editable_paths': editable_paths or [],
        },
        'success_criteria': {
            'changed_files': changed_files or [],
        },
    }
    if include_input:
        payload['inputs'] = {
            'items': [
                {
                    'name': 'issue',
                    'kind': 'text',
                    'content': 'Please update docs and README together.'
                }
            ]
        }

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    unittest.main()
