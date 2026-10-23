"""Explicit single-attempt vision port; no environment or business authority."""

import asyncio
import re
from dataclasses import dataclass

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.package_technical_features import JUDGMENT
from packages.domain.providers.deepseek import ProviderError
from packages.domain.providers.json_protocol import decode, identifier
from packages.domain.review_identity import canonical
from packages.domain.runtime import DomainError
from packages.model_governance import package_technical_vision as vision
from packages.model_governance.technical_png import digest_bytes

MAX_RESPONSE_BYTES = 1_048_576


class VisionProviderError(ProviderError):
    def __init__(self, code, *, raw_response=b"", raw_complete=False, request_id=None, usage=None):
        super().__init__(
            code,
            "图文服务未完整成功，未自动重试",
            billing_state="usage_reported" if usage is not None else "unknown",
            request_id=request_id,
            usage=usage,
        )
        self.raw_response = bytes(raw_response)
        self.raw_complete = raw_complete
        self.raw_response_digest = digest_bytes(self.raw_response)


@dataclass(frozen=True, repr=False)
class VisionGeneration:
    data: dict
    content: str
    usage: dict[str, int]
    request_id: str
    response_id: str
    model: str
    system_fingerprint: str | None
    raw_response: bytes
    raw_response_digest: str
    request_digest: str
    billing_state: str = "usage_reported"
    formal_scoring_eligible: bool = False


def parse_response(raw, request_id, request_digest):
    request_id = identifier(request_id)
    try:
        value = decode(raw)
        usage = value["usage"]
        if (
            not isinstance(usage, dict)
            or any(
                type(usage.get(k)) is not int or usage[k] < 0
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
            or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]
        ):
            raise ValueError("usage")
        usage = {key: count for key, count in usage.items() if type(count) is int and count >= 0}
        response_id = identifier(value["id"])
        request_id = request_id or response_id
        if (
            not response_id
            or not request_id
            or value["model"] != vision.profile()["expected_response_model"]
            or len(value["choices"]) != 1
        ):
            raise ValueError("identity")
        choice = value["choices"][0]
        message = choice["message"]
        content = message["content"]
        fingerprint = value.get("system_fingerprint")
        if (
            message["role"] != "assistant"
            or message.get("tool_calls")
            or not isinstance(content, str)
            or not content.strip()
            or (fingerprint is not None and identifier(fingerprint) != fingerprint)
        ):
            raise ValueError("message")
        finish = choice["finish_reason"]
    except (TypeError, ValueError, KeyError, IndexError, UnicodeError, RecursionError):
        raise VisionProviderError(
            "VISION_INVALID_RESPONSE", raw_response=raw, raw_complete=True, request_id=request_id
        ) from None
    if finish != "stop":
        raise VisionProviderError(
            "VISION_OUTPUT_INCOMPLETE",
            raw_response=raw,
            raw_complete=True,
            request_id=request_id,
            usage=usage,
        )
    try:
        data = decode(content)
        canonical(data)
        if not Draft202012Validator(JUDGMENT, format_checker=FormatChecker()).is_valid(data):
            raise ValueError("judgment")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise VisionProviderError(
            "VISION_OUTPUT_INVALID",
            raw_response=raw,
            raw_complete=True,
            request_id=request_id,
            usage=usage,
        ) from None
    return VisionGeneration(
        data=data,
        content=content,
        usage=usage,
        request_id=request_id,
        response_id=response_id,
        model=value["model"],
        system_fingerprint=fingerprint,
        raw_response=bytes(raw),
        raw_response_digest=digest_bytes(raw),
        request_digest=request_digest,
    )


class DeepSeekVisionClient:
    def __init__(self, *, api_key, total_timeout=60.0, transport=None):
        if not isinstance(api_key, str) or not re.fullmatch(r"[!-~]{1,1024}", api_key):
            raise DomainError("VISION_NOT_CONFIGURED", "尚未配置图文服务凭据", 503)
        if type(total_timeout) not in (int, float) or not 0 < total_timeout <= 120:
            raise DomainError("VISION_CONFIG_INVALID", "图文服务时限不合法", 503)
        self._api_key = api_key
        self._total_timeout = total_timeout
        self._transport = transport

    def generate(self, request, *, expected_request_digest, expected_profile_digest):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.generate_async(
                    request,
                    expected_request_digest=expected_request_digest,
                    expected_profile_digest=expected_profile_digest,
                )
            )
        raise DomainError("VISION_CALL_CONTEXT_INVALID", "异步环境请使用generate_async", 422)

    async def generate_async(self, request, *, expected_request_digest, expected_profile_digest):
        if (
            not isinstance(request, vision.PreparedVisionRequest)
            or not isinstance(request.body, bytes)
            or len(request.body) > vision.MAX_BODY_BYTES
            or digest_bytes(request.body) != expected_request_digest
            or expected_profile_digest != vision.profile_digest()
        ):
            raise DomainError("VISION_REQUEST_MISMATCH", "图文请求未绑定原预留与固定profile", 409)
        raw = bytearray()
        request_id = None
        try:
            async with asyncio.timeout(self._total_timeout):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(30, connect=5, write=10, pool=5),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    async with client.stream(
                        "POST",
                        vision.ENDPOINT,
                        content=request.body,
                        headers={
                            "Authorization": "Bearer " + self._api_key,
                            "Content-Type": "application/json",
                        },
                    ) as response:
                        request_id = identifier(response.headers.get("x-request-id")) or identifier(
                            response.headers.get("x-ds-request-id")
                        )
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            raw.extend(chunk)
                            if len(raw) > MAX_RESPONSE_BYTES:
                                raise VisionProviderError(
                                    "VISION_RESPONSE_TOO_LARGE",
                                    raw_response=raw[:MAX_RESPONSE_BYTES],
                                    request_id=request_id,
                                )
                        if response.status_code != 200:
                            raise VisionProviderError(
                                "VISION_HTTP_ERROR",
                                raw_response=raw,
                                raw_complete=True,
                                request_id=request_id,
                            )
        except (TimeoutError, httpx.TimeoutException):
            raise VisionProviderError(
                "VISION_TIMEOUT", raw_response=raw, request_id=request_id
            ) from None
        except httpx.RequestError:
            raise VisionProviderError(
                "VISION_NETWORK_ERROR", raw_response=raw, request_id=request_id
            ) from None
        return parse_response(bytes(raw), request_id, expected_request_digest)
