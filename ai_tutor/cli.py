"""命令行界面（CLI）。

用法总览：
    python -m ai_tutor status                        查看运行状态与已配置模型
    python -m ai_tutor models                        列出模型、可用性与视觉能力
    python -m ai_tutor routes                        查看任务路由表（工具路由建议）
    python -m ai_tutor modules                       列出六大功能模块
    python -m ai_tutor prompt show M1                查看精细提示词原文
    python -m ai_tutor prompt export prompts.md       导出完整提示词库文档
    python -m ai_tutor ask "问题" --image 题目.png     提问（支持图片输入）
    python -m ai_tutor chat                          交互式多轮对话（支持图片）
    python -m ai_tutor ablate "问题"                   提示词消融对照（评测用）
    python -m ai_tutor batch cases.jsonl             批量批改/解析
    python -m ai_tutor risk list                      列出风险测试用例
    python -m ai_tutor risk run --kind all            执行阶段三四类专项测试
    python -m ai_tutor report --out report.md         生成运行报告
    python -m ai_tutor export all ./deliverables      导出全部交付文档
    python -m ai_tutor selftest                       一键自检（离线可跑全流程）
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import APP_NAME, TEAM, __version__
from .config import PROJECT_ROOT, load_config
from .eval import COMPARISON_CASES, HALLUCINATION_CASES, LOGIC_CASES, REPETITION_CASE, get_case
from .features.plan import normalize_module
from .prompts import STRUCTURE_PATTERNS, get_module, list_modules, prompt_library_markdown
from .service import AgentService, get_service
from .utils import ellipsize, table, wrap_cjk

# ----------------------------------------------------------------------
# 输出工具
# ----------------------------------------------------------------------

def _setup_console() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)  # ENABLE_VIRTUAL_TERMINAL
        except Exception:
            pass

    # 让 print 不再因 GBK 控制台抛 UnicodeEncodeError（管道/重定向场景）
    if hasattr(sys.stdout, "buffer"):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                                          line_buffering=True)  # type: ignore[assignment]
        except (ValueError, AttributeError):
            pass


C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_RESET = "\033[0m"


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(text: str, color: str) -> str:
    return f"{color}{text}{C_RESET}" if _supports_color() else text


def hr(title: str = "") -> None:
    print(paint("─" * 78, C_DIM))
    if title:
        print(paint(title, C_BOLD))


def show_result(result: Dict[str, Any], show_prompt: bool = False, width: int = 100) -> None:
    meta = result.get("meta", {})
    vision = "　🖼 图片输入" if meta.get("vision") else ""
    hr(f"{result['module']} · 精细提示"
       f"　模型：{meta.get('provider')}/{meta.get('model')}"
       f"　耗时：{meta.get('elapsed_ms')}ms{vision}")
    if show_prompt:
        print(paint("【实际发送的提示词】", C_CYAN))
        print(wrap_cjk(result.get("prompt", ""), width))
        print(paint("【模型输出】", C_CYAN))
    print(wrap_cjk(result.get("answer", ""), width))
    checks = result.get("checks", {})
    hr()
    print(paint(f"质检：结构={checks.get('structure_score')} 诚实边界={checks.get('honesty_score')} "
                f"教学价值={checks.get('teaching_score')} 结构覆盖率={checks.get('section_coverage')}", C_DIM))
    if checks.get("redline_hits"):
        hits = "　".join(f"{k}={'✓' if v else '✗'}" for k, v in checks["redline_hits"].items())
        print(paint("红线落实：" + hits, C_DIM))
    if checks.get("uncertainty_marks"):
        print(paint("不确定标记：" + "、".join(checks["uncertainty_marks"]), C_DIM))
    for note in result.get("notes", []):
        print(paint("⚠ " + note, C_YELLOW))


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    text = Path(path).read_text(encoding="utf-8") if path != "-" else sys.stdin.read()
    stripped = text.strip()
    if not stripped:
        return items
    if stripped.startswith("["):
        return json.loads(stripped)
    for line in stripped.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            items.append(json.loads(line))
    return items


# ----------------------------------------------------------------------
# 子命令
# ----------------------------------------------------------------------

def cmd_status(svc: AgentService, args: argparse.Namespace) -> int:
    hr(f"{APP_NAME}　v{__version__}")
    print(f"团队：{TEAM}")
    print(f"默认模型：{paint(svc.client.default, C_GREEN)}　"
          f"可用：{', '.join(svc.client.available_names())}")
    print(f"已配置凭证的模型：{', '.join(svc.client.usable_names()) or '（无，使用内置离线模型）'}")
    if not svc.client.usable_names():
        print(paint("提示：当前未配置任何 API Key，应用使用内置离线模型运行——功能完整、可复现，"
                    "但输出不代表真实模型表现。填入 Key 后自动切换到真实模型。", C_YELLOW))
    stats = svc.storage.stats()
    print(f"数据：会话 {stats['sessions']}　轮次 {stats['turns']}　产出物 {stats['artifacts']}　"
          f"风险记录 {stats['risk_interactions']}　评测批次 {stats['eval_runs']}")
    print(f"数据库：{stats['db_path']}")
    print()
    print(table(["模块", "名称", "对应痛点", "结构模式", "路由任务"],
                [[m["id"], m["title"], m["pain_point"], m["pattern_label"], m["route_task"]]
                 for m in svc.modules()], width=26))
    return 0


def cmd_models(svc: AgentService, args: argparse.Namespace) -> int:
    rows = []
    for m in svc.models():
        rows.append([m["provider"], m["model"], "✓" if m["available"] else "—",
                     "✓" if m.get("supports_vision") else "—",
                     "默认" if m.get("is_default") else "", m["base_url"] or "—"])
    print(table(["提供方", "模型", "可用", "图片", "", "base_url"], rows, width=32))
    print()
    print("接入真实模型：在 config.json 填写 api_key，或设置环境变量（DEEPSEEK_API_KEY / "
          "OPENAI_API_KEY / ANTHROPIC_API_KEY / QIANFAN_API_KEY 等）。")
    vision = svc.client.pick_vision_model()
    if vision:
        print(f"图片输入：可用（将由 {vision} 识别图片；提供方需 vision=true）。")
    else:
        print("图片输入：当前没有可用的视觉模型，请在 config.json 配置一个支持图片的提供方。")
    return 0


def cmd_routes(svc: AgentService, args: argparse.Namespace) -> int:
    hr("任务路由表（阶段三「改进建议 4：工具路由」的代码实现）")
    rows = []
    for item in svc.routes():
        rows.append([item["label"], item["resolved_model"],
                     "、".join(item["preferred"]) or item["resolved_model"],
                     f"{item['temperature']}"])
    print(table(["任务类型", "当前选用", "优先级顺序", "温度"], rows, width=30))
    print()
    for item in svc.routes():
        print(paint(f"· {item['label']}：{item['reason']}", C_DIM))
    return 0


def cmd_modules(svc: AgentService, args: argparse.Namespace) -> int:
    for m in svc.modules():
        print(paint(f"{m['id']} · {m['title']}", C_BOLD))
        print(f"  痛点：{m['pain_point']}　结构：{m['pattern_label']}　路由：{m['route_task']}　温度：{m['temperature']}")
        print(f"  目标：{m['goal']}")
        print(f"  精细提示段落：{'、'.join(m['sections'])}")
        print()
    return 0


def cmd_prompt(svc: AgentService, args: argparse.Namespace) -> int:
    if args.action == "export":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(prompt_library_markdown(), encoding="utf-8")
        print(f"已导出提示词库：{out}（{len(prompt_library_markdown())} 字符）")
        return 0

    spec = get_module(args.module)
    if spec is None:
        print(f"未知模块：{args.module}（可选 {'、'.join(m.id for m in list_modules())}）")
        return 2
    hr(f"{spec.id} 精细提示（应用正式使用的模板）")
    print(spec.fine_prompt())
    hr("输出模式（JSON Schema）")
    print(spec.schema_json() if spec.json_schema else "（无）")
    return 0


def _build_ask_kwargs(args: argparse.Namespace) -> Dict[str, Any]:
    images = _collect_images(args)
    return {
        "module": args.module,
        "model": args.model,
        "use_router": args.router,
        "temperature": args.temperature,
        "session_id": args.session,
        "images": images,
        "subject": getattr(args, "subject", "") or "",
        "days": getattr(args, "days", 5) or 5,
        "student_answer": getattr(args, "student_answer", "") or "",
        "answers": getattr(args, "answers", "") or "",
        "stage": getattr(args, "stage", "auto") or "auto",
        "level": getattr(args, "level", "零基础") or "零基础",
        "student_reply": getattr(args, "reply", "") or "",
        "scenario": getattr(args, "scenario", "") or "",
    }


def _collect_images(args: argparse.Namespace) -> List[Any]:
    """收集命令行传入的图片：--image 可重复、也支持通配符与目录。"""
    raw: List[str] = []
    for item in list(getattr(args, "image", None) or []):
        path = Path(item)
        if path.is_dir():
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif"):
                raw.extend(str(p) for p in sorted(path.glob(ext)))
        elif any(ch in item for ch in "*?["):
            raw.extend(str(p) for p in sorted(Path().glob(item)))
        else:
            raw.append(item)
    if raw:
        print(paint(f"待上传图片：{'、'.join(Path(p).name for p in raw)}", C_DIM))
    return raw


def cmd_ask(svc: AgentService, args: argparse.Namespace) -> int:
    question = args.question or (sys.stdin.read() if not sys.stdin.isatty() else "")
    if not question.strip():
        print("请提供问题内容。")
        return 2
    kwargs = _build_ask_kwargs(args)
    result = svc.ask(question, **kwargs)
    show_result(result, show_prompt=args.show_prompt, width=args.width)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_chat(svc: AgentService, args: argparse.Namespace) -> int:
    kwargs = _build_ask_kwargs(args)
    session = svc.create_session(title=args.title or "CLI 对话", module=args.module)
    kwargs["session_id"] = session["id"]
    hr(f"{APP_NAME} · 交互式答疑（模块 {args.module} · 精细提示）")
    print(paint("输入问题回车发送；命令：:module M3 切换模块　:router 开关路由　"
                ":image <路径> 附加图片　:clear 清空图片　:prompt 查看上次提示词　"
                ":json 开关 JSON　:quit 退出", C_DIM))
    if kwargs.get("images"):
        print(paint(f"已附加 {len(kwargs['images'])} 张图片（仅本次提问生效；可用 :clear 清除）", C_CYAN))
    json_on = False
    last: Optional[Dict[str, Any]] = None
    while True:
        try:
            line = input(paint("你 > ", C_GREEN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in (":quit", ":q", ":exit"):
            break
        if line.startswith(":image"):
            value = line.split(maxsplit=1)
            if len(value) > 1:
                path = Path(value[1].strip().strip('"'))
                if path.exists():
                    kwargs.setdefault("images", []).append(str(path))
                    print(paint(f"已附加图片：{path.name}（共 {len(kwargs['images'])} 张）", C_CYAN))
                else:
                    print(paint(f"图片不存在：{path}", C_RED))
            else:
                print(paint("用法：:image D:\\path\\题目.png", C_DIM))
            continue
        if line == ":clear":
            kwargs["images"] = []
            print(paint("已清空附加图片", C_CYAN))
            continue
        if line.startswith(":module"):
            value = line.split(maxsplit=1)
            if len(value) > 1:
                kwargs["module"] = normalize_module(value[1])
            print(paint(f"当前模块 → {kwargs['module']}", C_CYAN))
            continue
        if line == ":router":
            kwargs["use_router"] = not kwargs["use_router"]
            print(paint(f"工具路由 → {'开' if kwargs['use_router'] else '关'}", C_CYAN))
            continue
        if line == ":json":
            json_on = not json_on
            print(paint(f"JSON 输出 → {'开' if json_on else '关'}", C_CYAN))
            continue
        if line == ":prompt" and last:
            print(wrap_cjk(last.get("prompt", ""), args.width))
            continue
        if line == ":session":
            print(json.dumps(svc.get_session(kwargs["session_id"]), ensure_ascii=False, indent=2))
            continue
        try:
            result = svc.ask(line, **kwargs)
        except Exception as exc:  # noqa: BLE001
            print(paint(f"调用失败：{exc}", C_RED))
            continue
        last = result
        show_result(result, width=args.width)
        if json_on:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    print(paint(f"会话已保存：{kwargs['session_id']}（数据库：{svc.storage.db_path}）", C_DIM))
    return 0


def cmd_ablate(svc: AgentService, args: argparse.Namespace) -> int:
    """提示词消融对照（评测层）：同一问题分别用精细提示与无约束提示各跑一次。"""
    result = svc.compare(args.question, module=args.module, model=args.model,
                         use_router=args.router)
    hr(f"提示词消融对照　模块：{result['module']}")
    for key, label in (("plain", "无约束提示（消融对照）"), ("constrained", "精细提示（正式使用）")):
        item = result[key]
        print(paint(f"■ {label}　{len(item['answer'])} 字符　"
                    f"结构={item['checks']['structure_score']}　"
                    f"诚实={item['checks']['honesty_score']}　"
                    f"教学={item['checks']['teaching_score']}", C_BOLD))
        print(wrap_cjk(item["answer"], args.width))
        print()
    print(paint("■ 量化差异", C_BOLD))
    print(table(["指标", "差值（精细 − 无约束）"],
                [["字符数", result["delta"]["chars"]],
                 ["结构完整度", result["delta"]["structure"]],
                 ["不确定标记", result["delta"]["uncertainty"]],
                 ["教学价值", result["delta"]["teaching"]]], width=28))
    print(paint("■ 输出相似度（越低说明两种提示词下的输出差异越大）", C_BOLD))
    sim = result["similarity"]
    print(table(["2-gram Jaccard", "LCS 占比", "结构相似度", "综合"],
                [[sim["ngram_jaccard"], sim["lcs_ratio"], sim["structure_sim"], sim["overall"]]]))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_batch(svc: AgentService, args: argparse.Namespace) -> int:
    items = load_jsonl(args.file)
    if not items:
        print("没有可处理的数据。每行形如："
              '{"question": "...", "module": "M1", "image": "D:/path/q.png"}')
        return 2
    rows, outputs = [], []
    for i, item in enumerate(items, 1):
        question = item.get("question") or item.get("text") or ""
        module = item.get("module") or "auto"
        item_images = item.get("images") or ([item["image"]] if item.get("image") else None)
        try:
            result = svc.ask(question, module=module, model=args.model,
                            use_router=args.router, student_answer=item.get("student_answer", ""),
                            images=item_images, save=True)
        except Exception as exc:  # noqa: BLE001
            print(paint(f"[{i}] 失败：{exc}", C_RED))
            rows.append([i, module, "失败", str(exc)[:40]])
            continue
        rows.append([i, result["module"], len(result["answer"]),
                     result["checks"]["structure_score"], ellipsize(question, 28)])
        outputs.append({"index": i, "question": question, "module": result["module"],
                        "answer": result["answer"],
                        "checks": result["checks"], "meta": result["meta"]})
    print(table(["#", "模块", "字数", "结构分", "题目"], rows, width=30))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for item in outputs:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"已写出 {len(outputs)} 条结果：{out}")
    return 0


def cmd_risk(svc: AgentService, args: argparse.Namespace) -> int:
    if args.action == "list":
        rows = []
        for case in HALLUCINATION_CASES + LOGIC_CASES + [REPETITION_CASE]:
            rows.append([case.id, {"hallucination": "事实幻觉", "logic": "逻辑缺陷",
                                   "repetition": "同质化"}.get(case.type, case.type),
                         case.module, ellipsize(case.title, 24), ellipsize(case.question, 34)])
        print(table(["编号", "类型", "模块", "标题", "问题"], rows, width=36))
        print(f"\n对比测试共 {len(COMPARISON_CASES)} 题（事实幻觉 5 + 逻辑缺陷 5）")
        return 0

    if args.action == "show":
        case = get_case(args.case_id)
        if not case:
            print(f"未找到用例 {args.case_id}")
            return 2
        print(paint(f"{case.id} · {case.title}（{case.type}）", C_BOLD))
        print(f"模块：{case.module}")
        print(f"问题：{case.question}")
        print(f"期望表现：{case.expectation}")
        print(f"风险模式：{json.dumps(case.risk_flags, ensure_ascii=False, indent=2)}")
        print(f"合规信号：{'、'.join(case.compliant_markers)}")
        if case.expected_conclusion:
            print(f"正确结论关键词：{'、'.join(case.expected_conclusion)}")
            print(f"错误结论关键词：{'、'.join(case.wrong_conclusion)}")
        print(f"说明：{case.note}")
        return 0

    print(paint("正在执行风险实证测试……", C_CYAN))
    report = svc.run_risk(kind=args.kind, model=args.model, rounds=args.rounds,
                          models=args.models, output_dir=args.outdir)
    if args.kind == "all":
        for key, item in report.items():
            _print_risk_report(item, args.width)
        paths = [v for item in report.values() for v in (item.get("artifacts") or {}).values()]
    else:
        _print_risk_report(report, args.width)
        paths = list((report.get("artifacts") or {}).values())
    if paths:
        print(paint("已保存：" + "、".join(paths), C_DIM))
    return 0


def _print_risk_report(report: Dict[str, Any], width: int) -> None:
    hr(report["title"])
    rows = report.get("comparison", {}).get("rows", [])
    if rows:
        headers = list(rows[0].keys())
        print(table(headers, [[r.get(h, "") for h in headers] for r in rows], width=26))
    if report.get("findings"):
        print(paint("关键发现：", C_BOLD))
        for i, item in enumerate(report["findings"], 1):
            print(wrap_cjk(f"  {i}. {item}", width))
    if report.get("suggestions"):
        print(paint("改进建议：", C_BOLD))
        for i, item in enumerate(report["suggestions"], 1):
            print(wrap_cjk(f"  {i}. {item}", width))
    print()


def cmd_report(svc: AgentService, args: argparse.Namespace) -> int:
    if getattr(args, "action", "run") == "assets":
        return cmd_report_assets(svc, args)
    text = svc.report(limit=args.limit)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"报告已写出：{out}")
    else:
        print(text)
    return 0


def cmd_report_assets(svc: AgentService, args: argparse.Namespace) -> int:
    """生成第三阶段风险实证的图片素材 + Excel 记录表 + Markdown 报告。"""
    from .report import DEFAULT_OUTDIR, generate_all

    mode = args.mode
    if mode == "auto":
        usable = [n for n in svc.client.usable_names() if n != "mock"]
        print(paint(f"数据来源：{'在线实测 ' + usable[0] if usable else '内置离线模型'}"
                    f"（可用模型：{', '.join(svc.client.available_names())}）", C_CYAN))
    outdir = Path(args.outdir) if args.outdir else DEFAULT_OUTDIR
    hr("正在采集风险实证数据并生成图解……")
    result = generate_all(svc, mode=mode, outdir=outdir, rounds=args.rounds,
                          workbook=not args.no_workbook, markdown=not args.no_markdown)
    print(paint(f"数据来源：{result.source_label}", C_BOLD))
    print()
    print(paint("生成的图片素材：", C_BOLD))
    for p in result.images:
        size = Path(p).stat().st_size / 1024
        print(f"  · {Path(p).name}　（{size:.0f} KB）")
    if result.workbook:
        print(f"\nExcel 记录表：{result.workbook}")
    if result.markdown:
        print(f"图文报告：{result.markdown}")
    if result.json:
        print(f"数据快照：{result.json}")
    for note in result.notes:
        print(paint("⚠ " + note, C_YELLOW))
    print()
    print(paint("提示：图片可直接插入汇报 PPT；Slide 10【关键截图位】对应 "
                "06_关键截图_EDTA实测对比.png", C_DIM))
    return 0


def cmd_export(svc: AgentService, args: argparse.Namespace) -> int:
    from .deliverables import export_all, export_prompt_library

    target = Path(args.outdir or (PROJECT_ROOT / "deliverables"))
    target.mkdir(parents=True, exist_ok=True)
    what = args.what
    written: List[str] = []
    if what in ("all", "prompts"):
        written += export_prompt_library(target, svc)
    if what in ("all", "modules"):
        written += export_all(target, svc)
    if what in ("all", "report"):
        path = target / "运行报告.md"
        path.write_text(svc.report(limit=20), encoding="utf-8")
        written.append(str(path))
    if what in ("all", "cases"):
        path = target / "风险测试用例集.md"
        path.write_text(_cases_markdown(), encoding="utf-8")
        written.append(str(path))
    for item in written:
        print(f"· {item}")
    print(f"\n共导出 {len(written)} 个文件到 {target}")
    return 0


def _cases_markdown() -> str:
    lines = ["# 风险实证测试用例集", "",
             "> 由 `python -m ai_tutor export cases` 自动生成。", ""]
    groups = [("一、事实幻觉测试（H）", HALLUCINATION_CASES),
              ("二、逻辑缺陷测试（L）", LOGIC_CASES),
              ("三、同质化测试（T）", [REPETITION_CASE])]
    for title, cases in groups:
        lines += [f"## {title}", ""]
        for case in cases:
            lines += [f"### {case.id} · {case.title}", "",
                      f"- **模块**：{case.module}",
                      f"- **问题**：{case.question}",
                      f"- **期望表现**：{case.expectation}"]
            if case.expected_conclusion:
                lines.append(f"- **正确结论关键词**：{'、'.join(case.expected_conclusion)}")
                lines.append(f"- **错误结论关键词**：{'、'.join(case.wrong_conclusion)}")
            lines += ["- **风险模式（正则）**：", ""]
            lines += [f"  - `{p}`" for p in case.risk_flags]
            lines += ["", f"- **合规信号**：{'、'.join(case.compliant_markers)}",
                      f"- **说明**：{case.note}", ""]
    return "\n".join(lines)


def cmd_selftest(svc: AgentService, args: argparse.Namespace) -> int:
    from .selftest import offline_service, run_selftest

    if not args.online:
        svc = offline_service(svc)
    return run_selftest(svc, verbose=not args.quiet, online=args.online)


def cmd_web(svc: AgentService, args: argparse.Namespace) -> int:
    from .webapp import serve

    host = args.host or svc.config.get("web", {}).get("host", "127.0.0.1")
    port = args.port or int(svc.config.get("web", {}).get("port", 8848))
    return serve(host=host, port=port, open_browser=args.open, service=svc)


def cmd_plan(svc: AgentService, args: argparse.Namespace) -> int:
    result = svc.weekly_plan(subject=args.subject, days=args.days,
                             weak_points=args.weak or None, model=args.model)
    show_result(result, width=args.width)
    if args.out:
        out = Path(args.out)
        out.write_text(result["meta"].get("plan_markdown") or result["answer"], encoding="utf-8")
        print(f"计划已写出：{out}")
    return 0


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai_tutor",
        description=f"{APP_NAME} · 命令行工具（{TEAM}）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="查看运行状态").set_defaults(func=cmd_status)
    sub.add_parser("models", help="列出模型与可用性").set_defaults(func=cmd_models)
    sub.add_parser("routes", help="查看任务路由表").set_defaults(func=cmd_routes)
    sub.add_parser("modules", help="列出六大功能模块").set_defaults(func=cmd_modules)

    p_prompt = sub.add_parser("prompt", help="查看 / 导出提示词库")
    p_prompt.add_argument("action", nargs="?", default="show", choices=["show", "export"])
    p_prompt.add_argument("module", nargs="?", default="M1")
    p_prompt.add_argument("--out", default="prompts.md")
    p_prompt.set_defaults(func=cmd_prompt)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--module", "-m", default="auto",
                        help="模块：auto 或 M1–M6（也接受中文名，如 习题解析）")
        sp.add_argument("--image", "-i", action="append", default=None, metavar="PATH",
                        help="附加图片（可重复；支持通配符与目录，如 -i 题目.png -i shots/）")
        sp.add_argument("--model", default=None, help="指定模型提供方（如 deepseek / openai / mock）")
        sp.add_argument("--temperature", type=float, default=None)
        sp.add_argument("--router", action="store_true", help="启用任务路由自动选模型")
        sp.add_argument("--width", type=int, default=100, help="输出折行宽度")
        sp.add_argument("--json", action="store_true", help="附加输出 JSON 结果")

    p_ask = sub.add_parser("ask", help="单次提问")
    p_ask.add_argument("question", nargs="?", default="")
    p_ask.add_argument("--show-prompt", action="store_true", help="同时打印实际发送的提示词")
    p_ask.add_argument("--session", default=None)
    p_ask.add_argument("--subject", default="")
    p_ask.add_argument("--days", type=int, default=5)
    p_ask.add_argument("--student-answer", default="")
    p_ask.add_argument("--answers", default="")
    p_ask.add_argument("--stage", default="auto", choices=["auto", "diagnose", "plan"])
    p_ask.add_argument("--level", default="零基础")
    p_ask.add_argument("--reply", default="")
    p_ask.add_argument("--scenario", default="")
    add_common(p_ask)
    p_ask.set_defaults(func=cmd_ask)

    p_chat = sub.add_parser("chat", help="交互式多轮对话")
    p_chat.add_argument("--title", default="")
    add_common(p_chat)
    p_chat.set_defaults(func=cmd_chat)

    p_cmp = sub.add_parser("ablate", help="提示词消融对照（评测用：精细 vs 无约束）")
    p_cmp.add_argument("question")
    add_common(p_cmp)
    p_cmp.set_defaults(func=cmd_ablate)

    p_batch = sub.add_parser("batch", help="批量处理 JSONL/JSON 题目文件")
    p_batch.add_argument("file", help="文件路径，或 - 表示标准输入")
    p_batch.add_argument("--out", default="")
    add_common(p_batch)
    p_batch.set_defaults(func=cmd_batch)

    p_risk = sub.add_parser("risk", help="风险实证测试（阶段三）")
    p_risk.add_argument("action", nargs="?", default="run",
                        choices=["run", "list", "show"])
    p_risk.add_argument("--kind", default="all", choices=["all", "pair", "repetition", "comparison"])
    p_risk.add_argument("--rounds", type=int, default=3)
    p_risk.add_argument("--models", nargs="*", default=None)
    p_risk.add_argument("--outdir", default=None)
    p_risk.add_argument("--case-id", dest="case_id", default="")
    p_risk.add_argument("--width", type=int, default=100)
    p_risk.add_argument("--model", default=None)
    p_risk.set_defaults(func=cmd_risk)

    p_report = sub.add_parser("report", help="生成运行报告 / 风险实证图解素材")
    p_report.add_argument("action", nargs="?", default="run", choices=["run", "assets"],
                          help="run=运行报告；assets=生成风险实证图片与 Excel 记录表")
    p_report.add_argument("--out", default="")
    p_report.add_argument("--limit", type=int, default=10)
    p_report.add_argument("--mode", default="auto", choices=["auto", "online", "offline"],
                          help="assets 的数据来源：auto 自动选择 / online 强制实测 / offline 离线复现")
    p_report.add_argument("--outdir", default="", help="assets 的输出目录")
    p_report.add_argument("--rounds", type=int, default=3, help="同质化测试重复次数")
    p_report.add_argument("--no-workbook", action="store_true", help="不生成 Excel 记录表")
    p_report.add_argument("--no-markdown", action="store_true", help="不生成 Markdown 图文报告")
    p_report.set_defaults(func=cmd_report)

    p_export = sub.add_parser("export", help="导出交付文档")
    p_export.add_argument("what", nargs="?", default="all",
                          choices=["all", "prompts", "modules", "report", "cases"])
    p_export.add_argument("outdir", nargs="?", default="")
    p_export.set_defaults(func=cmd_export)

    p_plan = sub.add_parser("plan", help="一键生成个性化复习计划（M5）")
    p_plan.add_argument("--subject", default="高等数学")
    p_plan.add_argument("--days", type=int, default=5)
    p_plan.add_argument("--weak", nargs="*", default=None)
    p_plan.add_argument("--model", default=None)
    p_plan.add_argument("--width", type=int, default=100)
    p_plan.add_argument("--out", default="")
    p_plan.set_defaults(func=cmd_plan)

    p_test = sub.add_parser("selftest", help="一键自检（默认离线，可复现、不消耗额度）")
    p_test.add_argument("--quiet", action="store_true")
    p_test.add_argument("--online", action="store_true",
                        help="使用 config 中的真实模型做自检（会真实调用接口并产生费用）")
    p_test.set_defaults(func=cmd_selftest)

    p_web = sub.add_parser("web", help="启动 Web 界面")
    p_web.add_argument("--host", default=None)
    p_web.add_argument("--port", type=int, default=None)
    p_web.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    p_web.set_defaults(func=cmd_web)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        svc = get_service()
    except Exception as exc:  # noqa: BLE001
        print(paint(f"初始化失败：{exc}", C_RED))
        return 1
    try:
        return int(args.func(svc, args) or 0)
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("AI_TUTOR_DEBUG"):
            raise
        print(paint(f"执行失败：{exc}", C_RED))
        print(paint("（设置 AI_TUTOR_DEBUG=1 可查看完整堆栈）", C_DIM))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
