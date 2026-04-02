from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from repo_harness_lab.domain.eval_models import EvalCase, EvalRunConfig, EvalSuite
from repo_harness_lab.domain.run_models import (
    AgentProfile,
    BudgetPolicy,
    RunRequest,
    SandboxProfile,
    TimeoutPolicy,
    ToolPolicy,
)
from repo_harness_lab.domain.task_spec import HarnessProfile


class JsonEvalSuiteLoader:
    def load(self, source: str | Path) -> EvalSuite:
        path = Path(source).resolve()
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return parse_eval_suite(payload, base_dir=path.parent)



def parse_eval_suite(data: Mapping[str, Any], *, base_dir: Path | None = None) -> EvalSuite:
    suite = EvalSuite(
        suite_id=str(data["suite_id"]),
        cases=tuple(_parse_eval_case(_mapping(item), base_dir=base_dir) for item in data.get("cases", ())),
        notes=_tuple_of_str(data.get("notes")),
    )
    validate_eval_suite(suite)
    return suite



def validate_eval_suite(suite: EvalSuite) -> None:
    errors: list[str] = []
    if not suite.suite_id.strip():
        errors.append("suite_id must not be empty")

    seen_case_ids: set[str] = set()
    for case in suite.cases:
        if not case.case_id.strip():
            errors.append("case_id must not be empty")
        elif case.case_id in seen_case_ids:
            errors.append(f"duplicate case_id: {case.case_id}")
        else:
            seen_case_ids.add(case.case_id)

        if not case.task_spec_ref.strip():
            errors.append(f"case {case.case_id or '<unknown>'} must define task_spec_ref")
        if not case.run_matrix:
            errors.append(f"case {case.case_id or '<unknown>'} must define at least one run config")

        seen_labels: set[str] = set()
        for config in case.run_matrix:
            if not config.label.strip():
                errors.append(f"case {case.case_id or '<unknown>'} has an empty run label")
            elif config.label in seen_labels:
                errors.append(f"case {case.case_id or '<unknown>'} has duplicate run label: {config.label}")
            else:
                seen_labels.add(config.label)

    if errors:
        raise ValueError("; ".join(errors))



def _parse_eval_case(data: Mapping[str, Any], *, base_dir: Path | None) -> EvalCase:
    task_spec_ref = str(data["task_spec_ref"])
    task_path = Path(task_spec_ref)
    if base_dir is not None and not task_path.is_absolute():
        task_path = (base_dir / task_path).resolve()

    return EvalCase(
        case_id=str(data["case_id"]),
        task_spec_ref=str(task_path),
        run_matrix=tuple(_parse_eval_run_config(_mapping(item)) for item in data.get("run_matrix", ())),
        notes=_tuple_of_str(data.get("notes")),
    )



def _parse_eval_run_config(data: Mapping[str, Any]) -> EvalRunConfig:
    return EvalRunConfig(
        label=str(data["label"]),
        request=_parse_run_request(data.get("request")),
        harness_profile=HarnessProfile(data.get("harness_profile", HarnessProfile.CUSTOM.value)),
    )



def _parse_run_request(data: Any) -> RunRequest:
    payload = _mapping(data)
    return RunRequest(
        run_id=str(payload.get("run_id", "")),
        task_id=str(payload.get("task_id", "")),
        agent_profile=_parse_agent_profile(payload.get("agent_profile")),
        sandbox_profile=_parse_sandbox_profile(payload.get("sandbox_profile")),
        budget_policy=_parse_budget_policy(payload.get("budget_policy")),
        timeout_policy=_parse_timeout_policy(payload.get("timeout_policy")),
        tool_policy=_parse_tool_policy(payload.get("tool_policy")),
        labels=_tuple_of_str(payload.get("labels")),
        metadata=_mapping(payload.get("metadata")),
    )



def _parse_agent_profile(data: Any) -> AgentProfile:
    payload = _mapping(data)
    provider = _optional_str(payload.get("provider"))
    return AgentProfile(
        name=str(payload.get("name", provider or "noop-agent")),
        provider=provider,
        version=_optional_str(payload.get("version")),
        metadata=_mapping(payload.get("metadata")),
    )



def _parse_sandbox_profile(data: Any) -> SandboxProfile:
    payload = _mapping(data)
    return SandboxProfile(
        backend_name=str(payload.get("backend_name", "local")),
        environment={str(key): str(value) for key, value in _mapping(payload.get("environment")).items()},
        read_only_paths=_tuple_of_str(payload.get("read_only_paths")),
        install_dependencies=bool(payload.get("install_dependencies", False)),
    )



def _parse_budget_policy(data: Any) -> BudgetPolicy:
    payload = _mapping(data)
    return BudgetPolicy(
        max_steps=_optional_int(payload.get("max_steps")),
        max_tokens=_optional_int(payload.get("max_tokens")),
        max_cost_usd=_optional_float(payload.get("max_cost_usd")),
    )



def _parse_timeout_policy(data: Any) -> TimeoutPolicy:
    payload = _mapping(data)
    return TimeoutPolicy(
        run_timeout_seconds=_optional_int(payload.get("run_timeout_seconds")),
        command_timeout_seconds=_optional_int(payload.get("command_timeout_seconds")),
    )



def _parse_tool_policy(data: Any) -> ToolPolicy:
    payload = _mapping(data)
    return ToolPolicy(
        allow_shell=bool(payload.get("allow_shell", True)),
        allow_network=bool(payload.get("allow_network", False)),
        allowed_tools=_tuple_of_str(payload.get("allowed_tools")),
        blocked_tools=_tuple_of_str(payload.get("blocked_tools")),
    )



def _mapping(data: Any) -> Mapping[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TypeError(f"expected mapping, got {type(data).__name__}")
    return dict(data)



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
