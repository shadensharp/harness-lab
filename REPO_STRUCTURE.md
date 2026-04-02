# 目录结构设计

最后更新：2026-04-02 16:36:18 +08:00

## 2026-03-27 结构补充
- `reporting/` 目录新增 `failure_summary.py`，用于把 verifier 证据、命令退出码和 run notes 归并成统一失败摘要，再投影到 markdown / html 报告。
- `agents/factory.py` 现在除了千问外，也内建了 `deepseek` 和 `openrouter` 这类 provider shortcut，继续保持 adapter/provider 分层不变，但降低真实外部模型接入成本。
- `examples/repos/provider_readme_uplift_repo/` 的示例素材现在要求保持无 BOM UTF-8；否则 provider eval 会被样例编码噪音干扰，掩盖真实 harness uplift。
- `examples/` 现在不只放单个任务，还开始承载可直接运行的 provider uplift 示例资产，包括：
  - `examples/repos/`：示例目标仓库
  - `examples/tasks/`：示例任务定义
  - `examples/evals/`：示例评测套件
- `agents/` 目录现在正式拆出 `providers/`，用于承接外部模型 API 通信；`adapters/` 继续负责 prompt/context packing 与工作区写入。
- `tasks/loader.py` 现在需要把本地相对路径按任务文件目录解析，这样任务样例和标准任务池资产才能脱离当前工作目录稳定复用。
- `shared/` 目录新增 `failure_hints.py`，用于统一挑选“最能解释失败原因”的提示语，避免 markdown / html / dashboard 各自用不同口径解释失败。
- `evals/runner.py` 现在除了 `profile_uplift` 外，还会产出 `profile_failure_summary`，让评测层能按 harness profile 聚合失败原因，而不只统计通过率。
- `cli/commands/evals.py` 现在会在 `run-eval` 结束后自动生成基线 profile 对比页；因此 `runtime/reports/` 不再只承载 suite / dashboard，也开始承载可直接演示的 run comparison 页面。
- `tasks/catalog.py` 现在除了扫描和过滤，也开始承接 recommendation 语义；也就是说任务池层不仅能“列出可跑任务”，还要能输出“哪些任务更适合展示 harness uplift”。
- `cli/commands/info.py` 现在新增 `recommend-tasks`，把“开放任务入口 + 系统推荐优先级”正式变成 CLI 能力，而不是文档约定。
- `agents/factory.py` 里的 provider preset 表继续扩张，但仍保持“preset 只解决接入摩擦，不改变主闭环契约”的边界。
- `reporting/html.py` 现在除了 run report / compare report，也开始把 trial 级输出快照投影到 eval 页面；因此 `runtime/reports/*.html` 不再只是指标总览，而开始承载可直接人工判读的输出证据。
- `runtime/reports/` 当前的 suite / compare / portal 页面都已经能联动到 run-level HTML 报告，形成“总览 -> trial snapshot -> full run evidence”的连续浏览路径。
## 2026-03-26 结构补充

- `tasks/` 现在不只负责 loader / validator，也需要支持 task pool catalog，服务“标准任务池 + 开放入口”双轨体系。
- `agents/` 后续目录要优先为外部 provider adapter 预留位置，而不是把本地脚本型 adapter 当成最终形态。
- `evals/` 的职责已经从“批量跑 case”扩展到“表达 harness profile uplift”。
- `runtime/reports/` 将继续作为 portal / dashboard / comparison 的统一展示目录。

## 设计目标

目录结构必须同时满足三件事：
- 方便当前一个月内实现
- 能支撑后续扩展
- 让面试官一眼看出这是一个边界清晰的工程项目，而不是脚本堆积

## 根目录建议结构

```text
repo-harness-lab/
  CODEX_WORKING_PROTOCOL.md
  PROJECT_LOG.md
  INTERVIEW_QA.md
  SYSTEM_ARCHITECTURE.md
  REPO_STRUCTURE.md
  .gitignore
  README.md
  pyproject.toml
  src/
    repo_harness_lab/
      __init__.py
      cli/
      config/
      domain/
      tasks/
      runtime/
      agents/
      verifiers/
      traces/
      storage/
      evals/
      reporting/
      shared/
  examples/
    README.md
    repos/
    tasks/
      requirement_change/
      bug_fix/
    evals/
  tests/
    unit/
    integration/
    fixtures/
  runtime/
    runs/
    reports/
    tmp/
```

## 顶层目录说明

### 根目录文档
- `CODEX_WORKING_PROTOCOL.md`
  - 用于本地 Codex 协作协议、恢复顺序与长期记录约束
- `PROJECT_LOG.md`
  - 用于恢复上下文
