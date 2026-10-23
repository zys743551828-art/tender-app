"""Actual API contracts for explicit, versioned external Word import."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.domain.runtime import DomainError

BASE = "/api/v1/bids/{bid_id}/drafts/{draft_id}/word-imports"
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TEXT = {"type": "string"}
TIME = {"type": "string", "format": "date-time"}
REV = {"type": "integer", "minimum": 1}
JSON = {"$ref": "#/components/schemas/AuthoringWordImportJson"}
REASON = {
    "type": "string",
    "minLength": 1,
    "maxLength": 1000,
    "pattern": r"\S",
    "not": {"pattern": r"[\u0000-\u001F\uD800-\uDFFF]"},
}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


def array(value):
    return {"type": "array", "items": value}


PREPARE = object_schema(
    {
        "source_document_version_id": UUID,
        "source_digest": SHA,
        "source_byte_size": {"type": "integer", "minimum": 1, "maximum": 33554432},
        "base_draft_revision": REV,
        "method_digest": SHA,
        "reason": REASON,
    }
)
RESOLVE = object_schema(
    {
        "decision": {"enum": ["append", "reject"]},
        "candidate_digest": SHA,
        "acknowledged_issue_ids": {
            "type": "array",
            "maxItems": 10000,
            "uniqueItems": True,
            "items": SHA,
        },
        "reason": REASON,
    }
)


def command(request):
    return object_schema(
        {
            "command_id": UUID,
            "actor_id": UUID,
            "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
            "request_digest": SHA,
            "request": request,
            "if_match": nullable(TEXT),
        }
    )


SOURCE = object_schema(
    {
        "document_version_id": UUID,
        "digest": SHA,
        "byte_size": {"type": "integer", "minimum": 1},
        "media_type": {
            "const": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        },
        "filename": TEXT,
        "role": TEXT,
        "file_id": UUID,
        "file_revision": REV,
        "intake_digest": SHA,
    }
)
ISSUE = object_schema(
    {
        "id": SHA,
        "code": TEXT,
        "severity": {"enum": ["warning", "blocker"]},
        "source_path": TEXT,
        "message": TEXT,
    }
)
SECTION = object_schema(
    {
        "key": UUID,
        "parent_key": nullable(UUID),
        "section_id": UUID,
        "parent_id": nullable(UUID),
        "ordinal": {"type": "integer", "minimum": 0},
        "title": TEXT,
        "source_path": TEXT,
        "content": JSON,
    }
)
IMAGE = object_schema(
    {
        "key": UUID,
        "source_part": TEXT,
        "source_digest": SHA,
        "source_byte_size": {"type": "integer", "minimum": 1},
        "source_media_type": {"enum": ["image/png", "image/jpeg"]},
        "media_type": {"const": "image/png"},
        "digest": SHA,
        "byte_size": {"type": "integer", "minimum": 1},
        "width_px": {"type": "integer", "minimum": 1},
        "height_px": {"type": "integer", "minimum": 1},
    }
)
RESULT = object_schema(
    {
        "bid_id": UUID,
        "draft_id": UUID,
        "candidate_id": UUID,
        "candidate_digest": SHA,
        "decision": {"enum": ["append", "reject"]},
        "state": {"enum": ["applied", "rejected"]},
        "created_section_ids": array(UUID),
        "draft_revision": nullable(REV),
        "snapshot_id": nullable(UUID),
        "snapshot_digest": nullable(SHA),
        "resolved_at": TIME,
        "command": command(RESOLVE),
    }
)
SUMMARY = object_schema(
    {
        "candidate_id": UUID,
        "bid_id": UUID,
        "draft_id": UUID,
        "candidate_digest": SHA,
        "source": SOURCE,
        "base_draft_revision": REV,
        "method_digest": SHA,
        "state": {"enum": ["ready", "blocked", "applied", "rejected"]},
        "created_at": TIME,
        "created_by": UUID,
        "section_count": {"type": "integer", "minimum": 0},
        "image_count": {"type": "integer", "minimum": 0},
        "warning_count": {"type": "integer", "minimum": 0},
        "blocker_count": {"type": "integer", "minimum": 0},
    }
)
SCHEMAS = {
    "AuthoringWordImportJson": {
        "oneOf": [
            {"type": "null"},
            {"type": "boolean"},
            {"type": "number"},
            TEXT,
            array(JSON),
            {"type": "object", "additionalProperties": JSON},
        ]
    },
    "AuthoringWordImportPrepareRequest": PREPARE,
    "AuthoringWordImportResolveRequest": RESOLVE,
    "AuthoringWordImportResult": RESULT,
    "AuthoringWordImportCandidate": object_schema(
        {
            **SUMMARY["properties"],
            "protocol": {"const": "authoring-word-import-candidate/1"},
            "base_snapshot_id": UUID,
            "base_draft_etag": TEXT,
            "before_digest": SHA,
            "existing_sections": array(
                object_schema(
                    {
                        "section_id": UUID,
                        "parent_id": nullable(UUID),
                        "ordinal": {"type": "integer", "minimum": 0},
                        "title": TEXT,
                    }
                )
            ),
            "method": JSON,
            "sections": array(SECTION),
            "mapping": array(
                object_schema(
                    {
                        "source_path": TEXT,
                        "section_key": UUID,
                        "node_id": UUID,
                        "kind": TEXT,
                    }
                )
            ),
            "images": array(IMAGE),
            "issues": array(ISSUE),
            "can_apply": {"type": "boolean"},
            "current_validity": {"const": "rechecked_on_append"},
            "append_only": {"const": True},
            "reason": REASON,
            "preparation": command(PREPARE),
            "resolution": nullable(ref("AuthoringWordImportResult")),
        }
    ),
    "AuthoringWordImportPage": object_schema(
        {
            "bid_id": UUID,
            "draft_id": UUID,
            "items": array(SUMMARY),
            "next_cursor": nullable(UUID),
            "has_more": {"type": "boolean"},
        }
    ),
    "AuthoringWordImportCapabilities": object_schema(
        {
            "enabled": {"type": "boolean"},
            "unavailable_reason": nullable(object_schema({"code": TEXT, "message": TEXT})),
            "method_digest": SHA,
            "method": JSON,
            "supported": array(TEXT),
            "limitations": array(TEXT),
            "limits": object_schema(
                {
                    "max_docx_bytes": REV,
                    "max_candidate_bytes": REV,
                    "max_sections": REV,
                    "max_images": REV,
                }
            ),
            "append_only": {"const": True},
            "requires_registered_original": {"const": True},
            "requires_loss_acknowledgement": {"const": True},
        }
    ),
}


def validate(name, value):
    if not Draft202012Validator(
        {"components": {"schemas": SCHEMAS}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value):
        raise DomainError("AUTHORING_WORD_IMPORT_INVALID", "Word 导入字段不符合实际协议", 422)
    return value


def extend_openapi(document):
    operations = (
        (
            "/api/v1/authoring/word-import-capabilities",
            "get",
            None,
            "AuthoringWordImportCapabilities",
            "getAuthoringWordImportCapabilities",
        ),
        (BASE, "get", None, "AuthoringWordImportPage", "listAuthoringWordImports"),
        (
            BASE,
            "post",
            "AuthoringWordImportPrepareRequest",
            "AuthoringWordImportCandidate",
            "prepareAuthoringWordImport",
        ),
        (
            BASE + "/{candidate_id}",
            "get",
            None,
            "AuthoringWordImportCandidate",
            "getAuthoringWordImport",
        ),
        (
            BASE + "/{candidate_id}/resolve",
            "post",
            "AuthoringWordImportResolveRequest",
            "AuthoringWordImportResult",
            "resolveAuthoringWordImport",
        ),
    )
    registered = [item for item in operations if item[1] in document["paths"].get(item[0], {})]
    if not registered:
        return
    document.setdefault("components", {}).setdefault("schemas", {}).update(deepcopy(SCHEMAS))
    for path, verb, request, response, identity in registered:
        operation = document["paths"][path][verb]
        operation["operationId"] = identity
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {
            "201" if request == "AuthoringWordImportPrepareRequest" else "200": {
                "description": "精确外部 Word 候选与明确追加回执",
                "content": {"application/json": {"schema": ref(response)}},
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
        if request:
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": ref(request)}},
            }
            operation.setdefault("parameters", []).extend(
                {
                    "name": header,
                    "in": "header",
                    "required": header != "If-Match"
                    or request == "AuthoringWordImportPrepareRequest",
                    "schema": {"type": "string", "minLength": 1, "maxLength": 128},
                }
                for header in ("Origin", "X-CSRF-Token", "Idempotency-Key", "If-Match")
            )
    image = document["paths"].get(BASE + "/{candidate_id}/images/{image_key}", {}).get("get")
    if image is not None:
        image["operationId"] = "getAuthoringWordImportImage"
        image["security"] = [{"SessionCookie": []}]
        image["responses"] = {
            "200": {
                "description": "按候选固定摘要核验的私有 PNG 图片预览",
                "headers": {
                    "X-Content-SHA256": {
                        "description": "实际返回 PNG 字节的 SHA-256",
                        "schema": SHA,
                    },
                    "Cache-Control": {"schema": {"const": "private, no-store"}},
                    "X-Content-Type-Options": {"schema": {"const": "nosniff"}},
                },
                "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
