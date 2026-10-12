"""评测框架：模块划分与评价维度（阶段二 + 阶段三）。

阶段二评价维度：结构完整性、事实幻觉、逻辑错误、不确定标记、教学价值。
阶段三通过标准：精细提示下 幻觉率 ≤20%、逻辑错误 ≤1 处、重复度 ≤30%。
"""

from .cases import (
    ANTI_REPETITION_PROMPTS,
    ANTI_REPETITION_SUFFIX,
    COMPARISON_CASES,
    COMPARISON_DIMENSIONS,
    HALLUCINATION_CASES,
    LOGIC_CASES,
    REPETITION_CASE,
    REPETITION_PROMPTS,
    RiskCase,
    all_cases,
    detect_flags,
    detect_markers,
    get_case,
    judge,
)
from .metrics import (
    DimensionScore,
    MetricSummary,
    aggregate,
    evaluate_output,
    summarize,
)
from .runner import RiskReport, RiskRunner

__all__ = [
    "RiskCase",
    "HALLUCINATION_CASES",
    "LOGIC_CASES",
    "REPETITION_CASE",
    "COMPARISON_CASES",
    "COMPARISON_DIMENSIONS",
    "ANTI_REPETITION_SUFFIX",
    "ANTI_REPETITION_PROMPTS",
    "REPETITION_PROMPTS",
    "all_cases",
    "get_case",
    "judge",
    "detect_flags",
    "detect_markers",
    "MetricSummary",
    "DimensionScore",
    "summarize",
    "aggregate",
    "evaluate_output",
    "RiskRunner",
    "RiskReport",
]
