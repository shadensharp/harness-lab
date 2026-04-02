# 核心接口设计

最后更新：2026-03-27 12:45:00 +08:00

## 2026-03-27 recommendation / preset 补充

- `TaskCatalog` 虽然当前还没有单独抽成 Protocol，但它的接口语义已经从“scan / select”扩展到“recommend”：
  - `scan / select` 回答“有哪些任务、按什么条件筛出来”
  - `recommend` 回答“哪些任务更适合优先拿来展示 harness uplift，为什么”
- 这条边界的意义是：系统可以推荐，但不能替用户限制任务来源。
- `AgentAdapter` 的外部接入边界保持不变；新增的 provider preset 仍然只是 factory 层的便利能力，不应该泄漏到 runner / verifier / report 的主接口里。
- `recommend-tasks` 的加入也说明：CLI 不只负责执行任务，还要负责把系统已有的结构化认知投影成用户能直接消费的建议。
## 2026-03-27 provider layer 补充

- `AgentAdapter.execute()` 不再只是“执行结束就返回空值”，而是返回 `AgentExecutionResult`，把 agent usage、notes、agent-generated trace events 结构化交回 runner。
- 这样 `RunOrchestrator` 才能在不感知具体 provider 细节的前提下，把外部模型调用的 token、notes 和关键事件写回 `RunSummary` 与 `events.jsonl`。
- Agent 层现在形成两段式稳定边界：
  - `provider layer`：负责与外部模型 API 通信
  - `adapter layer`：负责 prompt/context packing、输出解释和工作区写入
- 这种拆分的取舍是：外部 SDK / HTTP 差异停留在 provider 内部，harness 主闭环继续只依赖 `AgentAdapter`。
## 2026-03-26 方向对齐补充

- `AgentAdapter` 仍然是模型接入的唯一稳定边界；后续接千问或其他 provider 时，应通过新的 adapter / provider layer 接入，而不是改写主闭环。
- `EvalRunner` 后续的核心职责不再只是批量运行，还包括产出能直接解释 uplift 的 profile / tag / signal 对比视图。
- 任务池扫描和筛选虽然不一定都抽成 Protocol，但它们的语义边界已经成立：系统必须支持标准任务池的结构化选择，而不是只支持单文件任务装载。

## 为什么要先定接口

系统骨架解决的是“模块怎么分”，领域模型解决的是“系统里有什么”，核心接口解决的是“这些模块怎么协作”。

如果没有清晰接口，常见问题是：
- CLI 直接操纵底层实现
- Agent 逻辑和 Sandbox 逻辑混在一起
- Verifier 和 Report 共用一堆不稳定数据结构

所以接口层的价值是：
- 限制耦合
- 固定协作方式
- 让实现可以替换

## 接口设计原则

### 1. 单一职责
- 一个接口尽量只回答一个主问题

### 2. 先定输入输出，再谈内部实现
- 接口关注契约，不关注内部怎么完成

### 3. 优先服务主闭环
- 先把单机本地闭环设计好
- 不为了未来可能的云端能力把接口提前做复杂

### 4. 尽量返回结构化结果
- 不要到处传裸字符串
- 结构化结果更利于 Trace、Report 和 Eval 复用

## 核心接口总览

```text
TaskLoader
SandboxBackend
AgentAdapter
Verifier
TraceSink
RunStore
EvalRunner
Reporter
```

## `TaskLoader`

负责问题：
- 如何把任务文件或任务定义加载成 `TaskSpec`

典型输入：
- 任务路径
- 任务原始内容

典型输出：
- `TaskSpec`

核心思想：
- 任务加载和任务执行分开
- 这样后面任务来源可以从本地文件扩展到模板生成、数据集导入或外部系统同步

高层接口示意：

```python
class TaskLoader(Protocol):
    def load(self, source: str) -> TaskSpec: ...
```

## `SandboxBackend`

负责问题：
- 如何准备工作区、执行命令、清理环境

典型输入：
- `RunRequest`
- `TaskSpec`
- 命令与执行上下文

典型输出：
- `WorkspaceSession`
- `CommandExecutionRecord`

核心思想：
- Sandbox 负责“在哪跑”和“怎么受控地跑”
- 它不负责决定“跑什么任务”或“结果是否成功”

这里的子概念：
- `Sandbox`
  - 不一定指容器
  - 在 V1 里可以只是一个隔离工作区和受控执行器
- `Backend`
  - 指具体实现后端
  - 第一阶段可以是本地目录复制，后面可以增加 Docker

高层接口示意：

```python
class SandboxBackend(Protocol):
    def prepare(self, task: TaskSpec, request: RunRequest) -> WorkspaceSession: ...
    def run_command(self, workspace: WorkspaceSession, command: list[str]) -> CommandExecutionRecord: ...
    def cleanup(self, workspace: WorkspaceSession) -> None: ...
```

## `AgentAdapter`

负责问题：
- 如何把统一的运行输入交给具体 Agent 执行

典型输入：
- `TaskSpec`
- `RunRequest`
- `WorkspaceSession`

