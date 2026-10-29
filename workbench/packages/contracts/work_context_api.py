"""Closed contracts for exact historical selections and scoped read-only summaries.

These schemas describe only the separately mounted implementation. They do not
alter the reviewed target contract or automatically register application routes.
"""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID
from packages.contracts.bid_package_api import object_schema as obj
from packages.domain.runtime import DomainError
from packages.identity.contracts import HISTORICAL_SNAPSHOT

BASE = "/api/v1/bids/{bid_id}/work-contexts"
RUN_PATH = BASE + "/package_review_run/{run_id}"
SUBMISSION_PATH = BASE + "/package_submission/{submission_id}"
RELATIONS_PATH = BASE + "/build/{build_id}/relations"
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
NULL = {"type": "null"}
COUNT = {"type": "integer", "minimum": 0, "maximum": 400}
VERDICTS = ("satisfied", "violated", "not_found", "unable_to_judge", "not_applicable")
HUMAN_STATES = ("unreviewed", "confirmed", "rejected", "needs_review")
DIMENSIONS = (
    "identity",
    "package_head",
    "authority_head",
    "inventory_head",
    "rule_set_head",
    "sources",
    "selected_facts",
    "executor_method",
    "submission_head",
    "review_run_head",
    "bound_run_state",
)


def optional(schema):
    return {"anyOf": [deepcopy(schema), NULL]}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


