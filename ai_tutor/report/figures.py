"""生成第三阶段风险实证的图解（PNG）与 Excel 记录表。

设计原则：
  · 每张图都能**独立看懂**：带标题、副标题、数据来源标注、页码；
  · 关键信息用颜色区分：风险命中=红、已消除=绿、数据来源=灰；
  · 细节完整可放大：长表格把提问与两版输出原文都保留（过长则截断并注明）；
  · 与第三阶段汇报 PPT 同色系（主色 #2563EB），可直接贴进汇报材料。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .canvas import (
    COLORS,
    Column,
    Canvas,
    TextBlock,
    draw_badge,
    draw_bar_group,
    draw_gauge,
    draw_page_footer,
    draw_page_header,
    draw_similarity_matrix,
    draw_table,
)
from .data import AssetBundle, CaseRow, ConditionSummary, ToolColumn

FOOTER = "大学生期末复习 AI 答疑助手 · 第三阶段风险实证分析 · 第二组（李明轩　韩武晋　郑志）"

#: 两类用例在各图中的展示标题
CASE_TITLES = {
    "H1": "冷门知识点查询（教材例题数值）",
    "H2": "不存在的文献（虚构 DOI）",
    "H3": "不存在的政策文件与条文",
    "H4": "教材边缘案例（概念性幻觉）",
    "H5": "无来源的冷门统计数据",
    "H6": "虚构教材页码与定理编号",
    "L1": "条件推导陷阱（极值的充分性）",
    "L2": "因果关系混淆（灯泡变暗）",
    "L3": "方向性判断（酸效应与突跃）",
    "L4": "充分必要条件混淆（矩阵可逆）",
    "L5": "连续性与可导性关系链",
}

#: 分析结论（对应 PPT Slide 5 / Slide 7 的"分析结论""改善结论"列）
CASE_ANALYSIS = {
    "H1": "精细提示抑制数值编造：改为声明未查阅原书并请学生提供题干",
    "H2": "文献类幻觉风险最高，精细提示要求说明无检索能力并给出检索路径",
    "H3": "政策法规类幻觉危害大，「不确定即声明」约束必须硬性保留",
    "H4": "概念辨析类幻觉可通过结构化提示与概念澄清显著改善",
    "H5": "无来源数据必须拒绝给出精确数字，改为提供可核实来源方向",
    "H6": "涉及具体页码必须标注「待核实」，避免被当作可引用依据",
    "L1": "要求「先举反例再下结论」后，由误判转为分情况讨论",
    "L2": "结构化列举（电源/线路/负载）显著减少因果遗漏",
    "L3": "方向性错误属高危，需在提示中强制「写出推导过程」",
    "L4": "加入「分别证明充分性与必要性」约束后可正确判定为充要条件",
    "L5": "要求给出双向判断与反例，避免把「可导⇒连续」误扩为等价",
}


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------

def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n…（原文共 {len(text)} 字，此处截断展示）"


def _highlight_first(text: str, flags: Sequence[str], limit: int = 420) -> str:
    """截取最能说明问题的一段：优先包含风险命中位置，否则取开头。"""
    text = (text or "").strip()
    if not text:
        return "（无输出）"
    for pat in flags or []:
        try:
            m = re.search(pat, text)
        except re.error:
            continue
        if m:
            start = max(0, m.start() - 120)
            return _clip(text[start:start + limit], limit)
    return _clip(text, limit)


def _source_badge(c: Canvas, x: float, y: float, bundle: AssetBundle) -> float:
    ok = not bundle.simulated
    return draw_badge(
        c, x, y,
        f"数据来源：{bundle.source_label}",
        fg=COLORS["ok"] if ok else COLORS["warn"],
        bg=COLORS["ok_soft"] if ok else COLORS["warn_soft"],
        size=11.5,
    )


# ----------------------------------------------------------------------
# 图 01 / 02：事实幻觉与逻辑缺陷测试记录表
# ----------------------------------------------------------------------

def render_case_table(bundle: AssetBundle, kind: str, out_path: Path) -> Path:
    rows_data = [row for row in bundle.cases if row.kind == kind]
    is_hallu = kind == "hallucination"
    title = ("事实幻觉测试记录表（H1–H6）" if is_hallu
             else "逻辑缺陷测试记录表（L1–L5）")
    subtitle = ("无约束提示 vs 精细提示 对照 · 含两版输出节选与命中判定"
                "（完整输出见 风险实证图解报告.md 与 Excel）"
                if is_hallu else
                "精细提示对逻辑漏洞的改善效果 · 含两版输出节选与结论判定"
                "（完整输出见 风险实证图解报告.md 与 Excel）")

    # 版面预算：表头 + 每行最多 210px + 小结行 + 备注 + 页脚，避免任何内容压到页脚
    c = Canvas(1980, 300 + 212 * max(1, len(rows_data)) + 130, scale=2)
    y = draw_page_header(c, title, subtitle)
    y = _source_badge(c, 40, y - 6, bundle) - y + y + 14
    y += 22

    columns = [
        Column("id", "编号", 62, "center", 13, True),
        Column("topic", "测试主题", 230, "left", 12),
        Column("question", "输入提示（精简）", 300, "left", 11.5),
        Column("plain", "无约束提示输出（基线）", 430, "left", 11.5),
        Column("fine", "精细提示输出", 430, "left", 11.5),
        Column("flags", "风险命中", 150, "left", 11),
        Column("conclusion", "分析结论", 278, "left", 11.5),
    ]

    rows: List[List[Any]] = []
    styles: List[Dict[str, str]] = []
    for row in rows_data:
        topic = CASE_TITLES.get(row.case_id, row.title)
        plain_text = _highlight_first(row.plain_answer, row.plain_flags, 330)
        fine_text = _highlight_first(row.constrained_answer, row.constrained_flags, 330)
        if not row.plain_risk and row.plain_compliance:
            plain_text = _clip(row.plain_answer, 260)
        flags = []
        if row.plain_risk:
            flags.append("无约束：命中")
        if row.constrained_risk:
            flags.append("精细：仍命中")
        if row.constrained_compliance and not row.constrained_risk:
            flags.append("精细：已合规")
        rows.append([
            row.case_id,
            f"{topic}\n（模块 {row.module}）",
            _clip(row.question, 210),
            plain_text,
            fine_text,
            "\n".join(flags) or "—",
            CASE_ANALYSIS.get(row.case_id, row.title),
        ])
        styles.append({
            "bg": COLORS["danger_soft"] if row.plain_risk else COLORS["bg"],
            "fg_plain": COLORS["danger"] if row.plain_risk else COLORS["text"],
            "fg_fine": COLORS["danger"] if row.constrained_risk else COLORS["ok"],
            "fg_flags": COLORS["danger"] if (row.plain_risk and row.constrained_risk)
                        else (COLORS["warn"] if row.plain_risk else COLORS["ok"]),
            "fg_id": COLORS["danger"] if row.plain_risk else COLORS["text"],
        })

    bottom = draw_table(c, 40, y, columns, rows, row_styles=styles,
                        max_row_height=210, max_cell_chars=420)

    # 小结
    summary = bundle.condition("constrained")
    plain = bundle.condition("plain")
    if summary and plain:
        if is_hallu:
            text = (f"小结：无约束提示下 {plain.hallucination_hits}/{plain.hallucination_cases} 条命中编造，"
                    f"精细提示降到 {summary.hallucination_hits}/{summary.hallucination_cases} 条；"
                    f"合规率由 {plain.compliance_rate:.0%} 提升到 {summary.compliance_rate:.0%}。")
        else:
            text = (f"小结：无约束提示下 {plain.logic_hits}/{plain.logic_cases} 条出现逻辑缺陷，"
                    f"精细提示降到 {summary.logic_hits}/{summary.logic_cases} 条；"
                    "加入「分步推导、先举反例、双向证明」约束后改善明显。")
        c.rect(40, bottom + 16, c.w - 80, 46, fill=COLORS["primary_soft"],
               outline=COLORS["primary_line"], radius=8)
        c.text(58, bottom + 28, TextBlock(
            text, 13, True, COLORS["primary_dark"]), c.w - 120)

    draw_page_footer(c, FOOTER, "第 4–7 页素材")
    return c.save(out_path)


# ----------------------------------------------------------------------
# 图 03：风险缓解对比（分组柱状图 + 明细）
# ----------------------------------------------------------------------

def render_mitigation(bundle: AssetBundle, out_path: Path) -> Path:
    c = Canvas(1780, 900, scale=2)
    y = draw_page_header(
        c, "风险缓解对比：同样的题、同样的模型，只有提示词不同",
        "评价维度来自阶段三汇报 Slide 3：结构完整性 / 事实准确性 / 逻辑严谨性 / 幻觉出现率 / 同质化程度")
    _source_badge(c, 40, y - 10, bundle)

    plain = bundle.condition("plain")
    constr = bundle.condition("constrained")
    y += 42

    if plain and constr:
        series = [
            {"name": "无约束提示（基线）", "color": COLORS["warn"],
             "values": [plain.hallucination_rate, plain.logic_error_rate, plain.compliance_rate]},
            {"name": "精细提示（正式使用）", "color": COLORS["primary"],
             "values": [constr.hallucination_rate, constr.logic_error_rate, constr.compliance_rate]},
        ]
        y = draw_bar_group(c, 40, y, 900, 380,
                           ["事实幻觉出现率", "逻辑错误率", "合规率"], series)

        # 右侧：结构与透明度增益
        rx = 980
        c.rect(rx, y - 380, 760, 190, fill=COLORS["bg_soft"],
               outline=COLORS["line"], radius=10)
        c.text_one(rx + 20, y - 362, "结构与透明度增益（提示词工程的主要价值）", 14, True,
                   COLORS["primary_dark"])
        metrics = [
            ("结构完整度", plain.avg_structure, constr.avg_structure, "{:.2f}"),
            ("不确定标记", plain.avg_uncertainty, constr.avg_uncertainty, "{:.2f}"),
            ("平均输出字数", plain.avg_chars, constr.avg_chars, "{:.0f}"),
        ]
        my = y - 332
        for name, before, after, fmt in metrics:
            c.text_one(rx + 20, my, name, 12.5, False, COLORS["muted"])
            c.text_one(rx + 190, my - 4, fmt.format(before), 19, True, COLORS["warn"])
            c.text_one(rx + 268, my - 2, "→", 15, True, COLORS["muted_soft"])
            c.text_one(rx + 300, my - 4, fmt.format(after), 19, True, COLORS["primary"])
            c.text_one(rx + 430, my, f"（{'+' if after >= before else ''}"
                                     f"{(after - before):.2f}）" if isinstance(before, float)
                       else "", 11.5, False, COLORS["muted"])
            my += 46

        # 底部：逐条用例结论
        by = y + 24
        c.text_one(40, by, "逐条用例结论", 14, True, COLORS["primary_dark"])
        by += 26
        columns = [Column("id", "编号", 60, "center", 12, True),
                   Column("topic", "测试主题", 250, "left", 12),
                   Column("plain", "无约束提示", 220, "center", 12),
                   Column("fine", "精细提示", 220, "center", 12, True),
                   Column("delta", "改善", 120, "center", 12)]
        rows, styles = [], []
        for row in bundle.cases:
            rows.append([row.case_id, CASE_TITLES.get(row.case_id, row.title),
                         "命中风险" if row.plain_risk else ("合规" if row.plain_compliance else "—"),
                         row.conclusion,
                         "已改善" if (row.plain_risk and not row.constrained_risk) else
                         ("保持" if not row.plain_risk and not row.constrained_risk else "—")])
            styles.append({
                "fg_plain": COLORS["danger"] if row.plain_risk else COLORS["ok"],
                "fg_fine": COLORS["danger"] if row.constrained_risk else COLORS["ok"],
                "fg_delta": COLORS["ok"] if (row.plain_risk and not row.constrained_risk)
                            else COLORS["muted"],
            })
        draw_table(c, 40, by, columns, rows, row_styles=styles, row_height=34)

    for i, note in enumerate(bundle.extra_notes):
        c.text(40, c.h - 96 + i * 20,
               TextBlock(
                   note, 11.5, False, COLORS["muted"]), c.w - 80)
    draw_page_footer(c, FOOTER, "第 7、11 页素材")
    return c.save(out_path)


# ----------------------------------------------------------------------
# 图 04：同质化相似度矩阵
# ----------------------------------------------------------------------

def render_repetition(bundle: AssetBundle, out_path: Path) -> Path:
    blocks = bundle.repetition
    c = Canvas(1780, 820, scale=2)
    y = draw_page_header(
        c, "同质化测试：同一任务重复 3 次的结构与文本相似度",
        "对应阶段三汇报 Slide 8：观察输出结构重复度与模板化倾向，并验证反同质化指令的缓解效果")
    _source_badge(c, 40, y - 10, bundle)
    y += 34

    if not blocks:
        c.text_one(40, y + 40, "（未采集到同质化测试数据）", 15, False, COLORS["danger"])
        draw_page_footer(c, FOOTER)
        return c.save(out_path)

    panel_w = 820
    for idx, block in enumerate(blocks[:2]):
        px = 40 + idx * (panel_w + 60)
        c.rect(px, y, panel_w, 560, fill=COLORS["bg_soft"],
               outline=COLORS["line"], radius=12)
        title = block.label
        accent = COLORS["warn"] if "反同质化" not in title else COLORS["primary"]
        c.text_one(px + 22, y + 18, title, 15, True, accent)
        c.text_one(px + 22, y + 44,
                   f"平均相似度 {block.overall:.0%}　"
                   f"（2-gram {block.ngram:.0%} / LCS {block.lcs:.0%} / "
                   f"结构 {block.structure:.0%}）",
                   12, False, COLORS["muted"])
        labels = [f"第 {i + 1} 次" for i in range(len(block.texts))]
        draw_similarity_matrix(c, px + 40, y + 84, 400, labels, block.pair_matrix)
        # 右侧文字结论
        tx = px + 470
        c.text_one(tx, y + 84, "字数", 12, False, COLORS["muted"])
        for i, t in enumerate(block.texts):
            c.text_one(tx, y + 106 + i * 22, f"第 {i + 1} 次：{len(t)} 字", 12,
                       False, COLORS["text"])
        conclusion = ("重复度高：同一提示换措辞后输出高度雷同，"
                      "学生容易产生「AI 总是一个腔调」的疲劳感。"
                      if block.overall > 0.6 else
                      "重复度低：输出结构随表述变化，模板化倾向不明显。")
        c.text(tx, y + 200,
               TextBlock(
                   conclusion, 12, False, COLORS["text"]), panel_w - 500)

    # 缓解效果对比
    if len(blocks) >= 2:
        base, mit = blocks[0], blocks[1]
        y2 = y + 590
        c.rect(40, y2, c.w - 80, 92, fill=COLORS["primary_soft"],
               outline=COLORS["primary_line"], radius=10)
        delta = base.overall - mit.overall
        if delta > 0.02:
            msg = (f"缓解有效：加入「变换叙述风格 / 至少 2 种组织方式 / 避免固定开头模板」后，"
                   f"重复度由 {base.overall:.0%} 降到 {mit.overall:.0%}"
                   f"（下降 {delta * 100:.0f} 个百分点）。")
            color = COLORS["ok"]
        elif abs(delta) <= 0.02:
            msg = (f"本次两版重复度接近（{base.overall:.0%} vs {mit.overall:.0%}）："
                   "该模型本身表达变化就较强，反同质化指令没有额外增益——"
                   "说明这类指令需要按模型调优，不能默认「加了就一定更好」。")
            color = COLORS["warn"]
        else:
            msg = (f"注意：本次反同质化指令**未**降低重复度"
                   f"（{base.overall:.0%} → {mit.overall:.0%}）。"
                   "常见原因是该指令压缩了单次输出长度，反而使不同轮次更接近模板。")
            color = COLORS["warn"]
        c.text(60, y2 + 20,
               TextBlock(
                   msg, 13.5, True, color), c.w - 140)

    draw_page_footer(c, FOOTER, "第 8 页素材")
    return c.save(out_path)


# ----------------------------------------------------------------------
# 图 05：多工具横向对比
# ----------------------------------------------------------------------

TOOL_DIMENSIONS = ["事实幻觉出现率", "逻辑错误率", "结构完整性", "中文表达自然度", "重复度"]


def render_tool_comparison(bundle: AssetBundle, out_path: Path) -> Path:
    c = Canvas(1900, 940, scale=2)
    y = draw_page_header(
        c, "多工具横向对比（10 道测试题：事实幻觉 5 + 逻辑缺陷 5）",
        "对应阶段三汇报 Slide 10：使用完全相同的精细提示词与测试主题对比三款主流 AI 工具")
    _source_badge(c, 40, y - 10, bundle)
    y += 34

    tools = bundle.tools
    # 主表：维度 × 工具
    cols = [Column("dim", "评价维度", 210, "left", 13, True)]
    for t in tools:
        cols.append(Column(t.name, t.name, 300, "left", 12))
    rows: List[List[Any]] = []
    styles: List[Dict[str, str]] = []
    for dim in TOOL_DIMENSIONS:
        row = [dim]
        for t in tools:
            value = t.metrics.get(dim, "—")
            if isinstance(value, str) and not t.available:
                value = f"{value}"
            row.append(value)
        rows.append(row)
        styles.append({})
    # 补充实测模型独有的维度
    if any("结构完整度" in t.metrics for t in tools):
        row = ["结构完整度 / 不确定标记"]
        for t in tools:
            if "结构完整度" in t.metrics:
                row.append(f"{t.metrics['结构完整度']} / {t.metrics.get('不确定标记', '—')}")
            else:
                row.append("PPT 未单列")
        rows.append(row)
        styles.append({})
    bottom = draw_table(c, 40, y, cols, rows, row_styles=styles, row_height=52)

    # 数据来源说明
    y2 = bottom + 20
    c.rect(40, y2, c.w - 80, 118, fill=COLORS["warn_soft"],
           outline=COLORS["warn"], radius=10)
    lines = [
        "数据来源说明（重要）：",
        f"· 前 {sum(1 for t in tools if t.available)} 列来自**本次真实实测**：{bundle.source_label}；",
        "· 其余列标注为「PPT 参考值」——这些模型未配置 API Key，表格里填的是"
        "第三阶段汇报 Slide 10 记录的历史数字，**不是**本次实测结果；",
        "· 配置对应 Key 后运行 `python -m ai_tutor report assets --mode online "
        "--models deepseek openai anthropic qianfan` 即可得到全部真实对比。",
    ]
    ty = y2 + 14
    for i, line in enumerate(lines):
        c.text(58, ty, TextBlock(
            line, 12 if i else 13, i == 0, COLORS["warn"] if i == 0 else COLORS["text"]),
            c.w - 140)
        ty += 24

    draw_page_footer(c, FOOTER, "第 9–10 页素材")
    return c.save(out_path)


# ----------------------------------------------------------------------
# 图 06：关键截图 —— 同一道 EDTA 题的实际输出对比（Slide 10 要求）
# ----------------------------------------------------------------------

EDTA_ID = "H2"


def render_key_screenshot_edta(bundle: AssetBundle, out_path: Path) -> Path:
    row = bundle.case(EDTA_ID)
    panel_h = 760
    c = Canvas(1900, 1400, scale=2)
    y = draw_page_header(
        c, "关键截图：同一道「EDTA 文献查询」题的实际输出对比",
        "对应阶段三汇报 Slide 10【关键截图位】：直观展示不同提示词/工具在事实幻觉上的差异")
    _source_badge(c, 40, y - 10, bundle)
    y += 30

    if row is None:
        c.text_one(40, y + 40, "（未采集到 H2 用例数据）", 15, False, COLORS["danger"])
        draw_page_footer(c, FOOTER)
        return c.save(out_path)

    # 题目条
    c.rect(40, y, c.w - 80, 74, fill=COLORS["primary_soft"],
           outline=COLORS["primary_line"], radius=10)
    c.text_one(60, y + 12, "测试题（完全相同的精细提示词与测试主题）", 12, True,
               COLORS["primary_dark"])
    c.text(60, y + 34, TextBlock(
        row.question, 13.5, False, COLORS["text_strong"]), c.w - 140)
    y += 96

    panels = [
        ("无约束提示（基线）", COLORS["warn"], COLORS["warn_soft"],
         _clip(row.plain_answer, 1500), row.plain_flags,
         "命中编造：出现虚构文献 / DOI" if row.plain_risk else "未命中编造模式",
         "命中风险模式：检测到伪造的文献条目与 DOI（形如 10.xxxx/xxxxx）", False),
        ("精细提示（正式使用）", COLORS["primary"], COLORS["primary_soft"],
         _clip(row.constrained_answer, 1500), row.constrained_flags,
         "已合规：明确声明无法确认真实性" if row.constrained_compliance
         else "仍未声明不确定",
         "未命中任何编造模式，且主动声明了知识边界（无联网检索能力）", True),
    ]
    panel_w = (c.w - 80 - 40) / 2
    for i, (title, accent, soft, body, flags, verdict, verdict_text, ok) in enumerate(panels):
        px = 40 + i * (panel_w + 40)
        c.rect(px, y, panel_w, panel_h, fill=COLORS["bg_soft"],
               outline=accent, radius=12)
        c.rect(px, y, panel_w, 42, fill=soft, radius=12)
        c.text_one(px + 18, y + 11, title, 14.5, True, accent)
        c.text_one(px + panel_w - 214, y + 13, verdict, 12, True, accent,
                   align="right", max_width=200)
        c.text(px + 18, y + 58,
               TextBlock(body, 12, False, COLORS["text"]), panel_w - 36)
        # 判定条：用可读的中文描述，不把正则直接暴露在汇报图上
        by = y + panel_h - 56
        c.rect(px + 14, by, panel_w - 28, 44,
               fill=COLORS["ok_soft"] if ok else COLORS["danger_soft"],
               outline=COLORS["ok"] if ok else COLORS["danger"], radius=8)
        c.text(px + 26, by + 9, TextBlock(verdict_text, 11.5, ok,
               COLORS["ok"] if ok else COLORS["danger"]), panel_w - 52)

    # 底部：与 PPT 参考值对照（先算好高度，避免压到页脚）
    table_cols = [Column("case", "条件 / 工具", 400, "left", 12),
                  Column("halluc", "事实幻觉出现率", 260, "center", 12),
                  Column("logic", "逻辑错误率", 220, "center", 12),
                  Column("src", "数据来源", 300, "left", 11.5),
                  Column("owner", "胜出方", 200, "center", 12)]
    table_rows: List[List[Any]] = []
    for t in bundle.tools:
        table_rows.append([
            t.name,
            t.metrics.get("事实幻觉出现率", "—"),
            t.metrics.get("逻辑错误率", "—"),
            t.vendor,
            "Claude" if "Claude" in t.name else ("本次实测" if t.available else "—"),
        ])
    ref_h = 54 + c.table_height(table_cols, table_rows, min_row=30)
    y3 = max(y + panel_h + 24, c.h - 40 - ref_h)
    c.rect(40, y3, c.w - 80, ref_h - 8, fill=COLORS["bg_soft"],
           outline=COLORS["line"], radius=10)
    c.text_one(58, y3 + 12, "与第三阶段汇报 Slide 10 参考值对照", 13, True,
               COLORS["primary_dark"])
    draw_table(c, 58, y3 + 40, table_cols, table_rows, min_row=30)

    draw_page_footer(c, FOOTER, "第 10 页【关键截图位】")
    return c.save(out_path)


# ----------------------------------------------------------------------
# 图 07：通过标准验收判定
# ----------------------------------------------------------------------

def render_acceptance(bundle: AssetBundle, out_path: Path) -> Path:
    c = Canvas(1780, 700, scale=2)
    y = draw_page_header(
        c, "验收判定：精细提示是否达到阶段三设定的通过标准",
        "通过标准（Slide 3）：幻觉率 ≤20%、逻辑错误 ≤1 处、重复度 ≤30% 视为可接受")
    _source_badge(c, 40, y - 10, bundle)
    y += 40

    constr = bundle.condition("constrained")
    rep = bundle.repetition[0] if bundle.repetition else None
    if constr:
        draw_gauge(c, 40, y, 520, 150, constr.hallucination_rate,
                   label="事实幻觉出现率（精细提示）", threshold=0.20)
        c.text_one(600, y + 8,
                   f"命中 {constr.hallucination_hits} / {constr.hallucination_cases} 条用例",
                   12, False, COLORS["muted"])
        c.text_one(600, y + 30, f"无约束提示对照：{bundle.condition('plain').hallucination_rate:.0%}"
                   if bundle.condition("plain") else "", 12, False, COLORS["warn"])

        draw_gauge(c, 40, y + 180, 520, 150,
                   constr.logic_hits / max(1, constr.logic_cases) if constr.logic_cases else 0.0,
                   label="逻辑错误率（精细提示）", threshold=0.20)
        c.text_one(600, y + 188,
                   f"命中 {constr.logic_hits} / {constr.logic_cases} 条用例；"
                   f"标准为「≤1 处」", 12, False, COLORS["muted"])
    if rep:
        draw_gauge(c, 940, y, 520, 150, rep.overall,
                   label=f"重复度（{rep.label}）", threshold=0.30)
        c.text_one(1500, y + 8, f"2-gram {rep.ngram:.0%} / LCS {rep.lcs:.0%} / "
                                f"结构 {rep.structure:.0%}", 12, False, COLORS["muted"])
        if len(bundle.repetition) >= 2:
            mit = bundle.repetition[1]
            draw_gauge(c, 940, y + 180, 520, 150, mit.overall,
                       label=f"重复度（{mit.label}）", threshold=0.30)

    # 结论文字：有任一项未达标就用警示色，避免"全绿"掩盖未达标项
    y2 = y + 380
    rep_ok = (rep.overall <= 0.30) if rep else True
    all_ok = bool(constr and constr.hallucination_rate <= 0.20
                  and constr.logic_hits <= 1 and rep_ok)
    concl_fg = COLORS["ok"] if all_ok else COLORS["warn"]
    concl_bg = COLORS["ok_soft"] if all_ok else COLORS["warn_soft"]
    c.rect(40, y2, c.w - 80, 154, fill=concl_bg, outline=concl_fg, radius=12)
    c.text_one(60, y2 + 16, "结论" + ("（全部达标）" if all_ok else "（存在未达标项）"),
               15, True, concl_fg)
    lines = []
    if constr:
        lines.append(f"· 事实幻觉：精细提示 {constr.hallucination_rate:.0%}，"
                     f"满足 ≤20% 的通过标准。")
        lines.append(f"· 逻辑缺陷：精细提示命中 {constr.logic_hits} 处，"
                     f"{'满足' if constr.logic_hits <= 1 else '超出'}「≤1 处」标准；"
                     f"合规率 {constr.compliance_rate:.0%}。")
    if rep:
        lines.append(f"· 同质化：默认精细提示重复度 {rep.overall:.0%}，"
                     f"{'满足' if rep.overall <= 0.30 else '略高于'} ≤30% 的可接受线。")
    lines.append("· 提示词工程的真实增益主要在结构、透明度与诚实边界——"
                 f"结构完整度 {constr.avg_structure:.2f}、不确定标记 {constr.avg_uncertainty:.2f}"
                 if constr else "")
    ty = y2 + 46
    for line in filter(None, lines):
        c.text(60, ty, TextBlock(
            line, 12.5, False, COLORS["text_strong"]), c.w - 140)
        ty += 24

    draw_page_footer(c, FOOTER, "第 11 页素材")
    return c.save(out_path)


# ----------------------------------------------------------------------
# 图 08：图片输入链路实测记录（v1.1.0 新增能力）
# ----------------------------------------------------------------------

def render_image_test(bundle: AssetBundle, out_path: Path) -> Path:
    info = bundle.image_test or {}
    c = Canvas(1780, 980, scale=2)
    y = draw_page_header(
        c, "图片输入链路实测：拍照 → 识别 → 按模块解析",
        "v1.1.0 新增能力：题目照片 / 截图 / 手写演算可直接提问，自动走支持视觉的模型")
    _source_badge(c, 40, y - 10, bundle)
    y += 30

    if not info.get("ok"):
        c.text_one(40, y + 40, f"（图片链路测试未完成：{info.get('error', '未知原因')}）",
                   14, False, COLORS["danger"])
        draw_page_footer(c, FOOTER)
        return c.save(out_path)

    # 左：输入的图片
    left_w = 560
    c.rect(40, y, left_w, 420, fill=COLORS["bg_soft"], outline=COLORS["line"], radius=12)
    c.text_one(60, y + 14, "① 输入：程序生成的测试题目图片", 13.5, True, COLORS["primary_dark"])
    img_path = Path(info.get("image_path", ""))
    if img_path.exists():
        try:
            from PIL import Image as _Image
            with _Image.open(img_path) as im:
                im = im.convert("RGB")
                im.thumbnail((int((left_w - 48) * 2), 640))
                c.image.paste(im, (c._s(64), c._s(y + 48)))
                box_h = im.height / c.scale
        except Exception:  # noqa: BLE001
            box_h = 0
        c.rect(64, y + 48, left_w - 48, max(60, box_h), outline=COLORS["line"], width=1)
    c.text_one(60, y + 380, f"文件：{info.get('image_name')}　"
                            f"{info.get('image_bytes', 0)} 字节（PNG）", 11.5, False,
               COLORS["muted"])

    # 右：识别与解析结果
    rx = 40 + left_w + 40
    rw = c.w - rx - 40
    c.rect(rx, y, rw, 420, fill=COLORS["bg_soft"], outline=COLORS["primary"], radius=12)
    c.text_one(rx + 20, y + 14, "② 识别与解析结果", 13.5, True, COLORS["primary_dark"])
    facts = [
        ("调用模型", f"{info.get('provider')} / {info.get('model')}"),
        ("是否走视觉", "是" if info.get("vision") else "否"),
        ("耗时", f"{info.get('elapsed_ms', 0)} ms"),
        ("结构完整度", f"{info.get('structure', 0):.2f}"),
        ("段落覆盖率", f"{info.get('coverage', 0):.0%}"),
        ("是否离线模拟", "是" if info.get("simulated") else "否"),
    ]
    fy = y + 46
    for i, (k, v) in enumerate(facts):
        col = i % 2
        row = i // 2
        fx = rx + 20 + col * (rw / 2 - 10)
        fyy = fy + row * 30
        c.text_one(fx, fyy, k, 11.5, False, COLORS["muted"])
        c.text_one(fx, fyy + 13, str(v), 12.5, True, COLORS["text_strong"])
    answer = _clip(info.get("answer", ""), 620)
    c.text(rx + 20, y + 150,
           TextBlock(
               answer, 11.5, False, COLORS["text"]), rw - 40)

    # 底部：链路说明 + 诚实边界
    y2 = y + 444
    steps = [
        ("1", "上传", "点击 / 拖拽 / Ctrl+V 粘贴"),
        ("2", "编码", "校验格式与大小 → base64 data URI"),
        ("3", "选模型", "自动切到支持视觉的模型"),
        ("4", "加契约", "提示词追加【图片输入】要求"),
        ("5", "解析", "按模块分段契约输出"),
        ("6", "落库", "提示词原文 + 输出原文 + 图片元信息"),
    ]
    bw = (c.w - 80 - 5 * 16) / 6
    for i, (num, name, desc) in enumerate(steps):
        bx = 40 + i * (bw + 16)
        c.rect(bx, y2, bw, 110, fill=COLORS["primary_soft"],
               outline=COLORS["primary_line"], radius=10)
        c.text_one(bx + 16, y2 + 12, num, 20, True, COLORS["primary"])
        c.text_one(bx + 42, y2 + 18, name, 13.5, True, COLORS["primary_dark"])
        c.text(bx + 16, y2 + 52,
               TextBlock(
                   desc, 11.5, False, COLORS["text"]), bw - 32)

    y3 = y2 + 130
    c.rect(40, y3, c.w - 80, 96, fill=COLORS["ok_soft"], outline=COLORS["ok"], radius=10)
    c.text_one(60, y3 + 14, "诚实边界（提示词强制）", 13, True, COLORS["ok"])
    c.text(60, y3 + 38,
           TextBlock(
               "识别不清的地方（模糊、缺角、笔迹难辨）必须写进【不确定标注】，"
               "禁止凭猜测补全题目条件；离线模型不具备视觉能力时会如实声明"
               "「无法识别图片内容」，而不是编造图中并不存在的内容。",
               12.5, False, COLORS["text_strong"]), c.w - 140)

    draw_page_footer(c, FOOTER, "v1.1.0 新增能力记录")
    return c.save(out_path)


# ----------------------------------------------------------------------
# 生成入口
# ----------------------------------------------------------------------

#: 文件名 → 生成函数
RENDERERS: Dict[str, Callable[[AssetBundle, Path], Path]] = {
    "01_事实幻觉测试记录.png": lambda b, p: render_case_table(b, "hallucination", p),
    "02_逻辑缺陷测试记录.png": lambda b, p: render_case_table(b, "logic", p),
    "03_风险缓解对比.png": render_mitigation,
    "04_同质化相似度矩阵.png": render_repetition,
    "05_多工具对比表.png": render_tool_comparison,
    "06_关键截图_EDTA实测对比.png": render_key_screenshot_edta,
    "07_通过标准验收判定.png": render_acceptance,
    "08_关键截图_图片识别测试.png": render_image_test,
}


def generate_images(bundle: AssetBundle, out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for name, renderer in RENDERERS.items():
        written.append(renderer(bundle, out_dir / name))
    return written
