from __future__ import annotations

from typing import Any, Mapping

from repo_harness_lab.domain.trace_models import EventType
from repo_harness_lab.storage.run_store import StoredRunRecord


def build_harness_shared_items(record: StoredRunRecord | None) -> tuple[str, ...]:
    payload = _latest_payload(record, EventType.MODEL_REQUESTED)
    if not payload:
        return ()

    sections = _string_tuple(payload.get("shared_prompt_sections"))
    if not sections:
        return ()
    return (
        "共同任务信息固定："
        + "、".join(_shared_section_label(item) for item in sections),
    )


def build_harness_extra_items(record: StoredRunRecord | None) -> tuple[str, ...]:
    payload = _latest_payload(record, EventType.MODEL_REQUESTED)
    if not payload:
        return ()

    items: list[str] = []
    if payload.get("includes_repo_tree"):
        tree_count = _int(payload.get("tree_entry_count"))
        if tree_count is not None:
            items.append(f"本档额外附带仓库树：{tree_count} 条")

    context_files = _string_tuple(payload.get("selected_context_files"))
    context_count = _int(payload.get("context_file_count"))
    if context_files:
        items.append(f"本档额外上下文文件：{', '.join(context_files)}")
    elif context_count == 0:
        items.append("本档额外上下文文件：无")

    input_names = _string_tuple(payload.get("included_input_names"))
    if input_names:
        items.append(f"本档额外任务输入：{', '.join(input_names)}")

    verifier_steps = _string_tuple(payload.get("included_verifier_steps"))
    if verifier_steps:
        items.append(f"本档额外验收步骤：{', '.join(verifier_steps)}")
    return tuple(items)


def build_harness_input_items(record: StoredRunRecord | None) -> tuple[str, ...]:
    payload = _latest_payload(record, EventType.MODEL_REQUESTED)
    if not payload:
        return ()

    items: list[str] = []
    model_text = _model_text(payload)
    if model_text:
        items.append(f"模型：{model_text}")

    profile = _string(payload.get("harness_profile"))
    if profile:
        items.append(f"档位：{profile}")

    counts: list[str] = []
    context_count = _int(payload.get("context_file_count"))
    tree_count = _int(payload.get("tree_entry_count"))
    truncated_count = _int(payload.get("truncated_file_count"))
    if context_count is not None:
        counts.append(f"上下文文件：{context_count}")
    if tree_count is not None:
        counts.append(f"仓库树条目：{tree_count}")
    if truncated_count is not None:
        counts.append(f"截断文件：{truncated_count}")
    if counts:
        items.append(", ".join(counts))
    items.extend(build_harness_shared_items(record))
    items.extend(build_harness_extra_items(record))
    return tuple(items)


def build_model_response_items(record: StoredRunRecord | None) -> tuple[str, ...]:
    payload = _response_payload(record)
    if not payload:
        return ()

    items: list[str] = []
    finish_reason = _string(payload.get("finish_reason"))
    if finish_reason:
        items.append(f"结束原因：{finish_reason}")

    write_count = _int(payload.get("write_count"))
    if write_count is not None:
        items.append(f"写入文件：{write_count}")

    prompt_tokens = _int(payload.get("prompt_tokens"))
    completion_tokens = _int(payload.get("completion_tokens"))
    total_tokens = _int(payload.get("total_tokens"))
    if prompt_tokens or completion_tokens or total_tokens:
        items.append(
            "Token："
            f"提示 {prompt_tokens or 0}，"
            f"生成 {completion_tokens or 0}，"
            f"总计 {total_tokens or 0}"
        )

    total_cost = _float(payload.get("total_cost_usd"))
    if total_cost not in (None, 0.0):
        items.append(f"费用：${total_cost:.4f}")
    return tuple(items)


def build_harness_delta_items(
    left_record: StoredRunRecord | None,
    right_record: StoredRunRecord | None,
) -> tuple[str, ...]:
    left_payload = _latest_payload(left_record, EventType.MODEL_REQUESTED)
    right_payload = _latest_payload(right_record, EventType.MODEL_REQUESTED)
    if not left_payload or not right_payload:
        return ()

    items: list[str] = []
    left_model = _model_text(left_payload)
    right_model = _model_text(right_payload)
    if left_model and right_model and left_model != right_model:
        items.append(f"模型：{left_model} -> {right_model}")

    items.extend(
        item
        for item in (
            _string_delta("档位", left_payload.get("harness_profile"), right_payload.get("harness_profile")),
            _int_delta("上下文文件", left_payload.get("context_file_count"), right_payload.get("context_file_count")),
            _int_delta("仓库树条目", left_payload.get("tree_entry_count"), right_payload.get("tree_entry_count")),
            _int_delta("截断文件", left_payload.get("truncated_file_count"), right_payload.get("truncated_file_count")),
            _list_delta("新增上下文文件", left_payload.get("selected_context_files"), right_payload.get("selected_context_files")),
            _list_removed_delta("移除上下文文件", left_payload.get("selected_context_files"), right_payload.get("selected_context_files")),
            _list_delta("新增任务输入", left_payload.get("included_input_names"), right_payload.get("included_input_names")),
            _list_delta("新增验收步骤", left_payload.get("included_verifier_steps"), right_payload.get("included_verifier_steps")),
        )
        if item
    )
    return tuple(items)


