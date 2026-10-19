"""Requirements projections / human coverage declarations, never formal review output."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import IDENTIFIER, UUID, object_schema
from packages.contracts.bid_package_api import SCHEMAS as PACKAGE_SCHEMAS
from packages.domain.runtime import DomainError

SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
IDS = {"type": "array", "items": UUID, "uniqueItems": True, "maxItems": 500}
TEXTS = {"type": "array", "items": IDENTIFIER, "uniqueItems": True, "maxItems": 500}
NULL_SHA = {"anyOf": [SHA, {"type": "null"}]}
INSPECTED_RANGE = deepcopy(PACKAGE_SCHEMAS["BidPackage_inspectedRange"])
INSPECTED_RANGE["properties"]["part_id"] = deepcopy(IDENTIFIER)
STATES = [
    "not_provided",
    "missing",
    "pending_parse",
    "parse_gap",
    "unsupported",
    "verified",
    "not_applicable",
    "conflict",
    "unknown",
]
MAPPING = object_schema(
    {
        "rule_id": UUID,
        "categories": TEXTS | {"minItems": 1},
        "target_part_ids": TEXTS,
        "minimum_count": {"type": ["integer", "null"], "minimum": 0, "maximum": 9007199254740991},
        "applicability": {"enum": ["applicable", "unknown", "not_applicable"]},
        "applicability_evidence_ids": IDS,
        "valid_at": {"type": ["string", "null"], "format": "date-time"},
        "checks": TEXTS,
        "reason": IDENTIFIER,
        "basis_evidence_ids": IDS | {"minItems": 1},
    }
)
RESULT = object_schema(
    {
        "rule_id": UUID,
        "requirement_digest": SHA,
        "state": {"enum": STATES},
        "inspected": {
            "type": "array",
            "items": INSPECTED_RANGE,
        },
        "evidence_ids": IDS,
        "reason": IDENTIFIER,
        "basis_type": {"enum": ["human_scope_declaration", "human_observation"]},
    }
)
RESULT["allOf"] = [
    {
        "if": {"properties": {"state": {"enum": ["verified", "not_applicable"]}}},
        "then": {"properties": {"basis_type": {"const": "human_scope_declaration"}}},
        "else": {"properties": {"basis_type": {"const": "human_observation"}}},
    }
]

BINDING = object_schema(
    {
        "rule_id": UUID,
        "rule_digest": SHA,
        "rule_snapshot": {"type": "object"},
        "decision_id": {"type": ["string", "null"], "format": "uuid"},
        "decision_snapshot": {"type": ["object", "null"]},
        "requirement": {"$ref": "#/components/schemas/BidPackage_requirement"},
        "requirement_digest": SHA,
        "source_bound": {"type": "boolean"},
        "annotation": object_schema(
            {
                "kind": {"const": "human_check_plan_declaration"},
                "mapped": {"type": "boolean"},
                "reason": {"anyOf": [IDENTIFIER, {"type": "null"}]},
                "basis_evidence_ids": IDS,
            }
        ),
    }
)
INVENTORY_V1 = object_schema(
    {
        "version": {"const": "bid-package-requirements/1"},
        "id": UUID,
        "bid_id": UUID,
        "package_id": UUID,
        "target_revision_id": UUID,
        "package_digest": SHA,
        "authority_revision_id": UUID,
        "authority_digest": SHA,
        "rule_set_id": UUID,
        "rule_set_digest": SHA,
        "revision": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
        "predecessor_digest": NULL_SHA,
        "identity_digest": SHA,
        "source_snapshot": {"type": "array", "items": {"type": "object"}},
        "requirements": {"type": "array", "items": BINDING},
        "inventory_complete": {"const": False},
        "extraction_binding": {"const": "unproven_legacy_rule_set"},
        "review_ready": {"const": False},
        "actor_id": UUID,
    }
)
INVENTORY_V2 = deepcopy(INVENTORY_V1)
INVENTORY_V2["properties"]["version"] = {"const": "bid-package-requirements/2"}
INVENTORY_V2["properties"]["extraction_binding"] = {"const": "exact_frozen_input_result"}
INVENTORY_V2["properties"].update(
    {
        "extraction_input_digest": SHA,
        "extraction_result_digest": SHA,
        "extraction_result_id": UUID,
        "extraction_range_status": {"const": "all_frozen_evidence_submitted"},
        "extraction_coverage": {"enum": ["complete", "partial", "conflict"]},
        "extraction_quality_status": {"const": "not_measured"},
    }
)
INVENTORY_V2["required"].extend(
    [
        "extraction_input_digest",
        "extraction_result_digest",
        "extraction_result_id",
        "extraction_range_status",
        "extraction_coverage",
        "extraction_quality_status",
    ]
)
INVENTORY = {"oneOf": [INVENTORY_V1, INVENTORY_V2]}
ASSESSMENT = object_schema(
    {
        "package_digest": SHA,
        "complete": {"const": False},
        "requirement_inventory_complete": {"const": False},
        "requirement_states": {"type": "object", "additionalProperties": {"enum": STATES}},
        "requirement_digests": {"type": "object", "additionalProperties": SHA},
        "inspected_ranges": {"type": "array", "items": {"type": "object"}},
        "member_gaps": {"type": "array", "items": {"type": "object"}},
    }
)
ATTEMPT = object_schema(
    {
        "version": {"const": "bid-package-coverage/1"},
        "id": UUID,
        "bid_id": UUID,
        "inventory_id": UUID,
        "inventory_digest": SHA,
        "package_digest": SHA,
        "actor_id": UUID,
        "results": {
            "type": "array",
            "items": object_schema(
                {
                    "coverage": {"$ref": "#/components/schemas/BidPackage_coverage"},
                    "basis_type": {"enum": ["human_scope_declaration", "human_observation"]},
                    "evidence_ids": IDS,
                }
            ),
        },
        "assessment": ASSESSMENT,
        "review_ready": {"const": False},
    }
)
SCHEMAS = {
    "CreatePackageRequirementInventory": object_schema(
        {
            "authority_revision_id": UUID,
            "rule_set_id": UUID,
            "mappings": {"type": "array", "items": MAPPING, "maxItems": 500},
        }
    ),
    "CreatePackageCoverageAttempt": object_schema(
        {
            "inventory_digest": SHA,
            "package_digest": SHA,
            "results": {"type": "array", "items": RESULT, "maxItems": 500},
        }
    ),
    "PackageRequirementInventoryManifest": INVENTORY,
    "PackageCoverageAttemptManifest": ATTEMPT,
    "PackageRequirementInventoryView": object_schema({"manifest": INVENTORY, "digest": SHA}),
    "PackageCoverageAttemptView": object_schema({"manifest": ATTEMPT, "digest": SHA}),
    "PackageRequirementHistoryPage": object_schema(
        {
            "items": {
                "type": "array",
                "items": object_schema(
                    {
                        "id": UUID,
                        "digest": SHA,
                        "created_at": {"type": "string", "format": "date-time"},
                    }
                ),
            },
            "has_more": {"type": "boolean"},
            "next_cursor": {"type": ["string", "null"]},
        }
    ),
}

SCHEMAS["PackageRequirementInventoryPage"] = deepcopy(SCHEMAS["PackageRequirementHistoryPage"])
SCHEMAS["PackageRequirementInventoryPage"]["properties"]["current_inventory_id"] = {
    "type": ["string", "null"],
    "format": "uuid",
}
SCHEMAS["PackageRequirementInventoryPage"]["required"].append("current_inventory_id")


def valid(name, value):
    return Draft202012Validator(
        {"components": {"schemas": PACKAGE_SCHEMAS | SCHEMAS}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    if not valid(name, value):
        raise DomainError("INVALID_REQUEST", "要求清单或人工核验声明字段不符合协议", 422)


BASE = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories"


def extend_openapi(actual):
    schemas = actual.setdefault("components", {}).setdefault("schemas", {})
    for name, value in PACKAGE_SCHEMAS.items():
        schemas.setdefault(name, deepcopy(value))
    schemas.update(deepcopy(SCHEMAS))
    for suffix, method, operation_id, request, response in [
        ("", "get", "listPackageRequirementInventories", None, "PackageRequirementInventoryPage"),
        (
            "",
            "post",
            "createPackageRequirementInventory",
            "CreatePackageRequirementInventory",
            "PackageRequirementInventoryView",
        ),
        (
            "/{inventory_id}",
            "get",
            "getPackageRequirementInventory",
            None,
            "PackageRequirementInventoryView",
        ),
        (
            "/{inventory_id}/coverage-attempts",
            "post",
            "createPackageCoverageAttempt",
            "CreatePackageCoverageAttempt",
            "PackageCoverageAttemptView",
        ),
        (
            "/{inventory_id}/coverage-attempts",
            "get",
            "listPackageCoverageAttempts",
            None,
            "PackageRequirementHistoryPage",
        ),
        (
            "/{inventory_id}/coverage-attempts/{attempt_id}",
            "get",
            "getPackageCoverageAttempt",
            None,
            "PackageCoverageAttemptView",
        ),
    ]:
        operation = actual.get("paths", {}).get(BASE + suffix, {}).get(method)
        if operation is None:
            continue
        operation["operationId"] = operation_id
        operation["security"] = [{"SessionCookie": []}]
        if request:
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + request}}
                },
            }
            operation.setdefault("parameters", []).extend(
                {"in": "header", "name": header, "required": True, "schema": {"type": "string"}}
                for header in ("Origin", "X-CSRF-Token", "Idempotency-Key")
            )
            if not suffix:
                operation["parameters"].extend(
                    {
                        "in": "header",
                        "name": header,
                        "required": False,
                        "schema": {"type": "string"},
                        "description": "First revision requires If-None-Match:*; later revisions require exact current inventory If-Match.",
                    }
                    for header in ("If-Match", "If-None-Match")
                )
        operation["responses"] = {
            "201" if request else "200": {
                "description": "Frozen projection / explicit human scope declaration. Inventory completeness and review readiness remain false.",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + response}}
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
