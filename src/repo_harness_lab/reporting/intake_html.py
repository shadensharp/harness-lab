from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from repo_harness_lab.reporting.text_localization import localize_harness_message


def render_task_intake_preview(preview: Mapping[str, Any] | object) -> str:
    payload = dict(preview) if isinstance(preview, Mapping) else {}
    task = _mapping(payload.get("task_spec_preview"))
    matrix = _mapping(payload.get("harness_delivery_matrix"))
    readiness = _mapping(payload.get("uplift_readiness"))
    deltas = _sequence_of_mappings(payload.get("profile_delta_summary"))
    commands = _mapping(payload.get("suggested_commands"))
    risks = tuple(localize_harness_message(item) for item in _sequence(payload.get("risk_warnings")))
    source_path = str(payload.get("source_path") or "n/a")
    task_id = str(task.get("task_id") or "task-intake-preview")
    title = str(task.get("title") or task_id)
    description = str(task.get("description") or "这里展示从业务请求到 same-model harness 任务入口的收口结果。")
    repo_source_kind = str(task.get("repo_source_kind") or "n/a")
    recommendation_score = str(readiness.get("recommendation_score") or "n/a")
    task_text = title if not description else f"{title}\n\n{description}"

    profile_cards = "".join(_profile_card(name, _mapping(item)) for name, item in matrix.items())
    delta_cards = "".join(_delta_card(item) for item in deltas)
    command_cards = "".join(_command_card(name, command) for name, command in commands.items())

    task_contract = _facts(
        (
            ("任务 ID", task_id),
            ("任务类型", str(task.get("task_type") or "n/a")),
            ("可改文件", _join(_sequence(task.get("editable_paths")))),
            ("禁止路径", _join(_sequence(task.get("forbidden_paths")))),
            ("目标改动", _join(_sequence(task.get("expected_changed_files")))),
            ("验证步骤", _join(_sequence(task.get("verifier_step_names")))),
        )
    )
    readiness_body = "".join(
        [
            _facts(
                (
                    ("难度", str(readiness.get("difficulty") or "n/a")),
                    ("分层", str(readiness.get("tier") or "n/a")),
                    ("Harness 信号", _join(_sequence(readiness.get("declared_harness_signals")))),
                    ("标签", _join(_sequence(readiness.get("tags")))),
                )
            ),
            '<h4>推荐理由</h4>',
            _list_block(tuple(localize_harness_message(item) for item in _sequence(readiness.get("recommendation_reasons"))), empty_text="当前没有推荐理由。"),
            '<h4>风险提示</h4>',
            _list_block(risks, empty_text="当前没有风险提示。"),
        ]
    )

    entry_body = _card_grid(
        (
            "".join(
                [
                    '<article class="card">',
                    '<div class="card-top">',
                    '<span class="pill">用户任务</span>',
                    '<span class="muted">填写或查看当前任务</span>',
                    '</div>',
                    '<h3>任务输入</h3>',
                    '<textarea class="task-input" rows="6" placeholder="任务会显示在这里...">',
                    escape(task_text),
                    '</textarea>',
                    f'<p class="muted">来源：{escape(source_path)}</p>',
                    '</article>',
                ]
            ),
            "".join(
                [
                    '<article class="card">',
                    '<div class="card-top">',
                    '<span class="pill">执行入口</span>',
                    f'<span class="muted">推荐分：{escape(recommendation_score)}</span>',
                    '</div>',
                    '<h3>常用命令</h3>',
                    _card_grid(command_cards) if command_cards else _empty("当前没有可用命令模板。"),
                    '</article>',
                ]
            ),
        )
    )

    body = "".join(
        [
            '<div class="page simple-page">',
            '<section class="hero">',
            '<p class="eyebrow">任务入口预览</p>',
            f'<h1>{escape(title)}</h1>',
            f'<p>{escape(description)}</p>',
            '<div class="badge-row">',
            f'<span class="badge">任务：{escape(task_id)}</span>',
            f'<span class="badge">仓库来源：{escape(repo_source_kind)}</span>',
            f'<span class="badge">推荐分：{escape(recommendation_score)}</span>',
            '</div>',
            '</section>',
            _panel(
                '用户任务',
                entry_body,
                '先确认用户到底要做什么，再决定是否继续 scaffold 或评测。',
                wide=True,
            ),
            _panel(
                '三档交付',
                _card_grid(profile_cards) if profile_cards else _empty('当前没有可展示的交付矩阵。'),
                '直接看 bare / basic / full 三种交付范围。',
                wide=True,
            ),
            _panel(
                '交付差异',
                _card_grid(delta_cards) if delta_cards else _empty('当前没有交付差异。'),
                '把档位差异集中展示，避免分散到整页各处。',
                wide=False,
            ),
            _details_panel(
                '更多信息',
                "".join(
                    [
                        _panel('任务约束', task_contract, '编辑范围、目标改动和验证步骤都收在这里。', wide=False),
                        _panel('推荐与风险', readiness_body, '查看推荐理由与风险提示。', wide=False),
                    ]
                ),
                '查看任务契约、推荐理由和风险提示。',
                summary='展开更多',
                wide=True,
            ),
            '</div>',
        ]
    )
    return "".join(
        [
            '<!DOCTYPE html>',
            '<html lang="zh-CN">',
            '<head>',
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f'<title>{escape(task_id)} 入口预览</title>',
            '<style>:root{--bg:#f5efe5;--ink:#14212b;--muted:#5e6a73;--accent:#0f766e;--warm:#c46c2d;--panel:rgba(255,255,255,.84);--border:rgba(20,33,43,.12);--shadow:0 18px 50px rgba(20,33,43,.12);}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at top left, rgba(196,108,45,.18), transparent 32%),radial-gradient(circle at top right, rgba(15,118,110,.18), transparent 34%),linear-gradient(180deg,#f8f3ea 0%,#eef2ef 100%);font-family:"Aptos","Trebuchet MS",sans-serif}.page{max-width:1080px;margin:0 auto;padding:28px 20px 40px}.hero,.panel,.card{background:var(--panel);border:1px solid var(--border);border-radius:24px;box-shadow:var(--shadow)}.hero{padding:32px;background:linear-gradient(135deg, rgba(20,33,43,.98), rgba(15,118,110,.93));color:#fbfaf7}.hero p{max-width:820px}.eyebrow{letter-spacing:.18em;text-transform:uppercase;font-size:.75rem;color:rgba(251,250,247,.72)}h1,h2,h3,h4{font-family:Georgia,"Times New Roman",serif;margin:0}.hero h1{font-size:clamp(2rem,4vw,3.3rem);line-height:1.02;margin:8px 0 10px}.badge-row{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:6px 12px;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;background:rgba(255,255,255,.14);color:#fbfaf7}.panel{padding:18px;margin-top:18px}.panel.wide,.details-panel.wide{grid-column:span 2}.panel-head{display:flex;flex-direction:column;gap:6px;margin-bottom:14px}.panel-body{display:flex;flex-direction:column;gap:14px}.details-panel{padding:0;margin-top:18px}.details-panel details{padding:18px}.details-summary{list-style:none;display:flex;align-items:flex-start;justify-content:space-between;gap:16px;cursor:pointer}.details-summary::-webkit-details-marker{display:none}.details-summary-copy{display:flex;flex-direction:column;gap:6px}.details-hint{display:inline-flex;align-items:center;justify-content:center;padding:8px 12px;border-radius:999px;border:1px solid rgba(20,33,43,.12);color:var(--muted);white-space:nowrap}.details-body{padding-top:16px}.details-body .panel:first-child{margin-top:0}.facts{display:grid;grid-template-columns:minmax(0,1fr);gap:0}.facts li{display:grid;grid-template-columns:150px minmax(0,1fr);gap:12px;padding:10px 0;border-bottom:1px solid rgba(20,33,43,.08)}.facts li:last-child{border-bottom:none}.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.card{padding:16px;border-radius:20px;border:1px solid rgba(20,33,43,.1);background:rgba(255,255,255,.72)}.card-top{display:flex;flex-wrap:wrap;gap:10px}.stack-list{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:8px}.empty{border:1px dashed rgba(20,33,43,.18);border-radius:18px;padding:18px;color:var(--muted);background:rgba(255,255,255,.5)}pre{margin:0;white-space:pre-wrap;word-break:break-word;background:rgba(20,33,43,.06);border-radius:14px;padding:12px;font-family:"Cascadia Mono",Consolas,monospace}.pill{display:inline-flex;align-items:center;border-radius:999px;padding:5px 10px;font-size:.75rem;background:rgba(15,118,110,.12);color:var(--accent)}.task-input{width:100%;min-height:144px;resize:vertical;border:1px solid rgba(20,33,43,.12);border-radius:18px;padding:16px;background:rgba(255,255,255,.72);color:var(--ink);font:inherit;line-height:1.6}.simple-page{max-width:1080px}@media(max-width:900px){.panel.wide,.details-panel.wide{grid-column:auto}}@media(max-width:640px){.page{padding:16px 12px 28px}.hero{padding:24px}.facts li{grid-template-columns:1fr}.details-summary{position:static;flex-direction:column}.card-grid{grid-template-columns:1fr}}</style>',
            '</head>',
            f'<body>{body}</body></html>',
        ]
    )