def build_model_delta_items(
    left_record: StoredRunRecord | None,
    right_record: StoredRunRecord | None,
) -> tuple[str, ...]:
    left_payload = _response_payload(left_record)
    right_payload = _response_payload(right_record)
    if not left_payload or not right_payload:
        return ()

    items = [
        item
        for item in (
            _string_delta("结束原因", left_payload.get("finish_reason"), right_payload.get("finish_reason")),
            _int_delta("写入文件", left_payload.get("write_count"), right_payload.get("write_count")),
            _int_delta("提示 Token", left_payload.get("prompt_tokens"), right_payload.get("prompt_tokens")),
            _int_delta("生成 Token", left_payload.get("completion_tokens"), right_payload.get("completion_tokens")),
            _int_delta("总 Token", left_payload.get("total_tokens"), right_payload.get("total_tokens")),
        )
        if item
    ]

    left_cost = _float(left_payload.get("total_cost_usd"))
    right_cost = _float(right_payload.get("total_cost_usd"))
    if left_cost is not None and right_cost is not None and left_cost != right_cost:
        delta = right_cost - left_cost
        items.append(f"费用：${left_cost:.4f} -> ${right_cost:.4f} ({delta:+.4f})")
    return tuple(items)


def _response_payload(record: StoredRunRecord | None) -> dict[str, Any]:
    payload = _latest_payload(record, EventType.MODEL_RESPONDED)
    if record is None:
        return payload

    cost = record.summary.cost_summary
    if payload or cost.total_tokens or cost.total_cost_usd:
        if "prompt_tokens" not in payload:
            payload["prompt_tokens"] = cost.prompt_tokens
        if "completion_tokens" not in payload:
            payload["completion_tokens"] = cost.completion_tokens
        if "total_tokens" not in payload:
            payload["total_tokens"] = cost.total_tokens
        if "total_cost_usd" not in payload:
            payload["total_cost_usd"] = cost.total_cost_usd
    return payload


def _latest_payload(record: StoredRunRecord | None, event_type: EventType) -> dict[str, Any]:
    if record is None:
        return {}
    for event in reversed(record.events):
        if event.event_type == event_type:
            return dict(event.payload)
    return {}


def _model_text(payload: Mapping[str, Any]) -> str:
    model = _string(payload.get("model"))
    provider = _string(payload.get("provider"))
    if model and provider:
        return f"{model}（{provider}）"
    return model or provider


def _string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _int(value: object) -> int | None:
    return None if value is None else int(value)


def _float(value: object) -> float | None:
    return None if value is None else float(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(str(item) for item in value if str(item))


def _string_delta(label: str, left_value: object, right_value: object) -> str | None:
    left_text = _string(left_value)
    right_text = _string(right_value)
    if not left_text or not right_text or left_text == right_text:
        return None
    return f"{label}: {left_text} -> {right_text}"


def _int_delta(label: str, left_value: object, right_value: object) -> str | None:
    left_number = _int(left_value)
    right_number = _int(right_value)
    if left_number is None or right_number is None or left_number == right_number:
        return None
    delta = right_number - left_number
    return f"{label}: {left_number} -> {right_number} ({delta:+d})"


def _list_delta(label: str, left_value: object, right_value: object) -> str | None:
    left_items = _string_tuple(left_value)
    right_items = _string_tuple(right_value)
    added = [item for item in right_items if item not in left_items]
    if not added:
        return None
    return f"{label}: {', '.join(added)}"


def _list_removed_delta(label: str, left_value: object, right_value: object) -> str | None:
    left_items = _string_tuple(left_value)
    right_items = _string_tuple(right_value)
    removed = [item for item in left_items if item not in right_items]
    if not removed:
        return None
    return f"{label}: {', '.join(removed)}"


def _shared_section_label(value: str) -> str:
    labels = {
        "task_brief": "任务正文",
        "constraints": "约束条件",
        "success_criteria": "成功标准",
        "response_contract": "输出格式",
    }
    return labels.get(value, value)
