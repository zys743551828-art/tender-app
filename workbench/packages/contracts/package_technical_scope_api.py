"""Exact current package technical scope declarations; no scoring or model authority."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import IDENTIFIER, UUID, object_schema
from packages.contracts.bid_package_api import SCHEMAS as PACKAGE_SCHEMAS
from packages.contracts.bid_package_requirements_api import SCHEMAS as INVENTORY_SCHEMAS
from packages.contracts.openapi_dependencies import schema_closure, schema_references
from packages.domain.runtime import DomainError

SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TEXT = {
    "type": "string",
    "minLength": 1,
    "maxLength": 2000,
    "pattern": r"\S",
    "not": {"pattern": r"[\u0000\uD800-\uDFFF]"},
}
DATE = {"type": "string", "format": "date-time"}
NULL = {"type": "null"}
IDS = {"type": "array", "items": IDENTIFIER, "uniqueItems": True, "maxItems": 2000}
JSON = {"type": "object"}
FLAGS = {
    key: {"const": False}
    for key in (
        "inventory_complete",
        "scoring_ready",
        "formal_scoring_eligible",
        "model_execution_enabled",
        "training_eligible",
    )
}
LIMITS = {
    "members": 500,
    "parts": 2000,
    "rules": 1000,
    "source_rows": 20000,
    "blocks": 100000,
    "pages": 100000,
    "request_bytes": 1024 * 1024,
    "snapshot_bytes": 32 * 1024 * 1024,
    "original_bytes": 1024 * 1024 * 1024,
}
METHOD_SOURCES = (
    "packages/domain/package_technical_scope.py",
    "packages/domain/bid_package_technical_scope_repository.py",
    "packages/domain/bid_package_technical_scope_service.py",
    "packages/contracts/package_technical_scope_api.py",
    "packages/contracts/sql/bid-package-technical-scopes.sql",
    "packages/domain/bid_package_review_documents.py",
    "packages/domain/bid_package_repository.py",
    "packages/rag/indexing.py",
)
RULE_SCOPE = object_schema(
    {
        "rule_id": UUID,
        "rule_digest": SHA,
        "selection": {"enum": ["include", "exclude", "unclassified"]},
        "part_ids": IDS,
        "reason": TEXT,
    }
)
REQUEST = object_schema(
    {
        "purpose": {"const": "current_prebid"},
        "package_digest": SHA,
        "authority_revision_id": UUID,
        "authority_digest": SHA,
        "inventory_id": UUID,
        "inventory_digest": SHA,
        "technical_part_ids": IDS | {"minItems": 1},
        "rule_scopes": {"type": "array", "items": RULE_SCOPE, "maxItems": LIMITS["rules"]},
        "reason": TEXT,
    }
)
FREEZE = object_schema({"request": REQUEST, "preview_digest": SHA})
SCOPE = object_schema(
    {"bid_id": UUID, "package_id": UUID, "revision_id": UUID, "inventory_id": UUID}
)
METHOD = object_schema(
    {
        "version": {"const": "package-technical-scope-policy/1"},
        "digest": SHA,
        "sources": object_schema({name: SHA for name in METHOD_SOURCES}),
        "limits": object_schema({k: {"const": v} for k, v in LIMITS.items()}),
    }
)
TIMING = object_schema(
    {
        "purpose": {"const": "current_prebid"},
        "historical_as_of": NULL,
        "submitted_at": NULL,
        "label_known_at": NULL,
        "training_frozen_at": NULL,
        "submission_split_at": NULL,
        "label_available_as_of": NULL,
        "historical_qualification": {"const": "not_established"},
    }
)
GAP = object_schema(
    {
        "id": SHA,
        "code": IDENTIFIER,
        "subject": {"type": ["string", "null"], "maxLength": 200},
        "message": TEXT,
    }
)
BLOCK = object_schema(
    {
        "id": UUID,
        "physical_page": {"type": "integer", "minimum": 1},
        "ordinal": {"type": "integer", "minimum": 0},
        "kind": {"enum": ["text", "table", "visual_observation"]},
        "text_content": {"type": "string", "not": {"pattern": r"[\u0000\uD800-\uDFFF]"}},
        "digest": SHA,
        "bbox_json": {"type": ["string", "null"]},
        "structure_json": {"type": ["string", "null"]},
    }
)
PAGE = object_schema(
    {
        "physical_page": {"type": "integer", "minimum": 1},
        "quality": {"enum": ["usable", "partial", "failed"]},
        "gaps": {"type": "array", "items": {"type": "string"}},
    }
)
DOCUMENT = object_schema(
    {
        "package_role": {"enum": ["target", "authority"]},
        "member_id": IDENTIFIER,
        "document_version_id": UUID,
        "file_digest": SHA,
        "byte_size": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
        "parse": deepcopy(PACKAGE_SCHEMAS["BidPackage_parseIdentity"]),
        "page_count": {"type": ["integer", "null"], "minimum": 1},
        "pages": {"type": "array", "items": PAGE, "maxItems": LIMITS["pages"]},
        "blocks": {"type": "array", "items": BLOCK, "maxItems": LIMITS["blocks"]},
    }
)
PART = object_schema(
    {
        "member_id": IDENTIFIER,
        "document_version_id": UUID,
        "file_digest": SHA,
        "part": deepcopy(PACKAGE_SCHEMAS["BidPackage_part"]),
        "selected": {"type": "boolean"},
        "read_physical_pages": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "block_ids": {"type": "array", "items": UUID},
        "text_evidence_present": {"type": "boolean"},
        "visual_coverage": {"const": "unproven"},
    }
)
RULE = object_schema(
    {
        **RULE_SCOPE["properties"],
        "rule_snapshot": JSON,
        "requirement_digest": SHA,
        "declared_target_part_ids": IDS,
        "source_evidence": {
            "type": "array",
            "items": object_schema(
                {
                    "member_id": IDENTIFIER,
                    "document_version_id": UUID,
                    "file_digest": SHA,
                    "parse_run_id": UUID,
                    "physical_page": {"type": "integer", "minimum": 1},
                    "evidence_id": UUID,
                    "evidence_digest": SHA,
                    "text_content": {"type": "string"},
                    "part_ids": IDS,
                }
            ),
        },
    }
)
BASIS = object_schema(
    {
        "package_digest": SHA,
        "authority_revision_id": UUID,
        "authority_digest": SHA,
        "inventory_digest": SHA,
        "rule_set_id": UUID,
        "rule_set_digest": SHA,
        "identity_digest": SHA,
    }
)
COVERAGE = object_schema(
    {
        "state": {"enum": ["partial", "unknown"]},
        "all_part_count": {"type": "integer", "minimum": 0},
        "selected_part_count": {"type": "integer", "minimum": 0},
        "all_scoring_rule_count": {"type": "integer", "minimum": 0},
        "included_rule_count": {"type": "integer", "minimum": 0},
        "frozen_parse_member_count": {"type": "integer", "minimum": 0},
        "gaps": {"type": "array", "items": GAP},
        "visual_coverage": {"const": "unproven"},
        "required_range_completeness": {"const": "unproven"},
    }
)
PREVIEW_MANIFEST = object_schema(
    {
        "version": {"const": "package-technical-scope-preview/1"},
        "scope": SCOPE,
        "basis": BASIS,
        "method": METHOD,
        "request": REQUEST,
        "request_digest": SHA,
        "context_digest": SHA,
        "parts": {"type": "array", "items": PART, "maxItems": LIMITS["parts"]},
        "rules": {"type": "array", "items": RULE, "maxItems": LIMITS["rules"]},
        "documents": {"type": "array", "items": DOCUMENT, "maxItems": 2 * LIMITS["members"]},
        "source_snapshot": {"type": "array", "items": JSON, "maxItems": LIMITS["source_rows"]},
        "coverage": COVERAGE,
        "timing": TIMING,
        "original_bytes_verified": {"const": False},
        **FLAGS,
    }
)
PREVIEW = object_schema({"manifest": PREVIEW_MANIFEST, "digest": SHA})
ORIGINAL = object_schema(
    {
        "document_version_id": UUID,
        "digest": SHA,
        "byte_size": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
    }
)
MANIFEST = object_schema(
    {
        "version": {"const": "package-technical-scope/1"},
        "id": UUID,
        "actor_id": UUID,
        "command_id": UUID,
        "frozen_at": DATE,
        "preview": PREVIEW,
        "original_verification": object_schema(
            {
                "state": {"const": "verified_at_recording"},
                "verified_at": DATE,
                "files": {
                    "type": "array",
                    "items": ORIGINAL,
                    "minItems": 1,
                    "maxItems": LIMITS["source_rows"],
                },
            }
        ),
        **FLAGS,
    }
)
VIEW = object_schema({"manifest": MANIFEST, "digest": SHA})
COMMAND = object_schema(
    {
        "command_id": UUID,
        "actor_id": UUID,
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
        "request_digest": SHA,
        "request": FREEZE,
        "if_match": {"type": "string", "minLength": 1},
    }
)
SCHEMAS = {
    "PackageTechnicalScopeRequest": REQUEST,
    "FreezePackageTechnicalScope": FREEZE,
    "PackageTechnicalScopePreview": PREVIEW,
    "PackageTechnicalScopeView": VIEW,
    "PackageTechnicalScopeApplied": object_schema({"scope": VIEW, "command": COMMAND}),
    "PackageTechnicalScopeContext": object_schema(
        {
            "target": {"$ref": "#/components/schemas/BidPackageStoredView"},
            "authority": {"$ref": "#/components/schemas/BidPackageStoredView"},
            "inventory": {"$ref": "#/components/schemas/PackageRequirementInventoryView"},
            "method": METHOD,
            "context_digest": SHA,
            "etag": {"type": "string"},
            "can_freeze": {"type": "boolean"},
            "blocking_reasons": {"type": "array", "items": GAP},
            "catalog_complete": {"const": True},
            "timing": TIMING,
            **FLAGS,
        }
    ),
    "PackageTechnicalScopePage": object_schema(
        {
            "items": {
                "type": "array",
                "items": object_schema(
                    {
                        "id": UUID,
                        "digest": SHA,
                        "inventory_id": UUID,
                        "created_at": DATE,
                        "coverage_state": {"enum": ["partial", "unknown"]},
                        "selected_part_count": {"type": "integer", "minimum": 0},
                        "included_rule_count": {"type": "integer", "minimum": 0},
                        "scoring_ready": {"const": False},
                    }
                ),
                "maxItems": 50,
            },
            "has_more": {"type": "boolean"},
            "next_cursor": {"type": ["string", "null"]},
        }
    ),
}


def validate(name, body):
    schemas = {**PACKAGE_SCHEMAS, **INVENTORY_SCHEMAS, **SCHEMAS}
    schema = {"$ref": "#/components/schemas/" + name, "components": {"schemas": schemas}}
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(body):
        raise DomainError("PACKAGE_TECHNICAL_SCOPE_INVALID", "技术范围字段不符合精确冻结协议", 422)
    return body


def extend_openapi(actual):
    base = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"
    operations = [
        (
            "/technical-scope-context",
            "get",
            "getPackageTechnicalScopeContext",
            None,
            "PackageTechnicalScopeContext",
            "200",
        ),
        (
            "/technical-scope-previews",
            "post",
            "previewPackageTechnicalScope",
            "PackageTechnicalScopeRequest",
            "PackageTechnicalScopePreview",
            "200",
        ),
        (
            "/technical-scopes",
            "post",
            "freezePackageTechnicalScope",
            "FreezePackageTechnicalScope",
            "PackageTechnicalScopeApplied",
            "201",
        ),
        (
            "/technical-scopes",
            "get",
            "listPackageTechnicalScopes",
            None,
            "PackageTechnicalScopePage",
            "200",
        ),
        (
            "/technical-scopes/{scope_id}",
            "get",
            "getPackageTechnicalScope",
            None,
            "PackageTechnicalScopeView",
            "200",
        ),
    ]
    roots = set()
    for suffix, method, identity, request, response, status in operations:
        operation = actual.get("paths", {}).get(base + suffix, {}).get(method)
        if operation is None:
            continue
        operation["operationId"] = identity
        operation["security"] = [{"SessionCookie": []}]
        if request:
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + request}}
                },
            }
            headers = ["Origin", "X-CSRF-Token"] + (
                ["If-Match", "Idempotency-Key"] if status == "201" else []
            )
            existing = {(p.get("in"), p.get("name")) for p in operation.get("parameters", [])}
            operation.setdefault("parameters", []).extend(
                {"in": "header", "name": name, "required": True, "schema": {"type": "string"}}
                for name in headers
                if ("header", name) not in existing
            )
        operation["responses"] = {
            status: {
                "description": "Immutable declaration and exact evidence; all execution and training qualifications remain false.",
                "headers": {"ETag": {"schema": {"type": "string"}}},
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + response}}
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
        roots.update(schema_references(operation))
    if roots:
        available = {**PACKAGE_SCHEMAS, **INVENTORY_SCHEMAS, **SCHEMAS}
        schemas = actual.setdefault("components", {}).setdefault("schemas", {})
        required = schema_closure(schemas | available, roots)
        schemas.update({name: value for name, value in required.items() if name in available})
