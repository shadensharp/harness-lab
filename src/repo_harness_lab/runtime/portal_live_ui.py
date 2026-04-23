from __future__ import annotations

import json
from html import escape


def render_live_portal_shell(state: dict[str, object]) -> str:
    config_json = json.dumps(state.get("config", {}), ensure_ascii=False).replace("</", "<\\/")
    title = str(state.get("page_title") or "harness-lab")
    status_text = str(state.get("status_text") or "等待任务输入")
    model_display_name = str(state.get("model_display_name") or "")
    chat_example_text = str(state.get("chat_example_text") or "")
    results_html = str(state.get("results_html") or "")
    links_html = str(state.get("links_html") or "")
    workbench_html = str(state.get("workbench_html") or "")
    guidance_html = str(state.get("guidance_html") or "")
    plan_stream_html = str(state.get("profile_explainer_html") or "")
    recent_history_html = str(state.get("recent_history_html") or "")
    repo_source_input_label = str(state.get("repo_source_input_label") or "仓库来源")
    repo_source_placeholder = str(state.get("repo_source_placeholder") or "")
    advanced_settings_summary = str(state.get("advanced_settings_summary") or "可选高级字段")
    acceptance_checks_help_text = str(state.get("acceptance_checks_help_text") or "")
    task_shape_options = list(state.get("task_shape_options") or ())
    knowledge_pack_options = list(state.get("knowledge_pack_options") or ())
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

    swe_benchmark_name = str(state.get("swe_benchmark_name") or "SWE-bench Verified")
    swe_instance_id = str(state.get("swe_instance_id") or "sympy__sympy-20590")
    swe_profile_name = str(state.get("swe_profile_name") or "current")

    task_shape_options_markup = _render_select_options(task_shape_options, selected=task_shape)
    knowledge_pack_options_markup = _render_select_options(knowledge_pack_options, selected=knowledge_pack)
    metrics_html = _render_metrics(
        list(state.get("results") or ()),
        swe_benchmark_name=swe_benchmark_name,
        swe_instance_id=swe_instance_id,
        swe_profile_name=swe_profile_name,
        model_display_name=model_display_name,
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
            '<div class="app-shell">',
            '<header class="topbar">',
            '<div class="topbar-brand">',
            '<div class="brand-icon">∎</div>',
            f'<div class="brand-title">{escape(title)}</div>',
            "</div>",
            '<div class="topbar-meta">',
            f'<span class="meta-pill">{escape(model_display_name)}</span>',
            f'<span class="meta-pill">{escape(swe_benchmark_name)}</span>',
            "</div>",
            "</header>",
            '<div class="workspace-shell">',
            '<aside class="sidebar" id="portal-live-sidebar">',
            '<div class="sidebar-head">',
            '<div class="sidebar-title">工作台</div>',
            '<button id="portal-live-sidebar-toggle" class="icon-button" type="button" aria-label="toggle sidebar">☰</button>',
            "</div>",
            '<div class="sidebar-scroll">',
            '<details class="sidebar-block" open>',
            "<summary>最近任务</summary>",
            f'<div class="sidebar-body"><div id="portal-live-history">{recent_history_html}</div></div>',
            "</details>",
            '<details class="sidebar-block">',
            "<summary>计划</summary>",
            f'<div class="sidebar-body"><div id="portal-live-plan-stream">{plan_stream_html}</div></div>',
            "</details>",
            '<details class="sidebar-block">',
            "<summary>建议</summary>",
            f'<div class="sidebar-body"><div id="portal-live-guidance">{guidance_html}</div></div>',
            "</details>",
            '<details class="sidebar-block">',
            f"<summary>{escape(advanced_settings_summary)}</summary>",
            '<div class="sidebar-body">',
            f'<label class="field-label" for="portal-live-context-paths">context_paths</label>',
            f'<textarea id="portal-live-context-paths" class="side-textarea" rows="4">{escape(context_paths_text)}</textarea>',
            f'<label class="field-label" for="portal-live-editable-paths">editable_paths</label>',
            f'<textarea id="portal-live-editable-paths" class="side-textarea" rows="4">{escape(editable_paths_text)}</textarea>',
            f'<label class="field-label" for="portal-live-forbidden-paths">forbidden_paths</label>',
            f'<textarea id="portal-live-forbidden-paths" class="side-textarea" rows="3">{escape(forbidden_paths_text)}</textarea>',
            f'<label class="field-label" for="portal-live-expected-changed-files">expected_changed_files</label>',
            f'<textarea id="portal-live-expected-changed-files" class="side-textarea" rows="3">{escape(expected_changed_files_text)}</textarea>',
            f'<label class="field-label" for="portal-live-behavioral-checks">behavioral_checks</label>',
            f'<textarea id="portal-live-behavioral-checks" class="side-textarea" rows="4">{escape(behavioral_checks_text)}</textarea>',
            f'<label class="field-label" for="portal-live-acceptance-checks">acceptance_checks</label>',
            f'<textarea id="portal-live-acceptance-checks" class="side-textarea" rows="6">{escape(acceptance_checks_text)}</textarea>',
            f'<div class="field-help">{escape(acceptance_checks_help_text)}</div>',
            "</div>",
            "</details>",
            '<div id="portal-live-user-thread" class="hidden-node"></div>',
            "</div>",
            "</aside>",
            '<main class="stage">',
            '<section class="glass hero-card">',
            '<div class="hero-copy">',
            '<div class="section-kicker">用户输入</div>',
            f'<div id="portal-live-status" class="hero-status">{escape(status_text)}</div>',
            "</div>",
            '<div class="hero-tags">',
            f'<span class="hero-tag">{escape(swe_instance_id)}</span>',
            f'<span class="hero-tag">{escape(swe_profile_name)}</span>',
            "</div>",
            "</section>",
            f'<section id="portal-live-result-metrics" class="metric-grid">{metrics_html}</section>',
            '<section class="workflow-grid">',
            '<section class="glass task-card">',
            '<div class="card-head">',
            "<h1>任务</h1>",
            '<div class="mode-switch">',
            '<button id="portal-live-mode-swe" class="mode-button active" data-mode="swe" type="button">swe-bench</button>',
            '<button id="portal-live-mode-custom" class="mode-button" data-mode="custom" type="button">custom</button>',
            "</div>",
            "</div>",
            '<div class="card-body">',
            f'<input id="portal-live-title-input" type="hidden" value="{escape(form_title)}">',
            f'<select id="portal-live-task-shape" class="hidden-node">{task_shape_options_markup}</select>',
            f'<select id="portal-live-knowledge-pack" class="hidden-node">{knowledge_pack_options_markup}</select>',
            '<div id="portal-live-swe-fields" class="swe-fields">',
            '<div class="info-row"><span class="info-label">benchmark</span>',
            f'<span class="info-value">{escape(swe_benchmark_name)}</span></div>',
            '<div class="info-row"><span class="info-label">instance</span>',
            f'<span class="info-value">{escape(swe_instance_id)}</span></div>',
            '<div class="info-row"><span class="info-label">profile</span>',
            f'<span class="info-value">{escape(swe_profile_name)}</span></div>',
            "</div>",
            '<div id="portal-live-custom-fields" class="custom-fields is-hidden">',
            '<label class="field-block" for="portal-live-task-input">',
            "<span>任务定义</span>",
            f'<textarea id="portal-live-task-input" class="task-textarea" rows="4" placeholder="{escape(chat_example_text)}">{escape(task_text)}</textarea>',
            "</label>",
            '<label class="field-block" for="portal-live-repo-path">',
            f"<span>{escape(repo_source_input_label)}</span>",
            f'<input id="portal-live-repo-path" class="task-input" type="text" value="{escape(repo_path)}" placeholder="{escape(repo_source_placeholder)}">',
            "</label>",
            '<label class="field-block" for="portal-live-acceptance-input">',
            "<span>验收标准</span>",
            f'<textarea id="portal-live-acceptance-input" class="task-textarea" rows="4" placeholder="python -m pytest -q">{escape(acceptance_checks_text)}</textarea>',
            "</label>",
            "</div>",
            '<div class="task-actions">',
            '<button id="portal-live-use-example" class="secondary-button" type="button">示例</button>',
            '<button id="portal-live-submit" class="primary-button" type="button">运行任务</button>',
            "</div>",
            "</div>",
            "</section>",
            '<section class="glass progress-card">',
            '<div class="card-head">',
            "<h2>进度</h2>",
            '<div class="progress-flag"><span class="progress-dot" id="portal-live-busy-dot"></span><span id="portal-live-busy-state">待命</span></div>',
            "</div>",
            '<div id="portal-live-progress" class="progress-track">',
            '<div class="progress-step" data-phase-index="1"><span class="step-index">01</span><span class="step-name">任务</span><span class="step-badge" data-badge>等待</span></div>',
            '<div class="progress-step" data-phase-index="2"><span class="step-index">02</span><span class="step-name">工作区</span><span class="step-badge" data-badge>等待</span></div>',
            '<div class="progress-step" data-phase-index="3"><span class="step-index">03</span><span class="step-name">执行</span><span class="step-badge" data-badge>等待</span></div>',
            '<div class="progress-step" data-phase-index="4"><span class="step-index">04</span><span class="step-name">验收</span><span class="step-badge" data-badge>等待</span></div>',
            '<div class="progress-step" data-phase-index="5"><span class="step-index">05</span><span class="step-name">结果</span><span class="step-badge" data-badge>等待</span></div>',
            "</div>",
            "</section>",
            "</section>",
            '<section class="glass story-shell">',
            '<div class="card-head">',
            "<h2>全流程总览</h2>",
            '<div class="result-chip">首屏只看粗粒度结论</div>',
            "</div>",
            f'<div id="portal-live-workbench">{workbench_html}</div>',
            "</section>",
            '<section class="glass result-card">',
            '<div class="card-head">',
            "<h2>运行明细</h2>",
            '<div class="result-chip" id="portal-live-result-chip">-</div>',
            "</div>",
            '<div class="result-scroll">',
            '<details class="result-block" open>',
            "<summary>输出</summary>",
            f'<div class="result-body"><div id="portal-live-results">{results_html}</div></div>',
            "</details>",
            '<details class="result-block">',
            "<summary>链接</summary>",
            f'<div class="result-body"><div id="portal-live-links">{links_html}</div></div>',
            "</details>",
            "</div>",
            "</section>",
            f'<script id="portal-live-config" type="application/json">{config_json}</script>',
            f"<script>{_script()}</script>",
            "</main>",
            "</div>",
            "</div>",
            "</body>",
            "</html>",
        ]
    )


