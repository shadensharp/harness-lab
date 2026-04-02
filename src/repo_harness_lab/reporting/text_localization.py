from __future__ import annotations

import re


_EXACT_REPLACEMENTS = {
    "Only the repository tree is attached; task inputs and verifier steps stay hidden.": "只附带仓库目录树，不暴露任务输入和 verifier 步骤。",
    "This profile can inject task inputs, but the task does not currently declare any.": "这一档支持注入任务输入，但当前任务没有声明输入。",
    "No task inputs are declared, so full will not demonstrate input-injection uplift.": "当前没有声明任务输入，因此 full 档无法展示输入注入带来的抬升。",
    "No context_paths are declared, so basic/full will choose repo files mostly by changed files and editable paths.": "当前没有声明 context_paths，因此 basic/full 主要会根据改动文件和可编辑路径选取上下文。",
    "includes task inputs that can benefit from stronger context packing": "包含任务输入，能体现更强上下文打包的优势",
    "has deterministic verifier steps, so pass and fail stay explainable": "包含确定性 verifier 步骤，成败原因更容易解释",
    "touches multiple files or paths, which is useful for showing context-management uplift": "涉及多个文件或路径，适合展示上下文管理带来的抬升",
    "curated benchmark, easier to compare repeated harness runs": "属于精选基准任务，便于比较多次 Harness 运行",
    "rolling benchmark, reusable without locking users into a fixed pool": "属于滚动基准任务，可复用且不把用户锁死在固定任务池里",
    "open task, still runnable even when it is not part of the curated pool": "属于开放任务，即使不在精选任务池里也能直接运行",
    "medium difficulty usually shows harness differences without becoming brittle": "中等难度通常既能看出 Harness 差异，又不容易变脆",
    "hard difficulty can amplify context and verifier advantages": "高难度更容易放大上下文和 verifier 的优势",
    "easy difficulty is useful for smoke checks but usually shows less uplift": "低难度适合冒烟检查，但通常不容易体现明显抬升",
    "no harness signals declared, so uplift explanations will be weaker": "当前没有声明 Harness 信号，因此抬升解释会更弱",
}

_PREFIX_REPLACEMENTS = (
    ("declares harness signals: ", "声明了 Harness 信号："),
    ("matches preferred signals: ", "命中偏好信号："),
    ("matches preferred tags: ", "命中偏好标签："),
    ("Will inject task inputs: ", "将注入任务输入："),
    ("Will inject verifier steps: ", "将注入 verifier 步骤："),
    ("context files: ", "上下文文件："),
    ("context cap: ", "上下文上限："),
    ("new task inputs: ", "新增任务输入："),
    ("new verifier steps: ", "新增 verifier 步骤："),
)


def localize_harness_message(text: str) -> str:
    if not text:
        return text
    exact = _EXACT_REPLACEMENTS.get(text)
    if exact is not None:
        return exact
    for old, new in _PREFIX_REPLACEMENTS:
        if text.startswith(old):
            return new + text[len(old):]
    attach_match = re.fullmatch(r"Will attach up to (\d+) context files; current preview selects (\d+)\.", text)
    if attach_match is not None:
        return f"最多附带 {attach_match.group(1)} 个上下文文件；当前预览选中了 {attach_match.group(2)} 个。"
    return text
