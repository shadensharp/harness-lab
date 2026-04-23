from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Callable, Mapping
import json

from repo_harness_lab.domain.failure_analysis_models import (
    FailureAnalysisItem,
    FailureAnalysisProfileReport,
    FailureAnalysisReport,
)
from repo_harness_lab.domain.official_benchmark_models import (
    OfficialBenchmarkEvaluationReport,
    OfficialBenchmarkProfileReport,
)
from repo_harness_lab.domain.trace_models import EventType
from repo_harness_lab.storage.run_store import StoredEvalReport, StoredRunRecord
from repo_harness_lab.tasks.loader import JsonTaskLoader

LABEL_ENV = "\u73af\u5883\u5931\u8d25"
LABEL_PREP = "\u51c6\u5907\u5931\u8d25"
LABEL_TIMEOUT = "\u8d85\u65f6"
LABEL_CRASH = "\u8fd0\u884c\u5d29\u6e83"
LABEL_NO_PATCH = "\u6ca1\u6709\u4ea7\u51fa\u4fee\u6539"
LABEL_SCOPE = "\u4fee\u6539\u8d8a\u754c"
LABEL_INVALID_PATCH = "\u8865\u4e01\u65e0\u6548"
LABEL_UNRESOLVED = "\u76ee\u6807\u672a\u4fee\u590d"
LABEL_REGRESSION = "\u5f15\u5165\u56de\u5f52"
LABEL_PARTIAL = "\u90e8\u5206\u4fee\u590d"

CAUSE_ENV = "\u73af\u5883\u548c\u9898\u76ee\u8981\u6c42\u4e0d\u4e00\u81f4"
CAUSE_PREP = "\u524d\u7f6e\u51c6\u5907\u6b65\u9aa4\u4e0d\u5b8c\u6574"
CAUSE_TIMEOUT = "\u6267\u884c\u65f6\u95f4\u4e0d\u591f"
CAUSE_CRASH = "\u8fd0\u884c\u6d41\u7a0b\u5f02\u5e38\u9000\u51fa"
CAUSE_LOCATE = "\u6ca1\u627e\u5230\u6b63\u786e\u6587\u4ef6"
CAUSE_CONTEXT = "\u4e0a\u4e0b\u6587\u4fe1\u606f\u4e0d\u591f"
CAUSE_TEST = "\u6ca1\u610f\u8bc6\u5230\u6d4b\u8bd5\u8981\u6c42"
CAUSE_UNDERSTAND = "\u7406\u89e3\u9519\u4e86\u9898\u610f"
CAUSE_CONTRACT = "\u8f93\u51fa\u7ed3\u679c\u4e0d\u6ee1\u8db3\u8865\u4e01\u7ea6\u675f"
CAUSE_REGRESSION = "\u6539\u52a8\u8fc7\u5ea6\u4f24\u5230\u522b\u5904"
CAUSE_PARTIAL = "\u6539\u52a8\u592a\u4fdd\u5b88"
CAUSE_UNKNOWN = "\u539f\u56e0\u672a\u77e5"

CONF_HIGH = "\u9ad8"
CONF_MEDIUM = "\u4e2d"
CONF_LOW = "\u4f4e"

STAGE_PREP = "\u51c6\u5907"
STAGE_EXEC = "\u6267\u884c"
STAGE_EDIT = "\u4fee\u6539"
STAGE_OFFICIAL = "\u5b98\u65b9\u8bc4\u6d4b"


