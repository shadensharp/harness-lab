from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from repo_harness_lab.domain.task_spec import HarnessProfile

COMPARISON_MODE_UPLIFT = "uplift"
COMPARISON_MODE_FAIR = "fair"

_KNOWN_PROFILE_ORDER = (
    HarnessProfile.CURRENT.value,
    HarnessProfile.CUSTOM.value,
)


@dataclass(frozen=True, slots=True)
class ProfileRunComparison:
    mode: str
    left_profile: str
    right_profile: str
    left_run_id: str
    right_run_id: str


def default_baseline_profile(profile_names: Iterable[str]) -> str:
    ordered = ordered_profiles(profile_names)
    if not ordered:
        return HarnessProfile.CUSTOM.value
    if HarnessProfile.CURRENT.value in ordered:
        return HarnessProfile.CURRENT.value
    return ordered[0]


def ordered_profiles(profile_names: Iterable[str], *, baseline_profile: str | None = None) -> tuple[str, ...]:
    available = {str(item) for item in profile_names if str(item)}
    if not available:
        return ()

    ordered: list[str] = []
    seen: set[str] = set()
    preferred = (
        *(((baseline_profile or "").strip(),) if baseline_profile else ()),
        *_KNOWN_PROFILE_ORDER,
        *sorted(available),
    )
    for item in preferred:
        text = str(item).strip()
        if not text or text not in available or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered)


def build_profile_run_comparisons(
    profile_runs: Mapping[str, str],
    *,
    baseline_profile: str | None = None,
) -> tuple[ProfileRunComparison, ...]:
    normalized = {
        str(profile).strip(): str(run_id).strip()
        for profile, run_id in profile_runs.items()
        if str(profile).strip() and str(run_id).strip()
    }
    if not normalized:
        return ()

    resolved_baseline = baseline_profile or default_baseline_profile(normalized)
    ordered = ordered_profiles(normalized, baseline_profile=resolved_baseline)
    if resolved_baseline not in normalized or resolved_baseline not in ordered:
        resolved_baseline = default_baseline_profile(normalized)
        ordered = ordered_profiles(normalized, baseline_profile=resolved_baseline)
    if resolved_baseline not in normalized or not ordered:
        return ()

    comparisons: list[ProfileRunComparison] = []
    baseline_run_id = normalized[resolved_baseline]
    for profile in ordered:
        if profile == resolved_baseline:
            continue
        comparisons.append(
            ProfileRunComparison(
                mode=COMPARISON_MODE_UPLIFT,
                left_profile=resolved_baseline,
                right_profile=profile,
                left_run_id=baseline_run_id,
                right_run_id=normalized[profile],
            )
        )

    for index in range(1, len(ordered)):
        left_profile = ordered[index - 1]
        right_profile = ordered[index]
        comparisons.append(
            ProfileRunComparison(
                mode=COMPARISON_MODE_FAIR,
                left_profile=left_profile,
                right_profile=right_profile,
                left_run_id=normalized[left_profile],
                right_run_id=normalized[right_profile],
            )
        )
    return tuple(comparisons)


def comparison_map_by_target_profile(
    profile_runs: Mapping[str, str],
    *,
    baseline_profile: str | None = None,
) -> dict[str, tuple[ProfileRunComparison, ...]]:
    grouped: dict[str, list[ProfileRunComparison]] = {}
    for item in build_profile_run_comparisons(profile_runs, baseline_profile=baseline_profile):
        grouped.setdefault(item.right_profile, []).append(item)
    return {profile: tuple(items) for profile, items in grouped.items()}