def _render_select_options(options: list[object], *, selected: str) -> str:
    parts: list[str] = []
    for item in options:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "")
        label = str(item.get("label") or value)
        selected_attr = ' selected="selected"' if value == selected else ""
        parts.append(f'<option value="{escape(value)}"{selected_attr}>{escape(label)}</option>')
    return "".join(parts)


def _render_metrics(
    results: list[object],
    *,
    swe_benchmark_name: str,
    swe_instance_id: str,
    swe_profile_name: str,
    model_display_name: str,
) -> str:
    primary = results[0] if results and isinstance(results[0], dict) else {}
    cards = [
        ("status", str(primary.get("status_label") or primary.get("status") or "-"), swe_benchmark_name),
        ("verifier", str(primary.get("verifier_label") or primary.get("verifier") or "-"), swe_benchmark_name),
        ("instance", swe_instance_id, swe_benchmark_name),
        ("profile", str(primary.get("profile_label") or primary.get("profile") or swe_profile_name), model_display_name),
    ]
    return "".join(
        "".join(
            [
                '<article class="glass metric-card">',
                f'<div class="metric-label">{escape(label)}</div>',
                f'<div class="metric-value">{escape(value)}</div>',
                f'<div class="metric-sub">{escape(sub)}</div>',
                "</article>",
            ]
        )
        for label, value, sub in cards
    )


