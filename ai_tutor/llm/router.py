"""任务路由（对应第三阶段"改进建议 4：工具路由"）。

路由依据来自阶段三 10 道测试题的横向对比结论：
  · Claude 3.5 Sonnet —— 事实最保守，幻觉率最低（约 10%）→ 事实核查类任务首选
  · GPT-4o          —— 结构完整性最好（三部分齐全）  → 结构化提纲 / 习题解析首选
  · 文心一言 4.0     —— 中文表达最自然               → 中文口语化讲解首选

路由还会为每类任务给出推荐的 temperature 与质量红线，把"提示词优化方案"落成代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .registry import LLMClient


@dataclass
class Route:
    task: str
    label: str
    preferred: List[str] = field(default_factory=list)
    temperature: float = 0.3
    reason: str = ""
    redlines: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "label": self.label,
            "preferred": self.preferred,
            "temperature": self.temperature,
            "reason": self.reason,
            "redlines": self.redlines,
        }


ROUTING_TABLE: Dict[str, Route] = {
    "fact_check": Route(
        task="fact_check",
        label="事实核查 / 文献·数据·政策条文",
        preferred=["anthropic", "openai", "deepseek", "mock"],
        temperature=0.1,
        reason="Claude 事实最保守（幻觉率约 10%），低温可进一步降低编造倾向",
        redlines=[
            "不确定时明确声明，禁止编造文献 / 数据 / 出处",
            "涉及具体页码、DOI、政策条文时必须标注「待核实」",
            "无来源数据拒绝给出精确数字",
        ],
    ),
    "structured": Route(
        task="structured",
        label="结构化提纲 / 知识框架 / 习题解析",
        preferred=["openai", "deepseek", "anthropic", "mock"],
        temperature=0.3,
        reason="GPT-4o 结构完整性最优（三部分齐全、模块化稳定）",
        redlines=["固定分段标题", "禁止跳步", "必须交叉验证"],
    ),
    "logic": Route(
        task="logic",
        label="逻辑推导 / 因果与条件判断",
        preferred=["openai", "anthropic", "deepseek", "mock"],
        temperature=0.2,
        reason="逻辑类任务需要「先举反例 → 再分情况 → 最后给结论」，低温度减少直觉式回答",
        redlines=["先举反例再下结论", "写出推导过程", "分别证明充分性与必要性"],
    ),
    "chinese_explain": Route(
        task="chinese_explain",
        label="中文口语化讲解 / 通俗类比",
        preferred=["qianfan", "openai", "deepseek", "mock"],
        temperature=0.6,
        reason="文心一言中文表达最自然；同时提高温度以缓解同质化",
        redlines=["禁止使用「俄罗斯套娃」等俗套类比", "必须给出生活类比 + 技术定义"],
    ),
    "anti_repetition": Route(
        task="anti_repetition",
        label="反同质化生成（提纲 / 计划 / 长文本）",
        preferred=["openai", "anthropic", "deepseek", "mock"],
        temperature=0.9,
        reason="同一提示三次输出相似度高达 85%–90%，需高温度 + 强制多组织方式",
        redlines=["请给出 2 种不同组织方式", "变换叙述风格", "避免固定开头模板"],
    ),
    "general": Route(
        task="general",
        label="通用问答",
        preferred=[],
        temperature=0.3,
        reason="使用配置中的默认模型",
        redlines=[],
    ),
}


class TaskRouter:
    """根据任务类型选择模型，并给出推荐采样参数。"""

    #: 关键词 → 任务类型（用于自动识别）
    KEYWORDS = {
        "fact_check": ["文献", "doi", "sci", "出处", "页码", "政策", "文件", "规定",
                       "数据来源", "统计年鉴", "是否存在", "第几版", "例题"],
        "logic": ["是否一定", "能否推出", "充要", "充分必要", "必要条件", "反例",
                  "为什么", "推导", "证明", "属于什么条件"],
        "structured": ["提纲", "知识框架", "知识体系", "思维导图", "解析", "解题",
                       "步骤", "归纳", "整理"],
        "chinese_explain": ["通俗", "解释一下", "什么是", "是什么", "类比", "口语"],
        "anti_repetition": ["多种", "不同组织方式", "变换", "两个版本", "重复度"],
    }

    #: 高精度信号：一旦出现就优先判为对应任务，避免被"知识框架/整理"等泛词抢走。
    #: 依据阶段三结论：文献、DOI、页码、政策条文类问题必须走"事实核查"路由。
    PRIORITY_SIGNALS = {
        "fact_check": ["doi", "sci", "文献", "出处", "页码", "第几页", "政策", "条文",
                       "教育部", "规定是多少", "数据来源", "统计年鉴", "是否真实"],
        "logic": ["是否一定", "能否推出", "充要", "充分必要", "反例", "属于什么条件",
                  "是否意味着"],
    }

    def __init__(self, client: LLMClient, table: Optional[Dict[str, Route]] = None) -> None:
        self.client = client
        self.table = table or ROUTING_TABLE

    # -------------------------------------------------------------- 识别
    @classmethod
    def detect_task(cls, text: str, module: Optional[str] = None) -> str:
        # 说明：模块只作为**弱先验**。文本里若出现文献 / DOI / 页码 / 政策等
        # 高精度"事实核查"信号，即使问题出现在某个内容模块里，也必须改走事实核查路由，
        # 否则模型会被"知识框架"这类格式指令带着去编造文献出处。
        low = (text or "").lower()
        for task, signals in cls.PRIORITY_SIGNALS.items():
            if any(sig.lower() in low for sig in signals):
                return task

        if module in ("M3",):
            return "logic"
        if module in ("M1", "M2"):
            return "structured"
        if module == "M4":
            return "chinese_explain"
        if module == "M5":
            return "anti_repetition"
        if module == "M6":
            return "chinese_explain"

        best, best_hits = "general", 0
        for task, words in cls.KEYWORDS.items():
            hits = sum(1 for w in words if w.lower() in low)
            if hits > best_hits:
                best, best_hits = task, hits
        return best

    # -------------------------------------------------------------- 路由
    def route(self, text: str = "", module: Optional[str] = None,
              task: Optional[str] = None) -> Dict[str, Any]:
        task = task or self.detect_task(text, module)
        route = self.table.get(task) or self.table["general"]
        available = set(self.client.available_names())
        chosen: Optional[str] = None
        for name in route.preferred:
            if name in available:
                chosen = name
                break
        if chosen is None:
            chosen = self.client.default if self.client.default in self.client.providers else "mock"
        fallback = chosen not in available
        return {
            "task": route.task,
            "label": route.label,
            "model": chosen,
            "temperature": route.temperature,
            "reason": route.reason,
            "redlines": route.redlines,
            "fallback_to_default": fallback,
            "available": sorted(available),
        }

    def table_snapshot(self) -> List[Dict[str, Any]]:
        available = set(self.client.available_names())
        out = []
        for route in self.table.values():
            item = route.to_dict()
            hit = next((n for n in route.preferred if n in available), self.client.default)
            item["resolved_model"] = hit
            item["unavailable"] = [n for n in route.preferred if n not in available]
            out.append(item)
        return out
