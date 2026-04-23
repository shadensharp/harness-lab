from __future__ import annotations

import argparse
import io
import json
import os
import re
from collections.abc import Callable, Mapping
from contextlib import redirect_stdout
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from repo_harness_lab.cli.commands.evals import handle_run_intake_eval
from repo_harness_lab.config.settings import Settings, load_settings
from repo_harness_lab.domain.run_models import RunStatus, RunSummary
from repo_harness_lab.domain.task_spec import VerifierStep, VerifierStepKind
from repo_harness_lab.reporting.failure_summary import build_failure_summary
from repo_harness_lab.reporting.text_localization import localize_harness_message
from repo_harness_lab.runtime.portal_submission import (
    PORTAL_MODE_EXAMPLE,
    PORTAL_MODE_FREEFORM,
    PORTAL_MODE_STRUCTURED,
    PORTAL_TEMPLATE_REPO_TOKEN,
    PortalSubmissionPlan,
    blank_portal_form_fields,
    build_portal_form_fields,
    cleanup_portal_submission_plan,
    portal_knowledge_pack_label,
    portal_knowledge_pack_options,
    portal_task_shape_label,
    portal_task_shape_options,
    resolve_portal_submission,
)
from repo_harness_lab.runtime.portal_live_ui import render_live_portal_shell
from repo_harness_lab.runtime.repo_sources import display_repo_source_label
from repo_harness_lab.shared.failure_hints import pick_failure_hint
from repo_harness_lab.shared.ids import new_id
from repo_harness_lab.shared.portal_story import build_portal_story_sections, render_portal_story
from repo_harness_lab.shared.serialization import to_jsonable
from repo_harness_lab.storage.json_store import JsonRunStore
from repo_harness_lab.storage.run_store import RunRecordStore, StoredEvalCase, StoredEvalReport, StoredRunRecord
from repo_harness_lab.tasks.intake import JsonTaskIntakeLoader
from repo_harness_lab.tasks.intake_preview import build_task_intake_preview
from repo_harness_lab.verifiers.draft_completion import build_draft_completion_feedback

_PROVIDER_DISPLAY_NAMES = {
    "qwen": "\u5343\u95ee",
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
    "groq": "Groq",
    "moonshot": "\u6708\u4e4b\u6697\u9762",
    "siliconflow": "SiliconFlow",
    "fireworks": "Fireworks",
}

_DEFAULT_PAGE_TITLE = "\u540c\u6a21\u578b Harness \u4efb\u52a1\u6f14\u793a\u53f0"
_DEFAULT_IDLE_STATUS = "\u8fd9\u91cc\u652f\u6301\u4efb\u610f repo \u4efb\u52a1\uff1a\u5148\u5199\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u6765\u6e90\uff0c\u4e0d\u7528\u5148\u5199 intake JSON \u6216\u4e0b\u9762\u7684\u53ef\u9009\u5b57\u6bb5\uff1b\u53ef\u4ee5\u5148\u5237\u65b0\u5f53\u524d\u4ea4\u4ed8\u9884\u89c8\uff0c\u518d\u8fd0\u884c\u5f53\u524d\u4efb\u52a1\u3002"
_PORTAL_HISTORY_FILE_NAME = "portal-live-history.json"
_PORTAL_HISTORY_LIMIT = 6


@dataclass(frozen=True, slots=True)
class PortalLiveEntryConfig:
    template_id: str
    intake_source_path: Path
    provider: str = "qwen"
    model: str = "qwen-plus"
    api_key_env: str | None = "DASHSCOPE_API_KEY"
    agent_name: str | None = None
    base_url: str | None = None
    system_prompt: str | None = None
    label_prefix: str | None = None
    allow_custom_local_repo_paths: bool = True


def default_portal_live_entry_config(
    settings: Settings,
    *,
    template: str | Path | None = None,
    provider: str = "qwen",
    model: str = "qwen-plus",
    api_key_env: str | None = "DASHSCOPE_API_KEY",
    agent_name: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    label_prefix: str | None = None,
) -> PortalLiveEntryConfig:
    default_template = settings.paths.examples_dir / "intakes" / "portal_tetris_task_intake.json"
    fallback_templates = (
        settings.paths.examples_dir / "intakes" / "provider_policy_bundle_task_intake.json",
        settings.paths.examples_dir / "intakes" / "provider_release_input_task_intake.json",
    )
    intake_source_path = Path(template).resolve() if template is not None else default_template.resolve()
    if not intake_source_path.exists():
        for fallback_template in fallback_templates:
            if fallback_template.exists():
                intake_source_path = fallback_template.resolve()
                break
    if not intake_source_path.exists():
        raise FileNotFoundError(f"portal intake template not found: {intake_source_path}")
    return PortalLiveEntryConfig(
        template_id=_template_id_from_path(intake_source_path),
        intake_source_path=intake_source_path,
        provider=provider,
        model=model,
        api_key_env=api_key_env,
        agent_name=agent_name,
        base_url=base_url,
        system_prompt=system_prompt,
        label_prefix=label_prefix,
    )


def _live_entry_copy(config: PortalLiveEntryConfig) -> dict[str, object]:
    if config.allow_custom_local_repo_paths:
        return {
            "hosted_mode": False,
            "task_input_label": "\u4efb\u52a1\u6b63\u6587\uff08\u5fc5\u586b\uff09",
            "task_input_placeholder": "\u76f4\u63a5\u7528\u81ea\u7136\u8bed\u8a00\u63cf\u8ff0\u4f60\u60f3\u8ba9\u4ed3\u5e93\u53d1\u751f\u4ec0\u4e48\u53d8\u5316\uff0c\u4f8b\u5982\uff1a\u66f4\u65b0 README\uff0c\u8865\u4e00\u6761\u914d\u7f6e\uff0c\u6216\u540c\u6b65\u4e24\u4efd\u6587\u6863\u3002",
            "task_input_help_text": "\u8fd9\u91cc\u652f\u6301\u4efb\u610f repo \u4efb\u52a1\uff0c\u4e0d\u9700\u8981\u5148\u5199 intake JSON\uff1b\u8bf4\u6e05\u695a\u8981\u6539\u4ec0\u4e48\uff0c\u6700\u597d\u6539\u6210\u4ec0\u4e48\u6837\u5c31\u53ef\u4ee5\u3002",
            "task_shape_input_label": "\u4efb\u52a1\u5f62\u6001\uff08\u53ef\u9009\uff09",
            "task_shape_help_text": "\u5982\u679c\u53ea\u60f3\u5148\u5feb\u901f\u8349\u62df\u8fb9\u754c\uff0c\u53ef\u4ee5\u5148\u9009\u4e00\u4e2a\u6700\u63a5\u8fd1\u7684\u4efb\u52a1\u5f62\u6001\uff0clive \u4f1a\u66f4\u7a33\u5730\u8865 context\u3001editable scope \u548c expected changed files\u3002",
            "knowledge_pack_input_label": "\u6750\u6599\u5305\uff08\u53ef\u9009\uff09",
            "knowledge_pack_help_text": "\u5982\u679c\u4f60\u77e5\u9053\u8fd9\u6b21\u4efb\u52a1\u66f4\u4f9d\u8d56\u54ea\u7c7b\u652f\u6491\u6750\u6599\uff0c\u53ef\u4ee5\u5148\u9009\u4e00\u4e2a\u6750\u6599\u5305\uff0c\u7cfb\u7edf\u4f1a\u66f4\u7a33\u5730\u628a\u76f8\u5173 context \u548c\u76ee\u6807\u6587\u4ef6\u8349\u62df\u51fa\u6765\u3002",
            "repo_source_input_label": "\u4ed3\u5e93\u6765\u6e90\uff08\u5fc5\u586b\uff0cGit \u5730\u5740\u6216\u672c\u5730\u8def\u5f84\uff09",
            "repo_source_placeholder": "\u4f8b\u5982\uff1ahttps://github.com/example/repo \u6216 E:/path/to/local/repo",
            "repo_source_help_text": "\u4efb\u610f repo \u4efb\u52a1\u90fd\u5fc5\u987b\u544a\u8bc9 harness \u76ee\u6807\u4ed3\u5e93\uff1b\u672c\u5730\u6a21\u5f0f\u652f\u6301\u516c\u5f00 Git \u5730\u5740\u548c\u672c\u5730\u8def\u5f84\u3002\u4e0b\u9762\u7684\u53ef\u9009\u5b57\u6bb5\u7559\u7a7a\u65f6\uff0c\u7cfb\u7edf\u4f1a\u5148\u57fa\u4e8e\u4efb\u52a1\u548c\u4ed3\u5e93\u8349\u62df\u6700\u5c0f\u53ef\u8fd0\u884c\u5305\u88c5\u3002",
            "advanced_settings_summary": "\u53ef\u9009\u9ad8\u7ea7\u5b57\u6bb5",
            "advanced_settings_help_text": "\u53ea\u60f3\u5148\u8bd5\u8fd0\u884c\u7684\u8bdd\uff0c\u4e0b\u9762\u8fd9\u4e9b\u5b57\u6bb5\u90fd\u53ef\u4ee5\u5148\u7559\u7a7a\u3002live \u4f1a\u5148\u6839\u636e\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u751f\u6210\u8349\u7a3f\u503c\uff1b\u5982\u679c\u4f60\u5df2\u7ecf\u77e5\u9053\u6b63\u786e\u8fb9\u754c\uff0c\u518d\u624b\u52a8\u8986\u76d6\u3002",
            "acceptance_checks_help_text": "\u7559\u7a7a\u65f6\uff0c\u7cfb\u7edf\u4f1a\u653e\u4e00\u4e2a\u201c\u8349\u7a3f\u5b8c\u6210\u5ea6\u4f30\u7b97\u201d verifier\uff0c\u4f1a\u6839\u636e\u76ee\u6807\u6587\u4ef6\u3001\u4efb\u52a1\u951a\u70b9\u548c\u8303\u56f4\u7ea6\u675f\u6765\u4f30\u7b97\u5b8c\u6210\u5ea6\uff1b\u60f3\u62ff\u5230\u771f\u5b9e\u5b8c\u6210\u8bc1\u636e\uff0c\u5efa\u8bae\u6539\u6210\u4f60\u7684\u786e\u5b9a\u6027 acceptance checks\u3002",
            "default_status_text": "\u8fd9\u91cc\u652f\u6301\u4efb\u610f repo \u4efb\u52a1\uff1a\u5148\u5199\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u6765\u6e90\uff0c\u672c\u5730\u6a21\u5f0f\u652f\u6301\u516c\u5f00 Git \u5730\u5740\u6216\u672c\u5730\u8def\u5f84\uff1b\u4e0d\u7528\u5148\u586b\u4e0b\u9762\u7684\u53ef\u9009\u5b57\u6bb5\uff0c\u53ef\u4ee5\u5148\u5237\u65b0\u5f53\u524d\u4ea4\u4ed8\u9884\u89c8\uff0c\u518d\u8fd0\u884c\u5f53\u524d\u4efb\u52a1\u3002",
        }
    return {
        "hosted_mode": True,
        "task_input_label": "\u4efb\u52a1\u6b63\u6587\uff08\u5fc5\u586b\uff09",
        "task_input_placeholder": "\u76f4\u63a5\u7528\u81ea\u7136\u8bed\u8a00\u63cf\u8ff0\u4f60\u60f3\u8ba9\u4ed3\u5e93\u53d1\u751f\u4ec0\u4e48\u53d8\u5316\uff0c\u4f8b\u5982\uff1a\u66f4\u65b0 README\uff0c\u8865\u4e00\u6761\u914d\u7f6e\uff0c\u6216\u540c\u6b65\u4e24\u4efd\u6587\u6863\u3002",
        "task_input_help_text": "\u8fd9\u91cc\u652f\u6301\u4efb\u610f repo \u4efb\u52a1\uff0c\u4e0d\u9700\u8981\u5148\u5199 intake JSON\uff1b\u8bf4\u6e05\u695a\u8981\u6539\u4ec0\u4e48\uff0c\u6700\u597d\u6539\u6210\u4ec0\u4e48\u6837\u5c31\u53ef\u4ee5\u3002",
        "task_shape_input_label": "\u4efb\u52a1\u5f62\u6001\uff08\u53ef\u9009\uff09",
        "task_shape_help_text": "\u5982\u679c\u53ea\u60f3\u5148\u5feb\u901f\u8349\u62df\u8fb9\u754c\uff0c\u53ef\u4ee5\u5148\u9009\u4e00\u4e2a\u6700\u63a5\u8fd1\u7684\u4efb\u52a1\u5f62\u6001\uff0clive \u4f1a\u66f4\u7a33\u5730\u8865 context\u3001editable scope \u548c expected changed files\u3002",
        "knowledge_pack_input_label": "\u6750\u6599\u5305\uff08\u53ef\u9009\uff09",
        "knowledge_pack_help_text": "\u5982\u679c\u4f60\u77e5\u9053\u8fd9\u6b21\u4efb\u52a1\u66f4\u4f9d\u8d56\u54ea\u7c7b\u652f\u6491\u6750\u6599\uff0c\u53ef\u4ee5\u5148\u9009\u4e00\u4e2a\u6750\u6599\u5305\uff0c\u7cfb\u7edf\u4f1a\u66f4\u7a33\u5730\u628a\u76f8\u5173 context \u548c\u76ee\u6807\u6587\u4ef6\u8349\u62df\u51fa\u6765\u3002",
        "repo_source_input_label": "\u4ed3\u5e93\u6765\u6e90\uff08\u5fc5\u586b\uff0c\u516c\u5f00 Git \u5730\u5740\u6216\u793a\u4f8b\u4ed3\u5e93\uff09",
        "repo_source_placeholder": "\u4f8b\u5982\uff1ahttps://github.com/example/repo",
        "repo_source_help_text": "\u4efb\u610f repo \u4efb\u52a1\u90fd\u5fc5\u987b\u544a\u8bc9 harness \u76ee\u6807\u4ed3\u5e93\uff1b\u7ebf\u4e0a\u6a21\u5f0f\u53ea\u63a5\u53d7\u516c\u5f00 http/https Git \u5730\u5740\uff0c\u4e5f\u53ef\u4ee5\u4fdd\u7559\u793a\u4f8b\u4ed3\u5e93\u3002\u4e0b\u9762\u7684\u53ef\u9009\u5b57\u6bb5\u7559\u7a7a\u65f6\uff0c\u7cfb\u7edf\u4f1a\u5148\u57fa\u4e8e\u4efb\u52a1\u548c\u4ed3\u5e93\u8349\u62df\u6700\u5c0f\u53ef\u8fd0\u884c\u5305\u88c5\u3002",
        "advanced_settings_summary": "\u53ef\u9009\u9ad8\u7ea7\u5b57\u6bb5",
        "advanced_settings_help_text": "\u53ea\u60f3\u5148\u8bd5\u8fd0\u884c\u7684\u8bdd\uff0c\u4e0b\u9762\u8fd9\u4e9b\u5b57\u6bb5\u90fd\u53ef\u4ee5\u5148\u7559\u7a7a\u3002live \u4f1a\u5148\u6839\u636e\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u751f\u6210\u8349\u7a3f\u503c\uff1b\u5982\u679c\u4f60\u5df2\u7ecf\u77e5\u9053\u6b63\u786e\u8fb9\u754c\uff0c\u518d\u624b\u52a8\u8986\u76d6\u3002",
        "acceptance_checks_help_text": "\u7559\u7a7a\u65f6\uff0c\u7cfb\u7edf\u4f1a\u653e\u4e00\u4e2a\u201c\u8349\u7a3f\u5b8c\u6210\u5ea6\u4f30\u7b97\u201d verifier\uff0c\u4f1a\u6839\u636e\u76ee\u6807\u6587\u4ef6\u3001\u4efb\u52a1\u951a\u70b9\u548c\u8303\u56f4\u7ea6\u675f\u6765\u4f30\u7b97\u5b8c\u6210\u5ea6\uff1b\u60f3\u62ff\u5230\u771f\u5b9e\u5b8c\u6210\u8bc1\u636e\uff0c\u5efa\u8bae\u6539\u6210\u4f60\u7684\u786e\u5b9a\u6027 acceptance checks\u3002",
        "default_status_text": "\u8fd9\u91cc\u652f\u6301\u4efb\u610f repo \u4efb\u52a1\uff1a\u5148\u5199\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u6765\u6e90\uff1b\u7ebf\u4e0a\u6a21\u5f0f\u53ea\u63a5\u53d7\u516c\u5f00 http/https Git \u5730\u5740\u6216\u793a\u4f8b\u4ed3\u5e93\uff0c\u4e0d\u7528\u5148\u586b\u4e0b\u9762\u7684\u53ef\u9009\u5b57\u6bb5\uff0c\u53ef\u4ee5\u5148\u5237\u65b0\u5f53\u524d\u4ea4\u4ed8\u9884\u89c8\uff0c\u518d\u8fd0\u884c\u5f53\u524d\u4efb\u52a1\u3002",
    }


def _portal_repo_source_label(value: str) -> str:
    text = str(value).strip()
    if text == PORTAL_TEMPLATE_REPO_TOKEN:
        return "\u793a\u4f8b\u4ed3\u5e93"
    return display_repo_source_label(text) or text


def build_live_entry_payload(config: PortalLiveEntryConfig) -> dict[str, object]:
    intake = JsonTaskIntakeLoader().load(config.intake_source_path)
    entry_copy = _live_entry_copy(config)
    form_defaults = _build_form_defaults(intake, hide_local_repo_source=not config.allow_custom_local_repo_paths)
    model_display_name = _model_display_name(config.provider, config.model)
    example_plan = PortalSubmissionPlan(intake=intake, form_fields=form_defaults, mode=PORTAL_MODE_EXAMPLE)
    preview_bundle = _preview_bundle(
        plan=example_plan,
        source_path=config.intake_source_path,
        template_id=config.template_id,
        template_title=intake.title,
        template_form_defaults=form_defaults,
        model_display_name=model_display_name,
    )
    api_ready = True
    if config.api_key_env:
        api_ready = bool(os.environ.get(config.api_key_env))
        if api_ready:
            api_message = f"\u5df2\u68c0\u6d4b\u5230 {config.api_key_env}\uff0c\u53ef\u4ee5\u76f4\u63a5\u8fd0\u884c\u3002"
        else:
            api_message = f"\u672a\u68c0\u6d4b\u5230 {config.api_key_env}\uff0c\u76ee\u524d\u65e0\u6cd5\u76f4\u63a5\u8fd0\u884c\u3002"
    else:
        api_message = "\u5f53\u524d\u914d\u7f6e\u4e0d\u9700\u8981\u989d\u5916 API Key\u3002"
    return {
        "template_id": config.template_id,
        "template_title": intake.title,
        "task_id": intake.task_id,
        "default_task_text": intake.business_request,
        "provider": config.provider,
        "model": config.model,
        "api_key_env": config.api_key_env,
        "model_display_name": model_display_name,
        "api_ready": api_ready,
        "api_message": api_message,
        "run_endpoint": "/api/run-demo",
        "run_async_endpoint": "/api/run-demo-async",
        "run_status_endpoint": "/api/run-demo-status",
        "preview_endpoint": "/api/preview-demo",
        "config_endpoint": "/api/config",
        "poll_after_ms": 1500,
        **entry_copy,
        "allow_custom_local_repo_paths": config.allow_custom_local_repo_paths,
        "task_shape_options": portal_task_shape_options(),
        "knowledge_pack_options": portal_knowledge_pack_options(),
        "form_defaults": form_defaults,
        "blank_form_defaults": blank_portal_form_fields(),
        "scope_html": preview_bundle["scope_html"],
        "profile_explainer_html": preview_bundle["profile_explainer_html"],
    }


def build_live_page_state(*, settings: Settings, live_entry: PortalLiveEntryConfig) -> dict[str, object]:
    entry = build_live_entry_payload(live_entry)
    form_fields = blank_portal_form_fields()
    recent_submissions = _load_live_submission_history(settings=settings, template_id=live_entry.template_id)
    status_text = str(entry.get("default_status_text") or _DEFAULT_IDLE_STATUS)
    if not bool(entry.get("api_ready")):
        status_text = str(entry.get("api_message") or "") + " \u4ecd\u7136\u53ef\u4ee5\u5148\u5237\u65b0\u4e09\u6863\u4ea4\u4ed8\u9884\u89c8\u3002"
    return {
        "page_title": _DEFAULT_PAGE_TITLE,
        "entry_title": str(entry["template_title"]),
        "form_fields": form_fields,
        "example_task_text": str(entry["default_task_text"]),
        "model_display_name": str(entry["model_display_name"]),
        "api_ready": bool(entry["api_ready"]),
        "status_text": status_text,
        "task_input_label": str(entry.get("task_input_label") or "\u4efb\u52a1\u6b63\u6587"),
        "task_input_placeholder": str(entry.get("task_input_placeholder") or ""),
        "task_input_help_text": str(entry.get("task_input_help_text") or ""),
        "task_shape_input_label": str(entry.get("task_shape_input_label") or "\u4efb\u52a1\u5f62\u6001"),
        "task_shape_help_text": str(entry.get("task_shape_help_text") or ""),
        "task_shape_options": list(entry.get("task_shape_options") or ()),
        "knowledge_pack_input_label": str(entry.get("knowledge_pack_input_label") or "\u6750\u6599\u5305"),
        "knowledge_pack_help_text": str(entry.get("knowledge_pack_help_text") or ""),
        "knowledge_pack_options": list(entry.get("knowledge_pack_options") or ()),
        "repo_source_input_label": str(entry.get("repo_source_input_label") or "\u4ed3\u5e93\u6765\u6e90"),
        "repo_source_placeholder": str(entry.get("repo_source_placeholder") or ""),
        "repo_source_help_text": str(entry.get("repo_source_help_text") or ""),
        "advanced_settings_summary": str(entry.get("advanced_settings_summary") or "\u66f4\u591a\u4efb\u52a1\u8bbe\u7f6e"),
        "advanced_settings_help_text": str(entry.get("advanced_settings_help_text") or ""),
        "acceptance_checks_help_text": str(entry.get("acceptance_checks_help_text") or ""),
        "results": [],
        "results_html": render_live_results_markup([], empty_text=status_text),
        "links": [],
        "links_html": "",
        "scope_html": _render_scope_placeholder_markup(entry_title=str(entry["template_title"])),
        "profile_explainer_html": _render_profile_placeholder_markup(model_display_name=str(entry["model_display_name"])),
        "recent_submissions": recent_submissions,
        "recent_history_html": render_live_history_markup(recent_submissions),
        "config": {
            **entry,
            "recent_submissions": recent_submissions,
        },
    }


