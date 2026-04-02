from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_ROOT = Path(__file__).resolve().parents[2] / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from repo_harness_lab.agents.adapters.provider_json_edit import StructuredEditAgentAdapter
from repo_harness_lab.agents.factory import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_GROQ_BASE_URL,
    DEFAULT_MOONSHOT_BASE_URL,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_QWEN_BASE_URL,
    build_agent_adapter,
)
from repo_harness_lab.agents.providers.base import ModelMessage, ProviderResponse, ProviderUsage
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest, WorkspaceSession
from repo_harness_lab.domain.task_spec import (
    RepoCheckoutMode,
    RepoSource,
    RepoSourceKind,
    SuccessCriteria,
    TaskConstraints,
    TaskInput,
    TaskInputBundle,
    TaskInputKind,
    TaskSpec,
    TaskType,
    VerifierPlan,
    VerifierStep,
    VerifierStepKind,
)
from repo_harness_lab.domain.trace_models import EventType


class FakeProvider:
    def __init__(self, response: ProviderResponse) -> None:
        self.response = response
        self.messages: tuple[ModelMessage, ...] = ()

    def generate(self, messages: tuple[ModelMessage, ...]) -> ProviderResponse:
        self.messages = tuple(messages)
        return self.response


class StructuredEditAgentAdapterTests(unittest.TestCase):
    def _build_task(self, repo_root: Path, *, metadata: dict[str, object] | None = None) -> TaskSpec:
        return TaskSpec(
            task_id='task-001',
            title='Update README',
            description='Rewrite README.md so that it says updated.',
            task_type=TaskType.REQUIREMENT_CHANGE,
            repo_source=RepoSource(
                kind=RepoSourceKind.LOCAL_PATH,
                path_or_url=str(repo_root),
                checkout_mode=RepoCheckoutMode.COPY,
            ),
            constraints=TaskConstraints(editable_paths=('README.md',)),
            success_criteria=SuccessCriteria(changed_files=('README.md',)),
            inputs=TaskInputBundle(
                items=(
                    TaskInput(
                        name='issue',
                        kind=TaskInputKind.TEXT,
                        content='The README should contain the single word updated.',
                    ),
                )
            ),
            verifier_plan=VerifierPlan(
                steps=(
                    VerifierStep(
                        name='readme-check',
                        kind=VerifierStepKind.TEST,
                        command=(sys.executable, '-c', "print('check')"),
                    ),
                )
            ),
            metadata=metadata or {},
        )

    def test_full_profile_includes_context_and_returns_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            repo_root = Path(temp_root)
            (repo_root / 'README.md').write_text('hello\n', encoding='utf8')
            task = self._build_task(repo_root)
            workspace = WorkspaceSession(workspace_id='ws-001', repo_root=repo_root)
            request = RunRequest(
                run_id='run-001',
                task_id=task.task_id,
                agent_profile=AgentProfile(name='qwen-plus', provider='qwen', metadata={'harness_profile': 'full'}),
                metadata={'harness_profile': 'full'},
            )
            provider = FakeProvider(
                ProviderResponse(
                    content=json.dumps(
                        {
                            'summary': 'updated readme',
                            'writes': [{'path': 'README.md', 'content': 'updated\n'}],
                        },
                        ensure_ascii=False,
                    ),
                    model='qwen-plus',
                    usage=ProviderUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            )

            result = StructuredEditAgentAdapter(provider=provider).execute(task, request, workspace)
            user_prompt = provider.messages[1].content

            self.assertEqual((repo_root / 'README.md').read_text(encoding='utf8'), 'updated\n')
            self.assertIn('Verifier plan:', user_prompt)
            self.assertIn('Task inputs:', user_prompt)
            self.assertIn('hello', user_prompt)
            self.assertEqual(result.cost_summary.total_tokens, 18)
            self.assertEqual(result.events[0].event_type, EventType.MODEL_REQUESTED)
            self.assertEqual(result.events[1].event_type, EventType.MODEL_RESPONDED)
            self.assertEqual(result.notes, ('updated readme',))

    def test_basic_profile_prefers_context_paths_from_task_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            repo_root = Path(temp_root)
            (repo_root / 'README.md').write_text('hello\n', encoding='utf8')
            (repo_root / 'a_notes.txt').write_text('alpha\n', encoding='utf8')
            (repo_root / 'b_notes.txt').write_text('beta\n', encoding='utf8')
            (repo_root / 'c_notes.txt').write_text('gamma\n', encoding='utf8')
            (repo_root / 'd_notes.txt').write_text('delta\n', encoding='utf8')
            (repo_root / 'z_contract.txt').write_text('preferred contract context\n', encoding='utf8')
            task = self._build_task(repo_root, metadata={'context_paths': ['z_contract.txt']})
            workspace = WorkspaceSession(workspace_id='ws-001', repo_root=repo_root)
            request = RunRequest(
                run_id='run-001b',
                task_id=task.task_id,
                agent_profile=AgentProfile(name='qwen-plus', provider='qwen', metadata={'harness_profile': 'basic'}),
                metadata={'harness_profile': 'basic'},
            )
            provider = FakeProvider(
                ProviderResponse(content=json.dumps({'summary': 'noop', 'writes': []}, ensure_ascii=False))
            )

            StructuredEditAgentAdapter(provider=provider).execute(task, request, workspace)
            user_prompt = provider.messages[1].content

            self.assertIn('preferred contract context', user_prompt)
            self.assertNotIn('gamma\n', user_prompt)

    def test_bare_profile_limits_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            repo_root = Path(temp_root)
            (repo_root / 'README.md').write_text('hello\n', encoding='utf8')
            task = self._build_task(repo_root)
            workspace = WorkspaceSession(workspace_id='ws-001', repo_root=repo_root)
            request = RunRequest(
                run_id='run-002',
                task_id=task.task_id,
                agent_profile=AgentProfile(name='qwen-plus', provider='qwen', metadata={'harness_profile': 'bare'}),
                metadata={'harness_profile': 'bare'},
            )
            provider = FakeProvider(
                ProviderResponse(content=json.dumps({'summary': 'noop', 'writes': []}, ensure_ascii=False))
            )

            StructuredEditAgentAdapter(provider=provider).execute(task, request, workspace)
            user_prompt = provider.messages[1].content

            self.assertIn('Repository tree:', user_prompt)
            self.assertNotIn('Verifier plan:', user_prompt)
            self.assertNotIn('Task inputs:', user_prompt)
            self.assertNotIn('```text\nhello', user_prompt)


class AgentFactoryTests(unittest.TestCase):
    def test_factory_builds_qwen_provider_adapter(self) -> None:
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'token'}, clear=False):
            adapter = build_agent_adapter(AgentProfile(name='qwen-plus', provider='qwen'))

        self.assertIsInstance(adapter, StructuredEditAgentAdapter)
        self.assertEqual(adapter.provider.model, 'qwen-plus')
        self.assertEqual(adapter.provider.base_url, DEFAULT_QWEN_BASE_URL)

    def test_factory_builds_deepseek_provider_adapter(self) -> None:
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'token'}, clear=False):
            adapter = build_agent_adapter(AgentProfile(name='deepseek-chat', provider='deepseek'))

        self.assertIsInstance(adapter, StructuredEditAgentAdapter)
        self.assertEqual(adapter.provider.model, 'deepseek-chat')
        self.assertEqual(adapter.provider.base_url, DEFAULT_DEEPSEEK_BASE_URL)

    def test_factory_builds_openrouter_provider_adapter(self) -> None:
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'token'}, clear=False):
            adapter = build_agent_adapter(AgentProfile(name='openai/gpt-4.1-mini', provider='openrouter'))

        self.assertIsInstance(adapter, StructuredEditAgentAdapter)
        self.assertEqual(adapter.provider.model, 'openai/gpt-4.1-mini')
        self.assertEqual(adapter.provider.base_url, DEFAULT_OPENROUTER_BASE_URL)

    def test_factory_builds_openai_provider_adapter(self) -> None:
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'token'}, clear=False):
            adapter = build_agent_adapter(AgentProfile(name='gpt-4.1-mini', provider='openai'))

        self.assertIsInstance(adapter, StructuredEditAgentAdapter)
        self.assertEqual(adapter.provider.model, 'gpt-4.1-mini')
        self.assertEqual(adapter.provider.base_url, DEFAULT_OPENAI_BASE_URL)

    def test_factory_maps_kimi_alias_to_moonshot_provider(self) -> None:
        with patch.dict(os.environ, {'MOONSHOT_API_KEY': 'token'}, clear=False):
            adapter = build_agent_adapter(AgentProfile(name='moonshot-v1-8k', provider='kimi'))

        self.assertIsInstance(adapter, StructuredEditAgentAdapter)
        self.assertEqual(adapter.provider.model, 'moonshot-v1-8k')
        self.assertEqual(adapter.provider.base_url, DEFAULT_MOONSHOT_BASE_URL)

    def test_factory_builds_groq_provider_adapter(self) -> None:
        with patch.dict(os.environ, {'GROQ_API_KEY': 'token'}, clear=False):
            adapter = build_agent_adapter(AgentProfile(name='llama-3.3-70b-versatile', provider='groq'))

        self.assertIsInstance(adapter, StructuredEditAgentAdapter)
        self.assertEqual(adapter.provider.model, 'llama-3.3-70b-versatile')
        self.assertEqual(adapter.provider.base_url, DEFAULT_GROQ_BASE_URL)

    def test_factory_applies_openrouter_default_headers_from_env(self) -> None:
        env = {
            'OPENROUTER_API_KEY': 'token',
            'OPENROUTER_HTTP_REFERER': 'https://example.com',
            'OPENROUTER_X_TITLE': 'Repo Harness Lab',
        }
        with patch.dict(os.environ, env, clear=False):
            adapter = build_agent_adapter(AgentProfile(name='openai/gpt-4.1-mini', provider='openrouter'))

        self.assertIsInstance(adapter, StructuredEditAgentAdapter)
        self.assertEqual(adapter.provider.headers['HTTP-Referer'], 'https://example.com')
        self.assertEqual(adapter.provider.headers['X-Title'], 'Repo Harness Lab')


if __name__ == '__main__':
    unittest.main()