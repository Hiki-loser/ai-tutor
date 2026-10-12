"""Anthropic（Claude）原生协议提供方。

第三阶段报告中 Claude 3.5 Sonnet 作为"事实校验相对保守"的对照模型，
在本应用中被路由为「事实核查类任务」的首选提供方。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from .base import ChatResult, LLMError, LLMProvider, Message, ProviderConfigError, est_tokens


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = "claude-3-5-sonnet-latest", api_key: str = "",
                 base_url: str = "https://api.anthropic.com/v1", timeout: int = 60,
                 extra: Optional[Dict[str, Any]] = None, max_tokens_limit: int = 8192,
                 supports_vision: bool = True) -> None:
        super().__init__(model, api_key, base_url or "https://api.anthropic.com/v1", timeout, extra,
                         supports_vision=supports_vision)
        self.max_tokens_limit = max_tokens_limit

    def chat(
        self,
        messages: Sequence[Message],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_schema: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        stop: Optional[Sequence[str]] = None,
    ) -> ChatResult:
        if not self.api_key:
            raise ProviderConfigError("anthropic: 缺少 api_key")

        system_parts = [m.content for m in messages if m.role == "system"]
        conv = [{"role": m.role, "content": m.to_anthropic_content()}
                for m in messages if m.role != "system"]
        if not conv:
            conv = [{"role": "user", "content": "请开始。"}]

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": conv,
            "max_tokens": min(max_tokens, self.max_tokens_limit),
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if stop:
            payload["stop_sequences"] = list(stop)
        if tools and self.supports_tools:
            payload["tools"] = [
                {k: v for k, v in t.get("function", t).items() if k in ("name", "description", "input_schema")}
                for t in tools
            ]

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.extra.get("anthropic_version", "2023-06-01"),
        }
        headers.update(self.extra.get("headers", {}))

        t0 = time.perf_counter()
        data = self._post(f"{self.base_url}/messages", payload, headers)
        elapsed = int((time.perf_counter() - t0) * 1000)

        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        tool_use = [b for b in blocks if b.get("type") == "tool_use"]
        if not text and not tool_use:
            raise LLMError(f"anthropic: 返回中没有文本内容: {str(data)[:200]}")

        usage = data.get("usage") or {}
        prompt_text = "\n".join(m.content for m in messages)
        structured = None
        if json_schema:
            structured = self.extract_json(text)
            if structured is None and tool_use:
                structured = tool_use[0].get("input")

        return ChatResult(
            text=text,
            provider=self.name,
            model=data.get("model", self.model),
            elapsed_ms=elapsed,
            prompt_tokens=int(usage.get("input_tokens") or est_tokens(prompt_text)),
            completion_tokens=int(usage.get("output_tokens") or est_tokens(text)),
            finish_reason=data.get("stop_reason", ""),
            structured=structured,
            raw=data,
        )
