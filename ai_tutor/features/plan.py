"""M5 薄弱检测与复习计划、M6 口语背诵陪练（多轮闭环模块）。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .base import BaseFeature, FeatureContext, FeatureResult
from .diagnose import ConceptExplainer, MistakeAnalyzer
from .qa import ExerciseSolver, KnowledgeMapper


class WeaknessPlanner(BaseFeature):
    """M5 · 薄弱检测与复习计划 —— 对应痛点「弱点难辨」。

    关键设计（阶段二）：**两阶段闭环 —— 先诊断提问，再生成个性化计划**。
    程序层面把"禁止跳过诊断"变成了状态机：
      · stage=diagnose（默认）：只出诊断题，并明确声明未诊断不下发时间分配；
      · stage=plan：接收学生作答后，才生成按天计划（薄弱点占比 ≥40%）。
    """

    module_id = "M5"

    def run(self, question: str, ctx: FeatureContext, subject: str = "",
            days: int = 5, answers: str = "", stage: str = "auto",
            save: bool = True, images: Any = None) -> FeatureResult:
        session_id = ctx.ensure_session(title="M5 · 薄弱检测与复习计划", module="M5")
        state = ctx.session_meta().get("M5", {})
        has_prior_diagnosis = bool(state.get("asked_diagnosis"))

        if stage == "auto":
            stage = "plan" if (has_prior_diagnosis and answers.strip()) else "diagnose"
        if stage == "plan" and not (has_prior_diagnosis and answers.strip()):
            stage = "diagnose"

        subject = subject or state.get("subject") or self._guess_subject(question)

        if stage == "diagnose":
            extra = (
                "【本阶段任务】只输出第一阶段：诊断题。\n"
                "【硬性约束】本轮禁止给出任何具体的天数分配或时间占比；必须明确写出"
                "“未完成诊断前不下发最终计划”。"
            )
            result = self.ask(question, ctx, extra=extra, save=save, images=images)
            ctx.update_session_meta({"M5": {"stage": "diagnosed", "asked_diagnosis": True,
                                            "subject": subject, "days": days}})
            result.meta["stage"] = "diagnose"
            result.meta["subject"] = subject
            result.meta["next_action"] = "请学生提交 5 道诊断题的作答，随后自动生成个性化计划"
            return result

        extra = (
            "【本阶段任务】输出第二阶段：基于诊断结果的个性化复习计划。\n"
            f"【学生作答】\n{answers.strip()[:3000]}\n"
            f"【计划约束】科目：{subject}；剩余天数：{days} 天；薄弱点时间占比 ≥ 40% 且需写明比例；"
            "必须含 1 次限时模拟自测与每日达标标志；按“第 N 天｜内容 / 练习 / 自测 / 达标标志”排布。"
        )
        result = self.ask(question, ctx, extra=extra, save=save, images=images)
        plan_text = result.answer
        result.meta["stage"] = "plan"
        result.meta["subject"] = subject
        result.meta["days"] = days
        result.meta["weakness_ratio"] = self._extract_ratio(plan_text)
        result.meta["plan_markdown"] = self._to_markdown(subject, days, plan_text, answers)
        ctx.update_session_meta({"M5": {"stage": "planned", "asked_diagnosis": True,
                                        "subject": subject, "days": days}})
        if result.meta["weakness_ratio"] is None:
            result.notes.append("⚠ 未能从输出中识别薄弱点时间占比，请人工核对是否满足 ≥40% 的要求。")
        elif result.meta["weakness_ratio"] < 40:
            result.notes.append(f"⚠ 薄弱点时间占比仅 {result.meta['weakness_ratio']}%，低于 40% 的设计红线。")
        return result

    @staticmethod
    def _extract_ratio(text: str) -> Optional[int]:
        m = re.search(r"占比[^\d]{0,8}(\d{1,3})\s*%", text) or re.search(r"(\d{1,3})\s*%[^\n]{0,12}薄弱", text)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d{1,3})\s*%", text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _guess_subject(question: str) -> str:
        for name in ("高等数学", "线性代数", "计算机网络", "电路分析", "分析化学",
                     "操作系统", "数据结构", "大学物理", "英语"):
            if name in question:
                return name
        return "未指定科目"

    @staticmethod
    def _to_markdown(subject: str, days: int, plan: str, answers: str) -> str:
        return (f"# {subject} · 个性化复习计划（{days} 天）\n\n"
                f"## 学生诊断作答\n\n```text\n{answers.strip()[:2000]}\n```\n\n"
                f"## 计划正文\n\n{plan}\n")


class OralCoach(BaseFeature):
    """M6 · 口语背诵陪练 —— 对应痛点「练习难伴」。

    关键设计（阶段二）：**逐轮闭环 —— 每轮只问一个问题，四维评分，自适应调难度，5 轮后总结**。
    程序层面维护轮次状态，并在每一轮显式产出上一轮的四维评分表。
    """

    module_id = "M6"
    MAX_ROUNDS = 5

    def run(self, question: str, ctx: FeatureContext, student_reply: str = "",
            scenario: str = "", round_index: int = 0, save: bool = True, images: Any = None) -> FeatureResult:
        session_id = ctx.ensure_session(title="M6 · 口语背诵陪练", module="M6")
        state = ctx.session_meta().get("M6", {})
        rounds: List[Dict[str, Any]] = state.get("rounds", []) or []
        scenario = scenario or state.get("scenario") or self._guess_scenario(question)

        if student_reply.strip():
            score = self._score_reply(student_reply, scenario)
            rounds.append({"round": len(rounds) + 1, "reply": student_reply.strip()[:1200], **score})
        current_round = round_index or (len(rounds) + 1)

        finished = len(rounds) >= self.MAX_ROUNDS

        if finished:
            summary = self._summary(rounds)
            extra = ("【总结轮】已完成 5 轮练习。请只输出总结：总分（各维度均分）、进步点 3 条、"
                     "改进点 3 条，并给出课外练习建议。不要再出新的题目。\n"
                     "【历史成绩】" + json.dumps(rounds, ensure_ascii=False))
            result = self.ask(question, ctx, extra=extra, save=save, images=images)
            result.meta["report"] = summary
            result.meta["stage"] = "summary"
            result.meta["score_table"] = self._score_table(rounds)
            result.meta["summary_markdown"] = self._to_markdown(scenario, rounds, result.answer)
            ctx.update_session_meta({"M6": {"scenario": scenario, "rounds": rounds, "stage": "finished"}})
            return result

        extra = (
            f"【练习场景】{scenario}\n"
            f"【当前轮次】第 {current_round} 轮 / 共 {self.MAX_ROUNDS} 轮\n"
            "【硬性约束】本轮只问一个问题；若学生已作答，先在开头给出上一轮的四维评分"
            "（准确性 / 流畅度 / 完整度 / 逻辑性，各 25 分，并给一句改进建议），再提出本轮问题。\n"
        )
        if student_reply.strip():
            extra += ("【学生本轮作答】\n" + student_reply.strip()[:1500] +
                      "\n【自动预评分参考】" + json.dumps(self._score_reply(student_reply, scenario),
                                                          ensure_ascii=False) +
                      "\n注意：该预评分为规则化近似，请结合语义给出最终评分并说明理由。")
        else:
            extra += "【说明】学生尚未作答，本轮请先给出题面与评分维度说明。"

        result = self.ask(question, ctx, extra=extra, save=save, images=images)
        result.meta["stage"] = "practice"
        result.meta["round"] = current_round
        result.meta["rounds_done"] = len(rounds)
        result.meta["scenario"] = scenario
        result.meta["score_table"] = self._score_table(rounds)
        for item in rounds:
            result.meta.setdefault("round_reports", []).append(
                {"round": item["round"], "reply": item["reply"], **{k: item[k] for k in
                 ("准确性", "流畅度", "完整度", "逻辑性", "总分") if k in item}})
        ctx.update_session_meta({"M6": {"scenario": scenario, "rounds": rounds, "stage": "practice"}})
        return result

    # ------------------------------------------------------------ 规则化评分
    @staticmethod
    def _score_reply(reply: str, scenario: str) -> Dict[str, Any]:
        """四维规则化预评分（准确性/流畅度/完整度/逻辑性，各 25 分）。

        说明：这是**可复现的近似评分**，用于给学生即时反馈与趋势判断；
        最终分数仍以模型给出的语义评分为准（提示词中已要求模型说明理由）。
        """
        text = (reply or "").strip()
        if not text:
            return {"准确性": 0, "流畅度": 0, "完整度": 0, "逻辑性": 0, "总分": 0, "说明": "未作答"}

        # 准确性：术语覆盖
        terms = ["三次握手", "序列号", "ISN", "SYN", "ACK", "全双工", "确认",
                 "terminate", "handshake", "三次", "两次"]
        hit = sum(1 for t in terms if t.lower() in text.lower())
        accuracy = min(25, 8 + hit * 4)

        # 完整度：长度 + 要点数
        completeness = min(25, 6 + min(len(text), 400) // 20 + hit)

        # 流畅度：填充词与重复标点
        fillers = len(re.findall(r"(嗯|呃|那个|然后然后|就是就是)", text))
        awkward = len(re.findall(r"[，。！？]{2,}", text))
        fluency = max(5, 25 - fillers * 3 - awkward * 4)

        # 逻辑性：连接词与因果链
        links = len(re.findall(r"(因为|所以|因此|如果|否则|从而|导致|意味着)", text))
        logic = min(25, 8 + links * 4 + (4 if len(text) > 120 else 0))

        total = accuracy + fluency + completeness + logic
        return {"准确性": accuracy, "流畅度": fluency, "完整度": completeness,
                "逻辑性": logic, "总分": total,
                "说明": "规则化近似评分（术语命中/长度/填充词/连接词），仅供参考"}

    @staticmethod
    def _score_table(rounds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{"轮次": r["round"], "准确性": r.get("准确性", 0), "流畅度": r.get("流畅度", 0),
                 "完整度": r.get("完整度", 0), "逻辑性": r.get("逻辑性", 0), "总分": r.get("总分", 0)}
                for r in rounds]

    @staticmethod
    def _summary(rounds: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not rounds:
            return {}
        dims = ["准确性", "流畅度", "完整度", "逻辑性"]
        avg = {d: round(sum(r.get(d, 0) for r in rounds) / len(rounds), 1) for d in dims}
        avg["总分"] = round(sum(r.get("总分", 0) for r in rounds) / len(rounds), 1)
        best, worst = max(dims, key=lambda d: avg[d]), min(dims, key=lambda d: avg[d])
        return {"均分": avg, "最强维度": best, "最弱维度": worst, "轮次": len(rounds)}

    @staticmethod
    def _guess_scenario(question: str) -> str:
        if any(k in question for k in ("英语", "口语", "雅思", "托福")):
            return "英语口语练习（日常表达与发音）"
        if "TCP" in question or "网络" in question:
            return "计算机网络 · TCP 三次握手背诵检测"
        return "背诵与表达训练"

    @staticmethod
    def _to_markdown(scenario: str, rounds: List[Dict[str, Any]], summary_text: str) -> str:
        lines = [f"# 陪练报告 · {scenario}", "", "## 各轮成绩", "",
                 "| 轮次 | 准确性 | 流畅度 | 完整度 | 逻辑性 | 总分 |", "| --- | --- | --- | --- | --- | --- |"]
        for r in rounds:
            lines.append(f"| {r['round']} | {r.get('准确性',0)} | {r.get('流畅度',0)} | "
                         f"{r.get('完整度',0)} | {r.get('逻辑性',0)} | {r.get('总分',0)} |")
        lines += ["", "## 总结", "", summary_text, ""]
        return "\n".join(lines)


# ----------------------------------------------------------------------
# 注册表
# ----------------------------------------------------------------------

FEATURES: Dict[str, type] = {
    "M1": ExerciseSolver,
    "M2": KnowledgeMapper,
    "M3": MistakeAnalyzer,
    "M4": ConceptExplainer,
    "M5": WeaknessPlanner,
    "M6": OralCoach,
}

_ALIASES = {
    "习题解析": "M1", "知识框架": "M2", "错题归纳": "M3", "概念讲解": "M4",
    "薄弱检测": "M5", "复习计划": "M5", "口语陪练": "M6", "口语": "M6",
}


def normalize_module(module: str) -> str:
    if not module:
        return "M1"
    key = module.strip()
    upper = key.upper()
    if upper in FEATURES:
        return upper
    if key in _ALIASES:
        return _ALIASES[key]
    for name, mid in _ALIASES.items():
        if name in key:
            return mid
    return "M1"


def get_feature(module: str) -> BaseFeature:
    return FEATURES[normalize_module(module)]()
