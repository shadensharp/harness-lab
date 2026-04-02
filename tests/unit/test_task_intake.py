from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.tasks.intake import (
    JsonTaskIntakeLoader,
    TaskIntakeValidationError,
    build_task_spec_from_intake,
)


class TaskIntakeTests(unittest.TestCase):
    def test_loader_builds_task_spec_and_infers_harness_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_dir = root / 'repo'
            repo_dir.mkdir()
            contract_path = root / 'release_contract.md'
            contract_path.write_text('contract\n', encoding='utf8')
            intake_path = root / 'intake.json'
            intake_path.write_text(
                json.dumps(
                    {
                        'task_id': 'release-intake-001',
                        'title': 'Release sync intake',
                        'business_request': '同步配置和摘要。',
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
                                    'kind': 'file',
                                    'path': './release_contract.md',
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
                            },
                            {
                                'name': 'release-summary-check',
                                'kind': 'test',
                                'command': [sys.executable, '-V'],
                            },
                        ],
                        'benchmark': {
                            'tags': ['release_sync'],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding='utf8',
            )

            intake = JsonTaskIntakeLoader().load(intake_path)
            task = build_task_spec_from_intake(intake)

            self.assertEqual(task.repo_source.path_or_url, str(repo_dir.resolve()))
            self.assertEqual(task.inputs.items[0].path, str(contract_path.resolve()))
            self.assertEqual(task.success_criteria.required_verifier_steps, ('release-env-check', 'release-summary-check'))
            self.assertEqual(task.metadata['context_paths'], ['docs/release_contract.md'])
            self.assertIn('repo_context', task.benchmark_metadata.harness_signals)
            self.assertIn('task_inputs', task.benchmark_metadata.harness_signals)
            self.assertIn('multi_file_edit', task.benchmark_metadata.harness_signals)
            self.assertIn('verifier_plan', task.benchmark_metadata.harness_signals)

    def test_loader_rejects_missing_acceptance_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            repo_dir = root / 'repo'
            repo_dir.mkdir()
            intake_path = root / 'invalid-intake.json'
            intake_path.write_text(
                json.dumps(
                    {
                        'task_id': 'release-intake-002',
                        'title': 'Invalid intake',
                        'business_request': '同步配置。',
                        'task_type': 'requirement_change',
                        'repo_source': {
                            'kind': 'local_path',
                            'path_or_url': './repo',
                            'checkout_mode': 'copy',
                        },
                        'editable_paths': ['config/release.env'],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding='utf8',
            )

            with self.assertRaises(TaskIntakeValidationError):
                JsonTaskIntakeLoader().load(intake_path)


if __name__ == '__main__':
    unittest.main()