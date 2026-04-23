# 示例目录

## 默认单题示例：Tetris

如果你想先跑一个直观的单题示例，先用这套默认 intake：

```powershell
python -m repo_harness_lab.cli.main show-task-intake-template
python -m repo_harness_lab.cli.main preview-intake examples/intakes/portal_tetris_task_intake.json --format both
python -m repo_harness_lab.cli.main scaffold-task-spec examples/intakes/portal_tetris_task_intake.json --write runtime/tmp/portal_tetris_demo.task.json
```

如果已经配置好模型 API Key，也可以直接跑默认主线的 `current`：

```powershell
python -m repo_harness_lab.cli.main run-intake-eval examples/intakes/portal_tetris_task_intake.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY
```

这套示例对应的仓库是 `examples/repos/portal_tetris_demo_repo`，默认只允许修改 `game/tetris.py`，验收命令是 `python -m unittest tests.test_tetris_game -q`。

## 历史 uplift 示例

这些 suite 仍保留，用于演示 `current` 与 `custom` 的附加运行差异；它们不是当前默认主线。

- `examples/evals/qwen_provider_multi_signal_uplift_suite.json`
- `examples/evals/qwen_provider_uplift_suite.json`
- `examples/evals/qwen_provider_extended_uplift_suite.json`

运行命令：

```powershell
repo-harness-lab run-eval examples/evals/qwen_provider_multi_signal_uplift_suite.json
```

如果只想更快地跑一轮旧 smoke，可以用：

```powershell
python -m repo_harness_lab.cli.main run-eval examples/evals/qwen_provider_uplift_suite.json
```

如果只是想看 intake 经过系统后，当前运行会收到什么信息，可以先用：

```powershell
python -m repo_harness_lab.cli.main preview-intake examples/intakes/portal_tetris_task_intake.json
```

如果你要跑当前主线，而不是旧多配置矩阵，请优先使用 `run-intake-eval`。

## Repo Benchmark 示例

轻量 manifest 示例：

- `examples/evals/repo_benchmark_sample_manifest.json`
- `docs/benchmarks/EXTERNAL_BENCHMARK_LANE.md`

运行命令：

```powershell
python -m repo_harness_lab.cli.main run-benchmark-eval examples/evals/repo_benchmark_sample_manifest.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY
```

这条链路默认只跑一次 `current`；如果要对照旧结果或历史版本，使用 `--baseline-report-id` 或 `--historical-baseline-report-id`。

## SWE-bench Export 示例

如果你想从更接近 official benchmark 的实例文件开始，而不是手写 manifest，可以看：

- `examples/benchmarks/swe_bench_sample_instances.jsonl`

先导出 manifest：

```powershell
python -m repo_harness_lab.cli.main export-swebench-manifest examples/benchmarks/swe_bench_sample_instances.jsonl runtime/tmp/swe_bench_sample.manifest.json --benchmark-id swe-bench-sample --metric-name resolved_rate --default-verifier-command-json "[\"python\", \"-m\", \"pytest\", \"-q\"]"
```

再跑 benchmark lane：

```powershell
python -m repo_harness_lab.cli.main run-benchmark-eval runtime/tmp/swe_bench_sample.manifest.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY
```

如果需要官方判分，再把生成的 report 交给：

```powershell
python -m repo_harness_lab.cli.main grade-swebench-official <report-id> --model-name qwen-plus
```

## Hosted Portal 部署模板

如果你只是想保留一套单机 `hosted portal` 部署模板，请看：

- `docs/deployment/HOSTED_PORTAL_DEPLOYMENT.md`
- `examples/deployment/portal.env.example`
- `examples/deployment/start_hosted_portal.sh`
- `examples/deployment/repo-harness-lab-portal.service`
- `examples/deployment/nginx.repo-harness-lab-portal.conf`
