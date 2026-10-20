"""Requirements projections / human coverage declarations, never formal review output."""

import json
from copy import deepcopy
from pathlib import Path

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

SCHEMAS["PackageReviewInputPreviewRequest"] = object_schema(
    {
        "package_digest": SHA,
        "inventory_digest": SHA,
        "coverage_attempt_id": {"anyOf": [UUID, {"type": "null"}]},
        "coverage_digest": NULL_SHA,
    }
)
SCHEMAS["PackageReviewInputManifest"] = object_schema(
    {
        "version": {"const": "bid-package-review-input/1"},
        "kind": {"const": "preview"},
        "bid_id": UUID,
        "target": {"$ref": "#/components/schemas/BidPackageStoredView"},
        "authority": {"$ref": "#/components/schemas/BidPackageStoredView"},
        "inventory": {"$ref": "#/components/schemas/PackageRequirementInventoryView"},
        "coverage": {
            "anyOf": [{"$ref": "#/components/schemas/PackageCoverageAttemptView"}, {"type": "null"}]
        },
    }
)
SCHEMAS["PackageReviewInputPreview"] = object_schema(
    {
        "manifest": {"$ref": "#/components/schemas/PackageReviewInputManifest"},
        "digest": SHA,
        "review_ready": {"const": False},
        "launch_available": {"const": False},
        "blockers": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "enum": [
                    "PROJECT_WORK_CLOSED",
                    "PACKAGE_BIDDER_UNCONFIRMED",
                    "PACKAGE_REVIEW_IDENTITY_STALE",
                    "PACKAGE_REVIEW_PACKAGE_STALE",
                    "PACKAGE_REVIEW_INVENTORY_STALE",
                    "PACKAGE_REVIEW_RULE_SET_STALE",
                    "PACKAGE_REVIEW_SOURCE_UNPROVEN",
                    "PACKAGE_REVIEW_SOURCE_CHANGED",
                    "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE",
                    "PACKAGE_REVIEW_MEMBERS_UNPROVEN",
                    "PACKAGE_REVIEW_EVIDENCE_CHANGED",
                    "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP",
                    "PACKAGE_REVIEW_EXTRACTION_UNPROVEN",
                    "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN",
                    "PACKAGE_REVIEW_EXECUTOR_NOT_READY",
                ]
            },
        },
        "physical_page_gaps": {
            "type": "array",
            "items": object_schema(
                {
                    "role": {"enum": ["target", "authority"]},
                    "member_id": IDENTIFIER,
                    "first_page": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
                    "last_page": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
                }
            ),
        },
    }
)


SCHEMAS["PackageReviewOriginalVerificationRequest"] = object_schema(
    deepcopy(SCHEMAS["PackageReviewInputPreviewRequest"]["properties"]) | {"input_digest": SHA}
)
SCHEMAS["PackageReviewVerifiedOriginal"] = object_schema(
    {
        "role": {"enum": ["target", "authority"]},
        "member_id": IDENTIFIER,
        "document_version_id": UUID,
        "parse_run_id": UUID,
        "file_digest": SHA,
        "byte_size": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
    }
)
SCHEMAS["PackageReviewExecutionContext"] = object_schema(
    {
        "version": {"const": "package-review-context/1"},
        "kind": {"const": "candidate"},
        **{
            field: SHA
            for field in (
                "input_digest",
                "semantic_digest",
                "snapshot_digest",
                "method_digest",
                "policy_digest",
                "facts_digest",
                "sources_digest",
            )
        },
        "as_of": {"type": "string", "format": "date-time"},
        "purpose": {"const": "prebid_compliance"},
        "fact_set_id": {"anyOf": [UUID, {"type": "null"}]},
        "fact_count": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
        "confirmed_fact_count": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
        "facts_binding": {"enum": ["empty", "unproven"]},
        "executor_available": {"const": False},
        "formal_scoring_eligible": {"const": False},
    }
)
SCHEMAS["PackageReviewOriginalVerification"] = object_schema(
    {
        "kind": {"const": "observation"},
        "execution_context": {"$ref": "#/components/schemas/PackageReviewExecutionContext"},
        "input_digest": SHA,
        "checked_at": {"type": "string", "format": "date-time"},
        "originals_verified": {"const": True},
        "review_ready": {"const": False},
        "launch_available": {"const": False},
        "blockers": deepcopy(SCHEMAS["PackageReviewInputPreview"]["properties"]["blockers"]),
        "originals": {
            "type": "array",
            "minItems": 2,
            "items": {"$ref": "#/components/schemas/PackageReviewVerifiedOriginal"},
        },
    }
)


