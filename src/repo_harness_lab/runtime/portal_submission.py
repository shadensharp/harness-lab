from __future__ import annotations

import hashlib
import re
import sys
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repo_harness_lab.config.settings import Settings, load_settings
from repo_harness_lab.domain.task_spec import (
    RepoCheckoutMode,
    RepoSource,
    RepoSourceKind,
    TaskBenchmarkMetadata,
    TaskDifficulty,
    TaskSelectionTier,
    TaskType,
    VerifierStep,
    VerifierStepKind,
)
from repo_harness_lab.runtime.repo_sources import infer_repo_source_kind, is_http_remote_git_url, materialize_repo_source
from repo_harness_lab.shared.files import remove_directory
from repo_harness_lab.tasks.intake import TaskIntake, validate_task_intake
from repo_harness_lab.verifiers.draft_completion import DRAFT_COMPLETION_STEP_NAME

PORTAL_MODE_EXAMPLE = "example_template"
PORTAL_MODE_STRUCTURED = "structured_custom"
PORTAL_MODE_FREEFORM = "freeform_draft"
PORTAL_TEMPLATE_REPO_TOKEN = "example://template-repo"
PORTAL_TASK_SHAPE_GENERAL = "general"
PORTAL_TASK_SHAPE_DOC_UPDATE = "doc_update"
PORTAL_TASK_SHAPE_CONFIG_SYNC = "config_sync"
PORTAL_TASK_SHAPE_BUG_FIX = "bug_fix"
PORTAL_TASK_SHAPE_MULTI_FILE_SYNC = "multi_file_sync"
PORTAL_KNOWLEDGE_PACK_NONE = "none"
PORTAL_KNOWLEDGE_PACK_REPO_OVERVIEW = "repo_overview"
PORTAL_KNOWLEDGE_PACK_POLICY_BUNDLE = "policy_bundle"
PORTAL_KNOWLEDGE_PACK_RELEASE_BUNDLE = "release_bundle"
PORTAL_KNOWLEDGE_PACK_CODE_AND_TESTS = "code_and_tests"