典型输出：
- 运行过程事件
- 文件变更
- Agent 结果摘要

核心思想：
- Adapter 的作用是把统一系统契约翻译成具体 Agent 能理解的调用方式
- 这和直接把模型 SDK 写进 Runner 不一样

这里的子概念：
- `Adapter`
  - 适配器模式
  - 核心价值是隔离外部差异，保护内部骨架不被外部依赖绑死

高层接口示意：

```python
class AgentAdapter(Protocol):
    def execute(self, task: TaskSpec, request: RunRequest, workspace: WorkspaceSession) -> AgentExecutionResult: ...
```

说明：
- 第一阶段可以让 AgentAdapter 通过回调或 TraceSink 直接产生日志事件
- 不必过早设计特别复杂的多阶段返回值

## `Verifier`

负责问题：
- 如何判断一次运行是否真正完成任务

典型输入：
- `TaskSpec`
- `RunRequest`
- `WorkspaceSession`

典型输出：
- `VerifierResult`

核心思想：
- Verifier 不是读 Agent 自述
- Verifier 是独立地检查任务结果

这里的子概念：
- `deterministic verifier`
  - 通过测试、构建、静态检查、自定义断言给出稳定判断
  - 比 LLM judge 更适合作为第一版主判断机制

高层接口示意：

```python
class Verifier(Protocol):
    def verify(self, task: TaskSpec, request: RunRequest, workspace: WorkspaceSession) -> VerifierResult: ...
```

## `TraceSink`

负责问题：
- 如何记录结构化事件流

典型输入：
- `TraceEvent`

典型输出：
- 无返回值或落盘确认

核心思想：
- TraceSink 只做记录，不做业务判断
- 这样 Trace 才能作为独立证据流被复用

高层接口示意：

```python
class TraceSink(Protocol):
    def append(self, event: TraceEvent) -> None: ...
```

## `RunStore`

负责问题：
- 如何持久化运行摘要、索引和产物引用

典型输入：
- `RunSummary`
- artifact 索引

典型输出：
- 查询结果

核心思想：
- `TraceSink` 负责过程事件
- `RunStore` 负责最终摘要和检索
- 两者分开后，回放和列表查询都会更清晰

高层接口示意：

```python
class RunStore(Protocol):
    def save_summary(self, summary: RunSummary) -> None: ...
    def load_summary(self, run_id: str) -> RunSummary: ...
    def list_runs(self, limit: int) -> list[RunSummary]: ...
```

## `EvalRunner`

负责问题：
- 如何对一个或多个任务做重复运行和结果聚合

典型输入：
- `EvalCase`
- trial 配置

典型输出：
- `EvalReport`

核心思想：
- EvalRunner 不是简单 for 循环跑几次
- 它的职责是把对比、重复试验、统计聚合组织起来

高层接口示意：

```python
class EvalRunner(Protocol):
    def run_case(self, case: EvalCase) -> EvalReport: ...
```

## `Reporter`

负责问题：
- 如何把结构化结果渲染成人可读输出

典型输入：
- `RunSummary`
- `EvalReport`

典型输出：
- markdown / json / html

核心思想：
- 报告层是消费结构化结果，不是生成真相源
- 真相源仍然是 Trace、VerifierResult、RunSummary

高层接口示意：

```python
class Reporter(Protocol):
    def render_run(self, summary: RunSummary) -> str: ...
    def render_eval(self, report: EvalReport) -> str: ...
```

## 接口之间的协作关系

主闭环协作顺序：

1. `TaskLoader` 产出 `TaskSpec`
2. `SandboxBackend` 准备工作区
3. `AgentAdapter` 执行任务
4. `TraceSink` 记录全过程
5. `Verifier` 判断结果
6. `RunStore` 保存摘要
7. `EvalRunner` 组织重复试验与聚合
8. `Reporter` 输出可读结果

## 第一阶段最小接口集合

第一阶段真正必须写成代码协议的接口是：
- `SandboxBackend`
- `AgentAdapter`
- `Verifier`
- `TraceSink`
- `RunStore`

`TaskLoader`、`EvalRunner`、`Reporter` 可以先做轻量实现，但接口轮廓最好现在就定好。

## 取舍说明

### 为什么不先做一个万能 Runner？
- 因为万能 Runner 往往会吞掉太多职责
- 一旦后面想换 Agent 或增加 Verifier，修改面会很大

### 为什么不一开始就设计成异步分布式接口？
- 因为当前目标是本地单机闭环
- 过早为分布式设计，会增加复杂度而不提升当前价值

### 为什么接口要尽量返回结构化对象？
- 因为 Trace、Report、Eval 都要复用这些结果
- 如果全是字符串拼接，后面维护成本会非常高

## 面向实现的提醒

- 第一阶段接口可以用 `Protocol`
- 具体实现放到对应模块下，不要让 `domain/` 依赖实现层
- 入口层调用接口，不直接依赖具体实现细节
- 如果某个接口开始承担多个问题，优先拆接口，不优先加参数