def analyze_official_failures(
    *,
    official_report: OfficialBenchmarkEvaluationReport,
    eval_report: StoredEvalReport,
    run_record_loader: Callable[[str], StoredRunRecord],
    task_loader: JsonTaskLoader | None = None,
) -> FailureAnalysisReport:
    resolved_task_loader = task_loader or JsonTaskLoader()
    trial_index, task_path_index = _build_eval_indexes(eval_report)
    label_counts: Counter[str] = Counter()
    cause_counts: Counter[str] = Counter()
    profile_reports: list[FailureAnalysisProfileReport] = []

    for profile_report in official_report.profile_reports:
        failed_ids = tuple(
            dict.fromkeys(
                (
                    *profile_report.error_ids,
                    *profile_report.unresolved_ids,
                    *profile_report.empty_patch_ids,
                    *profile_report.incomplete_ids,
                )
            )
        )
        instance_result_map = _load_instance_result_map(profile_report)
        items: list[FailureAnalysisItem] = []
        profile_label_counts: Counter[str] = Counter()
        profile_cause_counts: Counter[str] = Counter()

        for instance_id in failed_ids:
            trial = trial_index.get((profile_report.harness_profile, instance_id))
            task = None
            task_path = task_path_index.get(instance_id)
            if task_path:
                try:
                    task = resolved_task_loader.load(task_path)
                except Exception:
                    task = None
            run_summary = None
            record = None
            if trial is not None and trial.run_summary is not None:
                run_summary = trial.run_summary
                try:
                    record = run_record_loader(run_summary.run_id)
                except FileNotFoundError:
                    record = None
            if instance_id in profile_report.error_ids:
                official_status = 'error'
            elif instance_id in profile_report.empty_patch_ids:
                official_status = 'empty_patch'
            elif instance_id in profile_report.incomplete_ids:
                official_status = 'incomplete'
            else:
                official_status = 'unresolved'
            official_payload = instance_result_map.get(instance_id, {})
            item = _analyze_failed_instance(
                instance_id=instance_id,
                harness_profile=profile_report.harness_profile,
                official_status=official_status,
                official_payload=official_payload,
                run_summary=run_summary,
                record=record,
                task=task,
            )
            items.append(item)
            profile_label_counts[item.main_label] += 1
            profile_cause_counts[item.probable_cause] += 1
            label_counts[item.main_label] += 1
            cause_counts[item.probable_cause] += 1

        profile_reports.append(
            FailureAnalysisProfileReport(
                harness_profile=profile_report.harness_profile,
                failed_instances=len(items),
                label_counts=dict(sorted(profile_label_counts.items())),
                probable_cause_counts=dict(sorted(profile_cause_counts.items())),
                items=tuple(items),
            )
        )

    return FailureAnalysisReport(
        benchmark_kind=official_report.benchmark_kind,
        source_report_id=official_report.source_report_id,
        dataset_name=official_report.dataset_name,
        notes=(
            "\u4e3b\u6807\u7b7e\u6309\u56fa\u5b9a\u4f18\u5148\u7ea7\u5224\u5b9a\uff1a\u73af\u5883/\u51c6\u5907 -> \u6267\u884c -> \u4fee\u6539\u7ed3\u679c -> \u5b98\u65b9\u8bc4\u6d4b",
            "\u6700\u53ef\u80fd\u539f\u56e0\u662f\u63a8\u6d4b\uff0c\u4e0d\u7b49\u4e8e\u5df2\u8bc1\u660e\u7684\u6839\u56e0",
        ),
        total_failed_instances=sum(item.failed_instances for item in profile_reports),
        label_counts=dict(sorted(label_counts.items())),
        probable_cause_counts=dict(sorted(cause_counts.items())),
        profile_reports=tuple(profile_reports),
    )


def _build_eval_indexes(eval_report: StoredEvalReport) -> tuple[dict[tuple[str, str], object], dict[str, str]]:
    trial_index: dict[tuple[str, str], object] = {}
    task_path_index: dict[str, str] = {}
    for case in eval_report.case_results:
        task_spec_ref = str(case.summary.get('task_spec_ref') or '').strip() if isinstance(case.summary, Mapping) else ''
        if task_spec_ref:
            task_path_index[case.case_id] = task_spec_ref
        for trial in case.trials:
            instance_id = case.case_id
            if trial.run_summary is not None:
                metadata = dict(trial.run_summary.metadata) if isinstance(trial.run_summary.metadata, Mapping) else {}
                benchmark_context = dict(metadata.get('benchmark_context', {})) if isinstance(metadata.get('benchmark_context'), Mapping) else {}
                instance_id = str(benchmark_context.get('instance_id') or case.case_id)
            trial_index[(trial.harness_profile, instance_id)] = trial
    return trial_index, task_path_index


