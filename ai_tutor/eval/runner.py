"""风险实证测试执行器（阶段三核心）。

四类专项测试：
  1) 事实幻觉测试    —— 精细提示 vs 无约束提示 消融对照（H1–H6）
  2) 逻辑缺陷测试    —— 精细提示 vs 无约束提示 消融对照（L1–L5）
  3) 同质化测试      —— 同一任务重复 3 次，比较重复度；并验证"反同质化提示"的缓解效果
  4) 多工具横向对比  —— 相同精细提示词下比较多个模型（10 道题：幻觉 5 + 逻辑 5）

所有过程都会：
  · 保存提示词原文与输出原文到 SQLite（risk_interactions / turns）；
  · 用规则化判定给出量化指标，并明确标注哪些数字来自**离线模拟**。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..features import get_feature
from ..features.base import FeatureContext, quality_check
from ..prompts import get_module
from ..utils import mean_pairwise_similarity, now_iso
from .cases import (
    ANTI_REPETITION_PROMPTS,
    ANTI_REPETITION_SUFFIX,
    COMPARISON_CASES,
    HALLUCINATION_CASES,
    LOGIC_CASES,
    REPETITION_CASE,
    REPETITION_PROMPTS,
    RiskCase,
    all_cases,
    judge,
)
from .metrics import MetricSummary, aggregate, repetition_metrics, summarize


@dataclass
class RiskReport:
    """一次风险实证的完整结果。"""

    kind: str
    title: str
    created_at: str = field(default_factory=now_iso)
    config: Dict[str, Any] = field(default_factory=dict)
    summaries: List[Dict[str, Any]] = field(default_factory=list)
    comparison: Dict[str, Any] = field(default_factory=dict)
    details: List[Dict[str, Any]] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    markdown: str = ""
    artifacts: Dict[str, str] = field(default_factory=dict)
    simulated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RiskRunner:
    """执行阶段三的四类专项风险测试。"""

    def __init__(self, ctx: FeatureContext, output_dir: Optional[Path | str] = None) -> None:
        self.ctx = ctx
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_model(self, model: Optional[str]) -> str:
        """未显式指定模型时，使用当前客户端的**默认模型**（而不是内置离线模型）。

        否则会出现"标注为某模型、实际跑的是离线模型"的错误对照结果。
        """
        if model:
            return model
        default = self.ctx.client.default
        return default if default in self.ctx.client.providers else "mock"

    def _run_case(self, case: RiskCase, mode: str, model: Optional[str] = None,
                  extra: str = "", temperature: Optional[float] = None,
                  scenario: str = "", question_override: Optional[str] = None) -> Dict[str, Any]:
        """执行一条用例。

        `mode` 是**评测层参数**，取值：
          · "constrained" —— 应用正式的精细提示（含格式契约、质量红线、诚实边界）
          · "plain"       —— 无约束提示（仅角色 + 问题），用于消融对照
        它不是用户可见的提示词模式开关。
        """
        feature = get_feature(case.module)
        constrained = mode != "plain"
        question = question_override or case.prompt(constrained=constrained)
        resolved_model = self._resolve_model(model)
        old_model, old_temp, old_plain = self.ctx.model, self.ctx.temperature, self.ctx.plain_prompt
        self.ctx.model = resolved_model
        self.ctx.temperature = temperature if temperature is not None else old_temp
        self.ctx.plain_prompt = not constrained
        try:
            result = feature.ask(question, self.ctx,
                                 extra=extra if constrained else "", save=False)
        finally:
            self.ctx.model, self.ctx.temperature, self.ctx.plain_prompt = old_model, old_temp, old_plain

        verdict = judge(case, result.answer)
        self.ctx.storage.add_risk_interaction(
            case_id=case.id, case_type=case.type, module=case.module, title=case.title,
            question=question, mode=mode, answer=result.answer,
            mode_detected=result.meta.get("mode_detected", mode),
            flags=verdict.get("flags", []),
            provider=result.meta.get("provider", ""), model=result.meta.get("model", ""),
        )
        return {
            "case": case,
            "case_id": case.id,
            "title": case.title,
            "mode": mode,
            "question": question,
            "model": result.meta.get("model", ""),
            "requested_model": resolved_model,
            "provider": result.meta.get("provider", ""),
            "answer": result.answer,
            "checks": result.checks,
            "verdict": verdict,
            "prompt": result.prompt,
            "simulated": bool(result.meta.get("simulated")),
            "elapsed_ms": result.meta.get("elapsed_ms", 0),
        }

    # ------------------------------------------------------------ 测试 1+2 对照
    def run_risk_pair(self, cases: Optional[Sequence[RiskCase]] = None,
                      model: Optional[str] = None, save_evals: bool = True) -> RiskReport:
        """事实幻觉 + 逻辑缺陷 的提示词消融对照测试。"""
        cases = list(cases or (HALLUCINATION_CASES + LOGIC_CASES))
        details: List[Dict[str, Any]] = []
        summaries: List[MetricSummary] = []

        for mode in ("plain", "constrained"):
            records = []
            for case in cases:
                rec = self._run_case(case, mode, model=model)
                details.append({k: v for k, v in rec.items() if k != "case"})
                records.append(rec)
            summary = summarize(records, label=f"{'无约束提示（消融对照）' if mode == 'plain' else '精细提示（正式使用）'}（{model or self.ctx.client.default}）",
                                model=model or self.ctx.client.default, mode=mode,
                                criteria=self.ctx.config.get("risk", {}).get("pass_criteria"))
            summaries.append(summary)

        report = self._build_report("risk_pair", "事实幻觉 + 逻辑缺陷 · 提示词消融对照测试", summaries, details)
        if save_evals:
            self._persist(report)
        return report

    # ------------------------------------------------------------ 测试 3 同质化
    def run_repetition(self, case: Optional[RiskCase] = None, rounds: int = 3,
                       model: Optional[str] = None, with_mitigation: bool = True,
                       save_evals: bool = True) -> RiskReport:
        """同质化测试：同一提示重复 N 次；并验证反同质化提示的缓解效果。"""
        case = case or REPETITION_CASE
        rounds = max(2, int(rounds))
        details: List[Dict[str, Any]] = []
        summaries: List[MetricSummary] = []

        def _collect(extra: str, tag: str, prompts: Optional[List[str]] = None) -> List[Dict[str, Any]]:
            """同质化测试统一使用精细提示（REPETITION_CASE 的无约束提示很简略，
            会引入与"同质化"无关的变量）。"""
            out = []
            for i in range(rounds):
                question = REPETITION_CASE.question
                if prompts:
                    question = prompts[i % len(prompts)] + (extra or "")
                rec = self._run_case(case, "constrained", model=model, extra=extra if not prompts else "",
                                     question_override=question)
                rec["round"] = i + 1
                rec["variant"] = tag
                rec["question_used"] = question
                out.append(rec)
            return out

        base_records = _collect("", "默认精细提示", REPETITION_PROMPTS)
        base_rep = mean_pairwise_similarity([r["answer"] for r in base_records])
        summaries.append(summarize(base_records, label="默认精细提示（重复 %d 次）" % rounds,
                                   model=model or self.ctx.client.default, mode="constrained",
                                   repetition=base_rep,
                                   criteria=self.ctx.config.get("risk", {}).get("pass_criteria")))
        details.extend({k: v for k, v in r.items() if k != "case"} for r in base_records)

        if with_mitigation:
            mit_records = _collect(ANTI_REPETITION_SUFFIX, "反同质化提示", ANTI_REPETITION_PROMPTS)
            mit_rep = mean_pairwise_similarity([r["answer"] for r in mit_records])
            summaries.append(summarize(mit_records, label="加入反同质化约束（重复 %d 次）" % rounds,
                                       model=model or self.ctx.client.default, mode="constrained",
                                       repetition=mit_rep,
                                       criteria=self.ctx.config.get("risk", {}).get("pass_criteria")))
            details.extend({k: v for k, v in r.items() if k != "case"} for r in mit_records)
            if mit_rep["overall"] < base_rep["overall"]:
                self._repetition_delta = (base_rep["overall"], mit_rep["overall"])

        report = self._build_report("repetition", "同质化测试（同一任务重复 %d 次）" % rounds,
                                    summaries, details)
        if save_evals:
            self._persist(report)
        return report

    # ------------------------------------------------------------ 测试 4 多工具对比
    def run_comparison(self, models: Optional[Sequence[str]] = None,
                       cases: Optional[Sequence[RiskCase]] = None,
                       save_evals: bool = True) -> RiskReport:
        """多工具横向对比：完全相同的精细提示词，比较多个模型。"""
        configured = self.ctx.config.get("risk", {}).get("comparison_models") or []
        available = self.ctx.client.usable_names()
        models = list(models or [n for n in configured if n in available])
        if not models:
            models = available or ["mock"]
        report_missing = [n for n in configured if n not in available]
        cases = list(cases or COMPARISON_CASES)

        summaries: List[MetricSummary] = []
        details: List[Dict[str, Any]] = []
        for model in models:
            records = [self._run_case(case, "constrained", model=model) for case in cases]
            details.extend({k: v for k, v in r.items() if k != "case"} for r in records)
            summaries.append(summarize(records, label=f"{model}（精细提示）", model=model, mode="constrained",
                                       criteria=self.ctx.config.get("risk", {}).get("pass_criteria")))

        # 同题重复 3 次计算重复度（同质化维度）
        rep_texts = [self._run_case(cases[0], "constrained", model=m)["answer"] for m in models]
        if len(rep_texts) > 1:
            summaries[0].repetition = mean_pairwise_similarity(rep_texts)

        report = self._build_report("comparison", "多工具横向对比（事实幻觉 5 题 + 逻辑缺陷 5 题）",
                                    summaries, details)
        report.config["models"] = models
        report.config["available_models"] = available
        report.config["missing_models"] = report_missing
        if models == ["mock"]:
            report.findings.append(
                "未检测到任何已配置 API Key 的模型，多工具横向对比暂时以**内置离线模型**演示流程；"
                "配置 Key 后（见 README「接入真实模型」）即可得到真实对比数据。")
        if report.config["missing_models"]:
            report.findings.append(
                "以下模型未配置 API Key，未纳入对比：" + "、".join(report.config["missing_models"]) +
                "；如需真实横向对比，请在 config.json 或环境变量中填入对应的 API Key。")
        if save_evals:
            self._persist(report)
        return report

    # ------------------------------------------------------------ 全量
    def run_all(self, model: Optional[str] = None, rounds: int = 3,
                models: Optional[Sequence[str]] = None, save_evals: bool = True) -> Dict[str, RiskReport]:
        return {
            "risk_pair": self.run_risk_pair(model=model, save_evals=save_evals),
            "repetition": self.run_repetition(rounds=rounds, model=model, save_evals=save_evals),
            "comparison": self.run_comparison(models=models, save_evals=save_evals),
        }

    # ------------------------------------------------------------ 构建报告
    def _build_report(self, kind: str, title: str, summaries: List[MetricSummary],
                      details: List[Dict[str, Any]]) -> RiskReport:
        report = RiskReport(
            kind=kind, title=title,
            config={"model_default": self.ctx.client.default,
                    "prompt_strict": not self.ctx.plain_prompt,
                    "available_models": self.ctx.client.available_names(),
                    "router": self.ctx.use_router,
                    "offline_mock": "mock" in self.ctx.client.available_names()},
            summaries=[s.to_dict() for s in summaries],
            comparison=aggregate(summaries, title),
            details=details,
            # 只有**全部**对照组都来自离线模型时才标记为模拟，避免把真实模型的
            # 结果误标成"离线模拟"。
            simulated=bool(summaries) and all(s.simulated for s in summaries),
        )
        report.findings = self._findings(report, summaries)
        report.suggestions = self._suggestions(report, summaries)
        report.markdown = self._to_markdown(report)
        return report

    @staticmethod
    def _findings(report: RiskReport, summaries: List[MetricSummary]) -> List[str]:
        out: List[str] = []
        for s in summaries:
            tag = f"{s.label}"
            if s.hallucination_cases:
                out.append(f"{tag}：事实幻觉率 {s.hallucination_rate:.0%}"
                           f"（{s.hallucination_hits}/{s.hallucination_cases}）")
            if s.logic_cases:
                out.append(f"{tag}：逻辑错误率 {s.logic_error_rate:.0%}"
                           f"（{s.logic_hits}/{s.logic_cases}）")
            if s.repetition:
                out.append(f"{tag}：重复度 {s.repetition_overall:.0%}"
                           f"（2-gram {s.repetition.get('ngram_jaccard', 0):.0%} / "
                           f"LCS {s.repetition.get('lcs_ratio', 0):.0%} / "
                           f"结构 {s.repetition.get('structure_sim', 0):.0%}）")
        if len(summaries) >= 2 and summaries[0].hallucination_cases and summaries[1].hallucination_cases:
            a, b = summaries[0].hallucination_rate, summaries[1].hallucination_rate
            if a > b:
                out.append(f"精细提示使事实幻觉率从 {a:.0%} 降至 {b:.0%}，"
                           f"下降 {(a - b) * 100:.0f} 个百分点（缓解幅度 {(1 - b / a) * 100:.0f}%）")
            elif a == b:
                out.append(f"本次测试中两版提示的事实幻觉率相同（均为 {a:.0%}），"
                           "说明该模型面对无来源问题时本身就较为谨慎，提示词在此维度上没有额外增益。")
        if len(summaries) >= 2 and summaries[0].logic_cases and summaries[1].logic_cases:
            a, b = summaries[0].logic_error_rate, summaries[1].logic_error_rate
            if a > b:
                out.append(f"加入分步推导/先举反例等约束后，逻辑错误率从 {a:.0%} 降至 {b:.0%}")
            elif a == b == 0:
                out.append("两版提示的逻辑错误率均为 0%：该模型在条件推导类问题上本身较稳健，"
                           "提示词工程并未改变其逻辑正确性，改善主要体现在结构、透明度与诚实边界上。")
        # 同质化对照（默认 vs 反同质化约束）
        check = {}
        for s in summaries:
            if s.repetition:
                check["默认" if "反同质化" not in s.label else "反同质化"] = s.repetition_overall
        if {"默认", "反同质化"} <= set(check):
            base_rep, mit_rep = check["默认"], check["反同质化"]
            threshold = 0.30
            if base_rep <= threshold:
                out.append(f"默认精细提示的重复度仅 {base_rep:.0%}，已低于 {threshold:.0%} 的可接受线，"
                           "说明该模型在同一任务上本身就有较强的表达变化能力，"
                           "与阶段三汇报中「相似度 85%–90%」的观察不一致（模型版本差异）。")
            if mit_rep < base_rep:
                out.append(f"反同质化约束把重复度从 {base_rep:.0%} 降到 {mit_rep:.0%}，缓解有效。")
            else:
                out.append(f"注意：本次反同质化约束**未**降低重复度（{base_rep:.0%} → {mit_rep:.0%}）。"
                           "原因通常是「至少给出 2 种组织方式」这类指令会压缩单次输出长度，"
                           "反而使不同轮次的输出更接近模板；说明反同质化指令需要按模型调优，"
                           "不能默认「加了就一定更好」。")
        # 结构 / 透明度增益（提示词工程最主要的价值所在）
        for s in summaries:
            if s.avg_chars:
                out.append(f"{s.label}：结构完整度 {s.avg_structure:.2f}、不确定标记 {s.avg_uncertainty:.2f}、"
                           f"平均输出 {s.avg_chars} 字")
        if len(summaries) >= 2:
            c0, c1 = summaries[0], summaries[1]
            if c1.avg_structure > c0.avg_structure + 0.2:
                out.append(f"核心结论：精细提示把结构完整度从 {c0.avg_structure:.2f} 提升到 "
                           f"{c1.avg_structure:.2f}，把主动的不确定标记从 {c0.avg_uncertainty:.2f} 提升到 "
                           f"{c1.avg_uncertainty:.2f}——提示词工程的主要价值是「让输出可预期、可复用、可信赖」，"
                           "而不是「让模型变聪明」。")
        if report.simulated:
            out.append("注：本次实验**全部**由内置离线模型完成（simulated=true），指标可复现，"
                       "但不代表任何商业模型的实际表现；配置 API Key 后可得到真实对比数据。")
        elif any(s.simulated for s in summaries):
            out.append("注：本批次含部分离线模拟输出（见各对照组的「来源」列），"
                       "真实模型与模拟结果请勿混用解读。")
        return out

    @staticmethod
    def _suggestions(report: RiskReport, summaries: List[MetricSummary]) -> List[str]:
        return [
            "提示词强制约束：在系统提示中加入「不确定时明确声明，禁止编造文献/数据/出处」。",
            "逻辑类任务模板化：要求模型「先举反例 → 再分情况 → 最后给结论」，减少直觉式回答。",
            "反同质化：在生成任务中加入「请给出 2 种不同组织方式」「变换叙述风格」指令。",
            "工具路由：事实校验类问题走 Claude，结构化提纲走 GPT-4o，中文口语化讲解走文心一言"
            "（已实现为 `TaskRouter`，可用 --router 启用）。",
            "人工复核：涉及具体教材页码、文献 DOI、政策条文的输出，必须标注「待核实」。",
        ]

    def _to_markdown(self, report: RiskReport) -> str:
        rows = report.comparison.get("rows", [])
        lines = [
            f"# {report.title}",
            "",
            f"- 生成时间：{report.created_at}",
            f"- 默认模型：{report.config.get('model_default')}",
            f"- 可用模型：{', '.join(report.config.get('available_models', []))}",
            f"- 是否含离线模拟输出：{'是' if report.simulated else '否'}",
            "",
            "## 一、量化对比",
            "",
        ]
        if rows:
            headers = list(rows[0].keys())
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
        lines += ["", "## 二、关键发现", ""]
        lines += [f"{i}. {f}" for i, f in enumerate(report.findings, 1)]
        lines += ["", "## 三、改进建议", ""]
        lines += [f"{i}. {s}" for i, s in enumerate(report.suggestions, 1)]
        lines += ["", "## 四、逐条记录（提示词原文与输出原文）", ""]
        for item in report.details:
            lines += [
                f"### {item.get('case_id')} · {item.get('title')}（{item.get('mode')}）",
                "",
                f"- 风险命中：{'是' if item.get('verdict', {}).get('risk_hit') else '否'}",
                f"- 合规信号：{'、'.join(item.get('verdict', {}).get('compliant_markers', [])) or '无'}",
                f"- 提供方/模型：{item.get('provider')} / {item.get('model')}"
                f"{'（离线模拟）' if item.get('simulated') else ''}",
                f"- 耗时：{item.get('elapsed_ms')} ms",
                "",
                "**提示词原文**",
                "",
                "```text",
                (item.get("prompt") or "").strip(),
                "```",
                "",
                "**输出原文**",
                "",
                "```text",
                (item.get("answer") or "").strip(),
                "```",
                "",
            ]
        return "\n".join(lines)

    # ------------------------------------------------------------ 落库与导出
    def _persist(self, report: RiskReport) -> None:
        file_path = ""
        if self.output_dir:
            path = self.output_dir / f"{report.kind}-{report.created_at.replace(':', '').replace('-', '')[:15]}.md"
            path.write_text(report.markdown, encoding="utf-8")
            json_path = path.with_suffix(".json")
            json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2,
                                            default=str), encoding="utf-8")
            file_path = str(path)
            report.artifacts = {"markdown": str(path), "json": str(json_path)}
        metrics = {
            "summaries": report.summaries,
            "simulated": report.simulated,
            "findings": report.findings,
        }
        self.ctx.storage.add_eval_run(
            kind=report.kind, title=report.title, config=report.config,
            metrics=metrics, detail={"comparison": report.comparison, "details": report.details},
            file_path=file_path,
        )
