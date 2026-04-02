# Harness Evidence Report

最后更新：2026-04-01

## 结论先行

- 这个项目的主骨架已经很清楚：`业务 Intake -> TaskSpec -> Harness Delivery -> Workspace Run -> Verifier -> Trace/Store -> Eval/Report`。
- 当前最重要的三档不是任务池的 `curated / rolling / open`，而是运行档位 `bare / basic / full`。
- `bare / basic / full` 的差异并不只是“上下文越来越多”。
- 最强证据来自第二道示例题：`basic` 和 `full` 的 `context_file_count` 一样，都是 `3`，但 `basic` 失败、`full` 成功；因此差异不能归因于“只是多塞了几个文件”，而是 `full` 额外注入了 `task_inputs + verifier_plan`。
- 因而本项目要讲的不是“prompt 写长一点模型就更强”，而是“harness 把业务信息、执行边界、验收标准、运行证据工程化之后，模型能力才会稳定释放出来”。

## 一、我们项目的真实架构

### 1. Intake 层：把一次性业务描述变成稳定运行协议

源码证据：
- `src/repo_harness_lab/tasks/intake.py`

这层要做的事：
- 接收业务请求、业务输入、上下文路径、可编辑路径、禁改路径、验收检查。
- 把这些字段转成稳定的 `TaskSpec`，而不是每次临场拼 prompt。
- 自动推断 `harness_signals`，例如：
  - 有 `context_paths` 就推断 `repo_context`
  - 有 `business_inputs` 就推断 `task_inputs`
  - 需要改多个文件就推断 `multi_file_edit`
  - 有 `acceptance_checks` 就推断 `verifier_plan`

为什么这一步关键：
- 它把“业务信息”从人脑里的临时说明，变成机器可复用的契约对象。
- 这一步已经超出 prompt engineering，因为它决定的不只是模型看到什么，还决定后面的编辑边界、验收和对比维度。

### 2. TaskSpec 层：稳定领域模型

源码证据：
- `src/repo_harness_lab/domain/task_spec.py`

这里稳定了几个关键对象：
- `TaskInputBundle`
- `TaskConstraints`
- `SuccessCriteria`
- `VerifierPlan`
- `TaskBenchmarkMetadata`
- `HarnessProfile`
- `TaskSelectionTier`

这层要做的事：
- 定义任务真相源。
- 明确任务输入、约束、成功标准、评测标签、harness 信号。

为什么这一步关键：
- 没有这层，后面的运行、报告、对比都只能围绕一段自由文本做脆弱推断。

### 3. Delivery 层：把同一任务投递成 bare/basic/full 三种运行协议

源码证据：
- `src/repo_harness_lab/agents/adapters/provider_json_edit.py`
- `src/repo_harness_lab/tasks/intake_preview.py`

这层要做的事：
- 选择是否附带 repo tree
- 选择多少 context files
- 是否注入 task inputs
- 是否注入 verifier plan
- 把这些差异先可视化成 `harness_delivery_matrix`

当前三档实现是：
- `bare`
  - `include_tree=True`
  - `include_inputs=False`
  - `include_verifier_plan=False`
  - `max_context_files=0`
- `basic`
  - `include_tree=True`
  - `include_inputs=False`
  - `include_verifier_plan=False`
  - `max_context_files=4`
- `full`
  - `include_tree=True`
  - `include_inputs=True`
  - `include_verifier_plan=True`
  - `max_context_files=12`

为什么这一步关键：
- 这里明确说明三档差异是多维 delivery policy，而不是一个“prompt 长度滑条”。

### 4. Workspace 层：隔离运行环境

源码证据：
- `src/repo_harness_lab/runtime/workspace.py`

这层要做的事：
- 复制源仓库到临时 workspace
- 在隔离副本里执行 agent
- 运行后清理或保留

为什么这一步关键：
- 这是 harness，不是 prompt。
- 没有隔离工作区，就无法稳定回放、比较 diff，也无法避免污染源仓库。

### 5. Agent Adapter 层：统一调用模型，但强制输出契约和写入边界

源码证据：
- `src/repo_harness_lab/agents/adapters/provider_json_edit.py`

这层要做的事：
- 把 TaskSpec 和 delivery snapshot 转成用户提示。
- 强制模型只返回 JSON。
- 只允许写相对路径。
- 对写入路径做 `editable_paths` 和 workspace 边界校验。