_PATH_HINT_PATTERN = re.compile(r"(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+")
_COMMON_CONTEXT_HINTS = (
    "README.md",
    "docs",
    "src",
    "tests",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
)
_KEYWORD_CONTEXT_HINTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("readme",), ("README.md",)),
    (("docs", "doc", "\u6587\u6863"), ("docs", "README.md")),
    (("test", "tests", "\u6d4b\u8bd5"), ("tests",)),
    (("config", "\u914d\u7f6e"), ("config", "package.json", "pyproject.toml", "requirements.txt")),
    (("api",), ("src", "app", "server")),
)
_PORTAL_TASK_SHAPE_DEFAULT = PORTAL_TASK_SHAPE_GENERAL
_PORTAL_TASK_SHAPE_PROFILES: dict[str, dict[str, object]] = {
    PORTAL_TASK_SHAPE_GENERAL: {
        "label": "\u901a\u7528\u4efb\u52a1",
        "description": "\u4e0d\u989d\u5916\u5047\u8bbe\u4efb\u52a1\u5f62\u6001\uff0c\u4e3b\u8981\u6839\u636e\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u7ed3\u6784\u8349\u62df\u8fb9\u754c\u3002",
        "task_type": TaskType.REQUIREMENT_CHANGE,
        "context_hints": (),
        "editable_hints": (),
        "expected_file_hints": (),
        "behavioral_hint": "\u4fee\u6539\u8303\u56f4\u5e94\u805a\u7126\u4efb\u52a1\u6b63\u6587\uff0c\u907f\u514d\u6269\u6563\u5230\u65e0\u5173\u76ee\u5f55\u3002",
    },
    PORTAL_TASK_SHAPE_DOC_UPDATE: {
        "label": "\u6587\u6863\u66f4\u65b0",
        "description": "\u66f4\u504f\u5411 README\u3001docs \u6216\u8fd0\u8425\u6750\u6599\u7684\u6587\u5b57\u7c7b\u6539\u52a8\u3002",
        "task_type": TaskType.REQUIREMENT_CHANGE,
        "context_hints": ("README.md", "docs"),
        "editable_hints": ("README.md", "docs"),
        "expected_file_hints": ("README.md", "docs"),
        "behavioral_hint": "\u6587\u6863\u6539\u52a8\u5e94\u4fdd\u6301\u6807\u9898\u3001\u672f\u8bed\u3001\u65e5\u671f\u548c\u793a\u4f8b\u8868\u8fbe\u4e00\u81f4\uff0c\u4e0d\u5f15\u5165\u4e0e\u4efb\u52a1\u65e0\u5173\u7684\u5b9e\u73b0\u4fee\u6539\u3002",
    },
    PORTAL_TASK_SHAPE_CONFIG_SYNC: {
        "label": "\u914d\u7f6e\u540c\u6b65",
        "description": "\u66f4\u504f\u5411 env\u3001package/pyproject\u3001CI \u6216 config \u76ee\u5f55\u4e0b\u7684\u914d\u7f6e\u6539\u52a8\u3002",
        "task_type": TaskType.REQUIREMENT_CHANGE,
        "context_hints": ("config", "configs", ".github", "pyproject.toml", "package.json", "requirements.txt", "Cargo.toml", "go.mod"),
        "editable_hints": ("config", "configs", ".github", "pyproject.toml", "package.json", "requirements.txt", "Cargo.toml", "go.mod"),
        "expected_file_hints": ("pyproject.toml", "package.json", "requirements.txt", "Cargo.toml", "go.mod", "config", "configs", ".github"),
        "behavioral_hint": "\u914d\u7f6e\u7c7b\u6539\u52a8\u5e94\u4fdd\u6301\u76ee\u6807\u914d\u7f6e\u952e\u548c\u53d6\u503c\u4e00\u81f4\uff0c\u907f\u514d\u8fde\u5e26\u4fee\u6539\u65e0\u5173\u8fd0\u884c\u53c2\u6570\u3002",
    },
    PORTAL_TASK_SHAPE_BUG_FIX: {
        "label": "\u7f3a\u9677\u4fee\u590d",
        "description": "\u66f4\u504f\u5411\u4fee\u590d\u62a5\u9519\u3001\u5931\u8d25\u573a\u666f\u6216\u56de\u5f52\u95ee\u9898\u3002",
        "task_type": TaskType.BUG_FIX,
        "context_hints": ("src", "app", "server", "tests"),
        "editable_hints": ("src", "app", "server", "tests"),
        "expected_file_hints": ("tests", "src", "app", "server"),
        "behavioral_hint": "\u4fee\u590d\u5e94\u8986\u76d6\u62a5\u9519\u6216\u5931\u8d25\u573a\u666f\uff0c\u5e76\u907f\u514d\u5f15\u5165\u660e\u663e\u56de\u5f52\u3002",
    },
    PORTAL_TASK_SHAPE_MULTI_FILE_SYNC: {
        "label": "\u591a\u6587\u4ef6\u540c\u6b65",
        "description": "\u9002\u5408\u9700\u8981\u540c\u65f6\u5bf9\u9f50\u591a\u4efd\u6587\u6863\u3001\u914d\u7f6e\u6216\u5b9e\u73b0\u6587\u4ef6\u7684\u4efb\u52a1\u3002",
        "task_type": TaskType.REQUIREMENT_CHANGE,
        "context_hints": ("README.md", "docs", "src", "tests", "config"),
        "editable_hints": ("README.md", "docs", "src", "tests", "config"),
        "expected_file_hints": ("README.md", "docs", "src", "config"),
        "behavioral_hint": "\u6d89\u53ca\u591a\u6587\u4ef6\u540c\u6b65\u65f6\uff0c\u91cd\u590d\u51fa\u73b0\u7684\u7248\u672c\u3001\u65e5\u671f\u3001\u672f\u8bed\u548c\u914d\u7f6e\u503c\u5e94\u4fdd\u6301\u4e00\u81f4\u3002",
    },
}
_PORTAL_KNOWLEDGE_PACK_DEFAULT = PORTAL_KNOWLEDGE_PACK_NONE
_PORTAL_KNOWLEDGE_PACK_PROFILES: dict[str, dict[str, object]] = {
    PORTAL_KNOWLEDGE_PACK_NONE: {
        "label": "\u4e0d\u989d\u5916\u52a0\u6750\u6599\u5305",
        "description": "\u4e0d\u989d\u5916\u5047\u8bbe\u652f\u6491\u6750\u6599\u7684\u7c7b\u578b\uff0c\u4e3b\u8981\u4f9d\u8d56\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u7ed3\u6784\u3002",
        "context_hints": (),
        "editable_hints": (),
        "expected_file_hints": (),
        "behavioral_hint": "",
    },
    PORTAL_KNOWLEDGE_PACK_REPO_OVERVIEW: {
        "label": "\u4ed3\u5e93\u6982\u89c8\u5305",
        "description": "\u4f18\u5148 README \u548c docs \u8fd9\u7c7b\u603b\u89c8\u6750\u6599\uff0c\u9002\u5408\u5148\u770b\u6574\u4f53\u53e3\u5f84\u7684\u4efb\u52a1\u3002",
        "context_hints": ("README.md", "docs"),
        "editable_hints": ("README.md", "docs"),
        "expected_file_hints": ("README.md", "docs"),
        "behavioral_hint": "\u6d89\u53ca\u4ed3\u5e93\u6982\u89c8\u6750\u6599\u65f6\uff0c\u9996\u9875\u53e3\u5f84\u4e0e docs \u63cf\u8ff0\u5e94\u4fdd\u6301\u4e00\u81f4\u3002",
    },
    PORTAL_KNOWLEDGE_PACK_POLICY_BUNDLE: {
        "label": "\u653f\u7b56\u6750\u6599\u5305",
        "description": "\u4f18\u5148 docs\u3001ops \u548c README \u8fd9\u7c7b\u653f\u7b56\u516c\u544a\u3001\u4e0a\u7ebf\u6e05\u5355\u3001\u8303\u56f4\u8bf4\u660e\u6750\u6599\u3002",
        "context_hints": ("docs", "ops", "README.md"),
        "editable_hints": ("docs", "ops"),
        "expected_file_hints": ("docs", "ops"),
        "behavioral_hint": "\u6d89\u53ca\u653f\u7b56\u6750\u6599\u65f6\uff0c\u516c\u544a\u3001\u8303\u56f4\u3001\u65e5\u671f\u548c\u6267\u884c\u6e05\u5355\u5e94\u4fdd\u6301\u4e00\u81f4\u3002",
    },
    PORTAL_KNOWLEDGE_PACK_RELEASE_BUNDLE: {
        "label": "\u53d1\u5e03\u6750\u6599\u5305",
        "description": "\u4f18\u5148 release summary\u3001CHANGELOG\u3001env/config \u548c\u90e8\u7f72\u6750\u6599\u3002",
        "context_hints": ("docs", "CHANGELOG.md", "release.env", "config", ".github"),
        "editable_hints": ("docs", "CHANGELOG.md", "release.env", "config", ".github"),
        "expected_file_hints": ("docs", "CHANGELOG.md", "release.env", "config", ".github"),
        "behavioral_hint": "\u6d89\u53ca\u53d1\u5e03\u6750\u6599\u65f6\uff0c\u53d1\u5e03\u6458\u8981\u3001\u53d8\u66f4\u5217\u8868\u3001\u73af\u5883\u503c\u548c\u90e8\u7f72\u8bf4\u660e\u5e94\u4fdd\u6301\u5bf9\u9f50\u3002",
    },
    PORTAL_KNOWLEDGE_PACK_CODE_AND_TESTS: {
        "label": "\u4ee3\u7801\u4e0e\u6d4b\u8bd5\u5305",
        "description": "\u4f18\u5148 src\u3001app\u3001server \u548c tests \u8fd9\u7c7b\u5b9e\u73b0\u4e0e\u56de\u5f52\u6750\u6599\u3002",
        "context_hints": ("src", "app", "server", "tests"),
        "editable_hints": ("src", "app", "server", "tests"),
        "expected_file_hints": ("src", "app", "server", "tests"),
        "behavioral_hint": "\u6d89\u53ca\u4ee3\u7801\u4e0e\u6d4b\u8bd5\u65f6\uff0c\u4fee\u6539\u903b\u8f91\u4e0e\u6d4b\u8bd5\u8986\u76d6\u5e94\u4fdd\u6301\u5bf9\u5e94\u5173\u7cfb\u3002",
    },
}


