from __future__ import annotations

from collections import Counter
import json
import re
from typing import TYPE_CHECKING

from repo_harness_lab.domain.eval_models import EvalReport
from repo_harness_lab.domain.run_models import RunSummary
from repo_harness_lab.reporting.failure_summary import build_failure_summary
from repo_harness_lab.shared.failure_hints import pick_failure_hint

if TYPE_CHECKING:
    from repo_harness_lab.storage.run_store import StoredRunRecord


_RUN_STATUS_LABELS = {
    "pending": "待开始",
    "running": "运行中",
    "succeeded": "成功",
    "failed": "失败",
    "cancelled": "已取消",
}

_VERIFIER_LABELS = {
    None: "未运行",
    "not_run": "未运行",
    "passed": "通过",
    "failed": "失败",
    "error": "错误",
    "skipped": "已跳过",
}

_STAGE_LABELS = {
    "preparation": "准备",
    "workspace": "工作区",
    "agent": "Agent",
    "verification": "验证",
    "finalization": "收尾",
    "evaluation": "评测",
}

_EVENT_TYPE_LABELS = {
    "run_started": "运行开始",
    "workspace_prepared": "工作区已就绪",
    "agent_invoked": "Agent 已调用",
    "model_requested": "模型请求已发出",
    "model_responded": "模型已响应",
    "command_executed": "命令已执行",
    "file_changed": "文件已改动",
    "verifier_started": "验证开始",
    "verifier_finished": "验证结束",
    "run_finished": "运行结束",
}

_ARTIFACT_LABELS = {
    "events": "事件日志",
    "patch": "补丁文件",
    "report": "Markdown 报告",
    "report_html": "HTML 报告",
    "summary": "摘要 JSON",
    "verifier_results": "验证结果 JSON",
}


class MarkdownReporter:
    def render_run(self, summary: RunSummary) -> str:
        lines = [
            f"# 运行报告 {summary.run_id}",
            "",
            "## 摘要",
            f"- 任务 ID：{summary.task_id}",
            f"- 运行状态：{_run_status_label(summary.status.value)}",
            f"- 运行耗时：{_format_duration(summary.duration_ms)}",
            f"- 验证结果：{_verifier_label(summary.verifier_outcome)}",
        ]
        if summary.changed_files:
            lines.extend(["", "## 改动文件"])
            lines.extend(f"- {path}" for path in summary.changed_files)
        if summary.notes:
            lines.extend(["", "## 运行备注"])
            lines.extend(f"- {note}" for note in summary.notes)
        if summary.artifact_index:
            lines.extend(["", "## 运行产物"])
            lines.extend(
                f"- {_artifact_label(artifact.name)}：{artifact.path}"
                for artifact in summary.artifact_index
            )
        return "\n".join(lines)

    def render_run_record(self, record: StoredRunRecord) -> str:
        lines = [self.render_run(record.summary)]
        failure_summary = build_failure_summary(record)

        if failure_summary:
            lines.extend(["", "## 失败摘要"])
            lines.extend(f"- {_localize_failure_item(item)}" for item in failure_summary)

        if record.verifier_result is not None:
            lines.extend(
                [
                    "",
                    "## 验证结果",
                    f"- 验证器：{record.verifier_result.verifier_name}",
                    f"- 状态：{_verifier_label(record.verifier_result.status.value)}",
                ]
            )
            if record.verifier_result.errors:
                lines.extend(f"- 错误：{_localize_failure_item(error)}" for error in record.verifier_result.errors)
            if record.verifier_result.evidence:
                lines.extend(["", "## 验证证据"])
                lines.extend(f"- {_localize_failure_item(item.summary)}" for item in record.verifier_result.evidence)

        if record.patch_diff:
            lines.extend(["", "## 补丁预览", "```diff"])
            lines.extend(_patch_preview_lines(record.patch_diff))
            lines.append("```")

        if record.events:
            counts = Counter(event.event_type.value for event in record.events)
            lines.extend(["", "## 事件统计", f"- 事件总数：{len(record.events)}"])
            lines.extend(
                f"- {_event_type_label(name)}：{count}"
                for name, count in sorted(counts.items())
            )
            lines.extend(["", "## 最近事件"])
            lines.extend(
                f"- {event.timestamp.isoformat()} · {_stage_label(event.stage.value)} · {_event_type_label(event.event_type.value)}"
                for event in record.events[-5:]
            )

        return "\n".join(lines)

    def render_eval(self, report: EvalReport) -> str:
        lines = [
            f"# 评测报告 {report.suite_id}",
            "",
        ]
        if report.aggregate_metrics:
            lines.extend(["## 指标"])
            lines.extend(f"- {metric.name}: {metric.value}" for metric in report.aggregate_metrics)

        if report.case_results:
            lines.extend(["", "## 用例"])
            for case_result in report.case_results:
                lines.extend(
                    [
                        f"### {case_result.case_id}",
                        f"- 摘要：{json.dumps(case_result.summary, ensure_ascii=False, sort_keys=True)}",
                    ]
                )
                for trial in case_result.trials:
                    summary = trial.run_summary
                    if summary is None:
                        lines.append(f"- {trial.trial_id}：暂无摘要")
                        continue
                    label = trial.notes[0] if trial.notes else "<unlabeled>"
                    failure_hint = pick_failure_hint(summary)
                    failure_suffix = f"，失败提示={failure_hint}" if failure_hint else ""
                    lines.append(
                        f"- {trial.trial_id}：标签={label}，run_id={summary.run_id}，状态={_run_status_label(summary.status.value)}，验证={_verifier_label(summary.verifier_outcome)}{failure_suffix}"
                    )

        if report.comparison_views:
            lines.extend(["", "## 对比视图"])
            for view in report.comparison_views:
                lines.append(f"### {view.name}")
                for key, value in sorted(view.items.items()):
                    lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
        return "\n".join(lines)



