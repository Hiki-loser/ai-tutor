"""开发辅助脚本：把文档中的"粗放提示"相关表述改为 v1.1.0 的口径（一次性使用）。

替换原则：
  · 应用对外只有精细提示 → 文档不再把它描述成"可切换的模式"
  · 原"粗放 vs 精细 对照" → 评测层的"提示词消融对照（精细 vs 无约束）"
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

EDITS = {
    "docs/使用说明.md": [
        ("会依次验证 36 项：提示词库完整性 → 六大模块输出合规 → 粗放/精细对照 →",
         "会依次验证 44 项：提示词库完整性 → 六大模块输出合规 → 提示词一致性 →"),
        ("| 提示词库 | 五要素方法论、六种结构模式、每模块粗放/精细提示原文 |",
         "| 提示词库 | 五要素方法论、六种结构模式、每模块的精细提示原文 |"),
        ("4. [做对照实验（阶段二）](#4-做对照实验阶段二)",
         "4. [图片输入](#4-图片输入)"),
        ("## 4. 做对照实验（阶段二）\n\n同题分别用粗放提示与精细提示各跑一次，自动算出量化差异：\n\n```powershell\npython -m ai_tutor compare \"帮我整理一下 TCP 协议的知识点\"\n```",
         "## 4. 图片输入\n\n题目照片、截图、手写演算都可以直接传给助手，程序会自动选用支持视觉的模型\n（当前为 `deepseek-flash`）识别图片内容，再按模块要求解析。\n\n```powershell\n# 单张\npython -m ai_tutor ask \"识别图片里的题目并按模块解析\" -i 题目.png\n\n# 多张（例如题目 + 自己的演算过程）\npython -m ai_tutor ask \"看看我的演算错在哪\" -i 演算.jpg -i 题目.png\n\n# 目录 / 通配符\npython -m ai_tutor ask \"批改这些题\" -i shots\\\npython -m ai_tutor ask \"批改这些题\" -i \"题目*.png\"\n```\n\nWeb 界面支持**点击选择、拖拽到虚线框、Ctrl+V 直接粘贴截图**（最多 4 张，单张 ≤ 8 MB）。\n\n限制可在 `config.json` 的 `image` 段调整：\n\n```json\n\"image\": { \"enabled\": true, \"max_images\": 4, \"max_bytes\": 8388608,\n           \"allowed_types\": [\"png\", \"jpg\", \"jpeg\", \"webp\", \"gif\"] }\n```\n\n> 识别不清的地方（模糊、缺角、笔迹难辨）会被明确写进【不确定标注】，\n> **不会**凭猜测补全题目条件——这是提示词里的硬性契约。"),
        ("# {\"question\": \"帮我整理一下 TCP 协议的知识点\", \"module\": \"M2\", \"mode\": \"coarse\"}",
         "# {\"question\": \"帮我整理一下 TCP 协议的知识点\", \"module\": \"M2\"}\n# {\"question\": \"识别图片里的题目\", \"module\": \"M1\", \"image\": \"D:/题.png\"}"),
        ("python -m ai_tutor risk run --kind pair                    # 事实幻觉 + 逻辑缺陷 对照",
         "python -m ai_tutor risk run --kind pair                    # 事实幻觉 + 逻辑缺陷（含消融对照）"),
        ("| `deliverables/提示词库.md` | 方法论 + 六种结构模式 + 六大模块粗放/精细提示原文（Markdown） |",
         "| `deliverables/提示词库.md` | 方法论 + 六种结构模式 + 六大模块精细提示原文（Markdown） |"),
        ("python -m ai_tutor prompt show M1 --mode both", "python -m ai_tutor prompt show M1"),
        ("# ③ 看对照实验\npython -m ai_tutor compare \"帮我整理一下 TCP 协议的知识点\"",
         "# ③ 图片输入（真实视觉模型）\npython -m ai_tutor ask \"识别图片里的题目\" -i tests\\fixtures\\题目样例.png"),
        (":mode            切换 精细/粗放 提示", ":image <路径>    附加图片（可多张，:clear 清空）"),
    ],
    "docs/架构说明.md": [
        ("│                ── 统一 ask / compare / run_risk / report / export      │",
         "│                ── 统一 ask / ablate / run_risk / report / export       │"),
        ("| 要素 | 粗放提示（基线） | 精细提示（生产） |\n| --- | --- | --- |\n| 角色设定 | 无角色 | \"你是一位大学课程助教\"，锁定语气与专业度 |\n| 输出格式 | 无格式要求 | 编号段落 + 表格模板，保证结构可复用 |\n| 质量约束 | 无约束 | \"禁止跳步\"\"必须交叉验证\" |\n| 不确定标记 | 无此意识 | 要求标注\"超纲\"\"有争议\"\"信息不足\" |\n| 受众适配 | 深度随机 | \"大二学生，已学完课程\" |",
         "| 要素 | 做法 |\n| --- | --- |\n| 角色设定 | \"你是一位大学课程助教\"，锁定语气与专业度 |\n| 输出格式 | 编号段落 + 表格模板，保证结构可复用 |\n| 质量约束 | \"禁止跳步\"\"必须交叉验证\" |\n| 不确定标记 | 要求标注\"超纲\"\"有争议\"\"信息不足\" |\n| 受众适配 | \"大二学生，已学完课程\" |"),
        ("`【精细提示】` / `【粗放提示】` 标记由 `BaseFeature.build_prompt()` 注入，\n既是给真实模型的模式提示，也是离线模型识别模式的依据——两处共用同一标记，避免不一致。",
         "`BaseFeature.build_prompt()` 固定注入**输出契约**（必须出现哪些【段落名】、\n先正文后 JSON、禁止只输出 JSON），并放在提示词末位——实测这样能显著提高真实模型的\n格式遵守率。应用对外**没有**提示词模式开关。"),
        ("读提示词 → 识别【粗放提示】/【精细提示】标记 + 模块编号 + 话题\n   ├─ 粗放（基线模式）→ 结构随意、跳步、编造 DOI/政策条文/页码、单一归因、不标不确定性\n   └─ 精细（生产模式）→ 按模块要求的分段标题输出，含交叉验证、易错点、超纲标注\n                       遇到幻觉/逻辑陷阱题时，输出\"拒绝编造 + 明确声明无法确认\"",
         "读提示词 → 识别模块编号 + 话题 + 是否带图片\n   ├─ 按模块的分段契约输出：固定段落标题、交叉验证、易错点、超纲标注\n   ├─ 遇到幻觉/逻辑陷阱题 → \"拒绝编造 + 明确声明无法确认\"\n   └─ 带图片时 → 如实说明已接收的图片并拒绝推断图片内容（不编造）"),
        ("价值：把阶段二/三的对照实验流程与量化口径做成**可自动运行、可复现**的流水线。",
         "价值：让整套流程在没有 Key、没有网络时也能**自动运行、结果可复现**。"),
        ("3. 粗放输出碰巧用词与合规信号相同（如\"现行\"）→ 误判为合规",
         "3. 无约束输出碰巧用词与合规信号相同（如\"现行\"）→ 误判为合规"),
        ("2. 在 `prompts/modules.py` 定义 `ModuleSpec`（角色/任务/受众/粗放提示/结构模式/红线）",
         "2. 在 `prompts/modules.py` 定义 `ModuleSpec`（角色/任务/受众/结构模式/红线）"),
        ("即可自动进入对照测试、多工具对比与用例集导出。",
         "即可自动进入消融对照测试、多工具对比与用例集导出。"),
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
                print(f"OK   {rel}: {old.splitlines()[0][:50]}")
            else:
                print(f"MISS {rel}: {old.splitlines()[0][:50]}")
        path.write_text(src, encoding="utf-8")
    print(f"共替换 {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