def preview_live_portal_submission(
    *,
    live_entry: PortalLiveEntryConfig,
    submission: Mapping[str, object],
    settings: Settings | None = None,
) -> dict[str, object]:
    resolved_settings = settings or load_settings()
    base_intake = JsonTaskIntakeLoader().load(live_entry.intake_source_path)
    template_form_defaults = _build_form_defaults(
        base_intake,
        hide_local_repo_source=not live_entry.allow_custom_local_repo_paths,
    )
    task_text = str(submission.get("task_text") or "").strip()
    repo_source = str(submission.get("repo_source") or submission.get("repo_path") or "").strip()
    model_display_name = _model_display_name(live_entry.provider, live_entry.model)
    if not task_text and not repo_source:
        return {
            "ok": True,
            "status_text": str(_live_entry_copy(live_entry).get("default_status_text") or _DEFAULT_IDLE_STATUS),
            "form_fields": blank_portal_form_fields(),
            "scope_html": _render_scope_placeholder_markup(entry_title=base_intake.title),
            "profile_explainer_html": _render_profile_placeholder_markup(model_display_name=model_display_name),
        }
    if not task_text:
        raise ValueError("\u8bf7\u5148\u8f93\u5165\u60f3\u6267\u884c\u7684\u4efb\u52a1\u3002")
    if not repo_source:
        raise ValueError("\u8bf7\u5148\u586b\u5199\u8981\u64cd\u4f5c\u7684\u4ed3\u5e93\u6765\u6e90\uff08\u672c\u5730\u8def\u5f84\u6216 Git \u5730\u5740\uff09\u3002")

    plan = resolve_portal_submission(
        base_intake=base_intake,
        submission=submission,
        template_id=live_entry.template_id,
        template_form_defaults=template_form_defaults,
        require_task_text=True,
        require_repo_path=True,
        settings=resolved_settings,
        allow_custom_local_repo_paths=live_entry.allow_custom_local_repo_paths,
    )
    try:
        preview_bundle = _preview_bundle(
            plan=plan,
            source_path=live_entry.intake_source_path if plan.mode == PORTAL_MODE_EXAMPLE else None,
            template_id=live_entry.template_id,
            template_title=base_intake.title,
            template_form_defaults=template_form_defaults,
            model_display_name=model_display_name,
        )
        return {
            "ok": True,
            "status_text": _preview_status_text(plan),
            "form_fields": plan.form_fields,
            "scope_html": preview_bundle["scope_html"],
            "profile_explainer_html": preview_bundle["profile_explainer_html"],
        }
    finally:
        cleanup_portal_submission_plan(plan)


def run_live_portal_submission(
    *,
    settings: Settings,
    live_entry: PortalLiveEntryConfig,
    submission: Mapping[str, object],
    progress_callback: Callable[[str, str], None] | None = None,
) -> dict[str, object]:
    def report_progress(phase: str, message: str) -> None:
        if progress_callback is not None:
            progress_callback(phase, message)

    report_progress("prepare", "正在准备任务")
    settings.paths.ensure_runtime_directories()
    base_intake = JsonTaskIntakeLoader().load(live_entry.intake_source_path)
    template_form_defaults = _build_form_defaults(
        base_intake,
        hide_local_repo_source=not live_entry.allow_custom_local_repo_paths,
    )
    submission_id = new_id("portal")
    plan = resolve_portal_submission(
        base_intake=base_intake,
        submission=submission,
        template_id=live_entry.template_id,
        template_form_defaults=template_form_defaults,
        submission_id=submission_id,
        require_task_text=True,
        require_repo_path=True,
        settings=settings,
        allow_custom_local_repo_paths=live_entry.allow_custom_local_repo_paths,
    )
    try:
        intake = plan.intake

        submission_path = settings.paths.tmp_dir / f"{_safe_file_stem(intake.task_id)}-{submission_id}.intake.json"
        submission_path.write_text(json.dumps(to_jsonable(intake), ensure_ascii=False, indent=2), encoding="utf8")

        suite_id = f"{live_entry.template_id}-{submission_id}-intake-uplift-suite"
        args = argparse.Namespace(
            source=str(submission_path),
            provider=live_entry.provider,
            model=live_entry.model,
            agent_name=live_entry.agent_name,
            api_key_env=live_entry.api_key_env,
            base_url=live_entry.base_url,
            system_prompt=live_entry.system_prompt,
            suite_id=suite_id,
            label_prefix=live_entry.label_prefix,
            historical_baseline_report_id=None,
            baseline_report_id=None,
        )
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                exit_code = handle_run_intake_eval(args)
        except Exception as exc:  # pragma: no cover - defensive surface around the CLI handler
            raise RuntimeError(str(exc)) from exc

        payload_text = buffer.getvalue().strip()
        if not payload_text:
            raise RuntimeError("portal run did not return a result payload")
        payload = json.loads(payload_text)
        if exit_code != 0 or payload.get("ok") is False:
            raise RuntimeError(str(payload.get("error") or "portal run failed"))

        record_store = RunRecordStore(settings=settings, json_store=JsonRunStore(settings=settings))
        focus_payload = _build_focus_payload(
            record_store=record_store,
            report_id=str(payload.get("suite_id") or ""),
            target_task_id=intake.task_id,
        )
        results = list(focus_payload.get("results", []))
        if plan.used_draft_verifier:
            results = _annotate_draft_results(
                results,
                note="当前是自由任务草稿完成度验收：系统会按目标文件覆盖、任务锚点命中和范围遵守估算完成度，仍不等于真实业务验收。",
            )
        links = list(focus_payload.get("links", []))
        preview_bundle = _preview_bundle(
            plan=plan,
            source_path=submission_path,
            template_id=live_entry.template_id,
            template_title=base_intake.title,
            template_form_defaults=template_form_defaults,
            model_display_name=_model_display_name(live_entry.provider, live_entry.model),
        )
        recent_submissions = _store_live_submission_history(
            settings=settings,
            template_id=live_entry.template_id,
            title=intake.title,
            suite_id=str(payload.get("suite_id") or ""),
            form_fields=plan.form_fields,
        )
        return {
            "ok": True,
            "suite_id": str(payload.get("suite_id") or ""),
            "task_text": intake.business_request,
            "task_title": intake.title,
            "model_display_name": _model_display_name(live_entry.provider, live_entry.model),
            "status_text": _run_status_text(plan),
            "results": results,
            "results_html": render_live_results_markup(results),
            "links": links,
            "links_html": render_live_links_markup(links),
            "scope_html": preview_bundle["scope_html"],
            "profile_explainer_html": preview_bundle["profile_explainer_html"],
            "form_fields": plan.form_fields,
            "recent_submissions": recent_submissions,
            "recent_history_html": render_live_history_markup(recent_submissions),
        }
    finally:
        cleanup_portal_submission_plan(plan)


def _preview_status_text(plan: PortalSubmissionPlan) -> str:
    if plan.mode == PORTAL_MODE_EXAMPLE:
        return "\u5df2\u5207\u56de\u793a\u4f8b\u6a21\u677f\u9884\u89c8\u3002"
    if plan.mode == PORTAL_MODE_FREEFORM and plan.used_draft_verifier:
        return "\u5df2\u751f\u6210\u81ea\u7531\u4efb\u52a1\u8349\u7a3f\u9884\u89c8\uff1b\u5f53\u524d\u9a8c\u6536\u4f1a\u6309\u76ee\u6807\u6587\u4ef6\u3001\u4efb\u52a1\u951a\u70b9\u548c\u8303\u56f4\u7ea6\u675f\u4f30\u7b97\u5b8c\u6210\u5ea6\uff0c\u5efa\u8bae\u8fd0\u884c\u524d\u8865\u5145\u771f\u5b9e acceptance checks\u3002"
    return "\u5df2\u6309\u5f53\u524d\u8f93\u5165\u5237\u65b0\u4e09\u6863\u4ea4\u4ed8\u9884\u89c8\u3002"


def _run_status_text(plan: PortalSubmissionPlan) -> str:
    if plan.mode == PORTAL_MODE_FREEFORM and plan.used_draft_verifier:
        return "\u5df2\u5b8c\u6210\u5f53\u524d\u8fd0\u884c\uff1b\u5f53\u524d\u662f\u81ea\u7531\u4efb\u52a1\u8349\u7a3f\u6a21\u5f0f\uff0c\u9a8c\u6536\u4f1a\u6309\u76ee\u6807\u6587\u4ef6\u3001\u4efb\u52a1\u951a\u70b9\u548c\u8303\u56f4\u7ea6\u675f\u4f30\u7b97\u5b8c\u6210\u5ea6\uff0c\u4f46\u4ecd\u4e0d\u7b49\u4e8e\u771f\u5b9e\u4e1a\u52a1\u9a8c\u6536\u3002"
    return "\u5df2\u5b8c\u6210\u5f53\u524d\u8fd0\u884c\u3002"


def _annotate_draft_results(results: list[dict[str, object]], *, note: str) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for item in results:
        updated = dict(item)
        result_items = [str(entry) for entry in item.get("result_items", ()) if str(entry)]
        updated["result_items"] = [note, *result_items]
        annotated.append(updated)
    return annotated


def render_live_results_markup(results: list[dict[str, object]], *, empty_text: str | None = None) -> str:
    if not results:
        return f'<div class="empty">{escape(empty_text or _DEFAULT_IDLE_STATUS)}</div>'
    cards = "".join(_render_result_card(result) for result in results)
    return f'<div class="results-grid">{cards}</div>'


def render_live_links_markup(links: list[dict[str, str]]) -> str:
    if not links:
        return ""
    items = []
    for link in links:
        label = str(link.get("label") or "\u6253\u5f00\u9875\u9762")
        href = str(link.get("href") or "#")
        items.append(f'<a class="button button-secondary" href="{escape(href)}">{escape(label)}</a>')
    return "".join(items)


def render_live_history_markup(entries: list[dict[str, object]]) -> str:
    if not entries:
        return '<div class="empty">\u6700\u8fd1\u8fd8\u6ca1\u6709\u901a\u8fc7\u8fd9\u4e2a\u5165\u53e3\u63d0\u4ea4\u8fc7\u4efb\u52a1\u3002</div>'
    cards = "".join(_render_history_card(entry) for entry in entries)
    return f'<div class="history-grid">{cards}</div>'


def _render_history_card(entry: dict[str, object]) -> str:
    title = str(entry.get("title") or "\u672a\u547d\u540d\u4efb\u52a1")
    task_text = str(entry.get("task_text") or "")
    repo_path = str(entry.get("repo_path") or "")
    repo_label = _portal_repo_source_label(repo_path) or repo_path or "\u672a\u8bbe\u7f6e\u4ed3\u5e93\u6765\u6e90"
    suite_id = str(entry.get("suite_id") or "")
    form_fields = dict(entry.get("form_fields") or {})
    form_payload = json.dumps(form_fields, ensure_ascii=False).replace("</", "<\/")
    task_snippet = task_text if len(task_text) <= 110 else task_text[:110].rstrip() + "..."
    task_display = task_snippet or "\u672a\u586b\u5199\u4efb\u52a1\u6b63\u6587"
    actions = [
        f'<button class="button button-secondary portal-live-load-history" type="button" data-form="{escape(form_payload)}">\u91cd\u65b0\u586b\u5165</button>',
    ]
    if suite_id:
        actions.append(f'<a class="button button-secondary" href="/{escape(_safe_file_stem(suite_id))}.html">\u6253\u5f00\u7ed3\u679c</a>')
    return "".join(
        [
            '<article class="history-card">',
            '<div class="history-meta">',
            f'<span class="badge badge-soft">{escape(title)}</span>',
            f'<span>{escape(repo_label)}</span>',
            '</div>',
            f'<p>{escape(task_display)}</p>',
            '<div class="history-actions">',
            "".join(actions),
            '</div>',
            '</article>',
        ]
    )


def render_live_portal_html(state: dict[str, object]) -> str:
    config_json = json.dumps(state.get("config", {}), ensure_ascii=False).replace("</", "<\\/")
    status_text = str(state.get("status_text") or _DEFAULT_IDLE_STATUS)
    results_html = str(state.get("results_html") or render_live_results_markup([], empty_text=status_text))
    links_html = str(state.get("links_html") or "")
    scope_html = str(state.get("scope_html") or "")
    profile_explainer_html = str(state.get("profile_explainer_html") or "")
    disabled_attr = " disabled" if not bool(state.get("api_ready")) else ""
    title = str(state.get("page_title") or _DEFAULT_PAGE_TITLE)
    model_display_name = str(state.get("model_display_name") or "")
    entry_title = str(state.get("entry_title") or "")
    example_task_text = str(state.get("example_task_text") or "")
    form_fields = dict(state.get("form_fields") or {})
    form_title = str(form_fields.get("title") or "")
    task_text = str(form_fields.get("task_text") or "")
    task_shape = str(form_fields.get("task_shape") or "general")
    knowledge_pack = str(form_fields.get("knowledge_pack") or "none")
    repo_path = str(form_fields.get("repo_path") or "")
    task_input_label = str(state.get("task_input_label") or "\u4efb\u52a1\u6b63\u6587")
    task_input_placeholder = str(state.get("task_input_placeholder") or "")
    task_input_help_text = str(state.get("task_input_help_text") or "")
    task_shape_input_label = str(state.get("task_shape_input_label") or "\u4efb\u52a1\u5f62\u6001")
    task_shape_help_text = str(state.get("task_shape_help_text") or "")
    task_shape_options = list(state.get("task_shape_options") or ())
    knowledge_pack_input_label = str(state.get("knowledge_pack_input_label") or "\u6750\u6599\u5305")
    knowledge_pack_help_text = str(state.get("knowledge_pack_help_text") or "")
    knowledge_pack_options = list(state.get("knowledge_pack_options") or ())
    repo_source_input_label = str(state.get("repo_source_input_label") or "\u4ed3\u5e93\u6765\u6e90")
    repo_source_placeholder = str(state.get("repo_source_placeholder") or "")
    repo_source_help_text = str(state.get("repo_source_help_text") or "")
    advanced_settings_summary = str(state.get("advanced_settings_summary") or "\u66f4\u591a\u4efb\u52a1\u8bbe\u7f6e")
    advanced_settings_help_text = str(state.get("advanced_settings_help_text") or "")
    acceptance_checks_help_text = str(state.get("acceptance_checks_help_text") or "")
    context_paths_text = str(form_fields.get("context_paths_text") or "")
    editable_paths_text = str(form_fields.get("editable_paths_text") or "")
    forbidden_paths_text = str(form_fields.get("forbidden_paths_text") or "")
    expected_changed_files_text = str(form_fields.get("expected_changed_files_text") or "")
    behavioral_checks_text = str(form_fields.get("behavioral_checks_text") or "")
    acceptance_checks_text = str(form_fields.get("acceptance_checks_text") or "")
    recent_history_html = str(state.get("recent_history_html") or render_live_history_markup([]))
    task_shape_options_markup = "".join(
        f'<option value="{escape(str(item.get("value") or ""))}"' + (' selected' if str(item.get("value") or "") == task_shape else '') + f'>{escape(str(item.get("label") or item.get("value") or ""))}</option>'
        for item in task_shape_options
    )
    knowledge_pack_options_markup = "".join(
        f'<option value="{escape(str(item.get("value") or ""))}"' + (' selected' if str(item.get("value") or "") == knowledge_pack else '') + f'>{escape(str(item.get("label") or item.get("value") or ""))}</option>'
        for item in knowledge_pack_options
    )
    return "".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{escape(title)}</title>",
            f"<style>{_styles()}</style>",
            "</head>",
            "<body>",
            '<div class="page-shell">',
            '<section class="hero">',
            '<p class="eyebrow">\u540c\u6a21\u578b Harness</p>',
            f"<h1>{escape(title)}</h1>",
            '<p>\u8fd9\u91cc\u652f\u6301\u4efb\u610f repo \u4efb\u52a1\uff0c\u4e0d\u7528\u5148\u5199 intake JSON\u3002\u5148\u7ed9\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u6765\u6e90\uff0clive \u9875\u4f1a\u5148\u5c55\u793a\u5f53\u524d\u4ea4\u4ed8\u4f1a\u628a\u4ec0\u4e48\u7ed9\u5230\u6a21\u578b\uff1b\u5982\u679c\u53ea\u60f3\u5bf9\u7167\u63a7\u5236\u6837\u672c\uff0c\u518d\u70b9\u201c\u586b\u5165\u793a\u4f8b\u201d\u3002</p>',
            '<div class="hero-badges">',
            f'<span class="badge badge-hero">\u6a21\u578b\uff1a{escape(model_display_name)}</span>',
            '<span class="badge badge-hero">\u81ea\u7531\u4efb\u52a1\u8349\u7a3f + \u793a\u4f8b\u6a21\u677f</span>',
            '<span class="badge badge-hero">\u5f53\u524d\u4ea4\u4ed8\u76f4\u89c6\u9884\u89c8</span>',
            '</div>',
            '</section>',
            '<section class="panel">',
            '<div class="panel-head">',
            '<h2>\u5f53\u524d\u8fd0\u884c\u8fb9\u754c</h2>',
            '<p class="subtitle">\u8fd9\u91cc\u6839\u636e\u4f60\u5f53\u524d\u8868\u5355\u751f\u6210\u4e00\u4efd\u6b63\u5728\u4f7f\u7528\u7684 harness \u5305\u88c5\uff0c\u5148\u770b\u6e05\u4ed3\u5e93\u3001\u53ef\u7f16\u8f91\u8303\u56f4\u3001\u9884\u671f\u6539\u52a8\u548c\u9a8c\u6536\u8fb9\u754c\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u8fd0\u884c\u3002</p>',
            '</div>',
            f'<div id="portal-live-scope">{scope_html}</div>',
            '</section>',
            '<section class="panel">',
            '<div class="panel-head">',
            '<h2>\u5f53\u524d\u4ea4\u4ed8\u8bf4\u660e</h2>',
            '<p class="subtitle">\u8fd9\u91cc\u76f4\u63a5\u5c55\u793a\u5f53\u524d\u4f1a\u4ea4\u7ed9\u6a21\u578b\u7684\u5185\u5bb9\uff0c\u4e0d\u518d\u628a\u5173\u952e\u5dee\u5f02\u85cf\u8fdb\u5386\u53f2\u62a5\u544a\u6216\u8fd0\u884c\u7ec6\u8282\u91cc\u3002</p>',
            '</div>',
            f'<div id="portal-live-profile-explainer">{profile_explainer_html}</div>',
            '</section>',
            '<section class="panel">',
            '<div class="panel-head">',
            '<h2>\u7528\u6237\u4efb\u52a1</h2>',
            '<p class="subtitle">\u8fd9\u91cc\u53ea\u6709\u4e24\u4e2a\u771f\u6b63\u5fc5\u586b\u9879\uff1a\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u6765\u6e90\u3002\u53ef\u9009\u5b57\u6bb5\u90fd\u80fd\u5148\u7559\u7a7a\uff1b\u70b9\u201c\u5237\u65b0\u5f53\u524d\u4ea4\u4ed8\u9884\u89c8\u201d\u540e\uff0c\u9875\u9762\u4f1a\u76f4\u63a5\u544a\u8bc9\u4f60\u5f53\u524d\u4f1a\u4ea4\u4ed8\u4ec0\u4e48\u3002</p>',
            '</div>',
            '<div class="entry-top">',
            f'<span class="badge badge-soft" id="portal-live-model-label">\u6a21\u578b\uff1a{escape(model_display_name)}</span>',
            f'<span class="status-note" id="portal-live-status">{escape(status_text)}</span>',
            '</div>',
            '<label class="input-label" for="portal-live-title-input">\u4efb\u52a1\u6807\u9898</label>',
            f'<input id="portal-live-title-input" class="text-input" type="text" value="{escape(form_title)}" placeholder="\u7ed9\u8fd9\u6b21\u4efb\u52a1\u8d77\u4e00\u4e2a\u6807\u9898\uff0c\u53ef\u7559\u7a7a\u8ba9\u7cfb\u7edf\u81ea\u52a8\u8349\u62df">',
            f'<label class="input-label" for="portal-live-task-input">{escape(task_input_label)}</label>',
            f'<textarea id="portal-live-task-input" class="task-input" rows="7" placeholder="{escape(task_input_placeholder)}">{escape(task_text)}</textarea>',
            f'<p class="subtitle">{escape(task_input_help_text)}</p>',
            f'<label class="input-label" for="portal-live-task-shape">{escape(task_shape_input_label)}</label>',
            f'<select id="portal-live-task-shape" class="text-input">{task_shape_options_markup}</select>',
            f'<p class="subtitle">{escape(task_shape_help_text)}</p>',
            f'<label class="input-label" for="portal-live-knowledge-pack">{escape(knowledge_pack_input_label)}</label>',
            f'<select id="portal-live-knowledge-pack" class="text-input">{knowledge_pack_options_markup}</select>',
            f'<p class="subtitle">{escape(knowledge_pack_help_text)}</p>',
            f'<label class="input-label" for="portal-live-repo-path">{escape(repo_source_input_label)}</label>',
            f'<input id="portal-live-repo-path" class="text-input" type="text" value="{escape(repo_path)}" placeholder="{escape(repo_source_placeholder)}">',
            f'<p class="subtitle">{escape(repo_source_help_text)}</p>',
            '<div class="example-box">',
            '<div class="example-head">',
            f'<div class="example-title">\u5f53\u524d\u793a\u4f8b\uff1a{escape(entry_title)}</div>',
            '<button id="portal-live-use-example" class="button button-secondary" type="button">\u586b\u5165\u793a\u4f8b</button>',
            '</div>',
            f'<pre>{escape(example_task_text)}</pre>',
            '</div>',
            '<details class="advanced-box">',
            f'<summary>{escape(advanced_settings_summary)}</summary>',
            f'<p class="subtitle">{escape(advanced_settings_help_text)}</p>',
            '<div class="field-grid">',
            '<label class="field-group" for="portal-live-context-paths"><span>\u4e0a\u4e0b\u6587\u6587\u4ef6</span>',
            f'<textarea id="portal-live-context-paths" class="code-input" rows="7" placeholder="\u4e00\u884c\u4e00\u4e2a\u76f8\u5bf9\u8def\u5f84">{escape(context_paths_text)}</textarea>',
            '<small class="field-hint">\u8fd9\u4e9b\u6587\u4ef6\u4f1a\u4f5c\u4e3a\u8865\u5145\u4e0a\u4e0b\u6587\u63d0\u4f9b\u7ed9 harness\u3002</small></label>',
            '<label class="field-group" for="portal-live-editable-paths"><span>\u5141\u8bb8\u4fee\u6539\u7684\u6587\u4ef6</span>',
            f'<textarea id="portal-live-editable-paths" class="code-input" rows="7" placeholder="\u4e00\u884c\u4e00\u4e2a\u76f8\u5bf9\u8def\u5f84">{escape(editable_paths_text)}</textarea>',
            '<small class="field-hint">\u4e0d\u586b\u65f6\uff0c\u7cfb\u7edf\u4f1a\u5148\u6839\u636e\u4efb\u52a1\u63d0\u793a\u8def\u5f84\u6216\u4ed3\u5e93\u9876\u5c42\u7ed3\u6784\u8349\u62df\u53ef\u7f16\u8f91\u8303\u56f4\u3002</small></label>',
            '<label class="field-group" for="portal-live-forbidden-paths"><span>\u7981\u6b62\u4fee\u6539\u7684\u6587\u4ef6</span>',
            f'<textarea id="portal-live-forbidden-paths" class="code-input" rows="6" placeholder="\u4e00\u884c\u4e00\u4e2a\u76f8\u5bf9\u8def\u5f84">{escape(forbidden_paths_text)}</textarea>',
            '<small class="field-hint">\u4e0d\u60f3\u8ba9\u6a21\u578b\u78b0\u7684\u8def\u5f84\u653e\u8fd9\u91cc\u3002</small></label>',
            '<label class="field-group" for="portal-live-expected-changed-files"><span>\u9884\u671f\u6539\u52a8\u6587\u4ef6</span>',
            f'<textarea id="portal-live-expected-changed-files" class="code-input" rows="6" placeholder="\u4e00\u884c\u4e00\u4e2a\u76f8\u5bf9\u8def\u5f84">{escape(expected_changed_files_text)}</textarea>',
            '<small class="field-hint">\u7ed3\u679c\u5927\u81f4\u5e94\u8be5\u6539\u54ea\u4e9b\u6587\u4ef6\uff0c\u53ef\u4ee5\u5199\u5728\u8fd9\u91cc\u3002</small></label>',
            '<label class="field-group field-span-wide" for="portal-live-behavioral-checks"><span>\u9a8c\u6536\u8981\u70b9</span>',
            f'<textarea id="portal-live-behavioral-checks" class="code-input" rows="5" placeholder="\u4e00\u884c\u4e00\u4e2a\u9a8c\u6536\u8981\u70b9">{escape(behavioral_checks_text)}</textarea>',
            '<small class="field-hint">\u8fd9\u91cc\u5199\u4eba\u80fd\u770b\u61c2\u7684\u9a8c\u6536\u8981\u6c42\u3002</small></label>',
            '<label class="field-group field-span-wide" for="portal-live-acceptance-checks"><span>\u9a8c\u6536\u547d\u4ee4\uff08\u9ad8\u7ea7\uff09</span>',
            f'<textarea id="portal-live-acceptance-checks" class="code-input" rows="14" placeholder="[check-name]&#10;python&#10;-c&#10;print(&#39;replace me&#39;)">{escape(acceptance_checks_text)}</textarea>',
            f'<small class="field-hint">{escape(acceptance_checks_help_text)}</small></label>',
            '</div>',
            '</details>',
            '<div class="toolbar">',
            '<button id="portal-live-preview" class="button button-secondary" type="button">\u5237\u65b0\u4e09\u6863\u4ea4\u4ed8\u9884\u89c8</button>',
            f'<button id="portal-live-submit" class="button button-primary" type="button"{disabled_attr}>\u5f00\u59cb\u8fd0\u884c\u4e09\u6863</button>',
            '<div id="portal-live-links" class="link-row">',
            links_html,
            '</div>',
            '</div>',
            '<div class="history-wrap">',
            '<div class="panel-head panel-head-compact">',
            '<h3>\u6700\u8fd1\u4efb\u52a1</h3>',
            '<p class="subtitle">\u70b9\u4e00\u4e0b\u5c31\u80fd\u628a\u4e0a\u6b21\u7684\u4efb\u52a1\u548c\u8bbe\u7f6e\u91cd\u65b0\u586b\u56de\uff1b\u56de\u586b\u540e\u5efa\u8bae\u5148\u5237\u65b0\u4ea4\u4ed8\u9884\u89c8\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u8fd0\u884c\u3002</p>',
            '</div>',
            f'<div id="portal-live-history">{recent_history_html}</div>',
            '</div>',
            '</section>',
            '<section class="panel">',
            '<div class="panel-head">',
            '<h2>\u4e09\u6863\u7ed3\u679c</h2>',
            '<p class="subtitle">\u8fd9\u91cc\u53ea\u663e\u793a\u4f60\u521a\u521a\u63d0\u4ea4\u90a3\u6b21\u4efb\u52a1\u7684\u4e09\u6863\u7ed3\u679c\uff1b\u9ed8\u8ba4\u4e0d\u518d\u9884\u88c5\u5386\u53f2\u7ed3\u679c\u3002</p>',
            '</div>',
            f'<div id="portal-live-results">{results_html}</div>',
            '</section>',
            f'<script id="portal-live-config" type="application/json">{config_json}</script>',
            f"<script>{_script()}</script>",
            '</div>',
            '</body>',
            '</html>',
        ]
    )


