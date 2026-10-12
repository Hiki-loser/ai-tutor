"""开发辅助脚本：从离线模型 mock.py 中移除粗放提示相关实现（一次性使用）。

保留原因：记录本次重构的机械替换方式，便于复核改动是否完整。
"""

import pathlib
import re

TARGET = pathlib.Path(__file__).resolve().parent.parent / "ai_tutor" / "llm" / "mock.py"

# (模式, 替换文本, flags) —— 按顺序执行
RULES = [
    (r"_COARSE_MARK = .*?\n_FINE_MARK = .*?\n", "", 0),
    (r"def _detect_mode\(prompt: str\) -> str:.*?\n\n\n", "", re.S),
    (r"def _coarse_text\(module: str, q: str\) -> str:.*?\n\n\ndef ", "def ", re.S),
    (r"def _definition_coarse\(q: str\) -> Optional\[str\]:.*?\n\n\n", "", re.S),
    (r"def _plan_coarse\(q: str\) -> str:.*?\n\n\n", "", re.S),
    (r"def _oral_coarse\(q: str\) -> str:.*?\n\n\n", "", re.S),
    (r"def _hallucinate\(case: str, q: str\) -> str:.*?\n\n\n", "", re.S),
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
