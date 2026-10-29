"""Strict local JSON/schema and safe identifiers shared by controlled ports."""

import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from packages.domain.errors import DomainError


def identifier(value):
    return (
        value if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9._:-]{1,200}", value) else None
    )


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def schema_check(schema):
    try:
        Draft202012Validator.check_schema(schema)

        # 不让供应商输出校验触发额外网络读取。
        def check(node, root=True):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "$id" and not root:
                        raise ValueError("nested schema resource")
                    if key in ("$ref", "$dynamicRef") and (
                        not isinstance(value, str) or not value.startswith("#")
                    ):
                        raise ValueError("remote schema reference")
                    if key in ("$ref", "$dynamicRef"):
                        # 本端口仅接受根内JSON Pointer；悬空引用须在付费前拒绝。
                        if value != "#" and not value.startswith("#/"):
                            raise ValueError("unsupported anchor")
                        target = schema
                        for part in value[2:].split("/") if value != "#" else []:
                            token = part.replace("~1", "/").replace("~0", "~")
                            target = (
                                target[int(token)] if isinstance(target, list) else target[token]
                            )
                    check(value, False)
            elif isinstance(node, list):
                for value in node:
                    check(value, False)

        check(schema)
    except (SchemaError, ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise DomainError(
            "MODEL_REQUEST_INVALID", "输出JSON Schema不合法或含外部引用", 422
        ) from None
