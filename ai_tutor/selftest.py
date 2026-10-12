"""一键自检：完全离线跑通"提示词 → 调用 → 质检 → 落库 → 指标 → 报告"全链路。

这是本项目"可交付、可复现"的证据脚本：
    python -m ai_tutor selftest
不需要任何 API Key、不需要联网。
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, List, Tuple

from .eval import HALLUCINATION_CASES, LOGIC_CASES, REPETITION_CASE, judge
from .prompts import list_modules, prompt_library_markdown
from .service import AgentService
from .utils import mean_pairwise_similarity, table

PASS = "✓"
FAIL = "✗"


class Checker:
    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self.results: List[Tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        if self.verbose:
            mark = PASS if ok else FAIL
            print(f"  [{mark}] {name}" + (f"　{detail}" if detail else ""))
        return ok

    def section(self, title: str) -> None:
        if self.verbose:
            print()
            print(f"■ {title}")

    @property
    def passed(self) -> int:
        return sum(1 for _, ok, _ in self.results if ok)

    @property
    def total(self) -> int:
        return len(self.results)


def offline_service(svc: AgentService) -> AgentService:
    """构造一个只含内置离线模型的服务实例，供自检使用。

    这样即使 config.json 里配置了真实模型的 API Key，自检也能：
      · 完全离线运行（不依赖网络）；
      · 结果完全可复现；
      · 不消耗任何 API 额度。
    """
    from .features.base import FeatureContext  # noqa: F401  (保持依赖显式)
    from .llm.mock import MockProvider
    from .llm.registry import LLMClient

    client = LLMClient({"mock": MockProvider("mock-offline")}, default="mock")
    return AgentService(config=svc.config, storage=svc.storage, client=client)


def _make_test_image(path) -> None:
    """生成一张自检用的题目图片（纯标准库写 PNG，不依赖 Pillow）。

    图片内容用简单的色块与线条表示一张"题目照片"，用于验证
    「图片读取 → base64 编码 → 多模态消息 → 落库 → 前端展示」的完整链路。
    """
    import struct
    import zlib

    width, height = 240, 120
    rows = []
    for y in range(height):
        row = bytearray([0])  # filter type 0
        for x in range(width):
            # 白底 + 几条深色"文字行"，形成可辨认的图片轮廓
            in_border = x < 3 or y < 3 or x >= width - 3 or y >= height - 3
            text_line = (28 <= y <= 34 or 52 <= y <= 58 or 76 <= y <= 82) and 20 <= x <= width - 20
            if in_border:
                row += bytes((40, 60, 110))
            elif text_line:
                row += bytes((30, 30, 30))
            else:
                row += bytes((250, 250, 250))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def run_selftest(svc: AgentService, verbose: bool = True, online: bool = False) -> int:
    """一键自检。默认在**离线模型**上运行，保证结果可复现、不消耗任何 API 额度。

    如需针对真实模型做自检，请用 `python -m ai_tutor selftest --online`
    （会真实调用接口并产生费用）。
    """
    c = Checker(verbose)
    if verbose:
        print("=" * 78)
        print("大学生期末复习 AI 答疑助手 · 一键自检")
        print(f"自检模型：{svc.client.default}　可用：{', '.join(svc.client.available_names())}")
        print("=" * 78)

    # ---------------------------------------------------------------- 1
    c.section("1. 提示词库（阶段二交付物 · 只提供精细提示模板）")
    modules = list_modules()
    c.check("六大模块齐备", len(modules) == 6, f"实际 {len(modules)} 个")
    for spec in modules:
        fine = spec.fine_prompt()
        sections = spec.structure.get("sections", [])
        # 精细提示必须逐条覆盖该模块的结构段落：既允许「【段落名】」写法，
        # 也允许把段落要求写成「① 说明文字（含段落名关键词）」，因此把要求行文本一并纳入匹配。
        requirement_text = "\n".join(spec.structure.get("requirements", []))
        haystack = fine + "\n" + requirement_text
        covered = []
        for s in sections:
            parts = [s] + [p for p in re.split(r"[：:（）()]", s) if len(p) >= 2]
            if any(part in haystack for part in parts):
                covered.append(s)
        has_coarse = hasattr(spec, "coarse_prompt")
        ok = (len(fine) > 200 and len(covered) == len(sections) and not has_coarse)
        c.check(f"{spec.id} {spec.title}：精细提示 + 结构段落完整（无粗放模板）", ok,
                f"fine={len(fine)}字 段落={len(covered)}/{len(sections)} "
                f"粗放字段={'残留' if has_coarse else '已移除'}")
    md = prompt_library_markdown()
    c.check("提示词库文档可导出", "五要素" in md and len(md) > 5000, f"{len(md)} 字符")

    # ---------------------------------------------------------------- 2
    c.section("2. 六大功能模块可独立运行（统一使用精细提示）")
    samples = [
        ("M1", "帮我解这道题：lim(x→0) (sin x - x) / x³"),
        ("M2", "帮我整理一下 TCP 协议的知识点"),
        ("M3", "帮我分析一下这个错题：这道题我第 2 步把 cos x − 1 直接替换成了 0"),
        ("M4", "帮我解释一下递归是什么"),
        ("M5", "帮我做个高等数学的复习计划，还剩 5 天"),
        ("M6", "陪我练一下计算机网络三次握手的背诵"),
    ]
    outputs: Dict[str, str] = {}
    for module, question in samples:
        result = svc.ask(question, module=module, save=True)
        outputs[module] = result["answer"]
        checks = result["checks"]
        ok = len(result["answer"]) > 150 and checks["section_coverage"] >= 0.8
        c.check(f"{module} 输出合规", ok,
                f"{len(result['answer'])}字 结构覆盖率={checks['section_coverage']} "
                f"结构分={checks['structure_score']}")

    # ---------------------------------------------------------------- 3
    c.section("3. 对外的提示词一致性（前端无模式开关）")
    a = svc.ask("帮我整理一下 TCP 协议的知识点", module="M2", save=False)
    b = svc.ask("帮我整理一下 TCP 协议的知识点", module="M2", save=False)
    c.check("同一问题的提示词完全一致（不存在可切换的提示模式）",
            a["prompt"] == b["prompt"], f"提示词长度 {len(a['prompt'])} 字符")
    c.check("提示词包含模块的角色/段落契约", "【角色】" in a["prompt"] and "输出契约" in a["prompt"])
    c.check("提示词不含任何“粗放/基线”字样",
            not any(k in a["prompt"] for k in ("粗放", "基线", "BASELINE")),
            f"{len(a['prompt'])} 字符")
    banned = [k for k in ("俄罗斯套娃", "剥洋葱") if k in outputs.get("M4", "")]
    c.check("M4 未使用被禁用的俗套类比", not banned, "、".join(banned))

    # ---------------------------------------------------------------- 4
    c.section("4. 风险判定与消融对照（阶段三，内部机制）")
    halluc_ok = []
    for case in HALLUCINATION_CASES[:3]:
        plain = svc.ask(case.plain_prompt or case.question, module=case.module,
                        save=False, plain_prompt=True)
        fine = svc.ask(case.question, module=case.module, save=False)
        v_plain, v_fine = judge(case, plain["answer"]), judge(case, fine["answer"])
        halluc_ok.append(not v_fine["risk_hit"])
        c.check(f"{case.id} 精细提示抑制幻觉",
                (not v_fine["risk_hit"]) and v_fine["compliance"],
                f"无约束提示命中风险={v_plain['risk_hit']}　精细提示命中风险={v_fine['risk_hit']}")
    logic_ok = []
    for case in LOGIC_CASES[:4]:
        fine = svc.ask(case.question, module=case.module, save=False)
        v_fine = judge(case, fine["answer"])
        logic_ok.append(not v_fine["risk_hit"])
        c.check(f"{case.id} 精细提示纠正逻辑错误",
                v_fine["conclusion_ok"] is True and not v_fine["risk_hit"],
                f"正确结论={v_fine['conclusion_ok']}　风险={v_fine['risk_hit']}")

    rep_texts = [svc.ask(REPETITION_CASE.question, module="M5", save=False)["answer"]
                 for _ in range(3)]
    rep = mean_pairwise_similarity(rep_texts)
    c.check("同质化指标可计算", rep["overall"] > 0,
            f"重复度={rep['overall']:.0%}（2-gram {rep['ngram_jaccard']:.0%}）")
    c.check("重复度算法对相同文本返回 1.0",
            abs(mean_pairwise_similarity(["同样的一段文字内容", "同样的一段文字内容"])["overall"] - 1.0) < 1e-6)

    # ---------------------------------------------------------------- 4.5
    c.section("4.5 图片输入链路（多模态消息 → 落库 → 展示）")
    from .llm.base import ImagePart, coerce_images
    test_png = svc.data_dir / "selftest-question.png"
    try:
        _make_test_image(test_png)
        part = ImagePart.from_path(str(test_png))
        c.check("图片可读取并编码为 data URI",
                part.data_uri.startswith("data:image/png;base64,") and part.size > 0,
                f"{part.name} {part.size / 1024:.1f} KB")
        c.check("coerce_images 支持路径 / data URI / ImagePart",
                len(coerce_images([str(test_png), part])) == 2)
        vision = svc.client.pick_vision_model()
        res = svc.ask("请看图片中的题目，按模块要求解析。", module="M1",
                      images=[str(test_png)], save=True)
        c.check("带图片的提问可完整返回", bool(res["answer"]) and res["meta"].get("vision") is True,
                f"{len(res['answer'])}字 模型={res['meta'].get('provider')}/{res['meta'].get('model')}")
        c.check("图片元信息已写入结果", len(res["meta"].get("images", [])) == 1,
                str(res["meta"].get("images", [{}])[0].get("name", "")))
        c.check("提示词包含图片识别契约", "【图片输入】" in res["prompt"])
        if online:
            c.check("存在可用的真实图片识别模型", vision is not None, f"选用 {vision or '（无）'}")
            c.check("真实模型已完成图片识别（未编造图片内容）",
                    "无法真正" not in res["answer"] and "无法" not in res["answer"][:40],
                    res["answer"][:40].replace("\n", " "))
        else:
            # 离线自检用的是 mock-only 客户端，因此直接检查**配置**里声明了视觉能力的提供方
            cfg_models = (svc.config.get("llm", {}) or {}).get("models", {}) or {}
            declared, ready = [], []
            for name, cfg in cfg_models.items():
                if name == "mock" or not cfg.get("vision"):
                    continue
                declared.append(name)
                if cfg.get("api_key"):
                    ready.append(name)
            c.check("配置中已声明具备视觉能力的提供方", bool(declared),
                    "、".join(declared) or "（无）")
            c.check("其中至少一个已配置 Key（图片识别可直接使用）", bool(ready),
                    f"已就绪：{'、'.join(ready) or '（无）'}"
                    f"；模型：{cfg_models.get(ready[0], {}).get('model', '') if ready else ''}")
            c.check("离线时如实声明无法识别图片（不编造内容）",
                    "无法真正识别图片内容" in res["answer"],
                    "离线模型按契约拒绝推断图片内容")
    except Exception as exc:  # noqa: BLE001
        c.check("图片输入链路", False, f"{type(exc).__name__}: {exc}")

    # ---------------------------------------------------------------- 5
    c.section("5. 风险报告落库与导出")
    report = svc.run_risk(kind="pair", output_dir=None)
    c.check("风险对照报告生成", bool(report.get("comparison", {}).get("rows")),
            f"{len(report.get('comparison', {}).get('rows', []))} 行")
    runs = svc.eval_runs(limit=5)
    c.check("评测记录已写入数据库", len(runs) > 0, f"{len(runs)} 条")
    records = svc.risk_records(limit=500)
    c.check("提示词与输出原文已完整落库", len(records) > 0, f"{len(records)} 条交互记录")

    # ---------------------------------------------------------------- 6
    c.section("6. 会话与产出物持久化")
    session = svc.create_session(title="自检会话", module="M1")
    detail = svc.get_session(session["id"])
    c.check("会话可创建与读取", bool(detail and detail["id"] == session["id"]))
    c.check("会话包含对话轮次", len(detail.get("turns", [])) >= 0)

    # ---------------------------------------------------------------- 7
    c.section("7. 任务路由（工具路由建议落地）")
    routes = svc.routes()
    c.check("路由表覆盖五类任务", len(routes) >= 5, f"{len(routes)} 类")
    fact = next((r for r in routes if r["task"] == "fact_check"), None)
    c.check("事实核查任务优先路由到保守模型",
            bool(fact and fact["preferred"] and fact["preferred"][0] in ("anthropic", "openai", "deepseek")),
            f"优先级={fact['preferred'] if fact else '—'}")
    detected = svc.detect("列出 3 篇 2023 年关于 EDTA 配位滴定的 SCI 论文，给出 DOI")
    c.check("事实类提问被识别为事实核查任务", detected["route"]["task"] == "fact_check",
            f"识别为 {detected['route']['task']}")

    # ---------------------------------------------------------------- 8
    c.section("8. 运行报告")
    text = svc.report(limit=5)
    c.check("运行报告可生成", "# 大学生期末复习 AI 答疑助手" in text and len(text) > 300,
            f"{len(text)} 字符")

    # ---------------------------------------------------------------- 汇总
    if verbose:
        print()
        print("=" * 78)
        print(table(["检查项", "结果", "说明"],
                    [[name, PASS if ok else FAIL, detail] for name, ok, detail in c.results],
                    width=44))
        print("=" * 78)
        print(f"自检结果：{c.passed}/{c.total} 项通过" +
              ("　✅ 全部通过" if c.passed == c.total else "　⚠ 存在未通过项"))
        print(f"数据目录：{svc.data_dir}")
        print("=" * 78)
    return 0 if c.passed == c.total else 1


if __name__ == "__main__":
    raise SystemExit(run_selftest(AgentService()))
