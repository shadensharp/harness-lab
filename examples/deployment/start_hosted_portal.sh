#!/usr/bin/env bash
set -euo pipefail

: "${PORTAL_APP_ROOT:=/srv/repo-harness-lab/app}"
: "${PORTAL_HOST:=127.0.0.1}"
: "${PORTAL_PORT:=8765}"
: "${PORTAL_PROVIDER:=qwen}"
: "${PORTAL_MODEL:=qwen-plus}"
: "${PORTAL_API_KEY_ENV:=DASHSCOPE_API_KEY}"
: "${REPO_HARNESS_LAB_PROJECT_ROOT:=$PORTAL_APP_ROOT}"
: "${REPO_HARNESS_LAB_RUNTIME_ROOT:=/srv/repo-harness-lab/runtime}"
: "${REPO_HARNESS_LAB_KEEP_WORKSPACES:=0}"

if [[ -z "${PORTAL_PUBLIC_BASE_URL:-}" ]]; then
  echo "PORTAL_PUBLIC_BASE_URL is required" >&2
  exit 1
fi

PORTAL_PYTHON_BIN="${PORTAL_PYTHON_BIN:-$PORTAL_APP_ROOT/.venv/bin/python}"

if [[ ! -x "$PORTAL_PYTHON_BIN" ]]; then
  echo "python executable not found: $PORTAL_PYTHON_BIN" >&2
  exit 1
fi

export REPO_HARNESS_LAB_PROJECT_ROOT
export REPO_HARNESS_LAB_RUNTIME_ROOT
export REPO_HARNESS_LAB_KEEP_WORKSPACES

cd "$PORTAL_APP_ROOT"

cmd=(
  "$PORTAL_PYTHON_BIN"
  -m
  repo_harness_lab.cli.main
  serve-portal
  --host
  "$PORTAL_HOST"
  --port
  "$PORTAL_PORT"
  --provider
  "$PORTAL_PROVIDER"
  --model
  "$PORTAL_MODEL"
  --api-key-env
  "$PORTAL_API_KEY_ENV"
  --public-base-url
  "$PORTAL_PUBLIC_BASE_URL"
  --hosted-mode
)

if [[ -n "${PORTAL_TEMPLATE:-}" ]]; then
  cmd+=(--template "$PORTAL_TEMPLATE")
fi

if [[ -n "${PORTAL_AGENT_NAME:-}" ]]; then
  cmd+=(--agent-name "$PORTAL_AGENT_NAME")
fi

if [[ -n "${PORTAL_BASE_URL:-}" ]]; then
  cmd+=(--base-url "$PORTAL_BASE_URL")
fi

if [[ -n "${PORTAL_SYSTEM_PROMPT:-}" ]]; then
  cmd+=(--system-prompt "$PORTAL_SYSTEM_PROMPT")
fi

if [[ -n "${PORTAL_LABEL_PREFIX:-}" ]]; then
  cmd+=(--label-prefix "$PORTAL_LABEL_PREFIX")
fi

exec "${cmd[@]}"