SCHEMAS["FreezePackageReviewInput"] = object_schema(
    deepcopy(SCHEMAS["PackageReviewOriginalVerificationRequest"]["properties"])
    | {"context_digest": SHA}
)
SCHEMAS["PackageReviewFrozenInputManifest"] = object_schema(
    {
        "version": {"const": "package-review-frozen-input/1"},
        "kind": {"const": "frozen_input"},
        **{
            key: UUID
            for key in (
                "id",
                "bid_id",
                "package_id",
                "revision_id",
                "inventory_id",
                "actor_id",
                "command_id",
            )
        },
        **{key: SHA for key in ("input_digest", "context_digest", "evidence_digest")},
        "execution_context": {"$ref": "#/components/schemas/PackageReviewExecutionContext"},
        "as_of": {"type": "string", "format": "date-time"},
        "frozen_at": {"type": "string", "format": "date-time"},
        "blockers": deepcopy(SCHEMAS["PackageReviewInputPreview"]["properties"]["blockers"]),
        "review_ready": {"const": False},
        "launch_available": {"const": False},
    }
)
SCHEMAS["PackageReviewFrozenInputView"] = object_schema(
    {"manifest": {"$ref": "#/components/schemas/PackageReviewFrozenInputManifest"}, "digest": SHA}
)
SCHEMAS["PackageReviewFrozenInputPage"] = object_schema(
    {
        **{key: UUID for key in ("bid_id", "package_id", "revision_id", "inventory_id")},
        "items": {
            "type": "array",
            "maxItems": 100,
            "items": object_schema(
                {
                    "id": UUID,
                    "digest": SHA,
                    "actor_id": UUID,
                    "frozen_at": {"type": "string", "format": "date-time"},
                    "input_digest": SHA,
                    "context_digest": SHA,
                }
            ),
        },
        "has_more": {"type": "boolean"},
        "next_cursor": {"type": ["string", "null"]},
    }
)
SCHEMAS["CheckPackageReviewEligibility"] = object_schema({"frozen_digest": SHA})
SCHEMAS["PackageReviewEligibilityObservation"] = object_schema(
    {
        "kind": {"const": "eligibility_observation"},
        "frozen_input_id": UUID,
        "frozen_digest": SHA,
        "input_digest": SHA,
        "checked_at": {"type": "string", "format": "date-time"},
        "current_context": {"$ref": "#/components/schemas/PackageReviewExecutionContext"},
        "parse_evidence_status": {"enum": ["matched", "mismatch"]},
        "original_verification": {"const": "not_performed"},
        "review_ready": {"const": False},
        "launch_available": {"const": False},
        "publication_authorized": {"const": False},
        "blockers": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "enum": SCHEMAS["PackageReviewInputPreview"]["properties"]["blockers"]["items"][
                    "enum"
                ]
                + [
                    "PACKAGE_REVIEW_METHOD_CHANGED",
                    "PACKAGE_REVIEW_POLICY_CHANGED",
                    "PACKAGE_REVIEW_FACTS_CHANGED",
                    "PACKAGE_REVIEW_FACTS_UNPROVEN",
                ]
            },
        },
    }
)


_execution = json.loads(
    (Path(__file__).parent / "schemas/package-review-execution.schema.json").read_text(
        encoding="utf-8"
    )
)
for _name, _schema in _execution["$defs"].items():
    SCHEMAS["PackageExecution_" + _name] = json.loads(
        json.dumps(_schema).replace("#/$defs/", "#/components/schemas/PackageExecution_")
    )
