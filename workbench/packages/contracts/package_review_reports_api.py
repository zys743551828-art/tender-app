"""Implemented immutable copies of package review reports; never submission bodies."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.contracts.package_review_decisions_api import SCHEMAS as HUMAN_SCHEMAS
from packages.contracts.package_review_runs_api import BASE, SCOPE, SHA, TIME
from packages.domain.runtime import DomainError

RUN_BASE = BASE + "/{run_id}"
EXPORT_BASE = RUN_BASE + "/report-exports"
FORMAT = {"enum": ["docx", "pdf"]}
FLAGS = {key: {"const": False} for key in ("formal_scoring_eligible", "submission_eligible")}
BINDING = {
    "scope": SCOPE,
    "frozen_input_id": UUID,
    "execution_input_id": UUID,
    "run_id": UUID,
    "input_digest": SHA,
    "result_digest": SHA,
}
RENDERER = object_schema(
    {
        "renderer_digest": SHA,
        "renderer_version": {"type": "string", "minLength": 1, "maxLength": 2000},
        "fontset_digest": SHA,
        "options_digest": SHA,
    }
)
PROFILE = object_schema(
    {
        "version": {"const": "package-review-report/1"},
        "writer_digest": SHA,
        "reporter_digest": SHA,
        "pdf_renderer": {"anyOf": [RENDERER, {"type": "null"}]},
    }
)
CONTEXT = object_schema(
    {
        **BINDING,
        "human_decisions": {"$ref": "#/components/schemas/PackageReviewHumanDecisionCurrent"},
        "method": PROFILE,
        **FLAGS,
    }
)
OPERATION = object_schema(
    {
        "id": UUID,
        "kind": {"const": "package-scope-report"},
        "state": {
            "enum": ["queued", "running", "cancel_requested", "succeeded", "failed", "cancelled"]
        },
        "input_digest": SHA,
        "handler_version": {"const": "package-report/1"},
        "error_code": {"type": ["string", "null"], "maxLength": 200},
        "created_at": TIME,
        "finished_at": {"anyOf": [TIME, {"type": "null"}]},
    }
)
SCHEMAS = {
    **deepcopy(HUMAN_SCHEMAS),
    "PackageReviewReportContext": object_schema(
        {
            **BINDING,
            "human_decisions_digest": SHA,
            "method_digest": SHA,
            "context_digest": SHA,
            "formats": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "uniqueItems": True,
                "items": FORMAT,
            },
            "pdf_unavailable_code": {"type": ["string", "null"], "maxLength": 200},
            **FLAGS,
        }
    ),
    "StartPackageReviewReport": object_schema({"context_digest": SHA, "format": FORMAT}),
    "PackageReviewReportInput": object_schema(
        {
            "version": {"const": "package-review-report-input/1"},
            "context": CONTEXT,
            "context_digest": SHA,
            "format": FORMAT,
            "artifact_kind": {"const": "review_report"},
            **FLAGS,
        }
    ),
    "PackageReviewReportView": object_schema(
        {
            **BINDING,
            "id": UUID,
            "actor_id": UUID,
            "created_at": TIME,
            "context_digest": SHA,
            "report_input_digest": SHA,
            "format": FORMAT,
            "artifact_kind": {"const": "review_report"},
            "operation": OPERATION,
            "result": {
                "anyOf": [
                    object_schema(
                        {
                            "document_version_id": UUID,
                            "blob_digest": SHA,
                            "byte_size": {"type": "integer", "minimum": 1},
                            "media_type": {
                                "enum": [
                                    "application/pdf",
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                ]
                            },
                            "filename": {"type": "string", "minLength": 1, "maxLength": 200},
                            "gaps": {
                                "type": "array",
                                "maxItems": 100,
                                "items": {"type": "string", "maxLength": 200},
                            },
                        }
                    ),
                    {"type": "null"},
                ]
            },
            **FLAGS,
        }
    ),
    "PackageReviewReportPage": object_schema(
        {
            **BINDING,
            "items": {
                "type": "array",
                "maxItems": 50,
                "items": {"$ref": "#/components/schemas/PackageReviewReportView"},
            },
            "has_more": {"type": "boolean"},
            "next_cursor": {"type": ["string", "null"], "maxLength": 4096},
        }
    ),
}


def valid(name, value):
    return Draft202012Validator(
        {"components": {"schemas": SCHEMAS}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    if not valid(name, value):
        raise DomainError("PACKAGE_REVIEW_REPORT_INVALID", "整包报告字段不符合已实现协议", 422)
    return value


def extend_openapi(document):
    operations = (
        (
            RUN_BASE + "/report-context",
            "get",
            "getPackageReviewReportContext",
            None,
            "PackageReviewReportContext",
            "200",
        ),
        (
            EXPORT_BASE,
            "post",
            "startPackageReviewReport",
            "StartPackageReviewReport",
            "PackageReviewReportView",
            "202",
        ),
        (EXPORT_BASE, "get", "listPackageReviewReports", None, "PackageReviewReportPage", "200"),
        (
            EXPORT_BASE + "/{export_id}",
            "get",
            "getPackageReviewReport",
            None,
            "PackageReviewReportView",
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
                "description": "原运行及申请时人工记录的报告副本",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/" + response_name}
                    }
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
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
