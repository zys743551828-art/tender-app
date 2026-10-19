"""Bounded streaming verification of one original; no database or scheduling access."""

import hashlib
from contextlib import closing
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from packages.domain import storage
from packages.domain.runtime import DomainError

CHUNK_SIZE = 1024 * 1024


def verify(document: dict[str, Any]) -> None:
    try:
        stream = storage.client().get_object(Bucket=storage.bucket(), Key=document["object_key"])[
            "Body"
        ]
        with closing(stream) as body:
            total, fingerprint = 0, hashlib.sha256()
            while True:
                # Read at most one byte beyond the declared size; never buffer the whole file.
                part = body.read(min(CHUNK_SIZE, document["byte_size"] - total + 1))
                if not part:
                    break
                total += len(part)
                if total > document["byte_size"]:
                    raise DomainError("ORIGINAL_BYTES_CORRUPTED", "原件实际大小或摘要不符", 409)
                fingerprint.update(part)
            if total != document["byte_size"] or fingerprint.hexdigest() != document["digest"]:
                raise DomainError("ORIGINAL_BYTES_CORRUPTED", "原件实际大小或摘要不符", 409)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "NotFound", "404"}:
            raise DomainError("ORIGINAL_NOT_AVAILABLE", "所选原件目前不可读取", 409) from None
        raise DomainError(
            "OBJECT_STORE_UNAVAILABLE", "对象存储请求失败", 503, retryable=True
        ) from None
    except (BotoCoreError, OSError):
        raise DomainError(
            "OBJECT_STORE_UNAVAILABLE", "对象存储读取失败", 503, retryable=True
        ) from None
