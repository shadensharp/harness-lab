# 领域模型设计

最后更新：2026-03-27 12:45:00 +08:00

## 2026-03-27 任务推荐与 provider preset 补充

- `TaskBenchmarkMetadata` 现在除了服务筛选，也开始服务 recommendation：
  - 系统不限制用户只能跑固定任务
  - 但可以根据 `tier`、`difficulty`、`tags`、`harness_signals` 给出“更适合展示 harness uplift”的推荐分与推荐理由
- 这意味着任务池的语义从“任务是否可选”扩展到了“任务是否值得优先展示”。
- 这种 recommendation 仍然是软约束，不会改变 `TaskSpec` 作为任务真相源的地位。
- provider 侧则继续沿用统一 `AgentProfile` 表达外部模型接入，只是补充了更多 provider preset，降低不同 OpenAI-compatible 变体的接入摩擦。
## 2026-03-27 provider adapter 补充

- 新增 `AgentExecutionResult`，用于承载 Agent 执行后的结构化返回，包括：
  - token / cost 摘要
  - agent notes
  - 可落盘的 agent 侧 trace events
- 这样外部 model provider 接入后，运行摘要和证据链不会只剩 pass/fail，还能保留调用成本与关键中间证据。
- 第一阶段 provider-backed adapter 采用“单次结构化写文件”协议：模型返回 JSON 写入动作，harness 负责把动作安全落到工作区。
- `HarnessProfile` 除了服务 eval，对 provider-backed agent 也开始承担上下文注入分层职责：
  - `bare`：最小上下文
  - `basic`：仓库树与有限文件内容
  - `full`：更多文件上下文、task inputs 与 verifier plan
## 2026-03-26 方向对齐补充

- `TaskSpec` 现在除了任务本身外，还要携带 `TaskBenchmarkMetadata`，用于表达任务分层事实：
  - `tier`
  - `difficulty`
  - `tags`
  - `harness_signals`
- 这样任务选择不再只是“手工挑题”，而是可以被系统化筛选、归类和回放。
- `EvalRunConfig` 与 `EvalTrial` 现在需要显式表达 `HarnessProfile`，默认支持：`bare`、`basic`、`full`、`custom`。
- 这样 `EvalReport` 的 comparison views 才能从“只是看不同 label”升级成“证明不同 harness profile 的 uplift 差异”。

## 为什么先做领域模型

这一层的核心思想是：先把系统里“长期稳定的对象”定义清楚，再开始写实现。

如果没有领域模型，后面很容易出现两个问题：
- 任务定义、运行过程、验证结果混在一起
- 每增加一个功能，都要改一大片代码

这里的“领域模型”不是数据库表设计，也不是代码类名清单。
它更接近系统语义层，回答的是：
- 系统里到底有哪些关键对象
- 每个对象代表什么
- 它和其他对象的关系是什么

## 建模原则

### 1. 把“任务”和“运行”分开
- `TaskSpec` 表示任务本身
- `RunRequest` 表示一次具体执行

原因：
- 同一个任务会被多次运行
- 每次运行可能换 Agent、换预算、换 policy
- 如果把任务和运行耦在一起，就很难做批量评测

### 2. 把“过程证据”和“结果判断”分开
- `TraceEvent` 负责记录过程
- `VerifierResult` 负责判断结果

原因：
- Trace 告诉你“发生了什么”
- Verifier 告诉你“结果是否成立”
- 两者混在一起，会导致系统既不利于调试，也不利于评测

### 3. 把“稳定对象”和“运行产物”分开
- 稳定对象放在领域模型里
- 临时 diff、命令输出、日志片段、HTML 报告属于运行产物

原因：
- 领域模型应该稳定
- 运行产物可以增减变化
- 不应该让产物格式反过来污染系统核心语义

## 核心对象总览

```text
TaskSpec
  -> RunRequest
    -> WorkspaceSession
    -> TraceEvent[]
    -> VerifierResult[]
    -> RunSummary

EvalCase
  -> EvalTrial[]
  -> EvalReport
```

## 任务相关对象

### `TaskSpec`

作用：
- 作为任务真相源
- 定义任务是什么、输入上下文是什么、成功标准是什么

建议字段：
- `task_id`
- `title`
- `description`
- `task_type`
- `repo_source`
- `repo_revision`
- `inputs`
- `constraints`
- `success_criteria`
- `setup_steps`
- `verifier_plan`
- `metadata`

关键思想：
- `TaskSpec` 不能只是一段 prompt
- 它必须把“可执行的任务语义”表达出来

这里的子概念：
- `constraints`
  - 表示限制条件，比如不能联网、不能改某些目录、预算上限是多少
- `success_criteria`
  - 表示成功标准，比如哪些测试必须通过、哪些文件必须变更、哪些行为必须满足
- `verifier_plan`
  - 表示后续要如何验证，不一定等于实际校验结果

### `RepoSource`

作用：
- 描述任务依赖的目标仓库来源

建议字段：
- `kind`
- `path_or_url`
- `default_branch`
- `checkout_mode`

关键思想：
- 先把仓库来源抽象出来，后面才有可能从本地路径扩展到镜像、副本或远程快照

### `TaskInputBundle`

作用：
- 描述任务附带的输入材料

可能包括：
- issue 文本
- 复现脚本
- 错误日志
- 需求说明
- 样例输入输出

关键思想：
- 业务任务不只有“任务描述”，还经常带附件式上下文
- 单独抽出来，比把所有内容拼进 description 更清晰