SCHEMAS["SavePackageExecutionInput"] = object_schema(
    {
        "frozen_digest": SHA,
        "context_digest": SHA,
        "rerun": {
            "anyOf": [
                {"$ref": "#/components/schemas/PackageExecution_RerunIntent"},
                {"type": "null"},
            ]
        },
    }
)
SCHEMAS["PackageExecutionInputManifest"] = object_schema(
    {
        "version": {"const": "package-review-execution-input/1"},
        "kind": {"const": "prepared_input"},
        **{
            k: UUID
            for k in (
                "id",
                "bid_id",
                "package_id",
                "revision_id",
                "inventory_id",
                "frozen_input_id",
                "actor_id",
                "command_id",
            )
        },
        "identity": {"$ref": "#/components/schemas/PackageExecution_Identity"},
        "execution_context": {"$ref": "#/components/schemas/PackageReviewExecutionContext"},
        "snapshot_digest": SHA,
        "originals_verified_at": {"type": "string", "format": "date-time"},
        "saved_at": {"type": "string", "format": "date-time"},
        "blockers": deepcopy(
            SCHEMAS["PackageReviewEligibilityObservation"]["properties"]["blockers"]
        ),
        "review_ready": {"const": False},
        "launch_available": {"const": False},
        "publication_authorized": {"const": False},
    }
)
SCHEMAS["PackageExecutionInputView"] = object_schema(
    {"manifest": {"$ref": "#/components/schemas/PackageExecutionInputManifest"}, "digest": SHA}
)


SCHEMAS["CheckPackageExecutionFacts"] = object_schema({"execution_input_digest": SHA})
_FACT_CODES = [
    "FACT_SET_EMPTY",
    "FACT_DECISION_UNCONFIRMED",
    "FACT_DECISION_BINDING_UNPROVEN",
    "FACT_DECISION_BASIS_UNPROVEN",
    "FACT_EVIDENCE_OUTSIDE_FROZEN_INPUT",
    "FACT_EVIDENCE_QUALITY_UNPROVEN",
    "FACT_SOURCE_BINDING_UNPROVEN",
    "FACT_SOURCE_NOT_EFFECTIVE",
    "FACT_SCOPE_MAPPING_REQUIRED",
]
SCHEMAS["PackageFactValidationItem"] = object_schema(
    {
        "fact_id": UUID,
        "provenance_status": {"enum": ["verified", "unproven"]},
        "scope_binding": {"const": "unproven"},
        "facts_qualified": {"const": False},
        "blockers": {
            "type": "array",
            "items": {"enum": _FACT_CODES[1:]},
            "minItems": 1,
            "uniqueItems": True,
        },
    }
)
SCHEMAS["PackageExecutionFactCheck"] = object_schema(
    {
        "kind": {"const": "fact_validation_observation"},
        **{
            k: UUID
            for k in (
                "bid_id",
                "package_id",
                "revision_id",
                "inventory_id",
                "frozen_input_id",
                "execution_input_id",
            )
        },
        **{
            k: SHA
            for k in (
                "execution_input_digest",
                "prepared_context_digest",
                "observed_context_digest",
                "observed_facts_digest",
            )
        },
        "matches_prepared_context": {"type": "boolean"},
        "checked_at": {"type": "string", "format": "date-time"},
        "fact_count": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
        "provenance_verified_count": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
        "fact_checks": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/PackageFactValidationItem"},
        },
        "blockers": {"type": "array", "items": {"const": "FACT_SET_EMPTY"}, "uniqueItems": True},
        "facts_qualified": {"const": False},
        "original_verification": {"const": "not_performed"},
        "review_ready": {"const": False},
        "launch_available": {"const": False},
        "publication_authorized": {"const": False},
    }
)


_fact_scope = json.loads(
    (Path(__file__).parent / "schemas/package-fact-scope.schema.json").read_text("utf-8")
)
for _name, _value in _fact_scope["$defs"].items():
    SCHEMAS["PackageFactScope_" + _name] = json.loads(
        json.dumps(_value).replace("#/$defs/", "#/components/schemas/PackageFactScope_")
    )
