from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from repo_harness_lab.agents.base import AgentExecutionError, BaseAgentAdapter
from repo_harness_lab.agents.providers.base import ModelMessage, ModelMessageRole, ProviderRequestError, TextGenerationProvider
from repo_harness_lab.domain.run_models import AgentExecutionResult, CostSummary, RunRequest, WorkspaceSession
from repo_harness_lab.domain.task_spec import HarnessProfile, TaskInputKind, TaskSpec
from repo_harness_lab.domain.trace_models import EventType, RunStage
from repo_harness_lab.traces.events import new_trace_event


IGNORED_PARTS = {".git", "__pycache__"}
IGNORED_SUFFIXES = {".pyc"}
BINARY_SENTINEL = b"\x00"
DEFAULT_SYSTEM_PROMPT = (
    "You are a repository task execution model inside a harness. "
    "Return only valid JSON with keys summary and writes. "
    "Each write must contain path and full file content. "
    "Do not wrap the JSON in markdown fences."
)


@dataclass(frozen=True, slots=True)
class SnapshotSettings:
    include_tree: bool
    include_inputs: bool
    include_verifier_plan: bool
    max_context_files: int
    max_file_chars: int
    max_tree_entries: int = 200


@dataclass(frozen=True, slots=True)
class WorkspacePromptSnapshot:
    prompt_text: str
    tree_entry_count: int
    context_file_count: int
    truncated_file_count: int
    includes_repo_tree: bool
    selected_context_files: tuple[str, ...]
    included_input_names: tuple[str, ...]
    included_verifier_steps: tuple[str, ...]
    shared_prompt_sections: tuple[str, ...] = (
        "task_brief",
        "constraints",
        "success_criteria",
        "response_contract",
    )


