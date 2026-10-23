"""Explicit synthetic wire tests and a real loopback GET; no locator permission change."""

import asyncio
import logging
import threading
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

import httpx
import pytest

from packages.domain.providers import original_bytes as port
from packages.domain.review_identity import digest
from packages.model_governance.technical_png import digest_bytes

RAW = b"synthetic exact original bytes"
URL = "http://127.0.0.1:8333/private-original?signature=synthetic-private-token"


def prepared(*, url=URL, raw=RAW, **changes):
    arguments = {
        "url": url,
        "profile": "development_s3",
        "bid_id": str(UUID(int=1)),
        "scope_id": str(UUID(int=2)),
        "scope_digest": "a" * 64,
        "document_version_id": str(UUID(int=3)),
        "source_digest": digest_bytes(raw),
        "source_byte_size": len(raw),
    } | changes
    return port.prepare_get(**arguments)


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def run(request, *, payload=RAW, status=200, headers=None, deadline=30, stream=None, changes=None):
    state = {"attempts": 0}
    body = stream if stream is not None else Stream([payload])

    async def respond(wire):
        state["attempts"] += 1
        assert wire.method == "GET" and wire.headers["accept-encoding"] == "identity"
        return httpx.Response(status, headers=headers or {}, stream=body)

    client = port.OriginalByteClient(transport=httpx.MockTransport(respond), total_timeout=deadline)
    arguments = {
        "expected_request_digest": request.metadata["digest"],
        "expected_method_digest": port.method_digest(),
    } | (changes or {})
    return lambda: asyncio.run(client.read(request, **arguments)), state, body


def test_complete_wire_bytes_and_private_repr_without_authority():
    request = prepared()
    execute, state, stream = run(
        request, stream=Stream([RAW[:5], RAW[5:]]), headers={"Content-Length": str(len(RAW))}
    )
    result = execute()
    assert result.data == RAW and stream.closed and state["attempts"] == 1
    assert result.metadata["complete_requested_bytes_verified"]
    assert result.metadata["digest"] == digest(
        {k: v for k, v in result.metadata.items() if k != "digest"}
    )
    assert not any(
        result.metadata[key]
        for key in (
            "native_permission_verified",
            "necessary_scope_verified",
            "input_authority_granted",
            "execution_authorized",
            "historical_existence_verified",
        )
    )
    assert "synthetic-private-token" not in repr(request) + repr(result) + str(result.metadata)
    assert "private-original" not in str(request.metadata)


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "http://untrusted.example/private"),
        ("url", "https://tender-base.oss-cn-hangzhou.aliyuncs.com.evil.example/x"),
        ("url", "http://user:secret@127.0.0.1:8333/x"),
        ("url", URL + "#private"),
        ("url", URL + "\n"),
        ("profile", "arbitrary"),
        ("source_byte_size", True),
        ("source_byte_size", 0),
        ("source_byte_size", port.MAX_BYTES + 1),
        ("scope_digest", "G" * 64),
        ("bid_id", "{00000000-0000-0000-0000-000000000001}"),
    ],
)
def test_invalid_or_unapproved_wire_preparation(field, value):
    with pytest.raises(port.OriginalReadError):
        prepared(**{field: value})


def test_official_oss_profile_accepts_only_exact_https_origin():
    request = prepared(
        url="https://tender-base.oss-cn-hangzhou.aliyuncs.com/private?signature=synthetic",
        profile="oss_hangzhou",
    )
    execute, _, _ = run(request)
    assert execute().data == RAW
    with pytest.raises(port.OriginalReadError):
        prepared(
            url="http://tender-base.oss-cn-hangzhou.aliyuncs.com/private", profile="oss_hangzhou"
        )


def test_invalid_url_error_has_no_private_sdk_exception_context():
    with pytest.raises(port.OriginalReadError) as error:
        prepared(url="http://127.0.0.1:synthetic-private-token/original")
    assert error.value.__context__ is None
    assert "synthetic-private-token" not in str(error.value)


