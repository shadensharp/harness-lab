from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.domain.task_spec import (
    RepoSource,
    RepoSourceKind,
    SuccessCriteria,
    TaskSpec,
    TaskType,
    VerifierPlan,
    VerifierStep,
    VerifierStepKind,
)
from repo_harness_lab.tasks.loader import JsonTaskLoader
from repo_harness_lab.tasks.validator import TaskValidationError, validate_task_spec


class TaskValidatorTests(unittest.TestCase):
    def test_validate_task_spec_rejects_unknown_required_verifier_step(self) -> None:
        task = TaskSpec(
            task_id="task-001",
            title="Invalid task",
            description="This task references a missing verifier step.",
            task_type=TaskType.REQUIREMENT_CHANGE,
            repo_source=RepoSource(kind=RepoSourceKind.LOCAL_PATH, path_or_url="E:/repo-harness-lab"),
            success_criteria=SuccessCriteria(required_verifier_steps=("missing-step",)),
            verifier_plan=VerifierPlan(
                steps=(VerifierStep(name="unit-tests", kind=VerifierStepKind.TEST, command=("python", "-V")),),
            ),
        )

        with self.assertRaises(TaskValidationError):
            validate_task_spec(task)

    def test_loader_runs_validation_and_raises_for_invalid_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            task_path = Path(temp_root) / "invalid-task.json"
            task_path.write_text(
                json.dumps(
                    {
                        "task_id": "task-001",
                        "title": "Invalid task",
                        "description": "Broken verifier references",
                        "task_type": "requirement_change",
                        "repo_source": {
                            "kind": "local_path",
                            "path_or_url": "E:/repo-harness-lab",
                            "checkout_mode": "copy"
                        },
                        "success_criteria": {
                            "required_verifier_steps": ["missing-step"]
                        },
                        "verifier_plan": {
                            "steps": [
                                {
                                    "name": "unit-tests",
                                    "kind": "test",
                                    "command": ["python", "-V"]
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf8",
            )

            with self.assertRaises(TaskValidationError):
                JsonTaskLoader().load(task_path)


if __name__ == "__main__":
    unittest.main()