@dataclass(slots=True)
class StructuredEditAgentAdapter(BaseAgentAdapter):
    provider: TextGenerationProvider
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    def execute(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession,
    ) -> AgentExecutionResult:
        harness_profile = _resolve_harness_profile(request)
        metadata = dict(request.agent_profile.metadata)
        snapshot = self._build_snapshot(task, workspace.repo_root, harness_profile, metadata)
        response = self._generate_response(task, request, workspace, harness_profile, snapshot)

        try:
            response_payload = _parse_response_payload(response.content)
            summary_note, writes = _extract_writes(response_payload)
            applied_paths = tuple(self._apply_write(task, workspace.repo_root, item) for item in writes)
        except (TypeError, ValueError) as exc:
            raise AgentExecutionError(f"provider response parsing failed for run {request.run_id}: {exc}") from exc

        provider_name = request.agent_profile.provider or self.provider.__class__.__name__
        response_model = response.model or getattr(self.provider, "model", None)
        notes = (summary_note,) if summary_note else ()
        events = (
            new_trace_event(
                request.run_id,
                event_type=EventType.MODEL_REQUESTED,
                stage=RunStage.AGENT,
                payload={
                    "provider": provider_name,
                    "model": response_model,
                    "harness_profile": harness_profile.value,
                    "context_file_count": snapshot.context_file_count,
                    "tree_entry_count": snapshot.tree_entry_count,
                    "truncated_file_count": snapshot.truncated_file_count,
                    "includes_repo_tree": snapshot.includes_repo_tree,
                    "selected_context_files": list(snapshot.selected_context_files),
                    "included_input_names": list(snapshot.included_input_names),
                    "included_verifier_steps": list(snapshot.included_verifier_steps),
                    "shared_prompt_sections": list(snapshot.shared_prompt_sections),
                },
            ),
            new_trace_event(
                request.run_id,
                event_type=EventType.MODEL_RESPONDED,
                stage=RunStage.AGENT,
                payload={
                    "provider": provider_name,
                    "model": response_model,
                    "finish_reason": response.finish_reason,
                    "write_count": len(applied_paths),
                    "applied_paths": list(applied_paths),
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            ),
        )
        return AgentExecutionResult(
            cost_summary=CostSummary(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                total_cost_usd=response.usage.total_cost_usd,
            ),
            notes=notes,
            events=events,
        )

    def _generate_response(
        self,
        task: TaskSpec,
        request: RunRequest,
        workspace: WorkspaceSession,
        harness_profile: HarnessProfile,
        snapshot: WorkspacePromptSnapshot,
    ):
        user_prompt = self._build_user_prompt(task, request, workspace.repo_root, harness_profile, snapshot.prompt_text)
        try:
            return self.provider.generate(
                (
                    ModelMessage(role=ModelMessageRole.SYSTEM, content=self.system_prompt),
                    ModelMessage(role=ModelMessageRole.USER, content=user_prompt),
                )
            )
        except ProviderRequestError as exc:
            raise AgentExecutionError(f"provider request failed for run {request.run_id}: {exc}") from exc

    def _build_snapshot(
        self,
        task: TaskSpec,
        repo_root: Path,
        harness_profile: HarnessProfile,
        metadata: Mapping[str, Any],
    ) -> WorkspacePromptSnapshot:
        settings = _snapshot_settings(harness_profile, metadata)
        tree_entries = _workspace_tree(repo_root, max_entries=settings.max_tree_entries) if settings.include_tree else ()
        tree_section = ""
        if tree_entries:
            tree_section = "\n".join(["Repository tree:", *[f"- {entry}" for entry in tree_entries]])

        file_sections: list[str] = []
        truncated_file_count = 0
        selected_context_files: list[str] = []
        if settings.max_context_files > 0:
            selected_paths = _select_context_files(task, repo_root, max_files=settings.max_context_files)
            for path in selected_paths:
                relative = path.relative_to(repo_root).as_posix()
                selected_context_files.append(relative)
                content, truncated = _read_text_context(path, settings.max_file_chars)
                if truncated:
                    truncated_file_count += 1
                file_sections.append(
                    "\n".join(
                        [
                            f"File: {relative}",
                            "```text",
                            content,
                            "```",
                        ]
                    )
                )

        input_section = ""
        if settings.include_inputs and not task.inputs.is_empty:
            rendered_inputs = []
            for item in task.inputs.items:
                line = f"- {item.name} ({item.kind.value})"
                if item.description:
                    line += f": {item.description}"
                if item.kind is TaskInputKind.TEXT and item.content:
                    line += f"\n  content: {item.content}"
                rendered_inputs.append(line)
            input_section = "\n".join(["Task inputs:", *rendered_inputs])

        verifier_section = ""
        if settings.include_verifier_plan and task.verifier_plan.steps:
            rendered_steps = []
            for step in task.verifier_plan.steps:
                command_text = " ".join(step.command) if step.command else ""
                rendered = f"- {step.name} ({step.kind.value})"
                if command_text:
                    rendered += f": {command_text}"
                rendered_steps.append(rendered)
            verifier_section = "\n".join(["Verifier plan:", *rendered_steps])

        sections = [section for section in (tree_section, input_section, verifier_section, "\n\n".join(file_sections)) if section]
        prompt_text = "\n\n".join(sections)
        return WorkspacePromptSnapshot(
            prompt_text=prompt_text,
            tree_entry_count=len(tree_entries),
            context_file_count=len(file_sections),
            truncated_file_count=truncated_file_count,
            includes_repo_tree=settings.include_tree,
            selected_context_files=tuple(selected_context_files),
            included_input_names=tuple(item.name for item in task.inputs.items) if settings.include_inputs else (),
            included_verifier_steps=tuple(step.name for step in task.verifier_plan.steps) if settings.include_verifier_plan else (),
        )

    def _build_user_prompt(
        self,
        task: TaskSpec,
        request: RunRequest,
        repo_root: Path,
        harness_profile: HarnessProfile,
        workspace_context: str,
    ) -> str:
        success_criteria = []
        if task.success_criteria.required_verifier_steps:
            success_criteria.append(
                f"required_verifier_steps={', '.join(task.success_criteria.required_verifier_steps)}"
            )
        if task.success_criteria.changed_files:
            success_criteria.append(f"changed_files={', '.join(task.success_criteria.changed_files)}")
        if task.success_criteria.behavioral_checks:
            success_criteria.append(
                f"behavioral_checks={'; '.join(task.success_criteria.behavioral_checks)}"
            )

        constraint_lines = [
            f"allow_network={task.constraints.allow_network}",
            f"editable_paths={', '.join(task.constraints.editable_paths) or '<any>'}",
            f"forbidden_paths={', '.join(task.constraints.forbidden_paths) or '<none>'}",
            f"allowed_tools={', '.join(task.constraints.allowed_tools) or '<none>'}",
        ]
        if task.constraints.max_runtime_seconds is not None:
            constraint_lines.append(f"max_runtime_seconds={task.constraints.max_runtime_seconds}")
        if task.constraints.max_cost_usd is not None:
            constraint_lines.append(f"max_cost_usd={task.constraints.max_cost_usd}")

        labels_text = ", ".join(request.labels) or "<none>"
        success_text = "\n".join(f"- {item}" for item in success_criteria) or "- <none>"
        context_text = workspace_context or "No repository context was attached for this harness profile."
        return "\n\n".join(
            [
                "Repository task:",
                f"- task_id: {task.task_id}",
                f"- title: {task.title}",
                f"- task_type: {task.task_type.value}",
                f"- harness_profile: {harness_profile.value}",
                f"- repo_root: {repo_root}",
                f"- agent_labels: {labels_text}",
                "Description:",
                task.description,
                "Constraints:",
                "\n".join(f"- {item}" for item in constraint_lines),
                "Success criteria:",
                success_text,
                "Response contract:",
                "Return JSON only with this shape:",
                '{"summary": "short explanation", "writes": [{"path": "relative/path", "content": "full file content"}]}',
                "Use relative repository paths. For modified files, return the full updated file content.",
                context_text,
            ]
        )

    def _apply_write(self, task: TaskSpec, repo_root: Path, item: Mapping[str, Any]) -> str:
        relative_path = _normalize_relative_path(item.get("path"))
        if not relative_path:
            raise ValueError("write action path must not be empty")
        if not _is_edit_allowed(relative_path, task):
            raise AgentExecutionError(f"write action is not allowed for path: {relative_path}")

        target = (repo_root / Path(relative_path)).resolve()
        if not _is_within_workspace(target, repo_root.resolve()):
            raise AgentExecutionError(f"write action escaped workspace: {relative_path}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("content", "")), encoding="utf8")
        return relative_path



def _resolve_harness_profile(request: RunRequest) -> HarnessProfile:
    eval_context = request.metadata.get("eval_context")
    if isinstance(eval_context, Mapping) and eval_context.get("harness_profile"):
        return HarnessProfile(str(eval_context["harness_profile"]))
    direct = request.metadata.get("harness_profile")
    if direct:
        return HarnessProfile(str(direct))
    metadata_profile = request.agent_profile.metadata.get("harness_profile")
    if metadata_profile:
        return HarnessProfile(str(metadata_profile))
    return HarnessProfile.CUSTOM



def _snapshot_settings(harness_profile: HarnessProfile, metadata: Mapping[str, Any]) -> SnapshotSettings:
    defaults = {
        HarnessProfile.BARE: SnapshotSettings(
            include_tree=True,
            include_inputs=False,
            include_verifier_plan=False,
            max_context_files=0,
            max_file_chars=0,
        ),
        HarnessProfile.BASIC: SnapshotSettings(
            include_tree=True,
            include_inputs=False,
            include_verifier_plan=False,
            max_context_files=4,
            max_file_chars=4000,
        ),
        HarnessProfile.FULL: SnapshotSettings(
            include_tree=True,
            include_inputs=True,
            include_verifier_plan=True,
            max_context_files=12,
            max_file_chars=8000,
        ),
        HarnessProfile.CUSTOM: SnapshotSettings(
            include_tree=True,
            include_inputs=True,
            include_verifier_plan=False,
            max_context_files=6,
            max_file_chars=6000,
        ),
    }
    base = defaults[harness_profile]
    return SnapshotSettings(
        include_tree=_bool_override(metadata, "include_tree", base.include_tree),
        include_inputs=_bool_override(metadata, "include_inputs", base.include_inputs),
        include_verifier_plan=_bool_override(metadata, "include_verifier_plan", base.include_verifier_plan),
        max_context_files=_int_override(metadata, "max_context_files", base.max_context_files),
        max_file_chars=_int_override(metadata, "max_file_chars", base.max_file_chars),
        max_tree_entries=_int_override(metadata, "max_tree_entries", base.max_tree_entries),
    )



def _workspace_tree(repo_root: Path, *, max_entries: int) -> tuple[str, ...]:
    entries = [path.relative_to(repo_root).as_posix() for path in _iter_workspace_files(repo_root)]
    visible = entries[:max_entries]
    if len(entries) > max_entries:
        visible.append(f"... {len(entries) - max_entries} more files")
    return tuple(visible)



def _select_context_files(task: TaskSpec, repo_root: Path, *, max_files: int) -> tuple[Path, ...]:
    candidates = list(_iter_workspace_files(repo_root))
    preferred_context_paths = _preferred_context_paths(task)
    success_targets = {PurePosixPath(item).as_posix() for item in task.success_criteria.changed_files if item}
    editable_prefixes = [PurePosixPath(item).as_posix() for item in task.constraints.editable_paths if item]

    def sort_key(path: Path) -> tuple[int, int, int, str]:
        relative = path.relative_to(repo_root).as_posix()
        preferred = 0 if any(_path_matches_prefix(relative, prefix) for prefix in preferred_context_paths) else 1
        exact = 0 if relative in success_targets else 1
        editable = 0 if any(_path_matches_prefix(relative, prefix) for prefix in editable_prefixes) else 1
        return (preferred, exact, editable, relative)

    return tuple(sorted(candidates, key=sort_key)[:max_files])


def _preferred_context_paths(task: TaskSpec) -> tuple[str, ...]:
    raw = task.metadata.get('context_paths') if isinstance(task.metadata, Mapping) else ()
    if isinstance(raw, str):
        values = (raw,)
    else:
        values = raw or ()
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        path = _normalize_relative_path(item)
        if not path or path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    return tuple(normalized)



def _iter_workspace_files(repo_root: Path):
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(repo_root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if relative.suffix in IGNORED_SUFFIXES:
            continue
        if _is_binary(path):
            continue
        yield path



def _is_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        sample = handle.read(4096)
    return BINARY_SENTINEL in sample



def _read_text_context(path: Path, max_chars: int) -> tuple[str, bool]:
    text = path.read_text(encoding="utf8", errors="replace")
    if len(text) <= max_chars:
        return text, False
    return f"{text[:max_chars]}\n... <truncated>", True



def _parse_response_payload(content: str) -> Mapping[str, Any]:
    candidate = content.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].startswith("```"):
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or start >= end:
            raise ValueError("response was not valid JSON")
        payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, Mapping):
        raise ValueError("response JSON must be an object")
    return dict(payload)



def _extract_writes(payload: Mapping[str, Any]) -> tuple[str | None, tuple[Mapping[str, Any], ...]]:
    summary = payload.get("summary")
    writes_payload = payload.get("writes")
    if writes_payload is None and isinstance(payload.get("actions"), list):
        writes_payload = [item for item in payload["actions"] if str(item.get("type", "write_file")) == "write_file"]
    if writes_payload is None:
        writes_payload = []
    if not isinstance(writes_payload, list):
        raise ValueError("writes must be a list")
    writes: list[Mapping[str, Any]] = []
    for item in writes_payload:
        if not isinstance(item, Mapping):
            raise ValueError("each write must be an object")
        if "path" not in item:
            raise ValueError("each write must include path")
        writes.append(dict(item))
    summary_text = str(summary).strip() if summary is not None else None
    return summary_text or None, tuple(writes)



def _normalize_relative_path(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().replace("\\", "/")
    if not text:
        return ""
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        return ""
    if pure.as_posix() == ".":
        return ""
    return pure.as_posix()



def _is_edit_allowed(relative_path: str, task: TaskSpec) -> bool:
    forbidden = [_normalize_relative_path(item) for item in task.constraints.forbidden_paths if item]
    if any(_path_matches_prefix(relative_path, prefix) for prefix in forbidden if prefix):
        return False
    editable = [_normalize_relative_path(item) for item in task.constraints.editable_paths if item]
    if not editable:
        return True
    return any(_path_matches_prefix(relative_path, prefix) for prefix in editable if prefix)



def _path_matches_prefix(relative_path: str, prefix: str) -> bool:
    target = PurePosixPath(relative_path)
    root = PurePosixPath(prefix)
    target_parts = target.parts
    root_parts = root.parts
    if len(root_parts) > len(target_parts):
        return False
    return target_parts[: len(root_parts)] == root_parts



def _is_within_workspace(target: Path, workspace_root: Path) -> bool:
    try:
        target.relative_to(workspace_root)
    except ValueError:
        return False
    return True



def _bool_override(metadata: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in metadata:
        return default
    value = metadata[key]
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)



def _int_override(metadata: Mapping[str, Any], key: str, default: int) -> int:
    if key not in metadata:
        return default
    return int(metadata[key])
