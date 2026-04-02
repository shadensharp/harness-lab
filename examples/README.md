# 示例目录

## qwen provider uplift 示例

这套示例用于演示同一个外部模型在 `bare / basic / full` 三档 harness profile 下的结果差异。

推荐优先跑多信号 suite：
- `examples/evals/qwen_provider_multi_signal_uplift_suite.json`
- 它同时覆盖两类差异来源：
  - `repo_context`：让 `bare` 明显弱于 `basic / full`
  - `task_inputs + verifier_plan`：让 `full` 明显强于 `bare / basic`

单题 smoke suite 仍然保留：
- `examples/evals/qwen_provider_uplift_suite.json`
- 它更快，适合先验证 provider 通路与页面链路。

前置条件：
- 已设置 `DASHSCOPE_API_KEY`
- 从项目根目录运行命令
- 当前环境里可直接使用 `python`

运行命令：

```powershell
repo-harness-lab run-eval examples/evals/qwen_provider_multi_signal_uplift_suite.json
```

如果尚未安装控制台脚本，也可以用：

```powershell
python -m repo_harness_lab.cli.main run-eval examples/evals/qwen_provider_multi_signal_uplift_suite.json
```

如果只想快速 smoke 一次单题 provider uplift，也可以用：

```powershell
python -m repo_harness_lab.cli.main run-eval examples/evals/qwen_provider_uplift_suite.json
```

如果想先把一段业务需求整理成可执行的 TaskSpec scaffold，可以先看 intake 模板，再把 intake JSON 转成任务文件：

```powershell
python -m repo_harness_lab.cli.main show-task-intake-template
python -m repo_harness_lab.cli.main scaffold-task-spec examples/intakes/provider_release_input_task_intake.json --write runtime/tmp/provider_release_input_task.json
```

如果想在真正开跑前，先看这份 intake 会如何被系统理解，以及 `bare / basic / full` 各自会交付哪些信息，可以先用：

```powershell
python -m repo_harness_lab.cli.main preview-intake examples/intakes/provider_release_input_task_intake.json
```

如果想直接从一张业务 intake 跑成同模型 bare/basic/full uplift 对比，而不是自己再手写 suite，可以用：

```powershell
python -m repo_harness_lab.cli.main run-intake-eval examples/intakes/provider_release_input_task_intake.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY
```

这条命令会自动：
- scaffold `TaskSpec`
- 生成单 case bare/basic/full suite
- 跑完整 eval / comparison / dashboard
- 把中间产物落到 `runtime/tmp/*.task.json` 和 `runtime/tmp/*.suite.json`

如果想先看系统推荐哪些任务更容易体现 harness uplift，可以用：

```powershell
python -m repo_harness_lab.cli.main recommend-tasks examples/tasks --prefer-signal repo_context --prefer-signal task_inputs --prefer-signal verifier_plan
```

推荐结果现在也会进入已落盘的 eval 事实里：
- suite case summary 会保存 `recommendation_score` 与 `recommendation_reasons`
- `runtime/reports/uplift-dashboard.html` 首页会显示 `Recommended Task Shapes`
- `runtime/reports/harness-portal.html` 会显示 `Recommended Uplift Tasks`
- `runtime/reports/uplift-dashboard.html` 与 `runtime/reports/harness-portal.html` 现在还会显示 `Open Task Entry`
- `Open Task Entry` 会基于当前 uplift 证据给出 `list-task-pool` / `recommend-tasks` 的命令模板
- 这样用户不必先进 suite 页，也能先看到“为什么这类任务更容易拉开 bare / basic / full 差距”，以及下一步具体该怎么跑

如果已经跑过 suite，后续只想基于已落盘的 eval JSON 与 run evidence 重渲 suite / compare / uplift 页面，可以用：

```powershell
python -m repo_harness_lab.cli.main render-eval-report qwen-provider-multi-signal-uplift-suite
```

示例设计：
- 第一题要求把 `README.md` 的标题更新为 `docs/target_title.txt` 中的目标标题。
- 第二题要求根据任务输入同步 `config/release.env` 与 `docs/release_summary.md`。
- `bare` 只会看到仓库树，不会拿到目标文件内容，也不会拿到任务输入。
- `basic` 会拿到更多仓库上下文，但仍不会拿到 task inputs / verifier plan。
- `full` 会拿到更多仓库上下文、task inputs 与 verifier plan，因此更容易在第二题上继续拉开差距。
- 跑完后可以直接查看 `runtime/reports/uplift-dashboard.html`。
- 用户依然可以自行传入任意任务；`recommend-tasks` 只是给“更适合做 uplift 展示”的任务一个优先级建议。

## 线上 live portal 部署

如果要把 live portal 真正挂到公网，让外部用户直接在网页里：

- 输入任务
- 填公开 Git 仓库地址
- 在网页里拿到 `bare / basic / full` 结果

请看：

- `HOSTED_PORTAL_DEPLOYMENT.md`
- `examples/deployment/portal.env.example`
- `examples/deployment/start_hosted_portal.sh`
- `examples/deployment/repo-harness-lab-portal.service`
- `examples/deployment/nginx.repo-harness-lab-portal.conf`


