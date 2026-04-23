from __future__ import annotations

import re


_EXACT_REPLACEMENTS = {
    "No task inputs are declared, so the current package relies on repository context only.": "当前没有声明任务输入，因此这次运行主要依赖仓库上下文。",
    "No verifier steps are declared, so completion evidence will rely on changed files and behavior checks.": "当前没有声明验收步骤，因此完成度主要依赖改动文件和行为检查。",
    "No task inputs are declared, so the run will depend on repository context and verifier steps only.": "当前没有声明任务输入，因此运行结果主要取决于仓库上下文和验收步骤。",
    "No context_paths are declared, so repository context will be chosen mostly by changed files and editable paths.": "当前没有声明 context_paths，因此仓库上下文主要会根据改动文件和可编辑路径选取。",
    "Repository preview is structural only because the task does not point to a local_path repo.": "当前任务没有指向本地仓库路径，因此这里只能展示结构化预览。",
    "Context-file preview is unavailable because the local repository path could not be inspected.": "当前无法检查本地仓库路径，因此上下文文件预览不可用。",
    "Repository tree preview is unavailable because the local repo could not be inspected.": "当前无法检查本地仓库，因此仓库树预览不可用。",
    "Verifier plan is narrow, so completion evidence may stay weak.": "当前 verifier 计划较窄，因此完成度证据可能偏弱。",
    "The task mostly changes a single file, so context selection may matter less.": "当前任务主要改动单个文件，因此上下文选择的影响可能较小。",
    "No harness signals are declared, so recommendation explanations will be weaker.": "当前没有声明 Harness 信号，因此推荐理由会偏弱。",
    "No context files were selected for the current preview, so the run will lean on the repository tree and direct task constraints.": "当前预览没有选中上下文文件，因此运行会更依赖仓库树和直接任务约束。",
    "The repo source could not be inspected, so tree and context-file previews are unavailable.": "当前无法检查仓库来源，因此仓库树和上下文文件预览都不可用。",
    "The current run receives the same task title and description.": "当前运行收到的任务标题和说明保持不变。",
    "Same response contract: JSON only with summary and writes.": "输出契约保持不变：只能返回 JSON summary + writes。",
}

_PREFIX_REPLACEMENTS = (
    ("declares harness signals: ", "声明了 Harness 信号："),
    ("matches preferred signals: ", "命中偏好信号："),
    ("matches preferred tags: ", "命中偏好标签："),
    ("Will attach up to ", "最多附带 "),
    ("Will inject task inputs: ", "将注入任务输入："),
    ("Will inject verifier steps: ", "将注入 verifier 步骤："),
    ("Same editable paths: ", "可改范围保持一致："),
    ("Same forbidden paths: ", "禁改范围保持一致："),
    ("Same expected changed files: ", "目标改动文件保持一致："),
    ("Same behavioral checks: ", "行为检查保持一致："),
    ("Same required verifier step names: ", "必过步骤名称保持一致："),
    ("Repository tree attached", "附带仓库树"),
    ("Repository context files: ", "附带的上下文文件："),
    ("Injected task inputs: ", "附带的任务输入："),
    ("Injected verifier steps: ", "附带的验收步骤："),
)


def localize_harness_message(text: str) -> str:
    if not text:
        return text
    normalized = " ".join(str(text).split())
    exact = _EXACT_REPLACEMENTS.get(normalized)
    if exact is not None:
        return exact
    for old, new in _PREFIX_REPLACEMENTS:
        if normalized.startswith(old):
            if old == "Will attach up to ":
                match = re.fullmatch(r"Will attach up to (\d+) context files; current preview selects (\d+)\.", normalized)
                if match is not None:
                    return f"最多附带 {match.group(1)} 个上下文文件；当前预览选中了 {match.group(2)} 个。"
            return new + normalized[len(old):]
    return normalized
