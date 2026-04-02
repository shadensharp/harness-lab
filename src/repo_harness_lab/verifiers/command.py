from __future__ import annotations

from dataclasses import dataclass

from repo_harness_lab.domain.protocols import SandboxBackend
from repo_harness_lab.domain.run_models import RunRequest, WorkspaceSession
from repo_harness_lab.domain.task_spec import FailurePolicy, TaskSpec, VerifierStep
from repo_harness_lab.domain.verifier_models import VerificationEvidence, VerificationStatus, VerifierResult
from repo_harness_lab.shared.clock import utc_now
from repo_harness_lab.verifiers.base import BaseVerifier


@dataclass(slots=True)
class CommandVerifier(BaseVerifier):
    backend: SandboxBackend
    step_names: tuple[str, ...] = ()
    verifier_name: str = "command_verifier"

    def verify(self, task: TaskSpec, request: RunRequest, workspace: WorkspaceSession) -> VerifierResult:
        started_at = utc_now()
        selected_steps = self._select_steps(task)
        if not selected_steps:
            return VerifierResult(
                verifier_name=self.verifier_name,
                status=VerificationStatus.SKIPPED,
                started_at=started_at,
                finished_at=utc_now(),
                errors=("no verifier steps selected",),
            )

        evidence: list[VerificationEvidence] = []
        command_results = []
        errors: list[str] = []
        failed_required = False
        passed_steps = 0

        for step in selected_steps:
            if not step.command:
                errors.append(f"{step.name}: missing verifier command")
                evidence.append(
                    VerificationEvidence(
                        summary=f"{step.name}: missing command",
                        details={"required": step.required},
                    )
                )
                failed_required = failed_required or step.required
                if step.required and task.verifier_plan.failure_policy is FailurePolicy.STOP_ON_FIRST_FAILURE:
                    break
                continue

            result = self.backend.run_command(workspace, step.command)
            command_results.append(result)
            passed = result.exit_code == 0
            if passed:
                passed_steps += 1
            else:
                errors.append(f"{step.name}: command exited with code {result.exit_code}")
                failed_required = failed_required or step.required

            evidence.append(
                VerificationEvidence(
                    summary=f"{step.name}: {'passed' if passed else 'failed'}",
                    details={
                        "required": step.required,
                        "exit_code": result.exit_code,
                        "command": list(step.command),
                    },
                )
            )

            if not passed and step.required and task.verifier_plan.failure_policy is FailurePolicy.STOP_ON_FIRST_FAILURE:
                break

        required_target = self._required_target(task, selected_steps)
        status = VerificationStatus.PASSED
        if failed_required or passed_steps < required_target:
            status = VerificationStatus.FAILED

        return VerifierResult(
            verifier_name=self.verifier_name,
            status=status,
            evidence=tuple(evidence),
            command_results=tuple(command_results),
            started_at=started_at,
            finished_at=utc_now(),
            errors=tuple(errors),
        )

    def _select_steps(self, task: TaskSpec) -> tuple[VerifierStep, ...]:
        if not self.step_names:
            return task.verifier_plan.steps
        names = set(self.step_names)
        return tuple(step for step in task.verifier_plan.steps if step.name in names)

    def _required_target(self, task: TaskSpec, selected_steps: tuple[VerifierStep, ...]) -> int:
        if task.verifier_plan.required_passes is not None and not self.step_names:
            return task.verifier_plan.required_passes
        return sum(1 for step in selected_steps if step.required)
