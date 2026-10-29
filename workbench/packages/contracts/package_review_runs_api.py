"""Implemented declared-scope review runs, separate from historical readiness flags."""

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.domain.runtime import DomainError

BASE = (
    "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"
    "/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}"
    "/execution-inputs/{execution_input_id}/review-runs"
)
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
SCOPE = object_schema(
    {key: UUID for key in ("bid_id", "package_id", "revision_id", "inventory_id")}
)
_protocol = json.loads(
    (Path(__file__).parent / "schemas/package-scope-review.schema.json").read_text("utf-8")
)
SCHEMAS = {
    "PackageScopeReview_" + name: json.loads(
        json.dumps(value).replace("#/$defs/", "#/components/schemas/PackageScopeReview_")
    )
    for name, value in _protocol["$defs"].items()
}
SCHEMAS.update(
    {
        "StartPackageReviewRun": object_schema(
            {
                "execution_input_digest": SHA,
                "dependency_plan_id": UUID,
                "dependency_plan_digest": SHA,
            }
        ),
        "PackageReviewRunInput": {"$ref": "#/components/schemas/PackageScopeReview_Input"},
        "PackageReviewRunInputView": object_schema(
            {
                "manifest": {"$ref": "#/components/schemas/PackageReviewRunInput"},
                "digest": SHA,
            }
        ),
        "PackageReviewResult": {"$ref": "#/components/schemas/PackageScopeReview_Result"},
        "PackageReviewRunView": object_schema(
            {
                "kind": {"const": "package_review_run"},
                "id": UUID,
                "actor_id": UUID,
                "created_at": TIME,
                "scope": SCOPE,
                "frozen_input_id": UUID,
                "frozen_input_digest": SHA,
                "execution_input_id": UUID,
                "execution_input_digest": SHA,
                "execution_digest": SHA,
                "dependency_plan_id": UUID,
                "dependency_plan_digest": SHA,
                "input_digest": SHA,
                "method_digest": SHA,
                "operation": object_schema(
                    {
                        "id": UUID,
                        "kind": {"const": "package-scope-review"},
                        "state": {
                            "enum": [
                                "queued",
                                "running",
                                "cancel_requested",
                                "succeeded",
                                "failed",
                                "cancelled",
                            ]
                        },
                        "input_digest": SHA,
                        "handler_version": {"const": "package-review/1"},
                        "error_code": {"type": ["string", "null"], "maxLength": 200},
                        "created_at": TIME,
                        "finished_at": {"anyOf": [TIME, {"type": "null"}]},
                    }
                ),
                "result": {
                    "anyOf": [
                        object_schema(
                            {
                                "manifest": {"$ref": "#/components/schemas/PackageReviewResult"},
                                "digest": SHA,
                            }
                        ),
                        {"type": "null"},
                    ]
                },
            }
        ),
        "PackageReviewRunPage": object_schema(
            {
                "scope": SCOPE,
                "frozen_input_id": UUID,
                "execution_input_id": UUID,
                "execution_input_digest": SHA,
                "items": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {"$ref": "#/components/schemas/PackageReviewRunSummary"},
                },
                "has_more": {"type": "boolean"},
                "next_cursor": {"type": ["string", "null"], "maxLength": 4096},
            }
        ),
    }
)
# History remains bounded even when every run contains a complete 400-row report.
# A selected report is read through its own immutable run URL.
SCHEMAS["PackageReviewRunSummary"] = deepcopy(SCHEMAS["PackageReviewRunView"])
SCHEMAS["PackageReviewRunSummary"]["properties"]["result"] = {
    "anyOf": [
        object_schema(
            {
                "digest": SHA,
                "requirement_count": {"type": "integer", "minimum": 1, "maximum": 400},
                "matrix_coverage": {"enum": ["complete", "partial"]},
                "overall_coverage": {"const": "partial"},
            }
        ),
        {"type": "null"},
    ]
}


def valid(name, value):
    return Draft202012Validator(
        {"components": {"schemas": SCHEMAS}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    if not valid(name, value):
        raise DomainError("PACKAGE_REVIEW_REQUEST_INVALID", "整包核查字段不符合已实现协议", 422)
    return value


def extend_openapi(document):
    operations = (
        (
            BASE,
            "post",
            "startPackageReviewRun",
            "StartPackageReviewRun",
            "PackageReviewRunView",
            "202",
        ),
        (BASE, "get", "listPackageReviewRuns", None, "PackageReviewRunPage", "200"),
        (BASE + "/{run_id}", "get", "getPackageReviewRun", None, "PackageReviewRunView", "200"),
        (
            BASE + "/{run_id}/input",
            "get",
            "getPackageReviewRunInput",
            None,
            "PackageReviewRunInputView",
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
                "description": "已保存核查任务回执" if method == "post" else "核查运行与原结果",
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
