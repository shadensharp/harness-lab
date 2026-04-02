from __future__ import annotations

import os
from typing import Any, Mapping

from repo_harness_lab.agents.adapters.local_script import LocalScriptAgentAdapter
from repo_harness_lab.agents.adapters.provider_json_edit import StructuredEditAgentAdapter
from repo_harness_lab.agents.base import BaseAgentAdapter, NoOpAgentAdapter
from repo_harness_lab.agents.providers.openai_compatible import OpenAICompatibleChatProvider
from repo_harness_lab.domain.run_models import AgentProfile


DEFAULT_QWEN_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
DEFAULT_DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
DEFAULT_OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'
DEFAULT_OPENAI_BASE_URL = 'https://api.openai.com/v1'
DEFAULT_GROQ_BASE_URL = 'https://api.groq.com/openai/v1'
DEFAULT_MOONSHOT_BASE_URL = 'https://api.moonshot.cn/v1'
DEFAULT_SILICONFLOW_BASE_URL = 'https://api.siliconflow.cn/v1'
DEFAULT_FIREWORKS_BASE_URL = 'https://api.fireworks.ai/inference/v1'

_PROVIDER_CANONICAL_NAMES: dict[str, str] = {
    'qwen': 'qwen',
    'dashscope': 'qwen',
    'deepseek': 'deepseek',
    'openrouter': 'openrouter',
    'openai': 'openai',
    'openai_compatible': 'openai_compatible',
    'groq': 'groq',
    'moonshot': 'moonshot',
    'kimi': 'moonshot',
    'siliconflow': 'siliconflow',
    'fireworks': 'fireworks',
}

_PROVIDER_BASE_URL_DEFAULTS: dict[str, tuple[str, str]] = {
    'qwen': ('DASHSCOPE_BASE_URL', DEFAULT_QWEN_BASE_URL),
    'deepseek': ('DEEPSEEK_BASE_URL', DEFAULT_DEEPSEEK_BASE_URL),
    'openrouter': ('OPENROUTER_BASE_URL', DEFAULT_OPENROUTER_BASE_URL),
    'openai': ('OPENAI_BASE_URL', DEFAULT_OPENAI_BASE_URL),
    'groq': ('GROQ_BASE_URL', DEFAULT_GROQ_BASE_URL),
    'moonshot': ('MOONSHOT_BASE_URL', DEFAULT_MOONSHOT_BASE_URL),
    'siliconflow': ('SILICONFLOW_BASE_URL', DEFAULT_SILICONFLOW_BASE_URL),
    'fireworks': ('FIREWORKS_BASE_URL', DEFAULT_FIREWORKS_BASE_URL),
}

_PROVIDER_API_KEY_ENVS: dict[str, tuple[str, ...]] = {
    'qwen': ('DASHSCOPE_API_KEY',),
    'deepseek': ('DEEPSEEK_API_KEY',),
    'openrouter': ('OPENROUTER_API_KEY',),
    'openai': ('OPENAI_API_KEY',),
    'openai_compatible': ('OPENAI_API_KEY',),
    'groq': ('GROQ_API_KEY',),
    'moonshot': ('MOONSHOT_API_KEY',),
    'siliconflow': ('SILICONFLOW_API_KEY',),
    'fireworks': ('FIREWORKS_API_KEY',),
}

_PROVIDER_HEADER_ENV_DEFAULTS: dict[str, Mapping[str, str]] = {
    'openrouter': {
        'HTTP-Referer': 'OPENROUTER_HTTP_REFERER',
        'X-Title': 'OPENROUTER_X_TITLE',
    }
}