def _load_instance_result_map(profile_report: OfficialBenchmarkProfileReport) -> dict[str, dict[str, object]]:
    path_text = str(profile_report.instance_results_path or '').strip()
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        return {}
    items: dict[str, dict[str, object]] = {}
    for raw_line in path.read_text(encoding='utf8').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, Mapping):
            continue
        instance_id = str(payload.get('instance_id', '')).strip()
        if instance_id:
            items[instance_id] = dict(payload)
    return items


def _analyze_failed_instance(
    *,
    instance_id: str,
    harness_profile: str,
    official_status: str,
    official_payload: Mapping[str, object],
    run_summary,
    record: StoredRunRecord | None,
    task,
) -> FailureAnalysisItem:
    notes = tuple(run_summary.notes) if run_summary is not None else ()
    note_text = ' | '.join(str(item) for item in notes).lower()
    changed_files = tuple(run_summary.changed_files) if run_summary is not None else ()
    patch_text = (record.patch_diff or '') if record is not None and record.patch_diff is not None else ''
    request_payload = _latest_model_request_payload(record)
    context_file_count = _int(request_payload.get('context_file_count'))

    if _looks_like_environment_failure(note_text):
        main_label = LABEL_ENV
        key_evidence = _build_evidence("\u672c\u5730\u65e5\u5fd7\u663e\u793a\u73af\u5883\u6216\u4f9d\u8d56\u9519\u8bef", run_summary, official_status, changed_files)
    elif _looks_like_preparation_failure(note_text):
        main_label = LABEL_PREP
        key_evidence = _build_evidence("\u524d\u7f6e\u51c6\u5907\u6b65\u9aa4\u5931\u8d25", run_summary, official_status, changed_files)
    elif _looks_like_timeout(note_text, official_payload):
        main_label = LABEL_TIMEOUT
        key_evidence = _build_evidence("\u8fd0\u884c\u8d85\u65f6\u6216\u88ab\u5b98\u65b9\u8bc4\u6d4b\u6807\u8bb0\u4e3a\u8d85\u65f6", run_summary, official_status, changed_files)
    elif _looks_like_crash(note_text, official_status):
        main_label = LABEL_CRASH
        key_evidence = _build_evidence("\u6267\u884c\u8fc7\u7a0b\u4e2d\u5f02\u5e38\u9000\u51fa", run_summary, official_status, changed_files)
    elif not patch_text.strip() and not changed_files:
        main_label = LABEL_NO_PATCH
        key_evidence = _build_evidence("\u6700\u7ec8\u8865\u4e01\u4e3a\u7a7a\uff0c\u4e14\u6ca1\u6709\u6539\u52a8\u6587\u4ef6", run_summary, official_status, changed_files)
    elif _has_scope_violation(task, changed_files):
        main_label = LABEL_SCOPE
        key_evidence = _build_evidence("\u6539\u52a8\u6587\u4ef6\u8d85\u51fa\u5141\u8bb8\u4fee\u6539\u8303\u56f4", run_summary, official_status, changed_files)
    elif _has_invalid_patch(official_payload):
        main_label = LABEL_INVALID_PATCH
        key_evidence = _build_evidence("\u5b98\u65b9\u7ed3\u679c\u663e\u793a\u8865\u4e01\u672a\u6210\u529f\u5e94\u7528", run_summary, official_status, changed_files)
    elif _has_regression(official_payload):
        main_label = LABEL_REGRESSION
        key_evidence = _build_evidence("\u5b98\u65b9\u7ed3\u679c\u663e\u793a\u539f\u672c\u5e94\u4fdd\u6301\u901a\u8fc7\u7684\u6d4b\u8bd5\u5931\u8d25", run_summary, official_status, changed_files)
    elif _is_partial_fix(official_payload):
        main_label = LABEL_PARTIAL
        key_evidence = _build_evidence("\u5b98\u65b9\u7ed3\u679c\u663e\u793a\u90e8\u5206\u76ee\u6807\u6d4b\u8bd5\u901a\u8fc7\uff0c\u4f46\u4ecd\u672a\u5b8c\u5168\u89e3\u51b3", run_summary, official_status, changed_files)
    else:
        main_label = LABEL_UNRESOLVED
        key_evidence = _build_evidence("\u5b98\u65b9\u76ee\u6807\u95ee\u9898\u4ecd\u672a\u89e3\u51b3", run_summary, official_status, changed_files)

    probable_cause, confidence = _infer_probable_cause(
        main_label=main_label,
        changed_files=changed_files,
        context_file_count=context_file_count,
        note_text=note_text,
    )
    return FailureAnalysisItem(
        instance_id=instance_id,
        task_id=run_summary.task_id if run_summary is not None else instance_id,
        harness_profile=harness_profile,
        official_status=official_status,
        main_label=main_label,
        stage=_stage_for_label(main_label),
        key_evidence=key_evidence,
        probable_cause=probable_cause,
        cause_confidence=confidence,
        run_status=run_summary.status.value if run_summary is not None else None,
        verifier_outcome=run_summary.verifier_outcome if run_summary is not None else None,
        changed_files=changed_files,
        notes=notes,
        signals={
            'context_file_count': context_file_count,
            'patch_present': bool(patch_text.strip()),
            'changed_file_count': len(changed_files),
        },
    )


