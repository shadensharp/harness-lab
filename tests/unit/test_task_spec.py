from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.task_spec import (
    FailurePolicy,
    RepoSource,
    RepoSourceKind,
    TaskDifficulty,
    TaskSelectionTier,
    TaskSpec,
    TaskType,
    VerifierPlan,
    VerifierStep,
    VerifierStepKind,
)


class TaskSpecTests(unittest.TestCase):
    def test_task_spec_uses_domain_defaults(self) -> None:
        task = TaskSpec(
            task_id="task-001",
            title="Fix failing tests",
            description="Stabilize the repository after a regression.",
            task_type=TaskType.BUG_FIX,
            repo_source=RepoSource(
                kind=RepoSourceKind.LOCAL_PATH,
                path_or_url="E:/repo-harness-lab",
            ),
        )

        self.assertTrue(task.inputs.is_empty)
        self.assertFalse(task.constraints.allow_network)
        self.assertEqual(task.success_criteria.required_verifier_steps, ())
        self.assertEqual(task.verifier_step_names, ())
        self.assertEqual(task.benchmark_metadata.tier, TaskSelectionTier.OPEN)
        self.assertEqual(task.benchmark_metadata.difficulty, TaskDifficulty.MEDIUM)
        self.assertEqual(task.benchmark_metadata.tags, ())

    def test_verifier_plan_derives_required_passes_from_required_steps(self) -> None:
        plan = VerifierPlan(
            steps=(
                VerifierStep(name="pytest", kind=VerifierStepKind.TEST, required=True),
                VerifierStep(name="lint", kind=VerifierStepKind.LINT, required=False),
            ),
            failure_policy=FailurePolicy.COLLECT_ALL,
        )

        self.assertEqual(plan.effective_required_passes, 1)

    def test_verifier_plan_rejects_invalid_required_pass_count(self) -> None:
        with self.assertRaises(ValueError):
            VerifierPlan(
                steps=(VerifierStep(name="pytest", kind=VerifierStepKind.TEST),),
                required_passes=2,
            )


if __name__ == "__main__":
    unittest.main()