@dataclass(frozen=True, slots=True)
class PortalSubmissionPlan:
    intake: TaskIntake
    form_fields: dict[str, str]
    mode: str
    autogenerated_fields: tuple[str, ...] = ()
    used_draft_verifier: bool = False
    resolved_repo_root: Path | None = None
    cleanup_roots: tuple[Path, ...] = ()


def blank_portal_form_fields() -> dict[str, str]:
    return {
        "title": "",
        "task_text": "",
        "task_shape": _PORTAL_TASK_SHAPE_DEFAULT,
        "knowledge_pack": _PORTAL_KNOWLEDGE_PACK_DEFAULT,
        "repo_path": "",
        "context_paths_text": "",
        "editable_paths_text": "",
        "forbidden_paths_text": "",
        "expected_changed_files_text": "",
        "behavioral_checks_text": "",
        "acceptance_checks_text": "",
    }


def build_portal_form_fields(intake: TaskIntake, *, hide_local_repo_source: bool = False) -> dict[str, str]:
    repo_path = intake.repo_source.path_or_url
    if hide_local_repo_source and intake.repo_source.kind is RepoSourceKind.LOCAL_PATH:
        repo_path = PORTAL_TEMPLATE_REPO_TOKEN
    task_shape = _normalize_task_shape(dict(intake.metadata).get("portal_task_shape"))
    knowledge_pack = _normalize_knowledge_pack(dict(intake.metadata).get("portal_knowledge_pack"))
    return {
        "title": intake.title,
        "task_text": intake.business_request,
        "task_shape": task_shape,
        "knowledge_pack": knowledge_pack,
        "repo_path": repo_path,
        "context_paths_text": _serialize_line_block(intake.context_paths),
        "editable_paths_text": _serialize_line_block(intake.editable_paths),
        "forbidden_paths_text": _serialize_line_block(intake.forbidden_paths),
        "expected_changed_files_text": _serialize_line_block(intake.expected_changed_files),
        "behavioral_checks_text": _serialize_line_block(intake.behavioral_checks),
        "acceptance_checks_text": _serialize_acceptance_checks(intake.acceptance_checks),
    }


