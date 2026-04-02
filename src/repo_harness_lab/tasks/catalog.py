from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from repo_harness_lab.domain.task_spec import TaskDifficulty, TaskSelectionTier, TaskSpec, TaskType
from repo_harness_lab.tasks.loader import JsonTaskLoader


@dataclass(frozen=True, slots=True)
class TaskCatalogEntry:
    path: Path
    task: TaskSpec


@dataclass(frozen=True, slots=True)
class TaskRecommendation:
    entry: TaskCatalogEntry
    score: int
    reasons: tuple[str, ...]
    matched_preferred_tags: tuple[str, ...] = ()
    matched_preferred_signals: tuple[str, ...] = ()


class FileSystemTaskCatalog:
    def __init__(self, loader: JsonTaskLoader | None = None) -> None:
        self.loader = loader or JsonTaskLoader()

    def scan(self, source: str | Path) -> tuple[TaskCatalogEntry, ...]:
        root = Path(source)
        if root.is_file():
            return (TaskCatalogEntry(path=root.resolve(), task=self.loader.load(root)),)

        entries: list[TaskCatalogEntry] = []
        for path in sorted(root.rglob('*.json')):
            task = self.loader.load(path)
            entries.append(TaskCatalogEntry(path=path.resolve(), task=task))
        return tuple(entries)

    def select(
        self,
        source: str | Path,
        *,
        tier: TaskSelectionTier | None = None,
        difficulty: TaskDifficulty | None = None,
        task_type: TaskType | None = None,
        tags: Sequence[str] = (),
        harness_signals: Sequence[str] = (),
        limit: int | None = None,
    ) -> tuple[TaskCatalogEntry, ...]:
        normalized_tags = {item.strip() for item in tags if item.strip()}
        normalized_signals = {item.strip() for item in harness_signals if item.strip()}
        selected: list[TaskCatalogEntry] = []

        for entry in self.scan(source):
            benchmark = entry.task.benchmark_metadata
            if tier is not None and benchmark.tier is not tier:
                continue
            if difficulty is not None and benchmark.difficulty is not difficulty:
                continue
            if task_type is not None and entry.task.task_type is not task_type:
                continue
            if normalized_tags and not normalized_tags.issubset(set(benchmark.tags)):
                continue
            if normalized_signals and not normalized_signals.issubset(set(benchmark.harness_signals)):
                continue
            selected.append(entry)
            if limit is not None and len(selected) >= limit:
                break
        return tuple(selected)

    def recommend(
        self,
        source: str | Path,
        *,
        tier: TaskSelectionTier | None = None,
        difficulty: TaskDifficulty | None = None,
        task_type: TaskType | None = None,
        tags: Sequence[str] = (),
        harness_signals: Sequence[str] = (),
        prefer_tags: Sequence[str] = (),
        prefer_harness_signals: Sequence[str] = (),
        limit: int | None = None,
    ) -> tuple[TaskRecommendation, ...]:
        preferred_tags = tuple(sorted({item.strip() for item in prefer_tags if item.strip()}))
        preferred_signals = tuple(sorted({item.strip() for item in prefer_harness_signals if item.strip()}))
        entries = self.select(
            source,
            tier=tier,
            difficulty=difficulty,
            task_type=task_type,
            tags=tags,
            harness_signals=harness_signals,
        )
        recommendations = sorted(
            (
                build_task_recommendation(
                    entry,
                    prefer_tags=preferred_tags,
                    prefer_harness_signals=preferred_signals,
                )
                for entry in entries
            ),
            key=lambda item: (-item.score, item.entry.task.task_id, str(item.entry.path)),
        )
        if limit is not None:
            recommendations = recommendations[:limit]
        return tuple(recommendations)



def serialize_catalog_entry(entry: TaskCatalogEntry) -> dict[str, object]:
    benchmark = entry.task.benchmark_metadata
    return {
        'path': str(entry.path),
        'task_id': entry.task.task_id,
        'title': entry.task.title,
        'task_type': entry.task.task_type.value,
        'tier': benchmark.tier.value,
        'difficulty': benchmark.difficulty.value,
        'tags': list(benchmark.tags),
        'harness_signals': list(benchmark.harness_signals),
    }