def _build_form_defaults(intake, *, hide_local_repo_source: bool = False) -> dict[str, str]:
    return build_portal_form_fields(intake, hide_local_repo_source=hide_local_repo_source)


def _join_values(values: list[str] | tuple[str, ...], empty_text: str) -> str:
    normalized = [str(item) for item in values if str(item)]
    return "、".join(normalized) if normalized else empty_text


def _render_string_list(items: list[str] | tuple[str, ...], *, empty_text: str) -> str:
    normalized = [str(item) for item in items if str(item)]
    if not normalized:
        return f'<div class="empty">{escape(empty_text)}</div>'
    return '<ul class="stack-list">' + ''.join(f'<li>{escape(item)}</li>' for item in normalized) + '</ul>'


def _render_harness_transition_card(payload: Mapping[str, object]) -> str:
    from_profile = str(payload.get("from_profile") or "")
    to_profile = str(payload.get("to_profile") or "")
    lines = [localize_harness_message(str(item)) for item in payload.get("summary_lines", ()) if str(item)]
    title = f"{_profile_label(from_profile)} -> {_profile_label(to_profile)}"
    return ''.join(
        [
            '<article class="history-card">',
            f'<h3>{escape(title)}</h3>',
            _render_string_list(lines, empty_text="当前没有新增说明。"),
            '</article>',
        ]
    )


def _render_harness_profile_card(profile: str, payload: Mapping[str, object]) -> str:
    includes_repo_tree = bool(payload.get("includes_repo_tree"))
    tree_file_count = payload.get("tree_file_count")
    context_files = [str(item) for item in payload.get("context_files", ()) if str(item)]
    context_file_count = int(payload.get("context_file_count", 0))
    max_context_files = int(payload.get("max_context_files", 0))
    input_names = [str(item) for item in payload.get("included_input_names", ()) if str(item)]
    verifier_steps = [str(item) for item in payload.get("included_verifier_steps", ()) if str(item)]
    notes = [localize_harness_message(str(item)) for item in payload.get("notes", ()) if str(item)]
    rows = [
        (f"仓库树：提供，当前仓库可见文件约 {tree_file_count} 个" if tree_file_count is not None else "仓库树：提供") if includes_repo_tree else "仓库树：不提供",
        "上下文文件：不提供" if max_context_files <= 0 else f"上下文文件：本次 {context_file_count} 个，上限 {max_context_files} 个",
        f"任务输入：{_join_values(input_names, '当前不注入')}",
        f"验收步骤：{_join_values(verifier_steps, '当前不注入')}",
    ]
    context_block = ''
    if context_files:
        context_block = ''.join(
            [
                '<details class="inline-details">',
                '<summary class="details-hint">查看这档实际带了哪些上下文</summary>',
                _render_string_list(context_files, empty_text="当前没有上下文文件。"),
                '</details>',
            ]
        )
    notes_block = ''
    if notes:
        notes_block = ''.join(
            [
                '<details class="inline-details">',
                '<summary class="details-hint">这档的补充说明</summary>',
                _render_string_list(notes, empty_text="当前没有补充说明。"),
                '</details>',
            ]
        )
    return ''.join(
        [
            '<article class="result-card">',
            '<div class="card-top">',
            f'<span class="badge badge-soft">{escape(_profile_label(profile))}</span>',
            '</div>',
            f'<h3>{escape(_profile_label(profile))}</h3>',
            _render_string_list(rows, empty_text="当前没有档位说明。"),
            context_block,
            notes_block,
            '</article>',
        ]
    )


def render_live_profile_explainer_markup(
    *,
    model_display_name: str,
    preview: Mapping[str, object],
    mode: str,
    used_draft_verifier: bool,
) -> str:
    task_preview = dict(preview.get("task_spec_preview") or {})
    profile_payloads = _preview_profile_payloads(preview)
    risk_warnings = [localize_harness_message(str(item)) for item in preview.get("risk_warnings", ()) if str(item)]
    if used_draft_verifier:
        risk_warnings.append("\u5f53\u524d\u9a8c\u6536\u662f\u8349\u7a3f completion verifier\uff1a\u5b83\u6839\u636e\u76ee\u6807\u6587\u4ef6\u3001\u4efb\u52a1\u951a\u70b9\u548c\u8303\u56f4\u7ea6\u675f\u4f30\u7b97\u5b8c\u6210\u5ea6\uff0c\u4ecd\u4e0d\u7b49\u4e8e\u771f\u5b9e\u4e1a\u52a1\u9a8c\u6536\u3002")
    input_names = [str(item) for item in task_preview.get("input_names", ()) if str(item)]
    verifier_steps = [str(item) for item in task_preview.get("verifier_step_names", ()) if str(item)]
    mode_note = {
        PORTAL_MODE_EXAMPLE: "\u5f53\u524d\u662f\u793a\u4f8b\u6a21\u677f\u6a21\u5f0f\uff1a\u9884\u89c8\u56f4\u7ed5\u53d7\u63a7\u6837\u672c\u5c55\u5f00\u3002",
        PORTAL_MODE_FREEFORM: "\u5f53\u524d\u662f\u81ea\u7531\u4efb\u52a1\u8349\u7a3f\u6a21\u5f0f\uff1alive \u4f1a\u5148\u628a\u4efb\u52a1\u5305\u88c5\u6210\u6700\u5c0f harness \u8fb9\u754c\uff0c\u518d\u5c55\u793a\u5f53\u524d\u4ea4\u4ed8\u3002",
        PORTAL_MODE_STRUCTURED: "\u5f53\u524d\u662f\u7ed3\u6784\u5316\u81ea\u5b9a\u4e49\u6a21\u5f0f\uff1a\u4f60\u5199\u4e0b\u7684 repo\u3001\u8303\u56f4\u548c verifier \u5c31\u662f\u5f53\u524d\u8fd0\u884c\u7684\u56fa\u5b9a\u8fb9\u754c\u3002",
    }.get(mode, "\u5f53\u524d\u662f live \u81ea\u5b9a\u4e49\u6a21\u5f0f\u3002")
    invariants = (
        mode_note,
        f"\u540c\u4e00\u6a21\u578b\uff1a{model_display_name}",
        "\u540c\u4e00\u4efb\u52a1\u6b63\u6587\uff1a\u9884\u89c8\u548c\u8fd0\u884c\u90fd\u4f7f\u7528\u540c\u4e00\u6761\u7528\u6237\u4efb\u52a1\u6587\u672c\u3002",
        "\u540c\u4e00\u4ed3\u5e93\u8fb9\u754c\uff1a\u9884\u89c8\u548c\u8fd0\u884c\u90fd\u9075\u5b88\u540c\u4e00\u4efd\u4ed3\u5e93\u8def\u5f84\u3001\u53ef\u7f16\u8f91\u8303\u56f4\u548c\u6210\u529f\u6807\u51c6\u3002",
        "\u540c\u4e00\u8f93\u51fa\u5951\u7ea6\uff1a\u6a21\u578b\u90fd\u5fc5\u987b\u8fd4\u56de\u540c\u4e00\u79cd JSON \u5199\u5165\u7ed3\u6784\u3002",
        f"\u5f53\u524d\u7ed3\u6784\u5316\u4efb\u52a1\u58f0\u660e\u4e86 {len(input_names)} \u4e2a\u4e1a\u52a1\u8f93\u5165\u3001{len(verifier_steps)} \u4e2a\u9a8c\u6536\u6b65\u9aa4\u3002",
        "\u771f\u6b63\u53d8\u5316\u7684\u53ea\u6709 harness \u989d\u5916\u4ea4\u7ed9\u6a21\u578b\u7684\u5185\u5bb9\uff1a\u4ed3\u5e93\u6811\u3001\u4e0a\u4e0b\u6587\u6587\u4ef6\u3001\u4efb\u52a1\u8f93\u5165\u3001verifier \u6b65\u9aa4\u3002",
    )
    profile_cards = "".join(
        _render_harness_profile_card(profile, payload)
        for profile, payload in profile_payloads
    )
    warning_block = (
        "".join(
            [
                '<details class="inline-details">',
                '<summary class="details-hint">\u5f53\u524d\u98ce\u9669\u63d0\u793a</summary>',
                _render_string_list(risk_warnings, empty_text="\u5f53\u524d\u6ca1\u6709\u989d\u5916\u98ce\u9669\u63d0\u793a\u3002"),
                '</details>',
            ]
        )
        if risk_warnings
        else ''
    )
    return "".join(
        [
            '<div class="example-box">',
            '<div class="example-title">\u4e3a\u4ec0\u4e48\u8fd9\u4e0d\u662f\u5355\u7eaf\u591a\u585e\u4e00\u70b9\u4e0a\u4e0b\u6587</div>',
            _render_string_list(invariants, empty_text="\u5f53\u524d\u6ca1\u6709\u63a7\u5236\u53d8\u91cf\u8bf4\u660e\u3002"),
            '</div>',
            '<div class="results-grid">',
            profile_cards,
            '</div>',
            '<div class="history-wrap">',
            '<div class="panel-head panel-head-compact">',
            '<h3>\u5f53\u524d\u4ea4\u4ed8\u5305\u542b\u4ec0\u4e48</h3>',
            '<p class="subtitle">\u8fd9\u91cc\u76f4\u63a5\u5217\u51fa\u5f53\u524d\u4ea4\u4ed8\u5305\u7684\u53ef\u89c1\u8f93\u5165\uff0c\u4e0d\u628a\u5173\u952e\u5dee\u5f02\u85cf\u5728\u62a5\u544a\u7ec6\u8282\u91cc\u3002</p>',
            '</div>',
            f'<div class="history-grid">{profile_cards}</div>' if profile_cards else '<div class="empty">\u5f53\u524d\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u4ea4\u4ed8\u5185\u5bb9\u3002</div>',
            warning_block,
            '</div>',
        ]
    )


def render_live_scope_markup(
    *,
    template_id: str,
    template_title: str,
    form_fields: Mapping[str, str],
    preview: Mapping[str, object],
    mode: str,
    autogenerated_fields: tuple[str, ...],
    used_draft_verifier: bool,
) -> str:
    task_preview = dict(preview.get("task_spec_preview") or {})
    editable_paths = [str(item) for item in task_preview.get("editable_paths", ()) if str(item)]
    expected_changed = [str(item) for item in task_preview.get("expected_changed_files", ()) if str(item)]
    verifier_steps = [str(item) for item in task_preview.get("verifier_step_names", ()) if str(item)]
    input_names = [str(item) for item in task_preview.get("input_names", ()) if str(item)]
    mode_label = {
        PORTAL_MODE_EXAMPLE: "\u793a\u4f8b\u6a21\u677f\u6a21\u5f0f",
        PORTAL_MODE_FREEFORM: "\u81ea\u7531\u4efb\u52a1\u8349\u7a3f\u6a21\u5f0f",
        PORTAL_MODE_STRUCTURED: "\u7ed3\u6784\u5316\u81ea\u5b9a\u4e49\u6a21\u5f0f",
    }.get(mode, "live \u6a21\u5f0f")
    mode_text = {
        PORTAL_MODE_EXAMPLE: "\u4f60\u73b0\u5728\u770b\u7684\u662f\u53d7\u63a7\u793a\u4f8b\u6a21\u677f\uff1a\u4e09\u6863\u5bf9\u6bd4\u4f7f\u7528\u7684\u662f\u8fd9\u4efd\u5df2\u77e5\u8fb9\u754c\u548c\u9a8c\u6536\u8bbe\u7f6e\u3002",
        PORTAL_MODE_FREEFORM: "\u4f60\u8f93\u5165\u7684\u662f\u4efb\u610f\u4efb\u52a1\uff0c\u7cfb\u7edf\u5df2\u6839\u636e\u4ed3\u5e93\u548c\u4efb\u52a1\u6b63\u6587\u81ea\u52a8\u8865\u4e86\u4e00\u4efd\u6700\u5c0f harness \u5305\u88c5\u3002\u5b83\u53ef\u4ee5\u8dd1\uff0c\u4f46\u4ecd\u5efa\u8bae\u4f60\u6309\u9700\u7ec6\u5316\u8303\u56f4\u548c verifier\u3002",
        PORTAL_MODE_STRUCTURED: "\u4f60\u5df2\u7ecf\u660e\u786e\u5199\u4e0b repo\u3001\u53ef\u7f16\u8f91\u8303\u56f4\u548c verifier\uff1b\u7cfb\u7edf\u4f1a\u6309\u8fd9\u4efd\u7ed3\u6784\u5316\u8bbe\u7f6e\u8fd0\u884c\u3002",
    }.get(mode, "\u5f53\u524d\u662f live \u81ea\u5b9a\u4e49\u6a21\u5f0f\u3002")
    repo_label = _portal_repo_source_label(str(form_fields.get("repo_path") or task_preview.get("repo_root") or "")) or "\u672a\u586b\u5199"
    task_shape_label = portal_task_shape_label(form_fields.get("task_shape") or "general")
    knowledge_pack_label = portal_knowledge_pack_label(form_fields.get("knowledge_pack") or "none")
    empty_declared = "\u672a\u58f0\u660e"
    no_inputs = "\u5f53\u524d\u6ca1\u6709\u989d\u5916\u4e1a\u52a1\u8f93\u5165"
    rows = [
        f"\u4efb\u52a1\u5f62\u6001\uff1a{task_shape_label}",
        f"\u6750\u6599\u5305\uff1a{knowledge_pack_label}",
        f"\u4ed3\u5e93\u6765\u6e90\uff1a{repo_label}",
        f"\u5141\u8bb8\u4fee\u6539\uff1a{_join_values(editable_paths, empty_declared)}",
        f"\u9884\u671f\u6539\u52a8\uff1a{_join_values(expected_changed, empty_declared)}",
        f"\u9a8c\u6536\u68c0\u67e5\uff1a{_join_values(verifier_steps, empty_declared)}",
        f"\u4e1a\u52a1\u8f93\u5165\uff1a{_join_values(input_names, no_inputs)}",
        f"\u5165\u53e3\u6a21\u677f\uff1a{template_title}\uff08{template_id}\uff09",
    ]
    if mode == PORTAL_MODE_FREEFORM and autogenerated_fields:
        auto_labels = [_autogenerated_field_label(item) for item in autogenerated_fields]
        rows.insert(0, "\u81ea\u52a8\u8865\u9f50\uff1a" + _join_values(auto_labels, "\u65e0"))
    if used_draft_verifier:
        rows.append("\u5f53\u524d verifier\uff1a\u8349\u7a3f completion check\uff0c\u4f1a\u6309\u76ee\u6807\u6587\u4ef6\u3001\u4efb\u52a1\u951a\u70b9\u548c\u8303\u56f4\u7ea6\u675f\u4f30\u7b97\u5b8c\u6210\u5ea6\u3002")
    return "".join(
        [
            '<div class="example-box">',
            '<div class="entry-top">',
            f'<span class="badge badge-soft">{escape(mode_label)}</span>',
            f'<span class="badge badge-soft">\u6a21\u677f\uff1a{escape(template_id)}</span>',
            '</div>',
            f'<p class="subtitle">{escape(mode_text)}</p>',
            '<ul class="stack-list">',
            ''.join(f'<li>{escape(item)}</li>' for item in rows),
            '</ul>',
            '</div>',
        ]
    )


