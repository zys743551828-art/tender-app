"""Implemented package storage requests and responses; distinct from review readiness."""

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.runtime import DomainError
from packages.identity.contracts import HISTORICAL_SNAPSHOT

MANIFEST = json.loads(
    (Path(__file__).parent / "schemas/bid-package.schema.json").read_text(encoding="utf-8")
)


def relocate(value):
    if isinstance(value, dict):
        return {
            k: (
                v.replace("#/$defs/", "#/components/schemas/BidPackage_")
                if k == "$ref"
                else relocate(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [relocate(v) for v in value]
    return value


def object_schema(properties, required=None):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required if required is not None else list(properties),
    }


UUID = {"type": "string", "format": "uuid"}
IDENTIFIER = {
    "type": "string",
    "minLength": 1,
    "maxLength": 200,
    "pattern": r"\S",
    # PostgreSQL jsonb rejects NUL; canonical UTF-8 rejects isolated surrogates.
    # Scalar values outside the BMP remain valid (e.g. Chinese plus emoji).
    "not": {"pattern": r"[\u0000\uD800-\uDFFF]"},
}
PART = deepcopy(MANIFEST["$defs"]["part"])
for _field in ("part_id", "category"):
    PART["properties"][_field] = deepcopy(IDENTIFIER)
MEMBER = object_schema(
    {
        "member_id": IDENTIFIER,
        "document_version_id": UUID,
        "parse_run_id": UUID,
        "purposes": {"type": "array", "items": IDENTIFIER, "minItems": 1, "uniqueItems": True},
        "parts": {"type": "array", "items": PART},
    },
    ["member_id", "document_version_id", "purposes", "parts"],
)
MEMBERS = {"type": "array", "items": MEMBER, "minItems": 1, "maxItems": 500}
SCHEMAS = {
    "CreateBidPackage": object_schema({"kind": {"enum": ["authority", "bid"]}, "members": MEMBERS}),
    "AppendBidPackage": object_schema({"members": MEMBERS}),
    "BidPackageManifest": relocate(
        {k: v for k, v in MANIFEST.items() if k not in {"$id", "$schema", "$defs"}}
    ),
    **{"BidPackage_" + k: relocate(v) for k, v in MANIFEST["$defs"].items()},
    "BidPackageStoredView": object_schema(
        {
            "manifest": {"$ref": "#/components/schemas/BidPackageManifest"},
            "digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "identity": deepcopy(HISTORICAL_SNAPSHOT),
            "storage_eligible": {"type": "boolean"},
            "review_ready": {"const": False},
        }
    ),
}

SCHEMAS.update(
    {
        "BidPackageHead": object_schema(
            {
                "id": UUID,
                "bid_id": UUID,
                "kind": {"enum": ["authority", "bid"]},
                "revision_id": UUID,
                "revision": {"type": "integer", "minimum": 1},
                "digest": {"type": "string"},
            }
        ),
        "BidPackageRevisionSummary": object_schema(
            {
                "id": UUID,
                "package_id": UUID,
                "revision": {"type": "integer", "minimum": 1},
                "digest": {"type": "string"},
                "created_at": {"type": "string", "format": "date-time"},
            }
        ),
        "BidPackageDocument": object_schema(
            {
                "id": UUID,
                "bid_id": UUID,
                "file_id": UUID,
                "file_revision": {"type": "integer", "minimum": 1},
                "filename": {"type": "string"},
                "role": {"enum": ["tender", "supplement", "drawing", "boq", "body"]},
                "artifact_kind": {
                    "enum": [
                        "bid_body",
                        "review_report",
                        "annotated_review_copy",
                        "source_original",
                        "research_artifact",
                    ]
                },
                "sha256": {"type": "string"},
                "verified_upload": {"type": "boolean"},
            }
        ),
        "BidPackageParse": object_schema(
            {
                "id": UUID,
                "document_version_id": UUID,
                "coverage": {"enum": ["complete", "partial", "failed"]},
                "page_count": {"type": "integer", "minimum": 0},
                "gaps": {"type": "array", "items": {}},
                "parser_digest": {"type": "string"},
                "config_digest": {"type": "string"},
                "created_at": {"type": "string", "format": "date-time"},
            }
        ),
    }
)
for _name in (
    "BidPackageHead",
    "BidPackageRevisionSummary",
    "BidPackageDocument",
    "BidPackageParse",
):
    SCHEMAS[_name + "Page"] = object_schema(
        {
            "items": {"type": "array", "items": {"$ref": "#/components/schemas/" + _name}},
            "has_more": {"type": "boolean"},
            "next_cursor": {"type": ["string", "null"]},
        }
    )


def validate(name, body):
    if not Draft202012Validator(SCHEMAS[name], format_checker=FormatChecker()).is_valid(body):
        raise DomainError("INVALID_REQUEST", "资料包字段不符合协议", 422)


def extend_openapi(actual):
    actual["components"]["schemas"].update(deepcopy(SCHEMAS))
    base = "/api/v1/bids/{bid_id}/packages"
    for suffix, method, operation_id, request in [
        ("", "post", "createBidPackage", "CreateBidPackage"),
        ("/{package_id}", "get", "getBidPackageHead", None),
        ("/{package_id}/revisions", "post", "appendBidPackageRevision", "AppendBidPackage"),
        ("/{package_id}/revisions/{revision_id}", "get", "getBidPackageRevision", None),
        ("/{package_id}/revisions/{revision_id}/manifest", "get", "getBidPackageManifest", None),
    ]:
        op = actual["paths"][base + suffix][method]
        op["operationId"] = operation_id
        op["security"] = [{"SessionCookie": []}]
        if request:
            op["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + request}}
                },
            }
            op.setdefault("parameters", []).extend(
                {"in": "header", "name": header, "required": True, "schema": {"type": "string"}}
                for header in ["Idempotency-Key", "Origin", "X-CSRF-Token"]
                + (["If-Match"] if suffix else [])
            )
        raw = operation_id == "getBidPackageManifest"
        op["responses"] = {
            "201" if request else "200": {
                "description": "Immutable storage only; review_ready remains false. Manifest uses canonical UTF-8 bytes."
                if raw
                else "Frozen package and identity; storage eligibility does not prove business readiness.",
                "headers": {"ETag": {"schema": {"type": "string"}}},
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": "#/components/schemas/"
                            + ("BidPackageManifest" if raw else "BidPackageStoredView")
                        }
                    }
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
    for path, operation_id, schema in [
        (base, "listBidPackages", "BidPackageHeadPage"),
        (
            base + "/{package_id}/revisions",
            "listBidPackageRevisions",
            "BidPackageRevisionSummaryPage",
        ),
        (
            "/api/v1/bids/{bid_id}/package-documents",
            "listBidPackageDocuments",
            "BidPackageDocumentPage",
        ),
        (
            "/api/v1/bids/{bid_id}/package-documents/{document_version_id}/parses",
            "listBidPackageParses",
            "BidPackageParsePage",
        ),
    ]:
        op = actual["paths"][path]["get"]
        op["operationId"] = operation_id
        op["security"] = [{"SessionCookie": []}]
        op["responses"] = {
            "200": {
                "description": "Scoped explicit discovery; parse coverage does not establish freezing eligibility.",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + schema}}
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
