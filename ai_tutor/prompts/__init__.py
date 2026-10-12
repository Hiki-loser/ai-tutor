"""提示词库：六大模块的精细提示模板（应用对外只使用精细提示）。"""

from .schema import FIVE_ELEMENTS, STRUCTURE_PATTERNS, ModuleSpec
from .modules import (
    COMMON_REDLINES,
    COMMON_UNCERTAINTY,
    MODULE_KEYWORDS,
    MODULES,
    detect_module,
    get_module,
    list_modules,
    prompt_library_markdown,
)

__all__ = [
    "ModuleSpec",
    "FIVE_ELEMENTS",
    "STRUCTURE_PATTERNS",
    "MODULES",
    "MODULE_KEYWORDS",
    "COMMON_REDLINES",
    "COMMON_UNCERTAINTY",
    "get_module",
    "list_modules",
    "detect_module",
    "prompt_library_markdown",
]
