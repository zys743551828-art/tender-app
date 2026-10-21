"""Explicit complete-package submission facts, with one native submission head."""

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import SCHEMAS as PACKAGE_SCHEMAS
from packages.contracts.bid_package_api import UUID, object_schema
from packages.contracts.bid_package_requirements_api import SCHEMAS as REQUIREMENT_SCHEMAS
from packages.contracts.openapi_dependencies import schema_closure, schema_references
from packages.contracts.package_review_runs_api import SCHEMAS as RUN_SCHEMAS
from packages.domain.runtime import DomainError
from packages.identity.contracts import SCHEMAS as IDENTITY_SCHEMAS

SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 2000}
JSON = {"type": "object"}
COUNT = {"type": "integer", "minimum": 0, "maximum": 9007199254740991}
REVISION = COUNT | {"minimum": 1}
NULL = {"type": "null"}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def optional(value):
    return {"anyOf": [value, NULL]}


POINTER = object_schema({"id": UUID, "digest": SHA})
SELECTION = object_schema(
    {
        "package_id": UUID,
        "revision_id": UUID,
        "package_digest": SHA,
        "inventory": optional(POINTER),
        "coverage": optional(POINTER),
        "review_run": optional(
            object_schema({"id": UUID, "input_digest": SHA, "result_digest": optional(SHA)})
        ),
    }
)
FROZEN_SELECTION = object_schema(
    {
        "target": ref("BidPackageStoredView"),
        "authority": optional(ref("BidPackageStoredView")),
        "inventory": optional(ref("PackageRequirementInventoryView")),
        "coverage": optional(ref("PackageCoverageAttemptView")),
    }
)
HEAD = object_schema({"id": UUID, "revision": REVISION})
CURRENT_HEAD = object_schema(
    {"id": UUID, "revision": REVISION, "subject_kind": {"enum": ["single_body", "bid_package"]}}
)
DOCUMENT = object_schema({"document_version_id": UUID, "digest": SHA, "byte_size": COUNT})
ORIGINAL = object_schema(
    {
        "document_version_id": UUID,
        "digest": SHA,
        "byte_size": COUNT,
        "media_type": {"type": "string"},
        "artifact_kind": {"type": "string"},
        "original_name": {"type": "string"},
        "roles": {
            "type": "array",
            "items": {"enum": ["target", "authority", "submission_attachment", "source_ancestor"]},
            "uniqueItems": True,
            "minItems": 1,
        },
    }
)
REQUEST = object_schema(
    {
        "kind": {"enum": ["standard", "offline_fact"]},
        "selection": SELECTION,
        "input_digest": SHA,
        "evidence": DOCUMENT,
        "submitted_at": TIME,
        "explanation": TEXT,
        "expected_head": optional(HEAD),
        "correction_reason": optional(TEXT),
    }
)
COMMAND = object_schema(
    {
        "command_id": UUID,
        "actor_id": UUID,
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
        "request_digest": SHA,
        "request": REQUEST,
        "if_match": {"type": "string", "minLength": 1, "maxLength": 2000},
    }
)
BINDING = object_schema(
    {
        "version": {"const": "package-submission-binding/1"},
        "submission_id": UUID,
        "bid_id": UUID,
        "subject": object_schema(
            {
                "kind": {"const": "bid_package"},
                "bid_id": UUID,
                "package_id": UUID,
                "revision_id": UUID,
                "package_digest": SHA,
            }
        ),
        "selection": FROZEN_SELECTION,
        "selection_request": SELECTION,
        "package_identity": ref("HistoricalBidIdentitySnapshot"),
        "recorded_identity": ref("BidIdentitySnapshot"),
        "submitted_at": TIME,
        "recorded_at": TIME,
        "assessed_at": TIME,
        "actor_id": UUID,
        "command_id": UUID,
        "request": REQUEST,
        "request_digest": SHA,
        "if_match": {"type": "string", "minLength": 1, "maxLength": 2000},
        "input_digest": SHA,
        "context": JSON,
        "review_run": optional(ref("PackageReviewRunView")),
        "inventory_proof": optional(JSON),
        "gate": ref("PackageSubmissionGateView"),
        "originals": {"type": "array", "items": ORIGINAL, "minItems": 1, "maxItems": 2000},
        "evidence": ORIGINAL,
        "attachment_sources": {"type": "array", "items": JSON},
        "supersedes_id": optional(UUID),
        "head_revision": REVISION,
        "platform_submission_verified": {"const": False},
        "pre_submission_system_check_verified": {"const": False},
        "original_bytes_verified": {"const": True},
    }
)
VIEW = object_schema(
    {
        "id": UUID,
        "bid_id": UUID,
        "subject_kind": {"const": "bid_package"},
        "body_version_id": NULL,
        "review_id": NULL,
        "kind": {"enum": ["standard", "offline_fact"]},
        "submitted_at": TIME,
        "recorded_at": TIME,
        "recorded_by": UUID,
        "gate_checked": {"type": "boolean"},
        "evidence_ref": UUID,
        "current": {"type": "boolean"},
        "supersedes_id": optional(UUID),
        "identity": ref("HistoricalBidIdentitySnapshot"),
        "original_name": NULL,
        "artifact_kind": NULL,
        "checks_label": {"type": "string"},
        "open_risk_snapshot": JSON,
        "platform_submission_verified": {"const": False},
        "explanation": TEXT,
        "correction_reason": optional(TEXT),
        "package_binding": ref("PackageSubmissionBindingView"),
    }
)
SCHEMAS = {
    "PackageSubmissionSelection": SELECTION,
    "PackageSubmissionRequest": REQUEST,
    "PackageSubmissionBindingManifest": BINDING,
    "PackageSubmissionBindingView": object_schema({"manifest": BINDING, "digest": SHA}),
    "PackageSubmissionView": VIEW,
    "PackageSubmissionAppliedView": object_schema({"submission": VIEW, "command": COMMAND}),
    "PackageSubmissionPreview": object_schema(
        {
            "selection": FROZEN_SELECTION,
            "selection_request": SELECTION,
            "gate": ref("PackageSubmissionGateView"),
            "input_digest": SHA,
            "bid_etag": {"type": "string"},
            "current_submission_head": optional(CURRENT_HEAD),
        }
    ),
}


