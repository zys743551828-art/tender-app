"""无状态小工具：时间、标识、摘要。集中在此便于测试时替换。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

Clock = Callable[[], datetime]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """生成形如 ``job_3f9a1c0b7d2e4a56`` 的标识，满足契约 ``^[a-z][a-z0-9_-]{2,80}$``。"""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def is_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))


def canonical_json(obj: Any) -> str:
    """键排序、无空白的 JSON，用于请求哈希与输入摘要，保证同一内容得到同一字节。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


def decimal_text(value: Decimal | None) -> str | None:
    """数值转字符串：去掉多余的小数零，不用科学计数法（8.50 → "8.5"，100 → "100"）。"""
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def xml_safe(text: str) -> str:
    """去掉 XML 1.0 不允许的字符（控制字符、U+FFFE/U+FFFF）。PDF 文本层常带这类字符，写进 Word 等 XML 格式前必须清掉。"""
    return _XML_ILLEGAL.sub("", text)
