"""M3 错题归纳、M4 概念通俗讲解。"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .base import BaseFeature, FeatureContext, FeatureResult

#: 错因五分类（阶段二模块 M3 的关键设计）
ERROR_TYPES: List[Dict[str, str]] = [
    {"type": "概念错误", "signal": "对定义、定理的适用条件理解有误"},
    {"type": "计算错误", "signal": "推导过程/代数/符号运算出错"},
    {"type": "审题错误", "signal": "误读题目条件、漏看限制、所求抓错"},
    {"type": "方法错误", "signal": "方法选择不当或步骤顺序不合理"},
    {"type": "知识盲区", "signal": "该知识点完全没学过或完全遗忘"},
]


class MistakeAnalyzer(BaseFeature):
    """M3 · 错题归纳 —— 对应痛点「错题难归」。

    关键设计（阶段二）：七步诊断 + 错误类型五分类 + 信息不足时主动追问。
    """

    module_id = "M3"

    def run(self, question: str, ctx: FeatureContext, student_answer: str = "",
            save: bool = True, images: Any = None) -> FeatureResult:
        extra_lines = []
        if not student_answer:
            extra_lines.append(
                "【信息不足提示】学生未提供自己的解答过程。请先在【主动追问】段落中要求其提供："
                "题目原文、完整解答步骤、卡住的位置，然后再做诊断；不得凭空推测错因。"
            )
        else:
            extra_lines.append("【学生解答】" + student_answer.strip()[:2000])
        extra_lines.append("【错误类型字典】" + "；".join(f"{e['type']}（{e['signal']}）" for e in ERROR_TYPES))
        extra_lines.append("【错误类型五分类】请从上述五类中选择最贴切的一类，并说明判定理由。")

        result = self.ask(question, ctx, extra="\n".join(extra_lines), save=save, images=images)
        structured = result.structured or {}
        result.meta["error_type"] = structured.get("错误类型") or self._guess_type(result.answer)
        result.meta["location"] = structured.get("错误定位", "")
        result.meta["related"] = structured.get("关联知识点", [])
        result.meta["need_info"] = structured.get("需补充信息", [])
        result.meta["error_taxonomy"] = [e["type"] for e in ERROR_TYPES]
        return result

    @staticmethod
    def _guess_type(text: str) -> str:
        for item in ERROR_TYPES:
            if item["type"] in text:
                return item["type"]
        for item in ERROR_TYPES:
            if item["type"].replace("错误", "") in text:
                return item["type"]
        return "待判定"


class ConceptExplainer(BaseFeature):
    """M4 · 概念通俗讲解 —— 对应痛点「概念难明」。

    关键设计（阶段二）：九段式讲解 + 禁用俗套类比 + 强制代码逐行注释与执行过程表。
    """

    module_id = "M4"

    #: 被明令禁止的俗套类比（阶段二 M4 设计要求）
    BANNED_ANALOGIES = ["俄罗斯套娃", "套娃", "剥洋葱", "洋葱"]

    def run(self, question: str, ctx: FeatureContext, level: str = "零基础",
            save: bool = True, images: Any = None) -> FeatureResult:
        extra_lines = [
            f"【难度档位】面向{level}读者；若同学已具备基础，可提高术语密度。",
            "【类比禁令】禁止使用：" + "、".join(self.BANNED_ANALOGIES) + "。若你想到的类比落入该清单，必须换一个。",
        ]
        result = self.ask(question, ctx, extra="\n".join(extra_lines), save=save, images=images)
        banned_hit = [b for b in self.BANNED_ANALOGIES if b in result.answer]
        result.meta["banned_analogy_hit"] = banned_hit
        result.meta["level"] = level
        if banned_hit:
            result.notes.append(f"⚠ 输出中仍出现被禁用的俗套类比：{'、'.join(banned_hit)}（提示词违反）")
        result.meta["concept"] = (result.structured or {}).get("概念") or self._guess_concept(question)
        return result

    @staticmethod
    def _guess_concept(question: str) -> str:
        m = re.search(r"(?:什么是|解释一下|讲一下|讲讲|介绍一下)\s*([\u4e00-\u9fffA-Za-z0-9\+#\.]{2,20})", question)
        if m:
            return m.group(1).strip("是什么？?。，,")
        return question.strip()[:20]