def _patch_preview_lines(patch_diff: str, max_lines: int = 80) -> list[str]:
    lines = patch_diff.splitlines()
    if len(lines) <= max_lines:
        return lines or ["# 空补丁"]
    preview = lines[:max_lines]
    preview.append(f"# ... 另有 {len(lines) - max_lines} 行未展开")
    return preview


def _run_status_label(value: str | None) -> str:
    return _RUN_STATUS_LABELS.get(value, str(value or "未知"))


def _verifier_label(value: str | None) -> str:
    return _VERIFIER_LABELS.get(value, str(value or "未知"))


def _stage_label(value: str | None) -> str:
    return _STAGE_LABELS.get(value, str(value or "未知阶段"))


def _event_type_label(value: str | None) -> str:
    return _EVENT_TYPE_LABELS.get(value, str(value or "未知事件"))


def _artifact_label(value: str | None) -> str:
    return _ARTIFACT_LABELS.get(value, str(value or "未知产物"))


def _format_duration(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "未知"
    if duration_ms < 1000:
        return f"{duration_ms} 毫秒"
    return f"{duration_ms / 1000:.2f} 秒"


def _localize_failure_item(text: str) -> str:
    normalized = " ".join(str(text).split())
    exact_replacements = {
        "The run stopped before deterministic verification produced a result.": "运行在确定性验证产出结果前已结束。",
        "The run did not leave any file changes.": "本次运行没有留下文件改动。",
    }
    exact = exact_replacements.get(normalized)
    if exact is not None:
        return exact

    prefixed_patterns: tuple[tuple[str, str], ...] = (
        (r"Direct error: (.+)", "直接错误："),
        (r"Failed check: (.+)", "失败检查："),
        (r"Command output: (.+)", "命令输出："),
        (r"Run note: (.+)", "运行备注："),
    )
    for pattern, prefix in prefixed_patterns:
        matched = re.fullmatch(pattern, normalized)
        if matched is not None:
            return prefix + _localize_failure_item(matched.group(1))

    patterns: tuple[tuple[str, str], ...] = (
        (r"The verifier `(.+)` did not pass\.", r"验证器 `\1` 未通过。"),
        (r"The verifier `(.+)` hit an internal error\.", r"验证器 `\1` 发生内部错误。"),
        (r"The verifier `(.+)` was skipped, so there is no proof of success\.", r"验证器 `\1` 被跳过，目前没有成功证据。"),
        (r"Command exited with code (\d+): (.+)", r"命令退出码 \1：\2"),
        (r"(.+): command exited with code (\d+)", r"\1：命令退出码 \2"),
        (r"(.+): failed", r"\1：失败"),
        (r"(.+): missing", r"\1：缺失"),
    )
    for pattern, replacement in patterns:
        if re.fullmatch(pattern, normalized) is not None:
            return re.sub(pattern, replacement, normalized)
    return normalized
