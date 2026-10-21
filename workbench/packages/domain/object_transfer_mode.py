"""Explicit same-origin transport selection; actual tickets and bytes use existing routes."""

from __future__ import annotations

import os
from collections.abc import Mapping

from packages.domain.runtime import DomainError

_REQUIRED = (
    "OBJECT_STORE_ENDPOINT",
    "OBJECT_STORE_BUCKET",
    "OBJECT_STORE_ACCESS_KEY",
    "OBJECT_STORE_SECRET_KEY",
)


def same_origin(environment: Mapping[str, str] | None = None) -> bool:
    """Keep the existing default, or explicitly select the authenticated transfer port.

    This does not mint a URL, contact storage, replace the endpoint, or accept a
    client-provided proxy. The caller still uses make_upload_url/make_download_url
    and their configured APP_ORIGIN, session, ticket and byte/identity guards.
    """
    values = os.environ if environment is None else environment
    mode, backend = values.get("OBJECT_TRANSFER_MODE"), values.get("OBJECT_STORE_BACKEND")
    if mode is None:
        return backend == "oss"
    if mode != "same_origin":
        raise DomainError("OBJECT_TRANSFER_MODE_INVALID", "原件传输模式配置不合法", 503)
    if backend not in {"s3", "oss"} or any(
        not isinstance(values.get(key), str)
        or not values[key].strip()
        or any(character in values[key] for character in "\r\n\x00")
        for key in _REQUIRED
    ):
        raise DomainError(
            "OBJECT_TRANSFER_STORE_NOT_CONFIGURED", "同源原件传输需要明确配置受支持的对象存储", 503
        )
    return True
