"""Public formal execution refusal is separate from isolated mechanism jobs."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.contracts.package_technical_eligibility_api import SCHEMAS as ELIGIBILITY
from packages.contracts.package_technical_scope_api import GAP, SHA
from packages.domain.runtime import DomainError
from packages.model_governance.package_scoring_profile import descriptor, digest

SCHEMAS = {
    "PackageTechnicalExecutionContext": object_schema(
        {
            "version": {"const": "package-technical-execution-context/1"},
            "qualification": deepcopy(ELIGIBILITY["PackageTechnicalScoringContext"]),
            "producer": object_schema(
                {
                    "software_foundation": {"enum": ["not_installed", "installed"]},
                    "real_provider_configured": {"const": False},
                    "formal_input_authority_configured": {"const": False},
                    "mechanism_test_publicly_available": {"const": False},
                }
            ),
            "method": object_schema(
                {key: {"const": value} for key, value in descriptor().items()}
                | {"digest": {"const": digest()}}
            ),
            "execution_enabled": {"const": False},
            "blockers": {"type": "array", "items": GAP, "minItems": 1},
        }
    ),
    "CreatePackageTechnicalExecution": object_schema(
        {
            "purpose": {"const": "current_prebid"},
            "scope_digest": SHA,
            "method_digest": {"const": digest()},
            "scale_id": {"anyOf": [UUID, {"type": "null"}]},
            "budget": {
                "type": "string",
                "pattern": r"^(0|[1-9][0-9]*)(\.[0-9]+)?$",
                "maxLength": 100,
            },
            "reason": {"type": "string", "minLength": 1, "maxLength": 4000},
        }
    ),
}


def validate(name, value):
    if not Draft202012Validator(SCHEMAS[name], format_checker=FormatChecker()).is_valid(value):
        raise DomainError(
            "PACKAGE_TECHNICAL_EXECUTION_INVALID", "整包执行请求或响应不符合专用协议", 422
        )
    return value


def extend_openapi(actual):
    base = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}"
    for suffix, method, operation_id in (
        ("/execution-context", "get", "getPackageTechnicalExecutionContext"),
        ("/executions", "post", "createPackageTechnicalExecution"),
    ):
        operation = actual.get("paths", {}).get(base + suffix, {}).get(method)
        if operation is None:
            continue
        components = actual.setdefault("components", {}).setdefault("schemas", {})
        operation["operationId"] = operation_id
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {"default": {"$ref": "#/components/responses/DomainError"}}
        if method == "get":
            components["PackageTechnicalExecutionContext"] = deepcopy(
                SCHEMAS["PackageTechnicalExecutionContext"]
            )
            operation["responses"]["200"] = {
                "description": "Exact-scope formal execution qualifications; unavailable capabilities remain explicit.",
                "headers": {"ETag": {"schema": {"type": "string"}}},
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/PackageTechnicalExecutionContext"}
                    }
                },
            }
        else:
            components["CreatePackageTechnicalExecution"] = deepcopy(
                SCHEMAS["CreatePackageTechnicalExecution"]
            )
            operation["description"] = (
                "Current release refuses formal model execution before creating a job or reserving a provider call. Isolated mechanism authority is never granted by this request."
            )
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/CreatePackageTechnicalExecution"}
                    }
                },
            }
            operation["parameters"] = [
                *[
                    row
                    for row in operation.get("parameters", [])
                    if row.get("name") not in {"If-Match", "X-CSRF-Token"}
                ],
                {
                    "name": "If-Match",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                },
                {
                    "name": "X-CSRF-Token",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ]
