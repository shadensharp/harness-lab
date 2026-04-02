from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from repo_harness_lab.storage.run_store import StoredEvalReport


@dataclass(frozen=True, slots=True)
class RecommendationGuide:
    prefer_signals: tuple[str, ...] = ()
    prefer_tags: tuple[str, ...] = ()
    top_reasons: tuple[str, ...] = ()
    list_command: str = ''
    recommend_command: str = ''
    preview_intake_command: str = ''
    run_intake_eval_command: str = ''



def build_recommendation_guide(
    eval_reports: Sequence[StoredEvalReport],
    *,
    task_source: str = '<task-dir>',
    list_limit: int = 20,
    recommend_limit: int = 10,
) -> RecommendationGuide:
    ranked = _ranked_case_summaries(eval_reports)
    prefer_signals = _ordered_unique_values(ranked, 'harness_signals', limit=3)
    prefer_tags = _ordered_unique_values(ranked, 'task_tags', limit=2)
    top_reasons = _ordered_unique_values(ranked, 'recommendation_reasons', limit=4)
    return RecommendationGuide(
        prefer_signals=prefer_signals,
        prefer_tags=prefer_tags,
        top_reasons=top_reasons,
        list_command=_build_list_command(task_source, limit=list_limit),
        recommend_command=_build_recommend_command(
            task_source,
            prefer_signals=prefer_signals,
            prefer_tags=prefer_tags,
            limit=recommend_limit,
        ),
        preview_intake_command=_build_preview_intake_command(),
        run_intake_eval_command=_build_run_intake_eval_command(),
    )



def _ranked_case_summaries(eval_reports: Sequence[StoredEvalReport]) -> tuple[Mapping[str, Any], ...]:
    ranked: list[tuple[int, str, str, Mapping[str, Any]]] = []
    for report in eval_reports:
        for case in report.case_results:
            summary = case.summary if isinstance(case.summary, Mapping) else {}
            score = _recommendation_score(summary)
            reasons = _sequence(summary, 'recommendation_reasons')
            if score is None or not reasons:
                continue
            ranked.append((score, report.suite_id, case.case_id, summary))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return tuple(item[3] for item in ranked)



def _ordered_unique_values(
    summaries: Sequence[Mapping[str, Any]],
    key: str,
    *,
    limit: int,
) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for summary in summaries:
        for item in _sequence(summary, key):
            if item in seen:
                continue
            seen.add(item)
            values.append(item)
            if len(values) >= limit:
                return tuple(values)
    return tuple(values)



def _sequence(summary: Mapping[str, Any], key: str) -> tuple[str, ...]:
    if not isinstance(summary, Mapping):
        return ()
    return tuple(str(item) for item in summary.get(key, ()) if str(item))



def _recommendation_score(summary: Mapping[str, Any]) -> int | None:
    if not isinstance(summary, Mapping):
        return None
    value = summary.get('recommendation_score')
    return None if value is None else int(value)



def _build_list_command(task_source: str, *, limit: int) -> str:
    return f'python -m repo_harness_lab.cli.main list-task-pool {task_source} --limit {limit}'



def _build_recommend_command(
    task_source: str,
    *,
    prefer_signals: Sequence[str],
    prefer_tags: Sequence[str],
    limit: int,
) -> str:
    parts = ['python', '-m', 'repo_harness_lab.cli.main', 'recommend-tasks', task_source]
    for signal in prefer_signals:
        parts.extend(['--prefer-signal', signal])
    for tag in prefer_tags:
        parts.extend(['--prefer-tag', tag])
    parts.extend(['--limit', str(limit)])
    return ' '.join(parts)



def _build_preview_intake_command() -> str:
    return 'python -m repo_harness_lab.cli.main preview-intake <intake-json> --format both'



def _build_run_intake_eval_command() -> str:
    return (
        'python -m repo_harness_lab.cli.main run-intake-eval '
        '<intake-json> --provider <provider> --model <model> --api-key-env <API_KEY_ENV>'
    )