def resolve_portal_submission(
    *,
    base_intake: TaskIntake,
    submission: Mapping[str, object],
    template_id: str,
    template_form_defaults: Mapping[str, str],
    submission_id: str | None = None,
    require_task_text: bool = True,
    require_repo_path: bool = True,
    settings: Settings | None = None,
    allow_custom_local_repo_paths: bool = True,
) -> PortalSubmissionPlan:
    task_text = str(submission.get("task_text") or "").strip()
    task_shape = _normalize_task_shape(submission.get("task_shape"))
    knowledge_pack = _normalize_knowledge_pack(submission.get("knowledge_pack"))
    if require_task_text and not task_text:
        raise ValueError("\u8bf7\u5148\u8f93\u5165\u60f3\u6267\u884c\u7684\u4efb\u52a1\u3002")

    repo_source_value = _submitted_repo_source_value(submission)
    if require_repo_path and not repo_source_value:
        raise ValueError("\u8bf7\u5148\u586b\u5199\u8981\u64cd\u4f5c\u7684\u4ed3\u5e93\u6765\u6e90\uff08\u672c\u5730\u8def\u5f84\u6216 Git \u5730\u5740\uff09\u3002")
    if not repo_source_value:
        repo_source_value = base_intake.repo_source.path_or_url
    resolved_repo_source_value = _resolve_submitted_repo_source_value(
        repo_source_value,
        base_repo_source=base_intake.repo_source,
    )
    _validate_submitted_repo_source_value(
        resolved_repo_source_value,
        base_repo_source=base_intake.repo_source,
        allow_custom_local_repo_paths=allow_custom_local_repo_paths,
    )

    task_repo_source, repo_root, cleanup_roots = _materialize_submission_repo_source(
        resolved_repo_source_value,
        base_repo_source=base_intake.repo_source,
        settings=settings,
        template_id=template_id,
        submission_id=submission_id,
    )

    title = str(submission.get("title") or "").strip()
    task_changed = _normalize_freeform_text(task_text) != _normalize_freeform_text(base_intake.business_request)
    template_bound_structure = _is_template_bound_structure(submission, template_form_defaults)
    discard_template_structure = template_bound_structure and task_changed

    context_paths = () if discard_template_structure else _parse_line_block(submission.get("context_paths_text"))
    editable_paths = () if discard_template_structure else _parse_line_block(submission.get("editable_paths_text"))
    forbidden_paths = () if discard_template_structure else _parse_line_block(submission.get("forbidden_paths_text"))
    expected_changed_files = () if discard_template_structure else _parse_line_block(submission.get("expected_changed_files_text"))
    behavioral_checks = () if discard_template_structure else _parse_line_block(submission.get("behavioral_checks_text"))
    acceptance_checks = () if discard_template_structure else _parse_acceptance_checks_text(submission.get("acceptance_checks_text"))

    if not task_changed and template_bound_structure:
        intake = TaskIntake(
            task_id=base_intake.task_id,
            title=title or base_intake.title,
            business_request=base_intake.business_request,
            task_type=base_intake.task_type,
            repo_source=base_intake.repo_source,
            repo_revision=base_intake.repo_revision,
            business_inputs=base_intake.business_inputs,
            context_paths=base_intake.context_paths,
            editable_paths=base_intake.editable_paths,
            forbidden_paths=base_intake.forbidden_paths,
            allowed_tools=base_intake.allowed_tools,
            allow_network=base_intake.allow_network,
            max_runtime_seconds=base_intake.max_runtime_seconds,
            max_cost_usd=base_intake.max_cost_usd,
            expected_changed_files=base_intake.expected_changed_files,
            behavioral_checks=base_intake.behavioral_checks,
            setup_steps=base_intake.setup_steps,
            acceptance_checks=base_intake.acceptance_checks,
            required_passes=base_intake.required_passes,
            failure_policy=base_intake.failure_policy,
            benchmark_metadata=base_intake.benchmark_metadata,
            metadata={
                **dict(base_intake.metadata),
                "portal_live_entry": True,
                "portal_template_id": template_id,
                "portal_submission_id": submission_id,
                "portal_mode": PORTAL_MODE_EXAMPLE,
                "portal_task_shape": task_shape,
                "portal_knowledge_pack": knowledge_pack,
            },
        )
        validate_task_intake(intake)
        return PortalSubmissionPlan(
            intake=intake,
            form_fields=build_portal_form_fields(intake, hide_local_repo_source=not allow_custom_local_repo_paths),
            mode=PORTAL_MODE_EXAMPLE,
            resolved_repo_root=repo_root,
            cleanup_roots=cleanup_roots,
        )

    hinted_paths = _extract_path_hints(task_text, repo_root)
    autogenerated_fields: list[str] = []

    if not title:
        title = _draft_title(task_text, repo_root.name)
    if not expected_changed_files:
        expected_changed_files = _draft_expected_changed_files(repo_root, task_text, hinted_paths, task_shape=task_shape, knowledge_pack=knowledge_pack)
        if expected_changed_files:
            autogenerated_fields.append("expected_changed_files")
    if not editable_paths:
        editable_paths = _draft_editable_paths(repo_root, expected_changed_files or hinted_paths, task_shape=task_shape, knowledge_pack=knowledge_pack)
        if editable_paths:
            autogenerated_fields.append("editable_paths")
    if not context_paths:
        context_paths = _draft_context_paths(repo_root, task_text, hinted_paths, task_shape=task_shape, knowledge_pack=knowledge_pack)
        if context_paths:
            autogenerated_fields.append("context_paths")
    if not behavioral_checks and task_text:
        behavioral_checks = _draft_behavioral_checks(task_text, task_shape=task_shape, knowledge_pack=knowledge_pack)
        autogenerated_fields.append("behavioral_checks")

    used_draft_verifier = False
    if not acceptance_checks:
        acceptance_checks = _draft_acceptance_checks(str(repo_root))
        autogenerated_fields.append("acceptance_checks")
        used_draft_verifier = True

    mode = PORTAL_MODE_FREEFORM if autogenerated_fields else PORTAL_MODE_STRUCTURED
    intake = TaskIntake(
        task_id=_draft_task_id(template_id, title, task_text, task_repo_source.path_or_url, submission_id=submission_id),
        title=title,
        business_request=task_text,
        task_type=_infer_task_type(task_text, task_shape=task_shape),
        repo_source=task_repo_source,
        repo_revision=base_intake.repo_revision,
        business_inputs=base_intake.business_inputs.__class__(),
        context_paths=context_paths,
        editable_paths=editable_paths,
        forbidden_paths=forbidden_paths,
        allowed_tools=base_intake.allowed_tools,
        allow_network=base_intake.allow_network,
        max_runtime_seconds=base_intake.max_runtime_seconds,
        max_cost_usd=base_intake.max_cost_usd,
        expected_changed_files=expected_changed_files,
        behavioral_checks=behavioral_checks,
        setup_steps=base_intake.setup_steps,
        acceptance_checks=acceptance_checks,
        required_passes=None,
        failure_policy=base_intake.failure_policy,
        benchmark_metadata=TaskBenchmarkMetadata(
            tier=TaskSelectionTier.OPEN,
            difficulty=TaskDifficulty.MEDIUM,
            tags=("portal_live", mode, f"task_shape:{task_shape}", f"knowledge_pack:{knowledge_pack}"),
            owner=base_intake.benchmark_metadata.owner,
            source="portal_live",
            notes=("drafted from portal live submission",),
        ),
        metadata={
            "portal_live_entry": True,
            "portal_template_id": template_id,
            "portal_submission_id": submission_id,
            "portal_mode": mode,
            "portal_task_shape": task_shape,
            "portal_knowledge_pack": knowledge_pack,
            "portal_autogenerated_fields": list(autogenerated_fields),
            "portal_used_draft_verifier": used_draft_verifier,
        },
    )
    validate_task_intake(intake)
    return PortalSubmissionPlan(
        intake=intake,
        form_fields=build_portal_form_fields(intake, hide_local_repo_source=not allow_custom_local_repo_paths),
        mode=mode,
        autogenerated_fields=tuple(autogenerated_fields),
        used_draft_verifier=used_draft_verifier,
        resolved_repo_root=repo_root,
        cleanup_roots=cleanup_roots,
    )