@pytest.mark.parametrize(
    "mutation", ["url", "digest", "extra", "integer_false", "size_boolean", "method"]
)
def test_tampered_request_is_rejected_before_transport(mutation):
    request = prepared()
    metadata = deepcopy(request.metadata)
    changes = {}
    if mutation == "url":
        request = replace(request, url=URL + "changed")
    elif mutation == "digest":
        changes["expected_request_digest"] = "0" * 64
    elif mutation == "method":
        changes["expected_method_digest"] = "0" * 64
    elif mutation == "extra":
        metadata["official_score"] = 95
        request = replace(request, metadata=metadata)
    elif mutation == "integer_false":
        metadata["native_permission_verified"] = 0
        request = replace(request, metadata=metadata)
    else:
        metadata["source_byte_size"] = True
        request = replace(request, metadata=metadata)
    execute, state, _ = run(request, changes=changes)
    with pytest.raises(port.OriginalReadError):
        execute()
    assert state["attempts"] == 0


@pytest.mark.parametrize(
    "payload,status,headers",
    [
        (RAW, 302, {}),
        (RAW, 500, {}),
        (RAW, 206, {}),
        (RAW + b"extra", 200, {}),
        (RAW[:-1], 200, {}),
        (b"x" * len(RAW), 200, {}),
        (RAW, 200, {"Content-Length": "1"}),
        (RAW, 200, {"Content-Length": "-1"}),
        (RAW, 200, {"Content-Length": "9" * 5000}),
        (RAW, 200, {"Content-Encoding": "gzip"}),
        (RAW, 200, {"Content-Range": "bytes 0-1/99"}),
    ],
)
def test_reject_partial_changed_encoded_or_failed_response_once(payload, status, headers):
    execute, state, stream = run(prepared(), payload=payload, status=status, headers=headers)
    with pytest.raises(port.OriginalReadError):
        execute()
    assert state["attempts"] == 1 and stream.closed


def test_slow_response_has_total_deadline_and_closes_without_retry():
    execute, state, stream = run(prepared(), stream=Stream([RAW], delay=0.05), deadline=0.01)
    with pytest.raises(port.OriginalReadError, match="TIMEOUT"):
        execute()
    assert stream.closed and state["attempts"] == 1


def test_network_failure_does_not_expose_private_url_or_context():
    async def unavailable(request):
        raise httpx.ConnectError(URL, request=request)

    request = prepared()
    client = port.OriginalByteClient(transport=httpx.MockTransport(unavailable))
    with pytest.raises(port.OriginalReadError, match="NETWORK_ERROR") as error:
        asyncio.run(
            client.read(
                request,
                expected_request_digest=request.metadata["digest"],
                expected_method_digest=port.method_digest(),
            )
        )
    assert error.value.__context__ is None and URL not in str(error.value)


def test_method_change_during_wire_read_rejects(monkeypatch):
    class Changed(Stream):
        async def __aiter__(self):
            monkeypatch.setattr(port, "MAX_URL_BYTES", 8191)
            yield RAW

    execute, _, _ = run(prepared(), stream=Changed([]))
    with pytest.raises(port.OriginalReadError, match="METHOD_CHANGED"):
        execute()


def test_real_loopback_get_and_signature_log_suppression(caplog):
    state = {"attempts": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["attempts"] += 1
            state["encoding"] = self.headers.get("Accept-Encoding")
            self.send_response(200)
            self.send_header("Content-Length", str(len(RAW)))
            self.end_headers()
            self.wfile.write(RAW)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        request = prepared(
            url=f"http://127.0.0.1:{server.server_port}/private-original?signature=synthetic-private-token"
        )
        caplog.set_level(logging.DEBUG)
        result = asyncio.run(
            port.OriginalByteClient().read(
                request,
                expected_request_digest=request.metadata["digest"],
                expected_method_digest=port.method_digest(),
            )
        )
        assert result.data == RAW and state == {"attempts": 1, "encoding": "identity"}
        assert (
            "private-original" not in caplog.text and "synthetic-private-token" not in caplog.text
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
