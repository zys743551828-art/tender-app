"""Explicit /3 single-attempt transport, with shared pure config/response codec.

The operator supplies credentials. No environment discovery, job admission,
native binding verification, billing reconciliation or automatic retry occurs.
"""

import asyncio

import httpx

from packages.domain.errors import DomainError
from packages.domain.providers.deepseek_vision import (
    MAX_RESPONSE_BYTES,
    DeepSeekVisionClient,
    VisionProviderError,
    parse_response,
)
from packages.domain.providers.json_protocol import identifier
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance.package_technical_material import MaterialInputError


class DeepSeekCompleteVisionClient(DeepSeekVisionClient):
    def generate(self, request, *, expected_request_digest, expected_profile_digest):
        running = False
        try:
            asyncio.get_running_loop()
            running = True
        except RuntimeError:
            pass
        if running:
            raise DomainError(
                "COMPLETE_VISION_CALL_CONTEXT_INVALID", "异步环境请使用generate_async", 422
            )
        return asyncio.run(
            self.generate_async(
                request,
                expected_request_digest=expected_request_digest,
                expected_profile_digest=expected_profile_digest,
            )
        )

    async def generate_async(self, request, *, expected_request_digest, expected_profile_digest):
        invalid = False
        try:
            vision.validate_request(request, expected_request_digest, expected_profile_digest)
        except MaterialInputError:
            invalid = True
        if invalid:
            raise DomainError(
                "COMPLETE_VISION_REQUEST_MISMATCH", "完整图文请求与固定输入不匹配", 409
            )
        raw = bytearray()
        request_id = None
        failure = None
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
                        vision.profile()["endpoint"],
                        content=request.body,
                        headers={
                            "Authorization": "Bearer " + self._api_key,
                            "Content-Type": "application/json",
                            "Accept-Encoding": "identity",
                        },
                    ) as response:
                        request_id = identifier(response.headers.get("x-request-id")) or identifier(
                            response.headers.get("x-ds-request-id")
                        )
                        if response.headers.get("content-encoding", "").lower() not in (
                            "",
                            "identity",
                        ):
                            raise VisionProviderError(
                                "COMPLETE_VISION_ENCODING_REJECTED", request_id=request_id
                            )
                        async for chunk in response.aiter_raw(chunk_size=8192):
                            raw.extend(chunk)
                            if len(raw) > MAX_RESPONSE_BYTES:
                                raise VisionProviderError(
                                    "COMPLETE_VISION_RESPONSE_TOO_LARGE",
                                    raw_response=raw[:MAX_RESPONSE_BYTES],
                                    request_id=request_id,
                                )
                        if response.status_code != 200:
                            raise VisionProviderError(
                                "COMPLETE_VISION_HTTP_ERROR",
                                raw_response=raw,
                                raw_complete=True,
                                request_id=request_id,
                            )
        except (TimeoutError, httpx.TimeoutException):
            failure = "COMPLETE_VISION_TIMEOUT"
        except (httpx.RequestError, httpx.StreamError):
            failure = "COMPLETE_VISION_NETWORK_ERROR"
        if failure:
            raise VisionProviderError(failure, raw_response=raw, request_id=request_id)
        return parse_response(bytes(raw), request_id, expected_request_digest)