SCHEMAS["ChangePackageFactScope"] = {"$ref": "#/components/schemas/PackageFactScope_Change"}
SCHEMAS["PackageFactScopeView"] = {"$ref": "#/components/schemas/PackageFactScope_Record"}
_fact_change = json.loads(
    (Path(__file__).parent / "schemas/package-fact-change.schema.json").read_text("utf-8")
)
for _name, _value in _fact_change["$defs"].items():
    SCHEMAS["PackageFactChange_" + _name] = json.loads(
        json.dumps(_value).replace("#/$defs/", "#/components/schemas/PackageFactChange_")
    )
SCHEMAS["ConfirmPackageFact"] = {"$ref": "#/components/schemas/PackageFactChange_ConfirmRequest"}
SCHEMAS["WithdrawPackageFact"] = {"$ref": "#/components/schemas/PackageFactChange_WithdrawRequest"}
SCHEMAS["PackageFactChangeView"] = {"$ref": "#/components/schemas/PackageFactChange_Record"}
_input_dependencies = json.loads(
    (Path(__file__).parent / "schemas/package-input-dependencies.schema.json").read_text("utf-8")
)
for _name, _value in _input_dependencies["$defs"].items():
    SCHEMAS["PackageInputDependencies_" + _name] = json.loads(
        json.dumps(_value).replace("#/$defs/", "#/components/schemas/PackageInputDependencies_")
    )
