from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.task_spec import TaskDifficulty, TaskSelectionTier, TaskType
from repo_harness_lab.tasks.catalog import (
    FileSystemTaskCatalog,
    serialize_catalog_entry,
    serialize_task_recommendation,
)


class FileSystemTaskCatalogTests(unittest.TestCase):
    def test_catalog_scans_and_filters_task_pool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            tasks_dir = root / 'tasks'
            tasks_dir.mkdir()
            _write_task(
                tasks_dir / 'curated-bug.json',
                task_id='task-bug',
                title='Fix failing integration path',
                task_type='bug_fix',
                tier='curated',
                difficulty='hard',
                tags=['cross_file', 'python'],
                harness_signals=['context_management', 'verifier_feedback'],
            )
            _write_task(
                tasks_dir / 'rolling-requirement.json',
                task_id='task-feature',
                title='Add small feature',
                task_type='requirement_change',
                tier='rolling',
                difficulty='easy',
                tags=['single_file'],
                harness_signals=['repo_search'],
            )

            catalog = FileSystemTaskCatalog()
            selected = catalog.select(
                tasks_dir,
                tier=TaskSelectionTier.CURATED,
                difficulty=TaskDifficulty.HARD,
                task_type=TaskType.BUG_FIX,
                tags=('cross_file',),
                harness_signals=('verifier_feedback',),
            )

            self.assertEqual(len(selected), 1)
            payload = serialize_catalog_entry(selected[0])
            self.assertEqual(payload['task_id'], 'task-bug')
            self.assertEqual(payload['tier'], 'curated')
            self.assertEqual(payload['difficulty'], 'hard')
            self.assertIn('cross_file', payload['tags'])

    def test_catalog_recommendation_scores_tasks_without_limiting_to_fixed_pool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            tasks_dir = root / 'tasks'
            tasks_dir.mkdir()
            _write_task(
                tasks_dir / 'curated-uplift.json',
                task_id='task-uplift',
                title='Update multiple files with verifier feedback',
                task_type='requirement_change',
                tier='curated',
                difficulty='medium',
                tags=['provider_uplift', 'cross_file'],
                harness_signals=['repo_context', 'verifier_feedback'],
                editable_paths=['README.md', 'docs/guide.md'],
                changed_files=['README.md', 'docs/guide.md'],
                include_input=True,
                notes=['recommended for uplift demos'],
            )
            _write_task(
                tasks_dir / 'open-smoke.json',
                task_id='task-open',
                title='Simple smoke task',
                task_type='requirement_change',
                tier='open',
                difficulty='easy',
                tags=['single_file'],
                harness_signals=[],
            )

            catalog = FileSystemTaskCatalog()
            recommendations = catalog.recommend(
                tasks_dir,
                prefer_tags=('provider_uplift',),
                prefer_harness_signals=('repo_context', 'verifier_feedback'),
            )

            self.assertEqual(len(recommendations), 2)
            self.assertEqual(recommendations[0].entry.task.task_id, 'task-uplift')
            self.assertGreater(recommendations[0].score, recommendations[1].score)
            payload = serialize_task_recommendation(recommendations[0])
            self.assertEqual(payload['task_id'], 'task-uplift')
            self.assertIn('provider_uplift', payload['matched_preferred_tags'])
            self.assertIn('repo_context', payload['matched_preferred_signals'])
            self.assertTrue(payload['recommendation_reasons'])



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
    notes: list[str] | None = None,
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
            'notes': notes or [],
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
                    'content': 'Please update the docs and README together.'
                }
            ]
        }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf8',
    )


if __name__ == '__main__':
    unittest.main()