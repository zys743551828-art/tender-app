"""Exact human derivations of package rules; never a replacement extraction receipt."""

import json
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import SCHEMAS as PACKAGE_SCHEMAS
from packages.contracts.bid_package_api import UUID, object_schema
from packages.domain.runtime import ROOT, DomainError

MAX_RULES = 10000
MAX_CHANGES = 100
MAX_CHAIN = 32
LIMITS = {
    "rules": MAX_RULES,
    "changes": MAX_CHANGES,
    "chain_depth": MAX_CHAIN,
    "request_bytes": 1024 * 1024,
    "preview_bytes": 4 * 1024 * 1024,
    "derivation_bytes": 64 * 1024 * 1024,
}
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 2000}
NULL_UUID = {"anyOf": [UUID, {"type": "null"}]}
NULL_SHA = {"anyOf": [SHA, {"type": "null"}]}
COUNT = {"type": "integer", "minimum": 0, "maximum": MAX_RULES}
INDEX = {"type": "integer", "minimum": 0, "maximum": MAX_CHANGES - 1}
HEAD = object_schema({"id": UUID, "digest": SHA})
OPTIONAL_HEAD = {"anyOf": [HEAD, {"type": "null"}]}
SCOPE = object_schema(
    {key: UUID for key in ("bid_id", "package_id", "revision_id", "inventory_id")}
)
BASE = object_schema({"inventory_digest": SHA, "rule_set_id": UUID, "rule_set_digest": SHA})
AUTHORITY = object_schema({"revision_id": UUID, "digest": SHA, "identity_digest": SHA})
EXTRACTION_BASIS = object_schema(
    {
        "inventory_id": UUID,
        "inventory_digest": SHA,
        "rule_set_id": UUID,
        "rule_set_digest": SHA,
        "extraction_result_id": UUID,
        "extraction_input_digest": SHA,
        "extraction_result_digest": SHA,
        "extraction_range_status": {"const": "all_frozen_evidence_submitted"},
        "extraction_coverage": {"enum": ["complete", "partial", "conflict"]},
        "extraction_quality_status": {"const": "not_measured"},
    }
)
DERIVATION_HEAD = object_schema(
    {
        "version": {"const": "package-rule-derivation/1"},
        "head_id": UUID,
        "head_digest": SHA,
        "length": {"type": "integer", "minimum": 1, "maximum": MAX_CHAIN},
    }
)

_protocol = json.loads((ROOT / "packages/contracts/schemas/protocol.schema.json").read_text())
_rule_defs = {
    name: deepcopy(_protocol["$defs"][name])
    for name in ("RuleAddition", "RuleScope", "RuleBand", "RuleEvidenceQuote")
}


