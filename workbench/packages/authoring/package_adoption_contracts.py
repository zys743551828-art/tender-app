"""Actual generated-file package adoption; no implicit review or body-head switch."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import MEMBER, UUID, object_schema
from packages.contracts.bid_package_api import SCHEMAS as PACKAGE_SCHEMAS
from packages.domain.runtime import DomainError

PATH = "/api/v1/bids/{bid_id}/builds/{build_id}/package-adoptions"
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
OUTPUT = object_schema(
    {
        "protocol": {"const": "authoring-build-output/1"},
        "bid_id": UUID,
        "build_id": UUID,
        "document_version_id": UUID,
        "format": {"enum": ["docx", "pdf"]},
        "sha256": SHA,
        "byte_size": {"type": "integer", "minimum": 1},
        "build_identity": object_schema(
            {
                "draft_id": UUID,
                "draft_revision": {"type": "integer", "minimum": 1},
                "snapshot_id": UUID,
                "snapshot_digest": SHA,
                "build_input_id": UUID,
                "input_digest": SHA,
                "manifest_digest": SHA,
                "writer_kind": {
                    "enum": [
                        "strict_text/1",
                        "structured_text/1",
                        "generated_text/2",
                        "generated_rich/3",
                    ]
                },
            }
        ),
        "word_document_version_id": UUID,
        "word_sha256": SHA,
        "word_pdf_relation": {"enum": ["verified", "not_applicable"]},
        "publication_receipt_digest": SHA,
        "source_authority_digest": SHA,
        "direct_source_ids": {"type": "array", "items": UUID, "uniqueItems": True},
    }
)
SCHEMAS = {
    **deepcopy(PACKAGE_SCHEMAS),
    "AuthoringOutputQualification": OUTPUT,
    "AdoptAuthoringOutput": object_schema(
        {
            "snapshot_id": UUID,
            "snapshot_digest": SHA,
            "package_id": {"anyOf": [UUID, {"type": "null"}]},
            "member": deepcopy(MEMBER),
            "reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
                "pattern": r"\S",
                "not": {"pattern": r"[\u0000-\u001F\uD800-\uDFFF]"},
            },
        }
    ),
    "AuthoringOutputAdopted": object_schema(
        {
            "protocol": {"const": "authoring-output-adoption/1"},
            "bid_id": UUID,
            "build_id": UUID,
            "actor_id": UUID,
            "command_id": UUID,
            "request_digest": SHA,
            "output": {"$ref": "#/components/schemas/AuthoringOutputQualification"},
            "package": {"$ref": "#/components/schemas/BidPackageStoredView"},
            "package_etag": {"type": "string", "minLength": 1, "maxLength": 200},
            "automatically_started_review": {"const": False},
            "current_body_changed": {"const": False},
        }
    ),
}


def validate(name, value):
    schema = {"components": {"schemas": SCHEMAS}, "allOf": [SCHEMAS[name]]}
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value):
        raise DomainError("AUTHORING_ADOPTION_INVALID", "生成文件采用字段不符合协议", 422)
    return value


def extend_openapi(document):
    if "post" not in document["paths"].get(PATH, {}):
        return
    document["components"]["schemas"].update(deepcopy(SCHEMAS))
    operation = document["paths"][PATH]["post"]
    operation["operationId"] = "adoptAuthoringOutputToPackage"
    operation["security"] = [{"SessionCookie": []}]
    operation["requestBody"] = {
        "required": True,
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/AdoptAuthoringOutput"}}
        },
    }
    operation["responses"] = {
        "201": {
            "description": "所选投标包的新冻结修订与精确生成文件采用回执",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AuthoringOutputAdopted"}
                }
            },
        },
        "default": {"$ref": "#/components/responses/DomainError"},
    }
    operation.setdefault("parameters", []).extend(
        {
            "name": name,
            "in": "header",
            "required": name != "If-Match",
            "schema": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200 if name == "If-Match" else 128,
            },
        }
        for name in ("Origin", "X-CSRF-Token", "Idempotency-Key", "If-Match")
    )
