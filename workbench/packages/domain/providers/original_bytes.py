"""Bounded private GET transport supplied by an existing authorized controller.

No DB, credential discovery, URL signer, permission registration or business
configuration. A matching object digest proves bytes, not input authority.
"""

import asyncio
import hashlib
import logging
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import NoReturn
from uuid import UUID

import httpx

from packages.domain import review_identity
from packages.domain.review_identity import canonical, digest

MAX_BYTES = 32 * 1024 * 1024
MAX_URL_BYTES = 8192
MAX_DEADLINE = 30
CHUNK = 65536
OSS_ORIGIN = "https://tender-base.oss-cn-hangzhou.aliyuncs.com"


class OriginalReadError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise OriginalReadError("ORIGINAL_READ_" + code)


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, repr=False)
class PreparedOriginalGet:
    metadata: dict
    url: str


@dataclass(frozen=True, repr=False)
class OriginalBytes:
    metadata: dict
    data: bytes


def method_digest():
    return digest(
        {
            "version": "package-original-get-method/1",
            "source_digest": digest_bytes(Path(__file__).read_bytes()),
            "canonical_source_digest": digest_bytes(Path(review_identity.__file__).read_bytes()),
            "httpx_version": version("httpx"),
            "maximum_bytes": MAX_BYTES,
            "maximum_url_bytes": MAX_URL_BYTES,
            "maximum_deadline_seconds": MAX_DEADLINE,
            "authority_grants": False,
        }
    )


def _sha(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _url(value, profile):
    parsed = None
    try:
        if (
            isinstance(value, str)
            and 1 <= len(value.encode("utf-8")) <= MAX_URL_BYTES
            and not any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in value)
        ):
            parsed = httpx.URL(value)
    except (httpx.InvalidURL, UnicodeError):
        pass
    if parsed is None:
        fail("INVALID_URL")
    if parsed.userinfo or parsed.fragment or not parsed.path or parsed.path == "/":
        fail("INVALID_URL")
    if profile == "oss_hangzhou":
        if (
            parsed.scheme != "https"
            or parsed.host != "tender-base.oss-cn-hangzhou.aliyuncs.com"
            or parsed.port not in (None, 443)
        ):
            fail("ORIGIN_REJECTED")
    elif profile == "development_s3":
        if parsed.scheme != "http" or not (
            (parsed.host == "object-store" and parsed.port == 8333)
            or (
                parsed.host == "127.0.0.1" and parsed.port is not None and 1 <= parsed.port <= 65535
            )
        ):
            fail("ORIGIN_REJECTED")
    else:
        fail("PROFILE_REJECTED")
    return parsed