SCHEMAS["PackageInputDependencyAssessment"] = {
    "$ref": "#/components/schemas/PackageInputDependencies_View"
}
SCHEMAS["CheckPackageInputDependencies"] = object_schema(
    {
        "execution_input_digest": SHA,
        "purpose": {"const": "prebid_compliance"},
        "fact_ids": IDS,
        "dependencies": {
            "type": "array",
            "maxItems": 500,
            "items": {"$ref": "#/components/schemas/PackageInputDependencies_Dependency"},
        },
    }
)
SCHEMAS["PackageEditableFact"] = deepcopy(SCHEMAS["PackageFactChange_Fact"])
SCHEMAS["PackageEditableFact"]["properties"].pop("reason")
SCHEMAS["PackageEditableFact"]["required"].remove("reason")
SCHEMAS["PackagePreparedFactSummary"] = object_schema(
    {
        "fact_id": UUID,
        "fact_item_digest": SHA,
        **{
            key: {"type": "string", "maxLength": 240}
            for key in ("name", "subject", "scope", "value_preview")
        },
        "unit": {"type": ["string", "null"], "maxLength": 240},
        "preview_truncated": {"type": "boolean"},
    }
)
SCHEMAS["PackagePreparedFactPage"] = object_schema(
    {
        **{
            key: UUID
            for key in (
                "bid_id",
                "package_id",
                "revision_id",
                "inventory_id",
                "frozen_input_id",
                "execution_input_id",
            )
        },
        "execution_input_digest": SHA,
        "facts_digest": SHA,
        "fact_set_id": {"anyOf": [UUID, {"type": "null"}]},
        "fact_count": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
        "items": {
            "type": "array",
            "maxItems": 100,
            "items": {"$ref": "#/components/schemas/PackagePreparedFactSummary"},
        },
        "has_more": {"type": "boolean"},
        "next_cursor": {"type": ["string", "null"], "maxLength": 4096},
    }
)
SCHEMAS["PackageCurrentFactSummary"] = deepcopy(SCHEMAS["PackagePreparedFactSummary"])
SCHEMAS["PackageCurrentFactSummary"]["properties"].update(
    confirmation_recorded={"enum": ["pending", "confirmed", "rejected"]},
    decision_id={"anyOf": [UUID, {"type": "null"}]},
    frozen_evidence_status={"enum": ["selected_parse", "unproven"]},
)
SCHEMAS["PackageCurrentFactSummary"]["required"].extend(
    ["confirmation_recorded", "decision_id", "frozen_evidence_status"]
)
_current_fact_common = dict(
    binding={"$ref": "#/components/schemas/PackageFactChange_Binding"},
    head={"$ref": "#/components/schemas/PackageFactChange_Head"},
    checked_at={"type": "string", "format": "date-time"},
    **{
        key: {"const": False}
        for key in (
            "original_bytes_verified",
            "facts_qualified",
            "review_ready",
            "launch_available",
            "publication_authorized",
        )
    },
    required_facts_assessment={"const": "not_performed"},
)
SCHEMAS["PackageCurrentFactPage"] = object_schema(
    dict(
        version={"const": "package-current-facts/1"},
        kind={"const": "current_package_facts"},
        fact_count={"type": "integer", "minimum": 0, "maximum": 9007199254740991},
        items={
            "type": "array",
            "maxItems": 100,
            "items": {"$ref": "#/components/schemas/PackageCurrentFactSummary"},
        },
        has_more={"type": "boolean"},
        next_cursor={"type": ["string", "null"], "maxLength": 4096},
        **deepcopy(_current_fact_common),
    )
)
SCHEMAS["PackageCurrentFactDetail"] = object_schema(
    dict(
        version={"const": "package-current-fact/1"},
        kind={"const": "current_package_fact"},
        summary={"$ref": "#/components/schemas/PackageCurrentFactSummary"},
        editability={"enum": ["editable", "unsupported_or_oversized"]},
        editable_fact={
            "anyOf": [{"$ref": "#/components/schemas/PackageEditableFact"}, {"type": "null"}]
        },
        **deepcopy(_current_fact_common),
    )
)
SCHEMAS["PackageFactSourcePackage"] = object_schema(
    dict(role={"enum": ["target", "authority"]}, package_id=UUID, revision_id=UUID, digest=SHA)
)
SCHEMAS["PackageCurrentFactPage"]["properties"]["source_packages"] = {
    "type": "array",
    "minItems": 2,
    "maxItems": 2,
    "items": {"$ref": "#/components/schemas/PackageFactSourcePackage"},
}
SCHEMAS["PackageCurrentFactPage"]["required"].append("source_packages")
SCHEMAS["PackageFactEvidenceReference"] = object_schema(
    dict(
        id=UUID,
        parse_id=UUID,
        document_version_id=UUID,
        physical_page={"type": "integer", "minimum": 1, "maximum": 9007199254740991},
        digest=SHA,
        frozen_parse_member={"type": "boolean"},
    )
)
SCHEMAS["PackageCurrentFactDetail"]["properties"].update(
    evidence_references={
        "type": "array",
        "maxItems": 100,
        "items": {"$ref": "#/components/schemas/PackageFactEvidenceReference"},
    },
    evidence_truncated={"type": "boolean"},
)
SCHEMAS["PackageCurrentFactDetail"]["required"].extend(
    ["evidence_references", "evidence_truncated"]
)
SCHEMAS["PackageFactScopeObservation"] = object_schema(
    {
        "kind": {"const": "fact_scope_observation"},
        **{
            k: UUID
            for k in (
                "bid_id",
                "package_id",
                "revision_id",
                "inventory_id",
                "frozen_input_id",
                "execution_input_id",
                "fact_id",
            )
        },
        "execution_input_digest": SHA,
        "prepared_context_digest": SHA,
        "observed_context_digest": NULL_SHA,
        "matches_prepared_input": {"type": "boolean"},
        "provenance_status": {"enum": ["verified", "unproven"]},
        "subject_choices": {
            "type": "array",
            "maxItems": 4,
            "items": object_schema(
                {
                    **deepcopy(SCHEMAS["PackageFactScope_Subject"]["properties"]),
                    "label": {"type": "string"},
                }
            ),
        },
        "head": {
            "anyOf": [{"$ref": "#/components/schemas/PackageFactScope_Record"}, {"type": "null"}]
        },
        "binding_status": {"enum": ["unproven", "matches_current_input", "withdrawn"]},
        "observation_gap": {"type": ["string", "null"]},
        "checked_at": {"type": "string", "format": "date-time"},
        **{
            k: {"const": False}
            for k in (
                "facts_qualified",
                "review_ready",
                "launch_available",
                "publication_authorized",
            )
        },
    }
)


