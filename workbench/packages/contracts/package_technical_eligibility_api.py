"""Read-only exact-package score/sample eligibility; no execution or sample grant."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.contracts.package_technical_scope_api import BASIS, COVERAGE, DATE, FLAGS, GAP, SHA
from packages.domain.runtime import DomainError


def nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


def array(value):
    return {"type": "array", "items": value}


BOOL = {"type": "boolean"}
TEXT = {"type": "string"}
DECIMAL = {"type": "string", "pattern": r"^(0|[1-9][0-9]*)(\.[0-9]+)?$"}
REFERENCE = object_schema(
    {
        "bid_id": UUID,
        "package_id": UUID,
        "revision_id": UUID,
        "inventory_id": UUID,
        "scope_id": UUID,
        "scope_digest": SHA,
    }
)
EVIDENCE = object_schema(
    {
        **dict.fromkeys(
            ("id", "document_version_id", "parse_id", "evidence_id", "source_id"), UUID
        ),
        "blob_digest": SHA,
        "evidence_digest": SHA,
        "physical_page": {"type": "integer", "minimum": 1},
        "source_revision": nullable({"type": "integer", "minimum": 0}),
        "quote": TEXT,
        "supported_fields": array(
            {"enum": ["technical_maximum", "scale_description", "aggregation"]}
        ),
    }
)
DENOMINATOR = object_schema(
    {
        "state": {"enum": ["unselected", "not_configured", "unavailable", "mismatched", "matched"]},
        "scale_id": nullable(UUID),
        "scale_digest": nullable(SHA),
        "purpose": {"enum": ["current_prebid", "historical_backtest"]},
        "technical_maximum": nullable(DECIMAL),
        "scale_description": nullable(TEXT),
        "aggregation": nullable(
            object_schema({"status": {"enum": ["unknown", "unsupported"]}, "description": TEXT})
        ),
        "maximum_usable": BOOL,
        "aggregation_usable": {"const": False},
        "evidence_refs": array(EVIDENCE),
        "reasons": array(GAP),
    }
)
JUDGMENTS = object_schema(
    {
        "required_valid_independent": {"const": 3},
        "recorded_valid_independent": {"const": 0},
        "producer_authority": {"const": "not_configured_for_exact_package"},
        "previous_answers_in_input": {"const": False},
        "retries_count_as_independent": {"const": False},
        "unknown_send_auto_retry": {"const": False},
        "execution_enabled": {"const": False},
    }
)
CURRENT = object_schema(
    {
        "state": {"enum": ["matched", "changed", "unavailable"]},
        "stored_context_digest": SHA,
        "current_context_digest": nullable(SHA),
        "method_matches": BOOL,
        "original_bytes_reverified": {"const": False},
        "reasons": array(GAP),
    }
)
COMMON = {
    "scope": REFERENCE,
    "basis": BASIS,
    "observed_at": DATE,
    "coverage": COVERAGE,
    "denominator": DENOMINATOR,
    "judgments": JUDGMENTS,
    "numeric_prediction": {"type": "null"},
    "blockers": array(GAP),
    **FLAGS,
}
SCHEMAS = {
    "PackageTechnicalScoringContext": object_schema(
        COMMON
        | {
            "version": {"const": "package-technical-scoring-context/1"},
            "purpose": {"const": "current_prebid"},
            "current_input": CURRENT,
            "official_label_access": {"const": "forbidden"},
        }
    ),
    "PackageTechnicalSampleContext": object_schema(
        COMMON
        | {
            "version": {"const": "package-technical-sample-context/1"},
            "purpose": {"const": "historical_backtest"},
            "submission": object_schema(
                {
                    "id": UUID,
                    "binding_digest": SHA,
                    "submitted_at": DATE,
                    "recorded_at": DATE,
                    "is_current_head": BOOL,
                    "matches_scope": BOOL,
                    "platform_submission_verified": {"const": False},
                }
            ),
            "official_result": object_schema(
                {
                    "outcome_id": nullable(UUID),
                    "score_kind": nullable(
                        {"enum": ["technical_total", "comprehensive_total", "unknown"]}
                    ),
                    "technical_value": nullable(DECIMAL),
                    "reported_maximum": nullable(DECIMAL),
                    "label_known_at": nullable(DATE),
                    "current_association": BOOL,
                    "reasons": array(GAP),
                }
            ),
            "timing": object_schema(
                {
                    "scope_frozen_at": DATE,
                    "historical_as_of": DATE,
                    "submitted_at": DATE,
                    "label_known_at": nullable(DATE),
                    "training_frozen_at": {"type": "null"},
                    "submission_split_at": {"type": "null"},
                    "label_available_as_of": {"type": "null"},
                    "strict_timing_ready": {"const": False},
                }
            ),
            "original_scope_precedes_submission": BOOL,
            "source_metadata_matches": BOOL,
            "sample_state": {"const": "pending"},
            "sample_created": {"const": False},
            "official_label_access": {"const": "association_check_only"},
        }
    ),
}


def validate(name, value):
    if not Draft202012Validator(SCHEMAS[name], format_checker=FormatChecker()).is_valid(value):
        raise DomainError(
            "PACKAGE_TECHNICAL_ELIGIBILITY_INVALID", "精确技术范围资格响应不符合只读协议", 422
        )
    return value


def extend_openapi(actual):
    base = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}"
    for suffix, operation_id, response in (
        ("/scoring-context", "getPackageTechnicalScoringContext", "PackageTechnicalScoringContext"),
        ("/sample-context", "getPackageTechnicalSampleContext", "PackageTechnicalSampleContext"),
    ):
        operation = actual.get("paths", {}).get(base + suffix, {}).get("get")
        if operation is None:
            continue
        operation["operationId"] = operation_id
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {
            "200": {
                "description": "Read-only exact authority assessment; no model execution, numeric prediction or sample admission.",
                "headers": {"ETag": {"schema": TEXT}},
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + response}}
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
        actual.setdefault("components", {}).setdefault("schemas", {})[response] = deepcopy(
            SCHEMAS[response]
        )