def schemas():
    from packages.domain import package_submission_gate

    return {
        **PACKAGE_SCHEMAS,
        **REQUIREMENT_SCHEMAS,
        **RUN_SCHEMAS,
        **IDENTITY_SCHEMAS,
        **package_submission_gate.SCHEMAS,
        **SCHEMAS,
    }


def valid(name, value):
    return Draft202012Validator(
        {"$ref": "#/components/schemas/" + name, "components": {"schemas": schemas()}},
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    from packages.domain.review_identity import canonical

    def contains_nul(item):
        if isinstance(item, str):
            return "\x00" in item
        if isinstance(item, list):
            return any(contains_nul(child) for child in item)
        if isinstance(item, dict):
            return any(contains_nul(key) or contains_nul(child) for key, child in item.items())
        return False

    try:
        canonical(value)
        supported = not contains_nul(value) and valid(name, value)
    except (TypeError, ValueError, RecursionError, OverflowError, UnicodeError):
        supported = False
    if not supported:
        raise DomainError("PACKAGE_SUBMISSION_INVALID", "整包实际提交登记字段不符合协议", 422)


def extend_openapi(actual):
    base = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"
    for path, request, response, operation in (
        (
            base + "/submission-preview",
            "PackageSubmissionSelection",
            "PackageSubmissionPreview",
            "previewPackageSubmission",
        ),
        (
            base + "/submissions",
            "PackageSubmissionRequest",
            "PackageSubmissionAppliedView",
            "registerPackageSubmission",
        ),
        (
            "/api/v1/submissions/{submission_id}/package-corrections",
            "PackageSubmissionRequest",
            "PackageSubmissionAppliedView",
            "correctPackageSubmission",
        ),
    ):
        item = actual.get("paths", {}).get(path, {}).get("post")
        if item is None:
            continue
        item["operationId"] = operation
        item["security"] = [{"SessionCookie": []}]
        item["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": ref(request)}},
        }
        code = "200" if path.endswith("submission-preview") else "201"
        response_definition = {
            "description": "Exact package submission observation or original immutable ACK",
            "content": {"application/json": {"schema": ref(response)}},
        }
        if code == "201":
            response_definition["headers"] = {
                "X-Bid-ETag": {
                    "description": "原成功命令完成后的强项目 ETag；重放返回原值",
                    "schema": {"type": "string", "minLength": 1},
                },
                "Idempotent-Replayed": {"schema": {"enum": ["true"]}},
            }
        item["responses"] = {
            code: response_definition,
            "default": {"$ref": "#/components/responses/DomainError"},
        }
        names = ["Origin", "X-CSRF-Token"]
        if code == "201":
            names.extend(["Idempotency-Key", "If-Match"])
        existing = {(p.get("in"), p.get("name")) for p in item.get("parameters", [])}
        item.setdefault("parameters", []).extend(
            {
                "in": "header",
                "name": name,
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
    # Shared submission GETs also expose package subjects, even in an app that
    # does not mount package writes. Follow actual operations through their
    # existing schemas rather than using either router's presence as a proxy.
    available = schemas()
    catalog = actual["components"]["schemas"] | available
    required = schema_closure(catalog, schema_references(actual.get("paths", {})))
    actual["components"]["schemas"].update(
        {name: value for name, value in required.items() if name in available}
    )
