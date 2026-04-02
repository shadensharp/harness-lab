from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from repo_harness_lab.agents.providers.base import (
    ModelMessage,
    ProviderRequestError,
    ProviderResponse,
    ProviderUsage,
)


@dataclass(slots=True)
class OpenAICompatibleChatProvider:
    model: str
    base_url: str
    api_key: str
    timeout_seconds: float = 60.0
    headers: Mapping[str, str] = field(default_factory=dict)
    request_body: Mapping[str, Any] = field(default_factory=dict)

    def generate(self, messages: Sequence[ModelMessage]) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": message.role.value,
                    "content": message.content,
                }
                for message in messages
            ],
        }
        payload.update(dict(self.request_body))
        request = Request(
            url=_completion_url(self.base_url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                **{str(key): str(value) for key, value in self.headers.items()},
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf8")
        except HTTPError as exc:
            detail = exc.read().decode("utf8", errors="replace")
            raise ProviderRequestError(f"provider request failed with status {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ProviderRequestError(f"provider request failed: {exc.reason}") from exc

        raw_payload = _parse_json_payload(raw_text)
        choices = raw_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderRequestError("provider response did not include choices")

        first_choice = dict(choices[0])
        message = dict(first_choice.get("message") or {})
        content = _flatten_content(message.get("content"))
        usage_payload = dict(raw_payload.get("usage") or {})

        return ProviderResponse(
            content=content,
            model=str(raw_payload.get("model", self.model)),
            finish_reason=_optional_str(first_choice.get("finish_reason")),
            response_id=_optional_str(raw_payload.get("id")),
            usage=ProviderUsage(
                prompt_tokens=_optional_int(usage_payload.get("prompt_tokens")) or 0,
                completion_tokens=_optional_int(usage_payload.get("completion_tokens")) or 0,
                total_tokens=_optional_int(usage_payload.get("total_tokens")) or 0,
                total_cost_usd=_extract_total_cost(usage_payload),
            ),
            raw_payload=raw_payload,
        )



def _completion_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"



def _parse_json_payload(raw_text: str) -> Mapping[str, Any]:
    payload = json.loads(raw_text)
    if not isinstance(payload, Mapping):
        raise ProviderRequestError("provider response was not a JSON object")
    return dict(payload)



def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                nested = item.get("content")
                if isinstance(nested, str):
                    parts.append(nested)
        return "\n".join(part for part in parts if part)
    return str(content or "")



def _extract_total_cost(usage_payload: Mapping[str, Any]) -> float:
    cost = usage_payload.get("total_cost_usd")
    if cost is None:
        cost = usage_payload.get("cost")
    return _optional_float(cost) or 0.0



def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)



def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)



def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
