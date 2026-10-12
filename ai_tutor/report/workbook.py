"""生成 Excel 版风险实证记录表（openpyxl，含原生图表与条件格式）。

为什么同时给 Excel：
  · 汇报要求"测试序号 / 模块 / 测试主题 / 两版输出评价"可追溯 → 表格比图片更好查；
  · 老师/助教可以自己改数字重算，配合原生柱状图直接看结论；
  · 图片用于贴 PPT，Excel 用于交付与复核，两者同源同数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .data import AssetBundle
from .figures import CASE_ANALYSIS, CASE_TITLES

#: 与 PPT 同色系
FILL_HEADER = PatternFill("solid", fgColor="2563EB")
FILL_RISK = PatternFill("solid", fgColor="FEF2F2")
FILL_OK = PatternFill("solid", fgColor="ECFDF5")
FILL_SOFT = PatternFill("solid", fgColor="EFF6FF")
FONT_HEADER = Font(name="微软雅黑", size=10.5, bold=True, color="FFFFFF")
FONT_BODY = Font(name="微软雅黑", size=10)
FONT_BOLD = Font(name="微软雅黑", size=10, bold=True)
FONT_DANGER = Font(name="微软雅黑", size=10, bold=True, color="DC2626")
FONT_OK = Font(name="微软雅黑", size=10, bold=True, color="059669")
THIN = Side(style="thin", color="D6DEE8")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center")


def _style_header(ws: Worksheet, row: int, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = FILL_HEADER
        cell.font = FONT_HEADER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[row].height = 30


def _set_widths(ws: Worksheet, widths: Sequence[int]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_workbook(bundle: AssetBundle, path: Path) -> Path:
    wb = Workbook()
    _sheet_summary(wb.active, bundle)
    _sheet_cases(wb, bundle, "hallucination")
    _sheet_cases(wb, bundle, "logic")
    _sheet_repetition(wb, bundle)
    _sheet_tools(wb, bundle)
    _sheet_acceptance(wb, bundle)
    _sheet_evidence(wb, bundle)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ----------------------------------------------------------------------

def _sheet_summary(ws: Worksheet, bundle: AssetBundle) -> None:
    ws.title = "00_测试说明"
    ws["A1"] = "第三阶段 · 风险实证记录表"
    ws["A1"].font = Font(name="微软雅黑", size=15, bold=True, color="1E3A5F")
    ws["A2"] = "大学生期末复习 AI 答疑助手 · 第二组（李明轩　韩武晋　郑志）"
    ws["A2"].font = Font(name="微软雅黑", size=10, color="6B7280")
    ws["A3"] = f"生成时间：{bundle.created_at}　　数据来源：{bundle.source_label}"
    ws["A3"].font = Font(name="微软雅黑", size=10, color="6B7280")

    rows = [
        ("测试对象", f"{bundle.model}（{'离线模型' if bundle.simulated else '真实模型'}）"),
        ("提示词设置", "同一用例分别用「精细提示」与「无约束提示」各跑一次（提示词消融对照）"),
        ("记录方式", "测试序号 / 模块 / 测试主题 / 两版输出评价 / 关键截图"),
        ("评价维度", "结构完整性 / 事实准确性 / 逻辑严谨性 / 幻觉出现率 / 同质化程度"),
        ("通过标准", "精细提示下：幻觉率 ≤20%、逻辑错误 ≤1 处、重复度 ≤30%"),
        ("用例总数", f"事实幻觉 {sum(1 for c in bundle.cases if c.kind == 'hallucination')} 条"
                     f" + 逻辑缺陷 {sum(1 for c in bundle.cases if c.kind == 'logic')} 条"),
        ("说明", "本表中「无约束提示」列仅用于量化提示词结构的贡献，"
                 "应用对外只使用精细提示，界面上没有模式开关。"),
    ]
    r = 5
    for k, v in rows:
        ws.cell(row=r, column=1, value=k).font = FONT_BOLD
        ws.cell(row=r, column=1).fill = FILL_SOFT
        ws.cell(row=r, column=1).border = BORDER
        c = ws.cell(row=r, column=2, value=v)
        c.font = FONT_BODY
        c.alignment = WRAP
        c.border = BORDER
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
        r += 1

    if bundle.extra_notes:
        ws.cell(row=r + 1, column=1, value="备注").font = FONT_BOLD
        for i, note in enumerate(bundle.extra_notes):
            c = ws.cell(row=r + 2 + i, column=2, value=note)
            c.font = Font(name="微软雅黑", size=10, color="EA580C")
            c.alignment = WRAP
            ws.merge_cells(start_row=r + 2 + i, start_column=2, end_row=r + 2 + i, end_column=6)
    _set_widths(ws, [14, 26, 18, 18, 18, 18])


def _sheet_cases(wb: Workbook, bundle: AssetBundle, kind: str) -> None:
    title = "01_事实幻觉测试" if kind == "hallucination" else "02_逻辑缺陷测试"
    ws = wb.create_sheet(title)
    headers = ["序号", "用例编号", "模块", "测试主题", "输入提示（精简）",
               "无约束提示输出（基线）", "无约束判定", "精细提示输出",
               "精细提示判定", "风险模式（命中）", "分析结论"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))

    rows = [c for c in bundle.cases if c.kind == kind]
    for i, row in enumerate(rows, 1):
        verdict_plain = "命中风险" if row.plain_risk else ("合规" if row.plain_compliance else "—")
        verdict_fine = ("命中风险" if row.constrained_risk
                        else ("已合规" if row.constrained_compliance else "—"))
        ws.append([
            i, row.case_id, row.module, CASE_TITLES.get(row.case_id, row.title),
            row.question,
            (row.plain_answer or "")[:8000],
            verdict_plain,
            (row.constrained_answer or "")[:8000],
            verdict_fine,
            "；".join(row.plain_flags + row.constrained_flags) or "无",
            CASE_ANALYSIS.get(row.case_id, ""),
        ])
        r = i + 1
        ws.row_dimensions[r].height = 150
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=col)
            cell.border = BORDER
            cell.alignment = WRAP
            cell.font = FONT_BODY
        for col in (1, 2, 3):
            ws.cell(row=r, column=col).alignment = CENTER
        if verdict_plain == "命中风险":
            ws.cell(row=r, column=7).font = FONT_DANGER
            ws.cell(row=r, column=7).fill = FILL_RISK
        if verdict_fine == "命中风险":
            ws.cell(row=r, column=9).font = FONT_DANGER
            ws.cell(row=r, column=9).fill = FILL_RISK
        elif verdict_fine == "已合规":
            ws.cell(row=r, column=9).font = FONT_OK
            ws.cell(row=r, column=9).fill = FILL_OK

    _set_widths(ws, [6, 10, 8, 26, 44, 60, 12, 60, 12, 30, 36])
    ws.freeze_panes = "E2"


def _sheet_repetition(wb: Workbook, bundle: AssetBundle) -> None:
    ws = wb.create_sheet("03_同质化测试")
    ws["A1"] = "同一任务重复 3 次的相似度（对应汇报 Slide 8）"
    ws["A1"].font = Font(name="微软雅黑", size=12, bold=True, color="1E3A5F")
    row = 3
    for block in bundle.repetition:
        ws.cell(row=row, column=1, value=block.label).font = FONT_BOLD
        ws.cell(row=row, column=1).fill = FILL_SOFT
        row += 1
        headers = ["", "平均相似度", "2-gram Jaccard", "LCS 占比", "结构相似度", "平均字数"]
        ws.append([]) if False else None
        for j, h in enumerate(headers, 1):
            cell = ws.cell(row=row, column=j, value=h)
            cell.font = FONT_HEADER if j > 1 else FONT_BODY
            if j > 1:
                cell.fill = FILL_HEADER
                cell.alignment = CENTER
        ws.cell(row=row, column=1, value="指标")
        ws.cell(row=row, column=1).font = FONT_HEADER
        ws.cell(row=row, column=1).fill = FILL_HEADER
        ws.cell(row=row, column=1).alignment = CENTER
        row += 1
        ws.cell(row=row, column=1, value="数值").font = FONT_BODY
        for j, v in enumerate([block.overall, block.ngram, block.lcs, block.structure],
                              2):
            cell = ws.cell(row=row, column=j, value=round(v, 4))
            cell.number_format = "0.0%"
            cell.font = FONT_BOLD
            cell.alignment = CENTER
            if v > 0.30:
                cell.fill = FILL_RISK
                cell.font = FONT_DANGER
            else:
                cell.fill = FILL_OK
                cell.font = FONT_OK
        ws.cell(row=row, column=6, value=block.avg_chars).alignment = CENTER
        data_row = row
        row += 2

        # 相似度矩阵（含原生折线图引用所需的数据）
        ws.cell(row=row, column=1, value="相似度矩阵").font = FONT_BOLD
        row += 1
        labels = [f"第 {i + 1} 次" for i in range(len(block.texts))]
        for j, lab in enumerate(labels, 2):
            ws.cell(row=row, column=j, value=lab).font = FONT_BOLD
            ws.cell(row=row, column=j).alignment = CENTER
        for i, lab in enumerate(labels):
            ws.cell(row=row + 1 + i, column=1, value=lab).font = FONT_BOLD
            for j in range(len(labels)):
                v = block.pair_matrix[i][j]
                cell = ws.cell(row=row + 1 + i, column=2 + j, value=round(v, 4))
                cell.number_format = "0%"
                cell.alignment = CENTER
                cell.border = BORDER
                if i != j:
                    cell.fill = FILL_RISK if v > 0.6 else FILL_OK
        row += len(labels) + 3

    # 原生图表：两组重复度对比
    if len(bundle.repetition) >= 2:
        chart = BarChart()
        chart.type = "col"
        chart.title = "重复度对比：默认精细提示 vs 反同质化约束"
        chart.y_axis.title = "平均相似度"
        chart.y_axis.numFmt = "0%"
        chart.height, chart.width = 8, 16
        ws.cell(row=row, column=1, value="用于图表的数据").font = FONT_BOLD
        ws.cell(row=row + 1, column=1, value="条件")
        ws.cell(row=row + 1, column=2, value="平均相似度")
        for i, block in enumerate(bundle.repetition):
            ws.cell(row=row + 2 + i, column=1, value=block.label)
            c = ws.cell(row=row + 2 + i, column=2, value=round(block.overall, 4))
            c.number_format = "0.0%"
        data = Reference(ws, min_col=2, min_row=row + 1,
                         max_row=row + 1 + len(bundle.repetition))
        cats = Reference(ws, min_col=1, min_row=row + 2,
                         max_row=row + 1 + len(bundle.repetition))
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        ws.add_chart(chart, f"A{row + 6}")
    _set_widths(ws, [26, 16, 16, 14, 14, 14])


def _sheet_tools(wb: Workbook, bundle: AssetBundle) -> None:
    ws = wb.create_sheet("04_多工具对比")
    ws["A1"] = "多工具横向对比（对应汇报 Slide 10）"
    ws["A1"].font = Font(name="微软雅黑", size=12, bold=True, color="1E3A5F")
    dimensions = ["事实幻觉出现率", "逻辑错误率", "结构完整性", "中文表达自然度", "重复度"]
    headers = ["评价维度"] + [t.name for t in bundle.tools] + ["数据来源说明"]
    ws.append([]) if False else None
    for j, h in enumerate(headers, 1):
        ws.cell(row=3, column=j, value=h)
    _style_header(ws, 3, len(headers))
    for i, dim in enumerate(dimensions):
        r = 4 + i
        ws.cell(row=r, column=1, value=dim).font = FONT_BOLD
        ws.cell(row=r, column=1).fill = FILL_SOFT
        ws.cell(row=r, column=1).border = BORDER
        for j, t in enumerate(bundle.tools, 2):
            cell = ws.cell(row=r, column=j, value=t.metrics.get(dim, "—"))
            cell.font = FONT_BODY if t.available else Font(name="微软雅黑", size=10,
                                                           color="9CA3AF")
            cell.alignment = WRAP
            cell.border = BORDER
        src = ws.cell(row=r, column=len(bundle.tools) + 2,
                      value="本次实测" if all(t.available for t in bundle.tools)
                      else "标注「PPT 参考值」的列为第三阶段汇报的历史数字，非本次实测")
        src.font = Font(name="微软雅黑", size=9, color="6B7280")
        src.alignment = WRAP
    _set_widths(ws, [20] + [30] * len(bundle.tools) + [40])


def _sheet_acceptance(wb: Workbook, bundle: AssetBundle) -> None:
    ws = wb.create_sheet("05_通过标准验收")
    ws["A1"] = "通过标准验收（Slide 3：幻觉率 ≤20%、逻辑错误 ≤1 处、重复度 ≤30%）"
    ws["A1"].font = Font(name="微软雅黑", size=12, bold=True, color="1E3A5F")
    headers = ["指标", "无约束提示", "精细提示（正式使用）", "通过标准", "判定"]
    for j, h in enumerate(headers, 1):
        ws.cell(row=3, column=j, value=h)
    _style_header(ws, 3, len(headers))

    plain = bundle.condition("plain")
    constr = bundle.condition("constrained")
    rep = bundle.repetition[0] if bundle.repetition else None
    rows: List[Sequence] = []
    if plain and constr:
        rows += [
            ("事实幻觉出现率", plain.hallucination_rate, constr.hallucination_rate,
             "≤20%", constr.hallucination_rate <= 0.20),
            ("逻辑错误率", plain.logic_error_rate, constr.logic_error_rate,
             "≤20%（≤1 处）", constr.logic_hits <= 1),
            ("合规率", plain.compliance_rate, constr.compliance_rate, "—", None),
            ("结构完整度", plain.avg_structure, constr.avg_structure, "—", None),
            ("不确定标记", plain.avg_uncertainty, constr.avg_uncertainty, "—", None),
            ("平均输出字数", plain.avg_chars, constr.avg_chars, "—", None),
        ]
    if rep:
        rows.append(("同质化重复度", None, rep.overall, "≤30%", rep.overall <= 0.30))

    r = 4
    for name, before, after, standard, ok in rows:
        ws.cell(row=r, column=1, value=name).font = FONT_BOLD
        ws.cell(row=r, column=1).fill = FILL_SOFT
        ws.cell(row=r, column=1).border = BORDER
        is_pct = name in ("事实幻觉出现率", "逻辑错误率", "合规率",
                          "同质化重复度", "结构完整度", "不确定标记")
        for col, val in ((2, before), (3, after)):
            if val is None:
                ws.cell(row=r, column=col, value="—").alignment = CENTER
                continue
            cell = ws.cell(row=r, column=col, value=round(float(val), 4) if is_pct else val)
            if is_pct:
                cell.number_format = "0.0%"
            cell.alignment = CENTER
            cell.border = BORDER
            cell.font = FONT_BOLD if col == 3 else FONT_BODY
        ws.cell(row=r, column=4, value=standard).alignment = CENTER
        if ok is None:
            ws.cell(row=r, column=5, value="—").alignment = CENTER
        else:
            cell = ws.cell(row=r, column=5, value="达标 ✓" if ok else "未达标 ✗")
            cell.font = FONT_OK if ok else FONT_DANGER
            cell.fill = FILL_OK if ok else FILL_RISK
            cell.alignment = CENTER
        for col in range(1, 6):
            ws.cell(row=r, column=col).border = BORDER
        r += 1

    # 原生柱状图：三个核心指标的无约束 vs 精细
    if plain and constr:
        chart = BarChart()
        chart.type = "col"
        chart.title = "核心风险指标：无约束提示 vs 精细提示"
        chart.y_axis.title = "比例"
        chart.y_axis.numFmt = "0%"
        chart.height, chart.width = 8.5, 17
        base = r + 2
        ws.cell(row=base, column=1, value="条件")
        ws.cell(row=base, column=2, value="事实幻觉出现率")
        ws.cell(row=base, column=3, value="逻辑错误率")
        ws.cell(row=base, column=4, value="合规率")
        ws.cell(row=base + 1, column=1, value="无约束提示")
        for col, v in ((2, plain.hallucination_rate), (3, plain.logic_error_rate),
                       (4, plain.compliance_rate)):
            cell = ws.cell(row=base + 1, column=col, value=round(v, 4))
            cell.number_format = "0.0%"
        ws.cell(row=base + 2, column=1, value="精细提示")
        for col, v in ((2, constr.hallucination_rate), (3, constr.logic_error_rate),
                       (4, constr.compliance_rate)):
            cell = ws.cell(row=base + 2, column=col, value=round(v, 4))
            cell.number_format = "0.0%"
        data = Reference(ws, min_col=2, max_col=4, min_row=base, max_row=base + 2)
        cats = Reference(ws, min_col=1, min_row=base + 1, max_row=base + 2)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        ws.add_chart(chart, f"A{base + 5}")

    _set_widths(ws, [22, 18, 24, 18, 14])


def _sheet_evidence(wb: Workbook, bundle: AssetBundle) -> None:
    ws = wb.create_sheet("06_关键截图说明")
    ws["A1"] = "关键截图说明（对应汇报 Slide 10【关键截图位】）"
    ws["A1"].font = Font(name="微软雅黑", size=12, bold=True, color="1E3A5F")
    rows = [
        ("01_事实幻觉测试记录.png", "H1–H6 的提问、两版输出与命中判定", "Slide 4–5"),
        ("02_逻辑缺陷测试记录.png", "L1–L5 的提问、两版输出与改善结论", "Slide 6–7"),
        ("03_风险缓解对比.png", "幻觉率/逻辑错误率/合规率 分组柱状对比", "Slide 7、11"),
        ("04_同质化相似度矩阵.png", "重复 3 次的两两相似度热力图 + 反同质化对照", "Slide 8"),
        ("05_多工具对比表.png", "三工具五维度汇总（含数据来源标注）", "Slide 9–10"),
        ("06_关键截图_EDTA实测对比.png",
         "同一道 EDTA 题在无约束/精细提示下的实际输出并排对照", "Slide 10【关键截图位】"),
        ("07_通过标准验收判定.png", "幻觉率/逻辑错误/重复度 三个指标卡与结论", "Slide 11"),
        ("08_关键截图_图片识别测试.png", "图片输入链路实测（v1.1.0 新增能力）", "阶段四素材"),
    ]
    headers = ["文件名", "内容说明", "对应汇报页"]
    for j, h in enumerate(headers, 1):
        ws.cell(row=3, column=j, value=h)
    _style_header(ws, 3, len(headers))
    for i, (name, desc, page) in enumerate(rows):
        r = 4 + i
        ws.cell(row=r, column=1, value=name).font = FONT_BODY
        ws.cell(row=r, column=2, value=desc).font = FONT_BODY
        ws.cell(row=r, column=3, value=page).font = FONT_BODY
        for col in range(1, 4):
            ws.cell(row=r, column=col).border = BORDER
            ws.cell(row=r, column=col).alignment = WRAP
    _set_widths(ws, [34, 58, 18])