def cleanup_portal_submission_plan(plan: PortalSubmissionPlan) -> None:
    for root in plan.cleanup_roots:
        remove_directory(root)


def _materialize_submission_repo_source(
    repo_source_value: str,
    *,
    base_repo_source: RepoSource,
    settings: Settings | None,
    template_id: str,
    submission_id: str | None,
) -> tuple[RepoSource, Path, tuple[Path, ...]]:
    task_repo_source = _coerce_repo_source(repo_source_value, base_repo_source=base_repo_source)
    materialized = materialize_repo_source(
        task_repo_source,
        settings=settings or load_settings(),
        temp_label=f"portal-{submission_id or template_id}",
    )
    cleanup_roots = (materialized.cleanup_root,) if materialized.cleanup_root is not None else ()
    return task_repo_source, materialized.repo_root.resolve(), cleanup_roots


def _coerce_repo_source(repo_source_value: str, *, base_repo_source: RepoSource) -> RepoSource:
    normalized_value = str(repo_source_value).strip()
    source_kind = infer_repo_source_kind(normalized_value)
    if source_kind is RepoSourceKind.LOCAL_PATH:
        return RepoSource(
            kind=RepoSourceKind.LOCAL_PATH,
            path_or_url=str(Path(normalized_value).resolve()),
            default_branch=base_repo_source.default_branch,
            checkout_mode=RepoCheckoutMode.COPY,
        )
    return RepoSource(
        kind=RepoSourceKind.GIT_URL,
        path_or_url=normalized_value,
        default_branch="",
        checkout_mode=RepoCheckoutMode.COPY,
    )