def _render_scope_placeholder_markup(*, entry_title: str) -> str:
    rows = (
        "\u9ed8\u8ba4\u8fdb\u5165\u81ea\u7531\u4efb\u52a1\u8349\u7a3f\u6001\uff0c\u4e0d\u518d\u9884\u88c5\u5386\u53f2 focus case \u3002",
        "\u5148\u586b\u4efb\u52a1\u6b63\u6587 + \u4ed3\u5e93\u8def\u5f84\uff0clive \u4f1a\u4e3a\u4f60\u751f\u6210\u4e00\u4efd\u5f53\u524d harness \u5305\u88c5\u3002",
        "\u5982\u679c\u60f3\u770b\u53d7\u63a7\u6837\u672c\uff0c\u53ef\u4ee5\u70b9\u201c\u586b\u5165\u793a\u4f8b\u201d\uff0c\u5207\u56de\u6a21\u677f\uff1a" + entry_title,
    )
    return "".join(
        [
            '<div class="example-box">',
            '<div class="entry-top">',
            '<span class="badge badge-soft">\u7b49\u5f85\u751f\u6210\u8fb9\u754c</span>',
            '</div>',
            _render_string_list(rows, empty_text="\u8bf7\u5148\u586b\u8868\u5355\u3002"),
            '</div>',
        ]
    )


def _render_profile_placeholder_markup(*, model_display_name: str) -> str:
    rows = (
        f"\u5f53\u524d\u6a21\u578b\uff1a{model_display_name}",
        "\u5148\u586b\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u8def\u5f84\uff0c\u518d\u70b9\u201c\u5237\u65b0\u4e09\u6863\u4ea4\u4ed8\u9884\u89c8\u201d\u3002",
        "\u9884\u89c8\u540e\u8fd9\u91cc\u4f1a\u76f4\u63a5\u5c55\u793a\u5f53\u524d\u4ea4\u4ed8\u4f1a\u4ea4\u7ed9\u6a21\u578b\u4ec0\u4e48\uff0c\u4e0d\u7528\u5148\u53bb\u7ffb\u62a5\u544a\u6216 live \u7ed3\u679c\u3002",
    )
    return "".join(
        [
            '<div class="example-box">',
            '<div class="example-title">\u4e09\u6863\u4ea4\u4ed8\u9884\u89c8\u8fd8\u6ca1\u751f\u6210</div>',
            _render_string_list(rows, empty_text="\u8bf7\u5148\u586b\u8868\u5355\u3002"),
            '</div>',
        ]
    )


def _autogenerated_field_label(name: str) -> str:
    return {
        "context_paths": "\u4e0a\u4e0b\u6587\u6587\u4ef6",
        "editable_paths": "\u53ef\u7f16\u8f91\u8303\u56f4",
        "expected_changed_files": "\u9884\u671f\u6539\u52a8\u6587\u4ef6",
        "behavioral_checks": "\u9a8c\u6536\u8981\u70b9",
        "acceptance_checks": "\u8349\u7a3f verifier",
    }.get(name, name)


def _preview_bundle(
    *,
    plan: PortalSubmissionPlan,
    source_path: Path | None,
    template_id: str,
    template_title: str,
    template_form_defaults: Mapping[str, str],
    model_display_name: str,
) -> dict[str, object]:
    preview = build_task_intake_preview(plan.intake, source_path=source_path, repo_root_override=plan.resolved_repo_root)
    return {
        "preview": preview,
        "scope_html": render_live_scope_markup(
            template_id=template_id,
            template_title=template_title,
            form_fields=plan.form_fields,
            preview=preview,
            mode=plan.mode,
            autogenerated_fields=plan.autogenerated_fields,
            used_draft_verifier=plan.used_draft_verifier,
        ),
        "profile_explainer_html": render_live_profile_explainer_markup(
            model_display_name=model_display_name,
            preview=preview,
            mode=plan.mode,
            used_draft_verifier=plan.used_draft_verifier,
        ),
    }


def _serialize_line_block(values: tuple[str, ...]) -> str:
    return "\n".join(str(value) for value in values if str(value).strip())


def _serialize_acceptance_checks(steps: tuple[VerifierStep, ...]) -> str:
    blocks: list[str] = []
    for step in steps:
        lines = [f"[{step.name}]", f"kind={step.kind.value}", f"required={'true' if step.required else 'false'}"]
        if step.notes:
            lines.append(f"notes={step.notes}")
        lines.extend(step.command)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _submitted_optional_text(submission: Mapping[str, object], key: str) -> str | None:
    if key not in submission:
        return None
    value = str(submission.get(key) or "").strip()
    return value or None


def _submitted_required_text(
    submission: Mapping[str, object],
    *,
    key: str,
    fallback: str,
    field_label: str,
) -> str:
    if key not in submission:
        return fallback
    value = str(submission.get(key) or "").strip()
    if not value:
        raise ValueError(f"请填写{field_label}。")
    return value


def _submitted_line_block(
    submission: Mapping[str, object],
    key: str,
    *,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    if key not in submission:
        return fallback
    return _parse_line_block(submission.get(key))


def _submitted_acceptance_checks(
    submission: Mapping[str, object],
    *,
    key: str,
    fallback: tuple[VerifierStep, ...],
) -> tuple[VerifierStep, ...]:
    if key not in submission:
        return fallback
    return _parse_acceptance_checks_text(submission.get(key))


def _parse_line_block(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(line.strip() for line in str(value).splitlines() if line.strip())


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
            raise ValueError("验收命令格式错误：每个检查都要用 [检查名] 开头。")
        name = header[1:-1].strip()
        if not name:
            raise ValueError("验收命令格式错误：检查名不能为空。")
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
            raise ValueError(f"验收检查 {name} 缺少命令参数。")
        steps.append(
            VerifierStep(
                name=name,
                kind=kind,
                command=tuple(command),
                required=required,
                notes=notes,
            )
        )
    return tuple(steps)


def _normalize_freeform_text(value: str) -> str:
    return " ".join(str(value).split())


def _parse_required_flag(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "required"}:
        return True
    if normalized in {"false", "0", "no", "n", "optional"}:
        return False
    raise ValueError(f"验收命令格式错误：无法识别 required={value}。")


def _history_store_path(settings: Settings) -> Path:
    return settings.paths.runtime_root / _PORTAL_HISTORY_FILE_NAME


def _load_raw_live_history_entries(settings: Settings) -> list[Mapping[str, object]]:
    path = _history_store_path(settings)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, Mapping)]


def _load_live_submission_history(*, settings: Settings, template_id: str, limit: int = _PORTAL_HISTORY_LIMIT) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for item in _load_raw_live_history_entries(settings):
        if str(item.get("template_id") or "") != template_id:
            continue
        form_fields = item.get("form_fields")
        if not isinstance(form_fields, Mapping):
            continue
        form_payload = {str(key): str(value) for key, value in form_fields.items()}
        task_text = str(form_payload.get("task_text") or "").strip()
        if not task_text:
            continue
        normalized.append(
            {
                "submission_id": str(item.get("submission_id") or ""),
                "template_id": template_id,
                "title": str(item.get("title") or form_payload.get("title") or "未命名任务"),
                "task_text": task_text,
                "repo_path": str(item.get("repo_path") or form_payload.get("repo_path") or ""),
                "suite_id": str(item.get("suite_id") or ""),
                "form_fields": form_payload,
            }
        )
        if len(normalized) >= limit:
            break
    return normalized


def _store_live_submission_history(
    *,
    settings: Settings,
    template_id: str,
    title: str,
    suite_id: str,
    form_fields: Mapping[str, str],
) -> list[dict[str, object]]:
    path = _history_store_path(settings)
    normalized_form_fields = {str(key): str(value) for key, value in form_fields.items()}
    other_templates: list[Mapping[str, object]] = []
    same_template: list[dict[str, object]] = []
    for item in _load_raw_live_history_entries(settings):
        if str(item.get("template_id") or "") != template_id:
            other_templates.append(item)
            continue
        item_form_fields = item.get("form_fields")
        if isinstance(item_form_fields, Mapping):
            comparable = {str(key): str(value) for key, value in item_form_fields.items()}
            if comparable == normalized_form_fields:
                continue
        same_template.append(dict(item))

    entry = {
        "submission_id": new_id("history"),
        "template_id": template_id,
        "title": title,
        "task_text": normalized_form_fields.get("task_text", ""),
        "repo_path": normalized_form_fields.get("repo_path", ""),
        "suite_id": suite_id,
        "form_fields": normalized_form_fields,
    }
    same_template = [entry, *same_template][:20]
    try:
        path.write_text(json.dumps([*same_template, *other_templates], ensure_ascii=False, indent=2), encoding="utf8")
    except OSError:
        return [entry, *same_template][: _PORTAL_HISTORY_LIMIT]
    return _load_live_submission_history(settings=settings, template_id=template_id)


def _build_focus_payload(
    *,
    record_store: RunRecordStore,
    target_task_id: str | None = None,
    report_id: str | None = None,
) -> dict[str, object]:
    report: StoredEvalReport | None = None
    case: StoredEvalCase | None = None
    if report_id:
        report = record_store.load_eval_report(report_id)
        case = _match_case(report, target_task_id=target_task_id)
    else:
        for candidate in record_store.list_eval_report_records(limit=50):
            matched_case = _match_case(candidate, target_task_id=target_task_id)
            if matched_case is not None:
                report = candidate
                case = matched_case
                break
            if report is None and candidate.case_results:
                report = candidate
                case = candidate.case_results[0]
    if report is None or case is None:
        return {"results": [], "links": []}

    baseline_run_id = _baseline_run_id(case)
    results: list[dict[str, object]] = []
    for trial in sorted(case.trials, key=lambda item: _profile_sort_key(item.harness_profile or "custom")):
        summary = trial.run_summary
        if summary is None:
            continue
        record = record_store.load_run_record(summary.run_id)
        comparison_path = None
        if baseline_run_id and baseline_run_id != summary.run_id:
            comparison_path = f"/{_compare_filename(baseline_run_id, summary.run_id)}"
        results.append(
            {
                "profile": trial.harness_profile,
                "profile_label": _profile_label(trial.harness_profile),
                "status": summary.status.value,
                "status_label": _status_label(summary.status.value),
                "verifier": summary.verifier_outcome or "not_run",
                "verifier_label": _verifier_label(summary.verifier_outcome),
                "duration_text": _format_duration(summary.duration_ms),
                "output_text": _extract_task_output_text(record.patch_diff),
                "result_items": list(_feedback_items(record, summary)),
                "run_report_path": f"/runs/{summary.run_id}/report.html",
                "comparison_path": comparison_path,
            }
        )
    links = [
        {"label": "\u5957\u4ef6\u7ed3\u679c", "href": f"/{report.html_path.name}"},
        {"label": "Uplift \u603b\u89c8", "href": "/uplift-dashboard.html"},
        {"label": "\u8fd0\u884c\u5217\u8868", "href": "/runs-dashboard.html"},
    ]
    return {"results": results, "links": links}


def _render_result_card(result: dict[str, object]) -> str:
    result_items = list(result.get("result_items") or ["\u5f53\u524d\u6ca1\u6709\u989d\u5916\u8bf4\u660e\u3002"])
    output_text = str(result.get("output_text") or "") or "\u5f53\u524d\u6ca1\u6709\u63d0\u53d6\u5230\u663e\u5f0f\u8f93\u51fa\u3002"
    actions = [
        f'<a class="button button-secondary" href="{escape(str(result.get("run_report_path") or "#"))}">\u8fd0\u884c\u62a5\u544a</a>',
    ]
    comparison_path = str(result.get("comparison_path") or "")
    if comparison_path:
        actions.append(f'<a class="button button-secondary" href="{escape(comparison_path)}">\u5bf9\u6bd4\u9875</a>')
    badge_class = f'badge badge-status badge-status-{escape(str(result.get("status") or "pending"))}'
    return "".join(
        [
            '<article class="result-card">',
            '<div class="card-top">',
            f'<span class="badge badge-soft">{escape(str(result.get("profile_label") or ""))}</span>',
            f'<span class="{badge_class}">{escape(str(result.get("status_label") or ""))}</span>',
            "</div>",
            '<div class="meta-row">',
            f'<span>\u9a8c\u8bc1\uff1a{escape(str(result.get("verifier_label") or ""))}</span>',
            f'<span>\u8017\u65f6\uff1a{escape(str(result.get("duration_text") or ""))}</span>',
            "</div>",
            '<h3>\u4efb\u52a1\u8f93\u51fa</h3>',
            f"<pre>{escape(output_text)}</pre>",
            '<h4>\u5904\u7406\u7ed3\u679c</h4>',
            '<ul class="stack-list">',
            "".join(f"<li>{escape(str(item))}</li>" for item in result_items),
            "</ul>",
            '<div class="actions">',
            "".join(actions),
            "</div>",
            "</article>",
        ]
    )


def _match_case(report: StoredEvalReport, *, target_task_id: str | None) -> StoredEvalCase | None:
    if target_task_id:
        for case in report.case_results:
            if case.case_id == target_task_id:
                return case
    return report.case_results[0] if report.case_results else None


def _feedback_items(record: StoredRunRecord, summary: RunSummary) -> tuple[str, ...]:
    draft_feedback = build_draft_completion_feedback(record.verifier_result)
    if draft_feedback:
        if summary.status is RunStatus.SUCCEEDED and summary.verifier_outcome == "passed":
            items = ("Draft completion threshold reached.", *draft_feedback)
        else:
            items = ("Draft completion threshold not reached.", *draft_feedback)
        return tuple(_localize_feedback_message(item) for item in items if item)

    if summary.status is RunStatus.SUCCEEDED and summary.verifier_outcome == "passed":
        items = ("\u5df2\u901a\u8fc7\u9a8c\u8bc1\u3002",)
    elif summary.status is RunStatus.SUCCEEDED:
        items = ("\u5df2\u5b8c\u6210\u8fd0\u884c\u3002",)
    else:
        items: tuple[str, ...] = ()
        failure_summary = build_failure_summary(record)
        if failure_summary:
            items = tuple(failure_summary[:3])
        if not items and summary.notes:
            items = tuple(str(item) for item in summary.notes[:3])
        if not items:
            hint = pick_failure_hint(summary)
            if hint:
                items = (hint,)
        if not items:
            items = ("\u5f53\u524d\u6ca1\u6709\u989d\u5916\u7ed3\u679c\u8bf4\u660e\u3002",)
    return tuple(_localize_feedback_message(item) for item in items if item)


def _localize_feedback_message(text: str) -> str:
    normalized = " ".join(str(text).split())
    if not normalized:
        return ""
    exact = {
        "The run stopped before deterministic verification produced a result.": "\u8fd0\u884c\u5728\u786e\u5b9a\u6027\u9a8c\u8bc1\u5b8c\u6210\u524d\u5c31\u505c\u6b62\u4e86\u3002",
        "The run did not leave any file changes.": "\u672c\u6b21\u8fd0\u884c\u6ca1\u6709\u7559\u4e0b\u6587\u4ef6\u6539\u52a8\u3002",
        "Draft completion threshold reached.": "\u8349\u7a3f\u5b8c\u6210\u5ea6\u5df2\u8fbe\u5230\u5f53\u524d\u9608\u503c\u3002",
        "Draft completion threshold not reached.": "\u8349\u7a3f\u5b8c\u6210\u5ea6\u672a\u8fbe\u5230\u5f53\u524d\u9608\u503c\u3002",
        "no file changes detected in workspace": "\u5de5\u4f5c\u533a\u6ca1\u6709\u68c0\u6d4b\u5230\u6587\u4ef6\u6539\u52a8\u3002",
        "failed": "\u5931\u8d25",
        "passed": "\u901a\u8fc7",
    }
    if normalized in exact:
        return exact[normalized]
    if normalized.startswith("Run note: "):
        return "\u8fd0\u884c\u5907\u6ce8\uff1a" + normalized.removeprefix("Run note: ")
    if normalized.startswith("Direct error: "):
        return "\u76f4\u63a5\u9519\u8bef\uff1a" + normalized.removeprefix("Direct error: ")
    if normalized.startswith("Failed check: "):
        return "\u5931\u8d25\u68c0\u67e5\uff1a" + normalized.removeprefix("Failed check: ")
    if normalized.startswith("Command output: "):
        return "\u547d\u4ee4\u8f93\u51fa\uff1a" + normalized.removeprefix("Command output: ")
    if normalized.startswith("Command exited with code "):
        return "\u547d\u4ee4\u9000\u51fa\u7801\uff1a" + normalized.removeprefix("Command exited with code ")
    draft_score = re.fullmatch(r"draft completion score: ([0-9.]+) / 1.00 \(threshold ([0-9.]+)\)", normalized)
    if draft_score is not None:
        return f"\u8349\u7a3f\u5b8c\u6210\u5ea6\u5206\uff1a{draft_score.group(1)} / 1.00\uff08\u9608\u503c {draft_score.group(2)}\uff09"
    expected_match = re.fullmatch(r"expected files matched: (\d+)/(\d+) \((.*)\)", normalized)
    if expected_match is not None:
        return f"\u76ee\u6807\u6587\u4ef6\u547d\u4e2d\uff1a{expected_match.group(1)}/{expected_match.group(2)}\uff08{expected_match.group(3)}\uff09"
    changed_detected = re.fullmatch(r"changed files detected: (.+)", normalized)
    if changed_detected is not None:
        return f"\u5df2\u68c0\u6d4b\u5230\u6539\u52a8\u6587\u4ef6\uff1a{changed_detected.group(1)}"
    anchor_match = re.fullmatch(r"task anchors matched: (\d+)/(\d+) \((.*)\)", normalized)
    if anchor_match is not None:
        return f"\u4efb\u52a1\u951a\u70b9\u547d\u4e2d\uff1a{anchor_match.group(1)}/{anchor_match.group(2)}\uff08{anchor_match.group(3)}\uff09"
    missing_expected = re.fullmatch(r"missing expected changed files: (.+)", normalized)
    if missing_expected is not None:
        return f"\u7f3a\u5c11\u76ee\u6807\u6539\u52a8\u6587\u4ef6\uff1a{missing_expected.group(1)}"
    missing_anchors = re.fullmatch(r"task anchors not reflected in changed content: (.+)", normalized)
    if missing_anchors is not None:
        return f"\u6539\u52a8\u5185\u5bb9\u672a\u4f53\u73b0\u8fd9\u4e9b\u4efb\u52a1\u951a\u70b9\uff1a{missing_anchors.group(1)}"
    scope_violation = re.fullmatch(r"changed files escaped drafted scope: (.+)", normalized)
    if scope_violation is not None:
        return f"\u6539\u52a8\u8d85\u51fa\u4e86\u8349\u62df\u8303\u56f4\uff1a{scope_violation.group(1)}"
    weak_confidence = re.fullmatch(r"draft completion confidence is weak: (.+)", normalized)
    if weak_confidence is not None:
        return f"\u8349\u7a3f\u5b8c\u6210\u5ea6\u4fe1\u53f7\u504f\u5f31\uff1a{weak_confidence.group(1)}"
    low_score = re.fullmatch(r"completion score ([0-9.]+) is below threshold ([0-9.]+)", normalized)
    if low_score is not None:
        return f"\u5b8c\u6210\u5ea6\u5206 {low_score.group(1)} \u4f4e\u4e8e\u901a\u8fc7\u9608\u503c {low_score.group(2)}"

    verifier_failed = re.fullmatch(r"The verifier `(.+)` did not pass\.", normalized)
    if verifier_failed is not None:
        return f"\u9a8c\u8bc1\u5668 `{verifier_failed.group(1)}` \u672a\u901a\u8fc7\u3002"
    verifier_error = re.fullmatch(r"The verifier `(.+)` hit an internal error\.", normalized)
    if verifier_error is not None:
        return f"\u9a8c\u8bc1\u5668 `{verifier_error.group(1)}` \u53d1\u751f\u5185\u90e8\u9519\u8bef\u3002"
    verifier_skipped = re.fullmatch(r"The verifier `(.+)` was skipped, so there is no proof of success\.", normalized)
    if verifier_skipped is not None:
        return f"\u9a8c\u8bc1\u5668 `{verifier_skipped.group(1)}` \u88ab\u8df3\u8fc7\uff0c\u76ee\u524d\u6ca1\u6709\u6210\u529f\u8bc1\u636e\u3002"
    step_exit = re.fullmatch(r"(.+): command exited with code (\d+)", normalized)
    if step_exit is not None:
        return f"{step_exit.group(1)}\uff1a\u547d\u4ee4\u9000\u51fa\u7801 {step_exit.group(2)}"
    step_failed = re.fullmatch(r"(.+): failed", normalized, flags=re.IGNORECASE)
    if step_failed is not None:
        return f"{step_failed.group(1)}\uff1a\u5931\u8d25"
    if normalized.startswith("verifier="):
        verifier_value = normalized.removeprefix("verifier=")
        verifier_labels = {"passed": "\u901a\u8fc7", "failed": "\u672a\u901a\u8fc7", "not_run": "\u672a\u6267\u884c"}
        return "\u9a8c\u8bc1\u7ed3\u679c\uff1a" + verifier_labels.get(verifier_value, verifier_value)
    return normalized