def _styles() -> str:
    return """
:root {
  --bg: #f6f1e7;
  --panel: rgba(255, 251, 245, 0.92);
  --line: rgba(120, 98, 72, 0.14);
  --text: #1f2937;
  --muted: #6b7280;
  --ok: #10b981;
  --danger: #dc2626;
  --shadow: 0 18px 40px rgba(120, 98, 72, 0.14);
}
* {
  box-sizing: border-box;
}
html,
body {
  height: 100%;
  margin: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(251, 191, 36, 0.12), transparent 24%),
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.12), transparent 26%),
    linear-gradient(180deg, #fbf7ef 0%, #f2ece2 100%);
  color: var(--text);
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
a {
  color: #4338ca;
}
.app-shell {
  height: 100%;
  display: grid;
  grid-template-rows: 64px minmax(0, 1fr);
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid var(--line);
  background: rgba(251, 247, 239, 0.84);
  backdrop-filter: blur(16px);
}
.topbar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: linear-gradient(135deg, #1d4ed8, #f59e0b);
  color: #fff;
  font-size: 18px;
  font-weight: 700;
}
.brand-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.03em;
}
.topbar-meta {
  display: flex;
  gap: 10px;
}
.meta-pill {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.82);
  color: var(--muted);
  font-size: 12px;
}
.workspace-shell {
  min-height: 0;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
}
.sidebar {
  min-width: 0;
  border-right: 1px solid var(--line);
  background: rgba(248, 244, 236, 0.76);
}
.sidebar-head {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
}
.sidebar-title {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #475569;
}
.icon-button {
  width: 36px;
  height: 36px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.9);
  color: var(--text);
  cursor: pointer;
}
.sidebar-scroll {
  height: calc(100vh - 124px);
  padding: 16px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sidebar-block,
.result-block {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.9);
}
.sidebar-block > summary,
.result-block > summary {
  cursor: pointer;
  list-style: none;
  padding: 14px 16px;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}
.sidebar-block > summary::-webkit-details-marker,
.result-block > summary::-webkit-details-marker {
  display: none;
}
.sidebar-body,
.result-body {
  padding: 0 16px 16px;
}
.field-label,
.field-block > span {
  display: block;
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--muted);
}
.field-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.side-textarea,
.task-textarea,
.task-input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  color: var(--text);
  padding: 12px 14px;
  font: inherit;
}
.side-textarea {
  margin-bottom: 12px;
  resize: vertical;
}
.field-help {
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
}
.stage {
  min-width: 0;
  min-height: 0;
  padding: 20px;
  overflow: hidden;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 16px;
}
.glass {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  backdrop-filter: blur(18px);
  box-shadow: var(--shadow);
}
.hero-card {
  padding: 16px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.hero-copy {
  min-width: 0;
}
.section-kicker {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.hero-status {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.hero-tag {
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.12);
  color: #1d4ed8;
  font-size: 12px;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}
.metric-card {
  padding: 18px;
}
.metric-label {
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.metric-value {
  margin-top: 10px;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.04em;
}
.metric-sub {
  margin-top: 10px;
  font-size: 12px;
  color: #4f46e5;
}
.workflow-grid {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  gap: 16px;
}
.task-card,
.progress-card,
.result-card {
  min-height: 0;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--line);
}
.card-head h1,
.card-head h2 {
  margin: 0;
  font-size: 18px;
}
.card-body {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.mode-switch {
  display: inline-flex;
  gap: 8px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(241, 235, 226, 0.92);
}
.mode-button {
  border: 0;
  background: transparent;
  color: var(--muted);
  border-radius: 999px;
  padding: 8px 14px;
  cursor: pointer;
}
.mode-button.active {
  background: #ffffff;
  color: #111827;
  font-weight: 700;
}
.swe-fields,
.custom-fields {
  display: grid;
  gap: 12px;
}
.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.78);
}
.info-label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.info-value {
  font-size: 14px;
  font-weight: 600;
}
.task-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.primary-button,
.secondary-button {
  height: 40px;
  padding: 0 16px;
  border-radius: 999px;
  border: 0;
  cursor: pointer;
  font: inherit;
}
.primary-button {
  background: #111827;
  color: #f8fafc;
  font-weight: 700;
}
.secondary-button {
  background: rgba(241, 235, 226, 0.92);
  color: var(--text);
  border: 1px solid var(--line);
}
.progress-card {
  display: flex;
  flex-direction: column;
}
.progress-flag {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
}
.progress-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: rgba(107, 114, 128, 0.5);
}
body.is-running .progress-dot {
  background: var(--ok);
  box-shadow: 0 0 0 8px rgba(52, 211, 153, 0.18);
}
.progress-track {
  min-height: 0;
  padding: 18px;
  display: grid;
  gap: 12px;
}
.progress-step {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.82);
}
.step-index {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: rgba(79, 70, 229, 0.1);
  color: #4f46e5;
  font-size: 12px;
  font-weight: 700;
}
.step-name {
  font-size: 14px;
  font-weight: 600;
}
.step-badge {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--muted);
  background: rgba(226, 232, 240, 0.9);
}
.progress-step.is-active {
  border-color: rgba(52, 211, 153, 0.36);
}
.progress-step.is-active .step-badge {
  color: #064e3b;
  background: var(--ok);
}
.progress-step.is-done .step-badge {
  color: #1e3a8a;
  background: #bfdbfe;
}
.progress-step.is-failed .step-badge {
  color: #fff7ed;
  background: var(--danger);
}
.result-card {
  display: flex;
  flex-direction: column;
}
.result-chip {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.9);
  color: var(--muted);
  font-size: 12px;
}
.result-scroll {
  min-height: 0;
  padding: 18px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.story-shell {
  padding: 0 0 18px;
}
.story-shell #portal-live-workbench {
  padding: 18px;
}
.story-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.story-card {
  border: 1px solid var(--line);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.9);
  padding: 16px 18px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}
.story-head {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  margin-bottom: 12px;
}
.story-step {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(13, 148, 136, 0.18), rgba(245, 158, 11, 0.22));
  color: #0f172a;
  font-size: 18px;
  font-weight: 700;
}
.story-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.story-title-row h3 {
  margin: 0;
  font-size: 18px;
}
.story-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 6px 10px;
  border: 1px solid var(--line);
  background: rgba(248, 250, 252, 0.92);
  color: var(--muted);
  font-size: 12px;
}
.story-headline {
  margin: 8px 0 0;
  color: #334155;
  line-height: 1.6;
}
.story-list,
.story-detail-list {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: #334155;
}
.story-detail {
  margin-top: 12px;
  border-top: 1px dashed rgba(120, 98, 72, 0.2);
  padding-top: 12px;
}
.story-detail > summary {
  cursor: pointer;
  color: #0f766e;
  font-weight: 600;
}
.story-detail-body {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.story-kv-grid {
  display: grid;
  gap: 10px;
}
.story-kv-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(120, 98, 72, 0.12);
}
.story-kv-row:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}
.story-kv-label {
  color: var(--muted);
  font-size: 13px;
}
.story-kv-value {
  color: #1f2937;
}
.story-link-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.story-link-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.92);
  color: #1d4ed8;
}
.story-pre-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.story-pre-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--muted);
}
.story-empty {
  border: 1px dashed var(--line);
  border-radius: 16px;
  padding: 12px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.76);
}
.story-status-failed .story-step {
  background: linear-gradient(135deg, rgba(220, 38, 38, 0.18), rgba(248, 113, 113, 0.24));
}
.story-status-done .story-step {
  background: linear-gradient(135deg, rgba(5, 150, 105, 0.18), rgba(52, 211, 153, 0.24));
}
.story-status-pending .story-step {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.18), rgba(251, 191, 36, 0.24));
}
.thread-card {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.86);
  padding: 14px 16px;
}
.thread-card-title {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 8px;
}
.thread-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.thread-role,
.profile-badge,
.thread-meta {
  color: var(--muted);
  font-size: 12px;
}
.thread-card p,
.thread-card pre,
.plain-list {
  margin: 0;
  line-height: 1.6;
}
.plain-list {
  padding-left: 18px;
}
.actions,
#portal-live-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}
.button,
#portal-live-links a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.92);
  color: var(--text);
  text-decoration: none;
}
.hidden-node,
.is-hidden {
  display: none !important;
}
body.sidebar-collapsed .workspace-shell {
  grid-template-columns: 76px minmax(0, 1fr);
}
body.sidebar-collapsed .sidebar-title,
body.sidebar-collapsed .sidebar-block > summary,
body.sidebar-collapsed .sidebar-body {
  display: none;
}
body.sidebar-collapsed .sidebar-scroll {
  padding: 12px 10px;
}
body.sidebar-collapsed .sidebar-block {
  min-height: 48px;
}
@media (max-width: 1360px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
"""