def _submitted_repo_source_value(submission: Mapping[str, object]) -> str:
    return str(submission.get("repo_source") or submission.get("repo_path") or "").strip()


def _resolve_submitted_repo_source_value(repo_source_value: str, *, base_repo_source: RepoSource) -> str:
    normalized_value = str(repo_source_value).strip()
    if normalized_value == PORTAL_TEMPLATE_REPO_TOKEN:
        return base_repo_source.path_or_url
    return normalized_value


def _validate_submitted_repo_source_value(
    repo_source_value: str,
    *,
    base_repo_source: RepoSource,
    allow_custom_local_repo_paths: bool,
) -> None:
    normalized_value = str(repo_source_value).strip()
    if not normalized_value or allow_custom_local_repo_paths:
        return
    if normalized_value == str(base_repo_source.path_or_url).strip():
        return
    if is_http_remote_git_url(normalized_value):
        return
    raise ValueError(
        "\u5f53\u524d\u7ebf\u4e0a live \u9875\u53ea\u63a5\u53d7\u516c\u5f00 Git \u4ed3\u5e93\u5730\u5740\uff08http/https\uff09\uff0c\u4e0d\u63a5\u53d7 file://\u3001ssh:// \u6216\u670d\u52a1\u5668\u672c\u5730\u8def\u5f84\uff1b\u5982\u679c\u60f3\u7ee7\u7eed\u8dd1\u793a\u4f8b\uff0c\u8bf7\u4fdd\u7559\u9ed8\u8ba4\u793a\u4f8b\u4ed3\u5e93\u3002"
    )


def _is_template_bound_structure(submission: Mapping[str, object], template_form_defaults: Mapping[str, str]) -> bool:
    structural_keys = (
        "context_paths_text",
        "editable_paths_text",
        "forbidden_paths_text",
        "expected_changed_files_text",
        "behavioral_checks_text",
        "acceptance_checks_text",
    )
    repo_matches = _submitted_repo_source_value(submission) == str(template_form_defaults.get("repo_path") or "")
    submitted_task_shape = _normalize_task_shape(submission.get("task_shape") or template_form_defaults.get("task_shape"))
    template_task_shape = _normalize_task_shape(template_form_defaults.get("task_shape"))
    submitted_knowledge_pack = _normalize_knowledge_pack(submission.get("knowledge_pack") or template_form_defaults.get("knowledge_pack"))
    template_knowledge_pack = _normalize_knowledge_pack(template_form_defaults.get("knowledge_pack"))
    return repo_matches and submitted_task_shape == template_task_shape and submitted_knowledge_pack == template_knowledge_pack and all(
        str(submission.get(key) or "") == str(template_form_defaults.get(key) or "")
        for key in structural_keys
    )


def _draft_title(task_text: str, repo_name: str) -> str:
    normalized = " ".join(task_text.split())
    if not normalized:
        return f"{repo_name} task"
    for separator in ("\u3002", "\uff01", "\uff1f", ". ", "! ", "? ", "\n"):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0]
            break
    normalized = normalized.strip()
    return normalized[:48] + ("..." if len(normalized) > 48 else "")


def portal_task_shape_options() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "value": value,
            "label": str(profile["label"]),
            "description": str(profile["description"]),
        }
        for value, profile in _PORTAL_TASK_SHAPE_PROFILES.items()
    )


def portal_task_shape_label(value: object) -> str:
    return str(_task_shape_profile(_normalize_task_shape(value))["label"])


def portal_knowledge_pack_options() -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "value": value,
            "label": str(profile["label"]),
            "description": str(profile["description"]),
        }
        for value, profile in _PORTAL_KNOWLEDGE_PACK_PROFILES.items()
    )


def portal_knowledge_pack_label(value: object) -> str:
    return str(_knowledge_pack_profile(_normalize_knowledge_pack(value))["label"])