def _latest_model_request_payload(record: StoredRunRecord | None) -> dict[str, object]:
    if record is None:
        return {}
    for event in reversed(record.events):
        if event.event_type is EventType.MODEL_REQUESTED:
            return dict(event.payload)
    return {}


def _looks_like_environment_failure(note_text: str) -> bool:
    patterns = (
        'no module named',
        'modulenotfounderror',
        'permission denied',
        'docker',
        'api key',
        'authentication',
        'network is unreachable',
    )
    return any(pattern in note_text for pattern in patterns)


def _looks_like_preparation_failure(note_text: str) -> bool:
    patterns = (
        'setup step failed',
        'git clone failed',
        'git checkout failed',
        'source repository does not exist',
        'not a git repository',
    )
    return any(pattern in note_text for pattern in patterns)


def _looks_like_timeout(note_text: str, official_payload: Mapping[str, object]) -> bool:
    if 'timed out' in note_text or 'timeout' in note_text:
        return True
    return _truthy(official_payload, 'timeout', 'timed_out', 'report.timeout', 'report.timed_out')


def _looks_like_crash(note_text: str, official_status: str) -> bool:
    if official_status == 'error':
        return True
    patterns = (
        'response parsing failed',
        'traceback',
        'runtimeerror',
        'valueerror',
        'jsondecodeerror',
        'exception',
        'provider request failed',
    )
    return any(pattern in note_text for pattern in patterns)


def _has_scope_violation(task, changed_files: tuple[str, ...]) -> bool:
    if task is None or not changed_files:
        return False
    forbidden = tuple(str(item) for item in getattr(task.constraints, 'forbidden_paths', ()) if str(item))
    editable = tuple(str(item) for item in getattr(task.constraints, 'editable_paths', ()) if str(item))
    for path in changed_files:
        if any(_matches_prefix(path, item) for item in forbidden):
            return True
        if editable and not any(_matches_prefix(path, item) for item in editable):
            return True
    return False


def _has_invalid_patch(official_payload: Mapping[str, object]) -> bool:
    if not official_payload:
        return False
    if _truthy(official_payload, 'patch_failure', 'patch_apply_failed', 'report.patch_apply_failed'):
        return True
    applied = _first_value(official_payload, 'patch_successfully_applied', 'report.patch_successfully_applied')
    return applied is False


def _has_regression(official_payload: Mapping[str, object]) -> bool:
    if _truthy(official_payload, 'regression', 'has_regression', 'report.regression'):
        return True
    failed = _first_nonempty_list(
        official_payload,
        'pass_to_pass_failed',
        'pass_to_pass_failures',
        'report.pass_to_pass.failed',
    )
    return bool(failed)


