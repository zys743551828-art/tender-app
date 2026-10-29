"""Transport budget for a complete dependency check/save request, never historical views."""

import json
from typing import Any

from packages.domain.runtime import DomainError

MAX_DEPENDENCY_BODY_BYTES = 4 * 1024 * 1024
MAX_DEPENDENCY_TRANSPORT_BYTES = 5 * 1024 * 1024


def require_body_size(size: int) -> None:
    if size > MAX_DEPENDENCY_BODY_BYTES:
        raise DomainError(
            "PACKAGE_DEPENDENCY_BODY_TOO_LARGE",
            "本轮请求正文超过 4 MiB，未执行核对或新保存；请缩短标注说明后重试",
            413,
        )


def require_transport_size(size: int) -> None:
    # Match the existing proxy ceiling so old accepted commands between 4 and
    # 5 MiB can still retrieve their exact ACK before today's new-write budget.
    if size > MAX_DEPENDENCY_TRANSPORT_BYTES:
        raise DomainError(
            "PACKAGE_DEPENDENCY_BODY_TOO_LARGE",
            "请求正文超过 5 MiB，未处理本次请求；原保存回执仍可通过历史接口查阅",
            413,
        )


def require_dependency_body(body: Any) -> None:
    """Also guard direct service callers using the compact UTF-8 wire representation."""
    try:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        size = len(raw.encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise DomainError("INVALID_REQUEST", "依赖请求必须为有效的 UTF-8 JSON", 422) from error
    require_body_size(size)