def _panel(title: str, body: str, subtitle: str, *, wide: bool, section_id: str = "") -> str:
    class_name = "panel wide" if wide else "panel"
    id_attr = f' id="{escape(section_id)}"' if section_id else ""
    return "".join(
        [
            f'<section{id_attr} class="{class_name}">',
            '<div class="panel-head">',
            f'<h2>{escape(title)}</h2>',
            f'<p class="subtitle">{escape(subtitle)}</p>',
            '</div>',
            f'<div class="panel-body">{body}</div>',
            '</section>',
        ]
    )


def _details_panel(
    title: str,
    body: str,
    subtitle: str,
    *,
    summary: str,
    wide: bool,
    section_id: str = "",
) -> str:
    class_name = "details-panel wide" if wide else "details-panel"
    id_attr = f' id="{escape(section_id)}"' if section_id else ""
    return "".join(
        [
            f'<section{id_attr} class="{class_name}">',
            '<details>',
            '<summary class="details-summary">',
            '<div class="details-summary-copy">',
            f'<h2>{escape(title)}</h2>',
            f'<p class="subtitle">{escape(subtitle)}</p>',
            '</div>',
            f'<span class="details-hint">{escape(summary)}</span>',
            '</summary>',
            f'<div class="panel-body details-body">{body}</div>',
            '</details>',
            '</section>',
        ]
    )


