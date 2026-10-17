"""同源上传的权限、边界、重传与最终内容校验。"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import text

from bidwb.services.files import PART_BYTES
from bidwb.storage import content_key
from tests.test_files_and_parse import _setup

pytestmark = pytest.mark.integration


def _init(api, pid, data):  # type: ignore[no-untyped-def]
    result = api.post(
        f"/projects/{pid}/uploads",
        {
            "original_name": "分片.txt",
            "role": "other",
            "byte_size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_type": "text/plain",
        },
    )
    assert result.status_code == 200
    return result.json()


def _put(api, upload, number, data, *, csrf=True):  # type: ignore[no-untyped-def]
    return api.http.put(
        f"/api/v1/uploads/{upload['upload_id']}/parts/{number}",
        content=data,
        headers={"X-CSRF-Token": api.csrf} if csrf else {},
    )


def test_same_origin_parts_retry_and_complete(api_factory, make_member, store):  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    data = b"a" * PART_BYTES + b"final"
    upload = _init(api, pid, data)
    assert [p["url"] for p in upload["parts"]] == [f"/api/v1/uploads/{upload['upload_id']}/parts/{n}" for n in (1, 2)]
    first = _put(api, upload, 1, data[:PART_BYTES])
    retry = _put(api, upload, 1, data[:PART_BYTES])
    last = _put(api, upload, 2, data[PART_BYTES:])
    assert first.status_code == retry.status_code == last.status_code == 200
    assert first.headers["etag"] == retry.headers["etag"]
    result = api.post(
        f"/uploads/{upload['upload_id']}/complete",
        {
            "sha256": hashlib.sha256(data).hexdigest(),
            "parts": [{"part_number": 1, "etag": first.headers["etag"]}, {"part_number": 2, "etag": last.headers["etag"]}],
        },
    )
    assert result.status_code == 200
    assert store.objects[content_key(hashlib.sha256(data).hexdigest())] == data
    assert _put(api, upload, 1, data[:PART_BYTES]).status_code == 409


def test_part_authorization_and_size_limits(api_factory, make_member, store):  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    upload = _init(api, pid, b"test")
    assert _put(api, upload, 1, b"test", csrf=False).status_code == 403
    anonymous = api_factory()
    assert _put(anonymous, upload, 1, b"test").status_code == 401
    make_member("other")
    other = api_factory().login("other")
    assert _put(other, upload, 1, b"test").status_code == 404
    assert _put(api, upload, 0, b"test").status_code == 422
    assert _put(api, upload, 2, b"test").status_code == 422
    assert _put(api, upload, 1, b"x").json()["code"] == "part_size_mismatch"
    assert _put(api, upload, 1, b"too-long").json()["code"] == "part_size_mismatch"
    assert not next(iter(store._uploads.values())).parts
    assert _put(api, upload, 1, b"test").status_code == 200


def test_expired_part_does_not_touch_storage(api_factory, make_member, store, engine):  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    upload = _init(api, pid, b"test")
    with engine.begin() as conn:
        conn.execute(text("UPDATE upload_sessions SET expires_at=now()-interval '1 second' WHERE id=:id"), {"id": upload["upload_id"]})
    assert _put(api, upload, 1, b"test").json()["code"] == "upload_expired"
    assert not next(iter(store._uploads.values())).parts
