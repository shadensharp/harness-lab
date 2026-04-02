from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.evals.loader import JsonEvalSuiteLoader
from repo_harness_lab.tasks.intake import JsonTaskIntakeLoader, build_task_spec_from_intake
from repo_harness_lab.tasks.loader import JsonTaskLoader


class ExampleAssetsTests(unittest.TestCase):
    def test_example_provider_tasks_suites_and_intake_load(self) -> None:
        root = Path(__file__).resolve().parents[2]
        readme_task_path = root / "examples" / "tasks" / "requirement_change" / "qwen_provider_readme_uplift_task.json"
        release_task_path = root / "examples" / "tasks" / "requirement_change" / "qwen_provider_release_input_uplift_task.json"
        policy_task_path = root / "examples" / "tasks" / "requirement_change" / "qwen_provider_policy_bundle_uplift_task.json"
        single_suite_path = root / "examples" / "evals" / "qwen_provider_uplift_suite.json"
        multi_suite_path = root / "examples" / "evals" / "qwen_provider_multi_signal_uplift_suite.json"
        extended_suite_path = root / "examples" / "evals" / "qwen_provider_extended_uplift_suite.json"
        release_intake_path = root / "examples" / "intakes" / "provider_release_input_task_intake.json"
        policy_intake_path = root / "examples" / "intakes" / "provider_policy_bundle_task_intake.json"

        task_loader = JsonTaskLoader()
        intake_loader = JsonTaskIntakeLoader()
        suite_loader = JsonEvalSuiteLoader()
        readme_task = task_loader.load(readme_task_path)
        release_task = task_loader.load(release_task_path)
        policy_task = task_loader.load(policy_task_path)
        release_intake = intake_loader.load(release_intake_path)
        policy_intake = intake_loader.load(policy_intake_path)
        scaffolded_release_task = build_task_spec_from_intake(release_intake)
        scaffolded_policy_task = build_task_spec_from_intake(policy_intake)
        single_suite = suite_loader.load(single_suite_path)
        multi_suite = suite_loader.load(multi_suite_path)
        extended_suite = suite_loader.load(extended_suite_path)

        self.assertTrue(Path(readme_task.repo_source.path_or_url).exists())
        self.assertTrue(Path(release_task.repo_source.path_or_url).exists())
        self.assertTrue(Path(policy_task.repo_source.path_or_url).exists())
        self.assertEqual(len(single_suite.cases), 1)
        self.assertEqual(len(multi_suite.cases), 2)
        self.assertEqual(len(extended_suite.cases), 3)
        self.assertTrue(Path(single_suite.cases[0].task_spec_ref).exists())
        self.assertTrue(all(Path(case.task_spec_ref).exists() for case in multi_suite.cases))
        self.assertTrue(all(Path(case.task_spec_ref).exists() for case in extended_suite.cases))
        self.assertEqual(len(single_suite.cases[0].run_matrix), 3)
        self.assertTrue(all(len(case.run_matrix) == 3 for case in multi_suite.cases))
        self.assertTrue(all(len(case.run_matrix) == 3 for case in extended_suite.cases))
        self.assertEqual(
            set(release_task.benchmark_metadata.harness_signals),
            {"task_inputs", "multi_file_edit", "verifier_plan"},
        )
        self.assertEqual(
            set(policy_task.benchmark_metadata.harness_signals),
            {"repo_context", "multi_file_edit", "verifier_plan"},
        )
        self.assertEqual(scaffolded_release_task.task_id, 'provider-release-input-sync')
        self.assertEqual(scaffolded_policy_task.task_id, 'provider-policy-bundle-sync')
        self.assertEqual(policy_intake.title, '根据政策资料包同步公告与上线清单')
        self.assertIn('更新 docs/policy_notice.md 和 ops/policy_rollout_checklist.md', policy_intake.business_request)
        self.assertEqual(policy_task.title, '根据政策资料包同步公告与上线清单')
        self.assertIn('公告与上线清单保持一致', policy_task.description)
        self.assertEqual(scaffolded_policy_task.title, '根据政策资料包同步公告与上线清单')
        self.assertIn('公告与清单中的 audience', scaffolded_policy_task.success_criteria.behavioral_checks[0])
        self.assertEqual(scaffolded_release_task.success_criteria.required_verifier_steps, ('release-env-check', 'release-summary-check'))
        self.assertEqual(scaffolded_policy_task.success_criteria.required_verifier_steps, ('policy-notice-check', 'policy-checklist-check'))
        self.assertIn('task_inputs', scaffolded_release_task.benchmark_metadata.harness_signals)
        self.assertIn('multi_file_edit', scaffolded_release_task.benchmark_metadata.harness_signals)
        self.assertIn('verifier_plan', scaffolded_release_task.benchmark_metadata.harness_signals)
        self.assertIn('repo_context', scaffolded_policy_task.benchmark_metadata.harness_signals)
        self.assertIn('multi_file_edit', scaffolded_policy_task.benchmark_metadata.harness_signals)
        self.assertIn('verifier_plan', scaffolded_policy_task.benchmark_metadata.harness_signals)


if __name__ == "__main__":
    unittest.main()


