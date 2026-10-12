"""通用工具：ID 生成、时间、文本处理、重复度计算。

重复度算法按阶段三报告的口径实现（同一提示重复 3 次，比较输出相似度）：
  · ngram_jaccard —— 字符 2-gram Jaccard 相似度（主指标，对同义改写敏感）
  · lcs_ratio     —— 最长公共子序列占比（次序保持度）
  · structure_sim —— 结构（段落标题）相似度
  · overall       —— 加权综合重复度，用于与 85%–90% 的实测结论对齐
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Sequence, Tuple

# ----------------------------------------------------------------------
# 基础
# ----------------------------------------------------------------------

def new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex[:12]
    return f"{prefix}{token}" if prefix else token


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def pick(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------
# 文本
# ----------------------------------------------------------------------

_WS = re.compile(r"[ \t\u3000]+")
_MULTI_NL = re.compile(r"\n{3,}")
_HEADER = re.compile(r"^[\s>#\-•·]*[【\[]?([\u4e00-\u9fffA-Za-z][^】\]\n:：]{1,18})[】\]]?\s*[:：]?\s*$")


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


def strip_markup(text: str) -> str:
    """去掉表格框线、项目符号与标题括号，只留语义内容，用于相似度计算。"""
    if not text:
        return ""
    lines = []
    for line in normalize_text(text).splitlines():
        line = re.sub(r"[│┌┐└┘├┤┬┴┼─═╔╗╚╝║╠╣]+", " ", line)
        line = re.sub(r"^[\s\-•·*+>]+", "", line)
        line = re.sub(r"[【】\[\]]", "", line)
        lines.append(line.strip())
    return "\n".join(l for l in lines if l)


def char_ngrams(text: str, n: int = 2) -> List[str]:
    clean = re.sub(r"\s+", "", strip_markup(text))
    if len(clean) < n:
        return [clean] if clean else []
    return [clean[i:i + n] for i in range(len(clean) - n + 1)]


def ngram_jaccard(a: str, b: str, n: int = 2) -> float:
    sa, sb = set(char_ngrams(a, n)), set(char_ngrams(b, n))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def lcs_ratio(a: str, b: str) -> float:
    """最长公共子序列占比（基于字符，长度裁剪以保证性能）。"""
    x = re.sub(r"\s+", "", strip_markup(a))[:1500]
    y = re.sub(r"\s+", "", strip_markup(b))[:1500]
    if not x or not y:
        return 0.0
    if len(x) > len(y):
        x, y = y, x
    prev = [0] * (len(x) + 1)
    for ch in y:
        cur = [0]
        for i, cx in enumerate(x):
            if cx == ch:
                cur.append(prev[i] + 1)
            else:
                cur.append(max(prev[i + 1], cur[i]))
        prev = cur
    return prev[-1] / len(x)


def extract_headers(text: str) -> List[str]:
    """抽取结构标题：支持【标题】、一、二、三、1. / ① 等常见形式。"""
    headers: List[str] = []
    for raw in normalize_text(text).splitlines():
        line = raw.strip()
        if not line or len(line) > 40:
            continue
        m = re.match(r"^【([^】]{2,20})】", line)
        if m:
            headers.append(m.group(1))
            continue
        m = re.match(r"^([一二三四五六七八九十]+)\s*[、.．)]\s*(.{2,18})$", line)
        if m:
            headers.append(m.group(2).strip())
            continue
        m = re.match(r"^([①-⑳])\s*(.{2,18})$", line)
        if m:
            headers.append(m.group(2).strip())
            continue
        m = re.match(r"^(\d{1,2})\s*[.、．)]\s*(.{2,18})$", line)
        if m:
            headers.append(m.group(2).strip())
    return headers


def structure_sim(a: str, b: str) -> float:
    ha, hb = extract_headers(a), extract_headers(b)
    if not ha or not hb:
        return 0.0
    sa, sb = set(ha), set(hb)
    return len(sa & sb) / len(sa | sb)


def similarity_report(a: str, b: str) -> Dict[str, float]:
    """两个输出的重复度综合报告。"""
    ng = ngram_jaccard(a, b, 2)
    lcs = lcs_ratio(a, b)
    st = structure_sim(a, b)
    overall = round(0.5 * ng + 0.3 * lcs + 0.2 * st, 4) if st else round(0.6 * ng + 0.4 * lcs, 4)
    return {
        "ngram_jaccard": round(ng, 4),
        "lcs_ratio": round(lcs, 4),
        "structure_sim": round(st, 4),
        "overall": overall,
    }


def mean_pairwise_similarity(texts: Sequence[str]) -> Dict[str, float]:
    """多次输出的平均两两相似度（同质化测试主指标）。"""
    pairs: List[Tuple[str, str]] = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            pairs.append((texts[i], texts[j]))
    if not pairs:
        return {"ngram_jaccard": 0.0, "lcs_ratio": 0.0, "structure_sim": 0.0, "overall": 0.0, "pairs": 0}
    acc = {"ngram_jaccard": 0.0, "lcs_ratio": 0.0, "structure_sim": 0.0, "overall": 0.0}
    for a, b in pairs:
        rep = similarity_report(a, b)
        for k in acc:
            acc[k] += rep[k]
    n = len(pairs)
    out = {k: round(v / n, 4) for k, v in acc.items()}
    out["pairs"] = n
    return out


# ----------------------------------------------------------------------
# 显示
# ----------------------------------------------------------------------

def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def ellipsize(text: str, width: int = 60) -> str:
    text = (text or "").replace("\n", " ")
    out, acc = [], 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if acc + w > width:
            return "".join(out) + "…"
        out.append(ch)
        acc += w
    return "".join(out)


def wrap_cjk(text: str, width: int = 100) -> str:
    """按显示宽度折行（对中文友好），用于 CLI 输出。"""
    lines: List[str] = []
    for para in (text or "").splitlines():
        if not para.strip():
            lines.append("")
            continue
        cur, acc = [], 0
        for ch in para:
            w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
            if acc + w > width:
                lines.append("".join(cur))
                cur, acc = [], 0
            cur.append(ch)
            acc += w
        lines.append("".join(cur))
    return "\n".join(lines)


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]], width: int = 24) -> str:
    """生成等宽文本表格（CLI 报告用）。"""
    rows = [[ellipsize(str(c), width) for c in row] for row in rows]
    cols = len(headers)
    widths = [display_width(str(headers[i])) for i in range(cols)]
    for row in rows:
        for i in range(cols):
            widths[i] = max(widths[i], display_width(row[i]))
    def line(cells: Sequence[str]) -> str:
        return "  ".join(c + " " * (widths[i] - display_width(c)) for i, c in enumerate(cells))
    out = [line(list(headers)), "  ".join("─" * w for w in widths)]
    out.extend(line(row) for row in rows)
    return "\n".join(out)
