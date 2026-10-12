"""量化指标：把对照实验的结果折算成阶段三汇报中的口径。

指标口径（与阶段三 PPT 一致）：
  · 事实幻觉出现率 = 出现事实幻觉的题目数 / 测试题数
  · 逻辑错误率     = 出现逻辑错误的题目数 / 测试题数
  · 不确定标记率   = 主动标注知识边界（超纲/争议/信息不足）的输出占比
  · 结构完整度     = 输出中结构标题与表格的完善程度（0–1）
  · 重复度         = 同一提示多次输出的平均两两相似度
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..utils import mean_pairwise_similarity, to_float
from .cases import RiskCase, judge


@dataclass
class DimensionScore:
    """阶段二汇报中"五个评价维度"的量化结果。"""

    structure: float = 0.0        # 结构完整性 0–1
    hallucination: int = 0        # 事实幻觉次数
    logic_error: int = 0          # 逻辑错误次数
    uncertainty: float = 0.0      # 不确定标记 0–1
    teaching: float = 0.0         # 教学价值 0–1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def total(self) -> float:
        penalty = 0.35 * self.hallucination + 0.35 * self.logic_error
        return round(max(0.0, 0.3 * self.structure + 0.2 * self.uncertainty
                         + 0.2 * self.teaching + 0.3 - penalty), 4)


@dataclass
class MetricSummary:
    """一组测试的汇总指标。"""

    label: str = ""
    model: str = ""
    #: 评测层标记：True = 使用精细提示（应用正式模板）；False = 无约束提示（消融对照）
    prompt_strict: bool = True
    cases: int = 0
    hallucination_cases: int = 0
    logic_cases: int = 0
    hallucination_hits: int = 0
    logic_hits: int = 0
    compliance_hits: int = 0
    avg_structure: float = 0.0
    avg_uncertainty: float = 0.0
    avg_teaching: float = 0.0
    avg_chars: int = 0
    repetition: Dict[str, float] = field(default_factory=dict)
    simulated: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def hallucination_rate(self) -> float:
        return round(self.hallucination_hits / self.hallucination_cases, 4) if self.hallucination_cases else 0.0

    @property
    def logic_error_rate(self) -> float:
        return round(self.logic_hits / self.logic_cases, 4) if self.logic_cases else 0.0

    @property
    def compliance_rate(self) -> float:
        total = self.hallucination_cases + self.logic_cases
        return round(self.compliance_hits / total, 4) if total else 0.0

    @property
    def repetition_overall(self) -> float:
        return to_float(self.repetition.get("overall"), 0.0)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update({
            "hallucination_rate": self.hallucination_rate,
            "logic_error_rate": self.logic_error_rate,
            "compliance_rate": self.compliance_rate,
            "repetition_overall": self.repetition_overall,
        })
        return data

    # ------------------------------------------------------------ 达标判定
    def verdict(self, criteria: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        criteria = criteria or {"hallucination_rate": 0.20, "logic_errors": 1, "repetition": 0.30}
        checks = {
            "幻觉率 ≤ 20%": self.hallucination_rate <= to_float(criteria.get("hallucination_rate"), 0.20),
            f"逻辑错误 ≤ {criteria.get('logic_errors', 1)} 处":
                self.logic_hits <= int(criteria.get("logic_errors", 1)),
            "重复度 ≤ 30%": self.repetition_overall <= to_float(criteria.get("repetition"), 0.30),
        }
        return {"checks": checks, "passed": all(checks.values())}


# ----------------------------------------------------------------------
# 单条输出评分
# ----------------------------------------------------------------------

def evaluate_output(answer: str, case: Optional[RiskCase] = None,
                    checks: Optional[Dict[str, Any]] = None) -> DimensionScore:
    """对一条输出打五维分。case 提供风险模式；checks 提供结构质检结果。"""
    score = DimensionScore()
    if checks:
        score.structure = to_float(checks.get("structure_score"), 0.0)
        score.uncertainty = to_float(checks.get("honesty_score"), 0.0)
        score.teaching = to_float(checks.get("teaching_score"), 0.0)
    if case:
        verdict = judge(case, answer or "")
        if case.type == "hallucination" and verdict["risk_hit"]:
            score.hallucination = 1
        if case.type == "logic" and verdict["risk_hit"]:
            score.logic_error = 1
        if not score.uncertainty:
            score.uncertainty = 1.0 if verdict["compliance"] else 0.0
    return score


# ----------------------------------------------------------------------
# 汇总
# ----------------------------------------------------------------------

def summarize(records: Sequence[Dict[str, Any]], label: str = "", model: str = "",
              mode: str = "", repetition: Optional[Dict[str, float]] = None,
              criteria: Optional[Dict[str, Any]] = None) -> MetricSummary:
    """records 每项形如：
    {"case": RiskCase|None, "answer": str, "checks": dict|None, "verdict": dict|None}
    """
    summary = MetricSummary(label=label, model=model,
                            prompt_strict=(str(mode).lower() != "plain"),
                            repetition=repetition or {})
    structures, uncertainties, teachings, chars = [], [], [], []
    for rec in records:
        case = rec.get("case")
        answer = rec.get("answer") or ""
        checks = rec.get("checks") or {}
        verdict = rec.get("verdict") or (judge(case, answer) if case else {})

        summary.cases += 1
        chars.append(len(answer))
        structures.append(to_float(checks.get("structure_score"), 0.0))
        uncertainties.append(to_float(checks.get("honesty_score"), 1.0 if verdict.get("compliance") else 0.0))
        teachings.append(to_float(checks.get("teaching_score"), 0.0))
        if verdict.get("compliance"):
            summary.compliance_hits += 1
        if case and case.type == "hallucination":
            summary.hallucination_cases += 1
            if verdict.get("risk_hit"):
                summary.hallucination_hits += 1
        if case and case.type == "logic":
            summary.logic_cases += 1
            if verdict.get("risk_hit"):
                summary.logic_hits += 1
        if rec.get("simulated"):
            summary.simulated = True

    n = max(1, len(records))
    summary.avg_structure = round(sum(structures) / n, 4)
    summary.avg_uncertainty = round(sum(uncertainties) / n, 4)
    summary.avg_teaching = round(sum(teachings) / n, 4)
    summary.avg_chars = int(sum(chars) / n)
    summary.extra["verdict"] = summary.verdict(criteria)
    return summary


def aggregate(summaries: Iterable[MetricSummary], label: str = "") -> Dict[str, Any]:
    """把多个对照组汇总成一张对比表（Markdown 友好）。"""
    rows = []
    for s in summaries:
        rows.append({
            "label": s.label or s.model,
            "model": s.model,
            "提示词": "精细提示" if s.prompt_strict else "无约束（消融）",
            "cases": s.cases,
            "幻觉率": f"{s.hallucination_rate:.0%}",
            "逻辑错误率": f"{s.logic_error_rate:.0%}",
            "合规率": f"{s.compliance_rate:.0%}",
            "结构完整度": f"{s.avg_structure:.2f}",
            "不确定标记": f"{s.avg_uncertainty:.2f}",
            "教学价值": f"{s.avg_teaching:.2f}",
            "重复度": f"{s.repetition_overall:.0%}" if s.repetition else "—",
            "平均字数": s.avg_chars,
            "是否离线模拟": "是" if s.simulated else "否",
        })
    return {"title": label, "rows": rows}


def repetition_metrics(texts: Sequence[str]) -> Dict[str, float]:
    return mean_pairwise_similarity(list(texts))
