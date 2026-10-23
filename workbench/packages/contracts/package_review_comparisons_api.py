"""Read-only comparison of two exact completed scope-review runs."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.contracts.package_review_decisions_api import SCHEMAS as DECISION_SCHEMAS
from packages.contracts.package_review_runs_api import SCOPE, SHA, TIME
from packages.domain.runtime import DomainError

BASE = "/api/v1/bids/{bid_id}/package-review-comparisons"
SCHEMAS = deepcopy(DECISION_SCHEMAS)
_matrix = SCHEMAS["PackageScopeReview_MatrixRow"]["properties"]
ROW_FIELDS = (
    "requirement_digest",
    "rule_digest",
    "rule_kind",
    "requirement_statement",
    "applicability",
    "target_part_ids",
    "verdict",
    "statement",
    "limitations",
)
_row = object_schema({"row_digest": SHA, **{key: _matrix[key] for key in ROW_FIELDS}})
_optional_row = {
    "anyOf": [{"$ref": "#/components/schemas/PackageReviewComparisonRowSide"}, {"type": "null"}]
}
_optional_human = {
    "anyOf": [{"$ref": "#/components/schemas/PackageReviewHumanDecisionSummary"}, {"type": "null"}]
}
CHANGE_FIELDS = (
    "run_input",
    "scope",
    "frozen_input",
    "prepared_input",
    "rerun_intent",
    "requirements",
    "submitted_documents",
    "selected_facts",
    "fact_admission",
    "dependency_plan",
    "inventory_proof",
    "method",
)
COUNT_FIELDS = (
    "added",
    "removed",
    "changed",
    "unchanged",
    "machine_row_changed",
    "verdict_changed",
)
SCHEMAS.update(
    {
        "PackageReviewComparisonRowSide": _row,
        "PackageReviewComparisonRun": object_schema(
            {
                "id": UUID,
                "actor_id": UUID,
                "created_at": TIME,
                "scope": SCOPE,
                "frozen_input_id": UUID,
                "frozen_input_digest": SHA,
                "execution_input_id": UUID,
                "execution_input_digest": SHA,
                "execution_digest": SHA,
                "input_digest": SHA,
                "method_digest": SHA,
                "dependency_plan_id": UUID,
                "dependency_plan_digest": SHA,
                "result_digest": SHA,
                "requirement_count": {"type": "integer", "minimum": 1, "maximum": 400},
                "matrix_coverage": {"enum": ["partial", "complete"]},
                "overall_coverage": {"const": "partial"},
                "human_heads_digest": SHA,
            }
        ),
        "PackageReviewComparisonRow": object_schema(
            {
                "requirement_id": UUID,
                "definition_change": {"enum": ["added", "removed", "changed", "unchanged"]},
                "machine_row_changed": {"type": ["boolean", "null"]},
                "verdict_transition": {
                    "anyOf": [
                        object_schema(
                            {
                                "from": _matrix["verdict"],
                                "to": _matrix["verdict"],
                                "changed": {"type": "boolean"},
                            }
                        ),
                        {"type": "null"},
                    ]
                },
                "left": _optional_row,
                "right": _optional_row,
                "left_human": _optional_human,
                "right_human": _optional_human,
            }
        ),
    }
)
_summary = {
    "version": {"const": "package-review-comparison/1"},
    "kind": {"const": "declared_scope_review_comparison"},
    "bid_id": UUID,
    "match_policy": {"const": "exact_requirement_id_and_definition_digests/1"},
    "left": {"$ref": "#/components/schemas/PackageReviewComparisonRun"},
    "right": {"$ref": "#/components/schemas/PackageReviewComparisonRun"},
    "input_changes": object_schema(
        {
            **{key: {"type": "boolean"} for key in CHANGE_FIELDS},
            "method_fields": {
                "type": "array",
                "uniqueItems": True,
                "items": {
                    "enum": sorted(SCHEMAS["PackageScopeReview_MethodProfile"]["properties"])
                },
            },
        }
    ),
    "counts": object_schema(
        {key: {"type": "integer", "minimum": 0, "maximum": 800} for key in COUNT_FIELDS}
    ),
    "overall_coverage": {"const": "partial"},
    "risk_resolution_assessed": {"const": False},
    "inventory_complete": {"const": False},
    "formal_scoring_eligible": {"const": False},
    "submission_eligible": {"const": False},
}
SCHEMAS.update(
    {
        "PackageReviewComparisonManifest": object_schema(
            {
                **_summary,
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 800,
                    "items": {"$ref": "#/components/schemas/PackageReviewComparisonRow"},
                },
            }
        ),
        "PackageReviewComparisonPage": object_schema(
            {
                **_summary,
                "comparison_digest": SHA,
                "items": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {"$ref": "#/components/schemas/PackageReviewComparisonRow"},
                },
                "has_more": {"type": "boolean"},
                "next_cursor": {"type": ["string", "null"], "maxLength": 4096},
            }
        ),
    }
)


def valid(name, value):
    return Draft202012Validator(
        {"components": {"schemas": SCHEMAS}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    if not valid(name, value):
        raise DomainError("PACKAGE_REVIEW_COMPARISON_INVALID", "两轮核查对比不符合已实现协议", 422)
    return value


def extend_openapi(document):
    if "get" not in document["paths"].get(BASE, {}):
        return
    document["components"]["schemas"].update(deepcopy(SCHEMAS))
    operation = document["paths"][BASE]["get"]
    operation["operationId"] = "comparePackageReviewRuns"
    operation["security"] = [{"SessionCookie": []}]
    operation["responses"] = {
        "200": {
            "description": "精确要求身份和原始判断的分页对比；不推断风险已解决或授予投标资格",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/PackageReviewComparisonPage"}
                }
            },
        }
    }
