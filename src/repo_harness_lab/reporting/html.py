from __future__ import annotations

from collections import Counter
from html import escape
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Sequence

from repo_harness_lab.domain.eval_models import EvalReport
from repo_harness_lab.domain.run_models import RunSummary
from repo_harness_lab.reporting.failure_summary import build_failure_summary
from repo_harness_lab.reporting.run_evidence import (
    build_harness_delta_items,
    build_harness_extra_items,
    build_harness_input_items,
    build_harness_shared_items,
    build_model_delta_items,
    build_model_response_items,
)
from repo_harness_lab.reporting.text_localization import localize_harness_message
from repo_harness_lab.shared.failure_hints import pick_failure_hint
from repo_harness_lab.shared.profile_comparisons import (
    COMPARISON_MODE_FAIR,
    COMPARISON_MODE_UPLIFT,
    ProfileRunComparison,
    comparison_map_by_target_profile,
    default_baseline_profile,
)
from repo_harness_lab.shared.portal_story import PORTAL_STORY_TITLES

if TYPE_CHECKING:
    from repo_harness_lab.storage.run_store import (
        ReportArtifactSummary,
        StoredEvalCase,
        StoredEvalReport,
        StoredRunComparison,
        StoredRunRecord,
    )


class HtmlReporter:
    def __init__(self, *, run_record_loader: Callable[[str], StoredRunRecord] | None = None) -> None:
        self._run_record_loader = run_record_loader

    def render_run_record(self, record: StoredRunRecord) -> str:
        summary = record.summary
        event_counts = Counter(event.event_type.value for event in record.events)
        body = "".join(
            [
                '<div class="page-shell">',
                self._hero(
                    eyebrow="运行报告",
                    title=summary.run_id,
                    subtitle=f"任务 {summary.task_id} · 状态 {self._status_label(summary.status.value)}",
                    badges=(self._status_label(summary.status.value), self._verifier_label(summary.verifier_outcome)),
                ),
                self._metric_grid(
                    (
                        ("状态", self._status_label(summary.status.value), "当前运行的最终状态"),
                        ("验证", self._verifier_label(summary.verifier_outcome), "确定性验证的结果"),
                        ("耗时", self._format_duration(summary.duration_ms), "从开始到结束的总时间"),
                        ("改动文件", str(len(summary.changed_files)), "本次运行写入过的文件数"),
                        ("事件数", str(len(record.events)), "记录下来的过程事件"),
                        ("产物", str(len(summary.artifact_index)), "报告、补丁和验证产物"),
                    )
                ),
                '<div class="layout-grid">',
                self._panel("任务输出", self._render_task_output_box(record), subtitle="先看模型最终交付了什么内容。", extra_class="panel-span-2"),
                self._panel("验证结果", self._render_verifier(record), subtitle="这里汇总通过、失败原因和命令检查结果。", extra_class="panel-span-2"),
                self._panel("改动文件", self._list_block(summary.changed_files, empty_text="当前没有检测到仓库改动。"), subtitle="本次运行实际写入过哪些文件。"),
                self._panel("运行产物", self._render_artifacts(summary), subtitle="保存下来的 HTML、Markdown、JSON 等产物。"),
                self._panel("补丁预览", self._render_patch_preview(record.patch_diff), subtitle="这里展示裁剪后的 patch diff。", extra_class="panel-span-2"),
                self._panel("流程时间线", self._timeline(record.events), subtitle="按时间顺序查看各阶段发生了什么。", extra_class="panel-span-2"),
                self._panel(
                    "事件分布",
                    self._kv_rows((self._event_type_label(name), str(count)) for name, count in sorted(event_counts.items())),
                    subtitle="每类事件出现了多少次。",
                ),
                self._panel("运行备注", self._list_block(self._failure_items(record, summary), empty_text="当前没有额外备注。"), subtitle="失败提示、运行备注和补充说明。"),
                '</div>',
                '</div>',
            ]
        )
        return self._document(title=f"运行报告 {summary.run_id}", body=body)

    def render_eval(self, report: EvalReport) -> str:
        model_label = self._eval_model_label(report.case_results)
        case_cards = "".join(self._render_eval_case(case.case_id, case.summary, case.trials) for case in report.case_results)
        metric_rows = self._kv_rows((metric.name, self._format_metric(metric.value, metric.unit)) for metric in report.aggregate_metrics)
        baseline_view = next((dict(view.items) for view in report.comparison_views if view.name == "report_baseline"), {})
        uses_profile_matrix = self._report_uses_profile_matrix(report.case_results)
        comparison_cards = "".join(
            self._panel(
                f"对比视图 · {view.name}",
                self._kv_rows((key, self._json(value)) for key, value in sorted(view.items.items())),
                subtitle="需要核查原始字段时再展开。",
            )
            for view in report.comparison_views
        )
        hero_badges = [f"模型：{model_label}", f"任务：{len(report.case_results)}"]
        if uses_profile_matrix:
            hero_badges.append("模式：multi-run")
        else:
            hero_badges.append("模式：current")
            if baseline_view.get("baseline_report_id"):
                hero_badges.append(f"基线：{baseline_view['baseline_report_id']}")
        explainer_title = "多运行说明" if uses_profile_matrix else "基线说明"
        explainer_body = (
            self._profile_explainer()
            if uses_profile_matrix
            else self._baseline_summary_block(baseline_view) if baseline_view else self._current_mode_explainer()
        )
        explainer_subtitle = (
            "控制变量固定，同一模型、同一任务、同一验收，只改变 harness 额外交给模型的内容。"
            if uses_profile_matrix
            else "主线只跑 current 单次配置；要比较时，再对照历史基线或自定义基线报告。"
        )
        body = "".join(
            [
                '<div class="page-shell simple-shell">',
                self._hero(
                    eyebrow="同模型 Harness 抬升" if uses_profile_matrix else "基线对比",
                    title=report.suite_id,
                    subtitle=(
                        "同一模型下直接对比当前运行和附加运行结果。"
                        if uses_profile_matrix
                        else "当前运行结果；如已指定基线，会在这里直接展示当前版本和基线版本的差异。"
                    ),
                    badges=tuple(hero_badges),
                ),
                self._panel(explainer_title, explainer_body, subtitle=explainer_subtitle, extra_class="panel-span-2"),
                self._panel("用户任务与结果", case_cards or self._empty_state("当前没有可展示的任务结果。"), subtitle="每个任务都直接展示任务、结果输出和验证结果。", extra_class="panel-span-2"),
                self._details_panel(
                    "更多证据",
                    self._panel("聚合指标", metric_rows, subtitle="当前套件的汇总指标。")
                    + self._panel("原始对比视图", comparison_cards or self._empty_state("当前没有额外对比视图。"), subtitle="需要看底层字段时再展开。", extra_class="panel-span-2"),
                    subtitle="保留原始指标和对比数据，但不占满首屏。",
                    summary="展开更多",
                    extra_class="panel-span-2",
                ),
                '</div>',
            ]
        )
        return self._document(title=f"评测结果 {report.suite_id}", body=body)

    def render_run_comparison(self, bundle: StoredRunComparison) -> str:
        comparison = bundle.comparison
        duration_delta = self._format_signed_duration(comparison.duration_ms_delta)
        event_delta = comparison.right_event_count - comparison.left_event_count
        body = "".join(
            [
                '<div class="page-shell">',
                self._hero(
                    eyebrow="运行对比",
                    title=f"{comparison.left_run_id} vs {comparison.right_run_id}",
                    subtitle="同一任务下，逐项比较两次运行到底差在哪里。",
                    badges=(
                        f"状态：{'有变化' if comparison.status_changed else '一致'}",
                        f"验证：{'有变化' if comparison.verifier_outcome_changed else '一致'}",
                    ),
                ),
                self._metric_grid(
                    (
                        ("状态差异", "有变化" if comparison.status_changed else "一致", "最终状态是否不同"),
                        ("验证差异", "有变化" if comparison.verifier_outcome_changed else "一致", "验证结果是否不同"),
                        ("耗时差异", duration_delta, "右侧相对左侧的耗时变化"),
                        ("事件差异", self._format_signed_number(event_delta), "过程事件数量的变化"),
                    )
                ),
                '<div class="layout-grid">',
                self._panel(bundle.left.summary.run_id, self._comparison_run_snapshot(bundle.left, side="left"), subtitle="左侧运行的关键事实。"),
                self._panel(bundle.right.summary.run_id, self._comparison_run_snapshot(bundle.right, side="right"), subtitle="右侧运行的关键事实。"),
                self._panel(
                    "总体差异",
                    self._kv_rows(
                        (
                            ("左侧状态", self._status_label(comparison.left_status)),
                            ("右侧状态", self._status_label(comparison.right_status)),
                            ("左侧验证", self._verifier_label(comparison.left_verifier_outcome)),
                            ("右侧验证", self._verifier_label(comparison.right_verifier_outcome)),
                            ("耗时变化", duration_delta),
                            ("事件变化", self._format_signed_number(event_delta)),
                        )
                    ),
                    subtitle="先用最少字段看清两边差在哪。",
                ),
                self._panel("Harness 差异", self._render_evidence_delta(bundle.left, bundle.right), subtitle="这里说明两边究竟多给了模型什么、模型又多返回了什么。", extra_class="panel-span-2"),
                self._panel("改动文件差异", self._dual_list(left_title=f"仅 {comparison.left_run_id} 改动", left_items=comparison.changed_files_only_in_left, right_title=f"仅 {comparison.right_run_id} 改动", right_items=comparison.changed_files_only_in_right, empty_text="两边改动文件没有额外差异。"), subtitle="哪些文件只出现在某一边。", extra_class="panel-span-2"),
                self._panel("备注差异", self._dual_list(left_title=f"仅 {comparison.left_run_id} 备注", left_items=comparison.notes_only_in_left, right_title=f"仅 {comparison.right_run_id} 备注", right_items=comparison.notes_only_in_right, empty_text="两边备注没有额外差异。"), subtitle="失败提示、运行备注等差异。", extra_class="panel-span-2"),
                self._panel("补丁预览", self._dual_patch_preview(left_title=bundle.left.summary.run_id, left_patch=bundle.left.patch_diff, right_title=bundle.right.summary.run_id, right_patch=bundle.right.patch_diff), subtitle="直接对照两边写出来的 patch。", extra_class="panel-span-2"),
                self._panel("流程时间线对比", self._dual_timeline(left_title=bundle.left.summary.run_id, left_events=bundle.left.events, right_title=bundle.right.summary.run_id, right_events=bundle.right.events), subtitle="查看各阶段的过程差异。", extra_class="panel-span-2"),
                '</div>',
                '</div>',
            ]
        )
        return self._document(title=f"运行对比 {comparison.left_run_id} vs {comparison.right_run_id}", body=body)

    def render_runs_dashboard(self, summaries: Sequence[RunSummary], *, title: str = "最近运行") -> str:
        cards = "".join(self._render_run_card(summary) for summary in summaries)
        body = "".join(
            [
                '<div class="page-shell">',
                self._hero(eyebrow="运行总览", title=title, subtitle="查看最近的 harness 运行记录和结果。", badges=(f"总运行：{len(summaries)}",)),
                self._metric_grid(
                    (
                        ("总运行数", str(len(summaries)), "当前页面展示的运行总数"),
                        ("成功", str(sum(1 for summary in summaries if summary.status.value == "succeeded")), "状态为 succeeded 的运行数"),
                        ("失败", str(sum(1 for summary in summaries if summary.status.value == "failed")), "状态为 failed 的运行数"),
                    )
                ),
                self._panel("运行卡片", f'<div class="card-grid">{cards}</div>' if cards else self._empty_state("当前没有可展示的运行记录。"), subtitle="每张卡片都可以直接打开运行报告。"),
                '</div>',
            ]
        )
        return self._document(title=title, body=body)

    def render_portal(
        self,
        *,
        runs: Sequence[RunSummary],
        report_artifacts: Sequence[ReportArtifactSummary],
        eval_reports: Sequence[StoredEvalReport] = (),
        title: str = "同模型 Harness 演示台",
        runtime_root: Path | None = None,
        runs_dir: Path | None = None,
        reports_dir: Path | None = None,
        live_portal_url: str | None = None,
        live_portal_command: str | None = None,
    ) -> str:
        dashboard_reports = [item for item in report_artifacts if item.category in {"dashboard", "uplift"}]
        intake_reports = [item for item in report_artifacts if item.category == "intake"]
        eval_pages = [item for item in report_artifacts if item.category == "eval"]
        primary_eval_pages = [item for item in eval_pages if not getattr(item, "is_portal_live", False)]
        archived_eval_pages = [item for item in eval_pages if getattr(item, "is_portal_live", False)]
        comparison_reports = [item for item in report_artifacts if item.category == "comparison"]
        focus = self._pick_focus_eval_case(eval_reports)

        focus_entry = self._empty_state("当前还没有可展示的真实任务。")
        focus_results = self._empty_state("当前还没有可展示的当前结果，请先跑真实评测。")
        focus_actions = ""
        focus_comparison_actions = ""
        focus_uses_profile_matrix = False
        if focus is not None:
            focus_report, focus_case = focus
            summary_mapping = dict(focus_case.summary) if isinstance(focus_case.summary, Mapping) else {}
            focus_uses_profile_matrix = self._stored_case_uses_profile_matrix(focus_case)
            task_title, task_description = self._load_task_brief(summary_mapping, focus_case.case_id, focus_case.trials)
            model_label = self._model_label_from_trials(focus_case.trials)
            focus_entry = (
                self._render_task_input_box(
                    title=task_title,
                    description=task_description,
                    model_label=model_label,
                    hint="这里展示的是最近一次历史样本任务，不是你当前要输入的新任务；真正提交任务请进入 live 交互页。",
                )
                + self._render_case_delivery_proof(summary_mapping)
            )
            ordered_trials = sorted((trial for trial in focus_case.trials if trial.run_summary is not None), key=lambda trial: self._profile_sort_key(str(getattr(trial.harness_profile, "value", trial.harness_profile))))
            available_comparison_filenames = {item.html_path.name for item in comparison_reports}
            focus_results = self._card_grid(
                self._render_focus_trial_card(
                    trial,
                    case_summary=summary_mapping,
                    all_trials=ordered_trials,
                    available_comparison_filenames=available_comparison_filenames,
                )
                for trial in ordered_trials
            )
            focus_actions = '<div class="run-card-actions">' + self._link_button(focus_report.html_path.name, "打开当前套件", primary=True) + '</div>'
            focus_comparison_actions = "".join(
                self._link_button(href, label)
                for href, label in self._focus_comparison_links(focus_report, focus_case, comparison_reports)
            )
        live_portal_box = self._render_live_portal_box(
            url=live_portal_url or "http://127.0.0.1:8765/harness-portal.html",
            command=live_portal_command or "python -m repo_harness_lab.cli.main serve-portal",
        )
        overview_actions = "".join(self._link_button(report.html_path.name, report.title or report.report_id, primary=index == 0) for index, report in enumerate(dashboard_reports[:2]))
        comparison_actions = focus_comparison_actions or "".join(self._link_button(report.html_path.name, report.title or report.report_id) for report in comparison_reports[:2])
        support_actions = "".join(self._link_button(report.html_path.name, report.title or report.report_id) for report in [*intake_reports[:2], *primary_eval_pages[:2]]) + comparison_actions
        archived_actions = "".join(self._link_button(report.html_path.name, report.title or report.report_id) for report in archived_eval_pages[:4])
        runtime_rows: list[tuple[str, str]] = []
        if runtime_root is not None:
            runtime_rows.append(("runtime_root", str(runtime_root)))
        if runs_dir is not None:
            runtime_rows.append(("runs_dir", str(runs_dir)))
        if reports_dir is not None:
            runtime_rows.append(("reports_dir", str(reports_dir)))

        body = "".join(
            [
                '<div class="page-shell simple-shell">',
                self._hero(eyebrow="历史证据页", title="同模型 Harness 演示台", subtitle="这是静态历史证据页，只展示已经跑完的样本和结果；如果要提交任意新任务，请先启动 live 服务，再通过本地 HTTP 页面操作。", badges=("历史样本任务", "正式套件优先", "Live 入口")),
                self._panel(
                    PORTAL_STORY_TITLES["decision"],
                    self._profile_explainer() if focus_uses_profile_matrix else self._current_mode_explainer(),
                    subtitle="同一模型、同一任务、同一仓库边界，只改变 harness 额外交给模型的东西；真正的新任务输入不在这个静态页里。" if focus_uses_profile_matrix else "主线只展示 current 结果；如有基线报告，会在套件页里显示当前 vs 基线的差异。",
                    extra_class="panel-span-2",
                ),
                self._panel(PORTAL_STORY_TITLES["task"], focus_entry + focus_actions + live_portal_box, subtitle="这里展示最近一次历史样本任务，不是你当前正在输入的新任务；新任务请走下面的 Live 提交入口。", extra_class="panel-span-2"),
                self._panel(PORTAL_STORY_TITLES["result"], focus_results, subtitle="下面是这条历史任务在不同运行配置下的真实结果，用来说明 harness 交付差异。" if focus_uses_profile_matrix else "下面是这条历史任务在 current 配置下的真实结果。", extra_class="panel-span-2"),
                self._details_panel(
                    PORTAL_STORY_TITLES["details"],
                    self._panel("快捷入口", overview_actions or self._empty_state("当前没有可打开的总览页面。"), subtitle="常用总览页入口。", extra_class="panel-span-2")
                    + self._panel("正式证据页", support_actions or self._empty_state("当前没有正式证据页。"), subtitle="首页只保留正式 intake、suite 和当前聚焦任务的对比入口。", extra_class="panel-span-2")
                    + self._panel("Portal 试跑归档", archived_actions or self._empty_state("当前没有归档试跑记录。"), subtitle="live portal 的临时提交记录会收在这里，不再占首页正式入口。", extra_class="panel-span-2")
                    + self._panel("运行目录", self._kv_rows(runtime_rows), subtitle="当前 runtime、runs、reports 目录。", extra_class="panel-span-2"),
                    subtitle="不把文件名和内部结构堆满首屏，但保留入口。",
                    summary="展开更多",
                    extra_class="panel-span-2",
                ),
                '</div>',
            ]
        )
        return self._document(title=title, body=body)

    def _profile_explainer(self) -> str:
        return self._list_block(
            (
                "Current：展示当前主线实际交付给模型的仓库树、上下文、任务输入和验收信息。",
                "Custom：如果存在自定义基线，就用同一任务边界对照当前交付和基线差异。",
                "控制变量固定：同一模型、同一任务、同一仓库边界、同一输出格式；只改变 harness 额外交给模型的内容。",
            ),
            empty_text="当前没有运行模式说明。",
        )

    def _current_mode_explainer(self) -> str:
        return self._list_block(
            (
                "主线只跑一次 current 配置，不再默认展开历史矩阵。",
                "current 会带完整仓库树、上下文文件、任务输入和 verifier 步骤。",
                "如果要比较效果，直接对照历史基线报告或用户手工指定的基线报告。",
            ),
            empty_text="当前没有基线说明。",
        )

    def _baseline_summary_block(self, baseline_view: Mapping[str, object]) -> str:
        if not baseline_view:
            return self._empty_state("当前没有基线信息。")
        items = [
            f"当前套件：{baseline_view.get('current_suite_id', 'n/a')}",
            f"{self._baseline_kind_label(str(baseline_view.get('baseline_kind', 'custom')))}：{baseline_view.get('baseline_report_id', 'n/a')}",
            f"通过率变化：{self._format_signed_ratio_delta(baseline_view.get('pass_rate_delta'))}",
            f"平均耗时变化：{self._format_signed_duration_value(baseline_view.get('average_duration_delta_ms'))}",
            f"匹配到的 case 数：{baseline_view.get('matched_case_count', 0)}",
        ]
        improved = [str(item) for item in baseline_view.get("improved_case_ids", ()) if str(item)]
        regressed = [str(item) for item in baseline_view.get("regressed_case_ids", ()) if str(item)]
        if improved:
            items.append("变好 case：" + ", ".join(improved[:3]))
        if regressed:
            items.append("变差 case：" + ", ".join(regressed[:3]))
        return self._list_block(tuple(items), empty_text="当前没有基线信息。")

    def _primary_eval_reports(self, eval_reports: Sequence[StoredEvalReport]) -> list[StoredEvalReport]:
        primary = [report for report in eval_reports if not getattr(report, "is_portal_live", False)]
        return primary or list(eval_reports)

    def _pick_focus_eval_case(self, eval_reports: Sequence[StoredEvalReport]) -> tuple[StoredEvalReport, StoredEvalCase] | None:
        for report in self._primary_eval_reports(eval_reports):
            if not report.case_results:
                continue
            return report, report.case_results[0]
        return None

    def _comparison_link_specs(
        self,
        trials: Sequence[object],
        *,
        baseline_profile: str | None = None,
        available_comparison_filenames: set[str] | None = None,
    ) -> tuple[tuple[str, str, tuple[ProfileRunComparison, ...]], ...]:
        ordered_trials = sorted(
            (trial for trial in trials if getattr(trial, "run_summary", None) is not None),
            key=lambda trial: self._profile_sort_key(str(getattr(trial.harness_profile, "value", trial.harness_profile))),
        )
        profile_runs = {
            str(getattr(trial.harness_profile, "value", trial.harness_profile)): getattr(trial.run_summary, "run_id", "")
            for trial in ordered_trials
            if getattr(trial, "run_summary", None) is not None
        }
        resolved_baseline = baseline_profile or default_baseline_profile(profile_runs.keys())
        grouped_by_target = comparison_map_by_target_profile(profile_runs, baseline_profile=resolved_baseline)
        specs: list[tuple[str, str, tuple[ProfileRunComparison, ...]]] = []
        for trial in ordered_trials:
            profile = str(getattr(trial.harness_profile, "value", trial.harness_profile))
            grouped: dict[str, list[ProfileRunComparison]] = {}
            for comparison in grouped_by_target.get(profile, ()):
                filename = self._comparison_filename(comparison.left_run_id, comparison.right_run_id)
                if available_comparison_filenames is not None and filename not in available_comparison_filenames:
                    continue
                grouped.setdefault(filename, []).append(comparison)
            for filename, comparisons in grouped.items():
                specs.append((profile, filename, tuple(comparisons)))
        return tuple(specs)

    def _comparison_link_label(
        self,
        profile: str,
        comparisons: tuple[ProfileRunComparison, ...],
        *,
        action: bool,
    ) -> str:
        modes = {item.mode for item in comparisons}
        if len(modes) > 1:
            return "打开对比页面" if action else f"{self._profile_label(profile)} 对比"
        mode = next(iter(modes), COMPARISON_MODE_UPLIFT)
        if mode == COMPARISON_MODE_FAIR:
            return "打开公平对比页面" if action else f"{self._profile_label(profile)} 公平对比"
        return "打开抬升对比页面" if action else f"{self._profile_label(profile)} 抬升对比"

    def _comparison_action_links(
        self,
        trials: Sequence[object],
        *,
        target_profile: str,
        available_comparison_filenames: set[str] | None = None,
    ) -> str:
        links = [
            self._link_button(filename, self._comparison_link_label(profile, comparisons, action=True))
            for profile, filename, comparisons in self._comparison_link_specs(
                trials,
                available_comparison_filenames=available_comparison_filenames,
            )
            if profile == target_profile
        ]
        return "".join(links)

    def _focus_comparison_links(
        self,
        report: StoredEvalReport,
        case: StoredEvalCase,
        comparison_reports: Sequence[ReportArtifactSummary],
    ) -> tuple[tuple[str, str], ...]:
        profile_uplift = dict(report.comparison_views.get("profile_uplift", {}))
        baseline_profile = str(profile_uplift.get("baseline_profile", "") or default_baseline_profile(
            str(getattr(trial.harness_profile, "value", trial.harness_profile))
            for trial in case.trials
            if getattr(trial, "run_summary", None) is not None
        ))
        available_filenames = {item.html_path.name for item in comparison_reports}
        return tuple(
            (
                filename,
                self._comparison_link_label(profile, comparisons, action=False),
            )
            for profile, filename, comparisons in self._comparison_link_specs(
                case.trials,
                baseline_profile=baseline_profile,
                available_comparison_filenames=available_filenames,
            )
        )

    def _render_eval_case(self, case_id: str, summary: object, trials: Sequence[object]) -> str:
        summary_mapping = dict(summary) if isinstance(summary, Mapping) else {}
        task_title, task_description = self._load_task_brief(summary_mapping, case_id, trials)
        model_label = self._model_label_from_trials(trials)
        ordered_trials = sorted((trial for trial in trials if trial.run_summary is not None), key=lambda trial: self._profile_sort_key(str(getattr(trial.harness_profile, "value", trial.harness_profile))))
        pass_rate = summary_mapping.get("pass_rate")
        difficulty = str(summary_mapping.get("difficulty", "未知"))
        notes = tuple(localize_harness_message(str(item)) for item in summary_mapping.get("notes", ()) if str(item))
        meta_bits = [f"模型：{model_label}", f"难度：{difficulty}"]
        if pass_rate is not None:
            meta_bits.append(f"通过率：{self._format_metric(float(pass_rate), 'ratio')}")
        note_block = ""
        if notes:
            note_block = '<details class="inline-details"><summary class="details-hint">补充说明</summary>' + self._list_block(notes, empty_text="当前没有额外说明。") + '</details>'
        uses_profile_matrix = self._trials_use_profile_matrix(ordered_trials)
        return "".join(
            [
                '<article class="run-card focus-case">',
                '<div class="card-top">',
                "<span class=\"badge badge-stage\">历史样本任务</span>",
                f'<span class="muted">{" · ".join(escape(item) for item in meta_bits)}</span>',
                '</div>',
                f'<h3>{escape(task_title)}</h3>',
                f'<p class="muted">{escape(task_description or "当前任务没有额外描述。")}</p>',
                self._render_task_input_box(title=task_title, description=task_description, model_label=model_label, hint="下方展示各档 harness 的真实运行结果。" if uses_profile_matrix else "下方展示 current 配置下的真实运行结果。"),
                self._render_case_delivery_proof(summary_mapping),
                '<h4>多运行结果</h4>' if uses_profile_matrix else '<h4>当前结果</h4>',
                self._card_grid(self._render_focus_trial_card(trial, case_summary=summary_mapping, all_trials=ordered_trials) for trial in ordered_trials),
                note_block,
                '</article>',
            ]
        )

    def _render_task_input_box(self, *, title: str, description: str, model_label: str, hint: str) -> str:
        example_text = title if not description else f"{title}\n\n{description}"
        return "".join(
            [
                '<div class="task-box">',
                '<div class="card-top">',
                "<span class=\"badge badge-stage\">历史样本任务</span>",
                f'<span class="muted">模型：{escape(model_label)}</span>',
                '</div>',
                "<div class=\"example-box\"><div class=\"example-title\">历史样本任务正文</div>",
                f'<pre>{escape(example_text)}</pre></div>',
                f'<p class="muted">{escape(hint)}</p>',
                '</div>',
            ]
        )

    def _render_live_portal_box(self, *, url: str, command: str) -> str:
        return ''.join(
            [
                '<div class="example-box">',
                '<div class="example-title">提交新任务（Live 页）</div>',
                '<div class="run-card-actions">',
                self._link_button(url, "打开 Live 提交页", primary=True),
                '</div>',
                '<p class="muted">你现在打开的 file:///.../runtime/reports/harness-portal.html 是静态历史页，只能看证据，不能直接提交新任务。</p>',
                '<ul class="stack-list">',
                '<li>1. 先在终端运行下面这条命令启动 live 服务。</li>',
                '<li>2. 再用浏览器打开上面的 HTTP 地址，而不是 file:/// 本地文件地址。</li>',
                '<li>3. 进入 live 页后，至少填写“任务正文”和“仓库来源”；本地模式支持任意自然语言任务，其余字段可以先留空。</li>',
                '</ul>',
                f'<pre>{escape(command)}</pre>',
                f'<p class="muted">建议直接访问：<code>{escape(url)}</code></p>',
                '</div>',
            ]
        )

    def _render_case_delivery_proof(self, summary_mapping: Mapping[str, object]) -> str:
        shared_items = self._summary_shared_task_items(summary_mapping)
        profile_cards = "".join(
            self._render_profile_delivery_card(name, payload)
            for name, payload in self._summary_profile_matrix(summary_mapping).items()
        )
        delta_cards = "".join(
            self._render_delta_summary_card(item)
            for item in self._summary_profile_deltas(summary_mapping)
        )
        parts: list[str] = []
        if shared_items:
            parts.extend([
                '<h4>共同任务信息</h4>',
                self._list_block(shared_items, empty_text="当前没有共同任务信息。"),
            ])
        if profile_cards:
            parts.extend([
                '<h4>本次额外交付</h4>',
                self._card_grid((profile_cards,)),
            ])
        if delta_cards:
            parts.extend([
                '<h4>控制变量变化</h4>',
                self._card_grid((delta_cards,)),
            ])
        return "".join(parts)

    def _render_focus_trial_card(
        self,
        trial: object,
        *,
        case_summary: Mapping[str, object] | None = None,
        all_trials: Sequence[object] = (),
        available_comparison_filenames: set[str] | None = None,
    ) -> str:
        run_summary = getattr(trial, "run_summary", None)
        if run_summary is None:
            return ""
        profile = str(getattr(trial.harness_profile, "value", trial.harness_profile))
        record = self._load_run_record(run_summary.run_id)
        feedback_items = self._failure_items(record, run_summary)
        harness_items = build_harness_input_items(record)
        shared_items = self._summary_shared_task_items(case_summary or {}) or build_harness_shared_items(record)
        extra_items = self._summary_profile_delivery_items(case_summary or {}, profile) or build_harness_extra_items(record)
        response_items = build_model_response_items(record)
        result_items = feedback_items[:3] if feedback_items else ("当前没有额外反馈。",)
        comparison_actions = self._comparison_action_links(
            all_trials,
            target_profile=profile,
            available_comparison_filenames=available_comparison_filenames,
        )
        actions = self._link_button(self._run_report_href(run_summary.run_id), "打开运行报告", primary=True) + comparison_actions
        return "".join(
            [
                '<article class="run-card result-card">',
                '<div class="run-card-top">',
                '<span class="badge badge-stage">历史样本任务</span>',
                f'<span class="badge badge-status-{escape(run_summary.status.value)}">{escape(self._status_label(run_summary.status.value))}</span>',
                '</div>',
                f'<h3>{escape(self._profile_label(profile))}</h3>',
                '<div class="run-card-metrics">',
                f'<span>验证：{escape(self._verifier_label(run_summary.verifier_outcome))}</span>',
                f'<span>耗时：{escape(self._format_duration(run_summary.duration_ms))}</span>',
                '</div>',
                '<h4>任务输出</h4>',
                self._render_task_output_box(record),
                '<h4>处理结果</h4>',
                self._list_block(result_items, empty_text="当前没有额外结果说明。"),
                '<details class="inline-details"><summary class="details-hint">查看细节</summary><div class="panel-body details-body">',
                '<h4>共同任务信息</h4>',
                self._list_block(shared_items, empty_text="当前没有共同任务信息。"),
                '<h4>本档额外交付</h4>',
                self._list_block(extra_items, empty_text="当前没有额外 harness 交付。"),
                '<h4>Harness 输入摘要</h4>',
                self._list_block(harness_items, empty_text="当前没有记录到 Harness 输入证据。"),
                '<h4>模型响应</h4>',
                self._list_block(response_items, empty_text="当前没有记录到模型响应证据。"),
                '<h4>改动文件</h4>',
                self._list_block(run_summary.changed_files, empty_text="当前没有生成文件改动。"),
                '<div class="run-card-actions">',
                actions,
                '</div></div></details></article>',
            ]
        )

    def _comparison_run_snapshot(self, record: StoredRunRecord, *, side: str) -> str:
        summary = record.summary
        report_href = self._run_report_href(summary.run_id)
        parts = [
            self._kv_rows((("任务 ID", summary.task_id), ("状态", self._status_label(summary.status.value)), ("验证", self._verifier_label(summary.verifier_outcome)), ("耗时", self._format_duration(summary.duration_ms)), ("事件数", str(len(record.events))))),
            '<div class="run-card-actions">' + self._link_button(report_href, "打开左侧运行" if side == "left" else "打开右侧运行", primary=True) + '</div>',
            '<h4>改动文件</h4>',
            self._list_block(summary.changed_files, empty_text="当前没有检测到仓库改动。"),
        ]
        shared_items = build_harness_shared_items(record)
        extra_items = build_harness_extra_items(record)
        harness_items = build_harness_input_items(record)
        response_items = build_model_response_items(record)
        if shared_items:
            parts.extend(['<h4>共同任务信息</h4>', self._list_block(shared_items, empty_text="当前没有共同任务信息。")])
        if extra_items:
            parts.extend(['<h4>本档额外交付</h4>', self._list_block(extra_items, empty_text="当前没有额外 harness 交付。")])
        if harness_items:
            parts.extend(['<h4>模型输入摘要</h4>', self._list_block(harness_items, empty_text="当前没有模型输入证据。")])
        if response_items:
            parts.extend(['<h4>模型输出</h4>', self._list_block(response_items, empty_text="当前没有模型输出证据。")])
        feedback = self._failure_items(record, summary)
        if feedback:
            parts.extend(['<h4>运行反馈</h4>', self._list_block(feedback, empty_text="当前没有记录备注。")])
        return "".join(parts)

    def _render_evidence_delta(self, left: StoredRunRecord, right: StoredRunRecord) -> str:
        harness_items = build_harness_delta_items(left, right)
        response_items = build_model_delta_items(left, right)
        if not harness_items and not response_items:
            return self._empty_state("当前没有记录到 Harness 或模型响应差异。")
        return '<div class="split-panel">' + self._mini_column("Harness 输入差异", self._list_block(harness_items, empty_text="当前没有记录到 Harness 输入差异。")) + self._mini_column("模型响应差异", self._list_block(response_items, empty_text="当前没有记录到模型响应差异。")) + '</div>'

    def _summary_shared_task_items(self, summary_mapping: Mapping[str, object]) -> tuple[str, ...]:
        shared = self._mapping(summary_mapping.get("shared_task_information"))
        if not shared:
            return ()
        items = ["各运行都收到上面这条完全相同的任务正文。"]
        editable = [str(item) for item in shared.get("editable_paths", ()) if str(item)]
        forbidden = [str(item) for item in shared.get("forbidden_paths", ()) if str(item)]
        changed = [str(item) for item in shared.get("expected_changed_files", ()) if str(item)]
        checks = [str(item) for item in shared.get("behavioral_checks", ()) if str(item)]
        verifier_steps = [str(item) for item in shared.get("required_verifier_steps", ()) if str(item)]
        if editable:
            items.append(f"各运行的可改范围相同：{', '.join(editable)}")
        if forbidden:
            items.append(f"各运行的禁改范围相同：{', '.join(forbidden)}")
        if changed:
            items.append(f"各运行的目标改动文件相同：{', '.join(changed)}")
        if checks:
            items.append(f"各运行的行为检查相同：{'; '.join(checks)}")
        if verifier_steps:
            items.append(f"各运行看到的必过步骤名称相同：{', '.join(verifier_steps)}")
        if shared.get("response_contract"):
            items.append("各运行的输出格式要求相同：只能返回 JSON summary + writes。")
        return tuple(items)

    def _summary_profile_matrix(self, summary_mapping: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        matrix = summary_mapping.get("harness_delivery_matrix")
        return {
            str(name): self._mapping(payload)
            for name, payload in dict(matrix).items()
        } if isinstance(matrix, Mapping) else {}

    def _summary_profile_deltas(self, summary_mapping: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
        raw = summary_mapping.get("profile_delta_summary")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return ()
        return tuple(self._mapping(item) for item in raw if isinstance(item, Mapping))

    def _summary_profile_delivery_items(self, summary_mapping: Mapping[str, object], profile: str) -> tuple[str, ...]:
        payload = self._summary_profile_matrix(summary_mapping).get(profile, {})
        items = [str(item) for item in payload.get("additional_delivery_items", ()) if str(item)]
        return tuple(self._localize_delivery_item(item) for item in items)

    def _render_profile_delivery_card(self, profile: str, payload: Mapping[str, object]) -> str:
        items = self._summary_profile_delivery_items({"harness_delivery_matrix": {profile: payload}}, profile)
        return "".join(
            [
                '<article class="run-card result-card">',
                f'<h5>{escape(self._profile_label(profile))}</h5>',
                self._list_block(items, empty_text="当前没有额外交付说明。"),
                '</article>',
            ]
        )

    def _render_delta_summary_card(self, item: Mapping[str, object]) -> str:
        from_profile = self._profile_label(str(item.get("from_profile", "?")))
        to_profile = self._profile_label(str(item.get("to_profile", "?")))
        summary_lines = tuple(self._localize_delivery_item(str(line)) for line in item.get("summary_lines", ()) if str(line))
        return "".join(
            [
                '<article class="run-card result-card">',
                f'<h5>{escape(from_profile)} -> {escape(to_profile)}</h5>',
                self._list_block(summary_lines, empty_text="当前没有控制变量变化说明。"),
                '</article>',
            ]
        )

    def _localize_delivery_item(self, text: str) -> str:
        normalized = " ".join(str(text).split())
        if not normalized:
            return ""
        if normalized == "The current run receives the same task title and description.":
            return "当前运行收到的是同一条用户任务标题和说明。"
        if normalized.startswith("Same editable paths: "):
            return "各运行可改范围相同：" + normalized.removeprefix("Same editable paths: ")
        if normalized.startswith("Same forbidden paths: "):
            return "各运行禁改范围相同：" + normalized.removeprefix("Same forbidden paths: ")
        if normalized.startswith("Same expected changed files: "):
            return "各运行目标改动文件相同：" + normalized.removeprefix("Same expected changed files: ")
        if normalized.startswith("Same behavioral checks: "):
            return "各运行行为检查相同：" + normalized.removeprefix("Same behavioral checks: ")
        if normalized.startswith("Same required verifier step names: "):
            return "各运行必过步骤名称相同：" + normalized.removeprefix("Same required verifier step names: ")
        if normalized == "Same response contract: JSON only with summary and writes.":
            return "各运行输出格式相同：只能返回 JSON summary + writes。"
        if normalized.startswith("Extra harness material: repository tree only"):
            return normalized.replace("Extra harness material: repository tree only", "额外 harness 材料：只有仓库树")
        if normalized.startswith("Repository tree attached"):
            return normalized.replace("Repository tree attached", "附带仓库树")
        if normalized.startswith("Repository tree is enabled"):
            return normalized.replace("Repository tree is enabled for this profile, but the local repo preview is unavailable.", "这个档位会附带仓库树，但当前拿不到本地仓库预览。")
        if normalized.startswith("Repository context files: "):
            return "额外上下文文件：" + normalized.removeprefix("Repository context files: ")
        if normalized.startswith("Injected task inputs: "):
            return "额外任务输入：" + normalized.removeprefix("Injected task inputs: ")
        if normalized.startswith("Injected verifier steps: "):
            return "额外验收步骤：" + normalized.removeprefix("Injected verifier steps: ")
        if normalized.startswith("context files: "):
            return "上下文文件：" + normalized.removeprefix("context files: ")
        if normalized.startswith("context cap: "):
            return "上下文上限：" + normalized.removeprefix("context cap: ")
        if normalized.startswith("new task inputs: "):
            return "新增任务输入：" + normalized.removeprefix("new task inputs: ")
        if normalized.startswith("new verifier steps: "):
            return "新增验收步骤：" + normalized.removeprefix("new verifier steps: ")
        if normalized == "No material delivery difference detected between these profiles.":
            return "这两个档位之间没有检测到实质性交付差异。"
        return normalized

    def _render_task_output_box(self, record: StoredRunRecord | None) -> str:
        output_text = self._task_output_text(record.patch_diff if record is not None else None)
        if not output_text:
            return self._empty_state("当前没有提取到显式任务输出。")
        return f'<pre>{escape(output_text)}</pre>'

    def _task_output_text(self, patch_diff: str | None, *, max_lines: int = 18) -> str:
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
            lines = lines[:max_lines] + [f"... 另有 {len(lines) - max_lines} 行未展开"]
        return "\n".join(lines).strip()

    def _render_verifier(self, record: StoredRunRecord) -> str:
        verifier = record.verifier_result
        failure_summary = tuple(self._localize_feedback_message(item) for item in build_failure_summary(record))
        if verifier is None:
            if not failure_summary:
                return self._empty_state("当前没有保存验证结果。")
            return '<h4>失败摘要</h4>' + self._list_block(failure_summary, empty_text="当前没有失败摘要。") + self._empty_state("当前没有保存独立的 verifier 结果。")

        evidence_items = ''.join(f'<li><strong>{escape(self._localize_feedback_message(item.summary))}</strong><div class="muted">{escape(self._json(item.details))}</div></li>' for item in verifier.evidence)
        command_cards = ''.join(self._command_card(command=' '.join(item.command), exit_code=item.exit_code, cwd=item.cwd, stdout_excerpt=item.stdout_excerpt, stderr_excerpt=item.stderr_excerpt, duration_ms=item.duration_ms) for item in verifier.command_results)
        parts: list[str] = []
        if failure_summary:
            parts.extend(['<h4>失败摘要</h4>', self._list_block(failure_summary, empty_text="当前没有失败摘要。")])
        parts.extend([
            '<div class="split-panel"><div>',
            f'<p><span class="badge badge-status-{escape(verifier.status.value)}">{escape(self._verification_status_label(verifier.status.value))}</span></p>',
            f'<p class="muted">验证器：{escape(verifier.verifier_name)}</p>',
            '<h4>验证证据</h4>',
            f'<ul class="stack-list">{evidence_items or "<li>当前没有保存验证证据。</li>"}</ul>',
            '</div><div><h4>命令结果</h4>',
            command_cards or self._empty_state("当前没有记录到命令执行结果。"),
            '</div></div>',
        ])
        if verifier.errors:
            parts.append(self._panel("验证错误", self._list_block(tuple(self._localize_feedback_message(item) for item in verifier.errors), empty_text="当前没有验证错误。")))
        return ''.join(parts)

    def _render_artifacts(self, summary: RunSummary) -> str:
        if not summary.artifact_index:
            return self._empty_state("当前没有保存运行产物。")
        items = ''.join(f'<li class="artifact-item"><div><strong>{escape(item.name)}</strong><div class="muted">{escape(item.media_type or "未知类型")}</div></div><code>{escape(item.path)}</code></li>' for item in summary.artifact_index)
        return f'<ul class="artifact-list">{items}</ul>'

    def _render_patch_preview(self, patch_diff: str | None, *, max_lines: int = 120) -> str:
        if not patch_diff:
            return self._empty_state("当前没有记录到 patch diff。")
        return f'<pre>{escape(self._trim_patch_preview(patch_diff, max_lines=max_lines))}</pre>'

    def _timeline(self, events: Sequence[object]) -> str:
        if not events:
            return self._empty_state("当前没有可展示的流程事件。")
        items = []
        for event in events:
            payload = self._json(event.payload)
            items.append(''.join([
                '<li class="timeline-item"><div class="timeline-rail"></div><div class="timeline-body"><div class="timeline-meta">',
                "<span class=\"badge badge-stage\">历史样本任务</span>",
                f'<span class="badge badge-event">{escape(event.event_type.value)}</span>',
                f'<span class="muted">{escape(event.timestamp.isoformat())}</span>',
                '</div>',
                f'<div class="timeline-title">{escape(self._event_type_label(event.event_type.value))}</div>',
                f'<pre>{escape(payload)}</pre>' if payload != '{}' else '<p class="muted">当前没有额外负载。</p>',
                '</div></li>',
            ]))
        return f'<ol class="timeline">{"".join(items)}</ol>'

    def _render_run_card(self, summary: RunSummary) -> str:
        run_dir = Path('..') / 'runs' / summary.run_id
        actions = [
            self._link_button((run_dir / 'report.html').as_posix(), '打开运行报告', primary=True),
            self._link_button((run_dir / 'summary.json').as_posix(), '打开摘要 JSON'),
        ]
        artifact_names = {artifact.name for artifact in summary.artifact_index}
        if 'report' in artifact_names:
            actions.append(self._link_button((run_dir / 'report.md').as_posix(), '打开 Markdown 报告'))
        if 'patch' in artifact_names:
            actions.append(self._link_button((run_dir / 'patch.diff').as_posix(), '打开补丁 Diff'))
        return ''.join([
            '<article class="run-card">',
            '<div class="run-card-top">',
            f'<span class="badge badge-status-{escape(summary.status.value)}">{escape(self._status_label(summary.status.value))}</span>',
            f'<span class="muted">{escape(self._format_timestamp(summary.started_at))}</span>',
            '</div>',
            f'<h3>{escape(summary.run_id)}</h3>',
            f'<p class="muted">任务：{escape(summary.task_id)}</p>',
            '<div class="run-card-metrics">',
            f'<span>验证：{escape(self._verifier_label(summary.verifier_outcome))}</span>',
            f'<span>耗时：{escape(self._format_duration(summary.duration_ms))}</span>',
            f'<span>改动文件：{len(summary.changed_files)}</span>',
            '</div><div class="run-card-actions">',
            ''.join(actions),
            '</div></article>',
        ])

    def _comparison_filename(self, left_run_id: str, right_run_id: str) -> str:
        return f"compare-{self._safe_file_stem(left_run_id)}-vs-{self._safe_file_stem(right_run_id)}.html"

    def _safe_file_stem(self, value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
        return sanitized or "report"

    def _profile_sort_key(self, profile: str) -> tuple[int, str]:
        order = {"current": 0, "custom": 1}
        return order.get(profile, 99), profile

    def _profile_label(self, profile: str) -> str:
        return {
            "current": "Current 当前配置",
            "custom": "Custom 自定义配置",
        }.get(profile, profile)

    def _report_uses_profile_matrix(self, case_results: Sequence[object]) -> bool:
        return any(self._trials_use_profile_matrix(getattr(case, "trials", ())) for case in case_results)

    def _stored_case_uses_profile_matrix(self, case: object) -> bool:
        return self._trials_use_profile_matrix(getattr(case, "trials", ()))

    def _trials_use_profile_matrix(self, trials: Sequence[object]) -> bool:
        profiles = {
            str(getattr(getattr(trial, "harness_profile", ""), "value", getattr(trial, "harness_profile", "")))
            for trial in trials
            if getattr(trial, "run_summary", None) is not None
        }
        supported_profiles = {"current", "custom"}
        return len(profiles) > 1 and bool(profiles & supported_profiles)

    def _baseline_kind_label(self, kind: str) -> str:
        return {"historical": "历史基线", "custom": "自定义基线"}.get(kind, kind or "基线")

    def _format_signed_ratio_delta(self, value: object) -> str:
        if value is None:
            return "n/a"
        points = float(value) * 100
        sign = "+" if points > 0 else ""
        return f"{sign}{points:.1f} pts"

    def _format_signed_duration_value(self, value: object) -> str:
        if value is None:
            return "n/a"
        milliseconds = int(round(float(value)))
        sign = "+" if milliseconds > 0 else ""
        return f"{sign}{milliseconds} ms" if abs(milliseconds) < 1000 else f"{sign}{milliseconds / 1000:.2f} s"

    def _status_label(self, status: str) -> str:
        return {"succeeded": "成功", "failed": "失败", "error": "错误", "running": "运行中", "pending": "等待中", "skipped": "已跳过", "cancelled": "已取消"}.get(status, status)

    def _verifier_label(self, verifier: str | None) -> str:
        return {"passed": "通过", "failed": "未通过", "error": "错误", "skipped": "已跳过", "not_run": "未执行", None: "未执行"}.get(verifier, verifier or "未执行")

    def _verification_status_label(self, status: str) -> str:
        return {"passed": "通过", "failed": "失败", "error": "错误", "skipped": "已跳过"}.get(status, status)

    def _event_type_label(self, event_type: str) -> str:
        return {
            "run_started": "运行开始",
            "workspace_prepared": "工作区准备完成",
            "agent_invoked": "Agent 已调用",
            "model_requested": "模型请求已发出",
            "model_responded": "模型已返回",
            "command_executed": "命令已执行",
            "file_changed": "文件已改动",
            "verifier_started": "验证开始",
            "verifier_finished": "验证结束",
            "run_finished": "运行结束",
        }.get(event_type, event_type)

    def _stage_label(self, stage: str) -> str:
        return {"preparation": "准备", "workspace": "工作区", "agent": "模型执行", "verification": "验证", "finalization": "收尾", "evaluation": "评测"}.get(stage, stage)
    def _failure_items(self, record: StoredRunRecord | None, summary: RunSummary) -> tuple[str, ...]:
        items: tuple[str, ...] = ()
        if record is not None:
            failure_summary = build_failure_summary(record)
            if failure_summary:
                items = tuple(failure_summary)
        if not items and summary.notes:
            items = tuple(str(item) for item in summary.notes)
        if not items:
            hint = pick_failure_hint(summary)
            items = (hint,) if hint else ()
        return tuple(self._localize_feedback_message(item) for item in items if item)

    def _localize_feedback_message(self, text: str) -> str:
        normalized = " ".join(str(text).split())
        if not normalized:
            return ""
        exact = {
            "The run stopped before deterministic verification produced a result.": "运行在确定性验证完成前就停止了。",
            "The run did not leave any file changes.": "本次运行没有留下文件改动。",
            "Draft completion threshold reached.": "草稿完成度已达到当前阈值。",
            "Draft completion threshold not reached.": "草稿完成度未达到当前阈值。",
            "no file changes detected in workspace": "工作区没有检测到文件改动。",
            "failed": "失败",
            "passed": "通过",
        }
        if normalized in exact:
            return exact[normalized]
        if normalized.startswith("Run note: "):
            return "运行备注：" + normalized.removeprefix("Run note: ")
        if normalized.startswith("Direct error: "):
            return "直接错误：" + normalized.removeprefix("Direct error: ")
        if normalized.startswith("Failed check: "):
            return "失败检查：" + normalized.removeprefix("Failed check: ")
        if normalized.startswith("Command output: "):
            return "命令输出：" + normalized.removeprefix("Command output: ")
        if normalized.startswith("Command exited with code "):
            return "命令退出码：" + normalized.removeprefix("Command exited with code ")
        draft_score = re.fullmatch(r"draft completion score: ([0-9.]+) / 1.00 \(threshold ([0-9.]+)\)", normalized)
        if draft_score is not None:
            return f"草稿完成度分：{draft_score.group(1)} / 1.00（阈值 {draft_score.group(2)}）"
        expected_match = re.fullmatch(r"expected files matched: (\d+)/(\d+) \((.*)\)", normalized)
        if expected_match is not None:
            return f"目标文件命中：{expected_match.group(1)}/{expected_match.group(2)}（{expected_match.group(3)}）"
        changed_detected = re.fullmatch(r"changed files detected: (.+)", normalized)
        if changed_detected is not None:
            return f"已检测到改动文件：{changed_detected.group(1)}"
        anchor_match = re.fullmatch(r"task anchors matched: (\d+)/(\d+) \((.*)\)", normalized)
        if anchor_match is not None:
            return f"任务锚点命中：{anchor_match.group(1)}/{anchor_match.group(2)}（{anchor_match.group(3)}）"
        missing_expected = re.fullmatch(r"missing expected changed files: (.+)", normalized)
        if missing_expected is not None:
            return f"缺少目标改动文件：{missing_expected.group(1)}"
        missing_anchors = re.fullmatch(r"task anchors not reflected in changed content: (.+)", normalized)
        if missing_anchors is not None:
            return f"改动内容未体现这些任务锚点：{missing_anchors.group(1)}"
        scope_violation = re.fullmatch(r"changed files escaped drafted scope: (.+)", normalized)
        if scope_violation is not None:
            return f"改动超出了草拟范围：{scope_violation.group(1)}"
        weak_confidence = re.fullmatch(r"draft completion confidence is weak: (.+)", normalized)
        if weak_confidence is not None:
            return f"草稿完成度信号偏弱：{weak_confidence.group(1)}"
        low_score = re.fullmatch(r"completion score ([0-9.]+) is below threshold ([0-9.]+)", normalized)
        if low_score is not None:
            return f"完成度分 {low_score.group(1)} 低于通过阈值 {low_score.group(2)}"
        verifier_failed = re.fullmatch(r"The verifier `(.+)` did not pass\.", normalized)
        if verifier_failed is not None:
            return f"验证器 `{verifier_failed.group(1)}` 未通过。"
        verifier_error = re.fullmatch(r"The verifier `(.+)` hit an internal error\.", normalized)
        if verifier_error is not None:
            return f"验证器 `{verifier_error.group(1)}` 发生内部错误。"
        verifier_skipped = re.fullmatch(r"The verifier `(.+)` was skipped, so there is no proof of success\.", normalized)
        if verifier_skipped is not None:
            return f"验证器 `{verifier_skipped.group(1)}` 被跳过，目前没有成功证据。"
        step_exit = re.fullmatch(r"(.+): command exited with code (\d+)", normalized)
        if step_exit is not None:
            return f"{step_exit.group(1)}：命令退出码 {step_exit.group(2)}"
        step_failed = re.fullmatch(r"(.+): failed", normalized, flags=re.IGNORECASE)
        if step_failed is not None:
            return f"{step_failed.group(1)}：失败"
        return normalized

    def _load_run_record(self, run_id: str) -> StoredRunRecord | None:
        if self._run_record_loader is None:
            return None
        try:
            return self._run_record_loader(run_id)
        except FileNotFoundError:
            return None

    def _run_report_href(self, run_id: str) -> str:
        return (Path("..") / "runs" / run_id / "report.html").as_posix()

    def _eval_model_label(self, case_results: Sequence[object]) -> str:
        for case in case_results:
            trials = getattr(case, "trials", ())
            label = self._model_label_from_trials(trials)
            if label != "未知模型":
                return label
        return "未知模型"

    def _model_label_from_trials(self, trials: Sequence[object]) -> str:
        for trial in trials:
            run_summary = getattr(trial, "run_summary", None)
            if run_summary is None:
                continue
            record = self._load_run_record(run_summary.run_id)
            label = self._model_label_from_record(record)
            if label != "未知模型":
                return label
        return "未知模型"

    def _model_label_from_record(self, record: StoredRunRecord | None) -> str:
        if record is None:
            return "未知模型"
        for item in build_harness_input_items(record):
            if item.startswith("模型："):
                return item.split("模型：", 1)[1]
        return "未知模型"

    def _load_task_brief(self, summary: Mapping[str, object], fallback_case_id: str, trials: Sequence[object] = ()) -> tuple[str, str]:
        title = str(summary.get("task_title") or "").strip()
        description = str(summary.get("task_description") or "").strip()
        if title or description:
            return title or fallback_case_id, description
        trial_title, trial_description = self._task_brief_from_trials(trials, fallback_case_id)
        if trial_title != fallback_case_id or trial_description:
            return trial_title, trial_description
        task_ref = summary.get("task_spec_ref")
        if isinstance(task_ref, str):
            task_path = Path(task_ref)
            if task_path.exists():
                return self._task_brief_from_path(task_path, fallback_case_id, description_key="description")
        return fallback_case_id, ""

    def _task_brief_from_trials(self, trials: Sequence[object], fallback_case_id: str) -> tuple[str, str]:
        for trial in trials:
            metadata = self._trial_metadata(trial)
            intake_ref = metadata.get("intake_source_path")
            if isinstance(intake_ref, str):
                intake_path = Path(intake_ref)
                if intake_path.exists():
                    return self._task_brief_from_path(intake_path, fallback_case_id, description_key="business_request")
            task_ref = metadata.get("scaffolded_task_spec_path")
            if isinstance(task_ref, str):
                task_path = Path(task_ref)
                if task_path.exists():
                    return self._task_brief_from_path(task_path, fallback_case_id, description_key="description")
        return fallback_case_id, ""

    def _trial_metadata(self, trial: object) -> Mapping[str, object]:
        metadata = getattr(trial, "run_request_metadata", None)
        if isinstance(metadata, Mapping):
            return dict(metadata)
        run_request = getattr(trial, "run_request", None)
        metadata = getattr(run_request, "metadata", None)
        if isinstance(metadata, Mapping):
            return dict(metadata)
        return {}

    def _task_brief_from_path(self, path: Path, fallback_case_id: str, *, description_key: str) -> tuple[str, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError):
            return fallback_case_id, ""
        description = payload.get(description_key) or payload.get("description") or ""
        return str(payload.get("title") or fallback_case_id), str(description)

    def _mini_column(self, title: str, content: str) -> str:
        return f'<div class="mini-column"><h3>{escape(title)}</h3>{content}</div>'

    def _dual_list(self, *, left_title: str, left_items: Sequence[str], right_title: str, right_items: Sequence[str], empty_text: str) -> str:
        return '<div class="split-panel">' + self._mini_column(left_title, self._list_block(left_items, empty_text=empty_text)) + self._mini_column(right_title, self._list_block(right_items, empty_text=empty_text)) + '</div>'

    def _dual_patch_preview(self, *, left_title: str, left_patch: str | None, right_title: str, right_patch: str | None) -> str:
        return '<div class="split-panel">' + self._mini_column(left_title, self._render_patch_preview(left_patch)) + self._mini_column(right_title, self._render_patch_preview(right_patch)) + '</div>'

    def _dual_timeline(self, *, left_title: str, left_events: Sequence[object], right_title: str, right_events: Sequence[object]) -> str:
        return '<div class="split-panel">' + self._mini_column(left_title, self._timeline(left_events)) + self._mini_column(right_title, self._timeline(right_events)) + '</div>'

    def _hero(self, *, eyebrow: str, title: str, subtitle: str, badges: Sequence[str]) -> str:
        badge_html = ''.join(f'<span class="badge badge-hero">{escape(item)}</span>' for item in badges if item)
        return f'<header class="hero"><div class="hero-eyebrow">{escape(eyebrow)}</div><h1>{escape(title)}</h1><p>{escape(subtitle)}</p><div class="hero-badges">{badge_html}</div></header>'

    def _metric_grid(self, metrics: Iterable[tuple[str, str, str]]) -> str:
        cards = ''.join(f'<article class="metric-card"><div class="metric-label">{escape(label)}</div><div class="metric-value">{escape(value)}</div><div class="metric-caption">{escape(caption)}</div></article>' for label, value, caption in metrics)
        return f'<section class="metric-grid">{cards}</section>'

    def _panel(self, title: str, content: str, *, subtitle: str = '', extra_class: str = '', section_id: str = '') -> str:
        subtitle_html = f'<p class="panel-subtitle">{escape(subtitle)}</p>' if subtitle else ''
        class_name = f'panel {extra_class}'.strip()
        id_attr = f' id="{escape(section_id)}"' if section_id else ''
        return f'<section{id_attr} class="{escape(class_name)}"><div class="panel-header"><h2>{escape(title)}</h2>{subtitle_html}</div><div class="panel-body">{content}</div></section>'

    def _details_panel(self, title: str, content: str, *, subtitle: str = '', summary: str = '', extra_class: str = '', section_id: str = '') -> str:
        subtitle_html = f'<p class="panel-subtitle">{escape(subtitle)}</p>' if subtitle else ''
        class_name = f'panel details-panel {extra_class}'.strip()
        id_attr = f' id="{escape(section_id)}"' if section_id else ''
        summary_text = summary or '展开'
        return f'<section{id_attr} class="{escape(class_name)}"><details><summary class="details-summary"><div class="details-summary-copy"><h2>{escape(title)}</h2>{subtitle_html}</div><span class="details-hint">{escape(summary_text)}</span></summary><div class="panel-body details-body">{content}</div></details></section>'

    def _kv_rows(self, items: Iterable[tuple[str, str]]) -> str:
        rows = ''.join(f'<div class="kv-row"><span>{escape(key)}</span><code>{escape(value)}</code></div>' for key, value in items)
        return rows or self._empty_state('当前没有值可展示。')

    def _list_block(self, items: Sequence[str], *, empty_text: str) -> str:
        if not items:
            return self._empty_state(empty_text)
        return '<ul class="stack-list">' + ''.join(f'<li>{escape(item)}</li>' for item in items) + '</ul>'

    def _card_grid(self, cards: Sequence[str] | Iterable[str]) -> str:
        rendered = ''.join(cards)
        return f'<div class="card-grid">{rendered}</div>' if rendered else self._empty_state('当前没有可展示的结果卡片。')

    def _link_button(self, href: str, label: str, *, primary: bool = False) -> str:
        class_name = 'button button-primary' if primary else 'button'
        return f'<a class="{class_name}" href="{escape(href)}">{escape(label)}</a>'

    def _command_card(self, *, command: str, exit_code: int, cwd: str, stdout_excerpt: str, stderr_excerpt: str, duration_ms: int | None) -> str:
        excerpts = []
        if stdout_excerpt:
            excerpts.append(f'<div><h5>标准输出</h5><pre>{escape(stdout_excerpt)}</pre></div>')
        if stderr_excerpt:
            excerpts.append(f'<div><h5>标准错误</h5><pre>{escape(stderr_excerpt)}</pre></div>')
        if not excerpts:
            excerpts.append(self._empty_state('当前没有保存命令输出片段。'))
        return '<article class="command-card"><div class="command-top">' + f'<code>{escape(command)}</code>' + f'<span class="badge {"badge-pass" if exit_code == 0 else "badge-fail"}">exit {exit_code}</span></div>' + f'<p class="muted">工作目录：{escape(cwd)} · 耗时：{escape(self._format_duration(duration_ms))}</p>' + ''.join(excerpts) + '</article>'

    def _document(self, *, title: str, body: str) -> str:
        return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + escape(title) + '</title><style>' + self._styles() + '</style></head><body>' + body + '</body></html>'

    def _empty_state(self, text: str) -> str:
        return f'<div class="empty-state">{escape(text)}</div>'

    def _format_duration(self, duration_ms: int | None) -> str:
        if duration_ms is None:
            return 'n/a'
        return f'{duration_ms} ms' if duration_ms < 1000 else f'{duration_ms / 1000:.2f} s'

    def _format_signed_duration(self, duration_ms: int | None) -> str:
        if duration_ms is None:
            return 'n/a'
        sign = '+' if duration_ms > 0 else ''
        return f'{sign}{duration_ms} ms' if abs(duration_ms) < 1000 else f'{sign}{duration_ms / 1000:.2f} s'

    def _format_signed_number(self, value: int) -> str:
        return f'{value:+d}'

    def _format_metric(self, value: float, unit: str | None) -> str:
        if unit == 'ratio':
            return f'{value:.2%}'
        if unit == 'ms':
            return self._format_duration(int(value))
        return str(int(value)) if float(value).is_integer() else f'{value:.2f}'

    def _format_timestamp(self, value: object) -> str:
        isoformat = getattr(value, 'isoformat', None)
        return str(isoformat()) if callable(isoformat) else str(value)

    def _mapping(self, value: object) -> Mapping[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    def _json(self, value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _trim_patch_preview(self, patch_diff: str, *, max_lines: int) -> str:
        lines = patch_diff.splitlines()
        if len(lines) <= max_lines:
            return patch_diff or '# empty patch'
        preview = lines[:max_lines]
        preview.append(f'# ... 另有 {len(lines) - max_lines} 行未展开')
        return '\n'.join(preview)

    def _styles(self) -> str:
        return """
:root{--panel:rgba(255,255,255,.8);--panel-border:rgba(26,49,60,.12);--ink:#14212b;--muted:#5e6a73;--accent:#0f766e;--warm:#c46c2d;--danger:#b42318;--ok:#1f7a1f;--shadow:0 18px 50px rgba(20,33,43,.12)}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at top left, rgba(196,108,45,.18), transparent 32%),radial-gradient(circle at top right, rgba(15,118,110,.18), transparent 34%),linear-gradient(180deg,#f8f3ea 0%,#eef2ef 100%);font-family:"Aptos","Trebuchet MS",sans-serif}h1,h2,h3,h4,h5{font-family:Georgia,"Times New Roman",serif;margin:0}a{color:inherit;text-decoration:none}code,pre{font-family:"Cascadia Mono",Consolas,monospace}pre{margin:0;white-space:pre-wrap;word-break:break-word;background:rgba(20,33,43,.06);border-radius:14px;padding:12px}.page-shell{max-width:1280px;margin:0 auto;padding:28px 20px 40px}.hero{background:linear-gradient(135deg,rgba(20,33,43,.98),rgba(15,118,110,.93));color:#fbfaf7;border-radius:28px;padding:32px;box-shadow:var(--shadow)}.hero h1{font-size:clamp(2rem,4vw,3.6rem);line-height:1;margin-top:6px}.hero p{max-width:720px;margin:14px 0 0;color:rgba(251,250,247,.8)}.hero-eyebrow{text-transform:uppercase;letter-spacing:.18em;font-size:.75rem;color:rgba(251,250,247,.72)}.hero-badges,.run-card-top,.run-card-actions,.run-card-metrics,.command-top,.card-top{display:flex;flex-wrap:wrap;gap:10px}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:22px 0}.metric-card,.panel,.run-card,.command-card{background:var(--panel);border:1px solid var(--panel-border);border-radius:22px;box-shadow:var(--shadow)}.metric-card,.panel,.run-card,.command-card{padding:18px}.metric-label,.metric-caption,.muted,.panel-subtitle{color:var(--muted)}.metric-label{text-transform:uppercase;letter-spacing:.12em;font-size:.72rem}.metric-value{font-family:Georgia,"Times New Roman",serif;font-size:2rem;margin:8px 0 6px}.layout-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.panel-span-2{grid-column:span 2}.panel-header{display:flex;flex-direction:column;gap:6px;margin-bottom:16px}.panel-body{display:flex;flex-direction:column;gap:14px}.details-panel{padding:0}.details-panel details{padding:18px}.details-summary{list-style:none;display:flex;align-items:flex-start;justify-content:space-between;gap:16px;cursor:pointer}.details-summary::-webkit-details-marker{display:none}.details-summary-copy{display:flex;flex-direction:column;gap:6px}.details-hint{display:inline-flex;align-items:center;justify-content:center;padding:8px 12px;border-radius:999px;border:1px solid rgba(20,33,43,.12);color:var(--muted);white-space:nowrap}.details-body{padding-top:16px}.details-body .panel:first-child{margin-top:0}.badge{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:6px 12px;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase}.badge-hero{background:rgba(255,255,255,.14);color:#fbfaf7}.badge-stage{background:rgba(15,118,110,.12);color:var(--accent)}.badge-event{background:rgba(196,108,45,.12);color:var(--warm)}.badge-pass,.badge-status-succeeded,.badge-status-passed{background:rgba(31,122,31,.12);color:var(--ok)}.badge-fail,.badge-status-failed,.badge-status-error{background:rgba(180,35,24,.12);color:var(--danger)}.badge-status-running,.badge-status-pending,.badge-status-skipped,.badge-status-cancelled{background:rgba(196,108,45,.12);color:var(--warm)}.stack-list,.artifact-list{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:10px}.kv-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid rgba(20,33,43,.08)}.kv-row:last-child{border-bottom:0}.split-panel{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.timeline{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:14px}.timeline-item{display:grid;grid-template-columns:20px 1fr;gap:12px}.timeline-rail{position:relative}.timeline-rail::before{content:"";position:absolute;left:8px;top:0;bottom:0;width:4px;border-radius:999px;background:linear-gradient(180deg,var(--accent),var(--warm))}.timeline-body{border:1px solid rgba(20,33,43,.08);border-radius:18px;padding:14px;background:rgba(255,255,255,.66)}.timeline-meta{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}.timeline-title{font-size:1.08rem;margin-bottom:10px}.task-box{display:flex;flex-direction:column;gap:12px}.input-label{font-size:.96rem;font-weight:600}.task-input{width:100%;min-height:144px;resize:vertical;border:1px solid rgba(20,33,43,.12);border-radius:18px;padding:16px;background:rgba(255,255,255,.72);color:var(--ink);font:inherit;line-height:1.6}.example-box{border:1px solid rgba(20,33,43,.1);border-radius:18px;padding:14px;background:rgba(255,255,255,.58)}.example-title{font-size:.84rem;color:var(--muted);margin-bottom:8px}.example-box pre{padding:0;background:transparent}.simple-shell{max-width:1080px}.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.inline-details{margin-top:14px}.inline-details summary{cursor:pointer}.empty-state{border:1px dashed rgba(20,33,43,.18);border-radius:18px;padding:18px;color:var(--muted);background:rgba(255,255,255,.5)}@media(max-width:1000px){.layout-grid,.split-panel{grid-template-columns:1fr}.panel-span-2{grid-column:span 1}}@media(max-width:640px){.page-shell{padding:16px 12px 28px}.hero{padding:24px}.details-summary{flex-direction:column}.metric-grid,.card-grid{grid-template-columns:1fr}}
"""