- `INTERVIEW_QA.md`
  - 用于阶段性面试准备
- `SYSTEM_ARCHITECTURE.md`
  - 用于系统骨架定义
- `REPO_STRUCTURE.md`
  - 用于目录设计说明
- `README.md`
  - 面向项目读者的总览入口

说明：
- 当前阶段先把关键设计文档放在根目录，便于快速维护和恢复。
- `CODEX_WORKING_PROTOCOL.md` 负责把共享协议接入本仓库，并把本项目自己的协作边界、读取顺序和长期记录方式固定下来。
- 如果准备公开上传 GitHub，`CODEX_WORKING_PROTOCOL.md`、`PROJECT_LOG.md`、`INTERVIEW_QA.md` 这类本地协作/个人准备文件可以不提交。
- 等代码骨架稳定后，正式设计文档可以再迁移到 `docs/`，但 `PROJECT_LOG.md` 和 `INTERVIEW_QA.md` 建议保留在根目录。

### `src/repo_harness_lab/`
- 正式源码目录
- 使用标准 `src` 布局，避免导入污染，也更适合做工程项目展示

### `examples/`
- 放可直接运行的示例资产与演示入口
- 当前按三层组织：
  - `repos/`：示例目标仓库
  - `tasks/`：示例任务定义
  - `evals/`：示例评测套件

### `tests/`
- `unit/` 放模块级测试
- `integration/` 放跨模块闭环测试
- `fixtures/` 放样例任务和样例仓库素材

### `runtime/`
- 放运行产物，不进源码目录
- `runs/` 放单次运行结果
- `reports/` 放评测与报告输出
- `tmp/` 放临时工作区

## 源码包内部分层

```text
src/repo_harness_lab/
  cli/
    main.py
    commands/
      task.py
      run.py
      verify.py
      eval.py
      report.py
  config/
    settings.py
    paths.py
  domain/
    task_spec.py
    run_models.py
    trace_models.py
    verifier_models.py
    eval_models.py
    protocols.py
  tasks/
    loader.py
    validator.py
    templates.py
  runtime/
    workspace.py
    executor.py
    sandbox.py
    budget.py
  agents/
    base.py
    adapters/
      local_script.py
      provider_json_edit.py
    providers/
      base.py
      openai_compatible.py
  verifiers/
    base.py
    command.py
    python_checks.py
    composite.py
  traces/
    events.py
    sink.py
    serializers.py
  storage/
    run_store.py
    json_store.py
  evals/
    suite.py
    runner.py
    metrics.py
    compare.py
  reporting/
    markdown.py
    json.py
    html.py
  shared/
    ids.py
    clock.py
    files.py
```

## 各模块职责

### `cli`
- 定义命令行入口
- 负责参数解析和顶层调度

### `config`
- 负责环境变量、默认配置、路径约定

### `domain`
- 放领域模型和协议接口
- 保持稳定、低耦合

### `tasks`
- 负责 `TaskSpec` 的装载、校验和模板生成

### `runtime`
- 负责工作区生命周期、命令执行、预算控制

### `agents`
- 放 Agent 抽象层和具体适配器

### `verifiers`
- 放可组合的确定性校验器

### `traces`
- 负责事件结构、序列化和落盘

### `storage`
- 负责运行摘要和持久化读写

### `evals`
- 负责批量评测、指标聚合、结果对比

### `reporting`
- 负责把结构化结果转成可读报告

### `shared`
- 放跨模块公用但不含业务语义的工具

## 第一阶段最小实现清单

如果先做最小可用闭环，目录里真正必须落地的是：
- `cli/main.py`
- `config/settings.py`
- `domain/task_spec.py`
- `domain/run_models.py`
- `domain/protocols.py`
- `tasks/loader.py`
- `runtime/workspace.py`
- `runtime/executor.py`
- `agents/base.py`
- `agents/adapters/local_script.py`
- `verifiers/base.py`
- `verifiers/command.py`
- `traces/events.py`
- `traces/sink.py`
- `storage/json_store.py`
- `evals/runner.py`
- `reporting/markdown.py`

其他模块可以在第二阶段补全。

## 裁剪策略

### 如果时间更充裕
- 保留完整分层
- 增加第二后端
- 增加更多 Verifier 和报告能力

### 如果时间变紧
- 保留目录骨架不变
- 先减少模块内部实现数量
- 不要把不同职责重新塞回一个大文件

## 目录结构的面试价值

这套结构想传达的信号不是“目录很多”，而是：
- 你清楚系统的变化点在哪里
- 你知道哪些东西应该稳定，哪些东西应该可替换
- 你把运行产物、领域模型、基础设施和入口层分开了
- 你在做工程系统，不是在堆功能



