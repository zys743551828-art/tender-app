"""分片边界：票据不能换会话/片号，状态元数据拒绝误解释。"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests

from apps.api import multipart_routes
from apps.api.object_transfer import _verify
from packages.domain import storage
from packages.domain.providers.oss import OssClient
from packages.domain.runtime import DomainError, now, validate
from packages.uploads import service
from packages.uploads.native import NativeMultipart
from packages.uploads.protocol import PART_SIZE, check_parts, layout, pack, unpack


@pytest.mark.parametrize(
    ("chunks", "status"),
    [
        ([(45, b"a"), (45, b"b"), (45, b"c")], 200),
        ([(45, b""), (50, b"abc")], 408),
        ([(65, b"a"), (65, b"b"), (65, b"c")], 408),
    ],
    ids=["ongoing-progress", "no-byte-progress", "total-deadline"],
)
def test_multipart_body_progress_and_deadlines(monkeypatch, chunks, status):
    monkeypatch.setenv("OBJECT_TRANSFER_DEADLINE_SECONDS", "180")
    staging = "staging/test-object"
    state = pack("ready", key=staging, nonce=str(uuid4()), provider_id="existing-upload")
    row = {
        "part_size": PART_SIZE,
        "part_count": 2,
        "declared_size": PART_SIZE + 3,
        "staging_key": staging,
        "provider_upload_id": state,
    }
    written = []
    published = []
    monkeypatch.setattr(multipart_routes, "auth", lambda *_: {})
    monkeypatch.setattr(service, "snapshot", lambda *_: row)
    monkeypatch.setattr(service, "publish_part", lambda *args: published.append(args))

    def upload(*args):
        written.append(args)
        return "stored-etag"

    async def run_locally(call, *args):
        return call(*args)

    monkeypatch.setattr(multipart_routes, "NativeMultipart", lambda: SimpleNamespace(upload=upload))
    monkeypatch.setattr(multipart_routes, "run_in_threadpool", run_locally)

    async def transfer():
        loop = asyncio.get_running_loop()
        clock = loop.time()
        monkeypatch.setattr(loop, "time", lambda: clock)

        async def stream():
            nonlocal clock
            for delay, data in chunks:
                clock += delay
                # Let the event loop fire any timeout due before the next chunk arrives.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                yield data

        request = SimpleNamespace(
            headers={"content-type": "application/octet-stream", "content-length": "3"},
            stream=stream,
        )
        return await multipart_routes.put_part(uuid4(), 2, request, "existing-ticket")

    if status == 200:
        response = asyncio.run(transfer())
        assert response.status_code == 200 and response.headers["ETag"] == "stored-etag"
        assert written == [(staging, "existing-upload", 2, b"abc")]
        assert len(published) == 1 and published[0][-1] == "stored-etag"
    else:
        with pytest.raises(DomainError) as error:
            asyncio.run(transfer())
        assert (error.value.status, error.value.code) == (408, "UPLOAD_INTERRUPTED")
        assert not written and not published


def test_layout_and_complete_receipts_reject_missing_duplicate_or_wrong_size():
    size, count = layout(PART_SIZE + 19)
    row = {"declared_size": PART_SIZE + 19, "part_size": size, "part_count": count}
    good = [
        {"part_number": 1, "byte_size": PART_SIZE, "etag": "one"},
        {"part_number": 2, "byte_size": 19, "etag": "two"},
    ]
    assert check_parts(row, good, complete=True) == good
    for wrong in (good[:1], [good[0], good[0]], [good[0], {**good[1], "byte_size": 20}]):
        with pytest.raises(DomainError):
            check_parts(row, wrong, complete=True)
    with pytest.raises(DomainError):
        layout(PART_SIZE * 10000 + 1)


def test_control_state_has_explicit_version_and_strict_shape():
    key = "staging/synthetic/key"
    encoded = pack("ready", key=key, nonce=str(uuid4()), provider_id="synthetic-native-identifier")
    assert unpack(encoded, key)["phase"] == "ready"
    for invalid in (
        "ready",
        "synthetic-native-identifier",
        encoded.replace('"ready"', '"arbitrary"'),
        encoded.replace('"provider_id"', '"other_field"'),
    ):
        with pytest.raises(DomainError):
            unpack(invalid, key)
    with pytest.raises(DomainError):
        unpack(encoded, key + "other")


def test_grants_bind_session_method_part_size_revision_and_expiry(monkeypatch):
    monkeypatch.setenv("APP_ORIGIN", "https://workbench.test")
    monkeypatch.setenv("SESSION_SECRET", "synthetic-multipart-secret-only")
    session = {"id": uuid4(), "member_id": uuid4(), "expires_at": now() + timedelta(hours=1)}
    row = {
        "id": uuid4(),
        "bid_id": uuid4(),
        "file_id": uuid4(),
        "staging_key": "staging/synthetic/key",
        "declared_digest": "a" * 64,
        "declared_size": PART_SIZE + 19,
        "part_size": PART_SIZE,
        "part_count": 2,
        "revision": 1,
        "expires_at": now() + timedelta(hours=24),
    }
    grant = service.grant(row, session, [1, 2])
    validate("UploadGrant", grant)
    assert grant["upload_url"] is None
    token = grant["parts"][0]["url"].split("ticket=", 1)[1]
    claims = service.claims(row, session, 1)
    _verify(token, claims)
    for altered in (
        {**claims, "method": "GET"},
        {**claims, "part": 2},
        {**claims, "revision": 2},
        {**claims, "size": 5},
        {**claims, "session": str(uuid4())},
        {**claims, "key": "other"},
    ):
        with pytest.raises(DomainError):
            _verify(token, altered)
    with pytest.raises(DomainError):
        service.grant(row, session, [1, 1])
    with pytest.raises(DomainError):
        service.grant(row, session, list(range(1, 130)))


def test_native_multipart_completed_object_is_private_and_completion_remains_immutable(monkeypatch):
    calls = []

    class Native:
        def init_multipart_upload(self, key, headers):
            calls.append(("init", key, headers))
            return SimpleNamespace(upload_id="owned-upload-id")

        def upload_part(self, key, provider_id, number, data):
            calls.append(("part", key, provider_id, number, data))
            return SimpleNamespace(etag="actual-part-etag")

        def complete_multipart_upload(self, key, provider_id, parts, headers):
            calls.append(("complete", key, provider_id, parts, headers))
            # Model the observed region: object ACL is chosen at assembly time.
            self.completed_acl = headers.get("x-oss-object-acl", "default")

        def abort_multipart_upload(self, key, provider_id):
            calls.append(("abort", key, provider_id))

    native = Native()
    port = OssClient(native, prefix="workbench-checks/native-private/")
    monkeypatch.setattr(storage, "client", lambda: port)
    monkeypatch.setattr(storage, "bucket", lambda: port.bucket_name)
    adapter = NativeMultipart()
    key = "staging/synthetic/object"
    upload_id = adapter.initialize(key, "application/octet-stream")
    assert upload_id == "owned-upload-id"
    assert calls == [
        (
            "init",
            port.prefix + key,
            {
                "Content-Type": "application/octet-stream",
            },
        ),
    ]
    etag = adapter.upload(key, upload_id, 1, b"synthetic-part")
    assert etag == "actual-part-etag"
    adapter.complete(key, upload_id, [{"part_number": 1, "etag": etag}])
    assert native.completed_acl == "private"
    adapter.abort(key, upload_id)
    assert [call[0] for call in calls] == ["init", "part", "complete", "abort"]
    assert all(call[1] == port.prefix + key for call in calls)
    assert all(call[2] == upload_id for call in calls[1:])
    assert calls[1][3:] == (1, b"synthetic-part")
    assert calls[2][3][0].part_number == 1 and calls[2][3][0].etag == etag
    assert calls[2][4] == {"x-oss-forbid-overwrite": "true", "x-oss-object-acl": "private"}


@pytest.mark.parametrize("operation", ["initialize", "complete", "abort"])
def test_native_multipart_failures_keep_exact_identity_and_do_not_echo_or_retry(
    monkeypatch, operation
):
    calls = []

    class Native:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                calls.append((name, args))
                raise requests.ConnectionError("synthetic-private-signed-url")

            return fail

    port = OssClient(Native(), prefix="workbench-checks/native-private/")
    monkeypatch.setattr(storage, "client", lambda: port)
    monkeypatch.setattr(storage, "bucket", lambda: port.bucket_name)
    adapter = NativeMultipart()
    key, upload_id = "staging/synthetic/object", "owned-upload-id"
    with pytest.raises(DomainError) as caught:
        if operation == "initialize":
            adapter.initialize(key)
        elif operation == "complete":
            adapter.complete(key, upload_id, [{"part_number": 1, "etag": "actual-etag"}])
        else:
            adapter.abort(key, upload_id)
    assert len(calls) == 1 and calls[0][1][0] == port.prefix + key
    if operation != "initialize":
        assert calls[0][1][1] == upload_id
    assert caught.value.code == (
        "MULTIPART_ABORT_UNCONFIRMED" if operation == "abort" else "MULTIPART_PROVIDER_UNAVAILABLE"
    )
    assert "synthetic-private-signed-url" not in str(caught.value) + str(caught.value.details)
