"""Bounded, explicit observations with authenticated pagination."""

import base64
import hmac
import json
import re
from uuid import UUID

from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, secret_hash

MAX_ITEMS = 1000
MAX_BYTES = 32 * 1024 * 1024
FLAGS = {
    "observation_only": True,
    "admission_granted": False,
    "original_bytes_reverified": False,
    "save_recheck_required": True,
    "formal_decisions_allowed": False,
}


def fail(code, message, status=409):
    raise DomainError("AUTHORING_INPUT_CATALOG_" + code, message, status)


def check(condition, message="精确目录记录的原生绑定或摘要不能核验"):
    if not condition:
        fail("CORRUPT", message, 500)


def request_ids(*values):
    try:
        valid = all(isinstance(value, str) and str(UUID(value)) == value for value in values)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        fail("REQUEST_INVALID", "目录需要明确的规范项目和对象身份", 422)


def request_digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        fail("REQUEST_INVALID", "目录需要明确的预期摘要", 422)


def bounded(value):
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
        fail("CAPACITY_EXCEEDED", "完整目录超过读取预算，未返回截断内容", 413)
    return value


def marker(value, at):
    value = {**value, **FLAGS}
    return bounded({**value, "observation_digest": digest(value), "observed_at": at})


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate cursor key")
        value[key] = item
    return value


def _decode(cursor, scope, observation):
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096:
            raise ValueError("cursor size")
        token, signature = cursor.split(".")
        if not hmac.compare_digest(secret_hash("authoring-input-catalog/1:" + token), signature):
            raise ValueError("cursor signature")
        value = json.loads(
            base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True),
            object_pairs_hook=_pairs,
        )
        if (
            set(value) != {"version", "scope", "observation", "after"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["scope"] != scope
            or not isinstance(value["observation"], str)
            or re.fullmatch(r"[a-f0-9]{64}", value["observation"]) is None
            or str(UUID(value["after"])) != value["after"]
        ):
            raise ValueError("cursor identity")
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError, RecursionError):
        fail("CURSOR_INVALID", "游标不属于本次明确选择，请重新读取目录", 422)
    if value["observation"] != observation:
        fail("OBSERVATION_CHANGED", "目录依据在分页期间已变化；保留原选择，请从首页重新核对", 409)
    return value["after"]


def page(value, items, *, identity, scope, limit, cursor, at):
    if type(limit) is not int or not 1 <= limit <= 50:
        fail("REQUEST_INVALID", "目录页大小必须为 1 至 50", 422)
    if len(items) > MAX_ITEMS:
        fail("CAPACITY_EXCEEDED", "完整目录超过 1000 项，未用局部目录代替完整观察", 413)
    check(
        len({item[identity] for item in items}) == len(items)
        and items == sorted(items, key=lambda item: item[identity])
    )
    complete = bounded({**value, "items": items, **FLAGS})
    observation = digest(complete)
    scope_digest = digest(scope)
    after = _decode(cursor, scope_digest, observation)
    if after is not None and not any(item[identity] == after for item in items):
        fail("CURSOR_INVALID", "目录游标没有对应记录，请从首页重新核对", 422)
    remaining = [item for item in items if after is None or item[identity] > after]
    selected, more = remaining[:limit], len(remaining) > limit
    next_cursor = None
    if more:
        raw = json.dumps(
            {
                "version": 1,
                "scope": scope_digest,
                "observation": observation,
                "after": selected[-1][identity],
            },
            separators=(",", ":"),
        ).encode()
        token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        next_cursor = token + "." + secret_hash("authoring-input-catalog/1:" + token)
    return {
        **value,
        "items": selected,
        "next_cursor": next_cursor,
        "has_more": more,
        "total_items": len(items),
        "observation_digest": observation,
        "observed_at": at,
        **FLAGS,
    }