def _profile_card(name: str, payload: Mapping[str, Any]) -> str:
    notes = tuple(localize_harness_message(item) for item in _sequence(payload.get("notes")))
    context_files = _sequence(payload.get("context_files"))
    input_names = _sequence(payload.get("included_input_names"))
    verifier_steps = _sequence(payload.get("included_verifier_steps"))
    badges = "".join(f'<span class="pill">{escape(item)}</span>' for item in input_names)
    badges += "".join(f'<span class="pill">验证：{escape(item)}</span>' for item in verifier_steps)
    return "".join(
        [
            '<article class="card">',
            f'<h3>{escape(_profile_label(name))}</h3>',
            f'<p class="muted">上下文文件：{escape(str(payload.get("context_file_count", 0)))} / {escape(str(payload.get("max_context_files", 0)))} </p>',
            f'<p class="muted">目录条目：{escape(str(payload.get("tree_file_count", "n/a")))}</p>',
            f'<div class="card-top">{badges}</div>' if badges else '',
            '<h4 style="margin:14px 0 8px">可见上下文</h4>',
            _list_block(context_files, empty_text="当前档位没有额外上下文文件。"),
            '<h4 style="margin:14px 0 8px">补充说明</h4>',
            _list_block(notes, empty_text="当前没有补充说明。"),
            '</article>',
        ]
    )


def _delta_card(item: Mapping[str, Any]) -> str:
    lines = tuple(localize_harness_message(item) for item in _sequence(item.get("summary_lines")))
    from_profile = _profile_label(str(item.get("from_profile") or "?"))
    to_profile = _profile_label(str(item.get("to_profile") or "?"))
    return "".join(
        [
            '<article class="card">',
            f'<h3>{escape(from_profile)} → {escape(to_profile)}</h3>',
            _list_block(lines, empty_text="当前没有交付差异。"),
            '</article>',
        ]
    )


def _command_card(name: str, command: Any) -> str:
    return "".join(
        [
            '<article class="card">',
            f'<h3>{escape(_command_label(name))}</h3>',
            f'<pre>{escape(str(command))}</pre>',
            '</article>',
        ]
    )


def _facts(items: Sequence[tuple[str, str]]) -> str:
    rows = "".join(
        f'<li><strong>{escape(label)}</strong><span>{escape(value)}</span></li>'
        for label, value in items
        if value and value != "无"
    )
    return f'<ul class="facts">{rows}</ul>' if rows else _empty("当前没有可展示字段。")


def _list_block(items: Sequence[str], *, empty_text: str) -> str:
    if not items:
        return _empty(empty_text)
    return '<ul class="stack-list">' + ''.join(f'<li>{escape(item)}</li>' for item in items) + '</ul>'


def _card_grid(cards: Sequence[str] | str) -> str:
    rendered = cards if isinstance(cards, str) else ''.join(cards)
    return f'<div class="card-grid">{rendered}</div>' if rendered else _empty("当前没有可展示内容。")


def _empty(text: str) -> str:
    return f'<div class="empty">{escape(text)}</div>'


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(str(item) for item in value if str(item))


def _sequence_of_mappings(value: Any) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _join(values: Sequence[str]) -> str:
    return ', '.join(values) if values else '无'


def _profile_label(name: str) -> str:
    labels = {
        'bare': 'Bare 直出',
        'basic': 'Basic 仓库上下文',
        'full': 'Full 完整 Harness',
    }
    return labels.get(name, name)


def _command_label(name: str) -> str:
    labels = {
        'preview_intake': '预览入口',
        'scaffold_task_spec': '生成 Task Spec',
        'run_intake_eval': '运行 Intake Eval',
    }
    return labels.get(name, str(name).replace('_', ' ').title())