为什么这一步关键：
- 这不是“给模型更多背景”的问题。
- 这里同时在做：
  - 输入结构化
  - 输出结构化
  - 写入约束
  - 运行证据采样

### 6. Verifier 层：确定性验收

源码证据：
- `src/repo_harness_lab/verifiers/command.py`

这层要做的事：
- 执行 test/build/lint/assertion/command 等验收步骤
- 记录每一步 exit code、是否 required、是否 passed
- 聚合成 `VerifierResult`

为什么这一步关键：
- 这一步彻底说明本项目不是“看模型回答像不像对”。
- 最终结果由确定性检查决定，不由主观 judge 决定。

### 7. Orchestrator / Trace / Store / Report 层：把运行变成可回放证据

源码证据：
- `src/repo_harness_lab/runtime/runner.py`
- `src/repo_harness_lab/storage/run_store.py`
- `src/repo_harness_lab/reporting/run_evidence.py`
- `src/repo_harness_lab/reporting/uplift_html.py`
- `src/repo_harness_lab/evals/runner.py`

这层要做的事：
- 准备 run 目录
- 记录 `events.jsonl`
- 写 `summary.json`
- 写 `patch.diff`
- 写 `verifier_results.json`
- 生成 run report、eval report、compare report、uplift dashboard
- 聚合 profile 级指标与失败摘要

为什么这一步关键：
- 这里说明项目真正要产出的不是一次成功演示，而是一套可对比、可复盘、可解释的证据链。

## 二、不同“档位”到底指什么

这里其实有两组“档位”，不要混淆。

### A. 运行档位：`bare / basic / full`

这是当前项目最重要的三档。

含义：
- `bare`：最小 delivery，只给任务文本和基础 repo tree
- `basic`：补 repo context files
- `full`：在 basic 上继续补 task inputs 和 verifier plan

它们用于回答的问题：
- 仓库上下文本身贡献了多少？
- 结构化任务输入贡献了多少？
- verifier-aware delivery 贡献了多少？

### B. 任务池档位：`curated / rolling / open`

源码证据：
- `src/repo_harness_lab/domain/task_spec.py`
- `src/repo_harness_lab/tasks/catalog.py`

含义：
- `curated`：精选基准题，最适合重复对比
- `rolling`：可持续更新的标准池
- `open`：开放任务入口，允许泛化演示

它们回答的是“题怎么选”，不是“运行时给模型什么”。

## 三、为什么能证明差异来自 harness，而不是三档上下文丰富度不同

## 证据 1：实验控制变量已经写死在源码里

源码证据：
- `src/repo_harness_lab/cli/commands/evals.py`
- `src/repo_harness_lab/evals/runner.py`

事实：
- `run-intake-eval` 生成 suite 时，三条 trial 共享同一个 `AgentProfile`。
- 变化的只有 `HarnessProfile.BARE / BASIC / FULL`。
- `SimpleEvalRunner` 会把 `harness_profile` 写入 label 和 metadata，但不会替换模型。

这意味着：
- 模型不变
- 任务不变
- workspace/verifier/report 链路不变
- 只切换 harness profile

所以这是受控对比，不是“换了模型顺便多给点信息”。

## 证据 2：三档实现本身就是多维 harness 开关，不是单维上下文多少

源码证据：
- `src/repo_harness_lab/agents/adapters/provider_json_edit.py`

`_snapshot_settings()` 里可以直接看到：
- `bare -> basic` 主要增加的是 context files
- `basic -> full` 不只是继续加 context cap，更关键的是：
  - `include_inputs=False -> True`
  - `include_verifier_plan=False -> True`

因此三档不是一个“上下文越多越好”的单轴变量，而是：
- repo tree
- context files
- task inputs
- verifier plan

四类交付能力的组合。

## 证据 3：最强因果证据来自 release-input 这道题

源码证据：
- `examples/tasks/requirement_change/qwen_provider_release_input_uplift_task.json`
- `runtime/runs/run-f86e31153985/events.jsonl`
- `runtime/runs/run-0c6a3f066d08/events.jsonl`
- `runtime/reports/qwen-provider-multi-signal-uplift-suite.md`

