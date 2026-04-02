# Repo Harness Lab

一个面向仓库任务的本地优先 Agent Harness：把业务请求整理成结构化任务，在隔离工作区里执行，使用确定性验证做验收，并把运行证据沉淀为可回放、可对比的报告。

## 项目在解决什么问题

很多“代码 Agent Demo”只能展示某次碰巧成功，但很难回答下面几个工程问题：

- 任务到底怎么定义，成功标准是什么
- Agent 看到了哪些上下文，哪些信息是结构化注入的
- 修改发生在什么工作区里，能不能安全回放
- 结果为什么算通过或失败
- 同一个模型在不同 harness 配置下，差异到底来自哪里

这个项目的目标，就是把这些问题都工程化落地，而不是只靠一次性的 prompt 拼接。

## 当前能力

- `Task Intake -> TaskSpec`：先整理业务请求，再稳定生成运行协议
- 本地隔离工作区：在副本里执行任务，避免直接污染源仓库
- 确定性验收：优先通过 verifier 而不是主观打分判断成功与否
- 结构化留证：保存 summary、events、diff、verifier 结果和报告
- 同模型多档对比：支持 `bare / basic / full` 三档 harness profile
- 可浏览报告：支持 run report、comparison、eval、dashboard 和 live portal

## 环境要求

- Python `3.11+`
- Windows / macOS / Linux 均可，本仓库当前主要以本地运行方式为主
- 如果要跑外部 provider 示例，需要自己准备对应 API Key 环境变量

## 快速开始

在项目根目录执行：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .[dev]
```

如果你只想确认 CLI 已安装成功，可以先执行：

```powershell
repo-harness-lab show-settings
```

## 常用命令

查看 intake 模板：

```powershell
repo-harness-lab show-task-intake-template
```

预览一份 intake 会如何映射成任务和三档 harness 交付：

```powershell
repo-harness-lab preview-intake examples/intakes/provider_release_input_task_intake.json --format both
```

直接从 intake 跑同模型 `bare / basic / full` 对比：

```powershell
repo-harness-lab run-intake-eval examples/intakes/provider_release_input_task_intake.json --provider qwen --model qwen-plus --api-key-env DASHSCOPE_API_KEY
```

启动本地 live portal：

```powershell
repo-harness-lab serve-portal --host 127.0.0.1 --port 8765
```

重渲最近运行的 dashboard / portal：

```powershell
repo-harness-lab render-dashboard --limit 20
repo-harness-lab render-uplift-dashboard --limit 20
repo-harness-lab render-portal --limit 20
```

## 目录说明

- `src/repo_harness_lab/`：正式源码
- `tests/`：单元测试与夹具
- `examples/`：示例仓库、任务、intake 和 eval 套件
- `SYSTEM_ARCHITECTURE.md`：系统骨架与主链路
- `REPO_STRUCTURE.md`：目录结构与模块分层说明
- `DOMAIN_MODELS.md`：领域对象设计
- `CORE_INTERFACES.md`：核心协议接口设计
- `HARNESS_EVIDENCE_REPORT.md`：项目为什么能证明 harness uplift 的说明
- `HOSTED_PORTAL_DEPLOYMENT.md`：hosted portal 的部署说明

## 测试

```powershell
python -m unittest discover -s tests/unit -p "test_*.py"
python -m compileall src tests examples
```
