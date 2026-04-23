from __future__ import annotations

from html import escape
from typing import Iterable

from repo_harness_lab.domain.official_benchmark_models import OfficialBenchmarkEvaluationReport


def render_official_benchmark_markdown(report: OfficialBenchmarkEvaluationReport) -> str:
    lines = [
        f"# 官方评测报告 {report.source_report_id}",
        "",
        "## 摘要",
        f"- 评测类型：{report.benchmark_kind}",
        f"- 数据集：{report.dataset_name}",
        f"- split：{report.split}",
        f"- 来源评测：{report.source_report_id}",
        f"- 官方 runner：{report.official_runner}",
    ]
    if report.notes:
        lines.extend(["", "## 备注"])
        lines.extend(f"- {item}" for item in report.notes)

    lines.extend(["", "## 各档位结果"])
    for item in report.profile_reports:
        lines.extend(
            [
                f"### {item.harness_profile}",
                f"- model_name_or_path：{item.model_name_or_path}",
                f"- submitted：{item.submitted_instances}",
                f"- completed：{item.completed_instances}",
                f"- resolved：{item.resolved_instances}",
                f"- unresolved：{item.unresolved_instances}",
                f"- error：{item.error_instances}",
                f"- empty_patch：{item.empty_patch_instances}",
                f"- incomplete：{item.incomplete_instances}",
                f"- resolution_rate：{_format_ratio(item.resolution_rate)}",
                f"- predictions_path：{item.predictions_path}",
                f"- results_path：{item.results_path or 'n/a'}",
                f"- instance_results_path：{item.instance_results_path or 'n/a'}",
                f"- stdout_path：{item.stdout_path or 'n/a'}",
                f"- stderr_path：{item.stderr_path or 'n/a'}",
            ]
        )
    return "\n".join(lines)


def render_official_benchmark_html(report: OfficialBenchmarkEvaluationReport) -> str:
    cards = "".join(_profile_card(item) for item in report.profile_reports)
    notes = _list_block(report.notes) if report.notes else '<div class="empty">当前没有额外备注。</div>'
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>官方评测报告 {escape(report.source_report_id)}</title>"
        "<style>"
        "body{margin:0;background:#f6f1e7;color:#17212b;font-family:'Aptos','Trebuchet MS',sans-serif}"
        ".page{max-width:1180px;margin:0 auto;padding:28px 18px 40px}"
        ".hero{background:linear-gradient(135deg,#13212b,#0f766e);color:#fbfaf7;border-radius:24px;padding:28px}"
        ".hero h1{margin:8px 0 0;font-size:2.4rem;font-family:Georgia,'Times New Roman',serif}"
        ".hero p{max-width:780px;color:rgba(251,250,247,.82)}"
        ".eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:.76rem;color:rgba(251,250,247,.72)}"
        ".panel{background:rgba(255,255,255,.82);border:1px solid rgba(23,33,43,.12);border-radius:20px;padding:18px;box-shadow:0 16px 44px rgba(23,33,43,.08);margin-top:16px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-top:18px}"
        ".metric{display:grid;grid-template-columns:1fr auto;gap:10px;padding:8px 0;border-bottom:1px solid rgba(23,33,43,.08)}"
        ".metric:last-child{border-bottom:0}.muted{color:#5f6a73}.empty{padding:14px;border:1px dashed rgba(23,33,43,.16);border-radius:14px;color:#5f6a73}"
        "ul{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:8px}"
        "code,pre{font-family:'Cascadia Mono',Consolas,monospace}"
        "</style></head><body><div class=\"page\">"
        f"<header class=\"hero\"><div class=\"eyebrow\">官方统一判分</div><h1>{escape(report.source_report_id)}</h1>"
        f"<p>数据集 {escape(report.dataset_name)} · split {escape(report.split)} · 来源评测 {escape(report.source_report_id)}</p></header>"
        f"<section class=\"panel\"><h2>说明</h2><div class=\"metric\"><span class=\"muted\">评测类型</span><code>{escape(report.benchmark_kind)}</code></div>"
        f"<div class=\"metric\"><span class=\"muted\">官方 runner</span><code>{escape(report.official_runner)}</code></div>{notes}</section>"
        f"<section class=\"grid\">{cards}</section></div></body></html>"
    )


def _profile_card(item) -> str:
    rows = [
        ("model_name_or_path", item.model_name_or_path),
        ("submitted", str(item.submitted_instances)),
        ("completed", str(item.completed_instances)),
        ("resolved", str(item.resolved_instances)),
        ("unresolved", str(item.unresolved_instances)),
        ("error", str(item.error_instances)),
        ("empty_patch", str(item.empty_patch_instances)),
        ("incomplete", str(item.incomplete_instances)),
        ("resolution_rate", _format_ratio(item.resolution_rate)),
        ("predictions", item.predictions_path),
        ("results", item.results_path or "n/a"),
    ]
    metrics = "".join(
        f"<div class=\"metric\"><span class=\"muted\">{escape(label)}</span><code>{escape(value)}</code></div>"
        for label, value in rows
    )
    return f"<article class=\"panel\"><h2>{escape(item.harness_profile)}</h2>{metrics}</article>"


def _list_block(items: Iterable[str]) -> str:
    rendered = "".join(f"<li>{escape(item)}</li>" for item in items if item)
    return f"<ul>{rendered}</ul>" if rendered else '<div class="empty">当前没有可展示内容。</div>'


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"
