"""百度千帆 / 文心一言提供方。

第三阶段报告中"文心一言 4.0"作为国产对照模型，其特点是"中文表达最自然，
但事实幻觉率偏高"，因此在工具路由中仅用于「中文口语化讲解」类任务。

鉴权流程：api_key + secret_key → access_token（有效期 30 天，本地缓存 25 天）。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlencode

from .base import ChatResult, LLMError, LLMProvider, Message, ProviderConfigError, est_tokens

_OAUTH_URL = "https://aip.baidubce.com/oauth/2.0/token"
_CHAT_URL = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat"


class QianfanProvider(LLMProvider):
    name = "qianfan"

    def __init__(self, model: str = "ernie-4.0-8k", api_key: str = "", secret_key: str = "",
                 base_url: str = "", timeout: int = 60, extra: Optional[Dict[str, Any]] = None,
                 endpoints: Optional[Dict[str, str]] = None) -> None:
        super().__init__(model, api_key, base_url, timeout, extra)
        self.secret_key = secret_key
        self.access_token = ""
        self.token_expire_at = 0.0
        self.endpoints = dict(endpoints or {})

    def available(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def _get_token(self) -> str:
        if self.access_token and time.time() < self.token_expire_at:
            return self.access_token
        if not (self.api_key and self.secret_key):
            raise ProviderConfigError("qianfan: 缺少 api_key / secret_key")
        url = f"{_OAUTH_URL}?{urlencode({'grant_type': 'client_credentials', 'client_id': self.api_key, 'client_secret': self.secret_key})}"
        data = self._post(url, {}, {})
        token = data.get("access_token")
        if not token:
            raise LLMError(f"qianfan: 获取 access_token 失败: {str(data)[:200]}")
        self.access_token = token
        self.token_expire_at = time.time() + int(data.get("expires_in", 2592000)) - 432000
        return token

    def _endpoint(self) -> str:
        if self.model in self.endpoints:
            return self.endpoints[self.model]
        return f"{_CHAT_URL}/{self.model}"

    def chat(
        self,
        messages: Sequence[Message],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_schema: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        stop: Optional[Sequence[str]] = None,
    ) -> ChatResult:
        token = self._get_token()
        system_parts = [m.content for m in messages if m.role == "system"]
        conv = [m.to_dict() for m in messages if m.role in ("user", "assistant")]
        payload: Dict[str, Any] = {
            "messages": conv,
            "temperature": max(0.01, temperature),
            "max_output_tokens": max_tokens,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if json_schema:
            payload["response_format"] = "json_object"
        if stop:
            payload["stop"] = list(stop)

        url = f"{self._endpoint()}?access_token={token}"
        t0 = time.perf_counter()
        data = self._post(url, payload, {})
        elapsed = int((time.perf_counter() - t0) * 1000)

        if data.get("error_code"):
            raise LLMError(f"qianfan: {data.get('error_code')} {data.get('error_msg')}")
        text = (data.get("result") or "").strip()
        usage = data.get("usage") or {}
        prompt_text = "\n".join(m.content for m in messages)
        return ChatResult(
            text=text,
            provider=self.name,
            model=self.model,
            elapsed_ms=elapsed,
            prompt_tokens=int(usage.get("prompt_tokens") or est_tokens(prompt_text)),
            completion_tokens=int(usage.get("completion_tokens") or est_tokens(text)),
            finish_reason=data.get("finish_reason", ""),
            structured=self.extract_json(text) if json_schema else None,
            raw=data,
        )
