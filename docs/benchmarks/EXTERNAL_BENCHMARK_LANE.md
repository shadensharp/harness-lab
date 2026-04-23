# External Benchmark Lane

## 这条链路是做什么的

`run-benchmark-eval` 是外部 repo benchmark 的 repo-first 入口。

它不会发明一套新的 scorer，而是把 benchmark manifest 物化成普通 `TaskSpec`，再接回现有 harness 的 workspace / agent / verifier / report 链路。

当前默认行为是：

- 每个 case 仍走正常的 run / eval / report 闭环
- 默认只跑一次 `current` harness 配置
- 如果你提供 `--baseline-report-id` 或 `--historical-baseline-report-id`，就把当前结果和基线报告做对比
- benchmark 自己的指标名会被保留在 metadata 里
- 仅保留指标名，不等于已经拿到官方 grader 或 leaderboard 语义

如果你要显式跑旧的 legacy 多运行对比，那应该用准备好的 suite 配合 `run-eval`，而不是把它当成 benchmark lane 的默认主线。

## 命令

```powershell
repo-harness-lab run-benchmark-eval examples/evals/repo_benchmark_sample_manifest.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY
```

可选地对照一个已落盘基线：

```powershell
repo-harness-lab run-benchmark-eval examples/evals/repo_benchmark_sample_manifest.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY --baseline-report-id <report-id>
```

命令会输出：

- `benchmark_id`
- `benchmark_metric_name`
- `benchmark_score`
- `benchmark_score_source_metric`
- `benchmark_score_semantics`
- `benchmark_score_matches_official_metric`
- `benchmark_profile_scores`
- `benchmark_baseline_comparison`
- 生成的临时 `TaskSpec` 路径
- 生成的临时 `EvalSuite` 路径
- 正常 eval report 产物路径

默认情况下，`benchmark_profile_scores` 里通常只有 `current`。

## SWE-bench Export

如果不想手写 manifest，可以先把 SWE-bench 风格实例文件导出成 manifest：

```powershell
repo-harness-lab export-swebench-manifest path\to\swebench.instances.jsonl runtime\tmp\swebench.manifest.json --benchmark-id swe-bench-verified --metric-name resolved_rate --default-verifier-command-json "[\"python\", \"-m\", \"pytest\", \"-q\"]"
```

这条命令只做一件事：

- 读取 JSON / JSON array / JSONL 的 SWE-bench 风格实例
- 把每个实例映射成固定 `git_url + repo_revision` 的 repo 任务
- 写出可被 `run-benchmark-eval` 加载的 manifest

当前主流程是：

1. 把 official-style 实例导出成 repo benchmark manifest
2. 用 `run-benchmark-eval` 跑默认的 `current` 主线
3. 如果需要项目外官方结论，再接 `grade-swebench-official`

## Manifest 结构

支持的 manifest 结构保持精简：

```json
{
  "benchmark_id": "swe-bench-sample",
  "metric_name": "resolved_rate",
  "score_semantics": "pass_rate_over_materialized_cases",
  "official_metric_equivalent": false,
  "cases": [
    {
      "instance_id": "swe-bench-001",
      "source_url": "https://example.test/swe-bench/001",
      "task_ref": "../tasks/requirement_change/qwen_provider_readme_uplift_task.json"
    }
  ]
}
```

每个 case 可以定义：

- `task`
- `task_ref`

其中 `task_ref` 适合复用已有任务定义，而不重复写整份 `TaskSpec`。

manifest 级别的两个边界字段：

- `score_semantics`
  - 说明当前 `benchmark_score` 到底表示什么
- `official_metric_equivalent`
  - `false` 表示不能把这个分数描述成 benchmark 官方 grader 结果

## Repo Revision Pinning

真实外部 Git benchmark 默认应把 `repo_revision` 当成必填。

例如：

```json
{
  "repo_source": {
    "kind": "git_url",
    "path_or_url": "https://github.com/example/project.git",
    "checkout_mode": "copy"
  },
  "repo_revision": "abc1234deadbeef"
}
```

运行时会在 run summary 里同时保存：

- `requested_repo_revision`
- `resolved_repo_revision`

这样回放和审计不会依赖一个会漂移的分支名。

## 当前边界

这条 lane 是外部 benchmark 的执行底座，不是数据集抓取器。

当前最重要的语义边界是：

- `benchmark_metric_name` 保留 benchmark 原命名
- `benchmark_score` 目前来自 `aggregate_metrics.pass_rate`
- 这个分数适合做系统内的 harness 对比
- 除非明确证明并设置 `official_metric_equivalent=true`，否则不要把它描述成官方 benchmark 分数

对 `SWE-bench Verified` 这类需要项目外公信力的结论，主链应继续接官方判分文档里的 `grade-swebench-official`。
