"""M1 习题解析、M2 知识框架生成。"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import BaseFeature, FeatureContext, FeatureResult


class ExerciseSolver(BaseFeature):
    """M1 · 习题解析 —— 对应痛点「解析难懂」。

    在通用流程之外增加：
      · 题目完整性预检查（缺条件时先追问，而不是硬解）
      · 从结构化结果中提取"答案"，便于前端快速展示与错题本归档
    """

    module_id = "M1"

    INCOMPLETE_HINTS = ("这题怎么做", "怎么做", "求解", "帮我看下", "解释下这道题")

    def preflight(self, question: str) -> List[str]:
        """检测题干信息是否严重不足，返回需要追问的问题列表。"""
        problems: List[str] = []
        stripped = (question or "").strip()
        if len(stripped) < 8:
            problems.append("题干过短，请补充完整题目（条件、所求、取值范围）。")
        if stripped in self.INCOMPLETE_HINTS:
            problems.append("未提供具体题目内容，请粘贴题目原文。")
        if self._looks_like_student_work(stripped) and "我的解答" not in stripped:
            problems.append("题目中似乎包含你的解题过程；如需错因诊断，请转到「错题归纳」模块（M3）效果更好。")
        return problems

    @staticmethod
    def _looks_like_student_work(text: str) -> bool:
        return any(k in text for k in ("我算的是", "我写成", "我的答案", "我这样做", "我不知道哪错了"))

    def run(self, question: str, ctx: FeatureContext, save: bool = True, images: Any = None) -> FeatureResult:
        preflight = self.preflight(question)
        extra = ""
        if preflight:
            extra = "【信息不足提示】检测到以下问题，若确实影响求解，请在【不确定标注】中先追问：" + "；".join(preflight)
        result = self.ask(question, ctx, extra=extra, save=save, images=images)
        result.meta["preflight"] = preflight
        structured = result.structured or {}
        answer = str(structured.get("答案", "")).strip()
        result.meta["answer"] = answer if answer and answer != "见正文推导" else self._extract_answer(result.answer)
        result.meta["error_prone"] = structured.get("易错点", [])
        result.meta["extended"] = structured.get("拓展题", [])
        return result

    @staticmethod
    def _extract_answer(text: str) -> str:
        """从正文里兜底抽取答案（优先取"结论/答案"后的内容）。"""
        import re
        for pattern in (r"答案[为是：:]\s*([^\n。；]{1,40})", r"结论[：:]\s*([^\n。；]{1,60})",
                        r"=\s*(-?\d+(?:/\d+)?)\s*$"):
            m = re.search(pattern, text, re.M)
            if m:
                return m.group(1).strip()
        return ""


class KnowledgeMapper(BaseFeature):
    """M2 · 知识框架生成 —— 对应痛点「框架难理」。

    在通用流程之外增加：
      · 主题识别与受众注入
      · 提纲导出（Markdown），可直接保存为学生复习提纲
    """

    module_id = "M2"

    def run(self, question: str, ctx: FeatureContext, subject: str = "自动识别",
            audience: str = "", save: bool = True, images: Any = None) -> FeatureResult:
        extra_lines = []
        if subject and subject != "自动识别":
            extra_lines.append(f"【主题约束】本次知识框架的主题限定为：{subject}，不要扩展到其他主题。")
        if audience:
            extra_lines.append(f"【受众覆盖】{audience}")
        result = self.ask(question, ctx, extra="\n".join(extra_lines), save=save, images=images)
        structured = result.structured or {}
        result.meta["topic"] = structured.get("主题") or subject
        result.meta["layers"] = structured.get("层级", [])
        result.meta["star_map"] = structured.get("考点星级", {})
        result.meta["outline_markdown"] = self.to_outline_markdown(result)
        return result

    @staticmethod
    def to_outline_markdown(result: FeatureResult) -> str:
        topic = result.meta.get("topic") or "知识框架"
        return (f"# {topic} · 复习提纲\n\n"
                f"> 由「知识框架生成 M2」使用 {result.meta.get('model', '')} 生成，"
                f"提示模板：精细提示（含考点星级与超纲标注）\n\n"
                f"{result.answer}\n")