def _extract_task_output_text(patch_diff: str | None, *, max_lines: int = 18) -> str:
    if not patch_diff:
        return ""
    extracted: list[str] = []
    for line in patch_diff.splitlines():
        if line.startswith(("diff --git", "index ", "--- ", "+++ ", "@@")):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            extracted.append(line[1:])
    lines = extracted or patch_diff.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... \u53e6\u6709 {len(lines) - max_lines} \u884c\u672a\u5c55\u5f00"]
    return "\n".join(lines).strip()


def _baseline_run_id(case: StoredEvalCase) -> str | None:
    for profile_name in ("current", "custom"):
        for trial in case.trials:
            if trial.run_summary is not None and trial.harness_profile == profile_name:
                return trial.run_summary.run_id
    for trial in case.trials:
        if trial.run_summary is not None:
            return trial.run_summary.run_id
    return None


def _profile_sort_key(profile: str) -> tuple[int, str]:
    order = {"current": 0, "custom": 1}
    return order.get(profile, 99), profile


def _profile_label(profile: str) -> str:
    labels = {
        "current": "Current package",
        "custom": "Custom baseline",
    }
    return labels.get(profile, profile)


def _preview_profile_payloads(preview: Mapping[str, object]) -> list[tuple[str, dict[str, object]]]:
    payloads: list[tuple[str, dict[str, object]]] = []
    current_delivery = dict(preview.get("current_delivery") or {})
    if current_delivery:
        payloads.append((str(current_delivery.get("profile") or "current"), current_delivery))
    custom_delivery = dict(preview.get("custom_delivery") or {})
    if custom_delivery:
        payloads.append((str(custom_delivery.get("profile") or "custom"), custom_delivery))
    return payloads


def _status_label(status: str) -> str:
    labels = {
        "succeeded": "\u6210\u529f",
        "failed": "\u5931\u8d25",
        "error": "\u9519\u8bef",
        "running": "\u8fd0\u884c\u4e2d",
        "pending": "\u7b49\u5f85\u4e2d",
        "skipped": "\u5df2\u8df3\u8fc7",
    }
    return labels.get(status, status)


def _verifier_label(verifier: str | None) -> str:
    if verifier == "passed":
        return "\u901a\u8fc7"
    if verifier == "failed":
        return "\u672a\u901a\u8fc7"
    if verifier == "not_run" or verifier is None:
        return "\u672a\u6267\u884c"
    return verifier


def _format_duration(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "n/a"
    if duration_ms < 1000:
        return f"{duration_ms} ms"
    return f"{duration_ms / 1000:.2f} s"


def _model_display_name(provider: str, model: str) -> str:
    provider_key = provider.strip().lower()
    provider_display = _PROVIDER_DISPLAY_NAMES.get(provider_key, provider.strip() or "\u672a\u77e5\u63d0\u4f9b\u65b9")
    return f"{provider_display} / {model}"


def _template_id_from_path(path: Path) -> str:
    return path.stem.removesuffix("_task_intake")


def _compare_filename(left_run_id: str, right_run_id: str) -> str:
    return f"compare-{_safe_file_stem(left_run_id)}-vs-{_safe_file_stem(right_run_id)}.html"


def _safe_file_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip("-")
    return sanitized or "portal-intake"


def _styles() -> str:
    return """
:root {
  --bg: #f4efe4;
  --panel: rgba(255, 255, 255, 0.82);
  --panel-border: rgba(26, 49, 60, 0.12);
  --ink: #14212b;
  --muted: #5e6a73;
  --accent: #0f766e;
  --warm: #c46c2d;
  --danger: #b42318;
  --ok: #1f7a1f;
  --shadow: 0 18px 50px rgba(20, 33, 43, 0.12);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(circle at top left, rgba(196, 108, 45, 0.18), transparent 32%),
    radial-gradient(circle at top right, rgba(15, 118, 110, 0.18), transparent 34%),
    linear-gradient(180deg, #f8f3ea 0%, #eef2ef 100%);
  font-family: "Aptos", "Microsoft YaHei UI", sans-serif;
}
h1, h2, h3, h4 {
  font-family: Georgia, "Times New Roman", serif;
  margin: 0;
}
a { color: inherit; text-decoration: none; }
pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  background: rgba(20, 33, 43, 0.06);
  border-radius: 14px;
  padding: 12px;
  font-family: "Cascadia Mono", Consolas, monospace;
}
.page-shell {
  max-width: 1120px;
  margin: 0 auto;
  padding: 28px 20px 40px;
}
.hero,
.panel,
.result-card {
  background: var(--panel);
  backdrop-filter: blur(14px);
  border: 1px solid var(--panel-border);
  border-radius: 24px;
  box-shadow: var(--shadow);
}
.hero {
  background: linear-gradient(135deg, rgba(20, 33, 43, 0.98), rgba(15, 118, 110, 0.93));
  color: #fbfaf7;
  padding: 32px;
}
.hero p {
  max-width: 820px;
  margin: 12px 0 0;
  color: rgba(251, 250, 247, 0.82);
}
.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.18em;
  font-size: 0.75rem;
  color: rgba(251, 250, 247, 0.72);
}
.hero-badges,
.entry-top,
.toolbar,
.link-row,
.actions,
.card-top,
.meta-row,
.example-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.hero-badges {
  margin-top: 18px;
}
.panel {
  margin-top: 18px;
  padding: 18px;
}
.panel-head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
.subtitle,
.status-note,
.meta-row,
.field-hint {
  color: var(--muted);
}
.input-label,
.field-group span {
  font-size: 0.96rem;
  font-weight: 600;
}
.text-input,
.task-input,
.code-input {
  width: 100%;
  border: 1px solid rgba(20, 33, 43, 0.12);
  border-radius: 18px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.72);
  color: var(--ink);
  font: inherit;
  line-height: 1.7;
}
.task-input,
.code-input {
  resize: vertical;
}
.task-input {
  min-height: 168px;
}
.code-input {
  min-height: 132px;
  font-family: "Cascadia Mono", Consolas, monospace;
  line-height: 1.55;
}
.example-box,
.advanced-box {
  border: 1px solid rgba(20, 33, 43, 0.1);
  border-radius: 18px;
  padding: 14px;
  background: rgba(255, 255, 255, 0.58);
  margin-top: 12px;
}
.example-head {
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.example-title {
  font-size: 0.88rem;
  color: var(--muted);
}
.example-box pre {
  padding: 0;
  background: transparent;
}
.advanced-box summary {
  cursor: pointer;
  font-weight: 600;
}
.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 14px;
}
.field-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field-group small {
  margin: 0;
}
.field-span-wide {
  grid-column: 1 / -1;
}
.toolbar {
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
}
.history-wrap {
  margin-top: 18px;
}
.panel-head-compact {
  margin-bottom: 10px;
}
.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.history-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border-radius: 18px;
  border: 1px solid rgba(20, 33, 43, 0.1);
  background: rgba(255, 255, 255, 0.68);
}
.history-card p {
  margin: 0;
}
.history-meta,
.history-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}
.history-meta {
  color: var(--muted);
}
.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.result-card {
  padding: 18px;
}
.result-card h3 {
  margin: 14px 0 10px;
  font-size: 1.08rem;
}
.result-card h4 {
  margin: 14px 0 8px;
  font-size: 0.94rem;
}
.meta-row {
  margin: 12px 0 16px;
}
.stack-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 0.78rem;
}
.badge-hero {
  background: rgba(255, 255, 255, 0.14);
  color: #fbfaf7;
}
.badge-soft {
  background: rgba(15, 118, 110, 0.12);
  color: var(--accent);
}
.badge-status {
  background: rgba(20, 33, 43, 0.08);
}
.badge-status-succeeded {
  background: rgba(31, 122, 31, 0.12);
  color: var(--ok);
}
.badge-status-failed,
.badge-status-error {
  background: rgba(180, 35, 24, 0.12);
  color: var(--danger);
}
.badge-status-running,
.badge-status-pending,
.badge-status-skipped {
  background: rgba(196, 108, 45, 0.12);
  color: var(--warm);
}
.button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 10px 14px;
  border-radius: 999px;
  border: 1px solid rgba(20, 33, 43, 0.12);
  background: rgba(255, 255, 255, 0.78);
  cursor: pointer;
}
.button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.button-primary {
  background: var(--ink);
  color: #fbfaf7;
  border-color: transparent;
}
.button-secondary {
  background: rgba(255, 255, 255, 0.72);
}
.empty {
  border: 1px dashed rgba(20, 33, 43, 0.18);
  border-radius: 18px;
  padding: 18px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.5);
}
@media (max-width: 720px) {
  .page-shell {
    padding: 16px 12px 28px;
  }
  .hero {
    padding: 24px;
  }
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .field-grid {
    grid-template-columns: 1fr;
  }
  .results-grid {
    grid-template-columns: 1fr;
  }
}
"""


def _script() -> str:
    return """
(() => {
  const configEl = document.getElementById("portal-live-config");
  if (!configEl) {
    return;
  }
  const config = JSON.parse(configEl.textContent || "{}");
  const titleInput = document.getElementById("portal-live-title-input");
  const textarea = document.getElementById("portal-live-task-input");
  const taskShapeInput = document.getElementById("portal-live-task-shape");
  const knowledgePackInput = document.getElementById("portal-live-knowledge-pack");
  const repoPathInput = document.getElementById("portal-live-repo-path");
  const contextPathsInput = document.getElementById("portal-live-context-paths");
  const editablePathsInput = document.getElementById("portal-live-editable-paths");
  const forbiddenPathsInput = document.getElementById("portal-live-forbidden-paths");
  const expectedChangedFilesInput = document.getElementById("portal-live-expected-changed-files");
  const behavioralChecksInput = document.getElementById("portal-live-behavioral-checks");
  const acceptanceChecksInput = document.getElementById("portal-live-acceptance-checks");
  const useExampleButton = document.getElementById("portal-live-use-example");
  const previewButton = document.getElementById("portal-live-preview");
  const submitButton = document.getElementById("portal-live-submit");
  const statusNode = document.getElementById("portal-live-status");
  const resultsNode = document.getElementById("portal-live-results");
  const linksNode = document.getElementById("portal-live-links");
  const historyNode = document.getElementById("portal-live-history");
  const scopeNode = document.getElementById("portal-live-scope");
  const profileExplainerNode = document.getElementById("portal-live-profile-explainer");
  const initialEnabled = !!(config && config.api_ready);
  const defaultPollAfterMs = Number((config && config.poll_after_ms) || 1500);

  function setStatus(message) {
    if (statusNode) {
      statusNode.textContent = message || "";
    }
  }

  function setRunBusy(isBusy) {
    if (submitButton) {
      submitButton.disabled = isBusy || !initialEnabled;
    }
    if (previewButton) {
      previewButton.disabled = !!isBusy;
    }
    if (useExampleButton) {
      useExampleButton.disabled = !!isBusy;
    }
  }

  function setValue(node, value) {
    if (node) {
      node.value = value || "";
    }
  }

  function applyFormData(form) {
    const payload = form || {};
    setValue(titleInput, payload.title || "");
    setValue(textarea, payload.task_text || "");
    setValue(taskShapeInput, payload.task_shape || "general");
    setValue(knowledgePackInput, payload.knowledge_pack || "none");
    setValue(repoPathInput, payload.repo_path || payload.repo_source || "");
    setValue(contextPathsInput, payload.context_paths_text || "");
    setValue(editablePathsInput, payload.editable_paths_text || "");
    setValue(forbiddenPathsInput, payload.forbidden_paths_text || "");
    setValue(expectedChangedFilesInput, payload.expected_changed_files_text || "");
    setValue(behavioralChecksInput, payload.behavioral_checks_text || "");
    setValue(acceptanceChecksInput, payload.acceptance_checks_text || "");
  }

  function applyServerUpdate(payload) {
    if (payload && payload.form_fields) {
      applyFormData(payload.form_fields);
    }
    if (scopeNode && payload && payload.scope_html) {
      scopeNode.innerHTML = payload.scope_html;
    }
    if (profileExplainerNode && payload && payload.profile_explainer_html) {
      profileExplainerNode.innerHTML = payload.profile_explainer_html;
    }
  }

  function applyRunResult(result) {
    applyServerUpdate(result);
    if (resultsNode) {
      resultsNode.innerHTML = result.results_html || "";
    }
    if (linksNode) {
      linksNode.innerHTML = result.links_html || "";
    }
    if (historyNode && result.recent_history_html) {
      historyNode.innerHTML = result.recent_history_html;
      bindHistoryButtons();
    }
  }

  function applyExample() {
    applyFormData((config && config.form_defaults) || {});
    if (textarea && !textarea.value) {
      setValue(textarea, config.default_task_text || "");
    }
  }

  function bindHistoryButtons() {
    document.querySelectorAll(".portal-live-load-history").forEach((button) => {
      button.addEventListener("click", () => {
        try {
          const form = JSON.parse(button.dataset.form || "{}");
          applyFormData(form);
          if (textarea) {
            textarea.focus();
          }
          setStatus("\u5df2\u628a\u5386\u53f2\u4efb\u52a1\u548c\u8bbe\u7f6e\u91cd\u65b0\u586b\u56de\u8868\u5355\u3002");
        } catch (error) {
          setStatus("\u91cd\u65b0\u586b\u5165\u5386\u53f2\u4efb\u52a1\u5931\u8d25\u3002");
        }
      });
    });
  }

  function collectPayload() {
    const repoSource = repoPathInput && repoPathInput.value ? repoPathInput.value : "";
    return {
      title: titleInput && titleInput.value ? titleInput.value : "",
      task_text: textarea && textarea.value ? textarea.value : "",
      task_shape: taskShapeInput && taskShapeInput.value ? taskShapeInput.value : "general",
      knowledge_pack: knowledgePackInput && knowledgePackInput.value ? knowledgePackInput.value : "none",
      repo_source: repoSource,
      repo_path: repoSource,
      context_paths_text: contextPathsInput && contextPathsInput.value ? contextPathsInput.value : "",
      editable_paths_text: editablePathsInput && editablePathsInput.value ? editablePathsInput.value : "",
      forbidden_paths_text: forbiddenPathsInput && forbiddenPathsInput.value ? forbiddenPathsInput.value : "",
      expected_changed_files_text: expectedChangedFilesInput && expectedChangedFilesInput.value ? expectedChangedFilesInput.value : "",
      behavioral_checks_text: behavioralChecksInput && behavioralChecksInput.value ? behavioralChecksInput.value : "",
      acceptance_checks_text: acceptanceChecksInput && acceptanceChecksInput.value ? acceptanceChecksInput.value : "",
    };
  }

  async function readJson(response) {
    const text = await response.text();
    return text ? JSON.parse(text) : {};
  }

  async function refreshPreview() {
    const payload = collectPayload();
    if (!(payload.task_text || "").trim() && !(payload.repo_path || "").trim()) {
      setStatus(config.api_ready ? "\u8bf7\u5148\u8f93\u5165\u4efb\u52a1\u6b63\u6587\u548c\u4ed3\u5e93\u6765\u6e90\u3002" : (config.api_message || "") + " \u4ecd\u7136\u53ef\u4ee5\u5148\u5237\u65b0\u9884\u89c8\u3002");
      return;
    }
    if (!(payload.task_text || "").trim()) {
      setStatus("\u8bf7\u5148\u8f93\u5165\u60f3\u6267\u884c\u7684\u4efb\u52a1\u3002");
      return;
    }
    if (!(payload.repo_path || "").trim()) {
      setStatus("\u8bf7\u5148\u586b\u5199\u4ed3\u5e93\u6765\u6e90\u3002");
      return;
    }
    if (previewButton) {
      previewButton.disabled = true;
    }
    setStatus("\u6b63\u5728\u5237\u65b0\u4e09\u6863\u4ea4\u4ed8\u9884\u89c8 ...");
    try {
      const response = await fetch(config.preview_endpoint || "/api/preview-demo", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const result = await readJson(response);
      if (!response.ok || result.ok === false) {
        throw new Error(result.error || "\u9884\u89c8\u5931\u8d25");
      }
      applyServerUpdate(result);
      setStatus(result.status_text || "\u5df2\u5237\u65b0\u4e09\u6863\u4ea4\u4ed8\u9884\u89c8\u3002");
    } catch (error) {
      const message = error && error.message ? error.message : "\u9884\u89c8\u5931\u8d25";
      setStatus(message);
    } finally {
      if (previewButton) {
        previewButton.disabled = false;
      }
    }
  }

  async function runDemoSynchronously(payload) {
    const response = await fetch(config.run_endpoint || "/api/run-demo", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const result = await readJson(response);
    if (!response.ok || result.ok === false) {
      throw new Error(result.error || "\u8fd0\u884c\u5931\u8d25");
    }
    return result;
  }

  async function waitForRunResult(jobId, initialPollAfterMs) {
    const statusEndpoint = config.run_status_endpoint || "/api/run-demo-status";
    let pollAfterMs = Number(initialPollAfterMs || defaultPollAfterMs);
    while (true) {
      await new Promise((resolve) => window.setTimeout(resolve, Math.max(pollAfterMs, 250)));
      const response = await fetch(`${statusEndpoint}?job_id=${encodeURIComponent(jobId)}`, {
        method: "GET",
        headers: {"Accept": "application/json"},
      });
      const result = await readJson(response);
      if (!response.ok || result.ok === false) {
        throw new Error(result.error || "\u67e5\u8be2\u8fd0\u884c\u72b6\u6001\u5931\u8d25");
      }
      setStatus(result.status_text || "\u6b63\u5728\u540e\u53f0\u8fd0\u884c\u5f53\u524d\u4efb\u52a1 ...");
      if (result.done) {
        return result;
      }
      pollAfterMs = Number(result.poll_after_ms || defaultPollAfterMs);
    }
  }

  async function runDemoAsynchronously(payload) {
    const response = await fetch(config.run_async_endpoint || "/api/run-demo-async", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const accepted = await readJson(response);
    if (!response.ok || accepted.ok === false) {
      throw new Error(accepted.error || "\u4efb\u52a1\u63d0\u4ea4\u5931\u8d25");
    }
    if (!accepted.job_id) {
      throw new Error("\u540e\u53f0\u8fd0\u884c\u672a\u8fd4\u56de\u4efb\u52a1\u7f16\u53f7");
    }
    setStatus(accepted.status_text || "\u4efb\u52a1\u5df2\u63d0\u4ea4\uff0c\u6b63\u5728\u540e\u53f0\u8fd0\u884c\u5f53\u524d\u4efb\u52a1 ...");
    return waitForRunResult(accepted.job_id, accepted.poll_after_ms);
  }

  async function runDemo() {
    const payload = collectPayload();
    if (!(payload.task_text || "").trim()) {
      setStatus("\u8bf7\u5148\u8f93\u5165\u60f3\u6267\u884c\u7684\u4efb\u52a1\u3002");
      return;
    }
    if (!(payload.repo_path || "").trim()) {
      setStatus("\u8bf7\u5148\u586b\u5199\u4ed3\u5e93\u6765\u6e90\u3002");
      return;
    }
    if (!submitButton) {
      return;
    }
    setRunBusy(true);
    setStatus(config.run_async_endpoint ? "\u4efb\u52a1\u5df2\u63d0\u4ea4\uff0c\u6b63\u5728\u51c6\u5907\u540e\u53f0\u8fd0\u884c ..." : "\u6b63\u5728\u8fd0\u884c\u5f53\u524d\u4efb\u52a1 ...");
    try {
      const result = config.run_async_endpoint
        ? await runDemoAsynchronously(payload)
        : await runDemoSynchronously(payload);
      applyRunResult(result);
      setStatus(result.status_text || "\u5df2\u5b8c\u6210\u5f53\u524d\u8fd0\u884c\u3002");
    } catch (error) {
      const message = error && error.message ? error.message : "\u8fd0\u884c\u5931\u8d25";
      setStatus(message);
    } finally {
      setRunBusy(false);
    }
  }

  if (previewButton) {
    previewButton.addEventListener("click", refreshPreview);
  }
  if (submitButton) {
    submitButton.addEventListener("click", runDemo);
  }
  if (useExampleButton) {
    useExampleButton.addEventListener("click", async () => {
      applyExample();
      if (textarea) {
        textarea.focus();
      }
      setStatus("\u5df2\u586b\u5165\u793a\u4f8b\uff0c\u6b63\u5728\u6309\u793a\u4f8b\u5237\u65b0\u9884\u89c8\u3002");
      await refreshPreview();
    });
  }
  if (textarea) {
    textarea.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        runDemo();
      }
    });
  }
  bindHistoryButtons();
})();
"""


_DEFAULT_PAGE_TITLE = "harness-lab"
_DEFAULT_IDLE_STATUS = "输入一个仓库任务，系统会先解释当前交付的 plan，再返回结果和建议。"
_CHAT_EXAMPLE_INPUT = "帮我做一个俄罗斯方块小游戏，要能直接运行开始玩"


def _join_display(values: list[str] | tuple[str, ...], empty_text: str = "未声明", *, limit: int | None = None) -> str:
    normalized = [str(item).strip() for item in values if str(item).strip()]
    if not normalized:
        return empty_text
    if limit is not None and len(normalized) > limit:
        shown = "、".join(normalized[:limit])
        return f"{shown} 等 {len(normalized)} 项"
    return "、".join(normalized)



def _render_plain_list(items: list[str] | tuple[str, ...], *, empty_text: str) -> str:
    normalized = [str(item).strip() for item in items if str(item).strip()]
    if not normalized:
        return f'<div class="thread-empty">{escape(empty_text)}</div>'
    return '<ul class="plain-list">' + ''.join(f'<li>{escape(item)}</li>' for item in normalized) + '</ul>'



def _render_prompt_block(title: str, content: str) -> str:
    normalized = str(content or "").strip()
    if not normalized:
        normalized = "当前没有可展示的 prompt 内容。"
    return ''.join(
        [
            '<div class="prompt-block">',
            f'<div class="prompt-label">{escape(title)}</div>',
            f'<pre class="prompt-preview">{escape(normalized)}</pre>',
            '</div>',
        ]
    )



def _build_plan_messages(preview: Mapping[str, object]) -> list[dict[str, object]]:
    task_preview = dict(preview.get("task_spec_preview") or {})
    profile_payloads = _preview_profile_payloads(preview)
    editable_paths = [str(item) for item in task_preview.get("editable_paths", ()) if str(item)]
    forbidden_paths = [str(item) for item in task_preview.get("forbidden_paths", ()) if str(item)]
    verifier_step_names = [str(item) for item in task_preview.get("verifier_step_names", ()) if str(item)]

    summary_map = {
        "current": "我会按当前交付边界执行任务，优先利用仓库树、上下文文件、任务输入和验收信息缩小改动范围。",
        "custom": "我会按自定义基线边界执行任务，用同一任务约束对照当前交付与基线差异。",
    }
    messages: list[dict[str, object]] = []
    for profile, payload in profile_payloads:
        context_files = [str(item) for item in payload.get("context_files", ()) if str(item)]
        input_names = [str(item) for item in payload.get("included_input_names", ()) if str(item)]
        visible_verifier_steps = [str(item) for item in payload.get("included_verifier_steps", ()) if str(item)]
        work_environment = dict(payload.get("work_environment") or {})
        context_summary = "仓库树可见" if bool(payload.get("includes_repo_tree")) else "不包含仓库树"
        if context_files:
            context_summary += f" + {len(context_files)} 个上下文文件（{_join_display(context_files, '无', limit=4)}）"
        bullets = [
            f"上下文内容：{context_summary}",
            f"喂给模型的额外信息：任务输入 {_join_display(input_names, '当前不注入')}；模型可见验收步骤 {_join_display(visible_verifier_steps, '当前不注入')}",
            f"行为边界：可改 {_join_display(editable_paths, '<any>')}；禁改 {_join_display(forbidden_paths, '<none>')}",
            f"最终验收：{_join_display(verifier_step_names, '当前未声明')}",
            "工作环境：隔离工作区 / checkout={} / 网络={} / 资源上限={} / 成本上限={}".format(
                work_environment.get("checkout_mode") or "copy",
                "允许" if bool(work_environment.get("allow_network")) else "禁用",
                work_environment.get("max_runtime_seconds") if work_environment.get("max_runtime_seconds") is not None else "未限制",
                work_environment.get("max_cost_usd") if work_environment.get("max_cost_usd") is not None else "未限制",
            ),
        ]
        messages.append(
            {
                "profile": profile,
                "label": _profile_label(profile),
                "title": f"{_profile_label(profile)} Plan",
                "summary": summary_map.get(profile, "我会按当前 harness 边界执行任务。"),
                "bullets": bullets,
            }
        )
    return messages



def _build_guidance_items(plan: PortalSubmissionPlan, preview: Mapping[str, object]) -> list[str]:
    task_preview = dict(preview.get("task_spec_preview") or {})
    shared_info = dict(preview.get("shared_task_information") or {})
    environment = dict(shared_info.get("environment") or {})
    form_fields = dict(plan.form_fields)
    guidance: list[str] = [
        "补充任务的业务场景、目标用户和最终交付形态，例如是 demo、正式功能、一次性脚本还是长期维护模块。",
    ]
    if not str(form_fields.get("context_paths_text") or "").strip():
        guidance.append("补充关键上下文文件，例如 README、核心模块、接口定义、测试或设计文档，减少模型在仓库里盲搜。")
    if not str(form_fields.get("editable_paths_text") or "").strip() or not str(form_fields.get("expected_changed_files_text") or "").strip():
        guidance.append("补充允许修改 / 禁止修改 / 预期改动文件，明确操作范围，避免模型扩散式改仓库。")
    if plan.used_draft_verifier or not [str(item) for item in task_preview.get("verifier_step_names", ()) if str(item)]:
        guidance.append("补充确定性的验收标准，例如测试命令、运行方式、截图、输出格式或可量化检查。")
    if environment.get("max_runtime_seconds") is None and environment.get("max_cost_usd") is None:
        guidance.append("补充资源约束：更看重时效还是质量、可接受的 token / 时间 / 成本上限。")
    if not environment.get("allowed_tools"):
        guidance.append("补充模型权限范围，例如能不能执行 shell、能不能安装依赖、能不能新建文件、哪些目录绝对不能碰。")
    if not bool(environment.get("allow_network")):
        guidance.append("如果需要联网搜索，请显式说明是否允许联网、允许检索哪些站点、搜索多深、多近，以及是否要保留来源。")
    behavioral_checks = [str(item) for item in task_preview.get("behavioral_checks", ()) if str(item)]
    if not behavioral_checks:
        guidance.append("补充你最看重的行为标准，例如更稳、可直接运行、UI 质量优先，还是先出能交付的版本。")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in guidance:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:6]