def prepare_get(
    *,
    url,
    profile,
    bid_id,
    scope_id,
    scope_digest,
    document_version_id,
    source_digest,
    source_byte_size,
):
    for identity in (bid_id, scope_id, document_version_id):
        try:
            if str(UUID(identity)) != identity:
                fail("INVALID_ID")
        except (ValueError, TypeError, AttributeError):
            fail("INVALID_ID")
    if not _sha(scope_digest) or not _sha(source_digest):
        fail("INVALID_DIGEST")
    if type(source_byte_size) is not int or not 1 <= source_byte_size <= MAX_BYTES:
        fail("SIZE_LIMIT")
    parsed = _url(url, profile)
    metadata = {
        "version": "package-original-get-request/1",
        "method_digest": method_digest(),
        "bid_id": bid_id,
        "scope_id": scope_id,
        "scope_digest": scope_digest,
        "document_version_id": document_version_id,
        "source_digest": source_digest,
        "source_byte_size": source_byte_size,
        "profile": profile,
        "url_digest": digest_bytes(url.encode()),
        "http_method": "GET",
        "response_decoding": "raw_identity",
        "automatic_retry": False,
        "native_permission_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    # Keep the exact private signed URL; no normalized string is re-signed or logged.
    del parsed
    return PreparedOriginalGet(metadata | {"digest": digest(metadata)}, url)


def _quiet_transport_logs():
    # This module belongs in the independent byte reader. HTTPX includes private
    # object paths and signature query strings in ordinary INFO request logs.
    for name in list(logging.Logger.manager.loggerDict):
        if name == "httpx" or name == "httpcore" or name.startswith("httpcore."):
            logging.getLogger(name).disabled = True


class OriginalByteClient:
    def __init__(self, *, transport=None, total_timeout=MAX_DEADLINE):
        if type(total_timeout) not in (int, float) or not 0 < total_timeout <= MAX_DEADLINE:
            fail("INVALID_TIMEOUT")
        self._transport = transport
        self._timeout = total_timeout

    async def read(self, request, *, expected_request_digest, expected_method_digest):
        if type(request) is not PreparedOriginalGet:
            fail("REQUEST_INVALID")
        metadata = deepcopy(request.metadata)
        method = method_digest()
        if expected_method_digest != method:
            fail("METHOD_MISMATCH")
        try:
            rebuilt = prepare_get(
                url=request.url,
                **{
                    key: metadata[key]
                    for key in (
                        "profile",
                        "bid_id",
                        "scope_id",
                        "scope_digest",
                        "document_version_id",
                        "source_digest",
                        "source_byte_size",
                    )
                },
            )
        except (KeyError, TypeError):
            fail("REQUEST_INVALID")
        try:
            same = canonical(metadata) == canonical(rebuilt.metadata)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            fail("REQUEST_INVALID")
        if not same or expected_request_digest != metadata["digest"]:
            fail("REQUEST_MISMATCH")
        raw = bytearray()
        failure = None
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(15, connect=5, pool=5),
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    _quiet_transport_logs()
                    async with client.stream(
                        "GET", request.url, headers={"Accept-Encoding": "identity"}
                    ) as response:
                        if response.status_code != 200:
                            fail("HTTP_REJECTED")
                        if (
                            response.headers.get("content-encoding", "").lower()
                            not in ("", "identity")
                            or "content-range" in response.headers
                        ):
                            fail("REPRESENTATION_REJECTED")
                        length = response.headers.get("content-length")
                        if length is not None and (
                            len(length) > 20
                            or not length.isascii()
                            or not length.isdecimal()
                            or int(length) != metadata["source_byte_size"]
                        ):
                            fail("LENGTH_MISMATCH")
                        async for chunk in response.aiter_raw(chunk_size=CHUNK):
                            if len(raw) + len(chunk) > metadata["source_byte_size"]:
                                fail("SIZE_LIMIT")
                            raw.extend(chunk)
        except (TimeoutError, httpx.TimeoutException):
            failure = "TIMEOUT"
        except (httpx.RequestError, httpx.StreamError):
            failure = "NETWORK_ERROR"
        if failure:
            fail(failure)
        if (
            len(raw) != metadata["source_byte_size"]
            or digest_bytes(raw) != metadata["source_digest"]
        ):
            fail("BYTES_MISMATCH")
        if method_digest() != method:
            fail("METHOD_CHANGED")
        value = {
            "version": "package-original-get-receipt/1",
            "request_digest": expected_request_digest,
            "method_digest": method,
            "bid_id": metadata["bid_id"],
            "scope_id": metadata["scope_id"],
            "scope_digest": metadata["scope_digest"],
            "document_version_id": metadata["document_version_id"],
            "source_digest": metadata["source_digest"],
            "source_byte_size": len(raw),
            "actual_http_attempts": 1,
            "complete_requested_bytes_verified": True,
            "native_permission_verified": False,
            "necessary_scope_verified": False,
            "input_authority_granted": False,
            "execution_authorized": False,
            "historical_existence_verified": False,
        }
        return OriginalBytes(value | {"digest": digest(value)}, bytes(raw))
