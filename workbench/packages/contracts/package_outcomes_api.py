"""Official result association with an exact complete-package submission fact.

The native outcome and decision chains are shared with single-body results.  These
schemas describe a different subject; they grant no formal research admission.
"""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.contracts.package_submissions_api import schemas as submission_schemas
from packages.domain.runtime import DomainError

SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
NULL = {"type": "null"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 4000, "pattern": r"\S"}
STATES = ["pending", "verified", "conflict", "rejected"]
SAMPLE_REASON = "package_formal_sample_not_supported"


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def optional(value):
    return {"anyOf": [value, NULL]}


IDENTITY = object_schema(
    {
        "project_id": UUID,
        "lot_id": optional(UUID),
        "round_id": UUID,
        "bidder_id": UUID,
        "package_id": UUID,
        "revision_id": UUID,
        "package_digest": SHA,
        "binding_digest": SHA,
        "identity_digest": SHA,
    }
)
AUTHORITY = object_schema(
    {"package_id": UUID, "revision_id": UUID, "digest": SHA, "identity_digest": SHA}
)
EVIDENCE_REF = object_schema(
    {
        "document_version_id": UUID,
        "evidence_id": UUID,
        "physical_page": {"type": "integer", "minimum": 1, "maximum": 2147483647},
        "quote": TEXT,
    }
)
REQUEST = object_schema(
    {
        "version": {"const": "package-outcome-verification/1"},
        "subject_kind": {"const": "bid_package"},
        "state": {"enum": STATES},
        "reason": TEXT,
        "identity": IDENTITY,
        "authority": optional(AUTHORITY),
        "aggregation": {"type": "string", "maxLength": 200},
        "published_at": optional(TIME),
        "evidence_refs": {
            "type": "array",
            "items": EVIDENCE_REF,
            "uniqueItems": True,
            "maxItems": 100,
        },
    }
)
SAMPLE_BLOCKERS = {
    "type": "array",
    "items": {"const": SAMPLE_REASON},
    "minItems": 1,
    "maxItems": 1,
}
SOURCE_PROOF = object_schema({"digest": SHA, "snapshot": {"type": "object"}})
DETAILS = object_schema(
    {
        "version": {"const": "package-outcome-verification-record/1"},
        "subject_kind": {"const": "bid_package"},
        "request": REQUEST,
        "package_identity": ref("HistoricalBidIdentitySnapshot"),
        "binding_digest": SHA,
        "checked_at": TIME,
        "authority_proof": optional(SOURCE_PROOF),
        "official_source_proof": optional(SOURCE_PROOF),
        "verification_scope": {"const": "official_outcome_association"},
        "formal_sample_eligible": {"const": False},
        "formal_sample_blockers": SAMPLE_BLOCKERS,
    }
)
CONTEXT = object_schema(
    {
        "subject_kind": {"const": "bid_package"},
        "bid_id": UUID,
        "submission_id": UUID,
        "body_version_id": NULL,
        "identity": IDENTITY,
        "package_identity": ref("HistoricalBidIdentitySnapshot"),
        "recorded_identity": ref("BidIdentitySnapshot"),
        "package_binding": ref("PackageSubmissionBindingView"),
        "authority": optional(AUTHORITY),
        "display": object_schema(
            {
                "project_title": {"type": "string"},
                "lot": optional({"type": "string"}),
                "round_no": {"type": "integer", "minimum": 1},
                "bidder_name": {"type": "string"},
                "body_filename": NULL,
            }
        ),
        "submitted_at": TIME,
        "kind": {"enum": ["standard", "offline_fact"]},
        "source_candidates": {
            "type": "array",
            "maxItems": 100,
            "items": object_schema(
                {"id": UUID, "original_name": {"type": "string"}, "obtained_at": TIME}
            ),
        },
        "identity_ready": {"type": "boolean"},
        "identity_status": {"enum": ["confirmed", "unavailable", "changed"]},
        "identity_reason": optional({"type": "string"}),
        "verification_blockers": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "verification_requires_source_evidence": {"const": True},
        "formal_sample_eligible": {"const": False},
        "formal_sample_blockers": SAMPLE_BLOCKERS,
    }
)

SCHEMAS = {
    "PackageOutcomeIdentity": IDENTITY,
    "PackageOutcomeAuthority": AUTHORITY,
    "PackageOutcomeEvidenceRef": EVIDENCE_REF,
    "PackageOutcomeVerificationRequest": REQUEST,
    "PackageOutcomeVerificationDetails": DETAILS,
    "PackageOutcomeContext": CONTEXT,
}


def schemas():
    return {**submission_schemas(), **SCHEMAS}


def valid(name, value):
    return Draft202012Validator(
        {"$ref": "#/components/schemas/" + name, "components": {"schemas": schemas()}},
        format_checker=FormatChecker(),
    ).is_valid(value)


def validate(name, value):
    if not valid(name, value):
        raise DomainError("PACKAGE_OUTCOME_INVALID", "整包成绩核验字段不符合精确提交协议", 422)


def extend_openapi(actual):
    """Register components; the shared research adapter owns its route unions."""
    actual["components"]["schemas"].update(deepcopy(schemas()))
