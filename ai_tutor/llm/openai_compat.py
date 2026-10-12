"""OpenAI 兼容协议提供方。

一次实现覆盖：OpenAI、DeepSeek、阿里通义(DashScope 兼容模式)、智谱 GLM、
月之暗面 Kimi、硅基流动、以及本地 Ollama / vLLM / LM Studio 等自建服务。
只需在配置里改 base_url 与 model。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from .base import ChatResult, LLMError, LLMProvider, Message, ProviderConfigError, est_tokens


class OpenAICompatProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str, api_key: str = "", base_url: str = "https://api.openai.com/v1",
                 timeout: int = 60, extra: Optional[Dict[str, Any]] = None, provider_name: str = "openai",
                 supports_vision: bool = False) -> None:
        super().__init__(model, api_key, base_url or "https://api.openai.com/v1", timeout, extra,
                         supports_vision=supports_vision)
        self.name = provider_name

    def chat(
        self,
        messages: Sequence[Message],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_schema: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        stop: Optional[Sequence[str]] = None,
    ) -> ChatResult:
        if not self.base_url:
            raise ProviderConfigError(f"{self.name}: 缺少 base_url")
        url = f"{self.base_url}/chat/completions"
        # 含图片时使用 content parts；纯文本仍用字符串（兼容性最好）
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai_message() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema and self.supports_json_mode:
            # 注意：部分提供方（实测 DeepSeek）在使用 response_format=json_object 时
            # 要求提示词中必须出现 "json" 字样，否则直接返回 400。
            # 这里做前置判断，宁可不启用 JSON 模式，也不让整次调用失败。
            if "json" in "\n".join(m.content for m in messages).lower():
                payload["response_format"] = {"type": "json_object"}
        if tools and self.supports_tools:
            payload["tools"] = tools
        if stop:
            payload["stop"] = list(stop)

        headers = {"Authorization": f"Bearer {self.api_key}"}
        headers.update(self.extra.get("headers", {}))

        t0 = time.perf_counter()
        data = self._post(url, payload, headers)
        elapsed = int((time.perf_counter() - t0) * 1000)

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"{self.name}: 返回中没有 choices 字段: {str(data)[:200]}")
        choice = choices[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        usage = data.get("usage") or {}
        prompt_text = "\n".join(m.content for m in messages)

        structured = None
        if json_schema:
            structured = self.extract_json(text)
            if structured is None and tool_calls:
                args = (tool_calls[0].get("function") or {}).get("arguments") or ""
                structured = self.extract_json(args)

        # 注意：部分模型（实测 DeepSeek 在 JSON 模式下）会在正文前返回大量空白字符，
        # 直接使用会导致长度统计、相似度与质检全部失真，因此统一剥除首尾空白。
        text = (text or "").strip()
        if not text and tool_calls:
            text = tool_calls[0]["function"]["arguments"]

        return ChatResult(
            text=text,
            provider=self.name,
            model=data.get("model", self.model),
            elapsed_ms=elapsed,
            prompt_tokens=int(usage.get("prompt_tokens") or est_tokens(prompt_text)),
            completion_tokens=int(usage.get("completion_tokens") or est_tokens(text)),
            finish_reason=choice.get("finish_reason", ""),
            structured=structured,
            raw=data,
        )
