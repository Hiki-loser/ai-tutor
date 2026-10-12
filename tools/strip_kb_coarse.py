"""开发辅助脚本：从知识库 kb.py 中移除粗放提示示例（一次性使用）。

保留原因：记录本次重构的机械替换方式，便于复核改动是否完整。
"""

import pathlib
import re

TARGET = pathlib.Path(__file__).resolve().parent.parent / "ai_tutor" / "llm" / "kb.py"

RULES = [
    # 三个粗放示例常量
    (r'LIMIT_COARSE = """.*?"""\n\n', "", re.S),
    (r'TCP_COARSE = """.*?"""\n\n', "", re.S),
    (r'RECURSION_COARSE = """.*?"""\n\n', "", re.S),
    # 定义库里的 coarse 字段
    (r', "coarse": RECURSION_COARSE', "", 0),
    # LOGIC_COARSE 字典整体
    (r"LOGIC_COARSE: Dict\[str, str\] = \{.*?\n\}\n\n", "", re.S),
]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    before = len(re.findall(r"coarse|粗放", src))
    for pattern, repl, flags in RULES:
        src = re.sub(pattern, repl, src, flags=flags)
    TARGET.write_text(src, encoding="utf-8")
    after = len(re.findall(r"coarse|粗放", src))
    print(f"{TARGET.name}: 粗放相关引用 {before} -> {after}")
    for i, line in enumerate(src.splitlines(), 1):
        if "coarse" in line or "粗放" in line:
            print(f"  剩余 L{i}: {line.strip()[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