def render_live_guidance_markup(items: list[str], *, empty_text: str | None = None) -> str:
    normalized = [str(item).strip() for item in items if str(item).strip()]
    if not normalized:
        fallback = empty_text or "补充更具体的业务上下文、操作边界、权限范围和验收标准后，这里会给出更有针对性的 harness 建议。"
        return ''.join(
            [
                '<article class="thread-card thread-card-assistant">',
                '<div class="thread-card-title">Harness 建议</div>',
                f'<p>{escape(fallback)}</p>',
                '</article>',
            ]
        )
    return ''.join(
        [
            '<article class="thread-card thread-card-assistant">',
            '<div class="thread-card-title">Harness 建议</div>',
            _render_plain_list(normalized, empty_text="当前没有额外建议。"),
            '</article>',
        ]
    )



def _render_workbench_profile_section(profile: str, payload: Mapping[str, object]) -> str:
    prompt_preview = dict(payload.get("prompt_preview") or {})
    boundary = dict(payload.get("boundary") or {})
    work_environment = dict(payload.get("work_environment") or {})
    context_files = [str(item) for item in payload.get("context_files", ()) if str(item)]
    tree_preview = [str(item) for item in prompt_preview.get("tree_preview", ()) if str(item)]
    context_summary = [
        f"仓库树：{'可见' if bool(payload.get('includes_repo_tree')) else '不可见'}",
        f"上下文文件：{_join_display(context_files, '当前不注入', limit=6)}",
        f"任务输入：{_join_display(payload.get('included_input_names', ()), '当前不注入')}",
        f"模型可见验收：{_join_display(payload.get('included_verifier_steps', ()), '当前不注入')}",
    ]
    boundary_rows = [
        f"可修改：{_join_display(boundary.get('editable_paths', ()), '<any>')}",
        f"禁止修改：{_join_display(boundary.get('forbidden_paths', ()), '<none>')}",
        f"预期改动：{_join_display(boundary.get('expected_changed_files', ()), '未声明')}",
        f"行为边界：{_join_display(boundary.get('behavioral_checks', ()), '未声明')}",
        f"最终验收：{_join_display(boundary.get('required_verifier_steps', ()), '未声明')}",
    ]
    environment_rows = [
        f"repo_root：{work_environment.get('repo_root') or '未解析'}",
        f"repo_source_kind：{work_environment.get('repo_source_kind') or 'unknown'}",
        f"checkout_mode：{work_environment.get('checkout_mode') or 'copy'}",
        f"联网：{'允许' if bool(work_environment.get('allow_network')) else '禁用'}",
        f"allowed_tools：{_join_display(work_environment.get('allowed_tools', ()), '未声明')}",
        f"max_runtime_seconds：{work_environment.get('max_runtime_seconds') if work_environment.get('max_runtime_seconds') is not None else '未限制'}",
        f"max_cost_usd：{work_environment.get('max_cost_usd') if work_environment.get('max_cost_usd') is not None else '未限制'}",
    ]
    return ''.join(
        [
            '<details class="bench-group" open>',
            f'<summary>{escape(_profile_label(profile))}</summary>',
            '<div class="bench-stack">',
            _render_plain_list(context_summary, empty_text="当前没有模式说明。"),
            '<details class="bench-subgroup">',
            '<summary>输入给模型的 Prompt</summary>',
            _render_prompt_block('System Prompt', str(prompt_preview.get('system_prompt') or '')),
            _render_prompt_block('User Prompt', str(prompt_preview.get('user_prompt') or '')),
            '</details>',
            '<details class="bench-subgroup">',
            '<summary>上下文细节</summary>',
            _render_plain_list(context_files, empty_text='当前没有注入上下文文件。'),
            _render_plain_list(tree_preview, empty_text='当前没有仓库树预览。'),
            '</details>',
            '<details class="bench-subgroup">',
            '<summary>约束与边界</summary>',
            _render_plain_list(boundary_rows, empty_text='当前没有任务边界信息。'),
            '</details>',
            '<details class="bench-subgroup">',
            '<summary>工作环境</summary>',
            _render_plain_list(environment_rows, empty_text='当前没有工作环境信息。'),
            '</details>',
            '</div>',
            '</details>',
        ]
    )



def render_live_workbench_markup(
    *,
    template_id: str,
    template_title: str,
    form_fields: Mapping[str, str],
    preview: Mapping[str, object],
    mode: str,
    autogenerated_fields: tuple[str, ...],
    used_draft_verifier: bool,
) -> str:
    task_preview = dict(preview.get("task_spec_preview") or {})
    shared_info = dict(preview.get("shared_task_information") or {})
    profile_payloads = _preview_profile_payloads(preview)
    environment = dict(shared_info.get("environment") or {})
    repo_label = _portal_repo_source_label(str(form_fields.get("repo_path") or task_preview.get("repo_root") or "")) or "未设置"
    task_boundary_rows = [
        f"模板：{template_title} ({template_id})",
        f"仓库来源：{repo_label}",
        f"可修改：{_join_display(task_preview.get('editable_paths', ()), '<any>')}",
        f"禁止修改：{_join_display(task_preview.get('forbidden_paths', ()), '<none>')}",
        f"预期改动：{_join_display(task_preview.get('expected_changed_files', ()), '未声明')}",
        f"行为边界：{_join_display(task_preview.get('behavioral_checks', ()), '未声明')}",
        f"验收标准：{_join_display(task_preview.get('verifier_step_names', ()), '未声明')}",
    ]
    if mode == PORTAL_MODE_FREEFORM and autogenerated_fields:
        task_boundary_rows.insert(0, f"系统自动草拟：{_join_display([_autogenerated_field_label(item) for item in autogenerated_fields], '无')}")
    if used_draft_verifier:
        task_boundary_rows.append("当前验收使用 draft completion 估算，不等于业务最终验收。")
    environment_rows = [
        f"repo_source_kind：{environment.get('repo_source_kind') or 'unknown'}",
        f"checkout_mode：{environment.get('checkout_mode') or 'copy'}",
        f"联网：{'允许' if bool(environment.get('allow_network')) else '禁用'}",
        f"allowed_tools：{_join_display(environment.get('allowed_tools', ()), '未声明')}",
        f"max_runtime_seconds：{environment.get('max_runtime_seconds') if environment.get('max_runtime_seconds') is not None else '未限制'}",
        f"max_cost_usd：{environment.get('max_cost_usd') if environment.get('max_cost_usd') is not None else '未限制'}",
    ]
    profile_sections = ''.join(
        _render_workbench_profile_section(profile, payload)
        for profile, payload in profile_payloads
    )
    return ''.join(
        [
            '<div class="workbench-stack">',
            '<details class="bench-group" open>',
            '<summary>任务边界</summary>',
            _render_plain_list(task_boundary_rows, empty_text='当前没有任务边界。'),
            '</details>',
            '<details class="bench-group" open>',
            '<summary>当前运行交付</summary>',
            '<div class="bench-stack">',
            profile_sections or _render_assistant_placeholder(None, "当前还没有可展示的交付预览。"),
            '</div>',
            '</details>',
            '<details class="bench-group">',
            '<summary>共享约束与环境</summary>',
            _render_plain_list(environment_rows, empty_text='当前没有环境信息。'),
            _render_prompt_block('统一响应契约', str(shared_info.get('response_contract') or '')),
            '</details>',
            '</div>',
        ]
    )



def _render_workbench_placeholder_markup(*, entry_title: str, model_display_name: str) -> str:
    rows = [
        f"当前模型：{model_display_name}",
        "右侧输入任务后，工作台会展开当前交付、Prompt、约束、验收和工作环境。",
        f"如需受控样例，可直接把任务换成：{_CHAT_EXAMPLE_INPUT}",
        f"当前模板示例：{entry_title}",
    ]
    return ''.join(
        [
            '<div class="workbench-stack">',
            '<details class="bench-group" open>',
            '<summary>等待任务输入</summary>',
            _render_plain_list(rows, empty_text='请先输入任务。'),
            '</details>',
            '</div>',
        ]
    )



def render_live_plan_stream_markup(messages: list[dict[str, object]], *, empty_text: str | None = None) -> str:
    if not messages:
        return ''.join(
            [
                '<article class="thread-card thread-card-assistant">',
                '<div class="thread-card-title">任务阐明</div>',
                f'<p>{escape(empty_text or "输入任务后，这里会按当前交付顺序展示 plan。")}</p>',
                '</article>',
            ]
        )
    cards: list[str] = []
    for message in messages:
        cards.append(
            ''.join(
                [
                    '<article class="thread-card thread-card-assistant plan-card">',
                    '<div class="thread-card-top">',
                    f'<span class="thread-role">{escape(str(message.get("title") or "Plan"))}</span>',
                    f'<span class="profile-badge">{escape(str(message.get("label") or ""))}</span>',
                    '</div>',
                    f'<p>{escape(str(message.get("summary") or ""))}</p>',
                    _render_plain_list([str(item) for item in message.get("bullets", ())], empty_text='当前没有额外 plan 说明。'),
                    '</article>',
                ]
            )
        )
    return ''.join(cards)



def _preview_bundle(
    *,
    plan: PortalSubmissionPlan,
    source_path: Path | None,
    template_id: str,
    template_title: str,
    template_form_defaults: Mapping[str, str],
    model_display_name: str,
) -> dict[str, object]:
    preview = build_task_intake_preview(plan.intake, source_path=source_path, repo_root_override=plan.resolved_repo_root)
    plan_messages = _build_plan_messages(preview)
    guidance_items = _build_guidance_items(plan, preview)
    workbench_html = _render_portal_story_markup(
        preview=preview,
        form_fields=plan.form_fields,
        mode=plan.mode,
        autogenerated_fields=plan.autogenerated_fields,
        used_draft_verifier=plan.used_draft_verifier,
        plan_messages=plan_messages,
        guidance_items=guidance_items,
    )
    guidance_html = render_live_guidance_markup(guidance_items)
    return {
        "preview": preview,
        "workbench_html": workbench_html,
        "plan_messages": plan_messages,
        "guidance_items": guidance_items,
        "guidance_html": guidance_html,
        "scope_html": workbench_html,
        "profile_explainer_html": render_live_plan_stream_markup(plan_messages),
    }



def _preview_status_text(plan: PortalSubmissionPlan) -> str:
    if plan.mode == PORTAL_MODE_FREEFORM and plan.used_draft_verifier:
        return "已生成当前交付 plan；当前仍是草拟验收，建议补充真实的 acceptance checks。"
    return "已生成当前交付的 plan。"



def _run_status_text(plan: PortalSubmissionPlan) -> str:
    if plan.mode == PORTAL_MODE_FREEFORM and plan.used_draft_verifier:
        return "已完成当前运行；当前结果基于草拟验收估算。"
    return "已完成当前运行。"



def build_live_page_state(*, settings: Settings, live_entry: PortalLiveEntryConfig) -> dict[str, object]:
    entry = build_live_entry_payload(live_entry)
    form_fields = blank_portal_form_fields()
    recent_submissions = _load_live_submission_history(settings=settings, template_id=live_entry.template_id)
    status_text = str(entry.get("api_message") or _DEFAULT_IDLE_STATUS) if not bool(entry.get("api_ready")) else _DEFAULT_IDLE_STATUS
    workbench_html = _render_workbench_placeholder_markup(
        entry_title=str(entry["template_title"]),
        model_display_name=str(entry["model_display_name"]),
    )
    guidance_html = render_live_guidance_markup([], empty_text="补充更具体的业务上下文、资源约束、权限范围和验收标准后，这里会生成针对当前任务的 harness 建议。")
    return {
        "page_title": _DEFAULT_PAGE_TITLE,
        "entry_title": str(entry["template_title"]),
        "chat_example_text": _CHAT_EXAMPLE_INPUT,
        "form_fields": form_fields,
        "example_task_text": str(entry["default_task_text"]),
        "model_display_name": str(entry["model_display_name"]),
        "api_ready": bool(entry["api_ready"]),
        "status_text": status_text,
        "task_input_label": str(entry.get("task_input_label") or "任务正文"),
        "task_input_placeholder": _CHAT_EXAMPLE_INPUT,
        "task_shape_input_label": str(entry.get("task_shape_input_label") or "任务形态"),
        "task_shape_options": list(entry.get("task_shape_options") or ()),
        "knowledge_pack_input_label": str(entry.get("knowledge_pack_input_label") or "材料包"),
        "knowledge_pack_options": list(entry.get("knowledge_pack_options") or ()),
        "repo_source_input_label": str(entry.get("repo_source_input_label") or "仓库来源"),
        "repo_source_placeholder": str(entry.get("repo_source_placeholder") or ""),
        "advanced_settings_summary": str(entry.get("advanced_settings_summary") or "高级范围与验收"),
        "advanced_settings_help_text": str(entry.get("advanced_settings_help_text") or ""),
        "acceptance_checks_help_text": str(entry.get("acceptance_checks_help_text") or ""),
        "results": [],
        "results_html": render_live_results_markup([], empty_text="运行完成后，这里会显示当前结果。"),
        "links": [],
        "links_html": "",
        "workbench_html": workbench_html,
        "plan_messages": [],
        "guidance_html": guidance_html,
        "scope_html": workbench_html,
        "profile_explainer_html": render_live_plan_stream_markup([], empty_text="输入任务后，这里会展示当前交付 plan。"),
        "recent_submissions": recent_submissions,
        "recent_history_html": render_live_history_markup(recent_submissions),
        "config": {
            **entry,
            "recent_submissions": recent_submissions,
            "chat_example_input": _CHAT_EXAMPLE_INPUT,
        },
    }



def preview_live_portal_submission(
    *,
    live_entry: PortalLiveEntryConfig,
    submission: Mapping[str, object],
    settings: Settings | None = None,
) -> dict[str, object]:
    resolved_settings = settings or load_settings()
    base_intake = JsonTaskIntakeLoader().load(live_entry.intake_source_path)
    template_form_defaults = _build_form_defaults(
        base_intake,
        hide_local_repo_source=not live_entry.allow_custom_local_repo_paths,
    )
    task_text = str(submission.get("task_text") or "").strip()
    repo_source = str(submission.get("repo_source") or submission.get("repo_path") or "").strip()
    model_display_name = _model_display_name(live_entry.provider, live_entry.model)
    if not task_text and not repo_source:
        workbench_html = _render_workbench_placeholder_markup(
            entry_title=base_intake.title,
            model_display_name=model_display_name,
        )
        return {
            "ok": True,
            "status_text": _DEFAULT_IDLE_STATUS,
            "form_fields": blank_portal_form_fields(),
            "workbench_html": workbench_html,
            "plan_messages": [],
            "guidance_html": render_live_guidance_markup([], empty_text="补充更具体的业务上下文、资源约束、权限范围和验收标准后，这里会生成针对当前任务的 harness 建议。"),
            "scope_html": workbench_html,
            "profile_explainer_html": render_live_plan_stream_markup([], empty_text="输入任务后，这里会展示当前交付 plan。"),
        }
    if not task_text:
        raise ValueError("请先输入想执行的任务。")
    if not repo_source:
        raise ValueError("请先填写要操作的仓库来源（本地路径或 Git 地址）。")

    plan = resolve_portal_submission(
        base_intake=base_intake,
        submission=submission,
        template_id=live_entry.template_id,
        template_form_defaults=template_form_defaults,
        require_task_text=True,
        require_repo_path=True,
        settings=resolved_settings,
        allow_custom_local_repo_paths=live_entry.allow_custom_local_repo_paths,
    )
    try:
        preview_bundle = _preview_bundle(
            plan=plan,
            source_path=live_entry.intake_source_path if plan.mode == PORTAL_MODE_EXAMPLE else None,
            template_id=live_entry.template_id,
            template_title=base_intake.title,
            template_form_defaults=template_form_defaults,
            model_display_name=model_display_name,
        )
        return {
            "ok": True,
            "status_text": _preview_status_text(plan),
            "form_fields": plan.form_fields,
            "workbench_html": preview_bundle["workbench_html"],
            "plan_messages": preview_bundle["plan_messages"],
            "guidance_html": preview_bundle["guidance_html"],
            "scope_html": preview_bundle["scope_html"],
            "profile_explainer_html": preview_bundle["profile_explainer_html"],
        }
    finally:
        cleanup_portal_submission_plan(plan)



