"""对象存储端口与适配器。

业务代码只依赖 ``ObjectStore``。生产使用阿里云 OSS 的 S3 兼容接口（``S3ObjectStore``）；开发和测试可指向 MinIO，
单元测试使用 ``MemoryObjectStore``。选择 S3 兼容接口而非 OSS 专有 SDK：同一份代码能在本地 MinIO 上完整跑通，
并避免被单一厂商 SDK 绑定。

对象键约定：
    staging/<upload_id>             API 分片转传落点，不对任何业务可见
    objects/<sha256[:2]>/<sha256>   内容寻址的最终位置，同一内容只保存一份且不会被覆盖
    artifacts/<artifact_id>         worker 产物
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

    from bidwb.config import Settings

CHUNK = 1024 * 1024


class ObjectStoreError(Exception):
    """存储调用失败（网络、权限、对象缺失等）；调用方转换为 503 或业务错误。"""


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    etag: str


class ObjectStore(Protocol):
    def create_multipart(self, key: str, content_type: str) -> str: ...

    def upload_part(self, key: str, upload_id: str, part_number: int, data: bytes) -> str: ...
    def presign_part(self, key: str, upload_id: str, part_number: int, ttl_seconds: int) -> str: ...
    def complete_multipart(self, key: str, upload_id: str, parts: Sequence[tuple[int, str]]) -> None: ...
    def abort_multipart(self, key: str, upload_id: str) -> None: ...
    def head(self, key: str) -> ObjectInfo | None: ...
    def sha256(self, key: str) -> str: ...
    def copy_if_absent(self, source: str, destination: str) -> bool: ...
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def read_range(self, key: str, start: int, end: int) -> Iterator[bytes]: ...
    def delete(self, key: str) -> None: ...


def staging_key(upload_id: str) -> str:
    return f"staging/{upload_id}"


def content_key(sha256: str) -> str:
    return f"objects/{sha256[:2]}/{sha256}"


def artifact_key(artifact_id: str) -> str:
    return f"artifacts/{artifact_id}"


class S3ObjectStore:
    """boto3 实现。预签名使用对浏览器可达的公网端点，服务端读写使用内网端点。"""

    def __init__(self, settings: Settings) -> None:
        cfg = Config(
            signature_version=settings.storage_signature_version,
            s3={"addressing_style": settings.storage_addressing_style},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
        )
        common = {
            "region_name": settings.storage_region,
            "aws_access_key_id": settings.storage_access_key_id.get_secret_value(),
            "aws_secret_access_key": settings.storage_secret_access_key.get_secret_value(),
            "config": cfg,
        }
        self._bucket = settings.storage_bucket
        self._client: S3Client = boto3.client("s3", endpoint_url=settings.storage_endpoint_url, **common)  # type: ignore[call-overload]
        public = settings.storage_public_endpoint_url or settings.storage_endpoint_url
        self._signer: S3Client = boto3.client("s3", endpoint_url=public, **common)  # type: ignore[call-overload]

    def create_multipart(self, key: str, content_type: str) -> str:
        try:
            out = self._client.create_multipart_upload(Bucket=self._bucket, Key=key, ContentType=content_type)
        except ClientError as exc:
            raise ObjectStoreError("create_multipart") from exc
        return out["UploadId"]

    def presign_part(self, key: str, upload_id: str, part_number: int, ttl_seconds: int) -> str:
        return self._signer.generate_presigned_url(
            "upload_part",
            Params={"Bucket": self._bucket, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
            ExpiresIn=ttl_seconds,
        )

    def upload_part(self, key: str, upload_id: str, part_number: int, data: bytes) -> str:
        try:
            result = self._client.upload_part(Bucket=self._bucket, Key=key, UploadId=upload_id, PartNumber=part_number, Body=data)
        except ClientError as exc:
            raise ObjectStoreError("upload_part") from exc
        return result["ETag"]

    def complete_multipart(self, key: str, upload_id: str, parts: Sequence[tuple[int, str]]) -> None:
        try:
            self._client.complete_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": [{"PartNumber": n, "ETag": etag} for n, etag in sorted(parts)]},
            )
        except ClientError as exc:
            raise ObjectStoreError("complete_multipart") from exc

    def abort_multipart(self, key: str, upload_id: str) -> None:
        try:
            self._client.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchUpload":
                raise ObjectStoreError("abort_multipart") from exc

    def head(self, key: str) -> ObjectInfo | None:
        try:
            out = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise ObjectStoreError("head") from exc
        return ObjectInfo(size=out["ContentLength"], etag=out["ETag"].strip('"'))

    def sha256(self, key: str) -> str:
        digest = hashlib.sha256()
        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
            for chunk in body.iter_chunks(CHUNK):
                digest.update(chunk)
        except ClientError as exc:
            raise ObjectStoreError("sha256") from exc
        return digest.hexdigest()

    def copy_if_absent(self, source: str, destination: str) -> bool:
        """内容寻址键只写一次。返回 True 表示本次写入，False 表示已存在（同键即同内容）。"""
        if self.head(destination) is not None:
            return False
        try:
            self._client.copy_object(
                Bucket=self._bucket,
                Key=destination,
                CopySource={"Bucket": self._bucket, "Key": source},
                MetadataDirective="COPY",
            )
        except ClientError as exc:
            raise ObjectStoreError("copy") from exc
        return True

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        except ClientError as exc:
            raise ObjectStoreError("put") from exc

    def get(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as exc:
            raise ObjectStoreError("get") from exc

    def read_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        """读取闭区间 ``[start, end]`` 的字节，供 HTTP Range 使用。"""
        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key, Range=f"bytes={start}-{end}")["Body"]
        except ClientError as exc:
            raise ObjectStoreError("read_range") from exc
        yield from body.iter_chunks(CHUNK)

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise ObjectStoreError("delete") from exc


@dataclass
class _Multipart:
    key: str
    parts: dict[int, bytes] = field(default_factory=dict)


class MemoryObjectStore:
    """进程内实现，用于单元测试与无外部依赖的本地试运行。

    ``presign_part`` 返回 ``memory://`` 地址；测试用 ``put_part`` 模拟浏览器上传并取得 ETag。
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._uploads: dict[str, _Multipart] = {}
        self._counter = 0

    def create_multipart(self, key: str, content_type: str) -> str:
        self._counter += 1
        upload_id = f"mem-upload-{self._counter}"
        self._uploads[upload_id] = _Multipart(key)
        return upload_id

    def presign_part(self, key: str, upload_id: str, part_number: int, ttl_seconds: int) -> str:
        return f"memory://{key}?uploadId={upload_id}&partNumber={part_number}"

    def put_part(self, upload_id: str, part_number: int, data: bytes) -> str:
        self._uploads[upload_id].parts[part_number] = data
        return hashlib.md5(data, usedforsecurity=False).hexdigest()

    def upload_part(self, key: str, upload_id: str, part_number: int, data: bytes) -> str:
        upload = self._uploads.get(upload_id)
        if upload is None or upload.key != key:
            raise ObjectStoreError("upload_part")
        return self.put_part(upload_id, part_number, data)

    def complete_multipart(self, key: str, upload_id: str, parts: Sequence[tuple[int, str]]) -> None:
        upload = self._uploads.get(upload_id)
        if upload is None or upload.key != key:
            raise ObjectStoreError("complete_multipart")
        missing = [n for n, _ in parts if n not in upload.parts]
        if missing:
            raise ObjectStoreError("complete_multipart")
        self.objects[key] = b"".join(upload.parts[n] for n, _ in sorted(parts))
        del self._uploads[upload_id]

    def abort_multipart(self, key: str, upload_id: str) -> None:
        self._uploads.pop(upload_id, None)

    def head(self, key: str) -> ObjectInfo | None:
        data = self.objects.get(key)
        if data is None:
            return None
        return ObjectInfo(len(data), hashlib.md5(data, usedforsecurity=False).hexdigest())

    def sha256(self, key: str) -> str:
        return hashlib.sha256(self._require(key)).hexdigest()

    def copy_if_absent(self, source: str, destination: str) -> bool:
        if destination in self.objects:
            return False
        self.objects[destination] = self._require(source)
        return True

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self._require(key)

    def read_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        yield self._require(key)[start : end + 1]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def _require(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise ObjectStoreError("missing") from exc