PACKAGE = obj({"bid_id": UUID, "package_id": UUID, "revision_id": UUID, "package_digest": SHA})
RUN_SELECTION = obj(
    {
        "kind": {"const": "package_review_run"},
        **PACKAGE["properties"],
        "inventory_id": UUID,
        "inventory_digest": SHA,
        "frozen_input_id": UUID,
        "frozen_input_digest": SHA,
        "execution_input_id": UUID,
        "execution_input_digest": SHA,
        "dependency_plan_id": UUID,
        "dependency_plan_digest": SHA,
        "run_id": UUID,
        "input_digest": SHA,
        "method_digest": SHA,
        "result_digest": optional(SHA),
    }
)
SUBMISSION_SELECTION = obj(
    {
        "kind": {"const": "package_submission"},
        **PACKAGE["properties"],
        "submission_id": UUID,
        "package_binding_digest": SHA,
        "inventory": optional(obj({"id": UUID, "digest": SHA})),
        "review_run": optional(RUN_SELECTION),
    }
)
RUN_TARGET = obj(
    {
        "kind": {"const": "package_review_run"},
        "bid_id": UUID,
        "package_id": UUID,
        "revision_id": UUID,
        "inventory_id": UUID,
        "frozen_input_id": UUID,
        "execution_input_id": UUID,
        "run_id": UUID,
        "input_digest": SHA,
        "result_digest": optional(SHA),
    }
)
PACKAGE_TARGET = obj({"kind": {"const": "package_revision"}, **PACKAGE["properties"]})
SUBMISSION_TARGET = obj(
    {
        "kind": {"const": "package_submission"},
        "bid_id": UUID,
        "submission_id": UUID,
        "package_binding_digest": SHA,
    }
)
SCHEMAS = {
    "WorkContextRunSelection": RUN_SELECTION,
    "WorkContextSubmissionSelection": SUBMISSION_SELECTION,
    "WorkContextSelection": {"oneOf": [RUN_SELECTION, SUBMISSION_SELECTION]},
    "WorkContextDimensionObservation": obj(
        {
            "status": {"enum": ["matched", "changed", "unknown", "not_applicable"]},
            "selected_digest": optional(SHA),
            "observed_digest": optional(SHA),
            "reason": {"type": "string", "minLength": 1, "maxLength": 100},
        }
    ),
    "WorkContextNativeTargets": obj(
        {
            "package_revision": PACKAGE_TARGET,
            "authority_revision": optional(PACKAGE_TARGET),
            "package_review_run": optional(RUN_TARGET),
            "package_submission": optional(SUBMISSION_TARGET),
        }
    ),
    "WorkContextReviewSummary": obj(
        {
            "run_id": UUID,
            "input_digest": SHA,
            "result_digest": SHA,
            "requirement_count": COUNT | {"minimum": 1},
            "machine_counts": obj({key: COUNT for key in VERDICTS}),
            "human_counts": obj({key: COUNT for key in HUMAN_STATES}),
            "human_heads_digest": SHA,
            "human_basis": {"const": "current_heads_for_exact_result"},
            "matrix_coverage": {"enum": ["complete", "partial"]},
            "overall_coverage": {"const": "partial"},
            "inventory_complete": {"const": False},
            "quality_status": {"const": "not_measured"},
            "risk_resolution_assessed": {"const": False},
        }
    ),
    "WorkContextSummary": obj(
        {
            "perspective": {"enum": ["declared_scope_history", "submission_history"]},
            "review_status": {
                "enum": [
                    "result_available",
                    "run_unfinished",
                    "bound_result_missing",
                    "not_selected",
                ]
            },
            "review": optional(ref("WorkContextReviewSummary")),
            "whole_package_blocking_risk_count": NULL,
            "whole_package_passed": NULL,
            "formal_scoring": obj(
                {
                    "status": {"const": "scope_not_selected"},
                    "scope_id": NULL,
                    "numeric_prediction": NULL,
                }
            ),
            "official_labels_read": {"const": False},
            "primary_action": {
                "enum": [
                    "open_selected_review",
                    "view_selected_operation",
                    "inspect_changed_basis",
                    "open_selected_submission",
                ]
            },
            "action_mode": {"const": "navigation_only"},
        }
    ),
}
STATE = {
    "oneOf": [
        obj(
            {
                "kind": {"const": "package_review_run"},
                "operation_id": UUID,
                "operation_state": {
                    "enum": [
                        "queued",
                        "running",
                        "cancel_requested",
                        "succeeded",
                        "failed",
                        "cancelled",
                    ]
                },
                "result_available": {"type": "boolean"},
            }
        ),
        obj(
            {
                "kind": {"const": "package_submission"},
                "registration_kind": {"enum": ["standard", "offline_fact"]},
                "submitted_at": TIME,
                "recorded_at": TIME,
                "supersedes_id": optional(UUID),
                "gate_checked_at_registration": {"type": "boolean"},
                "platform_submission_verified": {"const": False},
                "pre_submission_system_check_verified": {"const": False},
            }
        ),
    ]
}
SCHEMAS["PackageWorkContext"] = obj(
    {
        "version": {"const": "package-work-context/1"},
        "selection": ref("WorkContextSelection"),
        "selection_digest": SHA,
        "observed_at": TIME,
        "observation_digest": SHA,
        "identity": deepcopy(HISTORICAL_SNAPSHOT),
        "state": STATE,
        "current_observation": obj(
            {key: ref("WorkContextDimensionObservation") for key in DIMENSIONS}
        ),
        "summary": ref("WorkContextSummary"),
        "native_targets": ref("WorkContextNativeTargets"),
        "original_bytes_reverified": {"const": False},
        "limitations": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 30,
            "items": {"type": "string", "minLength": 1, "maxLength": 100},
        },
    }
)
BUILD_IDENTITY = obj(
    {
        "bid_id": UUID,
        "build_id": UUID,
        "draft_id": UUID,
        "draft_revision": {"type": "integer", "minimum": 1},
        "snapshot_id": UUID,
        "snapshot_digest": SHA,
        "build_input_id": UUID,
        "input_digest": SHA,
        "manifest_digest": SHA,
        "writer_kind": {"type": "string", "minLength": 1, "maxLength": 100},
    }
)
OUTPUT = obj({"document_version_id": UUID, "format": {"enum": ["docx", "pdf"]}, "sha256": SHA})
RELATION = obj(
    {
        "id": SHA,
        "kind": {"enum": ["adopted_into", "contains_output"]},
        "output": OUTPUT,
        "package_revision": PACKAGE_TARGET,
        "package_revision_number": {"type": "integer", "minimum": 1},
        "proof_digest": SHA,
        "adoption_command_id": optional(UUID),
        "adopted_at": optional(TIME),
        "current_package_head": ref("WorkContextDimensionObservation"),
        "current_source_basis": ref("WorkContextDimensionObservation"),
        "qualification_assessed": {"const": False},
    }
)
SCHEMAS.update(
    {
        "WorkContextBuildIdentity": BUILD_IDENTITY,
        "WorkContextRelation": RELATION,
        "WorkContextRelationPage": obj(
            {
                "version": {"const": "package-work-context-relations/1"},
                "seed": BUILD_IDENTITY,
                "target": {"const": "package_revision"},
                "observed_at": TIME,
                "observation_digest": SHA,
                "items": {"type": "array", "maxItems": 50, "items": RELATION},
                "total": {"type": "integer", "minimum": 0, "maximum": 2000},
                "has_more": {"type": "boolean"},
                "next_cursor": {"type": ["string", "null"], "maxLength": 4096},
                "complete_observation": {"const": True},
                "original_bytes_reverified": {"const": False},
                "qualification_assessed": {"const": False},
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
        raise DomainError("WORK_CONTEXT_INVALID", "工作上下文字段不符合已实现只读协议", 422)
    return value


def extend_openapi(document):
    routes = (
        (RUN_PATH, "resolveExactPackageReviewWorkContext", "PackageWorkContext"),
        (SUBMISSION_PATH, "resolveExactPackageSubmissionWorkContext", "PackageWorkContext"),
        (RELATIONS_PATH, "listExactBuildPackageRelations", "WorkContextRelationPage"),
    )
    mounted = [
        (path, operation, name)
        for path, operation, name in routes
        if "get" in document["paths"].get(path, {})
    ]
    if not mounted:
        return
    document["components"]["schemas"].update(deepcopy(SCHEMAS))
    for path, operation, name in mounted:
        get = document["paths"][path]["get"]
        get["operationId"] = operation
        get["security"] = [{"SessionCookie": []}]
        get["responses"] = {
            "200": {
                "description": "同一只读快照中的精确历史身份和范围摘要；不授予当前资格",
                "headers": {"Cache-Control": {"schema": {"const": "private, no-store"}}},
                "content": {"application/json": {"schema": ref(name)}},
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
