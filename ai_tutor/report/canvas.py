"""图片绘制基础设施：中文字体、HiDPI 画布、主题色、表格 / 柱状图 / 热力图。

为什么自己画而不是用 matplotlib：
1) 项目坚持**零第三方依赖**（原方案只用标准库），引入 matplotlib 会破坏这一点；
2) 汇报材料需要的是"表格截图 + 对照图"，用 Pillow 直接绘制反而更可控、更贴近 PPT 版式；
3) 生成的是**给人看的记录图**，字号、留白、换行都要精确控制，Pillow 更直接。

主题配色取自第三阶段汇报 PPT 的实际用色（主色 #2563EB，危险色 #DC2626，
警示色 #EA580C，正文 #374151，辅助文字 #6B7280，浅底 #EFF6FF）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# 主题
# ----------------------------------------------------------------------

#: 与第三阶段汇报 PPT 一致的配色
COLORS: Dict[str, str] = {
    "primary": "#2563EB",       # 主色（PPT 标题蓝）
    "primary_dark": "#1E3A5F",  # 深蓝（PPT 深色标题）
    "primary_soft": "#EFF6FF",  # 浅蓝底
    "primary_line": "#BFDBFE",  # 浅蓝边框
    "text": "#374151",          # 正文
    "text_strong": "#111827",   # 强调正文
    "muted": "#6B7280",         # 辅助文字
    "muted_soft": "#9CA3AF",    # 更浅的辅助文字
    "line": "#D6DEE8",          # 分隔线
    "bg": "#FFFFFF",            # 页面底色
    "bg_soft": "#F8FAFC",       # 表头底色
    "danger": "#DC2626",        # 风险命中（红）
    "danger_soft": "#FEF2F2",   # 风险浅底
    "warn": "#EA580C",          # 警示（橙）
    "warn_soft": "#FFF7ED",
    "ok": "#059669",            # 通过（绿）
    "ok_soft": "#ECFDF5",
    "row_alt": "#FBFCFE",       # 斑马纹
}

#: 各"提示词条件"对应的颜色，保证多张图里同一条件颜色一致
CONDITION_COLORS: Dict[str, str] = {
    "plain": "#EA580C",
    "constrained": "#2563EB",
    "baseline": "#94A3B8",
}

#: 中文字体候选（按优先级）。优先使用无衬线中文字体，保证小字号下清晰。
_FONT_CANDIDATES_BOLD = (
    r"C:\Windows\Fonts\msyhbd.ttc",   # 微软雅黑 Bold
    r"C:\Windows\Fonts\Dengb.ttf",    # 等线 Bold
    r"C:\Windows\Fonts\simhei.ttf",   # 黑体
    r"C:\Windows\Fonts\msjhbd.ttc",
)
_FONT_CANDIDATES_REGULAR = (
    r"C:\Windows\Fonts\msyh.ttc",     # 微软雅黑
    r"C:\Windows\Fonts\Deng.ttf",     # 等线
    r"C:\Windows\Fonts\simsun.ttc",   # 宋体
    r"C:\Windows\Fonts\msjh.ttc",
)


class FontBook:
    """字体注册表：按字号缓存，避免重复加载大字体文件。"""

    def __init__(self, scale: int = 2) -> None:
        self.scale = scale
        self._cache: Dict[Tuple[bool, int], ImageFont.FreeTypeFont] = {}
        self._bold_path = self._first_existing(_FONT_CANDIDATES_BOLD)
        self._regular_path = self._first_existing(_FONT_CANDIDATES_REGULAR)

    @staticmethod
    def _first_existing(paths: Sequence[str]) -> Optional[str]:
        for p in paths:
            if Path(p).exists():
                return p
        return None

    def get(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = (bold, size)
        if key in self._cache:
            return self._cache[key]
        path = self._bold_path if bold else self._regular_path
        px = max(8, int(round(size * self.scale)))
        font: ImageFont.FreeTypeFont
        if path:
            try:
                font = ImageFont.truetype(path, px)
            except OSError:
                font = ImageFont.load_default()
        else:
            font = ImageFont.load_default()
        self._cache[key] = font
        return font

    def measure(self, text: str, size: int, bold: bool = False) -> Tuple[int, int]:
        """返回**逻辑像素**尺寸（已按 scale 折算）。"""
        font = self.get(size, bold)
        box = font.getbbox(text or " ")
        return ((box[2] - box[0]) / self.scale, (box[3] - box[1]) / self.scale)


@dataclass
class TextBlock:
    """一段可绘制文本（支持自动换行）。"""

    text: str
    size: int = 14
    bold: bool = False
    color: str = COLORS["text"]
    align: str = "left"      # left | center | right
    line_gap: float = 1.55


class Canvas:
    """HiDPI 画布：所有坐标与字号都用**逻辑像素**，内部按 scale 放大以保证清晰。"""

    def __init__(self, width: int, height: int, scale: int = 2,
                 bg: str = COLORS["bg"]) -> None:
        self.w = width
        self.h = height
        self.scale = scale
        self.fonts = FontBook(scale)
        self.image = Image.new("RGB", (width * scale, height * scale), bg)
        self.draw = ImageDraw.Draw(self.image)

    # ------------------------------------------------------------ 基础
    def _s(self, v: float) -> int:
        return int(round(v * self.scale))

    def rect(self, x: float, y: float, w: float, h: float, fill: Optional[str] = None,
             outline: Optional[str] = None, width: float = 1, radius: float = 0) -> None:
        # 空尺寸直接跳过：数值为 0 的柱子在 Pillow 里会因为 y1 < y0 抛错。
        # 只要没有描边需求就直接返回（纯填充的 0 高度柱子本来就看不见）。
        if (w <= 0.6 or h <= 0.6) and outline is None:
            return
        w = max(w, 0.6)
        h = max(h, 0.6)
        box = [self._s(x), self._s(y), self._s(x + w) - 1, self._s(y + h) - 1]
        if box[2] < box[0]:
            box[2] = box[0]
        if box[3] < box[1]:
            box[3] = box[1]
        if radius > 0:
            max_radius = max(0, min((box[2] - box[0]) // 2, (box[3] - box[1]) // 2))
            self.draw.rounded_rectangle(box, radius=min(self._s(radius), max_radius),
                                        fill=fill, outline=outline,
                                        width=max(1, self._s(width)))
        else:
            self.draw.rectangle(box, fill=fill, outline=outline,
                                width=max(1, self._s(width)))

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str = COLORS["line"],
             width: float = 1) -> None:
        self.draw.line([self._s(x1), self._s(y1), self._s(x2), self._s(y2)],
                       fill=color, width=max(1, self._s(width)))

    # ------------------------------------------------------------ 文本
    def wrap(self, text: str, size: int, max_width: float, bold: bool = False) -> List[str]:
        """按显示宽度换行（中文逐字、英文按词，兼顾 URL 与长英文串）。"""
        text = (text or "").replace("\r\n", "\n")
        lines: List[str] = []
        for raw in text.split("\n"):
            if not raw:
                lines.append("")
                continue
            cur = ""
            for token in self._tokens(raw):
                probe = cur + token
                if self.fonts.measure(probe, size, bold)[0] <= max_width or not cur:
                    cur = probe
                else:
                    lines.append(cur.rstrip())
                    cur = token if token.strip() else ""
            lines.append(cur.rstrip())
        return lines

    def wrapped_height(self, text: str, size: int, max_width: float,
                       line_gap: float = 1.55, bold: bool = False) -> float:
        """一段文本换行后需要的高度（逻辑像素）。"""
        return len(self.wrap(text, size, max_width, bold)) * size * line_gap

    def table_height(self, columns: Sequence["Column"], rows: Sequence[Sequence[Any]],
                     row_pad: float = 9, min_row: float = 26) -> float:
        """预估表格总高度（含表头），用于提前判断是否会超出页面。"""
        total = 34  # 表头
        for row in rows:
            h = min_row
            for col, cell in zip(columns, row):
                text = "" if cell is None else str(cell)
                h = max(h, self.wrapped_height(text, col.size, col.width - row_pad * 2) + row_pad * 2)
            total += h
        return total

    @staticmethod
    def _tokens(line: str) -> List[str]:
        """把一行切成可换行的最小单元：中日韩单字成 token，英文数字按词。"""
        out: List[str] = []
        buf = ""
        for ch in line:
            if ch == " ":
                if buf:
                    out.append(buf)
                    buf = ""
                out.append(" ")
            elif "\u4e00" <= ch <= "\u9fff" or ch in "，。；：！？、（）【】《》“”‘’—…·":
                if buf:
                    out.append(buf)
                    buf = ""
                out.append(ch)
            else:
                buf += ch
        if buf:
            out.append(buf)
        return out

    def text(self, x: float, y: float, block: TextBlock, max_width: float,
             line_height: Optional[float] = None) -> float:
        """绘制一段（自动换行的）文本，返回下一个可用 y 坐标。"""
        lines = self.wrap(block.text, block.size, max_width, block.bold)
        lh = line_height if line_height is not None else block.size * block.line_gap
        for i, line in enumerate(lines):
            width = self.fonts.measure(line, block.size, block.bold)[0]
            if block.align == "center":
                dx = x + (max_width - width) / 2
            elif block.align == "right":
                dx = x + max_width - width
            else:
                dx = x
            self.draw.text((self._s(dx), self._s(y + i * lh)), line,
                           font=self.fonts.get(block.size, block.bold), fill=block.color)
        return y + len(lines) * lh

    def text_one(self, x: float, y: float, text: str, size: int = 14, bold: bool = False,
                 color: str = COLORS["text"], align: str = "left",
                 max_width: Optional[float] = None) -> None:
        """绘制单行文本（不换行）。align 相对 max_width 生效。"""
        self.text(x, y, TextBlock(text, size, bold, color, align),
                  max_width if max_width is not None else self.fonts.measure(text, size, bold)[0],
                  line_height=size * 1.4)

    def save(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(p, "PNG", optimize=True)
        return p


# ----------------------------------------------------------------------
# 通用版式组件
# ----------------------------------------------------------------------

@dataclass
class Column:
    """表格列定义。"""

    key: str
    title: str
    width: int
    align: str = "left"
    size: int = 12.5
    bold: bool = False


def draw_page_header(c: Canvas, title: str, subtitle: str = "", *,
                     x: float = 40, y: float = 28, width: Optional[float] = None,
                     size: int = 25) -> float:
    """页面标题 + 副标题 + 蓝色下划线，返回内容起始 y。"""
    width = width or (c.w - x * 2)
    c.rect(x, y + 3, 5, size + 6, fill=COLORS["primary"], radius=2.5)
    c.text(x + 16, y - 4, TextBlock(title, size, True, COLORS["primary_dark"]), width - 16)
    y2 = y + size + 12
    if subtitle:
        y2 = c.text(x, y2, TextBlock(subtitle, 13, False, COLORS["muted"]), width)
    c.line(x, y2 + 8, x + width, y2 + 8, COLORS["line"], 1)
    return y2 + 20


def draw_page_footer(c: Canvas, text: str, page: Optional[str] = None) -> None:
    """页脚固定贴近底边；文字过长时自动截断，避免压到正文。

    注意：页脚**不使用** c.text（会换行向上溢出）；这里只画单行并裁剪。
    """
    y = c.h - 26
    c.line(40, y - 10, c.w - 40, y - 10, COLORS["line"], 1)
    avail = c.w - 80 - (120 if page else 0)
    label = text
    if c.fonts.measure(label, 11.5)[0] > avail:
        while label and c.fonts.measure(label + "…", 11.5)[0] > avail:
            label = label[:-2]
        label += "…"
    c.text_one(40, y, label, 11.5, False, COLORS["muted_soft"])
    if page:
        c.text_one(c.w - 160, y, page, 11.5, False, COLORS["muted_soft"], align="right",
                   max_width=120)


def draw_badge(c: Canvas, x: float, y: float, text: str, *, fg: str, bg: str,
               size: int = 11.5, pad: float = 7) -> float:
    w = c.fonts.measure(text, size, True)[0] + pad * 2
    h = size + 9
    c.rect(x, y, w, h, fill=bg, radius=h / 2)
    c.text_one(x + pad, y + (h - size) / 2 - 1, text, size, True, fg)
    return x + w


def draw_table(c: Canvas, x: float, y: float, columns: Sequence[Column],
               rows: Sequence[Sequence[Any]], *, row_height: Optional[float] = None,
               header_height: float = 34, row_pad: float = 9, min_row: float = 26,
               row_styles: Optional[Sequence[Optional[Dict[str, str]]]] = None,
               max_row_height: float = 260, max_cell_chars: int = 0) -> float:
    """绘制表格，自动按列宽换行并撑高行高。

    row_styles 可为每行提供 {"bg": ..., "fg": ..., "fg_<列key>": ...} 以做风险高亮。
    max_cell_chars > 0 时，超长单元格先截断并在末尾标注原始字数，
    用于把记录表控制在一页高度内；完整原文仍保留在 Markdown / Excel / 数据库中。
    返回表格底部的 y。
    """
    total_w = sum(col.width for col in columns)
    # 表头
    c.rect(x, y, total_w, header_height, fill=COLORS["primary_soft"],
           outline=COLORS["primary_line"], radius=6)
    cx = x
    for col in columns:
        c.text_one(cx + row_pad, y + (header_height - col.size) / 2 - 1, col.title,
                   col.size, True, COLORS["primary_dark"],
                   align=col.align, max_width=col.width - row_pad * 2)
        cx += col.width
    top = y + header_height

    for i, row in enumerate(rows):
        style = (row_styles[i] if row_styles and i < len(row_styles) else None) or {}
        bg = style.get("bg", COLORS["row_alt"] if i % 2 else COLORS["bg"])
        fg = style.get("fg", COLORS["text"])
        # 计算行高
        heights = []
        wrapped: List[List[str]] = []
        for col, cell in zip(columns, row):
            text = "" if cell is None else str(cell)
            if max_cell_chars and len(text) > max_cell_chars:
                text = text[:max_cell_chars].rstrip() + f"\n…（原文 {len(str(cell))} 字，完整内容见报告与 Excel）"
            lines = c.wrap(text, col.size, col.width - row_pad * 2, col.bold)
            wrapped.append(lines)
            heights.append(len(lines) * col.size * 1.55 + row_pad * 2)
        h = row_height or min(max_row_height, max([min_row] + heights))

        # 裁掉超出画布的行，避免压到页脚/出图边界
        if top + h > c.h:
            break

        c.rect(x, top, total_w, h, fill=bg, outline=COLORS["line"], width=1)
        cx = x
        for col, lines in zip(columns, wrapped):
            color = style.get(f"fg_{col.key}", fg)
            ty = top + row_pad
            for line in lines:
                if ty + col.size > top + h - 2:
                    break
                c.text_one(cx + row_pad, ty, line, col.size, col.bold, color,
                           align=col.align, max_width=col.width - row_pad * 2)
                ty += col.size * 1.55
            cx += col.width
        top += h
    return top


def draw_bar_group(c: Canvas, x: float, y: float, w: float, h: float,
                   groups: Sequence[str], series: Sequence[Dict[str, Any]], *,
                   y_max: float = 1.0, y_ticks: int = 5, value_fmt: str = "{:.0%}",
                   legend: bool = True, bar_gap: float = 0.18) -> float:
    """分组柱状图。

    series: [{"name": str, "color": str, "values": [float, ...]}, ...]
    """
    plot_x, plot_y = x + 62, y + (26 if legend else 4)
    plot_w, plot_h = w - 62 - 16, h - (26 if legend else 4) - 40

    # 图例
    if legend:
        lx = x + 62
        for s in series:
            c.rect(lx, y + 6, 12, 12, fill=s["color"], radius=3)
            c.text_one(lx + 17, y + 3, str(s["name"]), 12, False, COLORS["text"])
            lx += 17 + c.fonts.measure(str(s["name"]), 12)[0] + 22

    # 网格与 Y 轴刻度
    for i in range(y_ticks + 1):
        val = y_max * i / y_ticks
        gy = plot_y + plot_h - plot_h * i / y_ticks
        c.line(plot_x, gy, plot_x + plot_w, gy,
               COLORS["line"] if i else COLORS["muted_soft"], 1)
        c.text_one(x, gy - 8, value_fmt.format(val), 11, False, COLORS["muted"],
                   align="right", max_width=52)

    n_groups = max(1, len(groups))
    n_series = max(1, len(series))
    group_w = plot_w / n_groups
    bar_w = group_w * (1 - bar_gap * 2) / n_series
    for gi, _g in enumerate(groups):
        gx = plot_x + gi * group_w
        for si, s in enumerate(series):
            val = float(s["values"][gi]) if gi < len(s["values"]) else 0.0
            bh = plot_h * min(1.0, max(0.0, val / y_max if y_max else 0))
            bx = gx + group_w * bar_gap + si * bar_w
            c.rect(bx, plot_y + plot_h - bh, bar_w - 3, bh, fill=s["color"], radius=3)
            label = value_fmt.format(val)
            lw = c.fonts.measure(label, 11.5, True)[0]
            c.text_one(bx + (bar_w - 3 - lw) / 2, plot_y + plot_h - bh - 18, label,
                       11.5, True, s["color"])
        c.text_one(gx, plot_y + plot_h + 8, groups[gi], 12, False, COLORS["text"],
                   align="center", max_width=group_w)
    c.line(plot_x, plot_y + plot_h, plot_x + plot_w, plot_y + plot_h, COLORS["muted_soft"], 1)
    return plot_y + plot_h + 30


def draw_similarity_matrix(c: Canvas, x: float, y: float, size: float,
                           labels: Sequence[str], matrix: Sequence[Sequence[float]],
                           title: str = "") -> float:
    """相似度矩阵热力图（对角线留空）。"""
    if title:
        c.text_one(x, y, title, 13, True, COLORS["text_strong"])
        y += 22
    n = len(labels)
    cell = size / (n + 1)
    # 列标题
    for j, lab in enumerate(labels):
        c.text_one(x + cell * (j + 1), y, lab, 12, False, COLORS["muted"],
                   align="center", max_width=cell)
    for i in range(n):
        c.text_one(x, y + cell * (i + 1), labels[i], 12, False, COLORS["muted"],
                   align="right", max_width=cell - 6)
        for j in range(n):
            cx = x + cell * (j + 1)
            cy = y + cell * (i + 1)
            if i == j:
                c.rect(cx, cy, cell - 3, cell - 3, fill=COLORS["bg_soft"],
                       outline=COLORS["line"])
                c.text_one(cx, cy + cell / 2 - 12, "—", 13, False, COLORS["muted_soft"],
                           align="center", max_width=cell - 3)
                continue
            v = float(matrix[i][j])
            # 相似度越高越红（越像越同质）
            color = _lerp_hex("#ECFDF5", COLORS["danger"], min(1.0, max(0.0, v)))
            c.rect(cx, cy, cell - 3, cell - 3, fill=color, radius=4)
            fg = "#FFFFFF" if v > 0.55 else COLORS["text_strong"]
            c.text_one(cx, cy + cell / 2 - 12, f"{v:.0%}", 13, True, fg,
                       align="center", max_width=cell - 3)
    return y + cell * (n + 1) + 6


def draw_gauge(c: Canvas, x: float, y: float, w: float, h: float, value: float, *,
               label: str, threshold: float, fmt: str = "{:.0%}") -> None:
    """单个指标卡：大数字 + 阈值线 + 达标标记。"""
    ok = value <= threshold
    c.rect(x, y, w, h, fill=COLORS["ok_soft"] if ok else COLORS["danger_soft"],
           outline=COLORS["ok"] if ok else COLORS["danger"], radius=10)
    c.text_one(x + 14, y + 10, label, 12, False, COLORS["muted"])
    c.text_one(x + 14, y + 28, fmt.format(value), 30, True,
               COLORS["ok"] if ok else COLORS["danger"])
    c.text_one(x + 14, y + h - 24, f"标准 ≤ {fmt.format(threshold)}　"
                                   f"{'达标' if ok else '未达标'}", 11.5, True,
               COLORS["ok"] if ok else COLORS["danger"])


def _lerp_hex(a: str, b: str, t: float) -> str:
    """两个十六进制颜色之间线性插值。"""
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    r = int(ar + (br - ar) * t)
    g = int(ag + (bg - ag) * t)
    bl = int(ab + (bb - ab) * t)
    return f"#{r:02X}{g:02X}{bl:02X}"
