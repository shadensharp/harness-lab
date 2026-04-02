from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.cli.main import main
from repo_harness_lab.tasks.intake import JsonTaskIntakeLoader
from repo_harness_lab.tasks.intake_preview import build_task_intake_preview


class TaskIntakePreviewTests(unittest.TestCase):
    def test_build_task_intake_preview_shows_delivery_matrix_deltas_and_risks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_dir = root / 'repo'
            (repo_dir / 'config').mkdir(parents=True)
            (repo_dir / 'docs').mkdir(parents=True)
            (repo_dir / 'README.md').write_text('# Placeholder\n', encoding='utf8')
            (repo_dir / 'config' / 'release.env').write_text('VERSION=0.0.1\nCHANNEL=stable\n', encoding='utf8')
            (repo_dir / 'docs' / 'release_summary.md').write_text('# Pending Release\n', encoding='utf8')
            (repo_dir / 'docs' / 'release_contract.md').write_text('use release input\n', encoding='utf8')

            intake_path = root / 'intake.json'
            intake_path.write_text(
                json.dumps(
                    {
                        'task_id': 'release-intake-preview',
                        'title': 'Release intake preview',
                        'business_request': '????????',
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
                                    'content': 'release_version=2026.04.0',
                                }
                            ]
                        },
                        'context_paths': ['docs/release_contract.md'],
                        'editable_paths': ['config/release.env', 'docs/release_summary.md'],
                        'expected_changed_files': ['config/release.env', 'docs/release_summary.md'],
                        'acceptance_checks': [
                            {
                                'name': 'release-env-check',
                                'kind': 'test',
                                'command': [sys.executable, '-V'],
                            }
                        ],
                        'benchmark': {
                            'tier': 'open',
                            'difficulty': 'medium',
                            'tags': ['release_sync'],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding='utf8',
            )

            intake = JsonTaskIntakeLoader().load(intake_path)
            preview = build_task_intake_preview(intake, source_path=intake_path)

            self.assertEqual(preview['task_spec_preview']['task_id'], 'release-intake-preview')
            self.assertEqual(preview['task_spec_preview']['context_paths'], ['docs/release_contract.md'])
            self.assertEqual(
                preview['shared_task_information']['editable_paths'],
                ['config/release.env', 'docs/release_summary.md'],
            )
            self.assertIn(
                'Same response contract: JSON only with summary and writes.',
                preview['shared_task_information']['shared_prompt_items'],
            )
            self.assertEqual(preview['harness_delivery_matrix']['bare']['context_file_count'], 0)
            self.assertEqual(preview['harness_delivery_matrix']['bare']['included_input_names'], [])
            self.assertIn(
                'Extra harness material: repository tree only (4 files discoverable).',
                preview['harness_delivery_matrix']['bare']['additional_delivery_items'],
            )
            self.assertEqual(preview['harness_delivery_matrix']['basic']['context_files'][0], 'docs/release_contract.md')
            self.assertIn('config/release.env', preview['harness_delivery_matrix']['basic']['context_files'])
            self.assertIn('docs/release_summary.md', preview['harness_delivery_matrix']['basic']['context_files'])
            self.assertEqual(preview['harness_delivery_matrix']['full']['included_input_names'], ['release_spec'])
            self.assertEqual(preview['harness_delivery_matrix']['full']['included_verifier_steps'], ['release-env-check'])
            self.assertIn(
                'Injected task inputs: release_spec',
                preview['harness_delivery_matrix']['full']['additional_delivery_items'],
            )
            self.assertEqual(preview['profile_delta_summary'][0]['from_profile'], 'bare')
            self.assertIn('context files: 0 -> 4 (+4)', preview['profile_delta_summary'][0]['summary_lines'])
            self.assertIn('new task inputs: release_spec', preview['profile_delta_summary'][1]['summary_lines'])
            self.assertIn('new verifier steps: release-env-check', preview['profile_delta_summary'][1]['summary_lines'])
            self.assertIn('preview-intake', preview['suggested_commands']['preview_intake'])
            self.assertIn('run-intake-eval', preview['suggested_commands']['run_intake_eval'])
            self.assertGreater(preview['uplift_readiness']['recommendation_score'], 0)
            self.assertIn('repo_context', preview['uplift_readiness']['declared_harness_signals'])
            self.assertIn(
                'Verifier plan is narrow, so the extra value of verifier-aware delivery may be harder to see.',
                preview['risk_warnings'],
            )

    def test_preview_intake_cli_renders_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_dir = root / 'repo'
            (repo_dir / 'docs').mkdir(parents=True)
            (repo_dir / 'README.md').write_text('# Placeholder\n', encoding='utf8')
            (repo_dir / 'docs' / 'target_title.txt').write_text('Golden Title\n', encoding='utf8')

            intake_path = root / 'intake.json'
            intake_path.write_text(
                json.dumps(
                    {
                        'task_id': 'readme-preview',
                        'title': 'Readme preview',
                        'business_request': '? README ?????????',
                        'task_type': 'requirement_change',
                        'repo_source': {
                            'kind': 'local_path',
                            'path_or_url': './repo',
                            'checkout_mode': 'copy',
                        },
                        'context_paths': ['docs/target_title.txt'],
                        'editable_paths': ['README.md'],
                        'expected_changed_files': ['README.md'],
                        'acceptance_checks': [
                            {
                                'name': 'readme-title-check',
                                'kind': 'test',
                                'command': [sys.executable, '-V'],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding='utf8',
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(['preview-intake', str(intake_path)])

            payload = json.loads(buffer.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload['task_spec_preview']['task_id'], 'readme-preview')
            self.assertEqual(payload['task_spec_preview']['editable_paths'], ['README.md'])
            self.assertEqual(payload['harness_delivery_matrix']['basic']['context_files'][0], 'docs/target_title.txt')
            self.assertEqual(payload['harness_delivery_matrix']['full']['included_verifier_steps'], ['readme-title-check'])
            self.assertIn('preview-intake', payload['suggested_commands']['preview_intake'])
            self.assertIn(
                'The task mostly changes a single file, so harness differences may be less visually obvious.',
                payload['risk_warnings'],
            )

    def test_preview_intake_cli_writes_html_and_json_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_dir = root / 'repo'
            (repo_dir / 'docs').mkdir(parents=True)
            (repo_dir / 'README.md').write_text('# Placeholder\n', encoding='utf8')
            (repo_dir / 'docs' / 'target_title.txt').write_text('Golden Title\n', encoding='utf8')

            intake_path = root / 'intake.json'
            output_path = root / 'preview.html'
            intake_path.write_text(
                json.dumps(
                    {
                        'task_id': 'readme-preview-html',
                        'title': 'Readme preview html',
                        'business_request': '? README ?????????',
                        'task_type': 'requirement_change',
                        'repo_source': {
                            'kind': 'local_path',
                            'path_or_url': './repo',
                            'checkout_mode': 'copy',
                        },
                        'context_paths': ['docs/target_title.txt'],
                        'editable_paths': ['README.md'],
                        'expected_changed_files': ['README.md'],
                        'acceptance_checks': [
                            {
                                'name': 'readme-title-check',
                                'kind': 'test',
                                'command': [sys.executable, '-V'],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding='utf8',
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(['preview-intake', str(intake_path), '--format', 'both', '--write', str(output_path)])

            payload = json.loads(buffer.getvalue())
            html_path = Path(payload['artifacts']['html_path'])
            json_path = Path(payload['artifacts']['json_path'])
            html_text = html_path.read_text(encoding='utf8')

            self.assertEqual(exit_code, 0)
            self.assertTrue(html_path.exists())
            self.assertTrue(json_path.exists())
            self.assertEqual(payload['preview']['task_spec_preview']['task_id'], 'readme-preview-html')
            self.assertIn('任务入口预览', html_text)
            self.assertIn('用户任务', html_text)
            self.assertIn('常用命令', html_text)
            self.assertIn('交付差异', html_text)
            self.assertIn('任务约束', html_text)
            self.assertIn('推荐与风险', html_text)
            self.assertIn('preview-intake', html_text)
            self.assertIn('run-intake-eval', html_text)


if __name__ == '__main__':
    unittest.main()
