"""Implemented immutable package retrospectives and explicit knowledge hand-off."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID
from packages.contracts.bid_package_api import object_schema as obj
from packages.contracts.openapi_dependencies import schema_closure
from packages.contracts.package_outcomes_api import EVIDENCE_REF, STATES
from packages.contracts.package_review_comparisons_api import SCHEMAS as COMPARISON_SCHEMAS
from packages.domain.runtime import DomainError
from packages.identity.contracts import SCHEMAS as IDENTITY_SCHEMAS
from packages.metrics.contracts import SCHEMAS as METRIC_SCHEMAS

BASE = "/api/v1/bids/{bid_id}/package-retrospectives"
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
TEXT = {
    "type": "string",
    "minLength": 1,
    "maxLength": 4000,
    "pattern": r"\S",
    "not": {"pattern": r"[\u0000\uD800-\uDFFF]"},
}
NULL = {"type": "null"}
BOOL = {"type": "boolean"}
POS = {"type": "integer", "minimum": 1}
DECIMAL = {"type": "string", "pattern": r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"}
LIMITS = {"snapshot_bytes": 8 * 1024 * 1024, "source_rows": 20000, "documents": 100}
FLAGS = {
    key: {"const": False}
    for key in (
        "official_deduction_reasons_inferred",
        "risk_resolution_assessed",
        "formal_sample_eligible",
        "model_qualification_granted",
        "knowledge_published",
    )
}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def optional(value):
    return {"anyOf": [value, NULL]}


def array(value, maximum=100):
    return {"type": "array", "items": value, "maxItems": maximum}


SELECTION = obj(
    {
        "submission_id": UUID,
        "outcome_id": optional(UUID),
        "outcome_missing_reason": optional(TEXT),
        "business_result_id": optional(UUID),
        "business_result_missing_reason": optional(TEXT),
        "baseline_run_id": optional(UUID),
        "submitted_run_id": optional(UUID),
        "reviews_missing_reason": optional(TEXT),
    }
)
NOTES = obj(
    {
        "observations": TEXT | {"maxLength": 12000},
        "hypotheses": {"type": "string", "maxLength": 12000},
        "next_actions": TEXT | {"maxLength": 12000},
        "additional_missing_materials": {"type": "string", "maxLength": 4000},
    }
)
FREEZE = obj(
    {
        "selection": SELECTION,
        "preview_digest": HASH,
        "title": TEXT | {"maxLength": 200},
        "notes": NOTES,
    }
)
HANDOFF = obj({"retrospective_digest": HASH, "reason": TEXT})
SOURCE = obj(
    {
        "source_id": UUID,
        "ancestor_id": UUID,
        "document_version_id": optional(UUID),
        "document_bid_id": optional(UUID),
        "kind": {"enum": ["document", "knowledge", "summary", "feature", "label", "model"]},
        "policy_class": {
            "enum": ["prebid_content", "official_label", "post_outcome", "derived_mixed"]
        },
        "known_at": TIME,
        "digest": HASH,
        "revision": optional(POS),
        "status": {"enum": [None, "candidate", "published", "withdrawn"]},
        "valid_from": optional(TIME),
        "valid_until": optional(TIME),
    }
)
DOCUMENT = obj(
    {
        "id": UUID,
        "original_name": TEXT,
        "digest": HASH,
        "byte_size": {"type": "integer", "minimum": 0},
    }
)
SUBMISSION = obj(
    {
        "id": UUID,
        "package_id": UUID,
        "revision_id": UUID,
        "package_digest": HASH,
        "binding_digest": HASH,
        "identity": ref("HistoricalBidIdentitySnapshot"),
        "kind": {"enum": ["standard", "offline_fact"]},
        "submitted_at": TIME,
        "recorded_at": TIME,
        "current": BOOL,
        "registration_risk_digest": HASH,
        "registration_assessed_at": TIME,
        "risk_resolution_assessed": {"const": False},
    }
)
OUTCOME = obj(
    {
        "id": UUID,
        "submission_id": UUID,
        "score_kind": {"enum": ["technical_total", "overall_total", "unknown"]},
        "value": optional(DECIMAL),
        "maximum": optional(DECIMAL),
        "source_version_id": UUID,
        "known_at": TIME,
        "supersedes_id": optional(UUID),
        "verification": {"enum": STATES},
        "verification_revision": {"type": "integer", "minimum": 0},
        "verification_id": optional(UUID),
        "verification_details_digest": optional(HASH),
        "aggregation": optional({"type": "string", "maxLength": 200}),
        "published_at": optional(TIME),
        "evidence_refs": array(EVIDENCE_REF),
        "current": BOOL,
        "association_reasons": array(TEXT),
    }
)
GAP = obj({"code": TEXT, "message": TEXT})
BUSINESS = obj(
    {
        key: deepcopy(value)
        for key, value in METRIC_SCHEMAS["BusinessResultView"]["properties"].items()
        if key not in {"usable", "unusable_reasons"}
    }
)
PREVIEW = obj(
    {
        "version": {"const": "package-retrospective-preview/1"},
        "bid_id": UUID,
        "selection": SELECTION,
        "submission": SUBMISSION,
        "outcome": optional(OUTCOME),
        "business_result": optional(BUSINESS),
        "comparison": optional(
            obj({"manifest": ref("PackageReviewComparisonManifest"), "digest": HASH})
        ),
        "source_ids": array(UUID, 400),
        "source_snapshot": array(SOURCE, LIMITS["source_rows"]),
        "documents": array(DOCUMENT, LIMITS["documents"]),
        "gaps": array(GAP, 100),
        "timing": {"const": "post_outcome_retrospective"},
        **FLAGS,
    }
)
PACKET = obj({"manifest": PREVIEW, "digest": HASH})
FROZEN = obj(
    {
        "version": {"const": "package-retrospective/1"},
        "id": UUID,
        "bid_id": UUID,
        "actor_id": UUID,
        "command_id": UUID,
        "created_at": TIME,
        "state": {"const": "pending_review"},
        "title": TEXT | {"maxLength": 200},
        "notes": NOTES,
        "preview": PACKET,
        **FLAGS,
    }
)
RETROSPECTIVE = obj({"manifest": FROZEN, "digest": HASH})
ORIGIN = obj(
    {
        "retrospective_id": UUID,
        "retrospective_digest": HASH,
        "preview_digest": HASH,
        "source_id": UUID,
    }
)
LINK = obj(
    {
        "retrospective_id": UUID,
        "retrospective_digest": HASH,
        "knowledge_id": UUID,
        "knowledge_version_id": UUID,
        "source_id": UUID,
        "created_at": TIME,
        "actor_id": UUID,
        "reason": TEXT,
        "policy_class": {"const": "derived_mixed"},
        "knowledge_published": {"const": False},
        "formal_sample_eligible": {"const": False},
    }
)
CURRENT = obj({"unchanged": BOOL, "issues": array(GAP, 100)})
COMMAND = obj(
    {
        "command_id": UUID,
        "actor_id": UUID,
        "idempotency_key": TEXT | {"maxLength": 128},
        "request_digest": HASH,
        "request": {"anyOf": [FREEZE, HANDOFF]},
        "if_match": TEXT,
    }
)
CHOICE = obj(
    {
        "id": UUID,
        "label": TEXT,
        "current": optional(BOOL),
        "package_id": optional(UUID),
        "revision_id": optional(UUID),
    }
)
SCHEMAS = {
    "PackageRetrospectiveSelection": SELECTION,
    "PackageRetrospectiveNotes": NOTES,
    "PackageRetrospectiveRequest": FREEZE,
    "PackageRetrospectiveKnowledgeRequest": HANDOFF,
    "PackageRetrospectivePreview": PACKET,
    "PackageRetrospectiveView": RETROSPECTIVE,
    "PackageRetrospectiveOrigin": ORIGIN,
    "PackageRetrospectiveKnowledgeLink": LINK,
    "PackageRetrospectiveCurrent": CURRENT,
    "PackageRetrospectiveApplied": obj({"retrospective": RETROSPECTIVE, "command": COMMAND}),
    "PackageRetrospectiveKnowledgeApplied": obj({"link": LINK, "command": COMMAND}),
    "PackageRetrospectiveDetail": obj(
        {"retrospective": RETROSPECTIVE, "current": CURRENT, "knowledge_link": optional(LINK)}
    ),
    "PackageRetrospectivePage": obj(
        {
            "bid_id": UUID,
            "items": array(
                obj(
                    {
                        "id": UUID,
                        "title": TEXT,
                        "submission_id": UUID,
                        "created_at": TIME,
                        "digest": HASH,
                    }
                ),
                100,
            ),
            "next_offset": optional({"type": "integer", "minimum": 0}),
        }
    ),
    "PackageRetrospectiveChoices": obj(
        {
            "bid_id": UUID,
            "kind": {"enum": ["submissions", "outcomes", "business_results", "runs"]},
            "submission_id": optional(UUID),
            "items": array(CHOICE),
            "next_offset": optional({"type": "integer", "minimum": 0}),
        }
    ),
}


def schemas():
    return {**IDENTITY_SCHEMAS, **COMPARISON_SCHEMAS, **METRIC_SCHEMAS, **SCHEMAS}


def valid(name, value):
    return Draft202012Validator(
        {"components": {"schemas": schemas()}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    if not valid(name, value):
        raise DomainError(
            "PACKAGE_RETROSPECTIVE_INVALID", "请核对实交、结果、核查选择及待补资料说明", 422
        )
    return value


def extend_openapi(document):
    operations = {
        (BASE + "/choices", "get"): (None, "PackageRetrospectiveChoices", 200),
        (BASE + "/preview", "post"): (
            "PackageRetrospectiveSelection",
            "PackageRetrospectivePreview",
            200,
        ),
        (BASE, "post"): ("PackageRetrospectiveRequest", "PackageRetrospectiveApplied", 201),
        (BASE, "get"): (None, "PackageRetrospectivePage", 200),
        (BASE + "/{retrospective_id}", "get"): (None, "PackageRetrospectiveDetail", 200),
        (BASE + "/{retrospective_id}/knowledge-candidate", "post"): (
            "PackageRetrospectiveKnowledgeRequest",
            "PackageRetrospectiveKnowledgeApplied",
            201,
        ),
    }
    roots = []
    for (path, method), (request, response, status) in operations.items():
        if method not in document["paths"].get(path, {}):
            continue
        operation = document["paths"][path][method]
        operation["security"] = [{"SessionCookie": []}]
        if request:
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": ref(request)}},
            }
            roots.append(request)
        operation["responses"][str(status)] = {
            "description": "明确选择的完整包待核复盘；不授予发布或研究资格",
            "content": {"application/json": {"schema": ref(response)}},
        }
        roots.append(response)
    available = schemas()
    document["components"]["schemas"].update(deepcopy(schema_closure(available, roots)))