def _is_partial_fix(official_payload: Mapping[str, object]) -> bool:
    passed = _first_nonempty_list(
        official_payload,
        'fail_to_pass_passed',
        'report.fail_to_pass.passed',
    )
    failed = _first_nonempty_list(
        official_payload,
        'fail_to_pass_failed',
        'report.fail_to_pass.failed',
    )
    return bool(passed and failed)


def _infer_probable_cause(
    *,
    main_label: str,
    changed_files: tuple[str, ...],
    context_file_count: int | None,
    note_text: str,
) -> tuple[str, str]:
    if main_label == LABEL_ENV:
        return CAUSE_ENV, CONF_HIGH
    if main_label == LABEL_PREP:
        return CAUSE_PREP, CONF_HIGH
    if main_label == LABEL_TIMEOUT:
        return CAUSE_TIMEOUT, CONF_HIGH
    if main_label == LABEL_CRASH:
        return CAUSE_CRASH, CONF_HIGH
    if main_label == LABEL_SCOPE:
        return CAUSE_LOCATE, CONF_HIGH
    if main_label == LABEL_INVALID_PATCH:
        return CAUSE_CONTRACT, CONF_HIGH
    if main_label == LABEL_REGRESSION:
        return CAUSE_REGRESSION, CONF_HIGH
    if main_label == LABEL_PARTIAL:
        return CAUSE_PARTIAL, CONF_MEDIUM
    if main_label == LABEL_NO_PATCH:
        if context_file_count == 0:
            return CAUSE_CONTEXT, CONF_MEDIUM
        return CAUSE_LOCATE, CONF_MEDIUM
    if main_label == LABEL_UNRESOLVED:
        if not changed_files:
            return CAUSE_LOCATE, CONF_MEDIUM
        if context_file_count == 0:
            return CAUSE_CONTEXT, CONF_MEDIUM
        if 'test' in note_text or 'verifier' in note_text:
            return CAUSE_TEST, CONF_MEDIUM
        return CAUSE_UNDERSTAND, CONF_MEDIUM
    return CAUSE_UNKNOWN, CONF_LOW


def _build_evidence(primary: str, run_summary, official_status: str, changed_files: tuple[str, ...]) -> tuple[str, ...]:
    items = [primary, f"\u5b98\u65b9\u72b6\u6001={official_status}"]
    if run_summary is not None:
        items.append(f"\u672c\u5730\u72b6\u6001={run_summary.status.value}")
    if changed_files:
        items.append("\u6539\u52a8\u6587\u4ef6=" + ', '.join(changed_files[:3]))
    return tuple(items[:3])


def _stage_for_label(label: str) -> str:
    if label in {LABEL_ENV, LABEL_PREP}:
        return STAGE_PREP
    if label in {LABEL_TIMEOUT, LABEL_CRASH}:
        return STAGE_EXEC
    if label in {LABEL_NO_PATCH, LABEL_SCOPE, LABEL_INVALID_PATCH}:
        return STAGE_EDIT
    return STAGE_OFFICIAL


def _matches_prefix(path: str, prefix: str) -> bool:
    normalized_path = path.replace('\\', '/')
    normalized_prefix = prefix.replace('\\', '/').strip('/')
    if not normalized_prefix:
        return False
    if normalized_path == normalized_prefix:
        return True
    return normalized_path.startswith(normalized_prefix + '/')


def _truthy(payload: Mapping[str, object], *paths: str) -> bool:
    value = _first_value(payload, *paths)
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _first_nonempty_list(payload: Mapping[str, object], *paths: str) -> tuple[str, ...]:
    for path in paths:
        items = _string_tuple(_nested_value(payload, path))
        if items:
            return items
    return ()


def _first_value(payload: Mapping[str, object], *paths: str):
    for path in paths:
        value = _nested_value(payload, path)
        if value is not None:
            return value
    return None


def _nested_value(payload: Mapping[str, object], path: str):
    current = payload
    for part in path.split('.'):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _string_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _int(value) -> int | None:
    if value is None:
        return None
    return int(value)