def _script() -> str:
    return """
(() => {
  const body = document.body;
  const config = JSON.parse(document.getElementById("portal-live-config")?.textContent || "{}");
  const sidebarToggle = document.getElementById("portal-live-sidebar-toggle");
  const titleInput = document.getElementById("portal-live-title-input");
  const taskInput = document.getElementById("portal-live-task-input");
  const taskShapeInput = document.getElementById("portal-live-task-shape");
  const knowledgePackInput = document.getElementById("portal-live-knowledge-pack");
  const repoPathInput = document.getElementById("portal-live-repo-path");
  const acceptanceInput = document.getElementById("portal-live-acceptance-input");
  const contextPathsInput = document.getElementById("portal-live-context-paths");
  const editablePathsInput = document.getElementById("portal-live-editable-paths");
  const forbiddenPathsInput = document.getElementById("portal-live-forbidden-paths");
  const expectedChangedFilesInput = document.getElementById("portal-live-expected-changed-files");
  const behavioralChecksInput = document.getElementById("portal-live-behavioral-checks");
  const acceptanceChecksInput = document.getElementById("portal-live-acceptance-checks");
  const useExampleButton = document.getElementById("portal-live-use-example");
  const submitButton = document.getElementById("portal-live-submit");
  const statusNode = document.getElementById("portal-live-status");
  const busyStateNode = document.getElementById("portal-live-busy-state");
  const sweModeButton = document.getElementById("portal-live-mode-swe");
  const customModeButton = document.getElementById("portal-live-mode-custom");
  const sweFieldsNode = document.getElementById("portal-live-swe-fields");
  const customFieldsNode = document.getElementById("portal-live-custom-fields");
  const progressNode = document.getElementById("portal-live-progress");
  const metricsNode = document.getElementById("portal-live-result-metrics");
  const resultChipNode = document.getElementById("portal-live-result-chip");
  const workbenchNode = document.getElementById("portal-live-workbench");
  const planNode = document.getElementById("portal-live-plan-stream");
  const guidanceNode = document.getElementById("portal-live-guidance");
  const resultsNode = document.getElementById("portal-live-results");
  const linksNode = document.getElementById("portal-live-links");
  const historyNode = document.getElementById("portal-live-history");
  const defaultPollAfterMs = Number(config.poll_after_ms || 1500);
  const stepNodes = Array.from(progressNode?.querySelectorAll(".progress-step") || []);
  let currentMode = "swe";
  let planToken = 0;

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setStatus(message) {
    if (statusNode) {
      statusNode.textContent = message || "";
    }
  }

  function setBusyState(label, isRunning) {
    if (busyStateNode) {
      busyStateNode.textContent = label || "";
    }
    body.classList.toggle("is-running", !!isRunning);
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

  function setMode(mode) {
    currentMode = mode === "custom" ? "custom" : "swe";
    sweModeButton?.classList.toggle("active", currentMode === "swe");
    customModeButton?.classList.toggle("active", currentMode === "custom");
    sweFieldsNode?.classList.toggle("is-hidden", currentMode !== "swe");
    customFieldsNode?.classList.toggle("is-hidden", currentMode !== "custom");
  }

  function applyFormData(form) {
    const payload = form || {};
    setValue(titleInput, payload.title || "");
    setValue(taskInput, payload.task_text || "");
    setValue(taskShapeInput, payload.task_shape || "general");
    setValue(knowledgePackInput, payload.knowledge_pack || "none");
    setValue(repoPathInput, payload.repo_path || payload.repo_source || "");
    setValue(contextPathsInput, payload.context_paths_text || "");
    setValue(editablePathsInput, payload.editable_paths_text || "");
    setValue(forbiddenPathsInput, payload.forbidden_paths_text || "");
    setValue(expectedChangedFilesInput, payload.expected_changed_files_text || "");
    setValue(behavioralChecksInput, payload.behavioral_checks_text || "");
    setValue(acceptanceChecksInput, payload.acceptance_checks_text || "");
    setValue(acceptanceInput, payload.acceptance_checks_text || "");
  }

  function collectPayload() {
    const repoSource = repoPathInput?.value || "";
    const acceptanceChecksText = acceptanceInput?.value || acceptanceChecksInput?.value || "";
    return {
      title: titleInput?.value || "",
      task_text: taskInput?.value || "",
      task_shape: taskShapeInput?.value || "general",
      knowledge_pack: knowledgePackInput?.value || "none",
      repo_source: repoSource,
      repo_path: repoSource,
      context_paths_text: contextPathsInput?.value || "",
      editable_paths_text: editablePathsInput?.value || "",
      forbidden_paths_text: forbiddenPathsInput?.value || "",
      expected_changed_files_text: expectedChangedFilesInput?.value || "",
      behavioral_checks_text: behavioralChecksInput?.value || "",
      acceptance_checks_text: acceptanceChecksText,
    };
  }

  function renderMetrics(result) {
    const item = Array.isArray(result?.results) ? (result.results[0] || {}) : {};
    const cards = [
      ["status", item.status_label || item.status || "-", config.swe_benchmark_name || "benchmark"],
      ["verifier", item.verifier_label || item.verifier || "-", config.swe_benchmark_name || "benchmark"],
      ["duration", item.duration_text || "-", config.swe_instance_id || "instance"],
      ["profile", item.profile_label || item.profile || "-", config.model_display_name || ""],
    ];
    if (metricsNode) {
      metricsNode.innerHTML = cards.map(([label, value, sub]) => `
        <article class="glass metric-card">
          <div class="metric-label">${escapeHtml(label)}</div>
          <div class="metric-value">${escapeHtml(value)}</div>
          <div class="metric-sub">${escapeHtml(sub)}</div>
        </article>
      `).join("");
    }
    if (resultChipNode) {
      resultChipNode.textContent = String(item.status_label || item.status || "-");
    }
  }

  function renderPlanCard(message) {
    const bullets = Array.isArray(message?.bullets) ? message.bullets : [];
    const bulletHtml = bullets.length
      ? `<ul class="plain-list">${bullets.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
      : "";
    return `
      <article class="thread-card thread-card-assistant">
        <div class="thread-card-top">
          <span class="thread-role">${escapeHtml(message?.title || "Plan")}</span>
          <span class="profile-badge">${escapeHtml(message?.label || "")}</span>
        </div>
        <div class="thread-card-title">${escapeHtml(message?.summary || "")}</div>
        ${bulletHtml}
      </article>
    `;
  }

  async function playPlanStream(messages) {
    const token = ++planToken;
    const items = Array.isArray(messages) ? messages : [];
    if (!planNode) return;
    if (!items.length) {
      planNode.innerHTML = '<article class="thread-card thread-card-assistant"><p>等待任务输入</p></article>';
      return;
    }
    planNode.innerHTML = "";
    for (let index = 0; index < items.length; index += 1) {
      if (token !== planToken) return;
      await new Promise((resolve) => window.setTimeout(resolve, index === 0 ? 80 : 160));
      if (token !== planToken) return;
      planNode.insertAdjacentHTML("beforeend", renderPlanCard(items[index]));
    }
  }

  function bindHistoryButtons() {
    document.querySelectorAll(".portal-live-load-history").forEach((button) => {
      button.onclick = () => {
        try {
          const form = JSON.parse(button.dataset.form || "{}");
          setMode("custom");
          applyFormData(form);
          setStatus("已载入历史任务");
        } catch (error) {
          setStatus("历史任务载入失败");
        }
      };
    });
  }

  function applySharedPayload(payload) {
    if (payload?.form_fields) {
      applyFormData(payload.form_fields);
    }
    if (workbenchNode && payload?.workbench_html) {
      workbenchNode.innerHTML = payload.workbench_html;
    }
    if (guidanceNode && payload?.guidance_html) {
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
    renderMetrics(result);
  }

  function applyExample() {
    setMode("custom");
    applyFormData(config.form_defaults || {});
    if (taskInput && !taskInput.value) {
      taskInput.value = config.default_task_text || config.chat_example_input || "";
    }
    if (acceptanceInput && !acceptanceInput.value && acceptanceChecksInput) {
      acceptanceInput.value = acceptanceChecksInput.value || "";
    }
  }

  function applyProgress(phase, busy, failed) {
    const phaseOrder = { queued: 1, prepare: 2, intake: 2, run: 3, collect: 4, completed: 5, failed: 5 };
    const activeIndex = phaseOrder[String(phase || "").trim()] || 1;
    stepNodes.forEach((node, index) => {
      const stepIndex = index + 1;
      const badge = node.querySelector("[data-badge]");
      node.classList.remove("is-done", "is-active", "is-failed");
      if (stepIndex < activeIndex || (stepIndex === activeIndex && phase === "completed")) {
        node.classList.add("is-done");
        if (badge) badge.textContent = "完成";
        return;
      }
      if (stepIndex === activeIndex) {
        if (failed) {
          node.classList.add("is-failed");
          if (badge) badge.textContent = "失败";
          return;
        }
        node.classList.add("is-active");
        if (badge) badge.textContent = busy ? "进行中" : "完成";
        return;
      }
      if (badge) badge.textContent = "等待";
    });
  }

  async function readJson(response) {
    const text = await response.text();
    return text ? JSON.parse(text) : {};
  }

  async function fetchPreview(payload) {
    const response = await fetch(config.preview_endpoint || "/api/preview-demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await readJson(response);
    if (!response.ok || result.ok === false) {
      throw new Error(result.error || "预览失败");
    }
    return result;
  }

  async function runDemoSynchronously(payload) {
    const response = await fetch(config.run_endpoint || "/api/run-demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await readJson(response);
    if (!response.ok || result.ok === false) {
      throw new Error(result.error || "运行失败");
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
        headers: { Accept: "application/json" },
      });
      const result = await readJson(response);
      if (!response.ok || result.ok === false) {
        throw new Error(result.error || "查询运行状态失败");
      }
      setStatus(result.status_text || "运行中");
      applyProgress(result.current_phase || "run", true, false);
      if (result.done) {
        return result;
      }
      pollAfterMs = Number(result.poll_after_ms || defaultPollAfterMs);
    }
  }

  async function runDemoAsynchronously(payload) {
    const response = await fetch(config.run_async_endpoint || "/api/run-demo-async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const accepted = await readJson(response);
    if (!response.ok || accepted.ok === false) {
      throw new Error(accepted.error || "任务提交失败");
    }
    setStatus(accepted.status_text || "任务已提交");
    applyProgress(accepted.current_phase || "queued", true, false);
    return waitForRunResult(accepted.job_id, accepted.poll_after_ms);
  }

  async function runTask() {
    if (currentMode === "swe") {
      setStatus("SWE-bench 当前只展示实例；运行入口待接通");
      applyProgress("queued", false, false);
      return;
    }
    const payload = collectPayload();
    if (!String(payload.task_text || "").trim()) {
      setStatus("请先输入任务定义");
      return;
    }
    if (!String(payload.repo_path || "").trim()) {
      setStatus("请先填写仓库地址");
      return;
    }
    setRunBusy(true);
    setBusyState("进行中", true);
    applyProgress("prepare", true, false);
    if (resultsNode) {
      resultsNode.innerHTML = '<article class="thread-card thread-card-assistant"><p>运行中</p></article>';
    }
    if (linksNode) {
      linksNode.innerHTML = "";
    }
    try {
      setStatus("正在准备任务");
      const preview = await fetchPreview(payload);
      applySharedPayload(preview);
      await playPlanStream(preview.plan_messages || []);
      setStatus(preview.status_text || "已生成计划");
      applyProgress("prepare", true, false);
      if (!config.api_ready) {
        setBusyState("待命", false);
        setRunBusy(false);
        return;
      }
      const result = config.run_async_endpoint
        ? await runDemoAsynchronously(payload)
        : await runDemoSynchronously(payload);
      applyRunResult(result);
      setStatus(result.status_text || "已完成");
      setBusyState("完成", false);
      applyProgress(result.current_phase || "completed", false, false);
    } catch (error) {
      const message = error?.message || "运行失败";
      setStatus(message);
      setBusyState("失败", false);
      applyProgress("failed", false, true);
    } finally {
      setRunBusy(false);
    }
  }

  sidebarToggle?.addEventListener("click", () => body.classList.toggle("sidebar-collapsed"));
  sweModeButton?.addEventListener("click", () => setMode("swe"));
  customModeButton?.addEventListener("click", () => setMode("custom"));
  submitButton?.addEventListener("click", runTask);
  useExampleButton?.addEventListener("click", applyExample);
  taskInput?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      runTask();
    }
  });

  bindHistoryButtons();
  renderMetrics({});
  applyProgress("queued", false, false);
  setBusyState("待命", false);
})();
"""
