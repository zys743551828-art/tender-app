"""Additive exact authoring contexts and four explicit choice directories.

The frozen package-work-context A schema is imported without modification. Rich
text schemas reuse the actual editor's closed definitions under independent names;
private snapshot image locators and arbitrary extension metadata are not exposed.
"""

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from packages.authoring import contracts as text_contracts
from packages.authoring import rich_contracts
from packages.contracts import work_context_api as base
from packages.contracts.bid_package_api import UUID
from packages.contracts.bid_package_api import object_schema as obj
from packages.domain.runtime import DomainError

BASE = base.BASE
CHOICES_PATH = BASE + "/choices"
SNAPSHOT_PATH = BASE + "/draft_snapshot/{snapshot_id}"
BUILD_PATH = BASE + "/build/{build_id}"
KINDS = ("draft_snapshot", "build", "package_review_run", "package_submission")
SHA, TIME, NULL = base.SHA, base.TIME, base.NULL
REV = {"type": "integer", "minimum": 1}
TITLE = {"type": "string", "minLength": 1, "maxLength": 200}
OPERATION = base.STATE["oneOf"][0]["properties"]["operation_state"]


def optional(schema):
    return base.optional(schema)


def ref(name):
    return base.ref(name)


def array(schema, maximum=500):
    return {"type": "array", "items": schema, "maxItems": maximum}


