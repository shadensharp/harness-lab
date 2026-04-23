# SWE-bench 官方判分接入

## 目的

这条链路解决的不是“再造一套项目内 verifier”，而是把项目产出的 patch 送进 `SWE-bench` 官方 Docker harness，用项目外部、统一的评分标准来判分。

它的角色是：

- 解决“不是项目自己出题自己判分”的公信力问题
- 把项目内部研发诊断指标和对外结论分开
- 为 `SWE-bench Verified` 主线提供官方 scorer 结果

## 当前主链

当前最小闭环是：

1. 先准备一个可运行的 eval report
2. 再把这个 report 交给 `grade-swebench-official`

通常第一步来自：

- `run-benchmark-eval` 跑出的默认 `current` report
- 或者历史遗留的 legacy smoke report

命令例如：

```powershell
python -m repo_harness_lab.cli.main grade-swebench-official <report-id> --model-name qwen-plus
```

第二步会自动：

- 按 source report 里实际存在的 harness profile 导出 `predictions.jsonl`
- 调用 `swebench.harness.run_evaluation`
- 收集官方 `results.json` / `instance_results.jsonl`
- 生成项目内可回看的 JSON / Markdown / HTML 报告
- 生成失败分析结果

如果 source report 是默认主线，导出的通常就是 `current`。
如果 source report 是遗留 smoke，导出的才会是那套旧的多运行 predictions。

## 预测文件格式

官方 SWE-bench 需要的 predictions 是 JSONL，每行一个对象：

```json
{
  "instance_id": "sympy__sympy-20590",
  "model_name_or_path": "your-model--current",
  "model_patch": "diff --git ..."
}
```

项目会从已落盘的 `patch.diff` 自动生成这份文件。

## 默认官方命令

如果当前环境已经安装 `swebench`，默认会调用：

```powershell
python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path <predictions.jsonl> --max_workers 1 --run_id <run_id>
```

也可以通过 `--official-runner-command-json` 注入自定义命令模板，用于：

- 本地包装脚本
- CI / Linux worker
- smoke 假跑

如果是在 `PowerShell` 下传一个很长的 runner 命令，优先使用 `--official-runner-command-file`，避免原生命令行把 JSON 引号吞掉。

例如：

```powershell
$runner = @(
  "wsl.exe",
  "-d",
  "Ubuntu-24.04",
  "bash",
  "-lc",
  "source ~/swebench-venv/bin/activate && python -m swebench.harness.run_evaluation --dataset_name {dataset_name} --split {split} --predictions_path {predictions_path} --max_workers {max_workers} --run_id {run_id} --instance_ids {instance_ids}"
)
$runner | ConvertTo-Json -Compress | Set-Content -Encoding utf8 runtime\tmp\official-runner-command.json
python -m repo_harness_lab.cli.main grade-swebench-official <report-id> --model-name qwen-plus --official-runner-command-file runtime\tmp\official-runner-command.json
```

## 结果分层

从这条链路开始，项目内结果必须分成两层：

- `官方统一判分结果`
  - 例如 official `resolved_instances`、`resolution_rate`
- `项目内部研发诊断指标`
  - 例如 `aggregate_metrics.pass_rate`

前者用于对外结论，后者用于调试与失败定位。

## 当前边界

- 当前主线默认是单次 `current` 运行，再和基线报告做比较
- legacy 多运行官方判分仍然可做，但主要用于遗留 smoke 和失败定位
- 对 `SWE-bench Verified` 的正式结论，应优先引用官方 scorer 结果，而不是项目内 pass rate
