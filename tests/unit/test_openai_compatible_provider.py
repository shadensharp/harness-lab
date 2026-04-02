from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.agents.providers.base import ModelMessage, ModelMessageRole
from repo_harness_lab.agents.providers.openai_compatible import OpenAICompatibleChatProvider


class _FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf8")


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_provider_maps_usage_cost_alias_to_total_cost_usd(self) -> None:
        provider = OpenAICompatibleChatProvider(
            model="openai/gpt-4.1-mini",
            base_url="https://openrouter.ai/api/v1",
            api_key="token",
        )
        response_payload = {
            "id": "resp-001",
            "model": "openai/gpt-4.1-mini",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "hello"},
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": 0.0123,
            },
        }

        with patch("repo_harness_lab.agents.providers.openai_compatible.urlopen", return_value=_FakeHttpResponse(response_payload)):
            response = provider.generate((ModelMessage(role=ModelMessageRole.USER, content="hi"),))

        self.assertEqual(response.content, "hello")
        self.assertEqual(response.usage.total_tokens, 15)
        self.assertAlmostEqual(response.usage.total_cost_usd, 0.0123)


if __name__ == "__main__":
    unittest.main()