def _content_schemas():
    # These existing functions only assemble JSON schema. No API route, provider,
    # model, filesystem contract or application export is initialized here.
    actual: dict[str, Any] = {
        "paths": {"/api/v1/authoring/rich-capabilities": {}},
        "components": {
            "schemas": {
                name: obj({})
                for name in (
                    "BuildRequest",
                    "BuildView",
                    "SectionChange",
                    "SectionView",
                    "DraftSaved",
                )
            }
        },
    }
    text_contracts.extend_openapi(actual)
    rich_contracts.extend_openapi(actual)
    schemas = actual["components"]["schemas"]
    selected = {}

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].split("/")[-1]
                if name not in selected:
                    selected[name] = deepcopy(schemas[name])
                    walk(selected[name])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(ref("AuthoringRichDocument"))

    def renamed(value):
        if isinstance(value, dict):
            return {
                key: "#/components/schemas/WorkContextReadOnly" + item.split("/")[-1]
                if key == "$ref"
                else renamed(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [renamed(item) for item in value]
        return value

    return {"WorkContextReadOnly" + name: renamed(value) for name, value in selected.items()}


SNAPSHOT_SELECTION = obj(
    {
        "kind": {"const": "draft_snapshot"},
        "bid_id": UUID,
        "draft_id": UUID,
        "draft_revision": REV,
        "snapshot_id": UUID,
        "snapshot_digest": SHA,
    }
)
BUILD_SELECTION = obj({"kind": {"const": "build"}, **base.BUILD_IDENTITY["properties"]})
AUTHORING_SELECTION = {"oneOf": [SNAPSHOT_SELECTION, BUILD_SELECTION]}
ANY_SELECTION = {
    "oneOf": [SNAPSHOT_SELECTION, BUILD_SELECTION, base.RUN_SELECTION, base.SUBMISSION_SELECTION]
}
SNAPSHOT = obj(
    {
        **{key: value for key, value in SNAPSHOT_SELECTION["properties"].items() if key != "kind"},
        "title": TITLE,
        "created_at": TIME,
        "section_count": {"type": "integer", "minimum": 0, "maximum": 500},
    }
)
SECTION = obj(
    {
        "section_id": UUID,
        "section_revision_id": UUID,
        "section_revision": REV,
        "schema_digest": SHA,
        "digest": SHA,
        "ordinal": {"type": "integer", "minimum": 0, "maximum": 499},
        "title": TITLE,
        "content": ref("WorkContextReadOnlyAuthoringRichDocument"),
    }
)
OUTLINE = obj(
    {
        "section_id": UUID,
        "parent_id": optional(UUID),
        "ordinal": {"type": "integer", "minimum": 0, "maximum": 499},
        "node_type": {"enum": ["chapter", "appendix"]},
    }
)
IMAGE = obj(
    {
        "asset_id": UUID,
        "asset_revision": REV,
        "asset_version_id": UUID,
        "version_digest": SHA,
        "normalized_sha256": SHA,
        "media_type": {"const": "image/png"},
    }
)
DOCUMENT = obj(
    {
        "sections": array(SECTION),
        "outline": optional(array(OUTLINE)),
        "images": array(IMAGE, 10000),
        "editable": {"const": False},
    }
)
OUTPUT_DOCUMENT = obj(
    {
        "document_version_id": UUID,
        "sha256": SHA,
        "byte_size": REV,
        "media_type": {
            "enum": [
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/pdf",
            ]
        },
        "publication_proof_digest": SHA,
    }
)
OUTPUT = obj(
    {
        "format": {"enum": ["docx", "pdf"]},
        "requested": {"type": "boolean"},
        "state": {"enum": ["pending", "succeeded", "failed", "not_published"]},
        "document": optional(OUTPUT_DOCUMENT),
        "gaps": array({"type": "string", "minLength": 1, "maxLength": 200}, 100),
    }
)
OUTPUT["allOf"] = [
    {
        "if": {"properties": {"state": {"const": "succeeded"}}},
        "then": {"properties": {"document": OUTPUT_DOCUMENT}},
        "else": {"properties": {"document": NULL}},
    }
]
BUILD = obj(
    {
        "operation_id": UUID,
        "operation_state": OPERATION,
        "created_at": TIME,
        "outputs": array(OUTPUT, 2),
    }
)
SUMMARY = obj(
    {
        "perspective": {"const": "saved_authoring_history"},
        "whole_package_blocking_risk_count": NULL,
        "whole_package_passed": NULL,
        "formal_scoring": deepcopy(
            base.SCHEMAS["WorkContextSummary"]["properties"]["formal_scoring"]
        ),
        "official_labels_read": {"const": False},
        "primary_action": {"enum": ["open_selected_snapshot", "view_selected_build"]},
        "action_mode": {"const": "navigation_only"},
    }
)
SCHEMAS = {
    **_content_schemas(),
    "WorkContextDraftSelection": SNAPSHOT_SELECTION,
    "WorkContextBuildSelection": BUILD_SELECTION,
    "WorkContextAuthoringSelection": AUTHORING_SELECTION,
    "WorkContextAnySelection": ANY_SELECTION,
    "WorkContextSnapshotMetadata": SNAPSHOT,
    "WorkContextSnapshotSection": SECTION,
    "WorkContextSnapshotDocument": DOCUMENT,
    "WorkContextBuildOutput": OUTPUT,
    "WorkContextBuildDetails": BUILD,
    "WorkContextAuthoringSummary": SUMMARY,
    "AuthoringWorkContext": obj(
        {
            "version": {"const": "authoring-work-context/1"},
            "selection": AUTHORING_SELECTION,
            "selection_digest": SHA,
            "observed_at": TIME,
            "observation_digest": SHA,
            "snapshot": SNAPSHOT,
            "document": optional(DOCUMENT),
            "build": optional(BUILD),
            "current_observation": obj(
                {
                    key: deepcopy(base.SCHEMAS["WorkContextDimensionObservation"])
                    for key in ("draft_head", "sources", "assets")
                }
            ),
            "summary": SUMMARY,
            "native_targets": obj(
                {
                    "draft_snapshot": SNAPSHOT_SELECTION,
                    "current_draft": obj(
                        {"kind": {"const": "draft"}, "bid_id": UUID, "draft_id": UUID}
                    ),
                    "build": optional(BUILD_SELECTION),
                    "build_relations": optional(
                        obj(
                            {
                                "kind": {"const": "build_package_relations"},
                                "bid_id": UUID,
                                "build_id": UUID,
                            }
                        )
                    ),
                }
            ),
            "original_bytes_reverified": {"const": False},
            "qualification_assessed": {"const": False},
            "limitations": array({"type": "string", "minLength": 1, "maxLength": 100}, 30),
        }
    ),
}
SCHEMAS["AuthoringWorkContext"]["allOf"] = [
    {
        "if": {"properties": {"selection": {"properties": {"kind": {"const": "draft_snapshot"}}}}},
        "then": {"properties": {"document": DOCUMENT, "build": NULL}},
        "else": {"properties": {"document": NULL, "build": BUILD}},
    }
]
CHOICE = obj(
    {
        "kind": {"enum": list(KINDS)},
        "id": UUID,
        "label": {"type": "string", "minLength": 1, "maxLength": 300},
        "created_at": TIME,
        "status": {"enum": ["saved", "standard", "offline_fact", *OPERATION["enum"]]},
        "selection": ANY_SELECTION,
        "selection_digest": SHA,
    }
)
FILTERS = obj({key: optional(UUID) for key in ("draft_id", "package_id", "revision_id")})
SCHEMAS.update(
    {
        "WorkContextChoice": CHOICE,
        "WorkContextChoicePage": obj(
            {
                "version": {"const": "work-context-choice-page/1"},
                "bid_id": UUID,
                "kind": {"enum": list(KINDS)},
                "filters": FILTERS,
                "observed_at": TIME,
                "observation_digest": SHA,
                "items": array(CHOICE, 50),
                "total": {"type": "integer", "minimum": 0, "maximum": 1000},
                "has_more": {"type": "boolean"},
                "next_cursor": {"type": ["string", "null"], "maxLength": 4096},
                "complete_observation": {"const": True},
                "directory_basis": {"const": "native_record_identity_and_state"},
                "selection_requires_resolution": {"const": True},
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
        raise DomainError("WORK_CONTEXT_INVALID", "工作上下文目录或历史正文不符合封闭协议", 422)
    return value


def extend_openapi(document):
    routes = (
        (SNAPSHOT_PATH, "resolveExactDraftSnapshotWorkContext", "AuthoringWorkContext"),
        (BUILD_PATH, "resolveExactBuildWorkContext", "AuthoringWorkContext"),
        (CHOICES_PATH, "listExplicitWorkContextChoices", "WorkContextChoicePage"),
    )
    mounted = [(p, o, n) for p, o, n in routes if "get" in document["paths"].get(p, {})]
    if not mounted:
        return
    document["components"]["schemas"].update(deepcopy(SCHEMAS))
    for path, operation, name in mounted:
        get = document["paths"][path]["get"]
        get["operationId"] = operation
        get["security"] = [{"SessionCookie": []}]
        get["responses"] = {
            "200": {
                "description": "明确历史选择的只读目录或已保存正文／构建；没有默认选择或当前资格",
                "headers": {"Cache-Control": {"schema": {"const": "private, no-store"}}},
                "content": {"application/json": {"schema": ref(name)}},
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
