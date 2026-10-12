"""六大功能模块的实现。

设计要点：
- 所有模块共用 `FeatureContext`，统一处理提示词组装、模式标记、模型路由、降级与落库；
- `quality_check` 对输出做**自动化质检**（结构覆盖率、质量约束落实、不确定标记、表格与代码），
  这是阶段二"评价维度"与阶段三"通过标准"的程序化落地；
- 多轮模块（M5 / M6）把会话状态保存在 session.meta 中，支持 Web 端连续对话。
"""

from .base import BaseFeature, FeatureContext, FeatureResult, OutputChecks, detect_table, quality_check
from .qa import ExerciseSolver, KnowledgeMapper
from .diagnose import MistakeAnalyzer, ConceptExplainer
from .plan import WeaknessPlanner, OralCoach, FEATURES, get_feature

__all__ = [
    "BaseFeature",
    "FeatureContext",
    "FeatureResult",
    "OutputChecks",
    "detect_table",
    "quality_check",
    "ExerciseSolver",
    "KnowledgeMapper",
    "MistakeAnalyzer",
    "ConceptExplainer",
    "WeaknessPlanner",
    "OralCoach",
    "FEATURES",
    "get_feature",
]