## 运行相关对象

### `RunRequest`

作用：
- 描述某个任务的一次具体执行请求

建议字段：
- `run_id`
- `task_id`
- `agent_profile`
- `sandbox_profile`
- `budget_policy`
- `timeout_policy`
- `tool_policy`
- `labels`

关键思想：
- `TaskSpec` 回答“做什么”
- `RunRequest` 回答“这次怎么做”

比如：
- 同一任务可以有不同 Agent
- 同一任务可以有不同预算
- 同一任务可以有不同工具权限

### `WorkspaceSession`

作用：
- 描述本次运行对应的隔离工作区

建议字段：
- `workspace_id`
- `repo_root`
- `base_revision`
- `status`
- `created_at`
- `cleanup_policy`

关键思想：
- 工作区是运行时对象，不是任务对象
- 它负责隔离执行环境，避免不同 trial 相互污染

### `RunSummary`

作用：
- 描述一次运行的最终聚合信息

建议字段：
- `run_id`
- `task_id`
- `status`
- `started_at`
- `finished_at`
- `duration_ms`
- `cost_summary`
- `changed_files`
- `verifier_outcome`
- `artifact_index`

关键思想：
- `RunSummary` 不是全部过程，只是最终摘要
- 它主要用于快速浏览、列表展示和后续报告汇总

## 过程证据对象

### `TraceEvent`

作用：
- 记录运行过程中发生的结构化事件

建议字段：
- `event_id`
- `run_id`
- `timestamp`
- `event_type`
- `stage`
- `payload`

常见事件类型：
- `run_started`
- `workspace_prepared`
- `agent_invoked`
- `command_executed`
- `file_changed`
- `verifier_started`
- `verifier_finished`
- `run_finished`

关键思想：
- TraceEvent 应尽量保持追加式、不可变
- 它是证据流，不应该被当成最终摘要来反复覆盖

这里的子概念：
- `payload`
  - 放事件特定内容
  - 例如命令行、返回码、diff 摘要、文件路径、token 使用量

### `FileChangeRecord`

作用：
- 描述一次运行里对文件的变更摘要

建议字段：
- `path`
- `change_type`
- `diff_excerpt`
- `line_count_delta`

关键思想：
- 文件变更是工程任务里很重要的证据，值得作为独立结构存在

### `CommandExecutionRecord`

作用：
- 描述一次命令执行结果

建议字段：
- `command`
- `cwd`
- `exit_code`
- `stdout_excerpt`
- `stderr_excerpt`
- `duration_ms`

关键思想：
- 命令执行是工程型 Agent 的核心行为之一
- 单独建模后，后续分析失败模式会更方便

## 验证相关对象

### `VerifierPlan`

作用：
- 描述这次任务计划执行哪些校验动作

建议字段：
- `steps`
- `required_passes`
- `failure_policy`

关键思想：
- “要怎么验” 和 “验出来是什么结果” 是两回事

### `VerifierResult`

作用：
- 描述一次校验动作或一组校验动作的结果

建议字段：
- `verifier_name`
- `status`
- `evidence`
- `command_results`
- `started_at`
- `finished_at`

关键思想：
- VerifierResult 必须是 evidence-first
- 不只是给一个 pass/fail，要能解释为什么

### `VerificationEvidence`

作用：
- 承载验证结论背后的证据

可能包括：
- 测试结果
- 构建结果
- 静态检查结果
- 自定义断言结果

关键思想：
- 后面做报告和失败分析时，真正有价值的是证据，不只是状态值

## 评测相关对象

### `EvalCase`

作用：
- 描述评测中的一个任务案例

建议字段：
- `case_id`
- `task_spec_ref`
- `run_matrix`
- `notes`

关键思想：
- EvalCase 是任务在评测里的视角
- 它强调“这个任务要怎么被反复试验”

### `EvalTrial`

作用：
- 描述某个案例中的一次试验

建议字段：
- `trial_id`
- `case_id`
- `run_request`
- `run_summary`

关键思想：
- Trial 是评测最小重复单元
- 它是做稳定性、成本和波动分析的基础

### `EvalReport`

作用：
- 描述评测汇总结果

建议字段：
- `suite_id`
- `case_results`
- `aggregate_metrics`
- `comparison_views`

关键思想：
- `EvalReport` 的价值不只是报通过率
- 它还要支持比较不同 Agent / policy / budget 的表现差异

## 最小必选模型

第一阶段代码里最先必须稳定下来的对象是：
- `TaskSpec`
- `RunRequest`
- `WorkspaceSession`
- `TraceEvent`
- `VerifierResult`
- `RunSummary`
- `EvalCase`
- `EvalTrial`
- `EvalReport`

## 建模取舍

### 为什么现在不把字段设计得特别重？
- 因为当前目标是先支撑一套稳定闭环
- 字段过重，反而会让第一版实现和维护成本过高

### 为什么依然要先建模，而不是边写边补？
- 因为这个项目的价值就在于系统边界清楚
- 如果连最基本对象都不稳定，后面的 Sandbox、Verifier、Eval 都会互相污染

## 面向实现的提醒

- 领域模型优先放在 `domain/`
- 模型命名要稳定，不要跟具体后端强绑定
- 能用组合关系表达的，不要急着做继承层次
- 第一阶段以 dataclass 或 pydantic 这种清晰结构为主，不要过度框架化