def run_live_portal_submission(
    *,
    settings: Settings,
    live_entry: PortalLiveEntryConfig,
    submission: Mapping[str, object],
    progress_callback: Callable[[str, str], None] | None = None,
) -> dict[str, object]:
    def report_progress(phase: str, message: str) -> None:
        if progress_callback is not None:
            progress_callback(phase, message)

    report_progress("prepare", "正在准备任务")
    settings.paths.ensure_runtime_directories()
    base_intake = JsonTaskIntakeLoader().load(live_entry.intake_source_path)
    template_form_defaults = _build_form_defaults(
        base_intake,
        hide_local_repo_source=not live_entry.allow_custom_local_repo_paths,
    )
    submission_id = new_id("portal")
    plan = resolve_portal_submission(
        base_intake=base_intake,
        submission=submission,
        template_id=live_entry.template_id,
        template_form_defaults=template_form_defaults,
        submission_id=submission_id,
        require_task_text=True,
        require_repo_path=True,
        settings=settings,
        allow_custom_local_repo_paths=live_entry.allow_custom_local_repo_paths,
    )
    try:
        intake = plan.intake
        report_progress("intake", "正在生成 intake")
        submission_path = settings.paths.tmp_dir / f"{_safe_file_stem(intake.task_id)}-{submission_id}.intake.json"
        submission_path.write_text(json.dumps(to_jsonable(intake), ensure_ascii=False, indent=2), encoding="utf8")

        suite_id = f"{live_entry.template_id}-{submission_id}-intake-uplift-suite"
        args = argparse.Namespace(
            source=str(submission_path),
            provider=live_entry.provider,
            model=live_entry.model,
            agent_name=live_entry.agent_name,
            api_key_env=live_entry.api_key_env,
            base_url=live_entry.base_url,
            system_prompt=live_entry.system_prompt,
            suite_id=suite_id,
            label_prefix=live_entry.label_prefix,
            historical_baseline_report_id=None,
            baseline_report_id=None,
        )
        buffer = io.StringIO()
        report_progress("run", "正在执行任务")
        try:
            with redirect_stdout(buffer):
                exit_code = handle_run_intake_eval(args)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        payload_text = buffer.getvalue().strip()
        if not payload_text:
            raise RuntimeError("portal run did not return a result payload")
        payload = json.loads(payload_text)
        if exit_code != 0 or payload.get("ok") is False:
            raise RuntimeError(str(payload.get("error") or "portal run failed"))

        report_progress("collect", "正在汇总结果")
        record_store = RunRecordStore(settings=settings, json_store=JsonRunStore(settings=settings))
        focus_payload = _build_focus_payload(
            record_store=record_store,
            report_id=str(payload.get("suite_id") or ""),
            target_task_id=intake.task_id,
        )
        results = list(focus_payload.get("results", []))
        if plan.used_draft_verifier:
            results = _annotate_draft_results(
                results,
                note="当前是自由任务草拟验收：系统会按目标文件覆盖、任务锚点命中和范围遵守估算完成度，不等于真实业务验收。",
            )
        links = list(focus_payload.get("links", []))
        preview_bundle = _preview_bundle(
            plan=plan,
            source_path=submission_path,
            template_id=live_entry.template_id,
            template_title=base_intake.title,
            template_form_defaults=template_form_defaults,
            model_display_name=_model_display_name(live_entry.provider, live_entry.model),
        )
        recent_submissions = _store_live_submission_history(
            settings=settings,
            template_id=live_entry.template_id,
            title=intake.title,
            suite_id=str(payload.get("suite_id") or ""),
            form_fields=plan.form_fields,
        )
        workbench_html = _render_portal_story_markup(
            preview=preview_bundle["preview"],
            form_fields=plan.form_fields,
            mode=plan.mode,
            autogenerated_fields=plan.autogenerated_fields,
            used_draft_verifier=plan.used_draft_verifier,
            plan_messages=preview_bundle["plan_messages"],
            guidance_items=list(preview_bundle.get("guidance_items") or ()),
            results=results,
            links=links,
            recent_submissions=recent_submissions,
        )
        report_progress("completed", _run_status_text(plan))
        return {
            "ok": True,
            "suite_id": str(payload.get("suite_id") or ""),
            "task_text": intake.business_request,
            "task_title": intake.title,
            "model_display_name": _model_display_name(live_entry.provider, live_entry.model),
            "status_text": _run_status_text(plan),
            "results": results,
            "results_html": render_live_results_markup(results),
            "links": links,
            "links_html": render_live_links_markup(links),
            "workbench_html": workbench_html,
            "plan_messages": preview_bundle["plan_messages"],
            "guidance_html": preview_bundle["guidance_html"],
            "scope_html": workbench_html,
            "profile_explainer_html": preview_bundle["profile_explainer_html"],
            "form_fields": plan.form_fields,
            "recent_submissions": recent_submissions,
            "recent_history_html": render_live_history_markup(recent_submissions),
            "current_phase": "completed",
        }
    finally:
        cleanup_portal_submission_plan(plan)
_DEFAULT_PAGE_TITLE = "harness-lab"
_DEFAULT_IDLE_STATUS = "\u7b49\u5f85\u4efb\u52a1\u8f93\u5165"
_CHAT_EXAMPLE_INPUT = "\u5e2e\u6211\u505a\u4e00\u4e2a\u4fc4\u7f57\u65af\u65b9\u5757\u5c0f\u6e38\u620f\uff0c\u8981\u80fd\u76f4\u63a5\u8fd0\u884c\u5f00\u59cb\u73a9"


def _render_assistant_placeholder(title: str | None, text: str) -> str:
    parts = ['<article class="thread-card thread-card-assistant">']
    if title:
        parts.append(f'<div class="thread-card-title">{escape(title)}</div>')
    parts.append(f'<p>{escape(text)}</p>')
    parts.append('</article>')
    return "".join(parts)



def render_live_plan_stream_markup(messages: list[dict[str, object]], *, empty_text: str | None = None) -> str:
    if not messages:
        return _render_assistant_placeholder(
            None,
            empty_text or "\u8f93\u5165\u4efb\u52a1\u540e\uff0c\u8fd9\u91cc\u4f1a\u6309\u5f53\u524d\u4ea4\u4ed8\u7684\u987a\u5e8f\u663e\u5f0f\u5c55\u5f00 harness plan\u3002",
        )
    cards: list[str] = []
    for message in messages:
        bullets = [str(item).strip() for item in message.get("bullets", ()) if str(item).strip()]
        cards.append(
            "".join(
                [
                    '<article class="thread-card thread-card-assistant plan-card">',
                    '<div class="thread-card-top">',
                    f'<span class="thread-role">{escape(str(message.get("title") or "Plan"))}</span>',
                    f'<span class="profile-badge">{escape(str(message.get("label") or ""))}</span>',
                    '</div>',
                    f'<p>{escape(str(message.get("summary") or ""))}</p>',
                    _render_plain_list(bullets, empty_text="\u5f53\u524d\u6ca1\u6709\u989d\u5916 plan \u8bf4\u660e\u3002"),
                    '</article>',
                ]
            )
        )
    return "".join(cards)



def render_live_guidance_markup(items: list[str], *, empty_text: str | None = None) -> str:
    normalized = [str(item).strip() for item in items if str(item).strip()]
    if not normalized:
        return _render_assistant_placeholder(
            None,
            empty_text
            or "\u8865\u5145\u66f4\u5177\u4f53\u7684\u4e1a\u52a1\u573a\u666f\u3001\u8d44\u6e90\u7ea6\u675f\u3001\u6743\u9650\u8303\u56f4\u548c\u9a8c\u6536\u6807\u51c6\u540e\uff0c\u8fd9\u91cc\u4f1a\u7ed9\u51fa\u66f4\u6709\u9488\u5bf9\u6027\u7684 harness \u5efa\u8bae\u3002",
        )
    return "".join(
        [
            '<article class="thread-card thread-card-assistant">',
            _render_plain_list(normalized, empty_text="\u5f53\u524d\u6ca1\u6709\u989d\u5916\u5efa\u8bae\u3002"),
            '</article>',
        ]
    )



def _render_workbench_placeholder_markup(*, entry_title: str, model_display_name: str) -> str:
    rows = [
        f"\u5f53\u524d\u6a21\u578b\uff1a{model_display_name}",
        "\u53f3\u4fa7\u8f93\u5165\u4efb\u52a1\u540e\uff0c\u5de5\u4f5c\u53f0\u4f1a\u5c55\u793a\u5f53\u524d\u4ea4\u4ed8\u7684 prompt\u3001\u7ea6\u675f\u3001\u9a8c\u6536\u6807\u51c6\u548c\u5de5\u4f5c\u73af\u5883\u3002",
        f"\u5f53\u524d\u9ed8\u8ba4\u793a\u4f8b\uff1a{entry_title}",
        f"\u53ef\u4ee5\u76f4\u63a5\u8f93\u5165\uff1a{_CHAT_EXAMPLE_INPUT}",
    ]
    sections = build_portal_story_sections(
        preview={
            "task_spec_preview": {
                "title": entry_title,
                "description": _CHAT_EXAMPLE_INPUT,
            }
        },
        form_fields={"task_text": _CHAT_EXAMPLE_INPUT, "repo_path": ""},
        mode="custom",
        autogenerated_fields=(),
        used_draft_verifier=False,
        results=(),
        links=(),
        detail_blocks=(("\u67e5\u770b\u5f53\u524d\u8bf4\u660e", _render_plain_list(rows, empty_text="\u8bf7\u5148\u8f93\u5165\u4efb\u52a1\u3002")),),
    )
    return render_portal_story(sections)



def _render_result_thread(result: dict[str, object]) -> str:
    profile_label = str(result.get("profile_label") or result.get("profile") or "")
    status_label = str(result.get("status_label") or result.get("status") or "")
    verifier_label = str(result.get("verifier_label") or result.get("verifier") or "")
    duration_text = str(result.get("duration_text") or "")
    output_text = str(result.get("output_text") or "") or "\u5f53\u524d\u6ca1\u6709\u63d0\u53d6\u5230\u663e\u5f0f\u8f93\u51fa\u3002"
    result_items = [str(item) for item in result.get("result_items", ()) if str(item)] or ["\u5f53\u524d\u6ca1\u6709\u989d\u5916\u7ed3\u679c\u8bf4\u660e\u3002"]
    actions = [
        f'<a class="button button-secondary" href="{escape(str(result.get("run_report_path") or "#"))}">\u8fd0\u884c\u62a5\u544a</a>',
    ]
    comparison_path = str(result.get("comparison_path") or "")
    if comparison_path:
        actions.append(f'<a class="button button-secondary" href="{escape(comparison_path)}">\u5bf9\u6bd4\u9875</a>')
    badge_class = f'badge badge-status badge-status-{escape(str(result.get("status") or "pending"))}'
    meta_parts = [part for part in (f"\u9a8c\u6536\uff1a{verifier_label}" if verifier_label else "", f"\u8017\u65f6\uff1a{duration_text}" if duration_text else "") if part]
    return "".join(
        [
            '<article class="thread-card thread-card-assistant result-card-chat">',
            '<div class="thread-card-top">',
            f'<span class="thread-role">{escape(profile_label)}</span>',
            f'<span class="{badge_class}">{escape(status_label)}</span>',
            '</div>',
            f'<div class="thread-card-title">{escape(profile_label)} \u8f93\u51fa</div>',
            f'<div class="thread-meta">{escape(" | ".join(meta_parts))}</div>' if meta_parts else '<div class="thread-meta"></div>',
            f'<pre>{escape(output_text)}</pre>',
            _render_plain_list(result_items, empty_text="\u5f53\u524d\u6ca1\u6709\u989d\u5916\u7ed3\u679c\u8bf4\u660e\u3002"),
            '<div class="actions">',
            "".join(actions),
            '</div>',
            '</article>',
        ]
    )



def render_live_results_markup(results: list[dict[str, object]], *, empty_text: str | None = None) -> str:
    if not results:
        return _render_assistant_placeholder(
            None,
            empty_text or "\u8fd0\u884c\u5b8c\u6210\u540e\uff0c\u8fd9\u91cc\u4f1a\u5c55\u793a\u5f53\u524d\u8fd0\u884c\u7ed3\u679c\u3002",
        )
    cards = "".join(_render_result_thread(result) for result in results)
    return cards


def _render_portal_story_markup(
    *,
    preview: Mapping[str, object],
    form_fields: Mapping[str, str],
    mode: str,
    autogenerated_fields: tuple[str, ...],
    used_draft_verifier: bool,
    plan_messages: list[dict[str, object]],
    guidance_items: list[str],
    results: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
    links: list[dict[str, str]] | tuple[dict[str, str], ...] = (),
    recent_submissions: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
) -> str:
    results_list = list(results)
    detail_blocks: list[tuple[str, str]] = [
        ("\u67e5\u770b system plan", render_live_plan_stream_markup(plan_messages, empty_text="\u8fd9\u4e00\u6bb5\u4f1a\u89e3\u91ca harness \u5148\u600e\u4e48\u7ec4\u88c5\u4efb\u52a1\u3002")),
        ("\u67e5\u770b harness \u5efa\u8bae", render_live_guidance_markup(guidance_items, empty_text="\u8fd9\u4e00\u6bb5\u4f1a\u8865\u5145\u8fd0\u884c\u524d\u540e\u7684\u5173\u952e\u5efa\u8bae\u3002")),
    ]
    if recent_submissions:
        detail_blocks.append(("\u67e5\u770b\u6700\u8fd1\u4efb\u52a1", render_live_history_markup(list(recent_submissions))))
    sections = build_portal_story_sections(
        preview=preview,
        form_fields=form_fields,
        mode=mode,
        autogenerated_fields=autogenerated_fields,
        used_draft_verifier=used_draft_verifier,
        results=results_list,
        links=list(links),
        detail_blocks=detail_blocks,
        result_details_html=render_live_results_markup(
            results_list,
            empty_text="\u8fd0\u884c\u5b8c\u6210\u540e\uff0c\u8fd9\u91cc\u4f1a\u5c55\u793a\u5168\u91cf\u7ed3\u679c\u5361\u7247\u3002",
        ),
    )
    return render_portal_story(sections)

def render_live_portal_html(state: dict[str, object]) -> str:
    return render_live_portal_shell(state)

    config_json = json.dumps(state.get("config", {}), ensure_ascii=False).replace("</", "<\\/")
    title = str(state.get("page_title") or _DEFAULT_PAGE_TITLE)
    status_text = str(state.get("status_text") or _DEFAULT_IDLE_STATUS)
    model_display_name = str(state.get("model_display_name") or "")
    chat_example_text = str(state.get("chat_example_text") or _CHAT_EXAMPLE_INPUT)
    results_html = str(state.get("results_html") or render_live_results_markup([], empty_text="\u8fd0\u884c\u5b8c\u6210\u540e\uff0c\u8fd9\u91cc\u4f1a\u5c55\u793a\u5f53\u524d\u8fd0\u884c\u7ed3\u679c\u3002"))
    links_html = str(state.get("links_html") or "")
    workbench_html = str(state.get("workbench_html") or "")
    guidance_html = str(state.get("guidance_html") or render_live_guidance_markup([]))
    plan_stream_html = str(state.get("profile_explainer_html") or render_live_plan_stream_markup(list(state.get("plan_messages") or [])))
    recent_history_html = str(state.get("recent_history_html") or render_live_history_markup([]))
    task_input_placeholder = str(state.get("task_input_placeholder") or chat_example_text)
    repo_source_input_label = str(state.get("repo_source_input_label") or "\u4ed3\u5e93\u6765\u6e90")
    repo_source_placeholder = str(state.get("repo_source_placeholder") or "")
    advanced_settings_summary = str(state.get("advanced_settings_summary") or "\u9ad8\u7ea7\u8303\u56f4\u4e0e\u9a8c\u6536")
    acceptance_checks_help_text = str(state.get("acceptance_checks_help_text") or "")
    form_fields = dict(state.get("form_fields") or {})
    form_title = str(form_fields.get("title") or "")
    task_text = str(form_fields.get("task_text") or "")
    task_shape = str(form_fields.get("task_shape") or "general")
    knowledge_pack = str(form_fields.get("knowledge_pack") or "none")
    repo_path = str(form_fields.get("repo_path") or "")
    context_paths_text = str(form_fields.get("context_paths_text") or "")
    editable_paths_text = str(form_fields.get("editable_paths_text") or "")
    forbidden_paths_text = str(form_fields.get("forbidden_paths_text") or "")
    expected_changed_files_text = str(form_fields.get("expected_changed_files_text") or "")
    behavioral_checks_text = str(form_fields.get("behavioral_checks_text") or "")
    acceptance_checks_text = str(form_fields.get("acceptance_checks_text") or "")
    return "".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{escape(title)}</title>",
            f"<style>{_styles()}</style>",
            "</head>",
            "<body>",
            '<div class="app-shell">',
            '<aside class="workspace-sidebar">',
            '<div class="sidebar-brand">',
            '<div class="brand-mark">\u5de5\u4f5c\u53f0</div>',
            f'<div class="sidebar-meta"><span class="badge badge-soft">{escape(model_display_name)}</span></div>',
            '</div>',
            f'<input id="portal-live-title-input" type="hidden" value="{escape(form_title)}">',
            f'<input id="portal-live-task-shape" type="hidden" value="{escape(task_shape)}">',
            f'<input id="portal-live-knowledge-pack" type="hidden" value="{escape(knowledge_pack)}">',
            '<div class="sidebar-section sidebar-section-plain">',
            f'<label class="input-label" for="portal-live-repo-path">{escape(repo_source_input_label)}</label>',
            f'<input id="portal-live-repo-path" class="text-input" type="text" value="{escape(repo_path)}" placeholder="{escape(repo_source_placeholder)}">',
            '</div>',
            '<details class="sidebar-section">',
            f'<summary>{escape(advanced_settings_summary)}</summary>',
            '<label class="input-label" for="portal-live-context-paths">context_paths</label>',
            f'<textarea id="portal-live-context-paths" class="code-input" rows="5">{escape(context_paths_text)}</textarea>',
            '<label class="input-label" for="portal-live-editable-paths">editable_paths</label>',
            f'<textarea id="portal-live-editable-paths" class="code-input" rows="5">{escape(editable_paths_text)}</textarea>',
            '<label class="input-label" for="portal-live-forbidden-paths">forbidden_paths</label>',
            f'<textarea id="portal-live-forbidden-paths" class="code-input" rows="4">{escape(forbidden_paths_text)}</textarea>',
            '<label class="input-label" for="portal-live-expected-changed-files">expected_changed_files</label>',
            f'<textarea id="portal-live-expected-changed-files" class="code-input" rows="4">{escape(expected_changed_files_text)}</textarea>',
            '<label class="input-label" for="portal-live-behavioral-checks">behavioral_checks</label>',
            f'<textarea id="portal-live-behavioral-checks" class="code-input" rows="4">{escape(behavioral_checks_text)}</textarea>',
            '<label class="input-label" for="portal-live-acceptance-checks">acceptance_checks</label>',
            f'<textarea id="portal-live-acceptance-checks" class="code-input" rows="8">{escape(acceptance_checks_text)}</textarea>',
            f'<p class="field-hint">{escape(acceptance_checks_help_text)}</p>',
            '</details>',
            '<details class="sidebar-section" open>',
            '<summary>Harness \u6a21\u5f0f\u5bf9\u6bd4</summary>',
            f'<div id="portal-live-workbench">{workbench_html}</div>',
            '</details>',
            '<details class="sidebar-section">',
            '<summary>\u6700\u8fd1\u4efb\u52a1</summary>',
            f'<div id="portal-live-history">{recent_history_html}</div>',
            '</details>',
            '</aside>',
            '<main class="conversation-shell">',
            '<header class="conversation-header">',
            f'<h1>{escape(title)}</h1>',
            '<p class="conversation-copy">\u8f93\u5165\u4e00\u4e2a\u4ed3\u5e93\u4efb\u52a1\uff0c\u7cfb\u7edf\u4f1a\u5148\u7ed9\u51fa\u5f53\u524d\u4ea4\u4ed8\u7684 plan\uff0c\u518d\u8fd4\u56de\u7ed3\u679c\u548c harness \u5efa\u8bae\u3002</p>',
            f'<div class="status-pill" id="portal-live-status">{escape(status_text)}</div>',
            '</header>',
            '<section class="composer-card">',
            '<div class="composer-top">',
            '<div>',
            '<div class="section-kicker">\u7528\u6237\u8f93\u5165</div>',
            f'<div class="composer-hint">\u793a\u4f8b\uff1a<button id="portal-live-use-example" class="chip-button" type="button">{escape(chat_example_text)}</button></div>',
            '</div>',
            '<div class="composer-actions">',
            '<button id="portal-live-submit" class="button button-primary" type="button">\u8fd0\u884c\u4efb\u52a1</button>',
            '</div>',
            '</div>',
            f'<textarea id="portal-live-task-input" class="task-input" rows="6" placeholder="{escape(task_input_placeholder)}">{escape(task_text)}</textarea>',
            '</section>',
            '<section class="thread-stream">',
            '<div id="portal-live-user-thread"></div>',
            '<section class="thread-section">',
            '<div class="thread-section-title">\u4efb\u52a1\u8ba1\u5212</div>',
            f'<div id="portal-live-plan-stream">{plan_stream_html}</div>',
            '</section>',
            '<section class="thread-section">',
            '<div class="thread-section-title">\u8fd0\u884c\u7ed3\u679c</div>',
            f'<div id="portal-live-results">{results_html}</div>',
            f'<div id="portal-live-links" class="link-row">{links_html}</div>',
            '</section>',
            '<section class="thread-section">',
            '<div class="thread-section-title">\u6539\u8fdb\u5efa\u8bae</div>',
            f'<div id="portal-live-guidance">{guidance_html}</div>',
            '</section>',
            '</section>',
            f'<script id="portal-live-config" type="application/json">{config_json}</script>',
            f'<script>{_script()}</script>',
            '</main>',
            '</div>',
            '</body>',
            '</html>',
        ]
    )

