"""开发辅助脚本：把 figures.py 里的 __import__ 写法替换成直接调用 TextBlock（一次性）。"""

import pathlib
import re

TARGET = pathlib.Path(__file__).resolve().parent.parent / "ai_tutor" / "report" / "figures.py"

PATTERN = re.compile(r'__import__\("ai_tutor\.report\.canvas",\s*fromlist=\["TextBlock"\]\)\.TextBlock')


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    new, n = PATTERN.subn("TextBlock", src)
    # 顺带删掉函数内多余的局部 import
    new = new.replace("        from .data import CASE_TITLES as _t  # noqa: F401  (保持可读性)\n", "")
    TARGET.write_text(new, encoding="utf-8")
    print(f"{TARGET.name}: 替换 {n} 处 __import__ 用法；剩余 {new.count('__import__')} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
