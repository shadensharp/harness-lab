from __future__ import annotations

from repo_harness_lab.domain.failure_analysis_models import FailureAnalysisReport


def render_failure_analysis_markdown(report: FailureAnalysisReport) -> str:
    lines = [
        f"# 失败分析 {report.source_report_id}",
        "",
        "## 概览",
        f"- 评测类型：{report.benchmark_kind}",
        f"- 数据集：{report.dataset_name}",
        f"- 失败任务数：{report.total_failed_instances}",
    ]
    if report.notes:
        lines.extend(["", "## 说明"])
        lines.extend(f"- {item}" for item in report.notes)
    if report.label_counts:
        lines.extend(["", "## 主标签统计"])
        lines.extend(f"- {label}：{count}" for label, count in sorted(report.label_counts.items()))
    if report.probable_cause_counts:
        lines.extend(["", "## 最可能原因统计"])
        lines.extend(f"- {label}：{count}" for label, count in sorted(report.probable_cause_counts.items()))
    for profile in report.profile_reports:
        lines.extend(["", f"## 档位 {profile.harness_profile}", f"- 失败任务数：{profile.failed_instances}"])
        for item in profile.items:
            evidence = "；".join(item.key_evidence) if item.key_evidence else "n/a"
            lines.extend(
                [
                    f"### {item.instance_id}",
                    f"- 主标签：{item.main_label}",
                    f"- 所属阶段：{item.stage}",
                    f"- 关键证据：{evidence}",
                    f"- 最可能原因：{item.probable_cause}",
                    f"- 原因置信度：{item.cause_confidence}",
                ]
            )
    return "\n".join(lines)
