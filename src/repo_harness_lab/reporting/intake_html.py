from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from repo_harness_lab.reporting.text_localization import localize_harness_message


def render_task_intake_preview(preview: Mapping[str, Any] | object) -> str:
    payload = dict(preview) if isinstance(preview, Mapping) else {}
    task = _mapping(payload.get("task_spec_preview"))
    shared = _mapping(payload.get("shared_task_information"))
    delivery = _mapping(payload.get("current_delivery"))
    readiness = _mapping(payload.get("uplift_readiness"))
    commands = _mapping(payload.get("suggested_commands"))
    risks = tuple(localize_harness_message(item) for item in _sequence(payload.get("risk_warnings")))
    source_path = str(payload.get("source_path") or "n/a")
    task_id = str(task.get("task_id") or "task-intake-preview")
    title = str(task.get("title") or task_id)
    description = str(task.get("description") or "这里展示业务任务如何收口成当前 harness 运行包。")
    repo_source_kind = str(task.get("repo_source_kind") or "n/a")
    recommendation_score = str(readiness.get("recommendation_score") or "n/a")
    task_text = title if not description else f"{title}\n\n{description}"

    command_cards = "".join(_command_card(name, command) for name, command in commands.items())
    package_items = tuple(localize_harness_message(item) for item in _sequence(delivery.get("additional_delivery_items")))
    package_notes = tuple(localize_harness_message(item) for item in _sequence(delivery.get("notes")))
    package_badges = tuple(str(item) for item in delivery.get("included_input_names", ()) if str(item))
    verifier_badges = tuple(str(item) for item in delivery.get("included_verifier_steps", ()) if str(item))

    task_contract = _facts(
        (
            ("任务 ID", task_id),
            ("任务类型", str(task.get("task_type") or "n/a")),
            ("可改范围", _join(_sequence(task.get("editable_paths")))),
            ("禁改范围", _join(_sequence(task.get("forbidden_paths")))),
            ("目标改动", _join(_sequence(task.get("expected_changed_files")))),
            ("验收步骤", _join(_sequence(task.get("verifier_step_names")))),
            ("上下文提示", _join(_sequence(task.get("context_paths")))),
        )
    )
    shared_body = "".join(
        [
            _facts(
                (
                    ("共享区块", _join(_sequence(shared.get("shared_prompt_sections")))),
                    ("响应契约", str(shared.get("response_contract") or "n/a")),
                )
            ),
            "<h4>共享事实</h4>",
            _list_block(
                tuple(localize_harness_message(item) for item in _sequence(shared.get("shared_prompt_items"))),
                empty_text="当前没有共享事实。",
            ),
        ]
    )
    readiness_body = "".join(
        [
            _facts(
                (
                    ("难度", str(readiness.get("difficulty") or "n/a")),
                    ("层级", str(readiness.get("tier") or "n/a")),
                    ("Harness 信号", _join(_sequence(readiness.get("declared_harness_signals")))),
                    ("标签", _join(_sequence(readiness.get("tags")))),
                )
            ),
            "<h4>推荐理由</h4>",
            _list_block(
                tuple(localize_harness_message(item) for item in _sequence(readiness.get("recommendation_reasons"))),
                empty_text="当前没有推荐理由。",
            ),
            "<h4>风险提示</h4>",
            _list_block(risks, empty_text="当前没有额外风险提示。"),
        ]
    )
    delivery_body = "".join(
        [
            _facts(
                (
                    ("模式", str(delivery.get("profile") or "current")),
                    ("仓库树条目", str(delivery.get("tree_file_count", "n/a"))),
                    ("上下文文件", str(delivery.get("context_file_count", 0))),
                    ("上下文上限", str(delivery.get("max_context_files", 0))),
                )
            ),
            _badge_row(package_badges, prefix="任务输入"),
            _badge_row(verifier_badges, prefix="验收步骤"),
            "<h4>当前会附带什么</h4>",
            _list_block(package_items, empty_text="当前没有额外交付说明。"),
            "<h4>运行备注</h4>",
            _list_block(package_notes, empty_text="当前没有额外运行备注。"),
        ]
    )

    entry_body = _card_grid(
        (
            "".join(
                [
                    '<article class="card">',
                    '<div class="card-top">',
                    '<span class="pill">用户任务</span>',
                    '<span class="muted">填写或核对当前任务</span>',
                    "</div>",
                    "<h3>任务输入</h3>",
                    '<textarea class="task-input" rows="6" placeholder="任务会显示在这里...">',
                    escape(task_text),
                    "</textarea>",
                    f'<p class="muted">来源：{escape(source_path)}</p>',
                    "</article>",
                ]
            ),
            "".join(
                [
                    '<article class="card">',
                    '<div class="card-top">',
                    '<span class="pill">执行入口</span>',
                    f'<span class="muted">推荐分：{escape(recommendation_score)}</span>',
                    "</div>",
                    "<h3>常用命令</h3>",
                    _card_grid(command_cards) if command_cards else _empty("当前没有可用命令模板。"),
                    "</article>",
                ]
            ),
        )
    )

    body = "".join(
        [
            '<div class="page simple-page">',
            '<section class="hero">',
            '<p class="eyebrow">任务入口预览</p>',
            f"<h1>{escape(title)}</h1>",
            f"<p>{escape(description)}</p>",
            '<div class="badge-row">',
            f'<span class="badge">任务：{escape(task_id)}</span>',
            f'<span class="badge">仓库来源：{escape(repo_source_kind)}</span>',
            f'<span class="badge">推荐分：{escape(recommendation_score)}</span>',
            "</div>",
            "</section>",
            _panel(
                "用户任务",
                entry_body,
                "先确认业务目标，再决定是否继续 scaffold 或评测。",
                wide=True,
            ),
            _panel(
                "当前交付包",
                delivery_body,
                "这里展示当前主线实际会交给模型的仓库边界、上下文、任务输入和验收信息。",
                wide=True,
            ),
            _details_panel(
                "更多信息",
                "".join(
                    [
                        _panel("任务约束", task_contract, "编辑范围、目标改动和验收步骤都收在这里。", wide=False),
                        _panel("共享任务信息", shared_body, "这些事实在当前运行里保持固定。", wide=False),
                        _panel("推荐与风险", readiness_body, "查看推荐理由和风险提示。", wide=False),
                    ]
                ),
                "查看任务契约、共享事实和推荐理由。",
                summary="展开更多",
                wide=True,
            ),
            "</div>",
        ]
    )
    return "".join(
        [
            "<!DOCTYPE html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{escape(task_id)} 入口预览</title>",
            "<style>:root{--bg:#f5efe5;--ink:#14212b;--muted:#5e6a73;--accent:#0f766e;--warm:#c46c2d;--panel:rgba(255,255,255,.84);--border:rgba(20,33,43,.12);--shadow:0 18px 50px rgba(20,33,43,.12);}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at top left, rgba(196,108,45,.18), transparent 32%),radial-gradient(circle at top right, rgba(15,118,110,.18), transparent 34%),linear-gradient(180deg,#f8f3ea 0%,#eef2ef 100%);font-family:\"Aptos\",\"Trebuchet MS\",sans-serif}.page{max-width:1080px;margin:0 auto;padding:28px 20px 40px}.hero,.panel,.card{background:var(--panel);border:1px solid var(--border);border-radius:24px;box-shadow:var(--shadow)}.hero{padding:32px;background:linear-gradient(135deg, rgba(20,33,43,.98), rgba(15,118,110,.93));color:#fbfaf7}.hero p{max-width:820px}.eyebrow{letter-spacing:.18em;text-transform:uppercase;font-size:.75rem;color:rgba(251,250,247,.72)}h1,h2,h3,h4{font-family:Georgia,\"Times New Roman\",serif;margin:0}.hero h1{font-size:clamp(2rem,4vw,3.3rem);line-height:1.02;margin:8px 0 10px}.badge-row{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:6px 12px;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;background:rgba(255,255,255,.14);color:#fbfaf7}.panel{padding:18px;margin-top:18px}.panel.wide,.details-panel.wide{grid-column:span 2}.panel-head{display:flex;flex-direction:column;gap:6px;margin-bottom:14px}.panel-body{display:flex;flex-direction:column;gap:14px}.details-panel{padding:0;margin-top:18px}.details-panel details{padding:18px}.details-summary{list-style:none;display:flex;align-items:flex-start;justify-content:space-between;gap:16px;cursor:pointer}.details-summary::-webkit-details-marker{display:none}.details-summary-copy{display:flex;flex-direction:column;gap:6px}.details-hint{display:inline-flex;align-items:center;justify-content:center;padding:8px 12px;border-radius:999px;border:1px solid rgba(20,33,43,.12);color:var(--muted);white-space:nowrap}.details-body{padding-top:16px}.details-body .panel:first-child{margin-top:0}.facts{display:grid;grid-template-columns:minmax(0,1fr);gap:0}.facts li{display:grid;grid-template-columns:150px minmax(0,1fr);gap:12px;padding:10px 0;border-bottom:1px solid rgba(20,33,43,.08)}.facts li:last-child{border-bottom:none}.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.card{padding:16px;border-radius:20px;border:1px solid rgba(20,33,43,.1);background:rgba(255,255,255,.72)}.card-top{display:flex;flex-wrap:wrap;gap:10px}.stack-list{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:8px}.empty{border:1px dashed rgba(20,33,43,.18);border-radius:18px;padding:18px;color:var(--muted);background:rgba(255,255,255,.5)}pre{margin:0;white-space:pre-wrap;word-break:break-word;background:rgba(20,33,43,.06);border-radius:14px;padding:12px;font-family:\"Cascadia Mono\",Consolas,monospace}.pill{display:inline-flex;align-items:center;border-radius:999px;padding:5px 10px;font-size:.75rem;background:rgba(15,118,110,.12);color:var(--accent)}.task-input{width:100%;min-height:144px;resize:vertical;border:1px solid rgba(20,33,43,.12);border-radius:18px;padding:16px;background:rgba(255,255,255,.72);color:var(--ink);font:inherit;line-height:1.6}.soft-badges{display:flex;flex-wrap:wrap;gap:8px}.soft-badges .pill{background:rgba(196,108,45,.12);color:var(--warm)}.simple-page{max-width:1080px}@media(max-width:900px){.panel.wide,.details-panel.wide{grid-column:auto}}@media(max-width:640px){.page{padding:16px 12px 28px}.hero{padding:24px}.facts li{grid-template-columns:1fr}.details-summary{position:static;flex-direction:column}.card-grid{grid-template-columns:1fr}}</style>",
            "</head>",
            f"<body>{body}</body></html>",
        ]
    )


