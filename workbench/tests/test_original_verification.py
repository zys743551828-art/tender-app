"""Streaming IO contract with explicit in-memory object bodies, no real provider claims."""

import hashlib
from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from packages.domain import original_verification as originals
from packages.domain.runtime import DomainError


class TrackingBody(BytesIO):
    def __init__(self, raw):
        super().__init__(raw)
        self.requests = []

    def read(self, size=-1):
        self.requests.append(size)
        return super().read(size)


@pytest.mark.parametrize("change", ["exact", "same_size", "short", "oversized"])
def test_actual_chunks_and_size_digest_are_checked_and_stream_closed(monkeypatch, change):
    raw = b"a" * (originals.CHUNK_SIZE + 23)
    changed = {
        "exact": raw,
        "same_size": b"b" * len(raw),
        "short": raw[:-1],
        "oversized": raw + b"z",
    }[change]
    stream = TrackingBody(changed)

    class Client:
        def get_object(self, **kwargs):
            assert kwargs == {"Bucket": "synthetic", "Key": "private/synthetic"}
            return {"Body": stream}

    monkeypatch.setattr(originals.storage, "client", Client)
    monkeypatch.setattr(originals.storage, "bucket", lambda: "synthetic")
    document = {
        "object_key": "private/synthetic",
        "byte_size": len(raw),
        "digest": hashlib.sha256(raw).hexdigest(),
    }
    if change == "exact":
        originals.verify(document)
    else:
        with pytest.raises(DomainError) as failure:
            originals.verify(document)
        assert failure.value.code == "ORIGINAL_BYTES_CORRUPTED"
    assert stream.closed
    assert max(stream.requests) <= originals.CHUNK_SIZE
    assert all(n > 0 for n in stream.requests)


@pytest.mark.parametrize(
    "code,expected,status",
    [
        ("NoSuchKey", "ORIGINAL_NOT_AVAILABLE", 409),
        ("AccessDenied", "OBJECT_STORE_UNAVAILABLE", 503),
    ],
)
def test_provider_error_never_exposes_private_locator_or_signature(
    monkeypatch, code, expected, status
):
    class Client:
        def get_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": code, "Message": "private/synthetic?secret=hidden"}}, "GetObject"
            )

    monkeypatch.setattr(originals.storage, "client", Client)
    monkeypatch.setattr(originals.storage, "bucket", lambda: "synthetic")
    with pytest.raises(DomainError) as failure:
        originals.verify({"object_key": "private/synthetic", "byte_size": 1, "digest": "0" * 64})
    assert failure.value.code == expected
    assert failure.value.status == status
    assert "private" not in failure.value.message


@pytest.mark.parametrize("stage", ["read", "close"])
def test_stream_failures_are_safe_dependency_errors_and_close_is_attempted(monkeypatch, stage):
    class Body(TrackingBody):
        attempted = False

        def read(self, size=-1):
            if stage == "read":
                raise OSError("private network diagnostic")
            return super().read(size)

        def close(self):
            self.attempted = True
            super().close()
            if stage == "close":
                raise OSError("private close diagnostic")

    stream = Body(b"a")

    class Client:
        def get_object(self, **kwargs):
            return {"Body": stream}

    monkeypatch.setattr(originals.storage, "client", Client)
    monkeypatch.setattr(originals.storage, "bucket", lambda: "synthetic")
    with pytest.raises(DomainError) as failure:
        originals.verify(
            {"object_key": "synthetic", "byte_size": 1, "digest": hashlib.sha256(b"a").hexdigest()}
        )
    assert failure.value.code == "OBJECT_STORE_UNAVAILABLE"
    assert failure.value.status == 503
    assert "private" not in failure.value.message
    assert stream.attempted and stream.closed