def _normalize_task_shape(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized in _PORTAL_TASK_SHAPE_PROFILES:
        return normalized
    return _PORTAL_TASK_SHAPE_DEFAULT


def _task_shape_profile(task_shape: str) -> Mapping[str, object]:
    return _PORTAL_TASK_SHAPE_PROFILES[_normalize_task_shape(task_shape)]


def _normalize_knowledge_pack(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized in _PORTAL_KNOWLEDGE_PACK_PROFILES:
        return normalized
    return _PORTAL_KNOWLEDGE_PACK_DEFAULT


def _knowledge_pack_profile(knowledge_pack: str) -> Mapping[str, object]:
    return _PORTAL_KNOWLEDGE_PACK_PROFILES[_normalize_knowledge_pack(knowledge_pack)]


def _task_shape_hints(task_shape: str, key: str) -> tuple[str, ...]:
    value = _task_shape_profile(task_shape).get(key) or ()
    return tuple(str(item) for item in value if str(item))


def _knowledge_pack_hints(knowledge_pack: str, key: str) -> tuple[str, ...]:
    value = _knowledge_pack_profile(knowledge_pack).get(key) or ()
    return tuple(str(item) for item in value if str(item))


def _combined_portal_hints(task_shape: str, knowledge_pack: str, key: str) -> tuple[str, ...]:
    combined: list[str] = []
    seen: set[str] = set()
    for item in (*_task_shape_hints(task_shape, key), *_knowledge_pack_hints(knowledge_pack, key)):
        if item in seen:
            continue
        seen.add(item)
        combined.append(item)
    return tuple(combined)


def _collect_existing_paths(
    repo_root: Path,
    *hint_sets: tuple[str, ...],
    files_only: bool = False,
    limit: int = 8,
) -> tuple[str, ...]:
    collected: list[str] = []
    seen: set[str] = set()

    def add_path(raw_path: str) -> None:
        normalized = _normalize_relative_path(raw_path)
        if not normalized or normalized in seen:
            return
        candidate = repo_root / normalized
        if candidate.is_file():
            seen.add(normalized)
            collected.append(normalized)
            return
        if not candidate.is_dir():
            return
        if not files_only:
            seen.add(normalized)
            collected.append(normalized)
            return
        for child in sorted(candidate.rglob("*")):
            if not child.is_file():
                continue
            relative = _normalize_relative_path(child.relative_to(repo_root))
            if not relative or relative in seen:
                continue
            seen.add(relative)
            collected.append(relative)
            return

    for hint_set in hint_sets:
        for item in hint_set:
            if len(collected) >= limit:
                return tuple(collected)
            add_path(item)
    return tuple(collected)


def _infer_task_type(task_text: str, *, task_shape: str) -> TaskType:
    if _normalize_task_shape(task_shape) == PORTAL_TASK_SHAPE_BUG_FIX:
        return TaskType.BUG_FIX
    lowered = task_text.lower()
    bug_keywords = ("fix", "bug", "error", "fail", "regression", "\u4fee\u590d", "\u62a5\u9519", "\u9519\u8bef", "\u5931\u8d25", "\u56de\u5f52")
    if any(keyword in lowered for keyword in bug_keywords):
        return TaskType.BUG_FIX
    return TaskType.REQUIREMENT_CHANGE


def _draft_task_id(template_id: str, title: str, task_text: str, repo_path: str, *, submission_id: str | None) -> str:
    stem = _safe_file_stem(title)[:40] or "portal-task"
    if submission_id:
        return f"{template_id}-{stem}-{submission_id}"
    digest = hashlib.sha1(f"{template_id}\n{title}\n{task_text}\n{repo_path}".encode("utf8")).hexdigest()[:10]
    return f"{template_id}-{stem}-{digest}"


def _extract_path_hints(task_text: str, repo_root: Path) -> tuple[str, ...]:
    hints: list[str] = []
    seen: set[str] = set()
    lowered = task_text.lower()
    for match in _PATH_HINT_PATTERN.findall(task_text):
        normalized = _normalize_relative_path(match)
        if normalized and (repo_root / normalized).exists() and normalized not in seen:
            seen.add(normalized)
            hints.append(normalized)
    for candidate in ("README.md", "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod"):
        if candidate.lower() in lowered and (repo_root / candidate).exists() and candidate not in seen:
            seen.add(candidate)
            hints.append(candidate)
    return tuple(hints)


def _draft_expected_changed_files(
    repo_root: Path,
    task_text: str,
    hinted_paths: tuple[str, ...],
    *,
    task_shape: str,
    knowledge_pack: str,
) -> tuple[str, ...]:
    file_hints = _collect_existing_paths(
        repo_root,
        hinted_paths,
        _combined_portal_hints(task_shape, knowledge_pack, "expected_file_hints"),
        files_only=True,
        limit=6,
    )
    if file_hints:
        return file_hints
    lowered = task_text.lower()
    if "readme" in lowered and (repo_root / "README.md").exists():
        return ("README.md",)
    return ()


def _draft_editable_paths(
    repo_root: Path,
    hinted_paths: tuple[str, ...],
    *,
    task_shape: str,
    knowledge_pack: str,
) -> tuple[str, ...]:
    draft_hints = _collect_existing_paths(
        repo_root,
        hinted_paths,
        _combined_portal_hints(task_shape, knowledge_pack, "editable_hints"),
        limit=10,
    )
    if draft_hints:
        return tuple(_coerce_editable_hint(path) for path in draft_hints)
    top_level: list[str] = []
    for child in sorted(repo_root.iterdir()):
        if child.name in {".git", "__pycache__"}:
            continue
        top_level.append(child.name)
    return tuple(top_level[:12])


def _coerce_editable_hint(path: str) -> str:
    return PurePosixPath(path).as_posix()


def _draft_context_paths(
    repo_root: Path,
    task_text: str,
    hinted_paths: tuple[str, ...],
    *,
    task_shape: str,
    knowledge_pack: str,
) -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        normalized = _normalize_relative_path(path)
        if not normalized or normalized in seen:
            return
        if not (repo_root / normalized).exists():
            return
        seen.add(normalized)
        candidates.append(normalized)

    for item in hinted_paths:
        add(item)

    for item in _combined_portal_hints(task_shape, knowledge_pack, "context_hints"):
        add(item)

    lowered = task_text.lower()
    for keywords, paths in _KEYWORD_CONTEXT_HINTS:
        if any(keyword in lowered for keyword in keywords):
            for item in paths:
                add(item)

    for item in _COMMON_CONTEXT_HINTS:
        if len(candidates) >= 8:
            break
        add(item)

    return tuple(candidates)


def _draft_behavioral_checks(task_text: str, *, task_shape: str, knowledge_pack: str) -> tuple[str, ...]:
    checks = [f"\u4ea4\u4ed8\u5185\u5bb9\u5e94\u6ee1\u8db3\u4efb\u52a1\u6b63\u6587\uff1a{task_text}"]
    for hint in (
        str(_task_shape_profile(task_shape).get("behavioral_hint") or "").strip(),
        str(_knowledge_pack_profile(knowledge_pack).get("behavioral_hint") or "").strip(),
    ):
        if hint and hint not in checks:
            checks.append(hint)
    return tuple(checks)


def _draft_acceptance_checks(source_repo: str) -> tuple[VerifierStep, ...]:
    script = textwrap.dedent(
        f"""
        print(
            "Draft completion verifier placeholder. "
            "This step is interpreted by {DRAFT_COMPLETION_STEP_NAME} and estimates completion from "
            "changed-file coverage, task-anchor coverage and scope adherence."
        )
        """
    ).strip()
    return (
        VerifierStep(
            name=DRAFT_COMPLETION_STEP_NAME,
            kind=VerifierStepKind.ASSERTION,
            command=(sys.executable, "-c", script),
            required=True,
            notes=(
                "Draft verifier: estimates task completion from expected changed files, task anchors and "
                "scope adherence. Replace it with a real deterministic acceptance check when possible."
            ),
        ),
    )


def _normalize_relative_path(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().replace("\\", "/")
    if not text:
        return ""
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() == ".":
        return ""
    return pure.as_posix()


def _parse_line_block(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(line.strip() for line in str(value).splitlines() if line.strip())


def _serialize_line_block(values: tuple[str, ...]) -> str:
    return "\n".join(str(value) for value in values if str(value).strip())


def _parse_acceptance_checks_text(value: object) -> tuple[VerifierStep, ...]:
    raw_text = str(value or "")
    lines = [line.rstrip() for line in raw_text.splitlines()]
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    steps: list[VerifierStep] = []
    for block in blocks:
        header = block[0].strip()
        if not header.startswith("[") or not header.endswith("]"):
            raise ValueError("\u9a8c\u6536\u547d\u4ee4\u683c\u5f0f\u9519\u8bef\uff1a\u6bcf\u4e2a\u68c0\u67e5\u90fd\u8981\u7528 [\u68c0\u67e5\u540d] \u5f00\u5934\u3002")
        name = header[1:-1].strip()
        if not name:
            raise ValueError("\u9a8c\u6536\u547d\u4ee4\u683c\u5f0f\u9519\u8bef\uff1a\u68c0\u67e5\u540d\u4e0d\u80fd\u4e3a\u7a7a\u3002")
        kind = VerifierStepKind.TEST
        required = True
        notes = ""
        command: list[str] = []
        for item in block[1:]:
            stripped = item.strip()
            if not command and stripped.startswith("kind="):
                kind = VerifierStepKind(stripped.removeprefix("kind=").strip() or VerifierStepKind.TEST.value)
                continue
            if not command and stripped.startswith("required="):
                required = _parse_required_flag(stripped.removeprefix("required=").strip())
                continue
            if not command and stripped.startswith("notes="):
                notes = stripped.removeprefix("notes=").strip()
                continue
            command.append(item)
        if not command:
            raise ValueError(f"\u9a8c\u6536\u68c0\u67e5 {name} \u7f3a\u5c11\u547d\u4ee4\u53c2\u6570\u3002")
        steps.append(VerifierStep(name=name, kind=kind, command=tuple(command), required=required, notes=notes))
    return tuple(steps)


def _serialize_acceptance_checks(steps: tuple[VerifierStep, ...]) -> str:
    blocks: list[str] = []
    for step in steps:
        lines = [f"[{step.name}]", f"kind={step.kind.value}", f"required={'true' if step.required else 'false'}"]
        if step.notes:
            lines.append(f"notes={step.notes}")
        lines.extend(step.command)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _parse_required_flag(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "required"}:
        return True
    if normalized in {"false", "0", "no", "n", "optional"}:
        return False
    raise ValueError(f"\u9a8c\u6536\u547d\u4ee4\u683c\u5f0f\u9519\u8bef\uff1a\u65e0\u6cd5\u8bc6\u522b required={value}\u3002")


def _normalize_freeform_text(value: str) -> str:
    return " ".join(str(value).split())


def _safe_file_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip("-")
    return sanitized or "portal-task"