def build_agent_adapter(profile: AgentProfile) -> BaseAgentAdapter:
    metadata = dict(profile.metadata)
    provider = _canonical_provider(profile.provider)
    command = _command_tuple(metadata.get('command'))
    timeout_seconds = _optional_float(metadata.get('timeout_seconds'))
    env = _string_mapping(metadata.get('env'))

    if provider == 'local_script' or (command and provider in {'', 'local', 'noop', 'local_noop', 'local_script'}):
        if not command:
            raise ValueError(f'agent profile {profile.name} requires metadata.command for local_script provider')
        return LocalScriptAgentAdapter(
            script_command=command,
            timeout_seconds=_optional_int(timeout_seconds),
            env=env or None,
        )

    if provider in {'', 'local', 'noop', 'local_noop'}:
        return NoOpAgentAdapter()

    if provider in _PROVIDER_API_KEY_ENVS or provider == 'openai_compatible':
        model = _resolve_model(profile, metadata)
        base_url = _resolve_base_url(provider, metadata)
        api_key = _resolve_api_key(provider, metadata)
        provider_client = OpenAICompatibleChatProvider(
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds or 60.0,
            headers=_resolve_headers(provider, metadata),
            request_body=_mapping(metadata.get('request_body')),
        )
        system_prompt = _optional_str(metadata.get('system_prompt'))
        if system_prompt:
            return StructuredEditAgentAdapter(provider=provider_client, system_prompt=system_prompt)
        return StructuredEditAgentAdapter(provider=provider_client)

    if provider == 'local_script':
        raise ValueError(f'agent profile {profile.name} requires metadata.command for local_script provider')

    raise ValueError(f'unsupported agent provider: {profile.provider}')



def _canonical_provider(value: str | None) -> str:
    provider = (value or '').strip().lower()
    return _PROVIDER_CANONICAL_NAMES.get(provider, provider)



def _resolve_model(profile: AgentProfile, metadata: Mapping[str, Any]) -> str:
    model = _optional_str(metadata.get('model')) or profile.version or profile.name
    if not model.strip():
        raise ValueError('provider-backed agents require a model name')
    return model



def _resolve_base_url(provider: str, metadata: Mapping[str, Any]) -> str:
    explicit = _optional_str(metadata.get('base_url'))
    if explicit:
        return explicit
    if provider in _PROVIDER_BASE_URL_DEFAULTS:
        env_name, default_value = _PROVIDER_BASE_URL_DEFAULTS[provider]
        return os.environ.get(env_name, default_value)
    env_value = os.environ.get('OPENAI_COMPATIBLE_BASE_URL')
    if env_value:
        return env_value
    raise ValueError('openai_compatible provider requires metadata.base_url or OPENAI_COMPATIBLE_BASE_URL')



def _resolve_api_key(provider: str, metadata: Mapping[str, Any]) -> str:
    explicit = _optional_str(metadata.get('api_key'))
    if explicit:
        return explicit

    api_key_env = _optional_str(metadata.get('api_key_env'))
    if api_key_env:
        env_value = os.environ.get(api_key_env)
        if env_value:
            return env_value
        raise ValueError(f'missing API key in environment variable: {api_key_env}')

    for env_name in _PROVIDER_API_KEY_ENVS.get(provider, ('OPENAI_API_KEY',)):
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value

    expected = ' or '.join(_PROVIDER_API_KEY_ENVS.get(provider, ('OPENAI_API_KEY',)))
    raise ValueError(f'missing API key for provider {provider}; set metadata.api_key or {expected}')



def _resolve_headers(provider: str, metadata: Mapping[str, Any]) -> Mapping[str, str]:
    headers: dict[str, str] = {}
    for key, env_name in _PROVIDER_HEADER_ENV_DEFAULTS.get(provider, {}).items():
        env_value = os.environ.get(env_name)
        if env_value:
            headers[str(key)] = env_value
    headers.update(_string_mapping(metadata.get('headers')))
    return headers



def _command_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(str(item) for item in value)



def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)



def _optional_int(value: float | None) -> int | None:
    if value is None:
        return None
    return int(value)



def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)



def _string_mapping(value: Any) -> Mapping[str, str]:
    if value is None:
        return {}
    return {str(key): str(item) for key, item in dict(value).items()}



def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    return dict(value)