"""Implemented independent original-file parsing. No implicit head or review change."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.domain.runtime import DomainError

BASE = "/api/v1/bids/{bid_id}/documents/{document_version_id}"
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
FALSE_FLAGS = {
    key: {"const": False} for key in ("current_body_changed", "automatically_started_review")
}
METHOD = object_schema(
    {
        "protocol": {"const": "document-parse-method/1"},
        "mode": {"enum": ["physical_text_only", "configured_local"]},
        "parser_digest": SHA,
        "config_digest": SHA,
        "implementation_digest": SHA,
        "max_bytes": {"const": 104857600},
        "max_pages": {"const": 1000},
    }
)
CONTEXT = object_schema(
    {
        "protocol": {"const": "document-parse-context/1"},
        "bid_id": UUID,
        "document_version_id": UUID,
        "document": object_schema(
            {
                "sha256": SHA,
                "byte_size": {"type": "integer", "minimum": 1, "maximum": 104857600},
                "media_type": {"const": "application/pdf"},
                "filename": {"type": "string", "minLength": 1, "maxLength": 4096},
                "file_id": UUID,
                "file_revision": {"type": "integer", "minimum": 1},
                "role": {"enum": ["body", "tender", "supplement", "drawing", "boq"]},
                "artifact_kind": {"enum": ["source_original", "bid_body"]},
                "locator_digest": SHA,
            }
        ),
        "qualification": object_schema(
            {"kind": {"enum": ["verified_upload", "adopted_generated"]}, "identity_digest": SHA}
        ),
        "source": object_schema(
            {
                "root_id": UUID,
                "state": {"enum": ["unregistered", "published"]},
                "authority_digest": SHA,
            }
        ),
        "method": METHOD,
        "word_coverage_claimed": {"const": False},
        **FALSE_FLAGS,
    }
)
RESULT = object_schema(
    {
        "parse_run_id": UUID,
        "document_version_id": UUID,
        "source_digest": SHA,
        "parser_digest": SHA,
        "config_digest": SHA,
        "parsed_digest": SHA,
        "coverage": {"enum": ["complete", "partial", "failed"]},
        "page_count": {"type": "integer", "minimum": 0, "maximum": 1000},
        "evidence_count": {"type": "integer", "minimum": 0, "maximum": 100000},
        "gaps": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000}},
        "gap_count": {"type": "integer", "minimum": 0, "maximum": 10000},
        "word_coverage_claimed": {"const": False},
    }
)
OPERATION = object_schema(
    {
        "id": UUID,
        "kind": {"const": "parse-document"},
        "state": {
            "enum": ["queued", "running", "cancel_requested", "cancelled", "succeeded", "failed"]
        },
        "input_digest": SHA,
        "handler_version": {"const": "document-parse/1"},
        "error_code": {"type": ["string", "null"]},
        "created_at": TIME,
        "finished_at": {"anyOf": [TIME, {"type": "null"}]},
    }
)
SCHEMAS = {
    "DocumentParseContext": object_schema({"context": CONTEXT, "context_digest": SHA}),
    "StartDocumentParse": object_schema(
        {
            "context_digest": SHA,
            "reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
                "pattern": r"\S",
                "not": {"pattern": r"[\u0000-\u001F\uD800-\uDFFF]"},
            },
        }
    ),
    "DocumentParseView": object_schema(
        {
            "protocol": {"const": "document-parse-request/1"},
            "id": UUID,
            "bid_id": UUID,
            "document_version_id": UUID,
            "actor_id": UUID,
            "created_at": TIME,
            "context": CONTEXT,
            "context_digest": SHA,
            "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
            "operation": OPERATION,
            "result": {"anyOf": [RESULT, {"type": "null"}]},
            **FALSE_FLAGS,
        }
    ),
    "DocumentParseStarted": object_schema(
        {
            "protocol": {"const": "document-parse-start/1"},
            "actor_id": UUID,
            "command_id": UUID,
            "request_digest": SHA,
            "reused": {"type": "boolean"},
            "request": {"$ref": "#/components/schemas/DocumentParseView"},
        }
    ),
    "DocumentParsePage": object_schema(
        {
            "bid_id": UUID,
            "document_version_id": UUID,
            "items": {
                "type": "array",
                "maxItems": 50,
                "items": {"$ref": "#/components/schemas/DocumentParseView"},
            },
            "has_more": {"type": "boolean"},
            "next_cursor": {"type": ["string", "null"], "maxLength": 4096},
        }
    ),
}


def validate(name, value):
    if not Draft202012Validator(
        {"components": {"schemas": SCHEMAS}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value):
        raise DomainError("DOCUMENT_PARSE_INVALID", "原件解析字段不符合协议", 422)
    return value


def extend_openapi(document):
    operations = (
        (BASE + "/parse-context", "get", "getDocumentParseContext", "DocumentParseContext"),
        (BASE + "/parse-requests", "get", "listDocumentParseRequests", "DocumentParsePage"),
        (BASE + "/parse-requests", "post", "startDocumentParse", "DocumentParseStarted"),
        (
            BASE + "/parse-requests/{request_id}",
            "get",
            "getDocumentParseRequest",
            "DocumentParseView",
        ),
    )
    registered = [entry for entry in operations if entry[1] in document["paths"].get(entry[0], {})]
    if not registered:
        return
    document["components"]["schemas"].update(deepcopy(SCHEMAS))
    for path, verb, name, response in registered:
        operation = document["paths"][path][verb]
        operation["operationId"] = name
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {
            "202" if verb == "post" else "200": {
                "description": "精确单文件解析记录，不自动采用正文或启动评审",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + response}}
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
        if verb == "post":
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/StartDocumentParse"}
                    }
                },
            }
            operation.setdefault("parameters", []).extend(
                {
                    "name": header,
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "minLength": 1, "maxLength": 128},
                }
                for header in ("Origin", "X-CSRF-Token", "Idempotency-Key")
            )
