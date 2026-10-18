"""模型调用端口与 OpenAI 兼容适配器。

适配器保持很薄：一次调用 → 一个 JSON 对象；限流与 5xx 有限退避重试，仍失败则抛 ``Unavailable``（任务按暂时性故障重新排队）。
没有配置模型时 ``build_llm`` 返回 ``None``，处理器以 ``llm_not_configured`` 明确失败，而不是假装完成。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from bidwb.config import Settings
from bidwb.errors import Unavailable
from bidwb.logs import get_logger

log = get_logger(__name__)
M = TypeVar("M", bound=BaseModel)

RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})
MAX_HTTP_ATTEMPTS = 3
MAX_REPAIRS = 2  # TECH-001 §7：结构修复首批最多 2 次


class IncompleteGeneration(Exception):
    """模型多次未给出符合结构的输出。"""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.calls += other.calls


@dataclass(frozen=True)
class LlmResult:
    text: str
    usage: Usage


class LlmClient(Protocol):
    model: str

    def complete(self, *, system: str, user: str, max_tokens: int = 4096, temperature: float = 0.0) -> LlmResult:
        """返回模型的原始文本（期望是一个 JSON 对象）。默认温度 0：同一输入尽量得到同一输出；重复抽样时调用方显式升温。"""


class OpenAICompatClient:
    def __init__(self, settings: Settings) -> None:
        if not (settings.llm_base_url and settings.llm_model):
            msg = "未配置模型服务"
            raise ValueError(msg)
        self.model = settings.llm_model
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        self._http = httpx.Client(
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=settings.llm_timeout_seconds,
            headers={"Authorization": f"Bearer {key}"} if key else {},
        )

    def close(self) -> None:
        self._http.close()

    def complete(self, *, system: str, user: str, max_tokens: int = 4096, temperature: float = 0.0) -> LlmResult:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        last: Exception | None = None
        for attempt in range(MAX_HTTP_ATTEMPTS):
            try:
                response = self._http.post("/chat/completions", json=payload)
            except httpx.TransportError as exc:
                last = exc
            else:
                if response.status_code in RETRY_STATUS:
                    last = RuntimeError(f"http {response.status_code}")
                elif response.status_code >= 400:
                    log.error("llm_request_rejected", status=response.status_code)
                    raise Unavailable("provider_rejected", "模型服务拒绝了请求，请检查模型配置")
                else:
                    body = response.json()
                    usage = body.get("usage") or {}
                    text = body["choices"][0]["message"]["content"] or ""
                    return LlmResult(text, Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), 1))
            time.sleep(min(2**attempt, 8))
        log.warning("llm_unavailable", error=str(last))
        raise Unavailable("provider_timeout", "模型服务暂不可用，稍后将自动重试")


def build_llm(settings: Settings) -> LlmClient | None:
    if not (settings.llm_base_url and settings.llm_model):
        return None
    return OpenAICompatClient(settings)


def _extract_json(text: str) -> Any:
    """容忍模型在 JSON 外包一层 ```json 围栏。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    return json.loads(cleaned)


def call_validated(
    llm: LlmClient, model_cls: type[M], *, system: str, user: str, usage: Usage, max_tokens: int = 4096, temperature: float = 0.0
) -> M:
    """调用并按 ``model_cls`` 校验；不符合时带着错误位置要求模型重发，最多 ``MAX_REPAIRS`` 次。

    修复提示只包含字段路径与原因，不回传原始输出，避免把可能被污染的内容再喂回去。
    """
    prompt = user
    for attempt in range(MAX_REPAIRS + 1):
        result = llm.complete(system=system, user=prompt, max_tokens=max_tokens, temperature=temperature)
        usage.add(result.usage)
        try:
            return model_cls.model_validate(_extract_json(result.text))
        except (json.JSONDecodeError, ValidationError) as exc:
            reason = _describe(exc)
            log.warning("llm_output_invalid", attempt=attempt, reason=reason[:200])
            prompt = f"{user}\n\n【上一次输出不符合要求，原因：{reason}】请严格按规定的 JSON 结构重新输出。"
    raise IncompleteGeneration("模型输出多次不符合结构")


def _describe(exc: json.JSONDecodeError | ValidationError) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "不是合法的 JSON"
    return "；".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
