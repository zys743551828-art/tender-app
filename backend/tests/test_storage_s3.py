"""S3 适配器与内存实现的行为一致性（moto 模拟 S3）：同一组操作在两者上结果相同。"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from moto import mock_aws
from pydantic import SecretStr

from bidwb.config import Settings
from bidwb.storage import MemoryObjectStore, ObjectStore, S3ObjectStore

DATA = os.urandom(5 * 1024 * 1024 + 123)  # 超过 S3 分片下限（5 MiB）的最后一片可以更小
PART = 5 * 1024 * 1024


@pytest.fixture(params=["s3", "s3v4"])
def s3_store(request: pytest.FixtureRequest) -> Iterator[S3ObjectStore]:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="bidwb")
        settings = Settings(
            environment="test",
            storage_region="us-east-1",
            storage_bucket="bidwb",
            storage_access_key_id=SecretStr("testing"),
            storage_secret_access_key=SecretStr("testing"),
            storage_addressing_style="path",
            storage_signature_version=request.param,
        )
        yield S3ObjectStore(settings)


def _exercise(store: ObjectStore, put_part) -> None:  # type: ignore[no-untyped-def]
    upload_id = store.create_multipart("staging/u1", "application/pdf")
    etags = [(1, put_part(upload_id, 1, DATA[:PART])), (2, put_part(upload_id, 2, DATA[PART:]))]
    store.complete_multipart("staging/u1", upload_id, etags)
    info = store.head("staging/u1")
    assert info is not None and info.size == len(DATA)
    assert store.sha256("staging/u1") == hashlib.sha256(DATA).hexdigest()
    assert store.copy_if_absent("staging/u1", "content/abc") is True
    assert store.copy_if_absent("staging/u1", "content/abc") is False  # 目标已存在：不覆盖
    assert b"".join(store.read_range("content/abc", 10, 19)) == DATA[10:20]
    store.put("artifacts/x", b"hello", "text/plain")
    assert store.get("artifacts/x") == b"hello"
    store.delete("staging/u1")
    assert store.head("staging/u1") is None
    assert store.head("missing") is None


def test_s3_adapter(s3_store: S3ObjectStore) -> None:
    client = s3_store._client

    def put_part(upload_id: str, number: int, data: bytes) -> str:
        key = "staging/u1"
        etag = client.upload_part(Bucket="bidwb", Key=key, UploadId=upload_id, PartNumber=number, Body=data)["ETag"]
        return str(etag)

    _exercise(s3_store, put_part)
    assert s3_store.presign_part("staging/u2", "uid", 1, 600).startswith("https://")


def test_s3_presign_uses_selected_signature(s3_store: S3ObjectStore) -> None:
    query = parse_qs(urlsplit(s3_store.presign_part("staging/u2", "uid", 1, 600)).query)
    if s3_store._client.meta.config.signature_version == "s3":
        assert "AWSAccessKeyId" in query and "Signature" in query
        assert "X-Amz-Algorithm" not in query
    else:
        assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
        assert "X-Amz-Signature" in query


def test_memory_store_behaves_the_same() -> None:
    store = MemoryObjectStore()
    _exercise(store, store.put_part)
