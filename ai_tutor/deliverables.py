"""交付文档导出：把应用内的提示词库、模块设计、测试用例集导出为 Markdown。

对应阶段二"交付物整理"：提示词库 1 套（文档）+ 模块与应用介绍。
对应阶段三：测试用例集 + 实证记录。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from . import APP_NAME, TEAM, __version__
from .eval import COMPARISON_DIMENSIONS, HALLUCINATION_CASES, LOGIC_CASES, REPETITION_CASE
from .prompts import FIVE_ELEMENTS, STRUCTURE_PATTERNS, list_modules, prompt_library_markdown


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def export_prompt_library(target: Path, svc: Any = None) -> List[str]:
    written = [_write(target / "提示词库.md", prompt_library_markdown())]
    data = {
        "app": APP_NAME,
        "team": TEAM,
        "version": __version__,
        "methodology": {"five_elements": FIVE_ELEMENTS, "structures": STRUCTURE_PATTERNS},
        "modules": [m.to_dict(include_prompts=True) for m in list_modules()],
    }
    written.append(_write(target / "提示词库.json", json.dumps(data, ensure_ascii=False, indent=2)))
    return written


def export_modules(target: Path, svc: Any = None) -> List[str]:
    lines = [
        f"# {APP_NAME} · 模块与应用说明",
        "",
        f"> {TEAM}　v{__version__}",
        "",
        "## 一、系统能力与边界（阶段一）",
        "",
        "### 预期能力 · 全维赋能",
        "",
        "| 能力 | 说明 | 对应模块 |",
        "| --- | --- | --- |",
        "| 习题解析 | 拆解解题步骤，提供清晰易懂的思路引导 | M1 |",
        "| 知识梳理 | 自动生成章节知识框架，构建知识体系 | M2 |",
        "| 错题归纳 | 归纳错题原因，精准推荐同类练习 | M3 |",
        "| 通俗讲解 | 用生活化语言解释晦涩难懂的专业概念 | M4 |",
        "| 薄弱检测 | 智能分析知识盲区，生成个性化复习计划 | M5 |",
        "| 口语陪练 | 实时发音纠正，模拟场景进行背诵检测 | M6 |",
        "",
        "### 能力边界 · 恪守准则",
        "",
        "| 边界 | 说明 | 代码实现 |",
        "| --- | --- | --- |",
        "| 坚决抵制作弊 | 不提供代写作业、考试作弊等违规服务 | 提示词全局红线 + 同类练习只给思路不给答案（M3） |",
        "| 拒绝虚假押题 | 不承诺考试原题预测 | 提示词明确禁止承诺原题；只给考点星级 |",
        "| 聚焦教学大纲 | 仅处理本科基础教学范围内的问题 | 超纲内容统一标注【超纲，仅了解】 |",
        "| 非官方批改 | 仅提供辅助参考建议 | 输出标注「参考性反馈」，口语评分为近似评分 |",
        "| 拒绝编造 | 不编造文献 / 数据 / 页码 / 政策条文 | `quality_check` 与风险用例正则自动检测 |",
        "",
        "## 二、六大功能模块（阶段二）",
        "",
        "| 模块 | 名称 | 对应痛点 | 结构模式 | 路由任务 | 温度 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for m in list_modules():
        lines.append(f"| {m.id} | {m.title} | {m.pain_point} | {m.structure.get('label','')} "
                     f"| `{m.route_task}` | {m.temperature} |")
    lines += ["", "## 三、模块详情", ""]
    for m in list_modules():
        lines += [m.to_markdown()]
    lines += [
        "## 四、运行方式",
        "",
        "```bash",
        "python -m ai_tutor status            # 查看状态",
        "python -m ai_tutor chat              # 交互式答疑",
        "python -m ai_tutor web               # 启动 Web 界面",
        "python -m ai_tutor selftest          # 一键自检（离线可跑）",
        "python -m ai_tutor risk run --kind all   # 风险实证测试",
        "```",
        "",
    ]
    return [_write(target / "模块与应用说明.md", "\n".join(lines))]


def export_risk_plan(target: Path, svc: Any = None) -> List[str]:
    lines = [
        "# 第三阶段：风险实证分析方案",
        "",
        "## 一、测试对象与设置",
        "",
        "- 测试对象：GPT-4o（主模型）+ Claude 3.5 Sonnet + 文心一言 4.0（可在 `config.json` 中调整）",
        "- 提示词设置：同一用例分别用「精细提示」与「无约束提示」各跑一次（消融对照）",
        "- 记录方式：测试序号 / 模块 / 测试主题 / 两版输出评价 / 完整提示词与输出原文",
        "- 评价维度：结构完整性 / 事实准确性 / 逻辑严谨性 / 幻觉出现率 / 同质化程度",
        "- 通过标准：精细提示下 幻觉率 ≤20%、逻辑错误 ≤1 处、重复度 ≤30%",
        "",
        "## 二、四类专项测试",
        "",
        "### 1) 事实幻觉测试（H1–H6）",
        "",
    ]
    for case in HALLUCINATION_CASES:
        lines += [f"- **{case.id}** {case.title}：{case.question}",
                  f"  - 期望：{case.expectation}",
                  f"  - 风险判定：命中 `{case.risk_flags[0]}` 等形式即计为幻觉"]
    lines += ["", "### 2) 逻辑缺陷测试（L1–L5）", ""]
    for case in LOGIC_CASES:
        lines += [f"- **{case.id}** {case.title}：{case.question}",
                  f"  - 正确结论关键词：{'、'.join(case.expected_conclusion)}",
                  f"  - 错误结论关键词：{'、'.join(case.wrong_conclusion)}"]
    lines += ["", "### 3) 同质化测试（T1）", "",
              f"- 任务：{REPETITION_CASE.question}",
              "- 方法：同一精细提示重复 3 次，计算两两平均相似度（2-gram Jaccard / LCS / 结构相似度）",
              "- 缓解验证：追加「变换叙述风格 + 至少 2 种组织方式」指令后重新测量",
              "",
              "### 4) 多工具横向对比", "",
              "| 对比维度 | 说明 |", "| --- | --- |"]
    for dim in COMPARISON_DIMENSIONS:
        lines.append(f"| {dim['dim']} | {dim['desc']} |")
    lines += [
        "",
        f"对比题量：{len(HALLUCINATION_CASES[:5]) + len(LOGIC_CASES[:5])} 题"
        "（事实幻觉 5 道 + 逻辑缺陷 5 道）",
        "",
        "## 三、执行方式",
        "",
        "```bash",
        "python -m ai_tutor risk list                    # 查看全部用例",
        "python -m ai_tutor risk show H2                 # 查看单个用例详情",
        "python -m ai_tutor risk run --kind pair         # 事实幻觉 + 逻辑缺陷 对照测试",
        "python -m ai_tutor risk run --kind repetition --rounds 3",
        "python -m ai_tutor risk run --kind comparison --models openai anthropic qianfan",
        "python -m ai_tutor risk run --kind all          # 全量执行",
        "```",
        "",
        "## 四、自动化判定与人工复核",
        "",
        "程序使用正则模式识别风险输出（如虚构 DOI、精确到个位却无来源的数据、逻辑方向倒置），",
        "并对逻辑题核对正确结论关键词。判定结果写入 `data/reports/*.md` 与 SQLite，",
        "**但仍需人工复核**：涉及教材页码、文献 DOI、政策条文的输出必须标注「待核实」。",
        "",
    ]
    return [_write(target / "风险实证方案.md", "\n".join(lines))]


def export_all(target: Path, svc: Any = None) -> List[str]:
    written: List[str] = []
    written += export_modules(target, svc)
    written += export_risk_plan(target, svc)
    return written
