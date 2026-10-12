"""第三阶段风险实证的图片与表格素材生成。

对应汇报 Slide 3「记录方式：测试序号 / 模块 / 测试主题 / 两版输出评价 / **关键截图**」
与 Slide 10「【关键截图位】此处可粘贴三工具在同一道 EDTA 题下的实际输出对比截图」。

产出（默认写入 `deliverables/风险实证图解/`）：

   01_事实幻觉测试记录.png       H1–H6：提问 / 无约束输出 / 精细提示输出 / 分析结论
   02_逻辑缺陷测试记录.png       L1–L5：同上
   03_风险缓解对比.png           幻觉率·逻辑错误率·合规率 的分组柱状对比
   04_同质化相似度矩阵.png       重复 3 次的两两相似度热力图 + 反同质化对照
   05_多工具对比与结论.png       三工具五维度汇总表（含数据来源标注）
   06_关键截图_EDTA实测对比.png  同一道 EDTA 题在三种条件下的实际输出对照（Slide 10 用）
   07_通过标准验收判定.png       幻觉率/逻辑错误/重复度 三个指标卡
   08_关键截图_图片识别测试.png   图片输入链路实测记录（v1.1.0 新增能力）
   风险实证记录表.xlsx           Excel 版记录表（含原生图表与条件格式）

所有数字都来自**真实执行的测试**（在线模型或离线模型），并在图上标注数据来源；
不做任何人工编造的"好看数字"。
"""

from __future__ import annotations

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
from .data import AssetBundle, collect_assets, load_bundle_from_reports
from .generate import DEFAULT_OUTDIR, AssetResult, generate_all

__all__ = [
    "COLORS",
    "Column",
    "Canvas",
    "TextBlock",
    "draw_badge",
    "draw_bar_group",
    "draw_gauge",
    "draw_page_footer",
    "draw_page_header",
    "draw_similarity_matrix",
    "draw_table",
    "AssetBundle",
    "collect_assets",
    "load_bundle_from_reports",
    "AssetResult",
    "DEFAULT_OUTDIR",
    "generate_all",
]
