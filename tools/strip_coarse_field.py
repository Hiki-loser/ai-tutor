"""开发辅助脚本：批量移除源码中的粗放提示词字段（一次性使用）。

保留原因：记录本次重构的机械替换方式，便于复核改动是否完整。
"""

import re
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 粗放提示字段：coarse_prompt="..." 或 coarse_prompt='...'（允许跨行）
FIELD_RE = re.compile(
    r'(?ms)^[ \t]*coarse_prompt\s*=\s*(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*,\s*\n'
)


def strip_field(path: pathlib.Path) -> int:
    src = path.read_text(encoding="utf-8")
    new, count = FIELD_RE.subn("", src)
    if count:
        path.write_text(new, encoding="utf-8")
    return count


def main() -> int:
    targets = sys.argv[1:] or ["ai_tutor/prompts/modules.py"]
    total = 0
    for rel in targets:
        path = ROOT / rel
        if not path.exists():
            print(f"跳过（不存在）: {rel}")
            continue
        n = strip_field(path)
        total += n
        print(f"{rel}: 移除 {n} 处")
    print(f"合计 {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