def _panel(title: str, body: str, subtitle: str, *, wide: bool, section_id: str = "") -> str:
    class_name = "panel wide" if wide else "panel"
    id_attr = f' id="{escape(section_id)}"' if section_id else ""
    return "".join(
        [
            f'<section{id_attr} class="{class_name}">',
            '<div class="panel-head">',
            f"<h2>{escape(title)}</h2>",
            f'<p class="subtitle">{escape(subtitle)}</p>',
            "</div>",
            f'<div class="panel-body">{body}</div>',
            "</section>",
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
            "<details>",
            '<summary class="details-summary">',
            '<div class="details-summary-copy">',
            f"<h2>{escape(title)}</h2>",
            f'<p class="subtitle">{escape(subtitle)}</p>',
            "</div>",
            f'<span class="details-hint">{escape(summary)}</span>',
            "</summary>",
            f'<div class="panel-body details-body">{body}</div>',
            "</details>",
            "</section>",
        ]
    )


def _command_card(name: str, command: Any) -> str:
    return "".join(
        [
            '<article class="card">',
            f"<h3>{escape(_command_label(name))}</h3>",
            f"<pre>{escape(str(command))}</pre>",
            "</article>",
        ]
    )


def _facts(items: Sequence[tuple[str, str]]) -> str:
    rows = "".join(
        f"<li><strong>{escape(label)}</strong><span>{escape(value)}</span></li>"
        for label, value in items
        if value and value != "n/a"
    )
    return f'<ul class="facts">{rows}</ul>' if rows else _empty("当前没有可展示字段。")


def _list_block(items: Sequence[str], *, empty_text: str) -> str:
    if not items:
        return _empty(empty_text)
    return '<ul class="stack-list">' + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def _card_grid(cards: Sequence[str] | str) -> str:
    rendered = cards if isinstance(cards, str) else "".join(cards)
    return f'<div class="card-grid">{rendered}</div>' if rendered else _empty("当前没有可展示内容。")


def _badge_row(items: Sequence[str], *, prefix: str) -> str:
    if not items:
        return ""
    rendered = "".join(f'<span class="pill">{escape(prefix)}：{escape(item)}</span>' for item in items)
    return f'<div class="soft-badges">{rendered}</div>'


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


def _join(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "n/a"


def _command_label(name: str) -> str:
    labels = {
        "preview_intake": "预览入口",
        "scaffold_task_spec": "生成 Task Spec",
        "run_intake_eval": "运行 Intake Eval",
    }
    return labels.get(name, str(name).replace("_", " ").title())
