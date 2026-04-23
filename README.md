# Repo Harness Lab

[中文说明](README.zh-CN.md)

License: MIT

Repo Harness Lab is a local-first harness for real repository tasks. It turns ambiguous requests into pinned, auditable jobs, runs them in isolated workspace copies, verifies them deterministically, and keeps the evidence needed to explain what happened.

## What The Task Is

This project is about real repository work, not a lucky one-off coding demo.

- The input is a real repository task, not just a chat prompt.
- The system cares about repository revision, editable scope, acceptance rules, and replayability.
- The goal is to study the harness layer behind repository agents, not the chat layer around them.
- The questions are practical: what was the task, what did the model see, why did it pass or fail, and which result came from an internal verifier versus an external official scorer.

## How The System Decides This

The system turns loose requests into a bounded task package before execution.

- It maps intake or benchmark manifests into structured repository tasks.
- It pins repository source, edit scope, expected changed files, context files, and verifier steps.
- It can materialize SWE-bench-style instance files into runnable manifests.
- It keeps benchmark metadata and separates internal diagnostics from official benchmark semantics.

## How Execution Actually Works

Execution follows a fixed chain instead of editing the source repository directly.

1. Materialize the task into a repository task with a pinned source and acceptance rule.
2. Copy the target repository into an isolated workspace.
3. Run the model inside that workspace copy.
4. Execute deterministic verifier commands.
5. If an external conclusion is needed, hand the saved report to the official SWE-bench scorer.

## What Evidence The System Keeps

Each run is designed to leave enough evidence to explain the result.

- Workspace execution record
- `patch.diff`
- Trace events
- Verifier outputs
- Rendered run and eval reports
- Official scorer artifacts when external grading is enabled

Generated evidence snapshots from saved local runs:

| Benchmark suite evidence | Official scorer evidence |
| --- | --- |
| ![Benchmark suite evidence](docs/assets/readme/swebench-benchmark-demo.png) | ![Official scorer evidence](docs/assets/readme/official-swebench-demo.png) |

![Uplift dashboard evidence](docs/assets/readme/uplift-dashboard-demo.png)

## What The Current Result Means

The current public story is a research story, not a product launch story.

- Current public lane: external repository benchmark execution on official repositories
- Priority track: SWE-bench Verified
- Default experiment shape: one `current` run, optionally compared against a saved baseline
- Current conclusion: the official scoring path is wired end to end; the main blocker is still reliable production of useful, non-empty patches on real benchmark tasks

## What You Can Inspect Next

If you want to inspect the system quickly, start here.

Requirements:

- Python `3.11+`
- Windows, macOS, or Linux
- A provider API key for real model runs

Set up the project:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .[dev]
python -m repo_harness_lab.cli.main show-settings
```

Preview the default single-task intake, then run it:

```bash
python -m repo_harness_lab.cli.main preview-intake examples/intakes/portal_tetris_task_intake.json --format both
python -m repo_harness_lab.cli.main run-intake-eval examples/intakes/portal_tetris_task_intake.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY
```

Run the benchmark-to-official chain:

```bash
python -m repo_harness_lab.cli.main export-swebench-manifest examples/benchmarks/swe_bench_sample_instances.jsonl runtime/tmp/swe_bench_sample.manifest.json --benchmark-id swe-bench-sample --metric-name resolved_rate --default-verifier-command-json "[\"python\", \"-m\", \"pytest\", \"-q\"]"
python -m repo_harness_lab.cli.main run-benchmark-eval runtime/tmp/swe_bench_sample.manifest.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY
python -m repo_harness_lab.cli.main grade-swebench-official <report-id> --model-name qwen-plus
```

Useful docs:

- [External benchmark lane](docs/benchmarks/EXTERNAL_BENCHMARK_LANE.md)
- [Official SWE-bench evaluation](docs/benchmarks/SWEBENCH_OFFICIAL_EVALUATION.md)
- [Examples](examples/README.md)

Important boundaries:

- This is not a general-purpose chat coding assistant.
- Internal diagnostics are not the same thing as official benchmark scores.
- Local runtime outputs, copied workspaces, private logs, and environment files are intentionally kept out of Git history.

## License

MIT. See [LICENSE](LICENSE).