def serialize_task_recommendation(recommendation: TaskRecommendation) -> dict[str, object]:
    payload = serialize_catalog_entry(recommendation.entry)
    payload.update(
        {
            'recommendation_score': recommendation.score,
            'recommendation_reasons': list(recommendation.reasons),
            'matched_preferred_tags': list(recommendation.matched_preferred_tags),
            'matched_preferred_signals': list(recommendation.matched_preferred_signals),
        }
    )
    return payload


def build_task_recommendation(
    entry: TaskCatalogEntry,
    *,
    prefer_tags: Sequence[str] = (),
    prefer_harness_signals: Sequence[str] = (),
) -> TaskRecommendation:
    preferred_tags = tuple(sorted({item.strip() for item in prefer_tags if item.strip()}))
    preferred_signals = tuple(sorted({item.strip() for item in prefer_harness_signals if item.strip()}))
    return _recommend_entry(
        entry,
        preferred_tags=preferred_tags,
        preferred_signals=preferred_signals,
    )


_TIER_SCORES = {
    TaskSelectionTier.CURATED: 40,
    TaskSelectionTier.ROLLING: 26,
    TaskSelectionTier.OPEN: 14,
}

_DIFFICULTY_SCORES = {
    TaskDifficulty.MEDIUM: 18,
    TaskDifficulty.HARD: 14,
    TaskDifficulty.EASY: 8,
}



def _recommend_entry(
    entry: TaskCatalogEntry,
    *,
    preferred_tags: Sequence[str],
    preferred_signals: Sequence[str],
) -> TaskRecommendation:
    task = entry.task
    benchmark = task.benchmark_metadata
    score = _TIER_SCORES[benchmark.tier] + _DIFFICULTY_SCORES[benchmark.difficulty]
    reasons = [
        _tier_reason(benchmark.tier),
        _difficulty_reason(benchmark.difficulty),
    ]

    task_signals = tuple(sorted(set(benchmark.harness_signals)))
    task_tags = tuple(sorted(set(benchmark.tags)))
    matched_signals = tuple(signal for signal in preferred_signals if signal in task_signals)
    matched_tags = tuple(tag for tag in preferred_tags if tag in task_tags)

    if task_signals:
        score += min(len(task_signals) * 6, 18)
        reasons.append(f"declares harness signals: {', '.join(task_signals)}")
    else:
        reasons.append('no harness signals declared, so uplift explanations will be weaker')

    if matched_signals:
        score += len(matched_signals) * 10
        reasons.append(f"matches preferred signals: {', '.join(matched_signals)}")

    if matched_tags:
        score += len(matched_tags) * 6
        reasons.append(f"matches preferred tags: {', '.join(matched_tags)}")

    if not task.inputs.is_empty:
        score += 4
        reasons.append('includes task inputs that can benefit from stronger context packing')

    if task.verifier_plan.steps:
        score += 8
        reasons.append('has deterministic verifier steps, so pass and fail stay explainable')

    editable_surface = max(len(task.constraints.editable_paths), len(task.success_criteria.changed_files))
    if editable_surface >= 2:
        score += 4
        reasons.append('touches multiple files or paths, which is useful for showing context-management uplift')

    if benchmark.notes:
        score += min(len(benchmark.notes), 2)

    return TaskRecommendation(
        entry=entry,
        score=score,
        reasons=tuple(reasons[:6]),
        matched_preferred_tags=matched_tags,
        matched_preferred_signals=matched_signals,
    )



def _tier_reason(tier: TaskSelectionTier) -> str:
    if tier is TaskSelectionTier.CURATED:
        return 'curated benchmark, easier to compare repeated harness runs'
    if tier is TaskSelectionTier.ROLLING:
        return 'rolling benchmark, reusable without locking users into a fixed pool'
    return 'open task, still runnable even when it is not part of the curated pool'



def _difficulty_reason(difficulty: TaskDifficulty) -> str:
    if difficulty is TaskDifficulty.MEDIUM:
        return 'medium difficulty usually shows harness differences without becoming brittle'
    if difficulty is TaskDifficulty.HARD:
        return 'hard difficulty can amplify context and verifier advantages'
    return 'easy difficulty is useful for smoke checks but usually shows less uplift'