关键事实：
- 这道题显式声明了 `task_inputs` 和 `verifier_plan`
- `basic` run：`run-f86e31153985`
  - `harness_profile=basic`
  - `context_file_count=3`
  - `tree_entry_count=3`
  - 最终失败
  - note: `guess release spec from repo context`
- `full` run：`run-0c6a3f066d08`
  - `harness_profile=full`
  - `context_file_count=3`
  - `tree_entry_count=3`
  - 最终成功
  - note: `apply release spec 2026.04.0 canary Paper Lantern`

这组证据最强的地方在于：
- `basic` 和 `full` 的上下文文件数量相同
- 仓库树条目数量也相同
- 但结果相反

因此这里的 uplift 不能解释成“full 只是多给了更多文件”。

唯一与源码实现一致的解释是：
- `full` 注入了 `release_spec`
- `full` 注入了 verifier step 信息
- `basic` 没有拿到这些结构化输入

也就是说，这里体现的是 harness 的“任务输入注入 + verifier-aware delivery”能力，而不是单纯的 context richness。

## 证据 4：单元测试把这个因果关系写成了回归断言

源码证据：
- `tests/unit/test_cli_intake_eval.py`

测试里做了一个非常干净的因果隔离：
- fake provider 会检查 prompt 里是否出现：
  - `release_version=2026.04.0`
  - `release_channel=canary`
  - `codename=Paper Lantern`
  - `release-summary-check`
- 如果这些 token 出现，返回正确写入
- 如果不出现，就返回 guessed 内容

然后测试断言：
- `bare.pass_rate == 0.0`
- `basic.pass_rate == 0.0`
- `full.pass_rate == 1.0`

这说明什么：
- 系统已经把“哪些 harness 信号应该出现在 full 而不是 basic”固化成了自动回归测试。
- 这不再是口头叙事，而是代码级、可重复执行的因果实验。

## 证据 5：harness 的大量关键能力根本不在“上下文注入”维度里

源码证据：
- `src/repo_harness_lab/runtime/workspace.py`
- `src/repo_harness_lab/agents/adapters/provider_json_edit.py`
- `src/repo_harness_lab/verifiers/command.py`
- `src/repo_harness_lab/runtime/runner.py`

这些都不是上下文工程：
- workspace 隔离复制
- 输出 JSON 契约
- 写入路径白名单和越界保护
- verifier 执行与 required-pass 聚合
- trace 落盘
- diff/report/comparison 生成

如果一个系统只有“多塞上下文”，它做不到这些事。

所以更准确的说法是：
- context engineering 只是 harness 的一个子集
- 本项目的 harness 是一个受控执行与评测系统

## 四、不同 harness 的强指标应该怎么讲

当前仓库里已经落地的强指标，不要只讲 pass rate。

### 1. Profile 级结果指标

源码证据：
- `src/repo_harness_lab/evals/runner.py`

已实现：
- `pass_rate`
- `passed_trials`
- `average_duration_ms`
- `median_duration_ms`
- `pass_rate_delta`
- `average_duration_delta_ms`

这是最基础的 uplift 指标。

### 2. Profile 级失败解释指标

已实现：
- `profile_failure_summary`
  - `failed_trials`
  - `top_reasons`

意义：
- 不只看哪个 profile 失败
- 还看它主要是因为什么失败

### 3. Tag / Signal 维度的结构化对比

已实现：
- `tag_profile_summary`
- `signal_profile_summary`

意义：
- 可以回答“是哪些类型任务更能拉开 bare/basic/full”
- 也可以回答“repo_context、task_inputs、verifier_plan 哪类信号最有效”

### 4. Run 级 Harness 输入证据

源码证据：
- `src/repo_harness_lab/reporting/run_evidence.py`

已实现：
- `harness_profile`
- `context_file_count`
- `tree_entry_count`
- `truncated_file_count`
- `write_count`
- token / 成本

意义：
- 这让 compare page 不只是显示输赢，而是显示“到底多交付了什么”。

### 5. 我建议下一步补上的更强指标

这些指标还没完全落地，但很值得做：

- `input_delivery_vector`
  - 是否带 tree
  - context file 数
  - context char 数
  - 是否带 task inputs
  - verifier step 数
- `changed_file_precision`
  - 改动文件中有多少命中 expected_changed_files
- `verifier_step_pass_vector`
  - 每个 verifier step 的通过率