def valid(name, value):
    return Draft202012Validator(
        {"components": {"schemas": PACKAGE_SCHEMAS | SCHEMAS}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    if not valid(name, value):
        message = (
            "事实操作字段不符合协议，请核对事实、依据与当前版本"
            if name in ("ConfirmPackageFact", "WithdrawPackageFact")
            else "要求清单或人工核验声明字段不符合协议"
        )
        raise DomainError("INVALID_REQUEST", message, 422)


BASE = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories"


def extend_openapi(actual):
    schemas = actual.setdefault("components", {}).setdefault("schemas", {})
    for name, value in PACKAGE_SCHEMAS.items():
        schemas.setdefault(name, deepcopy(value))
    schemas.update(deepcopy(SCHEMAS))
    for suffix, method, operation_id, request, response in [
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/dependency-check",
            "post",
            "checkPackageInputDependencies",
            "CheckPackageInputDependencies",
            "PackageInputDependencyAssessment",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/fact-confirmations",
            "post",
            "confirmPackageFact",
            "ConfirmPackageFact",
            "PackageFactChangeView",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/fact-withdrawals",
            "post",
            "withdrawPackageFact",
            "WithdrawPackageFact",
            "PackageFactChangeView",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/fact-changes/{command_id}",
            "get",
            "getPackageFactChange",
            None,
            "PackageFactChangeView",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/fact-context",
            "get",
            "listPackageCurrentFacts",
            None,
            "PackageCurrentFactPage",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/facts/{fact_id}",
            "get",
            "getPackageCurrentFact",
            None,
            "PackageCurrentFactDetail",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/facts",
            "get",
            "listPackagePreparedFacts",
            None,
            "PackagePreparedFactPage",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/fact-scope-declarations",
            "post",
            "changePackageFactScope",
            "ChangePackageFactScope",
            "PackageFactScopeView",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/fact-scope-declarations/{declaration_id}",
            "get",
            "getPackageFactScope",
            None,
            "PackageFactScopeView",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/facts/{fact_id}/scope-declaration",
            "get",
            "getPackageFactScopeObservation",
            None,
            "PackageFactScopeObservation",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/fact-check",
            "post",
            "checkPackageExecutionFacts",
            "CheckPackageExecutionFacts",
            "PackageExecutionFactCheck",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs",
            "post",
            "savePackageExecutionInput",
            "SavePackageExecutionInput",
            "PackageExecutionInputView",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}",
            "get",
            "getPackageExecutionInput",
            None,
            "PackageExecutionInputView",
        ),
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
        (
            "/{inventory_id}/review-input-preview",
            "post",
            "previewPackageReviewInput",
            "PackageReviewInputPreviewRequest",
            "PackageReviewInputPreview",
        ),
        (
            "/{inventory_id}/review-original-verification",
            "post",
            "verifyPackageReviewOriginals",
            "PackageReviewOriginalVerificationRequest",
            "PackageReviewOriginalVerification",
        ),
        (
            "/{inventory_id}/frozen-review-inputs",
            "post",
            "freezePackageReviewInput",
            "FreezePackageReviewInput",
            "PackageReviewFrozenInputView",
        ),
        (
            "/{inventory_id}/frozen-review-inputs",
            "get",
            "listFrozenPackageReviewInputs",
            None,
            "PackageReviewFrozenInputPage",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}/execution-check",
            "post",
            "checkFrozenPackageReviewEligibility",
            "CheckPackageReviewEligibility",
            "PackageReviewEligibilityObservation",
        ),
        (
            "/{inventory_id}/frozen-review-inputs/{input_id}",
            "get",
            "getFrozenPackageReviewInput",
            None,
            "PackageReviewFrozenInputView",
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
                for header in (
                    ("Origin", "X-CSRF-Token")
                    if suffix.endswith(
                        (
                            "review-input-preview",
                            "review-original-verification",
                            "execution-check",
                            "fact-check",
                            "dependency-check",
                        )
                    )
                    else ("Origin", "X-CSRF-Token", "Idempotency-Key")
                )
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
            "201"
            if request
            and not suffix.endswith(
                (
                    "review-input-preview",
                    "review-original-verification",
                    "execution-check",
                    "fact-check",
                    "dependency-check",
                )
            )
            else "200": {
                "description": "Explicit human fact operation or current fact observation; no review/execution authority."
                if operation_id
                in (
                    "confirmPackageFact",
                    "withdrawPackageFact",
                    "getPackageFactChange",
                    "listPackageCurrentFacts",
                    "getPackageCurrentFact",
                )
                else "Frozen projection / explicit human scope declaration. Inventory completeness and review readiness remain false.",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + response}}
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