def _local_refs(value):
    if isinstance(value, dict):
        return {
            key: item.replace("#/$defs/", "#/components/schemas/PackageRuleCorrection_")
            if key == "$ref"
            else _local_refs(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_local_refs(item) for item in value]
    return value


RULE_DEFS = _local_refs(_rule_defs)
RULE_DEFS["RuleAddition"]["properties"]["statement"]["maxLength"] = 16000
for _name in ("conditions", "exceptions"):
    RULE_DEFS["RuleAddition"]["properties"][_name]["maxItems"] = 50
    RULE_DEFS["RuleAddition"]["properties"][_name]["items"]["maxLength"] = 8000
RULE_DEFS["RuleAddition"]["properties"]["bands"]["maxItems"] = 100
RULE_DEFS["RuleScope"]["properties"]["description"]["maxLength"] = 2000
for _name in ("label", "description"):
    RULE_DEFS["RuleBand"]["properties"][_name]["maxLength"] = 8000
RULE_DEFS["RuleBand"]["properties"]["evidence_ids"]["maxItems"] = 50
RULE_DEFS["RuleBand"]["properties"]["evidence_ids"]["uniqueItems"] = True
RULE = {"$ref": "#/components/schemas/PackageRuleCorrection_RuleAddition"}
QUOTES = {
    "type": "array",
    "items": {"$ref": "#/components/schemas/PackageRuleCorrection_RuleEvidenceQuote"},
    "minItems": 1,
    "maxItems": 50,
    "uniqueItems": True,
}
RULE_DEFS["RuleAddition"]["properties"]["evidence_quotes"] = deepcopy(QUOTES)
CHANGE = {
    "oneOf": [
        object_schema({"op": {"const": "add"}, "rule": RULE}),
        object_schema(
            {"op": {"const": "replace"}, "rule_id": UUID, "rule_digest": SHA, "rule": RULE}
        ),
        object_schema(
            {
                "op": {"const": "withdraw"},
                "rule_id": UUID,
                "rule_digest": SHA,
                "evidence_quotes": QUOTES,
            }
        ),
    ]
}
REQUEST = object_schema(
    {
        "base_inventory_digest": SHA,
        "base_rule_set_digest": SHA,
        "reason": TEXT,
        "changes": {"type": "array", "items": CHANGE, "minItems": 1, "maxItems": MAX_CHANGES},
    }
)
SEMANTIC = object_schema(
    {
        "kind": {"enum": ["disqualification", "mandatory", "scoring", "advisory"]},
        "statement": {"type": "string", "minLength": 1},
        "conditions": {"type": "array", "items": {"type": "string"}},
        "exceptions": {"type": "array", "items": {"type": "string"}},
        "max_points": {"type": ["string", "null"], "pattern": "^[0-9]+(\\.[0-9]+)?$"},
        "evidence_ids": {"type": "array", "items": UUID, "minItems": 1, "uniqueItems": True},
        "bands": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/PackageRuleCorrection_RuleBand"},
        },
        "applicability_scope": {"type": "object"},
        "provenance_status": {"enum": ["effective", "needs_revalidation", "superseded"]},
    }
)
FROZEN_QUOTE = object_schema(
    {
        "evidence_id": UUID,
        "member_id": {"type": "string", "minLength": 1, "maxLength": 2000},
        "document_version_id": UUID,
        "parse_run_id": UUID,
        "physical_page": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
        "evidence_digest": SHA,
        "part_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "uniqueItems": True,
        },
        "quote": {"type": "string", "minLength": 1, "maxLength": 8000},
    }
)
PREVIEW_CHANGE = object_schema(
    {
        "index": INDEX,
        "op": {"enum": ["add", "replace", "withdraw"]},
        "rule_id": NULL_UUID,
        "rule_digest": NULL_SHA,
        "before": {"anyOf": [SEMANTIC, {"type": "null"}]},
        "after": SEMANTIC,
        "quotes": {"type": "array", "items": FROZEN_QUOTE, "minItems": 1, "maxItems": 50},
    }
)
COMMON = {
    "scope": SCOPE,
    "base": BASE,
    "authority": AUTHORITY,
    "extraction_basis": EXTRACTION_BASIS,
    "previous": OPTIONAL_HEAD,
    "sequence_no": {"type": "integer", "minimum": 1, "maximum": MAX_CHAIN},
    "policy_digest": SHA,
    "request": REQUEST,
    "request_digest": SHA,
    "source_snapshot_digest": SHA,
}
PREVIEW = object_schema(
    {
        "version": {"const": "package-rule-correction-preview/1"},
        **deepcopy(COMMON),
        "changes": {
            "type": "array",
            "items": PREVIEW_CHANGE,
            "minItems": 1,
            "maxItems": MAX_CHANGES,
        },
        "counts": object_schema(
            {
                key: COUNT
                for key in (
                    "before",
                    "after",
                    "carried",
                    "added",
                    "replaced",
                    "withdrawn",
                    "active_after",
                )
            }
        ),
        "limitations": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "inventory_complete": {"const": False},
        "review_ready": {"const": False},
        "original_bytes_verified": {"const": False},
    }
)
MAPPING = object_schema(
    {
        "from_rule_id": UUID,
        "from_rule_digest": SHA,
        "to_rule_id": UUID,
        "to_rule_digest": SHA,
        "op": {"enum": ["carry", "replace", "withdraw"]},
        "change_index": {"anyOf": [INDEX, {"type": "null"}]},
    }
)
ADDITION = object_schema({"change_index": INDEX, "to_rule_id": UUID, "to_rule_digest": SHA})
DECISION_BINDING = object_schema(
    {
        "rule_id": UUID,
        "decision_id": UUID,
        "decision_digest": SHA,
        "mode": {"enum": ["carried", "confirmed", "rejected"]},
    }
)
RECORD = object_schema(
    {
        "version": {"const": "package-rule-correction/1"},
        "id": UUID,
        **deepcopy(COMMON),
        "preview_digest": SHA,
        "actor_id": UUID,
        "command_id": UUID,
        "created_at": TIME,
        "result": object_schema(
            {
                "inventory_id": UUID,
                "rule_set_id": UUID,
                "rule_set_digest": SHA,
                "rule_count": COUNT,
                "rules_digest": SHA,
            }
        ),
        "mappings": {"type": "array", "items": MAPPING, "maxItems": MAX_RULES},
        "additions": {"type": "array", "items": ADDITION, "maxItems": MAX_CHANGES},
        "decision_bindings": {"type": "array", "items": DECISION_BINDING, "maxItems": MAX_RULES},
    }
)
APPLY = object_schema({"request": REQUEST, "preview_digest": SHA})
COMMAND = object_schema(
    {
        "command_id": UUID,
        "actor_id": UUID,
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
        "request_digest": SHA,
        "request": APPLY,
        "if_match": {"type": "string", "minLength": 1, "maxLength": 256},
    }
)
SCHEMAS = {
    **{"PackageRuleCorrection_" + name: value for name, value in RULE_DEFS.items()},
    "PackageRuleCorrectionRequest": REQUEST,
    "PackageRuleCorrectionSemantic": SEMANTIC,
    "ApplyPackageRuleCorrection": APPLY,
    "PackageRuleCorrectionPreviewManifest": PREVIEW,
    "PackageRuleCorrectionPreviewView": object_schema({"manifest": PREVIEW, "digest": SHA}),
    "PackageRuleCorrectionManifest": RECORD,
    "PackageRuleCorrectionView": object_schema({"manifest": RECORD, "digest": SHA}),
    "PackageRuleCorrectionAppliedView": object_schema(
        {
            "correction": {"$ref": "#/components/schemas/PackageRuleCorrectionView"},
            "inventory": {"$ref": "#/components/schemas/PackageRequirementInventoryView"},
            "command": COMMAND,
        }
    ),
}

