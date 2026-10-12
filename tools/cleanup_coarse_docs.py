"""开发辅助脚本：批量清理各处的"粗放提示/模式切换"残留（一次性使用）。"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 文件 -> [(旧文本, 新文本), ...]
EDITS = {
    "ai_tutor/prompts/__init__.py": [
        ('"""提示词库：六大模块 × （粗放 / 精细）两版模板。"""',
         '"""提示词库：六大模块的精细提示模板（应用对外只使用精细提示）。"""'),
    ],
    "ai_tutor/features/qa.py": [
        ("""                f"> 由「知识框架生成 M2」于 {result.meta.get('model', '')} 生成，"
                f"提示模式：{'精细提示' if result.mode == 'fine' else '粗放提示'}\\n\\n\"""",
         """                f"> 由「知识框架生成 M2」使用 {result.meta.get('model', '')} 生成，"
                f"提示模板：精细提示（含考点星级与超纲标注）\\n\\n\""""),
    ],
    "ai_tutor/__init__.py": [
        ("阶段二：六大功能模块 + 提示词库（粗放 / 精细对照）",
         "阶段二：六大功能模块 + 精细提示词库"),
        ("阶段三：四类专项风险实证 + 多工具横向对比",
         "阶段三：四类专项风险实证 + 多工具横向对比 + 图片输入"),
    ],
    "ai_tutor/deliverables.py": [
        ('"- 提示词设置：每组用例均对比「粗放提示」与「精细提示」两版输出",',
         '"- 提示词设置：同一用例分别用「精细提示」与「无约束提示」各跑一次（消融对照）",'),
    ],
}


def main() -> int:
    total = 0
    for rel, pairs in EDITS.items():
        path = ROOT / rel
        if not path.exists():
            print(f"跳过（不存在）: {rel}")
            continue
        src = path.read_text(encoding="utf-8")
        for old, new in pairs:
            if old in src:
                src = src.replace(old, new)
                total += 1
                print(f"OK   {rel}: {old.strip()[:52]}")
            else:
                print(f"MISS {rel}: {old.strip()[:52]}")
        path.write_text(src, encoding="utf-8")
    print(f"共替换 {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
