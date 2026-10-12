"""生成第三阶段风险实证的全部素材：PNG 图解 + Excel 记录表 + Markdown 报告。

CLI：`python -m ai_tutor report assets [--mode auto|online|offline] [--outdir ...]`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..config import PROJECT_ROOT
from ..service import AgentService
from .data import AssetBundle, collect_assets
from .figures import CASE_ANALYSIS, CASE_TITLES, generate_images

DEFAULT_OUTDIR = PROJECT_ROOT / "deliverables" / "风险实证图解"


@dataclass
class AssetResult:
    outdir: str
    source: str
    source_label: str
    images: List[str] = field(default_factory=list)
    workbook: str = ""
    markdown: str = ""
    json: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outdir": self.outdir, "source": self.source,
            "source_label": self.source_label,
            "images": list(self.images), "workbook": self.workbook,
            "markdown": self.markdown, "json": self.json,
            "notes": list(self.notes),
        }


def generate_all(svc: AgentService, *, mode: str = "auto", outdir: Optional[Path | str] = None,
                 rounds: int = 3, workbook: bool = True,
                 markdown: bool = True) -> AssetResult:
    """采集数据 → 出图 → 出 Excel → 出 Markdown 报告。"""
    out = Path(outdir) if outdir else DEFAULT_OUTDIR
    out.mkdir(parents=True, exist_ok=True)

    bundle = collect_assets(svc, mode=mode, rounds=rounds, output_dir=out)
    images = generate_images(bundle, out)

    result = AssetResult(
        outdir=str(out), source=bundle.source, source_label=bundle.source_label,
        images=[str(p) for p in images], notes=list(bundle.extra_notes),
    )
    if workbook:
        from .workbook import write_workbook
        result.workbook = str(write_workbook(bundle, out / "风险实证记录表.xlsx"))
    if markdown:
        result.markdown = str(write_markdown(bundle, out, images))
    # 同时落一份数据快照，便于复核图上每个数字的来源
    import json
    snapshot = out / "风险实证数据.json"
    snapshot.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
    result.json = str(snapshot)
    return result


def write_markdown(bundle: AssetBundle, outdir: Path, images: Sequence[Path]) -> Path:
    """把图解串成一份可直接阅读/提交的 Markdown 报告。"""
    plain = bundle.condition("plain")
    constr = bundle.condition("constrained")
    lines: List[str] = [
        "# 第三阶段 · 风险实证图解报告",
        "",
        "> 大学生期末复习 AI 答疑助手 · 第二组（李明轩　韩武晋　郑志）",
        f"> 生成时间：{bundle.created_at}　数据来源：**{bundle.source_label}**",
        "",
    ]
    if bundle.simulated:
        lines += [
            "> ⚠ 本批素材由**内置离线模型**生成：指标可复现、不消耗额度，"
            "但不代表任何商业模型的实际表现。配置 API Key 后重新生成即可得到真实数据。",
            "",
        ]
    lines += [
        "## 一、测试设置（对应汇报 Slide 3）",
        "",
        "| 项目 | 设置 |",
        "| --- | --- |",
        f"| 测试对象 | {bundle.model}（{'离线模型' if bundle.simulated else '真实模型'}） |",
        "| 提示词设置 | 同一用例分别用「精细提示」与「无约束提示」各跑一次（消融对照） |",
        "| 记录方式 | 测试序号 / 模块 / 测试主题 / 两版输出评价 / 关键截图 |",
        "| 评价维度 | 结构完整性 / 事实准确性 / 逻辑严谨性 / 幻觉出现率 / 同质化程度 |",
        "| 通过标准 | 精细提示下：幻觉率 ≤20%、逻辑错误 ≤1 处、重复度 ≤30% |",
        "",
        "## 二、测试结果图解",
        "",
    ]
    for path in images:
        title = Path(path).stem.replace("_", " · ", 1)
        lines += [f"### {title}", "", f"![{title}]({Path(path).name})", ""]

    lines += ["## 三、逐条用例记录", ""]
    for row in bundle.cases:
        lines += [
            f"### {row.case_id} · {CASE_TITLES.get(row.case_id, row.title)}",
            "",
            f"- **模块**：{row.module}",
            f"- **输入提示**：{row.question}",
            f"- **无约束提示**：{'命中风险' if row.plain_risk else '未命中'}"
            f"（命中模式：{'、'.join(f'`{f}`' for f in row.plain_flags) or '无'}）",
            f"- **精细提示**：{'命中风险' if row.constrained_risk else '已合规'}"
            f"（命中模式：{'、'.join(f'`{f}`' for f in row.constrained_flags) or '无'}）",
            f"- **分析结论**：{CASE_ANALYSIS.get(row.case_id, '')}",
            "",
            "<details><summary>展开两版输出原文</summary>",
            "",
            "**无约束提示输出**",
            "",
            "```text",
            (row.plain_answer or "").strip()[:4000],
            "```",
            "",
            "**精细提示输出**",
            "",
            "```text",
            (row.constrained_answer or "").strip()[:4000],
            "```",
            "",
            "</details>",
            "",
        ]

    if plain and constr:
        lines += [
            "## 四、汇总指标",
            "",
            "| 指标 | 无约束提示 | 精细提示 | 通过标准 | 是否达标 |",
            "| --- | --- | --- | --- | --- |",
            f"| 事实幻觉出现率 | {plain.hallucination_rate:.0%} | {constr.hallucination_rate:.0%} "
            f"| ≤20% | {'✓' if constr.hallucination_rate <= 0.20 else '✗'} |",
            f"| 逻辑错误率 | {plain.logic_error_rate:.0%} | {constr.logic_error_rate:.0%} "
            f"| ≤20% | {'✓' if constr.logic_error_rate <= 0.20 else '✗'} |",
            f"| 合规率 | {plain.compliance_rate:.0%} | {constr.compliance_rate:.0%} | — | — |",
            f"| 结构完整度 | {plain.avg_structure:.2f} | {constr.avg_structure:.2f} | — | — |",
            f"| 不确定标记 | {plain.avg_uncertainty:.2f} | {constr.avg_uncertainty:.2f} | — | — |",
            f"| 平均输出字数 | {plain.avg_chars} | {constr.avg_chars} | — | — |",
            "",
        ]
    if bundle.repetition:
        lines += ["### 同质化测试", "",
                  "| 条件 | 平均相似度 | 2-gram | LCS | 结构 | 平均字数 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for block in bundle.repetition:
            lines.append(f"| {block.label} | {block.overall:.0%} | {block.ngram:.0%} "
                         f"| {block.lcs:.0%} | {block.structure:.0%} | {block.avg_chars} |")
        lines.append("")

    if bundle.tools:
        lines += ["## 五、多工具横向对比（Slide 10）", "",
                  "| 工具 | 事实幻觉出现率 | 逻辑错误率 | 来源 |", "| --- | --- | --- | --- |"]
        for t in bundle.tools:
            lines.append(f"| {t.name} | {t.metrics.get('事实幻觉出现率', '—')} "
                         f"| {t.metrics.get('逻辑错误率', '—')} | {t.vendor} |")
        lines += ["",
                  "> 标注「PPT 参考值」的列来自第三阶段汇报 Slide 10 的历史记录，"
                  "不是本次实测结果；配置对应 API Key 后可得到真实对比。", ""]

    if bundle.image_test.get("ok"):
        info = bundle.image_test
        lines += [
            "## 六、图片输入链路实测（v1.1.0 新增）",
            "",
            f"- 测试图片：`{info.get('image_name')}`（{info.get('image_bytes')} 字节）",
            f"- 调用模型：{info.get('provider')} / {info.get('model')}",
            f"- 是否走视觉：{'是' if info.get('vision') else '否'}　耗时：{info.get('elapsed_ms')} ms",
            f"- 结构完整度：{info.get('structure', 0):.2f}　"
            f"段落覆盖率：{info.get('coverage', 0):.0%}",
            "",
            "```text",
            (info.get("answer") or "").strip()[:2000],
            "```",
            "",
        ]

    path = outdir / "风险实证图解报告.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
