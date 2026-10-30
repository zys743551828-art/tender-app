"""DeepSeek单次生成端口。没有业务资格授予、自动修复或隐式付费重试。"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from referencing.exceptions import Unresolvable

from packages.domain.errors import DomainError
from packages.domain.providers.errors import ProviderError
from packages.domain.providers.generation import Generation, GenerationConfig
from packages.domain.providers.json_protocol import decode as _decode
from packages.domain.providers.json_protocol import identifier as _identifier
from packages.domain.providers.json_protocol import schema_check as _schema_check

ENDPOINTS = {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
MODELS = {"deepseek-flash", "deepseek-v4-pro"}
# Historical frozen-method policy exports; generation transport does not use
# these sets as a model capability or qualification registry.
MAX_RESPONSE_BYTES = 1_048_576


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key,
        model="deepseek-flash",
        base_url="https://api.deepseek.com/v1",
        total_timeout=45.0,
        transport=None,
    ):
        if not isinstance(api_key, str) or not api_key.strip():
            raise DomainError("MODEL_NOT_CONFIGURED", "尚未配置DeepSeek凭据", 503)
        self.config = GenerationConfig(model=model, base_url=base_url)
        if type(total_timeout) not in (int, float) or not 0 < total_timeout <= 120:
            raise DomainError("MODEL_CONFIG_INVALID", "模型调用总时限不合法", 503)
        self._api_key = api_key
        self.total_timeout, self._transport = total_timeout, transport

    @property
    def model(self):
        return self.config.model

    @property
    def base_url(self):
        return self.config.base_url

    @classmethod
    def from_env(cls):
        from packages.domain.providers.factory import require_supported

        config = GenerationConfig.from_mapping(os.environ)
        require_supported(config)
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            model=config.model,
            base_url=config.base_url,
        )

    def generate(self, *, messages, max_tokens=256, json_schema=None, temperature=0):
        """同步CLI入口；异步服务应await generate_async，不能阻塞其事件循环。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.generate_async(
                    messages=messages,
                    max_tokens=max_tokens,
                    json_schema=json_schema,
                    temperature=temperature,
                )
            )
        raise DomainError("MODEL_CALL_CONTEXT_INVALID", "异步环境请使用generate_async", 422)

    async def generate_async(self, *, messages, max_tokens=256, json_schema=None, temperature=0):
        if (
            type(max_tokens) is not int
            or not 1 <= max_tokens <= 8192
            or type(temperature) not in (int, float)
            or not 0 <= temperature <= 2
        ):
            raise DomainError("MODEL_REQUEST_INVALID", "生成长度或温度不合法", 422)
        if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
            raise DomainError("MODEL_REQUEST_INVALID", "生成消息不合法", 422)
        prepared = []
        for message in messages:
            if (
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] not in ("system", "user", "assistant")
                or not isinstance(message["content"], str)
                or not message["content"].strip()
            ):
                raise DomainError("MODEL_REQUEST_INVALID", "生成消息字段不合法", 422)
            prepared.append(dict(message))
        if sum(len(m["content"]) for m in prepared) > 262144:
            raise DomainError("MODEL_REQUEST_INVALID", "生成输入超过本端口限制", 413)
        payload = {
            "model": self.model,
            "messages": prepared,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        if json_schema is not None:
            _schema_check(json_schema)
            schema_text = json.dumps(json_schema, ensure_ascii=False)
            if len(schema_text) > 65536:
                raise DomainError("MODEL_REQUEST_INVALID", "输出Schema过大", 422)
            payload["messages"] = [
                {
                    "role": "system",
                    "content": "Return only one valid JSON object satisfying this JSON Schema: "
                    + schema_text,
                }
            ] + prepared
            payload["response_format"] = {"type": "json_object"}
        request_id = None
        try:
            # asyncio总deadline覆盖连接、上传、慢速逐块响应和整个响应读取。
            async with asyncio.timeout(self.total_timeout):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(30, connect=5, write=10, pool=5),
                    follow_redirects=False,
                    trust_env=True,
                ) as client:
                    async with client.stream(
                        "POST",
                        self.base_url + "/chat/completions",
                        headers={
                            "Authorization": "Bearer " + self._api_key,
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    ) as response:
                        request_id = _identifier(
                            response.headers.get("x-request-id")
                        ) or _identifier(response.headers.get("x-ds-request-id"))
                        if response.status_code != 200:
                            codes = {
                                401: "MODEL_AUTH_FAILED",
                                403: "MODEL_ACCESS_DENIED",
                                429: "MODEL_RATE_LIMITED",
                            }
                            raise ProviderError(
                                codes.get(response.status_code, "MODEL_HTTP_ERROR"),
                                "模型服务未成功返回，未自动重试",
                                request_id=request_id,
                            )
                        raw = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            raw.extend(chunk)
                            if len(raw) > MAX_RESPONSE_BYTES:
                                raise ProviderError(
                                    "MODEL_RESPONSE_TOO_LARGE",
                                    "模型响应超出限制",
                                    request_id=request_id,
                                )
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderError(
                "MODEL_TIMEOUT", "模型调用超时，计费结果未知，未自动重试", request_id=request_id
            ) from None
        except httpx.RequestError:
            raise ProviderError(
                "MODEL_NETWORK_ERROR",
                "模型连接失败，计费结果未知，未自动重试",
                request_id=request_id,
            ) from None
        try:
            envelope = _decode(raw)
            if not isinstance(envelope, dict):
                raise ValueError("envelope")
            usage = envelope["usage"]
            if (
                not isinstance(usage, dict)
                or any(
                    type(usage.get(k)) is not int or usage[k] < 0
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                )
                or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]
            ):
                raise ValueError("usage")
            usage = {k: v for k, v in usage.items() if type(v) is int and v >= 0}
            response_id = _identifier(envelope["id"])
            request_id = request_id or response_id
            choices = envelope["choices"]
            if (
                not response_id
                or not request_id
                or envelope.get("model") != self.model
                or not isinstance(choices, list)
                or len(choices) != 1
            ):
                raise ValueError("identity")
            choice = choices[0]
            content = choice["message"]["content"]
            if (
                choice["message"].get("role") != "assistant"
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError("content")
            finish = choice["finish_reason"]
        except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
            raise ProviderError(
                "MODEL_INVALID_RESPONSE", "模型响应结构或usage不合法", request_id=request_id
            ) from None
        if finish != "stop":
            raise ProviderError(
                "MODEL_OUTPUT_INCOMPLETE",
                "模型输出未完整结束",
                billing_state="usage_reported",
                request_id=request_id,
                usage=usage,
            )
        data = None
        if json_schema is not None:
            try:
                data = _decode(content)
                if not isinstance(data, dict) or not Draft202012Validator(
                    json_schema, format_checker=FormatChecker()
                ).is_valid(data):
                    raise ValueError("schema")
            except (ValueError, TypeError, RecursionError, Unresolvable):
                raise ProviderError(
                    "MODEL_OUTPUT_INVALID",
                    "模型JSON输出不符合Schema",
                    billing_state="usage_reported",
                    request_id=request_id,
                    usage=usage,
                ) from None
        return Generation(
            content=content,
            data=data,
            usage=usage,
            request_id=request_id,
            response_id=response_id,
            model=self.model,
            finish_reason=finish,
        )