_evidence_item = {
    key: deepcopy(FROZEN_QUOTE["properties"][key])
    for key in (
        "evidence_id",
        "member_id",
        "document_version_id",
        "parse_run_id",
        "physical_page",
        "evidence_digest",
        "part_ids",
    )
} | {
    "file_digest": SHA,
    "ordinal": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
    "kind": {"enum": ["text", "table", "visual_observation"]},
}
_evidence_scope = {"scope": SCOPE, "inventory_digest": SHA, "authority": AUTHORITY}
_pagination = {
    "has_more": {"type": "boolean"},
    "next_cursor": {"type": ["string", "null"], "maxLength": 4096},
}
SCHEMAS.update(
    {
        "PackageRuleCorrectionEvidencePage": object_schema(
            {
                **_evidence_scope,
                "items": {
                    "type": "array",
                    "maxItems": 100,
                    "items": object_schema(_evidence_item | {"excerpt": {"type": "string"}}),
                },
                **_pagination,
            }
        ),
        "PackageRuleCorrectionEvidenceDetail": object_schema(
            {
                **_evidence_scope,
                "evidence": object_schema(_evidence_item | {"text_content": {"type": "string"}}),
            }
        ),
        "PackageRuleCorrectionHistoryPage": object_schema(
            {
                "scope": SCOPE,
                "items": {
                    "type": "array",
                    "maxItems": 100,
                    "items": object_schema(
                        {
                            "id": UUID,
                            "digest": SHA,
                            "created_at": TIME,
                            "actor_id": UUID,
                            "base_inventory_id": UUID,
                            "result_inventory_id": UUID,
                            "added": COUNT,
                            "replaced": COUNT,
                            "withdrawn": COUNT,
                        }
                    ),
                },
                **_pagination,
            }
        ),
        "PackageRuleCorrectionDetail": {
            "$ref": "#/components/schemas/PackageRuleCorrectionAppliedView"
        },
    }
)


