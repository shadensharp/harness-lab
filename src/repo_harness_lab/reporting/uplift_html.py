from __future__ import annotations

from collections import defaultdict
import json
from html import escape
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from repo_harness_lab.domain.run_models import RunSummary
from repo_harness_lab.reporting.failure_summary import build_failure_summary
from repo_harness_lab.reporting.run_evidence import (
    build_harness_extra_items,
    build_harness_input_items,
    build_harness_shared_items,
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
from repo_harness_lab.storage.run_store import StoredEvalCase, StoredEvalReport, StoredEvalTrial, StoredRunComparison, StoredRunRecord


class UpliftHtmlReporter:
    def __init__(
        self,
        *,
        run_record_loader: Callable[[str], StoredRunRecord] | None = None,
        run_comparison_loader: Callable[[str, str], StoredRunComparison] | None = None,
    ) -> None:
        self._run_record_loader = run_record_loader
        self._run_comparison_loader = run_comparison_loader

    def render_dashboard(self, eval_reports: Sequence[StoredEvalReport], *, title: str = "同模型 Harness 总览") -> str:
        primary_eval_reports = [report for report in eval_reports if not getattr(report, "is_portal_live", False)]
        featured_eval_reports = primary_eval_reports or list(eval_reports)
        archived_eval_reports = [report for report in eval_reports if getattr(report, "is_portal_live", False)]
        focus = self._pick_focus_case(featured_eval_reports)
        focus_entry = self._empty("当前还没有可展示的真实任务。")
        focus_results = self._empty("当前还没有可展示的当前结果。")
        focus_actions = ""
        focus_uses_profile_matrix = False
        if focus is not None:
            report, case = focus
            summary = self._mapping(case.summary)
            focus_uses_profile_matrix = self._report_uses_profile_matrix(report)
            task_title, task_description = self._load_task_brief(summary, case.case_id, case.trials)
            model_label = self._model_label_from_trials(case.trials)
            baseline_profile = str(self._mapping(report.comparison_views.get("profile_uplift")).get("baseline_profile", "current") or "current")
            focus_entry = (
                self._render_task_input_box(
                    title=task_title,
                    description=task_description,
                    model_label=model_label,
                    hint="这里展示真实提交给模型的任务；更细的运行过程请进入对应运行报告。",
                )
                + self._render_case_delivery_proof(summary)
            )
            ordered_trials = sorted(case.trials, key=lambda trial: self._profile_sort_key(trial.harness_profile, baseline_profile))
            focus_results = self._card_grid(
                self._render_focus_trial_card(
                    report=report,
                    trial=trial,
                    case_summary=summary,
                    baseline_profile=baseline_profile,
                    all_trials=ordered_trials,
                    profile_uplift=self._mapping(report.comparison_views.get("profile_uplift")),
                )
                for trial in ordered_trials
                if trial.run_summary is not None
            )
            focus_actions = '<div class="actions">' + self._button(report.html_path.name, "打开当前套件", primary=True) + '</div>'

        suite_cards = self._card_grid(self._render_suite_card(report) for report in featured_eval_reports)
        recommended_cards = self._card_grid(self._render_recommended_case_card(report, case, score, reasons) for report, case, score, reasons in self._sorted_recommended_eval_cases(featured_eval_reports))
        failure_cards = self._card_grid(self._render_failure_profile_card(name, item) for name, item in sorted(self._aggregate_profile_failures(featured_eval_reports).items()))
        archived_cards = self._card_grid(self._render_archived_suite_card(report) for report in archived_eval_reports)
        body = "".join(
            [
                '<div class="page simple-page">',
                self._hero(
                    title="同模型 Harness 结果页",
                    subtitle="查看用户任务、模型和多次运行结果。" if focus_uses_profile_matrix else "查看用户任务、模型和 current 结果，必要时再对照基线报告。",
                    badges=(f"正式套件：{len(featured_eval_reports)}", f"模型：{self._dashboard_model_label(featured_eval_reports)}", "模式：multi-run" if focus_uses_profile_matrix else "模式：current"),
                ),
                self._panel(PORTAL_STORY_TITLES["decision"], self._profile_explainer() if focus_uses_profile_matrix else self._current_mode_explainer(), subtitle="同一模型、同一任务、同一验收，只改变 harness 额外交给模型的内容。" if focus_uses_profile_matrix else "主线只跑 current 单次配置；比较时再看基线差异。", section_id="explain"),
                self._panel(PORTAL_STORY_TITLES["task"], focus_entry + focus_actions, subtitle="当前聚焦任务。", section_id="entry"),
                self._panel(PORTAL_STORY_TITLES["result"], focus_results, subtitle="直接对比多次运行的处理结果。" if focus_uses_profile_matrix else "这里展示 current 配置下的真实结果。", section_id="proof"),
                self._details_panel(
                    PORTAL_STORY_TITLES["details"],
                    self._panel("套件概览", suite_cards if featured_eval_reports else self._empty("当前还没有可展示的套件。"), subtitle="已生成的正式评测套件。")
                    + self._panel("失败汇总", failure_cards if failure_cards else self._empty("当前没有失败聚合结果。"), subtitle="需要排查失败时再展开。")
                    + self._panel("推荐任务", recommended_cards if recommended_cards else self._empty("当前没有推荐任务。"), subtitle="保留推荐理由，但不再占首屏高度。")
                    + self._panel("Portal 试跑归档", archived_cards if archived_cards else self._empty("当前没有归档试跑。"), subtitle="live portal 的临时套件会收在这里，不再混进正式推荐和失败汇总。"),
                    subtitle="保留套件、失败和推荐信息，但统一收进折叠区。",
                    summary="展开更多",
                    section_id="more",
                ),
                '</div>',
            ]
        )
        return self._document(title=title, body=body)

    def _profile_explainer(self) -> str:
        return self._list_block(
            (
                "Current：当前主线运行，默认带完整仓库树、上下文文件、任务输入和 verifier 步骤。",
                "Custom：用户或套件显式覆盖的运行配置，用来做附加对照。",
                "控制变量固定：同一模型、同一任务、同一仓库边界、同一输出格式；只改变 harness 交付给模型的内容。",
            ),
            empty_text="当前没有多运行说明。",
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

    def _render_suite_card(self, report: StoredEvalReport) -> str:
        profile_uplift = self._mapping(report.comparison_views.get("profile_uplift"))
        baseline = str(profile_uplift.get("baseline_profile", "n/a"))
        current = self._mapping(profile_uplift.get("current"))
        custom = self._mapping(profile_uplift.get("custom"))
        return ''.join(
            [
                '<article class="card">',
                '<div class="card-top">',
                f'<span class="badge">{escape(report.suite_id)}</span>',
                f'<span class="muted">基线：{escape(baseline)}</span>',
                '</div>',
                f'<h3>{escape(report.title)}</h3>',
                '<div class="facts">',
                f'<span>任务数：{report.case_count}</span>',
                f'<span>current：{escape(self._delta_ratio(current.get("pass_rate_delta")))}</span>',
                f'<span>custom：{escape(self._delta_ratio(custom.get("pass_rate_delta")))}</span>',
                '</div>',
                f'<p class="muted">标签：{escape(self._join_values(report.task_tags))}</p>',
                f'<p class="muted">信号：{escape(self._join_values(report.harness_signals))}</p>',
                '<div class="actions">',
                self._button(report.html_path.name, '打开套件页面', primary=True),
                '</div></article>',
            ]
        )

    def _render_recommended_case_card(self, report: StoredEvalReport, case: StoredEvalCase, score: int, reasons: Sequence[str]) -> str:
        summary = self._mapping(case.summary)
        difficulty = str(summary.get("difficulty", "n/a"))
        tags = [str(item) for item in summary.get("task_tags", ()) if str(item)]
        signals = [str(item) for item in summary.get("harness_signals", ()) if str(item)]
        reason_html = ''.join(f'<li>{escape(reason)}</li>' for reason in reasons[:3])
        return ''.join(
            [
                '<article class="card">',
                '<div class="card-top">',
                f'<span class="badge">score {score}</span>',
                f'<span class="muted">{escape(report.suite_id)}</span>',
                '</div>',
                f'<h3>{escape(case.case_id)}</h3>',
                f'<p class="muted">难度：{escape(difficulty)}</p>',
                f'<p class="muted">信号：{escape(self._join_values(signals))}</p>',
                f'<p class="muted">标签：{escape(self._join_values(tags))}</p>',
                '<h4>推荐理由</h4>',
                f'<ul class="reason-list">{reason_html}</ul>' if reason_html else self._empty("当前没有推荐理由。"),
                '<div class="actions">',
                self._button(report.html_path.name, '打开套件页面', primary=True),
                '</div></article>',
            ]
        )
    def _render_archived_suite_card(self, report: StoredEvalReport) -> str:
        return ''.join(
            [
                '<article class="card">',
                '<div class="card-top">',
                '<span class="badge">Portal 试跑</span>',
                f'<span class="muted">{escape(report.suite_id)}</span>',
                '</div>',
                f'<h3>{escape(report.title)}</h3>',
                '<p class="muted">这类 live portal 临时试跑会保留可回溯入口，但不会继续占用首页正式套件、推荐任务和失败汇总。</p>',
                '<div class="actions">',
                self._button(report.html_path.name, '打开归档页面'),
                '</div></article>',
            ]
        )

    def _comparison_link_specs(
        self,
        report: StoredEvalReport,
        trials: Sequence[StoredEvalTrial],
        *,
        baseline_profile: str | None = None,
    ) -> tuple[tuple[str, str, tuple[ProfileRunComparison, ...]], ...]:
        ordered_trials = sorted(trials, key=lambda trial: self._profile_sort_key(trial.harness_profile, baseline_profile or 'current'))
        profile_runs = {
            str(trial.harness_profile): trial.run_summary.run_id
            for trial in ordered_trials
            if trial.run_summary is not None
        }
        resolved_baseline = baseline_profile or default_baseline_profile(profile_runs.keys())
        grouped_by_target = comparison_map_by_target_profile(profile_runs, baseline_profile=resolved_baseline)
        specs: list[tuple[str, str, tuple[ProfileRunComparison, ...]]] = []
        for trial in ordered_trials:
            if trial.run_summary is None:
                continue
            profile = str(trial.harness_profile)
            grouped: dict[str, list[ProfileRunComparison]] = {}
            for comparison in grouped_by_target.get(profile, ()):
                filename = self._comparison_filename(comparison.left_run_id, comparison.right_run_id)
                comparison_path = report.html_path.parent / filename
                if not comparison_path.exists():
                    continue
                grouped.setdefault(filename, []).append(comparison)
            for filename, comparisons in grouped.items():
                specs.append((profile, filename, tuple(comparisons)))
        return tuple(specs)

    def _comparison_button_label(self, comparisons: tuple[ProfileRunComparison, ...]) -> str:
        modes = {item.mode for item in comparisons}
        if len(modes) > 1:
            return "打开对比页面"
        mode = next(iter(modes), COMPARISON_MODE_UPLIFT)
        if mode == COMPARISON_MODE_FAIR:
            return "打开公平对比页面"
        return "打开抬升对比页面"

    def _comparison_buttons(
        self,
        report: StoredEvalReport,
        trials: Sequence[StoredEvalTrial],
        *,
        target_profile: str,
        baseline_profile: str,
    ) -> list[str]:
        return [
            self._button(filename, self._comparison_button_label(comparisons))
            for profile, filename, comparisons in self._comparison_link_specs(
                report,
                trials,
                baseline_profile=baseline_profile,
            )
            if profile == target_profile
        ]

    def _render_focus_trial_card(
        self,
        *,
        report: StoredEvalReport,
        trial: StoredEvalTrial,
        case_summary: Mapping[str, Any],
        baseline_profile: str,
        all_trials: Sequence[StoredEvalTrial],
        profile_uplift: Mapping[str, Any],
    ) -> str:
        summary = trial.run_summary
        if summary is None:
            return ""
        record = self._load_run_record(summary.run_id)
        feedback_items = self._feedback_items(record, summary)
        harness_items = build_harness_input_items(record)
        shared_items = self._summary_shared_task_items(case_summary) or build_harness_shared_items(record)
        extra_items = self._summary_profile_delivery_items(case_summary, trial.harness_profile) or build_harness_extra_items(record)
        response_items = build_model_response_items(record)
        profile_items = self._mapping(profile_uplift.get(trial.harness_profile))
        uplift_caption = '基线' if trial.harness_profile == baseline_profile else self._delta_ratio(profile_items.get('pass_rate_delta'))
        actions = [self._button(self._run_report_href(summary.run_id), '打开运行报告', primary=True)]
        actions.extend(
            self._comparison_buttons(
                report,
                all_trials,
                target_profile=trial.harness_profile,
                baseline_profile=baseline_profile,
            )
        )
        result_items = feedback_items[:3] if feedback_items else ('当前没有额外反馈。',)
        return ''.join(
            [
                '<article class="snapshot result-card">',
                '<div class="card-top">',
                f'<span class="badge">{escape(self._profile_label(trial.harness_profile))}</span>',
                f'<span class="badge badge-status-{escape(summary.status.value)}">{escape(self._status_label(summary.status.value))}</span>',
                '</div>',
                f'<h4>{escape(self._profile_label(trial.harness_profile))}</h4>',
                '<div class="facts">',
                f'<span>验证：{escape(self._verifier_label(summary.verifier_outcome))}</span>',
                f'<span>耗时：{escape(self._duration(summary.duration_ms))}</span>',
                f'<span>抬升：{escape(uplift_caption)}</span>',
                '</div>',
                '<h4>任务输出</h4>',
                self._render_task_output_box(record),
                '<h4>处理结果</h4>',
                self._list_block(result_items, empty_text='当前没有额外结果说明。'),
                '<details class="inline-details"><summary class="details-hint">查看细节</summary><div class="panel-body details-body">',
                '<h4>共同任务信息</h4>',
                self._list_block(shared_items, empty_text='当前没有共同任务信息。'),
                '<h4>本档额外交付</h4>',
                self._list_block(extra_items, empty_text='当前没有额外 harness 交付。'),
                '<h4>Harness 输入摘要</h4>',
                self._list_block(harness_items, empty_text='当前没有记录到 Harness 输入证据。'),
                '<h4>模型响应</h4>',
                self._list_block(response_items, empty_text='当前没有记录到模型响应证据。'),
                '<h4>改动文件</h4>',
                self._list_block(summary.changed_files, empty_text='当前没有生成文件改动。'),
                '<div class="actions">',
                ''.join(actions),
                '</div></div></details></article>',
            ]
        )

    def _render_task_output_box(self, record: StoredRunRecord | None) -> str:
        patch_diff = record.patch_diff if record is not None else None
        if not patch_diff:
            return self._empty('当前没有提取到显式任务输出。')
        extracted: list[str] = []
        for line in patch_diff.splitlines():
            if line.startswith(("diff --git", "index ", "--- ", "+++ ", "@@")):
                continue
            if line.startswith('+') and not line.startswith('+++'):
                extracted.append(line[1:])
        lines = extracted or patch_diff.splitlines()
        if len(lines) > 18:
            lines = lines[:18] + [f'... 另有 {len(lines) - 18} 行未展开']
        rendered_output = '\n'.join(lines).strip()
        return f'<pre>{escape(rendered_output)}</pre>'

    def _primary_eval_reports(self, eval_reports: Sequence[StoredEvalReport]) -> list[StoredEvalReport]:
        primary = [report for report in eval_reports if not getattr(report, "is_portal_live", False)]
        return primary or list(eval_reports)

    def _pick_focus_case(self, eval_reports: Sequence[StoredEvalReport]) -> tuple[StoredEvalReport, StoredEvalCase] | None:
        for report in self._primary_eval_reports(eval_reports):
            if not report.case_results:
                continue
            return report, report.case_results[0]
        return None

    def _dashboard_model_label(self, eval_reports: Sequence[StoredEvalReport]) -> str:
        focus = self._pick_focus_case(eval_reports)
        if focus is None:
            return '未知模型'
        _, case = focus
        return self._model_label_from_trials(case.trials)

    def _model_label_from_trials(self, trials: Sequence[StoredEvalTrial]) -> str:
        for trial in trials:
            if trial.run_summary is None:
                continue
            record = self._load_run_record(trial.run_summary.run_id)
            label = self._model_label_from_record(record)
            if label != '未知模型':
                return label
        return '未知模型'

    def _model_label_from_record(self, record: StoredRunRecord | None) -> str:
        if record is None:
            return '未知模型'
        for item in build_harness_input_items(record):
            if item.startswith('模型：'):
                return item.split('模型：', 1)[1]
        return '未知模型'

    def _load_task_brief(self, summary: Mapping[str, Any], fallback_case_id: str, trials: Sequence[StoredEvalTrial] = ()) -> tuple[str, str]:
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

    def _task_brief_from_trials(self, trials: Sequence[StoredEvalTrial], fallback_case_id: str) -> tuple[str, str]:
        for trial in trials:
            metadata = dict(trial.run_request_metadata) if isinstance(trial.run_request_metadata, Mapping) else {}
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

    def _task_brief_from_path(self, path: Path, fallback_case_id: str, *, description_key: str) -> tuple[str, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError):
            return fallback_case_id, ""
        description = payload.get(description_key) or payload.get("description") or ""
        return str(payload.get("title") or fallback_case_id), str(description)

    def _render_task_input_box(self, *, title: str, description: str, model_label: str, hint: str) -> str:
        task_text = title if not description else f'{title}\n\n{description}'
        return ''.join([
            '<div class="task-box">',
            '<div class="card-top">',
            '<span class="badge">用户任务</span>',
            f'<span class="muted">模型：{escape(model_label)}</span>',
            '</div>',
            f'<pre>{escape(task_text)}</pre>',
            f'<p class="muted">{escape(hint)}</p>',
            '</div>',
        ])

    def _render_case_delivery_proof(self, summary_mapping: Mapping[str, Any]) -> str:
        shared_items = self._summary_shared_task_items(summary_mapping)
        profile_cards = ''.join(
            self._render_profile_delivery_card(name, payload)
            for name, payload in self._summary_profile_matrix(summary_mapping).items()
        )
        delta_cards = ''.join(
            self._render_delta_summary_card(item)
            for item in self._summary_profile_deltas(summary_mapping)
        )
        parts: list[str] = []
        if shared_items:
            parts.extend([
                '<h4>共同任务信息</h4>',
                self._list_block(shared_items, empty_text='当前没有共同任务信息。'),
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
        return ''.join(parts)

    def _summary_shared_task_items(self, summary_mapping: Mapping[str, Any]) -> tuple[str, ...]:
        shared = self._mapping(summary_mapping.get('shared_task_information'))
        if not shared:
            return ()
        items = ['各运行都收到上面这条完全相同的任务正文。']
        editable = [str(item) for item in shared.get('editable_paths', ()) if str(item)]
        forbidden = [str(item) for item in shared.get('forbidden_paths', ()) if str(item)]
        changed = [str(item) for item in shared.get('expected_changed_files', ()) if str(item)]
        checks = [str(item) for item in shared.get('behavioral_checks', ()) if str(item)]
        verifier_steps = [str(item) for item in shared.get('required_verifier_steps', ()) if str(item)]
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
        if shared.get('response_contract'):
            items.append('各运行的输出格式要求相同：只能返回 JSON summary + writes。')
        return tuple(items)

    def _summary_profile_matrix(self, summary_mapping: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        matrix = summary_mapping.get('harness_delivery_matrix')
        return {
            str(name): self._mapping(payload)
            for name, payload in dict(matrix).items()
        } if isinstance(matrix, Mapping) else {}

    def _summary_profile_deltas(self, summary_mapping: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        raw = summary_mapping.get('profile_delta_summary')
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return ()
        return tuple(self._mapping(item) for item in raw if isinstance(item, Mapping))

    def _summary_profile_delivery_items(self, summary_mapping: Mapping[str, Any], profile: str) -> tuple[str, ...]:
        payload = self._summary_profile_matrix(summary_mapping).get(profile, {})
        items = [str(item) for item in payload.get('additional_delivery_items', ()) if str(item)]
        return tuple(self._localize_delivery_item(item) for item in items)

    def _render_profile_delivery_card(self, profile: str, payload: Mapping[str, Any]) -> str:
        items = self._summary_profile_delivery_items({'harness_delivery_matrix': {profile: payload}}, profile)
        return ''.join([
            '<article class="card">',
            f'<h4>{escape(self._profile_label(profile))}</h4>',
            self._list_block(items, empty_text='当前没有额外交付说明。'),
            '</article>',
        ])

    def _render_delta_summary_card(self, item: Mapping[str, Any]) -> str:
        from_profile = self._profile_label(str(item.get('from_profile', '?')))
        to_profile = self._profile_label(str(item.get('to_profile', '?')))
        lines = tuple(self._localize_delivery_item(str(line)) for line in item.get('summary_lines', ()) if str(line))
        return ''.join([
            '<article class="card">',
            f'<h4>{escape(from_profile)} -> {escape(to_profile)}</h4>',
            self._list_block(lines, empty_text='当前没有控制变量变化说明。'),
            '</article>',
        ])

    def _localize_delivery_item(self, text: str) -> str:
        normalized = ' '.join(str(text).split())
        if not normalized:
            return ''
        if normalized == 'The current run receives the same task title and description.':
            return '当前运行收到的是同一条用户任务标题和说明。'
        if normalized.startswith('Same editable paths: '):
            return '各运行可改范围相同：' + normalized.removeprefix('Same editable paths: ')
        if normalized.startswith('Same forbidden paths: '):
            return '各运行禁改范围相同：' + normalized.removeprefix('Same forbidden paths: ')
        if normalized.startswith('Same expected changed files: '):
            return '各运行目标改动文件相同：' + normalized.removeprefix('Same expected changed files: ')
        if normalized.startswith('Same behavioral checks: '):
            return '各运行行为检查相同：' + normalized.removeprefix('Same behavioral checks: ')
        if normalized.startswith('Same required verifier step names: '):
            return '各运行必过步骤名称相同：' + normalized.removeprefix('Same required verifier step names: ')
        if normalized == 'Same response contract: JSON only with summary and writes.':
            return '各运行输出格式相同：只能返回 JSON summary + writes。'
        if normalized.startswith('Extra harness material: repository tree only'):
            return normalized.replace('Extra harness material: repository tree only', '额外 harness 材料：只有仓库树')
        if normalized.startswith('Repository tree attached'):
            return normalized.replace('Repository tree attached', '附带仓库树')
        if normalized.startswith('Repository tree is enabled'):
            return normalized.replace('Repository tree is enabled for this profile, but the local repo preview is unavailable.', '这个档位会附带仓库树，但当前拿不到本地仓库预览。')
        if normalized.startswith('Repository context files: '):
            return '额外上下文文件：' + normalized.removeprefix('Repository context files: ')
        if normalized.startswith('Injected task inputs: '):
            return '额外任务输入：' + normalized.removeprefix('Injected task inputs: ')
        if normalized.startswith('Injected verifier steps: '):
            return '额外验收步骤：' + normalized.removeprefix('Injected verifier steps: ')
        if normalized.startswith('context files: '):
            return '上下文文件：' + normalized.removeprefix('context files: ')
        if normalized.startswith('context cap: '):
            return '上下文上限：' + normalized.removeprefix('context cap: ')
        if normalized.startswith('new task inputs: '):
            return '新增任务输入：' + normalized.removeprefix('new task inputs: ')
        if normalized.startswith('new verifier steps: '):
            return '新增验收步骤：' + normalized.removeprefix('new verifier steps: ')
        if normalized == 'No material delivery difference detected between these profiles.':
            return '这两个档位之间没有检测到实质性交付差异。'
        return normalized

    def _feedback_items(self, record: StoredRunRecord | None, summary: RunSummary) -> tuple[str, ...]:
        if record is not None:
            failure_summary = build_failure_summary(record)
            if failure_summary:
                return tuple(self._localize_feedback_message(item) for item in failure_summary)
        if summary.notes:
            return tuple(self._localize_feedback_message(item) for item in summary.notes)
        hint = pick_failure_hint(summary)
        return (self._localize_feedback_message(hint),) if hint else ()

    def _baseline_run_id(self, case: StoredEvalCase, baseline_profile: str) -> str | None:
        for trial in case.trials:
            if trial.harness_profile == baseline_profile and trial.run_summary is not None:
                return trial.run_summary.run_id
        return None

    def _comparison_href(self, report: StoredEvalReport, baseline_run_id: str | None, candidate_run_id: str) -> str | None:
        if baseline_run_id is None or baseline_run_id == candidate_run_id:
            return None
        filename = self._comparison_filename(baseline_run_id, candidate_run_id)
        comparison_path = report.html_path.parent / filename
        return filename if comparison_path.exists() else None

    def _comparison_filename(self, left_run_id: str, right_run_id: str) -> str:
        return f'compare-{self._safe_file_stem(left_run_id)}-vs-{self._safe_file_stem(right_run_id)}.html'

    def _sorted_recommended_eval_cases(self, eval_reports: Sequence[StoredEvalReport]) -> list[tuple[StoredEvalReport, StoredEvalCase, int, tuple[str, ...]]]:
        ranked: list[tuple[StoredEvalReport, StoredEvalCase, int, tuple[str, ...]]] = []
        for report in eval_reports:
            for case in report.case_results:
                score = self._recommendation_score(case.summary)
                reasons = self._recommendation_reasons(case.summary)
                if score is None or not reasons:
                    continue
                ranked.append((report, case, score, reasons))
        return sorted(ranked, key=lambda item: (-item[2], item[0].suite_id, item[1].case_id))

    def _aggregate_profile_failures(self, eval_reports: Sequence[StoredEvalReport]) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {'failed_trials': 0, 'reasons': defaultdict(int)})
        for report in eval_reports:
            failure_view = self._mapping(report.comparison_views.get('profile_failure_summary'))
            for profile_name, item in failure_view.items():
                item_mapping = self._mapping(item)
                buckets[profile_name]['failed_trials'] += int(item_mapping.get('failed_trials', 0))
                for reason_item in item_mapping.get('top_reasons', ()):
                    reason_mapping = self._mapping(reason_item)
                    reason = str(reason_mapping.get('reason', '')).strip()
                    if reason:
                        buckets[profile_name]['reasons'][self._localize_feedback_message(reason)] += int(reason_mapping.get('count', 0))
        result: dict[str, dict[str, Any]] = {}
        for profile_name, item in sorted(buckets.items()):
            top_reasons = sorted(item['reasons'].items(), key=lambda pair: (-pair[1], pair[0]))[:3]
            result[profile_name] = {'failed_trials': item['failed_trials'], 'top_reasons': top_reasons}
        return result

    def _render_failure_profile_card(self, profile_name: str, item: Mapping[str, Any]) -> str:
        reasons = ''.join(f'<li>{escape(reason)} · {count}</li>' for reason, count in item.get('top_reasons', ()))
        return ''.join([
            '<article class="card">',
            '<div class="card-top">',
            f'<span class="badge">{escape(self._profile_label(profile_name))}</span>',
            f'<span class="muted">失败试次：{int(item.get("failed_trials", 0))}</span>',
            '</div>',
            '<h4>常见失败原因</h4>',
            f'<ul class="reason-list">{reasons}</ul>' if reasons else self._empty('当前没有聚合失败原因。'),
            '</article>',
        ])

    def _recommendation_score(self, summary: Mapping[str, Any] | object) -> int | None:
        if not isinstance(summary, Mapping):
            return None
        value = summary.get('recommendation_score')
        return None if value is None else int(value)

    def _recommendation_reasons(self, summary: Mapping[str, Any] | object) -> tuple[str, ...]:
        if not isinstance(summary, Mapping):
            return ()
        return tuple(localize_harness_message(str(item)) for item in summary.get('recommendation_reasons', ()) if str(item))

    def _load_run_record(self, run_id: str) -> StoredRunRecord | None:
        if self._run_record_loader is None:
            return None
        try:
            return self._run_record_loader(run_id)
        except FileNotFoundError:
            return None

    def _run_report_href(self, run_id: str) -> str:
        return (Path('..') / 'runs' / run_id / 'report.html').as_posix()

    def _profile_sort_key(self, profile_name: str, baseline_profile: str) -> tuple[int, str]:
        order: list[str] = []
        for item in (baseline_profile, 'current', 'custom'):
            if item and item not in order:
                order.append(item)
        return (order.index(profile_name), profile_name) if profile_name in order else (len(order), profile_name)

    def _profile_label(self, profile_name: str) -> str:
        return {'current': 'Current 当前配置', 'custom': 'Custom 自定义配置'}.get(profile_name, profile_name)

    def _status_label(self, status: str) -> str:
        return {'succeeded': '成功', 'failed': '失败', 'error': '错误', 'running': '运行中', 'pending': '等待中', 'skipped': '已跳过'}.get(status, status)

    def _verifier_label(self, verifier: str | None) -> str:
        return {'passed': '通过', 'failed': '未通过', 'error': '错误', 'skipped': '已跳过', 'not_run': '未执行', None: '未执行'}.get(verifier, verifier or '未执行')

    def _localize_feedback_message(self, text: str) -> str:
        normalized = ' '.join(str(text).split())
        if not normalized:
            return ''
        if normalized.startswith('Direct error: '):
            return '直接错误：' + normalized.removeprefix('Direct error: ')
        if normalized.startswith('Failed check: '):
            return '失败检查：' + normalized.removeprefix('Failed check: ')
        if normalized.startswith('Run note: '):
            return '运行备注：' + normalized.removeprefix('Run note: ')
        return normalized

    def _mapping(self, value: object) -> Mapping[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    def _card_grid(self, cards: Sequence[str] | Any) -> str:
        rendered = ''.join(cards)
        return f'<div class="grid">{rendered}</div>' if rendered else ''

    def _list_block(self, items: Sequence[str], *, empty_text: str) -> str:
        if not items:
            return self._empty(empty_text)
        return '<ul class="stack-list">' + ''.join(f'<li>{escape(item)}</li>' for item in items) + '</ul>'

    def _button(self, href: str, label: str, *, primary: bool = False) -> str:
        class_name = 'button button-primary' if primary else 'button'
        return f'<a class="{class_name}" href="{escape(href)}">{escape(label)}</a>'

    def _join_values(self, values: Sequence[object]) -> str:
        items = [str(value) for value in values if str(value)]
        return ', '.join(items) if items else '无'

    def _ratio(self, value: object) -> str:
        return 'n/a' if value is None else f'{float(value):.1%}'

    def _delta_ratio(self, value: object) -> str:
        if value is None:
            return 'n/a'
        points = float(value) * 100
        sign = '+' if points > 0 else ''
        return f'{sign}{points:.1f} pts'

    def _duration(self, value: object) -> str:
        if value is None:
            return 'n/a'
        milliseconds = int(round(float(value)))
        return f'{milliseconds} ms' if milliseconds < 1000 else f'{milliseconds / 1000:.2f} s'

    def _report_uses_profile_matrix(self, report: StoredEvalReport) -> bool:
        profiles = {
            str(trial.harness_profile)
            for case in report.case_results
            for trial in case.trials
            if trial.run_summary is not None
        }
        supported_profiles = {'current', 'custom'}
        return len(profiles) > 1 and bool(profiles & supported_profiles)

    def _safe_file_stem(self, value: str) -> str:
        sanitized = ''.join(char if char.isalnum() or char in '._-' else '-' for char in value).strip('-')
        return sanitized or 'report'

    def _empty(self, text: str) -> str:
        return f'<div class="empty">{escape(text)}</div>'

    def _hero(self, *, title: str, subtitle: str, badges: Sequence[str]) -> str:
        badge_html = ''.join(f'<span class="badge badge-hero">{escape(badge)}</span>' for badge in badges if badge)
        return ''.join(['<header class="hero"><div class="eyebrow">同模型 Harness</div>', f'<h1>{escape(title)}</h1>', f'<p>{escape(subtitle)}</p>', f'<div class="hero-badges">{badge_html}</div>' if badge_html else '', '</header>'])

    def _panel(self, title: str, content: str, *, subtitle: str = '', section_id: str = '') -> str:
        subtitle_html = f'<p class="subtitle">{escape(subtitle)}</p>' if subtitle else ''
        id_attr = f' id="{escape(section_id)}"' if section_id else ''
        return f'<section{id_attr} class="panel"><div class="panel-head"><h2>{escape(title)}</h2>{subtitle_html}</div><div class="panel-body">{content}</div></section>'

    def _details_panel(self, title: str, content: str, *, subtitle: str = '', summary: str = '', section_id: str = '') -> str:
        subtitle_html = f'<p class="subtitle">{escape(subtitle)}</p>' if subtitle else ''
        hint = summary or '展开更多'
        id_attr = f' id="{escape(section_id)}"' if section_id else ''
        return ''.join([f'<section{id_attr} class="panel details-panel"><details><summary class="details-summary"><div class="details-summary-copy"><h2>{escape(title)}</h2>{subtitle_html}</div><span class="details-hint">{escape(hint)}</span></summary><div class="panel-body details-body">{content}</div></details></section>'])

    def _document(self, *, title: str, body: str) -> str:
        return ''.join(['<!doctype html>', '<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">', f'<title>{escape(title)}</title>', '<style>:root{--panel:rgba(255,255,255,.82);--border:rgba(20,33,43,.12);--ink:#14212b;--muted:#5e6a73;--accent:#0f766e;--warm:#c46c2d;--danger:#b42318;--ok:#1f7a1f;--shadow:0 18px 50px rgba(20,33,43,.12)}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at top left, rgba(196,108,45,.18), transparent 32%),radial-gradient(circle at top right, rgba(15,118,110,.18), transparent 34%),linear-gradient(180deg,#f8f3ea 0%,#eef2ef 100%);font-family:"Aptos","Trebuchet MS",sans-serif}h1,h2,h3,h4,h5{font-family:Georgia,"Times New Roman",serif;margin:0}a{color:inherit;text-decoration:none}pre{margin:0;white-space:pre-wrap;word-break:break-word;background:rgba(20,33,43,.06);border-radius:14px;padding:12px;font-family:"Cascadia Mono",Consolas,monospace}.page{max-width:1080px;margin:0 auto;padding:28px 20px 40px}.hero,.panel,.card,.snapshot{background:var(--panel);border:1px solid var(--border);border-radius:24px;box-shadow:var(--shadow)}.hero{padding:32px;background:linear-gradient(135deg, rgba(20,33,43,.98), rgba(15,118,110,.93));color:#fbfaf7}.eyebrow,.muted,.subtitle{color:var(--muted)}.eyebrow{letter-spacing:.18em;text-transform:uppercase;font-size:.75rem;color:rgba(251,250,247,.72)}.hero p{max-width:760px;color:rgba(251,250,247,.8)}.hero-badges,.facts,.actions,.card-top{display:flex;flex-wrap:wrap;gap:10px}.panel{padding:18px;margin-top:18px}.panel-head{display:flex;flex-direction:column;gap:6px;margin-bottom:16px}.panel-body{display:flex;flex-direction:column;gap:14px}.details-panel{padding:0}.details-panel details{padding:18px}.details-summary{list-style:none;display:flex;align-items:flex-start;justify-content:space-between;gap:16px;cursor:pointer}.details-summary::-webkit-details-marker{display:none}.details-summary-copy{display:flex;flex-direction:column;gap:6px}.details-hint{display:inline-flex;align-items:center;justify-content:center;padding:8px 12px;border-radius:999px;border:1px solid rgba(20,33,43,.12);color:var(--muted)}.details-body{padding-top:16px}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:6px 12px;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;background:rgba(15,118,110,.12);color:var(--accent)}.badge-hero{background:rgba(255,255,255,.14);color:#fbfaf7}.badge-status-succeeded,.badge-status-passed{background:rgba(31,122,31,.12);color:var(--ok)}.badge-status-failed,.badge-status-error{background:rgba(180,35,24,.12);color:var(--danger)}.badge-status-running,.badge-status-pending,.badge-status-skipped{background:rgba(196,108,45,.12);color:var(--warm)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}.card,.snapshot{padding:18px}.facts,.actions{gap:10px}.reason-list,.stack-list{margin:14px 0 0;padding-left:18px;display:flex;flex-direction:column;gap:8px}.task-box{display:flex;flex-direction:column;gap:12px}.inline-details{margin-top:14px}.inline-details summary{cursor:pointer}.empty{border:1px dashed rgba(20,33,43,.18);border-radius:18px;padding:18px;color:var(--muted);background:rgba(255,255,255,.5)}@media(max-width:640px){.page{padding:16px 12px 28px}.hero{padding:24px}.details-summary{flex-direction:column}.grid{grid-template-columns:1fr}}</style>', f'</head><body>{body}</body></html>'])
