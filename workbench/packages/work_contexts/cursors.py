"""Signed cursors pin both the exact seed and the complete directory observation."""

import base64
import hmac
import json
import re

from packages.domain.runtime import secret_hash
from packages.work_contexts import policy

SHA = re.compile(r"^[0-9a-f]{64}$")


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate cursor key")
        value[key] = item
    return value


def encode(scope, observation, after):
    raw = json.dumps(
        {"version": 1, "scope": scope, "observation": observation, "after": after},
        separators=(",", ":"),
    ).encode()
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return token + "." + secret_hash("work-context-cursor/1:" + token)


def decode(cursor, scope, observation):
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
            raise ValueError("cursor size")
        token, signature = cursor.split(".")
        if not hmac.compare_digest(secret_hash("work-context-cursor/1:" + token), signature):
            raise ValueError("cursor signature")
        value = json.loads(
            base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True),
            object_pairs_hook=_pairs,
        )
        if (
            set(value) != {"version", "scope", "observation", "after"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or any(
                not isinstance(value[key], str) or not SHA.fullmatch(value[key])
                for key in ("scope", "observation", "after")
            )
            or value["scope"] != scope
        ):
            raise ValueError("cursor scope")
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        policy.fail("CURSOR_INVALID", "游标不属于当前明确选择或格式无效，请重新读取目录", 422)
    if value["observation"] != observation:
        policy.fail(
            "OBSERVATION_CHANGED",
            "关联或当前依据在分页期间已变化，请从首页重新读取；原选择仍保留",
            409,
        )
    return value["after"]
