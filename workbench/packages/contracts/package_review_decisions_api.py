"""Human dispositions of immutable scope-review rows; no machine qualification changes."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.contracts.package_review_runs_api import BASE, SCOPE, SHA, TIME
from packages.contracts.package_review_runs_api import SCHEMAS as REVIEW_SCHEMAS
from packages.domain.runtime import DomainError

RUN_BASE = BASE + "/{run_id}"
ROW_BASE = RUN_BASE + "/requirements/{requirement_id}/human-decisions"
HEAD = object_schema({"id": UUID, "digest": SHA})
OPTIONAL_HEAD = {"anyOf": [HEAD, {"type": "null"}]}
QUOTES = {
    "type": "array",
    "maxItems": 40,
    "uniqueItems": True,
    "items": {"$ref": "#/components/schemas/PackageScopeReview_Quote"},
}
SCHEMAS = {
    **deepcopy(REVIEW_SCHEMAS),
    "SavePackageReviewHumanDecision": object_schema(
        {
            "result_digest": SHA,
            "row_digest": SHA,
            "expected_head": OPTIONAL_HEAD,
            "state": {"enum": ["confirmed", "rejected", "needs_review"]},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
            "selected_quotes": QUOTES,
        }
    ),
    "PackageReviewHumanDecision": object_schema(
        {
            "version": {"const": "package-review-human-decision/1"},
            "id": UUID,
            "actor_id": UUID,
            "created_at": TIME,
            "sequence_no": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
            "scope": SCOPE,
            "frozen_input_id": UUID,
            "execution_input_id": UUID,
            "run_id": UUID,
            "requirement_id": UUID,
            "input_digest": SHA,
            "result_digest": SHA,
            "row_digest": SHA,
            "previous_head": OPTIONAL_HEAD,
            "state": {"enum": ["confirmed", "rejected", "needs_review"]},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
            "selected_quotes": QUOTES,
            "inventory_complete": {"const": False},
            "formal_scoring_eligible": {"const": False},
            "submission_eligible": {"const": False},
        }
    ),
    "PackageReviewHumanDecisionView": object_schema(
        {
            "manifest": {"$ref": "#/components/schemas/PackageReviewHumanDecision"},
            "digest": SHA,
        }
    ),
    "PackageReviewHumanDecisionSummary": object_schema(
        {
            "id": UUID,
            "digest": SHA,
            "sequence_no": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
            "actor_id": UUID,
            "created_at": TIME,
            "state": {"enum": ["confirmed", "rejected", "needs_review"]},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
        }
    ),
}
_binding = {
    "scope": SCOPE,
    "frozen_input_id": UUID,
    "execution_input_id": UUID,
    "run_id": UUID,
    "result_digest": SHA,
}
SCHEMAS.update(
    {
        "PackageReviewHumanDecisionCurrent": object_schema(
            {
                **_binding,
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 400,
                    "items": object_schema(
                        {
                            "requirement_id": UUID,
                            "row_digest": SHA,
                            "current": {
                                "anyOf": [
                                    {
                                        "$ref": "#/components/schemas/PackageReviewHumanDecisionSummary"
                                    },
                                    {"type": "null"},
                                ]
                            },
                        }
                    ),
                },
            }
        ),
        "PackageReviewHumanDecisionPage": object_schema(
            {
                **_binding,
                "requirement_id": UUID,
                "row_digest": SHA,
                "items": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {"$ref": "#/components/schemas/PackageReviewHumanDecisionView"},
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
        raise DomainError("PACKAGE_REVIEW_DECISION_INVALID", "人工处置字段不符合已实现协议", 422)
    return value


def extend_openapi(document):
    operations = (
        (
            RUN_BASE + "/human-decisions",
            "get",
            "getPackageReviewHumanDecisions",
            None,
            "PackageReviewHumanDecisionCurrent",
            "200",
        ),
        (
            ROW_BASE,
            "post",
            "savePackageReviewHumanDecision",
            "SavePackageReviewHumanDecision",
            "PackageReviewHumanDecisionView",
            "201",
        ),
        (
            ROW_BASE,
            "get",
            "listPackageReviewHumanDecisions",
            None,
            "PackageReviewHumanDecisionPage",
            "200",
        ),
    )
    registered = [entry for entry in operations if entry[1] in document["paths"].get(entry[0], {})]
    if not registered:
        return
    document["components"]["schemas"].update(deepcopy(SCHEMAS))
    for path, method, operation_id, request_name, response_name, status in registered:
        operation = document["paths"][path][method]
        operation["operationId"] = operation_id
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {
            status: {
                "description": "同一版核查条款的人工处置及历史，不改变机器原始判断或资格",
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
                for name in ("Origin", "X-CSRF-Token", "Idempotency-Key")
            )
