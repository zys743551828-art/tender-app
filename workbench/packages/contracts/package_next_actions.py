"""Selected-run navigation recommendations; never whole-package or write qualification."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID
from packages.contracts.bid_package_api import object_schema as obj
from packages.domain.runtime import DomainError

SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
PATH = "/api/v1/bids/{bid_id}/package-next-actions/{run_id}"
COUNT = {"type": "integer", "minimum": 0, "maximum": 400}
NULL = {"type": "null"}
BINDING = obj(
    {
        "scope": obj(
            {key: UUID for key in ("bid_id", "package_id", "revision_id", "inventory_id")}
        ),
        "run_id": UUID,
        "input_digest": SHA,
        "result_digest": {"oneOf": [SHA, NULL]},
        **{key: UUID for key in ("frozen_input_id", "execution_input_id", "dependency_plan_id")},
        **{
            key: SHA
            for key in (
                "frozen_input_digest",
                "execution_input_digest",
                "dependency_plan_digest",
                "method_digest",
            )
        },
    }
)
ACTION = obj(
    {
        "level": {"type": "integer", "minimum": 1, "maximum": 6},
        "key": {
            "enum": [
                "inspect_changed_basis",
                "inspect_unknown_basis",
                "view_archived_run",
                "inspect_failed_run",
                "observe_run",
                "inspect_coverage_gaps",
                "inspect_critical_risks",
                "confirm_critical_rules",
                "inspect_scoring_scope",
                "inspect_advisories",
                "inspect_package_limitations",
            ]
        },
        "title": {"type": "string", "minLength": 1, "maxLength": 200},
        "requirement_ids": {"type": "array", "items": UUID, "maxItems": 400, "uniqueItems": True},
        "item_count": {"oneOf": [COUNT, NULL]},
    }
)
MACHINE_COUNTS = obj({"critical": COUNT, "suggestions": COUNT})
SCHEMA = obj(
    {
        "version": {"const": "package-next-actions/1"},
        "binding": BINDING,
        "method_digest": SHA,
        "confirmation_digest": SHA,
        "basis_digest": SHA,
        "basis_status": {"enum": ["matched", "changed", "unknown", "archived"]},
        "basis_issues": {
            "type": "array",
            "maxItems": 12,
            "items": obj(
                {
                    "dimension": {"type": "string", "minLength": 1, "maxLength": 50},
                    "status": {"enum": ["changed", "unknown"]},
                    "message": {"type": "string", "minLength": 1, "maxLength": 200},
                }
            ),
        },
        "observation_digest": SHA,
        "observed_at": {"type": "string", "format": "date-time"},
        "current_scope_counts": {
            "oneOf": [
                obj({"critical": COUNT, "suggestions": COUNT, "pending_critical_rules": COUNT}),
                NULL,
            ]
        },
        "historical_scope_counts": {"oneOf": [MACHINE_COUNTS, NULL]},
        "primary": ACTION,
        "other_actions": {"type": "array", "items": ACTION, "maxItems": 6},
        "remaining_critical_count": {"oneOf": [COUNT, NULL]},
        "remaining_suggestion_count": {"oneOf": [COUNT, NULL]},
        "action_mode": {"const": "navigation_only"},
        "perspective": {"const": "selected_declared_scope"},
        **{
            key: {"const": False}
            for key in (
                "original_bytes_reverified",
                "inventory_complete",
                "formal_scoring_eligible",
                "submission_eligible",
            )
        },
    }
)


def validate(value):
    if not Draft202012Validator(SCHEMA, format_checker=FormatChecker()).is_valid(value):
        raise DomainError(
            "PACKAGE_NEXT_ACTION_CONTRACT_INVALID", "所选核查的下一步不能通过完整核验", 500
        )


def extend_openapi(document):
    if "get" not in document.get("paths", {}).get(PATH, {}):
        return
    document["components"]["schemas"]["PackageNextActions"] = deepcopy(SCHEMA)
    operation = document["paths"][PATH]["get"]
    operation["operationId"] = "readSelectedPackageNextActions"
    operation["security"] = [{"SessionCookie": []}]
    operation["responses"] = {
        "200": {
            "description": "确切运行的六级导航，不授权新执行或提交",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/PackageNextActions"}}
            },
        },
        "default": {"$ref": "#/components/responses/DomainError"},
    }
