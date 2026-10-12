"""统一的 API 调用层。

设计目标（对应第三阶段"多工具横向对比"与"工具路由"建议）：
- 同一套接口适配 OpenAI 兼容协议（OpenAI / DeepSeek / 通义 / 智谱 / Ollama / vLLM）、
  Anthropic 官方协议、百度千帆（文心一言）。
- 任何远端失败都可回退到内置离线 Mock 模型，保证应用永远可用、可复现。
- 统一返回 ChatResult，携带 provider / model / 耗时 / token / 是否降级 等元信息，
  这些元信息会被写入 SQLite 与测试记录，满足"完整保留提示词原文与输出原文"的要求。
"""

from .base import LLMError, LLMProvider, ChatResult, Message, ProviderConfigError
from .openai_compat import OpenAICompatProvider
from .anthropic import AnthropicProvider
from .qianfan import QianfanProvider
from .mock import MockProvider
from .registry import LLMClient, get_client, get_default_client, list_models
from .router import TaskRouter, ROUTING_TABLE

__all__ = [
    "LLMError",
    "LLMProvider",
    "ChatResult",
    "Message",
    "ProviderConfigError",
    "OpenAICompatProvider",
    "AnthropicProvider",
    "QianfanProvider",
    "MockProvider",
    "LLMClient",
    "get_client",
    "get_default_client",
    "list_models",
    "TaskRouter",
    "ROUTING_TABLE",
]
