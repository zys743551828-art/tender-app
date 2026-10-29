"""Implemented /3 check protocol, distinct from formal execution qualification."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID
from packages.contracts.bid_package_api import object_schema as obj
from packages.contracts.package_technical_eligibility_api import SCHEMAS as ELIGIBILITY
from packages.contracts.package_technical_scope_api import GAP, SHA
from packages.domain.runtime import DomainError
from packages.model_governance import package_technical_complete_vision as vision

REFERENCE = obj(
    {
        "seal_id": UUID,
        "seal_digest": SHA,
        "input_digest": SHA,
        "quote_id": UUID,
        "quote_digest": SHA,
    }
)
REQUEST = obj(
    {
        "version": {"const": "package-material-execution-check/1"},
        "scope_digest": SHA,
        "profile_digest": SHA,
        "serializer_digest": SHA,
        "judgment_method_digest": SHA,
        "input_reference": {"anyOf": [REFERENCE, {"type": "null"}]},
        "budget_usd": {
            "type": "string",
            "pattern": r"^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$",
            "maxLength": 30,
        },
    }
)
SCHEMAS = {
    "PackageMaterialExecutionCheck": REQUEST,
    "PackageMaterialExecutionContext": obj(
        {
            "version": {"const": "package-material-execution-context/1"},
            "qualification": deepcopy(ELIGIBILITY["PackageTechnicalScoringContext"]),
            "target": obj(
                {
                    "profile": {"const": vision.profile()},
                    "profile_digest": SHA,
                    "serializer_digest": SHA,
                    "judgment_method_digest": SHA,
                }
            ),
            "execution_enabled": {"const": False},
            "blockers": {"type": "array", "items": GAP, "minItems": 3},
        }
    ),
    "PackageMaterialExecutionReceipt": obj(
        {
            "version": {"const": "package-material-execution-receipt/1"},
            "command_id": UUID,
            "actor_id": UUID,
            "scope_id": UUID,
            "scope_digest": SHA,
            "request_digest": SHA,
            "request": REQUEST,
            "observed_at": {"type": "string", "format": "date-time"},
            "state": {"const": "blocked"},
            "reference_status": {"const": "unverified"},
            "execution_authorized": {"const": False},
            "jobs_created": {"const": 0},
            "model_requests": {"const": 0},
            "fee_reserved": {"const": False},
            "blockers": {"type": "array", "items": GAP, "minItems": 3},
        }
    ),
}


def validate(name, value):
    if not Draft202012Validator(SCHEMAS[name], format_checker=FormatChecker()).is_valid(value):
        raise DomainError("MATERIAL_EXECUTION_CHECK_INVALID", "完整材料请求或回执不符合协议", 422)
    return value


def extend_openapi(actual):
    base = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}"
    for suffix, method, name in (
        ("/material-execution-context", "get", "PackageMaterialExecutionContext"),
        ("/material-execution-checks", "post", "PackageMaterialExecutionReceipt"),
    ):
        op = actual.get("paths", {}).get(base + suffix, {}).get(method)
        if op is None:
            continue
        actual.setdefault("components", {}).setdefault("schemas", {}).update(deepcopy(SCHEMAS))
        op["security"] = [{"SessionCookie": []}]
        op["responses"] = {
            "200": {
                "description": "Persisted refusal is historical, never live authority.",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + name}}
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
        if method == "post":
            op["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/PackageMaterialExecutionCheck"}
                    }
                },
            }
            op["parameters"] = op.get("parameters", []) + [
                {"name": key, "in": "header", "required": True, "schema": {"type": "string"}}
                for key in ("If-Match", "Idempotency-Key", "X-CSRF-Token")
            ]