def _styles() -> str:
    return """
:root {
  --bg: #fbf7ef;
  --panel: rgba(255, 253, 248, 0.96);
  --panel-soft: #fff2df;
  --line: #e8ddc9;
  --ink: #1b2430;
  --muted: #6b7280;
  --accent: #0f766e;
  --accent-strong: #115e59;
  --accent-soft: #d9f3ee;
  --warm: #c67a16;
  --warm-soft: #fff1dc;
  --success: #0f7a43;
  --warn: #a16207;
  --danger: #b42318;
  --shadow: 0 22px 44px rgba(27, 36, 48, 0.1);
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 32%),
    radial-gradient(circle at top right, rgba(198, 122, 22, 0.14), transparent 28%),
    var(--bg);
  color: var(--ink);
  font-family: "Segoe UI Variable", "PingFang SC", "Microsoft YaHei UI", sans-serif;
}
a { color: inherit; text-decoration: none; }
pre {
  margin: 0;
  padding: 14px 16px;
  border-radius: 16px;
  background: #f6f7f2;
  border: 1px solid var(--line);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: "Cascadia Code", Consolas, monospace;
  line-height: 1.55;
}
button, input, textarea, select { font: inherit; }
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
}
.workspace-sidebar {
  border-right: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(227, 245, 241, 0.78), rgba(255, 247, 235, 0.9));
  backdrop-filter: blur(12px);
  padding: 22px 18px 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.sidebar-brand {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.brand-mark {
  font-size: 1.4rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--accent-strong);
}
.brand-copy,
.conversation-copy,
.field-hint,
.thread-meta,
.composer-hint,
.status-pill,
.history-meta,
.history-card p {
  color: var(--muted);
}
.sidebar-meta,
.composer-top,
.composer-actions,
.thread-card-top,
.actions,
.link-row,
.history-actions,
.history-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.sidebar-section,
.sidebar-section-plain {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 250, 243, 0.96));
  border: 1px solid rgba(17, 94, 89, 0.12);
  border-radius: 18px;
  padding: 14px;
  box-shadow: var(--shadow);
}
.sidebar-section summary,
.bench-group summary,
.bench-subgroup summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-strong);
}
.sidebar-section[open] summary,
.bench-group[open] summary,
.bench-subgroup[open] summary {
  margin-bottom: 10px;
}
.input-label {
  display: block;
  margin: 0 0 8px;
  font-size: 0.9rem;
  font-weight: 600;
}
.text-input,
.task-input,
.code-input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.96);
  color: var(--ink);
  transition: border-color 140ms ease, box-shadow 140ms ease, background 140ms ease;
}
.text-input:focus,
.task-input:focus,
.code-input:focus {
  outline: none;
  border-color: rgba(15, 118, 110, 0.42);
  box-shadow: 0 0 0 4px rgba(15, 118, 110, 0.12);
  background: #fff;
}
.task-input,
.code-input { resize: vertical; }
.code-input {
  min-height: 96px;
  font-family: "Cascadia Code", Consolas, monospace;
  line-height: 1.55;
}
.conversation-shell {
  padding: 24px 28px 40px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.conversation-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.conversation-header h1 {
  margin: 0;
  font-size: 1.8rem;
  letter-spacing: -0.03em;
  color: var(--accent-strong);
}
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(15, 118, 110, 0.18);
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-weight: 600;
}
.composer-card,
.thread-card {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 251, 245, 0.95));
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: var(--shadow);
}
.composer-card {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.composer-top { justify-content: space-between; }
.section-kicker,
.thread-section-title,
.thread-card-title,
.prompt-block-title {
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--accent-strong);
}
.chip-button,
.button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  border: 1px solid var(--line);
  padding: 9px 14px;
  background: #fff;
  color: var(--ink);
  cursor: pointer;
}
.chip-button {
  background: var(--warm-soft);
  border-color: rgba(198, 122, 22, 0.2);
  color: var(--warm);
}
.button:disabled,
.chip-button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.button-primary {
  background: linear-gradient(135deg, var(--accent), #169b8e);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 12px 24px rgba(15, 118, 110, 0.2);
}
.thread-stream,
.thread-section,
.workbench-stack,
.bench-stack,
.prompt-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.thread-card {
  padding: 16px 18px;
}
.thread-card-user {
  background: linear-gradient(135deg, #0f766e, #1f2937);
  color: #f9fafb;
  border-color: transparent;
}
.thread-card-user .thread-meta,
.thread-card-user .thread-card-title { color: rgba(249, 250, 251, 0.75); }
.thread-role,
.profile-badge,
.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 0.78rem;
}
.thread-role,
.badge-soft {
  background: var(--accent-soft);
  color: var(--accent-strong);
}
.profile-badge {
  background: var(--warm-soft);
  color: var(--warm);
}
.badge-status { background: #f3f4f6; color: #1f2937; }
.badge-status-succeeded { background: #e9f7ef; color: var(--success); }
.badge-status-failed,
.badge-status-error { background: #fdecec; color: var(--danger); }
.badge-status-running,
.badge-status-pending,
.badge-status-skipped { background: #fff4db; color: var(--warn); }
.thread-empty,
.empty {
  border: 1px dashed var(--line);
  border-radius: 16px;
  background: var(--panel-soft);
  padding: 14px;
  color: var(--muted);
}
.plain-list,
.stack-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bench-group,
.bench-subgroup {
  border: 1px solid rgba(198, 122, 22, 0.18);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 252, 247, 0.96), rgba(255, 247, 235, 0.9));
  padding: 12px;
}
.result-card-chat pre {
  background: rgba(247, 250, 252, 0.96);
}
.history-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}
.history-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(255, 248, 238, 0.95));
}
.link-row,
.actions { margin-top: 4px; }
@media (max-width: 980px) {
  .app-shell {
    grid-template-columns: 1fr;
  }
  .workspace-sidebar {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .conversation-shell {
    padding: 18px 14px 28px;
  }
}
"""

def _script() -> str:
    return """
(() => {
  const configEl = document.getElementById("portal-live-config");
  if (!configEl) {
    return;
  }
  const config = JSON.parse(configEl.textContent || "{}");
  const titleInput = document.getElementById("portal-live-title-input");
  const textarea = document.getElementById("portal-live-task-input");
  const taskShapeInput = document.getElementById("portal-live-task-shape");
  const knowledgePackInput = document.getElementById("portal-live-knowledge-pack");
  const repoPathInput = document.getElementById("portal-live-repo-path");
  const contextPathsInput = document.getElementById("portal-live-context-paths");
  const editablePathsInput = document.getElementById("portal-live-editable-paths");
  const forbiddenPathsInput = document.getElementById("portal-live-forbidden-paths");
  const expectedChangedFilesInput = document.getElementById("portal-live-expected-changed-files");
  const behavioralChecksInput = document.getElementById("portal-live-behavioral-checks");
  const acceptanceChecksInput = document.getElementById("portal-live-acceptance-checks");
  const useExampleButton = document.getElementById("portal-live-use-example");
  const submitButton = document.getElementById("portal-live-submit");
  const statusNode = document.getElementById("portal-live-status");
  const userThreadNode = document.getElementById("portal-live-user-thread");
  const planNode = document.getElementById("portal-live-plan-stream");
  const resultsNode = document.getElementById("portal-live-results");
  const guidanceNode = document.getElementById("portal-live-guidance");
  const workbenchNode = document.getElementById("portal-live-workbench");
  const linksNode = document.getElementById("portal-live-links");
  const historyNode = document.getElementById("portal-live-history");
  const defaultPollAfterMs = Number((config && config.poll_after_ms) || 1500);
  let streamToken = 0;

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setStatus(message) {
    if (statusNode) {
      statusNode.textContent = message || "";
    }
  }

  function setRunBusy(isBusy) {
    if (submitButton) {
      submitButton.disabled = !!isBusy;
    }
    if (useExampleButton) {
      useExampleButton.disabled = !!isBusy;
    }
  }

  function setValue(node, value) {
    if (node) {
      node.value = value || "";
    }
  }

  function applyFormData(form) {
    const payload = form || {};
    setValue(titleInput, payload.title || "");
    setValue(textarea, payload.task_text || "");
    setValue(taskShapeInput, payload.task_shape || "general");
    setValue(knowledgePackInput, payload.knowledge_pack || "none");
    setValue(repoPathInput, payload.repo_path || payload.repo_source || "");
    setValue(contextPathsInput, payload.context_paths_text || "");
    setValue(editablePathsInput, payload.editable_paths_text || "");
    setValue(forbiddenPathsInput, payload.forbidden_paths_text || "");
    setValue(expectedChangedFilesInput, payload.expected_changed_files_text || "");
    setValue(behavioralChecksInput, payload.behavioral_checks_text || "");
    setValue(acceptanceChecksInput, payload.acceptance_checks_text || "");
  }

  function collectPayload() {
    const repoSource = repoPathInput && repoPathInput.value ? repoPathInput.value : "";
    return {
      title: titleInput && titleInput.value ? titleInput.value : "",
      task_text: textarea && textarea.value ? textarea.value : "",
      task_shape: taskShapeInput && taskShapeInput.value ? taskShapeInput.value : "general",
      knowledge_pack: knowledgePackInput && knowledgePackInput.value ? knowledgePackInput.value : "none",
      repo_source: repoSource,
      repo_path: repoSource,
      context_paths_text: contextPathsInput && contextPathsInput.value ? contextPathsInput.value : "",
      editable_paths_text: editablePathsInput && editablePathsInput.value ? editablePathsInput.value : "",
      forbidden_paths_text: forbiddenPathsInput && forbiddenPathsInput.value ? forbiddenPathsInput.value : "",
      expected_changed_files_text: expectedChangedFilesInput && expectedChangedFilesInput.value ? expectedChangedFilesInput.value : "",
      behavioral_checks_text: behavioralChecksInput && behavioralChecksInput.value ? behavioralChecksInput.value : "",
      acceptance_checks_text: acceptanceChecksInput && acceptanceChecksInput.value ? acceptanceChecksInput.value : "",
    };
  }

  function renderUserThread(payload) {
    if (!userThreadNode) {
      return;
    }
    const taskText = String((payload && payload.task_text) || "").trim();
    if (!taskText) {
      userThreadNode.innerHTML = "";
      return;
    }
    const repoText = String((payload && (payload.repo_path || payload.repo_source)) || "").trim();
    const meta = repoText ? `\u4ed3\u5e93\uff1a${escapeHtml(repoText)}` : "";
    userThreadNode.innerHTML = `
      <article class="thread-card thread-card-user">
        <div class="thread-card-top">
          <span class="thread-role">\u7528\u6237</span>
        </div>
        <div class="thread-card-title">\u4efb\u52a1\u8f93\u5165</div>
        <p>${escapeHtml(taskText)}</p>
        <div class="thread-meta">${meta}</div>
      </article>
    `;
  }

  function renderPlanPlaceholder(message) {
    if (planNode) {
      planNode.innerHTML = `
        <article class="thread-card thread-card-assistant">
          <p>${escapeHtml(message || "\u8f93\u5165\u4efb\u52a1\u540e\uff0c\u8fd9\u91cc\u4f1a\u663e\u5f0f\u5c55\u5f00\u5f53\u524d\u4ea4\u4ed8\u7684 plan\u3002")}</p>
        </article>
      `;
    }
  }

  function renderPlanCard(message) {
    const bullets = Array.isArray(message && message.bullets) ? message.bullets : [];
    const bulletMarkup = bullets.length
      ? `<ul class="plain-list">${bullets.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
      : '<div class="thread-empty">\u5f53\u524d\u6ca1\u6709\u989d\u5916 plan \u8bf4\u660e\u3002</div>';
    return `
      <article class="thread-card thread-card-assistant plan-card">
        <div class="thread-card-top">
          <span class="thread-role">${escapeHtml((message && message.title) || "Plan")}</span>
          <span class="profile-badge">${escapeHtml((message && message.label) || "")}</span>
        </div>
        <p>${escapeHtml((message && message.summary) || "")}</p>
        ${bulletMarkup}
      </article>
    `;
  }

  async function playPlanStream(messages) {
    const token = ++streamToken;
    const items = Array.isArray(messages) ? messages : [];
    if (!items.length) {
      renderPlanPlaceholder();
      return;
    }
    if (planNode) {
      planNode.innerHTML = "";
    }
    for (let index = 0; index < items.length; index += 1) {
      if (token !== streamToken) {
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, index === 0 ? 120 : 220));
      if (token !== streamToken) {
        return;
      }
      if (planNode) {
        planNode.insertAdjacentHTML("beforeend", renderPlanCard(items[index] || {}));
      }
    }
  }

  function bindHistoryButtons() {
    document.querySelectorAll(".portal-live-load-history").forEach((button) => {
      button.onclick = () => {
        try {
          const form = JSON.parse(button.dataset.form || "{}");
          applyFormData(form);
          renderUserThread(form);
          if (textarea) {
            textarea.focus();
          }
          setStatus("\u5df2\u628a\u5386\u53f2\u4efb\u52a1\u548c\u8bbe\u7f6e\u91cd\u65b0\u586b\u56de\u5de5\u4f5c\u53f0\u3002");
        } catch (error) {
          setStatus("\u91cd\u65b0\u586b\u5165\u5386\u53f2\u4efb\u52a1\u5931\u8d25\u3002");
        }
      };
    });
  }

  function applySharedPayload(payload) {
    if (payload && payload.form_fields) {
      applyFormData(payload.form_fields);
    }
    if (workbenchNode && payload && payload.workbench_html) {
      workbenchNode.innerHTML = payload.workbench_html;
    }
    if (guidanceNode && payload && payload.guidance_html) {
      guidanceNode.innerHTML = payload.guidance_html;
    }
  }

  function applyRunResult(result) {
    applySharedPayload(result);
    if (resultsNode) {
      resultsNode.innerHTML = result.results_html || "";
    }
    if (linksNode) {
      linksNode.innerHTML = result.links_html || "";
    }
    if (historyNode && result.recent_history_html) {
      historyNode.innerHTML = result.recent_history_html;
      bindHistoryButtons();
    }
    renderUserThread((result && result.form_fields) || collectPayload());
  }

  function applyExample() {
    applyFormData((config && config.form_defaults) || {});
    if (textarea && !textarea.value) {
      textarea.value = (config && config.default_task_text) || (config && config.chat_example_input) || "";
    }
    renderUserThread(collectPayload());
  }

  async function readJson(response) {
    const text = await response.text();
    return text ? JSON.parse(text) : {};
  }

  async function fetchPreview(payload) {
    const response = await fetch((config && config.preview_endpoint) || "/api/preview-demo", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const result = await readJson(response);
    if (!response.ok || result.ok === false) {
      throw new Error(result.error || "\u9884\u89c8\u5931\u8d25");
    }
    return result;
  }    async function runDemoSynchronously(payload) {
      const response = await fetch((config && config.run_endpoint) || "/api/run-demo", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const result = await readJson(response);
      if (!response.ok || result.ok === false) {
        throw new Error(result.error || "\u8fd0\u884c\u5931\u8d25");
      }
      return result;
    }

    async function waitForRunResult(jobId, initialPollAfterMs) {
      const statusEndpoint = (config && config.run_status_endpoint) || "/api/run-demo-status";
      let pollAfterMs = Number(initialPollAfterMs || defaultPollAfterMs);
      while (true) {
        await new Promise((resolve) => window.setTimeout(resolve, Math.max(pollAfterMs, 250)));
        const response = await fetch(`${statusEndpoint}?job_id=${encodeURIComponent(jobId)}`, {
          method: "GET",
          headers: {"Accept": "application/json"},
        });
        const result = await readJson(response);
        if (!response.ok || result.ok === false) {
          throw new Error(result.error || "\u67e5\u8be2\u8fd0\u884c\u72b6\u6001\u5931\u8d25");
        }
        setStatus(result.status_text || "\u6b63\u5728\u540e\u53f0\u8fd0\u884c\u5f53\u524d\u4efb\u52a1 ...");
        if (result.done) {
          return result;
        }
        pollAfterMs = Number(result.poll_after_ms || defaultPollAfterMs);
      }
    }

    async function runDemoAsynchronously(payload) {
      const response = await fetch((config && config.run_async_endpoint) || "/api/run-demo-async", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      const accepted = await readJson(response);
      if (!response.ok || accepted.ok === false) {
        throw new Error(accepted.error || "\u4efb\u52a1\u63d0\u4ea4\u5931\u8d25");
      }
      if (!accepted.job_id) {
        throw new Error("\u540e\u53f0\u8fd0\u884c\u672a\u8fd4\u56de\u4efb\u52a1\u7f16\u53f7");
      }
      setStatus(accepted.status_text || "\u4efb\u52a1\u5df2\u63d0\u4ea4\uff0c\u6b63\u5728\u540e\u53f0\u8fd0\u884c\u5f53\u524d\u4efb\u52a1 ...");
      return waitForRunResult(accepted.job_id, accepted.poll_after_ms);
    }

    async function runTask() {
      const payload = collectPayload();
      if (!(payload.task_text || "").trim()) {
        setStatus("\u8bf7\u5148\u8f93\u5165\u60f3\u6267\u884c\u7684\u4efb\u52a1\u3002");
        return;
      }
      if (!(payload.repo_path || "").trim()) {
        setStatus("\u8bf7\u5148\u586b\u5199\u4ed3\u5e93\u6765\u6e90\u3002");
        return;
      }
      renderUserThread(payload);
      setRunBusy(true);
      if (resultsNode) {
        resultsNode.innerHTML = `
          <article class="thread-card thread-card-assistant">
            <p>\u6b63\u5728\u7b49\u5f85\u5f53\u524d\u8fd0\u884c\u7ed3\u679c ...</p>
          </article>
        `;
      }
      if (linksNode) {
        linksNode.innerHTML = "";
      }
      try {
        setStatus("\u6b63\u5728\u68b3\u7406\u5f53\u524d\u4ea4\u4ed8 plan ...");
        const preview = await fetchPreview(payload);
        applySharedPayload(preview);
        await playPlanStream(preview.plan_messages || []);
        setStatus(preview.status_text || "\u5df2\u751f\u6210\u5f53\u524d\u4ea4\u4ed8 plan\u3002");

        if (!(config && config.api_ready)) {
          setStatus((config && config.api_message) || "\u5df2\u5b8c\u6210 plan \u9610\u660e\uff0c\u5f53\u524d\u6a21\u578b API \u4e0d\u53ef\u7528\u3002");
          return;
        }

        setStatus("\u5f53\u524d\u4ea4\u4ed8 plan \u5df2\u5c55\u5f00\uff0c\u6b63\u5728\u8fd0\u884c\u4efb\u52a1 ...");
        const result = (config && config.run_async_endpoint)
          ? await runDemoAsynchronously(payload)
          : await runDemoSynchronously(payload);
        applyRunResult(result);
        setStatus(result.status_text || "\u5df2\u5b8c\u6210\u5f53\u524d\u8fd0\u884c\u3002");
      } catch (error) {
        const message = error && error.message ? error.message : "\u8fd0\u884c\u5931\u8d25";
        setStatus(message);
      } finally {
        setRunBusy(false);
      }
    }

    if (submitButton) {
      submitButton.addEventListener("click", runTask);
    }
    if (useExampleButton) {
      useExampleButton.addEventListener("click", () => {
        applyExample();
        if (textarea) {
          textarea.focus();
        }
        setStatus("\u5df2\u586b\u5165\u793a\u4f8b\uff0c\u53ef\u4ee5\u76f4\u63a5\u8fd0\u884c\u3002");
      });
    }
    if (textarea) {
      textarea.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
          event.preventDefault();
          runTask();
        }
      });
    }

    bindHistoryButtons();
})();
"""
