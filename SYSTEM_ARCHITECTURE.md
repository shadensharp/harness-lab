# 系统骨架设计

最后更新：2026-03-27 23:20:15 +08:00

## 2026-03-26 方向收口更新

- 当前系统北极星已经从“构建可运行的 Agent harness”收口为“量化同一模型在不同 harness 配置下的任务完成能力 uplift”。
- 第一阶段默认实验协议为：`模型尽量不变`、`任务尽量同源`、`预算尽量可比`、`只调整 harness`。
- 当前默认对比三档运行形态：`Bare Agent`、`Harness Basic`、`Harness Full`。
- 任务体系采用双轨：
  - `标准任务池`：用于证明 uplift
  - `开放任务入口`：用于证明泛化与真实业务可用性
- 任务选择不再只靠人工经验，必须通过 tier、difficulty、task tags、harness signals 做结构化分层。
- Agent 接入方向收口为 provider adapter，后续优先接外部模型（如千问），但不允许模型 provider 反向绑死系统主骨架。
- 展示层继续坚持 evidence-projected UI 原则：portal / dashboard / comparison 只投影已有证据链事实。

## 2026-03-27 叙事澄清：业务信息工程化，不是提示词堆料

- 项目不是靠对模型“藏信息”制造 uplift。
- `bare / basic / full` 是诊断型实验协议，用来拆解不同工程化辅助项各自贡献多少收益，不是生产环境的推荐长期配置。
- harness 真正做的是把业务信息变成稳定输入协议，包括：
  - 任务说明与成功标准结构化
  - 相关代码上下文选择
  - 任务输入注入
  - 可编辑 / 禁止编辑边界
  - 结构化输出契约
  - 隔离执行与确定性验证
- prompt 只是最终交付给模型的一层表达介质；如果没有前面的选择、约束、验证和留证，业务信息即使存在，也往往只是零散文档或人工临场复制粘贴，难以复用与比较。
- 因此本项目和纯提示词工程的区别在于：它沉淀的是一条可重复运行、可自动验收、可回放比较的业务信息管道。

## 2026-03-27 实现落地：Task Intake 已进入主链路

- 业务请求现在不必直接手写完整 `TaskSpec`，而是先进入结构化 `Task Intake`。
- `Task Intake` 里的 business request、business inputs、context paths、editable paths、forbidden paths、acceptance checks 会被 CLI 确定性 scaffold 成标准 `TaskSpec`。
- 这一步不是“再让另一个模型替你写 prompt”，而是把一次性的业务说明沉淀成可复用的运行协议。
- intake 里显式声明的 `context_paths` 已经接入 provider adapter 的上下文选择逻辑，会真实影响模型看到哪些仓库内容。
- 因而当前链路已经从概念上的“业务请求最终会变成任务”推进成可执行的入口：用户既可以先填 intake、生成任务、再进入 bare / basic / full 评测矩阵，也可以直接走 `run-intake-eval` 一步落到同模型 uplift 对比。

## 2026-03-27 跑前可视化：Task Intake Delivery Preview

- 业务请求现在不仅能直接进入 `run-intake-eval`，还能先通过 `preview-intake` 查看 delivery matrix。
- 这层 preview 会在真正执行前直接展示：
  - 任务最终会被 scaffold 成什么 `TaskSpec`
  - `bare / basic / full` 各自会交付哪些 repo tree、context files、task inputs、verifier steps
  - 当前任务为什么可能拉开 uplift，或者为什么还不容易拉开
- 这样用户在点跑之前，就能先判断：这题到底在测 repo context、task inputs、verifier plan，还是其实差异还不够明显。
## 目标

本文件定义项目的系统骨架，确保后续实现不偏离已经确认的产品定位：
这是一个面向仓库任务的、业务驱动的 Agent 执行与评测底座。

## 设计原则

### 1. Harness First
- Agent 不是系统中心，Harness 才是系统中心。
- 任何模型或 Agent 都应该通过适配器接入，而不是反过来塑造整体架构。

### 2. Contract First
- 先稳定核心对象和接口，再填充具体实现。
- 核心边界优先于“先写一个能跑的大脚本”。

### 3. Deterministic First
- 工程任务的成功判定优先依赖测试、构建、静态检查、自定义断言。
- LLM judge 只作为后续增强项。

### 4. Trace First
- Trace 不是普通日志，而是运行系统的一等产物。
- 没有可复盘证据的成功和失败，都不算真正可用的系统能力。

### 5. Local First
- 第一阶段先把本地单机闭环跑稳。
- 云端扩展、集群调度和协作能力都应建立在稳定本地闭环之上。

## 系统边界