- `failure_concentration`
  - 某 profile 的失败是否高度集中在一类原因
- `reproducibility_rate`
  - 同 profile 多次重跑的稳定性
- `uplift_per_extra_token`
  - 每多付出一单位上下文或 token，换来多少 pass_rate 提升

如果你要做“强有力指标”，建议优先实现前 3 个。

## 五、从 Claude Code 可以复用/借鉴什么

我重点看过的能力点：
- token budget
- tool orchestration
- shell permission matching
- compact / session memory

### 1. 最值得借鉴：预算跟踪，而不是固定 context cap

Claude Code 里值得借鉴的点：
- 不是只设一个硬 token 上限
- 还跟踪 continuation 次数和 diminishing returns
- 在收益变小时主动停止

对我们项目的价值：
- 现在我们的 `bare/basic/full` 还是固定 cap
- 下一步可以把 profile 从“静态档位”升级成“预算策略”
- 比如：
  - `basic`: 先给 4 个文件，不够再补 2 个
  - `full`: 在 verifier 失败后按失败步骤回补相关上下文

### 2. 很值得借鉴：工具调用分批与并发安全判定

Claude Code 里值得借鉴的点：
- 把工具调用区分为可并发的只读批次和必须串行的写入批次

对我们项目的价值：
- 如果后面从“structured write provider”扩到“真实工具代理”
- 这套并发安全划分会非常重要
- 特别适合未来的：
  - 读仓库
  - 跑 grep
  - 跑测试
  - 再执行写入

### 3. 很值得借鉴：shell 规则匹配和权限建议

Claude Code 里值得借鉴的点：
- prefix/exact/wildcard 三类 shell 权限规则
- 对未来交互式 harness 很关键

对我们项目的价值：
- 现在我们只有 `allowed_tools` 和路径边界
- 如果以后引入更真实的 shell agent，这套规则会比“allow_shell=true/false”细很多

### 4. 可借鉴但不要现在重投入：compact / session memory

Claude Code 里值得借鉴的点：
- compact 不是简单摘要，而是预算化、分阶段、可恢复的上下文压缩

对我们项目的价值：
- 如果后面做 long-running portal / live session / multi-turn task refinement，很有用
- 但对当前项目不是 P0

### 5. 不建议现在抄的大块

暂时不要跟进：
- 大型终端 UI
- bridge / remote / desktop
- 插件系统
- 语音
- MCP 全家桶

原因很简单：
- 我们现在的北极星是量化 harness uplift
- 不是做一个 Claude Code 替代品

## 六、下一步最应该做什么

按优先级，我建议这样推进：

### P0：把“强指标”补齐

最先做：
- 在 trace 里再记录：
  - `included_input_names`
  - `included_verifier_steps`
  - `selected_context_paths`
  - `prompt_char_count`
- 在 compare/eval 里增加：
  - `input_delivery_vector`
  - `verifier_step_pass_vector`
  - `changed_file_precision`

这样你后面讲“差异来自 harness 而不是上下文更丰富”时，证据会更硬。

### P1：把 profile 从静态档位升级成策略档位

现在：
- `bare/basic/full` 本质还是三组固定开关

下一步：
- 做成 strategy
  - `context selection strategy`
  - `input injection strategy`
  - `verifier-aware retry strategy`
  - `budget strategy`

这样项目会更像真正的 harness engineering，而不是“三套 prompt 模板”。

### P2：引入 verifier-aware adaptive delivery

目标：
- 第一次跑失败后，不是盲目重试
- 而是根据哪个 verifier step 失败，回补对应输入或上下文

这是最能体现“harness 不是上下文工程”的一步，因为它把验证反馈闭环接进 delivery policy。

## 七、面试时最稳的一句话

可以直接这么讲：

> 我这个项目不是在比谁 prompt 写得更长，而是在做一个受控的 harness 实验系统。  
> 同一模型、同一任务、同一验收下，只切换 bare/basic/full 三种交付策略。  
> 其中 full 的提升并不只是来自更多 repo context，最强证据是 release-input 这题里 basic 和 full 的 context_file_count 一样都是 3，但 basic 失败、full 成功，因为 full 额外拿到了结构化 task inputs 和 verifier plan。  
> 所以我证明的是 harness engineering 对模型能力释放的贡献，而不是单纯上下文堆料。

