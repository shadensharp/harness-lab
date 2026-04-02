from __future__ import annotations

import argparse
from pathlib import Path

from repo_harness_lab.agents.factory import build_agent_adapter
from repo_harness_lab.cli.commands.common import print_json
from repo_harness_lab.config.settings import load_settings
from repo_harness_lab.domain.run_models import AgentProfile, RunRequest
from repo_harness_lab.domain.task_spec import HarnessProfile
from repo_harness_lab.reporting.markdown import MarkdownReporter
from repo_harness_lab.runtime.runner import RunOrchestrator
from repo_harness_lab.runtime.workspace import LocalWorkspaceBackend
from repo_harness_lab.shared.ids import new_id
from repo_harness_lab.storage.json_store import JsonRunStore
from repo_harness_lab.tasks.loader import JsonTaskLoader
from repo_harness_lab.verifiers.factory import build_verifier



def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run_task = subparsers.add_parser("run-task", help="Run a task through the local harness")
    run_task.add_argument("source")
    run_task.add_argument("--verifier-step", action="append", default=[])
    run_task.add_argument(
        "--agent-command",
        nargs=argparse.REMAINDER,
        help="Command executed by the local script agent; place it last in the CLI invocation.",
    )
    run_task.add_argument("--agent-provider", help="Agent provider, for example qwen, deepseek, openrouter, openai, groq, moonshot, siliconflow or fireworks")
    run_task.add_argument("--agent-model", help="External model name used by provider-backed agents")
    run_task.add_argument("--agent-base-url", help="Override base URL for provider-backed agents")
    run_task.add_argument("--agent-api-key", help="Direct API key for provider-backed agents")
    run_task.add_argument("--agent-api-key-env", help="Environment variable name that stores the API key")
    run_task.add_argument(
        "--harness-profile",
        choices=[profile.value for profile in HarnessProfile],
        default=HarnessProfile.CUSTOM.value,
        help="Context strength passed into provider-backed agents",
    )
    run_task.set_defaults(handler=handle_run_task)



def handle_run_task(args: argparse.Namespace) -> int:
    settings = load_settings()
    settings.paths.ensure_runtime_directories()
    task = JsonTaskLoader().load(Path(args.source))

    agent, agent_profile = _build_agent(args)
    request = RunRequest(
        run_id=new_id("run"),
        task_id=task.task_id,
        agent_profile=agent_profile,
        labels=(f"harness_profile:{args.harness_profile}",),
        metadata={"harness_profile": args.harness_profile},
    )
    backend = LocalWorkspaceBackend(settings=settings)
    verifier = build_verifier(task=task, backend=backend, step_names=tuple(args.verifier_step))
    orchestrator = RunOrchestrator(
        agent=agent,
        verifier=verifier,
        backend=backend,
        run_store=JsonRunStore(settings=settings),
        reporter=MarkdownReporter(),
        settings=settings,
    )
    outcome = orchestrator.run(task, request)
    print_json(outcome.summary)
    return 0 if outcome.summary.status.value == "succeeded" else 1



def _build_agent(args: argparse.Namespace) -> tuple[object, AgentProfile]:
    if args.agent_command:
        profile = AgentProfile(
            name=args.agent_command[0],
            provider="local_script",
            metadata={"command": tuple(args.agent_command)},
        )
        return build_agent_adapter(profile), profile

    provider = (args.agent_provider or "").strip().lower()
    if not provider:
        profile = AgentProfile(name="noop-agent", provider="local")
        return build_agent_adapter(profile), profile

    if not args.agent_model:
        raise ValueError("provider-backed agents require --agent-model")

    metadata = {
        "model": args.agent_model,
        "harness_profile": args.harness_profile,
    }
    if args.agent_base_url:
        metadata["base_url"] = args.agent_base_url
    if args.agent_api_key:
        metadata["api_key"] = args.agent_api_key
    if args.agent_api_key_env:
        metadata["api_key_env"] = args.agent_api_key_env

    profile = AgentProfile(
        name=args.agent_model,
        provider=provider,
        metadata=metadata,
    )
    return build_agent_adapter(profile), profile