### 这个系统负责什么
- 把业务驱动的仓库任务先整理成 `Task Intake`，再标准化为 `TaskSpec`
- 为每次运行准备隔离工作区
- 调用 Agent 完成任务
- 验证结果是否真正达成
- 记录完整 Trace 与产物
- 对多次运行做评测和对比

### 这个系统当前不负责什么
- 通用 IDE 交互体验
- 浏览器或桌面 computer-use 自动化
- 多 Agent 编排
- SaaS 协作和权限系统
- 大规模线上调度

## 核心对象

### `TaskSpec`
- 描述任务本身
- 包含任务说明、输入上下文、允许工具、预算、终止条件、成功标准

### `RunRequest`
- 描述一次具体执行
- 包含任务引用、Agent 配置、运行策略、超时与重试参数

### `WorkspaceSession`
- 描述一次运行对应的隔离工作区
- 包含 repo 副本位置、初始化状态、清理策略

### `VerifierResult`
- 描述校验结果
- 包含通过/失败、证据、命令输出、结构化错误信息

### `TraceEvent`
- 描述运行过程中的事件
- 包含模型调用、工具调用、命令执行、文件改动、校验结果等

### `EvalReport`
- 描述单任务或多任务对比的聚合结果
- 包含同一模型在不同 harness profile 下的 pass rate、成本、耗时、失败模式和回归差异

## 核心接口

### `TaskLoader`
- 负责加载、解析、校验 `TaskSpec`

### `SandboxBackend`
- 负责工作区准备、命令执行、环境清理
- 第一阶段只实现一套本地工作区后端

### `AgentAdapter`
- 负责把统一运行输入转换成具体 Agent 可理解的调用方式
- 允许后续接入不同模型、CLI Agent 或脚本 Agent

### `Verifier`
- 负责执行一组验证动作并返回结构化结果
- 支持组合多个确定性校验器

### `TraceSink`
- 负责落盘 Trace 与运行过程事件

### `RunStore`
- 负责保存 summary、artifacts 索引和评测结果

## 主执行链路

### 阶段 0：业务 Intake
- 把业务请求整理成 intake 结构
- 明确业务输入、编辑边界和验收检查
- 将 intake scaffold 成 `TaskSpec`

### 阶段 1：任务准备
- 加载 `TaskSpec`
- 校验任务字段是否合法
- 生成本次 `RunRequest`

### 阶段 2：工作区准备
- 创建隔离工作区
- 复制或初始化目标仓库
- 执行 setup

### 阶段 3：Agent 执行
- 将任务、上下文、运行限制交给 `AgentAdapter`
- 记录模型调用、命令执行、文件变更和中间结果

### 阶段 4：结果验证
- 执行 tests/build/lint/custom checks
- 聚合为 `VerifierResult`

### 阶段 5：Trace 与总结
- 生成 `summary`
- 落盘 `events`
- 输出 diff、验证结果、运行报告

### 阶段 6：评测对比
- 多次运行同一任务
- 优先对比同一模型在不同 harness profile 下的结果
- 如有需要，再扩展到不同 Agent / prompt / policy / budget

## 模块边界

### `cli`
- 负责命令行入口和参数组织
- 只做入口编排，不承载核心业务逻辑

### `config`
- 负责配置读取、路径管理、默认值和环境变量

### `domain`
- 放核心对象、协议接口、结果模型
- 是全系统共享的稳定语义层

### `tasks`
- 负责任务 intake、任务模板、任务加载、任务校验、任务示例

### `runtime`
- 负责工作区、命令执行、运行预算、隔离逻辑

### `agents`
- 放统一 Agent 接口和具体适配器实现

### `verifiers`
- 放各类校验器与校验组合逻辑

### `traces`
- 放事件模型、序列化和落盘逻辑

### `storage`
- 放运行记录存储、索引和读取逻辑

### `evals`
- 放批量运行、指标聚合、比较逻辑

### `reporting`
- 放 markdown/json/html 报告渲染

### `shared`
- 放不含业务语义的通用工具

## 时间窗口下的实现策略

### 一个月版本应该完成的核心闭环
- 一套稳定的 `TaskSpec` 结构
- 一套本地工作区 Sandbox
- 一套可运行的 `AgentAdapter`
- 一套组合式 Verifier 管线
- 一套 Trace 与 RunStore
- 一套基础 Eval 与报告能力

### 如果进度更快，可以增加
- 第二类 Agent 适配器
- 更丰富的 HTML 报告
- 更强的任务模板与样例集
- 第二套 Sandbox 后端，比如 Docker

### 如果进度变紧，要优先保住
- `TaskSpec`
- `Sandbox`
- `Verifier`
- `Trace`
- `Eval`

首先砍掉：
- 重展示层
- 第二后端
- 额外适配器
- 非核心增强功能


