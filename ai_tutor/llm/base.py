"""LLM 提供方的抽象基类与统一数据结构。"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence


class LLMError(RuntimeError):
    """调用远端模型失败（网络、鉴权、限流、返回格式异常等）。"""


class ProviderConfigError(LLMError):
    """提供方缺少必要配置（如 API Key、模型名）。"""


@dataclass
class ImagePart:
    """一张待发送给模型的图片。

    支持两种来源：
      · 本地文件路径（由 `load()` 读取并按 MIME 类型编码为 base64 data URI）
      · 已是 base64 的数据（data URI 或纯 base64 字符串）
    """

    #: data URI，如 data:image/png;base64,xxxx
    data_uri: str = ""
    #: 原始文件名/来源说明（仅用于展示与日志）
    name: str = ""
    #: 图片 MIME 类型
    media_type: str = "image/png"
    #: 原始字节数
    size: int = 0
    #: 来源路径（若来自本地文件）
    path: str = ""

    #: 允许的图片类型（与 config.image.allowed_types 对应）
    ALLOWED = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "webp": "image/webp", "gif": "image/gif"}

    @classmethod
    def from_path(cls, path: str, max_bytes: int = 8 * 1024 * 1024) -> "ImagePart":
        import base64
        import mimetypes
        from pathlib import Path

        p = Path(path)
        if not p.exists() or not p.is_file():
            raise LLMError(f"图片文件不存在: {path}")
        data = p.read_bytes()
        if len(data) > max_bytes:
            raise LLMError(
                f"图片过大: {p.name} ({len(data) / 1048576:.1f} MB)，"
                f"上限 {max_bytes / 1048576:.1f} MB"
            )
        ext = p.suffix.lower().lstrip(".")
        media_type = cls.ALLOWED.get(ext)
        if not media_type:
            guessed = (mimetypes.guess_type(str(p))[0] or "").lower()
            if guessed.startswith("image/"):
                media_type = guessed
            else:
                raise LLMError(
                    f"不支持的图片格式: {p.suffix or '(无扩展名)'}，"
                    f"支持 {'/'.join(sorted(cls.ALLOWED))}"
                )
        return cls(
            data_uri=f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}",
            name=p.name, media_type=media_type, size=len(data), path=str(p),
        )

    @classmethod
    def from_base64(cls, b64: str, name: str = "pasted-image", media_type: str = "image/png",
                    max_bytes: int = 8 * 1024 * 1024) -> "ImagePart":
        import base64
        import binascii

        raw = (b64 or "").strip()
        # 允许直接传 data URI
        if raw.startswith("data:"):
            head, _, payload = raw.partition(",")
            media_type = head[5:].split(";")[0] or media_type
            raw = payload
        raw = "".join(raw.split())
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise LLMError(f"图片 base64 解码失败: {exc}") from exc
        if not data:
            raise LLMError("图片内容为空")
        if len(data) > max_bytes:
            raise LLMError(f"图片过大: {len(data) / 1048576:.1f} MB，上限 {max_bytes / 1048576:.1f} MB")
        if not media_type.startswith("image/"):
            media_type = "image/png"
        return cls(
            data_uri=f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}",
            name=name, media_type=media_type, size=len(data),
        )

    #: 纯 base64（含 data URI 的载荷部分）特征：只由 base64 字母表组成且足够长
    _B64_RE = re.compile(r"^[A-Za-z0-9+/\r\n\s]{64,}={0,2}$")

    @classmethod
    def coerce(cls, value: Any, max_bytes: int = 8 * 1024 * 1024) -> "ImagePart":
        """把多种输入统一成 ImagePart：ImagePart / 本地路径 / data URI / 纯 base64。"""
        if isinstance(value, ImagePart):
            return value
        if isinstance(value, dict):
            if value.get("path"):
                return cls.from_path(str(value["path"]), max_bytes)
            if value.get("base64") or value.get("data_uri"):
                return cls.from_base64(str(value.get("base64") or value.get("data_uri")),
                                       str(value.get("name") or "image"),
                                       str(value.get("media_type") or "image/png"), max_bytes)
            raise LLMError("无法识别的图片描述（需提供 path 或 base64）")
        text = str(value or "").strip()
        if not text:
            raise LLMError("图片内容为空")

        # 1) data URI 一定按 base64 处理
        if text.startswith("data:"):
            if not text.startswith("data:image/"):
                raise LLMError("仅支持图片类型的 data URI（data:image/...）")
            return cls.from_base64(text, "image", max_bytes=max_bytes)

        # 2) 明显的 base64 文本（长且只含 base64 字母表）
        if cls._B64_RE.match(text):
            return cls.from_base64(text, "image", max_bytes=max_bytes)

        # 3) 其余情况按本地文件路径处理——路径拼错时要给出明确报错，
        #    而不是把它当成 base64 去解码（否则会得到难以理解的错误）。
        from pathlib import Path

        candidate = Path(text)
        if candidate.exists():
            return cls.from_path(text, max_bytes)
        raise LLMError(
            f"找不到图片文件：{text}。"
            "如果这是 base64 内容，请确认它只包含 base64 字符；"
            "也可以直接传 data:image/... 形式的 data URI。"
        )

    def to_openai(self) -> Dict[str, Any]:
        return {"type": "image_url", "image_url": {"url": self.data_uri}}

    def to_anthropic(self) -> Dict[str, Any]:
        import base64

        payload = self.data_uri.split(",", 1)[-1]
        try:
            data = base64.b64decode(payload)
        except Exception:  # noqa: BLE001
            data = b""
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": self.media_type,
                       "data": base64.b64encode(data).decode("ascii")},
        }

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "media_type": self.media_type,
                "size": self.size, "path": self.path}


def coerce_images(values: Any, max_images: int = 4, max_bytes: int = 8 * 1024 * 1024) -> List[ImagePart]:
    """把任意形式的图片输入统一成 ImagePart 列表（带数量与大小校验）。"""
    if values is None:
        return []
    if isinstance(values, (str, bytes, ImagePart, dict)):
        values = [values]
    out: List[ImagePart] = []
    for item in values:
        if item in (None, ""):
            continue
        out.append(ImagePart.coerce(item, max_bytes))
    if len(out) > max_images:
        raise LLMError(f"一次最多支持 {max_images} 张图片，当前 {len(out)} 张")
    return out


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str
    images: List[ImagePart] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return bool(self.images)

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}

    def to_openai_content(self) -> Any:
        """OpenAI 兼容协议：纯文本时用字符串，含图片时用 content parts 数组。"""
        if not self.images:
            return self.content
        parts: List[Dict[str, Any]] = []
        if self.content:
            parts.append({"type": "text", "text": self.content})
        parts.extend(img.to_openai() for img in self.images)
        return parts

    def to_openai_message(self) -> Dict[str, Any]:
        return {"role": self.role, "content": self.to_openai_content()}

    def to_anthropic_content(self) -> Any:
        if not self.images:
            return self.content
        blocks: List[Dict[str, Any]] = []
        if self.content:
            blocks.append({"type": "text", "text": self.content})
        blocks.extend(img.to_anthropic() for img in self.images)
        return blocks


@dataclass
class ChatResult:
    """一次模型调用的完整结果与元信息。"""

    text: str
    provider: str
    model: str
    elapsed_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = ""
    degraded: bool = False          # 是否从远端降级到 mock
    degraded_reason: str = ""
    simulated: bool = False         # 是否为内置离线模拟输出
    raw: Dict[str, Any] = field(default_factory=dict)
    structured: Optional[Dict[str, Any]] = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def truncated(self) -> bool:
        """是否因 max_tokens 上限被截断（导致 JSON 不完整、段落缺失）。"""
        return self.finish_reason in ("length", "max_tokens", "max_output_tokens")

    def meta(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "elapsed_ms": self.elapsed_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "finish_reason": self.finish_reason,
            "truncated": self.truncated,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "simulated": self.simulated,
        }


def est_tokens(text: str) -> int:
    """粗略 token 估算：中文按 1 字 1 token，英文按 4 字符 1 token。"""
    if not text:
        return 0
    han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - han
    return int(han + other / 4) + 1


class LLMProvider:
    """所有提供方的基类。"""

    name = "base"
    requires_key = True
    supports_json_mode = True
    supports_tools = True
    #: 是否支持图片输入（多模态）
    supports_vision = False
    max_context = 32000

    def __init__(self, model: str, api_key: str = "", base_url: str = "",
                 timeout: int = 60, extra: Optional[Dict[str, Any]] = None,
                 supports_vision: bool = False) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self.extra = dict(extra or {})
        self.supports_vision = supports_vision

    # ---------------------------------------------------------------- 能力
    def available(self) -> bool:
        return (not self.requires_key) or bool(self.api_key)

    def describe(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "available": self.available(),
            "requires_key": self.requires_key,
            "supports_tools": self.supports_tools,
            "supports_vision": bool(self.supports_vision),
            "max_context": self.max_context,
        }

    # ---------------------------------------------------------------- 主入口
    def chat(
        self,
        messages: Sequence[Message],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_schema: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        stop: Optional[Sequence[str]] = None,
    ) -> ChatResult:
        raise NotImplementedError

    # ---------------------------------------------------------------- HTTP
    def _post(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:  # pragma: no cover - 依赖网络
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise LLMError(f"{self.name} HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - 依赖网络
            raise LLMError(f"{self.name} 网络错误: {exc.reason}") from exc
        except TimeoutError as exc:  # pragma: no cover
            raise LLMError(f"{self.name} 请求超时({self.timeout}s)") from exc
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self.name} 返回非 JSON: {data[:200]}") from exc

    # ---------------------------------------------------------------- 工具
    @staticmethod
    def extract_json(text: str) -> Optional[Dict[str, Any]]:
        """从模型输出中稳健地抽取 JSON 对象。

        兼容三类常见返回：
          1) 纯 JSON（可能带前导空白或 ```json 围栏）
          2) 正文在前、JSON 在后
          3) JSON 中字符串里出现花括号（如 LaTeX 的 {x^2}）——不能靠简单的括号计数，
             必须交给 JSONDecoder.raw_decode 按语法解析。
        """
        if not text:
            return None
        candidates: List[str] = []
        stripped = text.strip()
        candidates.append(stripped)

        # 去掉 Markdown 代码围栏
        if "```" in stripped:
            for part in stripped.split("```"):
                cand = part.strip()
                if cand.lower().startswith("json"):
                    cand = cand[4:].strip()
                if cand:
                    candidates.append(cand)

        decoder = json.JSONDecoder()
        for cand in candidates:
            try:
                data = json.loads(cand)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
            # 依次尝试每个 '{' 起点，用 raw_decode 按语法解析（能正确处理字符串内的花括号）
            for idx, ch in enumerate(cand):
                if ch != "{":
                    continue
                try:
                    data, _end = decoder.raw_decode(cand[idx:])
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    return data
        return None


def timed(fn: Callable[[], ChatResult]) -> ChatResult:
    t0 = time.perf_counter()
    result = fn()
    result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return result


def join_messages(messages: Iterable[Message]) -> str:
    return "\n".join(f"[{m.role}] {m.content}" for m in messages)