def valid(name, value):
    # Imported lazily: inventory /3 consumes only the two small schema constants above.
    from packages.contracts.bid_package_requirements_api import SCHEMAS as INVENTORY_SCHEMAS

    return Draft202012Validator(
        {
            "$ref": "#/components/schemas/" + name,
            "components": {"schemas": {**PACKAGE_SCHEMAS, **INVENTORY_SCHEMAS, **SCHEMAS}},
        },
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    if not valid(name, value):
        raise DomainError("PACKAGE_RULE_CORRECTION_INVALID", "整包人工更正内容不符合严格协议", 422)
    return value


BASE_PATH = (
    "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"
    "/requirement-inventories/{inventory_id}"
)


def extend_openapi(document):
    operations = (
        (
            "/rule-corrections/preview",
            "post",
            "previewPackageRuleCorrection",
            "PackageRuleCorrectionRequest",
            "PackageRuleCorrectionPreviewView",
            "200",
        ),
        (
            "/rule-corrections",
            "post",
            "applyPackageRuleCorrection",
            "ApplyPackageRuleCorrection",
            "PackageRuleCorrectionAppliedView",
            "201",
        ),
        (
            "/rule-corrections",
            "get",
            "listPackageRuleCorrections",
            None,
            "PackageRuleCorrectionHistoryPage",
            "200",
        ),
        (
            "/rule-corrections/{correction_id}",
            "get",
            "getPackageRuleCorrection",
            None,
            "PackageRuleCorrectionDetail",
            "200",
        ),
        (
            "/rule-correction-evidence",
            "get",
            "listPackageRuleCorrectionEvidence",
            None,
            "PackageRuleCorrectionEvidencePage",
            "200",
        ),
        (
            "/rule-correction-evidence/{evidence_id}",
            "get",
            "getPackageRuleCorrectionEvidence",
            None,
            "PackageRuleCorrectionEvidenceDetail",
            "200",
        ),
    )
    registered = [
        row for row in operations if row[1] in document["paths"].get(BASE_PATH + row[0], {})
    ]
    if not registered:
        return
    document["components"]["schemas"].update(deepcopy(SCHEMAS))
    for suffix, method, operation_id, request_name, response_name, status in registered:
        operation = document["paths"][BASE_PATH + suffix][method]
        operation["operationId"] = operation_id
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {
            status: {
                "description": "精确权威原页依据上的人工规则更正，不授予完整性或正式提交资格",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/" + response_name}
                    }
                },
            }
        }
        if request_name:
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + request_name}}
                },
            }
            names = ["Origin", "X-CSRF-Token"]
            if suffix == "/rule-corrections":
                names.extend(["Idempotency-Key", "If-Match"])
            existing = {(p.get("in"), p.get("name")) for p in operation.get("parameters", [])}
            operation.setdefault("parameters", []).extend(
                {
                    "name": name,
                    "in": "header",
                    "required": True,
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        **({"maxLength": 128} if name == "Idempotency-Key" else {}),
                    },
                }
                for name in names
                if ("header", name) not in existing
            )
