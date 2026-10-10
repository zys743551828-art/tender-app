"""结构化日志（JSON，一行一事件）。

约定：日志里不出现口令、令牌、预签名地址、招标文件正文。``_redact`` 对常见敏感键名兜底，
但真正的保证来自调用方不记录这些内容——兜底只是防止疏忽。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

_SENSITIVE_PARTS = ("password", "secret", "token", "authorization", "cookie", "signature", "api_key", "dsn")


def _redact(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for key in list(event_dict):
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE_PARTS):
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """配置 structlog 与标准库 logging；进程入口调用一次。"""
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact,
        structlog.processors.JSONRenderer(ensure_ascii=False) if json_output else structlog.dev.ConsoleRenderer(colors=False),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    # 访问日志由我们的中间件按统一格式输出，避免 uvicorn 重复记录且带上查询串。
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
