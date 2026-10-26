"""Independent native package history requests and actual HTTP response schemas."""

from copy import deepcopy
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from packages.contracts.bid_package_api import UUID as UUID_SCHEMA
from packages.contracts.bid_package_api import object_schema
from packages.contracts.package_technical_scope_api import SHA


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", check_fields=False)
    @classmethod
    def reason_nonblank(cls, value):
        if not value.strip():
            raise ValueError("请说明本次历史研究操作的具体原因")
        return value


class PackageHistoryAdmissionRequest(StrictBody):
    submission_id: UUID
    outcome_id: UUID
    proof_id: UUID
    context_digest: str = Field(pattern="^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)


class PackageHistoryProtocolRequest(StrictBody):
    method_digest: str = Field(pattern="^[a-f0-9]{64}$")
    seed: StrictInt = Field(ge=0, le=2147483647)
    bootstrap_iterations: StrictInt = Field(ge=100, le=10000)
    reason: str = Field(min_length=1, max_length=4000)


class PackageHistorySelection(StrictBody):
    admission_id: UUID
    purpose: Literal["fit", "development", "calibration", "final"]


class PackageHistoryCohortRequest(StrictBody):
    protocol_id: UUID
    submission_split_at: datetime
    label_available_as_of: datetime
    selections: list[PackageHistorySelection] = Field(min_length=4, max_length=1000)
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("submission_split_at", "label_available_as_of")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("回溯边界必须带时区")
        return value


class PackageHistoryJobRequest(StrictBody):
    kind: Literal["train", "evaluate"]
    reason: str = Field(min_length=1, max_length=4000)


class PackageHistoryJobControl(StrictBody):
    action: Literal["pause", "resume", "cancel"]
    generation: StrictInt = Field(ge=1)
    reason: str = Field(min_length=1, max_length=4000)


DATE = {"type": "string", "format": "date-time"}
TEXT = {"type": "string"}
NULL = {"type": "null"}
BOOL = {"type": "boolean"}
NUMBER = {"type": "string", "pattern": r"^(0|[1-9][0-9]*)(\.[0-9]+)?$"}
ORIGIN = {"enum": ["synthetic", "external_evidence"]}
FLAGS = {"research_only": {"const": True}, "formal_eligibility": {"const": "unavailable"}}
NO_FORMAL = {
    "strict_prebid_eligible": {"const": False},
    "online_metrics_eligible": {"const": False},
    "formal_sample_created": {"const": False},
}


def optional(value):
    return {"anyOf": [value, NULL]}


def array(value, **bounds):
    return {"type": "array", "items": value, **bounds}


ADMISSION = object_schema(
    {
        "schema": {"const": "package-historical-research-admission/1"},
        **dict.fromkeys(
            ["id", "proof_id", "bid_id", "scope_id", "submission_id", "outcome_id"], UUID_SCHEMA
        ),
        **dict.fromkeys(
            [
                "scope_digest",
                "submission_binding_digest",
                "context_digest",
                "proof_digest",
                "digest",
            ],
            SHA,
        ),
        "origin": ORIGIN,
        "state": {"enum": ["mechanism_candidate", "retrospective_candidate"]},
        **dict.fromkeys(
            [
                "historical_as_of",
                "scope_frozen_at",
                "label_known_at",
                "evidence_verified_at",
                "admitted_at",
            ],
            DATE,
        ),
        "official_technical_value": NUMBER,
        "technical_maximum": NUMBER,
        "aggregation": {"const": "published_final_technical_total"},
        "training_selected": {"const": False},
        **FLAGS,
        **NO_FORMAL,
    }
)
PROOF = object_schema(
    {
        "id": UUID_SCHEMA,
        "origin": ORIGIN,
        "adapter_id": UUID_SCHEMA,
        "verified_at": DATE,
        "context_digest": SHA,
    }
)
CONTEXT = object_schema(
    {
        "schema": {"const": "package-historical-admission-context/1"},
        "schema_configured": BOOL,
        **dict.fromkeys(["scope_id", "submission_id", "outcome_id"], UUID_SCHEMA),
        "context_digest": optional(SHA),
        "official_technical_value": optional(NUMBER),
        "official_maximum": optional(NUMBER),
        **dict.fromkeys(["historical_as_of", "scope_frozen_at", "label_known_at"], optional(DATE)),
        "proofs": array(PROOF),
        "blockers": array(object_schema({"code": TEXT, "message": TEXT})),
        "observed_at": DATE,
        **FLAGS,
        **NO_FORMAL,
    }
)
TIMING = object_schema(
    {
        "mode": {"const": "retrospective_submission_time_holdout"},
        "historical_as_of": {"const": "per_exact_actual_submission"},
        **dict.fromkeys(
            ["submission_split_at", "label_available_as_of", "training_frozen_at"], DATE
        ),
        "group_spanning_policy": {"const": "exclude"},
        "prediction_timing": {"const": "retrospective"},
    }
)
MEMBER = object_schema(
    {
        **dict.fromkeys(["admission_id", "proof_id", "submission_id", "group_id"], UUID_SCHEMA),
        "closure_ids": array(UUID_SCHEMA, minItems=1),
        "requested_purpose": {"enum": ["fit", "development", "calibration", "final"]},
        "purpose": {"enum": ["fit", "development", "calibration", "final", "excluded"]},
        "exclusion_reason": optional(
            {"enum": ["group_spans_submission_split", "label_after_available_cutoff"]}
        ),
        "submitted_at": DATE,
        "label_known_at": DATE,
    }
)
COHORT = object_schema(
    {
        "schema": {"const": "package-history-cohort/1"},
        "id": UUID_SCHEMA,
        "protocol_id": UUID_SCHEMA,
        "protocol_digest": SHA,
        "origin": ORIGIN,
        "timing": TIMING,
        "members": array(MEMBER, minItems=4, maxItems=1000),
        "membership_digest": SHA,
        "digest": SHA,
        **FLAGS,
        **NO_FORMAL,
    }
)
JOB = object_schema(
    {
        "job_id": UUID_SCHEMA,
        "cohort_id": UUID_SCHEMA,
        "kind": {"enum": ["train", "evaluate"]},
        "state": {"enum": ["queued", "running", "paused", "succeeded", "failed", "cancelled"]},
        "generation": {"type": "integer", "minimum": 1},
        **FLAGS,
    }
)
COUNT = {"type": "integer", "minimum": 0}
SIGNED_NUMBER = {"type": "string", "pattern": r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"}
METHOD = object_schema(
    {
        "version": {"const": "package-history-project-baselines/1"},
        "purpose": {"const": "retrospective_research"},
        "features": {"const": "not_required_by_constant_baselines"},
        "provider_requests": {"const": 0},
        "digest": SHA,
        "sources": object_schema(
            dict.fromkeys(
                [
                    "packages/model_governance/package_history_cpu.py",
                    "packages/model_governance/common.py",
                    "packages/model_governance/evaluation.py",
                    "packages/model_governance/statistics.py",
                ],
                SHA,
            )
        ),
    }
)
PROTOCOL = object_schema(
    {
        "schema": {"const": "package-history-cpu-protocol/1"},
        "method": METHOD,
        "families": {"const": ["mean", "median"]},
        "selection_metric": {"const": "project_mae"},
        "tie_order": {"const": ["mean", "median"]},
        "refit_with_development": {"const": False},
        "interval_levels": {"const": [0.8, 0.9]},
        "group_spanning_policy": {"const": "exclude"},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
        "bootstrap_iterations": {"type": "integer", "minimum": 100, "maximum": 10000},
    }
)
CONSTANTS = object_schema({"mean": NUMBER, "median": NUMBER})
MODEL = object_schema(
    {
        "schema": {"const": "package-history-constant-model/1"},
        "method_digest": SHA,
        "family": {"enum": ["mean", "median"]},
        "constant": NUMBER,
        "training_export_digest": SHA,
    }
)
INTERVAL = object_schema(
    {
        "radius": optional(NUMBER),
        "groups": COUNT,
        "rank": COUNT,
        "unavailable_reason": optional({"const": "insufficient_independent_calibration_groups"}),
    }
)
TRAINING_RESULT = object_schema(
    {
        "schema": {"const": "package-history-training-result/1"},
        "origin": ORIGIN,
        "cohort_id": UUID_SCHEMA,
        **dict.fromkeys(
            ["protocol_digest", "training_export_digest", "membership_digest", "model_digest"], SHA
        ),
        "model": MODEL,
        "baselines": CONSTANTS,
        "selection": object_schema(
            {
                "development_project_mae": CONSTANTS,
                "selected": {"enum": ["mean", "median"]},
                "refit_with_development": {"const": False},
            }
        ),
        "intervals": object_schema({"0.8": INTERVAL, "0.9": INTERVAL}),
        **FLAGS,
        "provider_requests": {"const": 0},
        "paid_calls": {"const": 0},
    }
)
COMPLETE_MATERIAL_CONSUMER = object_schema(
    {
        "version": {"const": "package-history-complete-consumer/1"},
        **dict.fromkeys(["method_digest", "reference_digest", "bindings_digest"], SHA),
        "receipts": array(
            object_schema(
                {
                    "admission_id": UUID_SCHEMA,
                    "proof_id": UUID_SCHEMA,
                    **dict.fromkeys(
                        [
                            "context_digest",
                            "source_commit",
                            "artifact_digest",
                            "input_digest",
                            "features_digest",
                        ],
                        SHA,
                    ),
                }
            ),
            minItems=1,
            maxItems=64,
        ),
        "features_used_for_fit": {"const": False},
        "formal_prediction": NULL,
        **dict.fromkeys(
            [
                "native_binding_verified",
                "current_native_facts_rechecked",
                "input_authority_granted",
                "execution_authorized",
                "training_eligible",
                "metrics_eligible",
                "formal_prediction_eligible",
            ],
            {"const": False},
        ),
    }
)
# Optional versioned receipt; old constant-baseline responses remain unchanged.
# Closed keys and unavailable eligibility are preserved for the new receipt too.
TRAINING_RESULT["properties"]["complete_material_consumer"] = COMPLETE_MATERIAL_CONSUMER

FEATURE_NAMES = [
    "declared_band_fraction",
    "modal_agreement",
    "specificity_supported",
    "validity_supported",
    "consistency_supported",
    "uncertain_fraction",
]
FEATURE_RIDGE_MODEL = object_schema(
    {
        "version": {"const": "package-complete-ridge-model/1"},
        "feature_schema": {"const": "package-complete-numeric-features/1"},
        "method_digest": SHA,
        "alpha": {"enum": ["10", "1", "0.1"]},
        "means": array(NUMBER, minItems=6, maxItems=6),
        "scales": array(NUMBER, minItems=6, maxItems=6),
        "coefficients": array(SIGNED_NUMBER, minItems=6, maxItems=6),
        "intercept": NUMBER,
        "training_digest": SHA,
    }
)
FEATURE_TRAINING_COMMON = {
    "version": {"const": "package-complete-feature-training/1"},
    "feature_schema": {"const": "package-complete-numeric-features/1"},
    "feature_names": {"const": FEATURE_NAMES},
    "origin": ORIGIN,
    **dict.fromkeys(
        ["method_digest", "membership_digest", "projection_digest", "source_digest"], SHA
    ),
    "groups": object_schema(dict.fromkeys(["fit", "development", "calibration"], COUNT)),
    "formal_prediction": NULL,
    "final_test_consumption": {"const": "not_implemented"},
    **dict.fromkeys(
        [
            "native_binding_verified",
            "current_native_facts_rechecked",
            "input_authority_granted",
            "execution_authorized",
            "training_eligible",
            "metrics_eligible",
            "formal_prediction_eligible",
        ],
        {"const": False},
    ),
}
FEATURE_TRAINING_RESULT = {
    "oneOf": [
        object_schema(
            FEATURE_TRAINING_COMMON
            | {
                "status": {"const": "research_candidate"},
                "unavailable_reasons": array({"type": "string"}, maxItems=0),
                "model": FEATURE_RIDGE_MODEL,
                "model_digest": SHA,
                "features_used_for_fit": {"const": True},
                "selection": object_schema(
                    {
                        "selected_alpha": {"enum": ["10", "1", "0.1"]},
                        "development_project_mae": object_schema(
                            dict.fromkeys(["10", "1", "0.1"], NUMBER)
                        ),
                        "refit_with_development": {"const": False},
                    }
                ),
                "intervals": object_schema(
                    {
                        level: object_schema({"radius": NUMBER, "groups": COUNT, "rank": COUNT})
                        for level in ("0.8", "0.9")
                    }
                ),
            }
        ),
        object_schema(
            FEATURE_TRAINING_COMMON
            | {
                "status": {"const": "unavailable"},
                "unavailable_reasons": array(
                    {
                        "enum": [
                            "declared_numeric_band_scale_required",
                            "distinct_declared_numeric_bands_required",
                            "included_rules_required",
                            "insufficient_fit_groups",
                            "insufficient_development_groups",
                            "insufficient_calibration_groups",
                            "fit_features_have_no_variation",
                        ]
                    },
                    minItems=1,
                ),
                "model": NULL,
                "model_digest": NULL,
                "selection": NULL,
                "intervals": NULL,
                "features_used_for_fit": {"const": False},
            }
        ),
    ]
}
TRAINING_RESULT["properties"]["complete_feature_training"] = FEATURE_TRAINING_RESULT

INTERVAL_REPORT = {
    "oneOf": [
        object_schema({"coverage": NUMBER, "width": NUMBER}),
        object_schema(
            {
                "coverage": NULL,
                "width": NULL,
                "reason": {"const": "interval_or_labeled_predictions_unavailable"},
            }
        ),
    ]
}
BASELINE_REPORT = {
    "oneOf": [
        object_schema(
            {
                "gain": SIGNED_NUMBER,
                "paired_count": COUNT,
                "group_bootstrap_gain_95": optional(array(SIGNED_NUMBER, minItems=2, maxItems=2)),
            }
        ),
        object_schema({"gain": NULL, "reason": {"const": "paired_baseline_missing"}}),
    ]
}
STRATUM = {
    "type": "object",
    "additionalProperties": object_schema({"count": COUNT, "project_mae": optional(NUMBER)}),
}
REPORT = object_schema(
    {
        **dict.fromkeys(["denominator", "independent_groups", "projects"], COUNT),
        "counts": object_schema(
            dict.fromkeys(["succeeded", "failed", "rejected", "unlabeled"], COUNT)
        ),
        **dict.fromkeys(
            [
                "success_coverage",
                "sample_mae",
                "project_mae",
                "original_scale_project_mae",
                "p90_absolute_error",
                "project_within_three",
            ],
            optional(NUMBER),
        ),
        "project_bias": optional(SIGNED_NUMBER),
        "intervals": object_schema({"0.8": INTERVAL_REPORT, "0.9": INTERVAL_REPORT}),
        "paired_baselines": object_schema(
            {"mean": BASELINE_REPORT, "median": BASELINE_REPORT}, required=[]
        ),
        "group_bootstrap_project_mae_95": optional(array(NUMBER, minItems=2, maxItems=2)),
        "stability_range_p90": NULL,
        "strata": object_schema(dict.fromkeys(["method", "maximum", "engineering_type"], STRATUM)),
        "unavailable_statistics": {
            "const": [
                "ranking_without_ranking_labels",
                "shortlist_probability_without_labels",
                "judge_disagreement_without_judge_labels",
                "whole_round_stability_without_independent_repeat_predictions",
            ]
        },
    }
)
EVALUATION_RESULT = object_schema(
    {
        "schema": {"const": "package-history-independent-evaluation/1"},
        "origin": ORIGIN,
        "cohort_id": UUID_SCHEMA,
        **dict.fromkeys(
            [
                "protocol_digest",
                "model_digest",
                "membership_digest",
                "predictions_digest",
                "labels_digest",
            ],
            SHA,
        ),
        "timing": TIMING,
        "selection_denominator": object_schema(
            dict.fromkeys(
                ["selected_submissions", "excluded_submissions", "final_side_candidates"], COUNT
            )
        ),
        "report": REPORT,
        "official_source_subset": object_schema(
            {
                "scope": {"const": "verified_official_associations_with_evidence_backed_admission"},
                "origin": ORIGIN,
                "report": REPORT,
            }
        ),
        **FLAGS,
        "acceptance_decision": {"const": "unavailable"},
        "missing_acceptance": {
            "const": [
                "real_independent_quality_validation",
                "complete_package_three_judgment_features",
                "preexposure_business_certification",
                "independent_repeat_stability",
                "observation_and_release_authority",
            ]
        },
        "provider_requests": {"const": 0},
        "paid_calls": {"const": 0},
    }
)
SCHEMAS = {
    "PackageHistoricalAdmissionContext": CONTEXT,
    "PackageHistoricalAdmission": ADMISSION,
    "PackageHistoricalAdmissionView": object_schema({"admission": ADMISSION, "current": BOOL}),
    "PackageHistoricalProtocol": object_schema(
        {"id": UUID_SCHEMA, "document": PROTOCOL, "digest": SHA, **FLAGS}
    ),
    "PackageHistoricalProtocolTemplate": object_schema(
        {
            "schema_configured": BOOL,
            "document": PROTOCOL,
            "method_digest": SHA,
            "signed_proof_public_upload": {"const": False},
            "feature_calibration_available": {"const": False},
            **FLAGS,
        }
    ),
    "PackageHistoricalCohort": COHORT,
    "PackageHistoricalCohortView": object_schema({"cohort": COHORT, "current": BOOL}),
    "PackageHistoricalJob": JOB,
    "PackageHistoricalJobView": object_schema(
        JOB["properties"]
        | {
            "current": BOOL,
            "result": optional({"oneOf": [TRAINING_RESULT, EVALUATION_RESULT]}),
            "result_digest": optional(SHA),
        }
    ),
}


def extend_openapi(actual):
    models = (
        PackageHistoryAdmissionRequest,
        PackageHistoryProtocolRequest,
        PackageHistoryCohortRequest,
        PackageHistoryJobRequest,
        PackageHistoryJobControl,
    )
    components = actual.setdefault("components", {}).setdefault("schemas", {})
    components.update(deepcopy(SCHEMAS))
    for model in models:
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        components.update(schema.pop("$defs", {}))
        components[model.__name__] = schema
    scope = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}"
    base = "/api/v1/package-historical-research"
    bindings = [
        (scope + "/historical-admission-context", "get", "PackageHistoricalAdmissionContext", 200),
        (scope + "/historical-admissions", "post", "PackageHistoricalAdmission", 201),
        (base + "/admissions/{admission_id}", "get", "PackageHistoricalAdmissionView", 200),
        (base + "/cpu-protocol-template", "get", "PackageHistoricalProtocolTemplate", 200),
        (base + "/protocols", "post", "PackageHistoricalProtocol", 201),
        (base + "/cohorts", "post", "PackageHistoricalCohort", 201),
        (base + "/cohorts/{cohort_id}", "get", "PackageHistoricalCohortView", 200),
        (base + "/cohorts/{cohort_id}/jobs", "post", "PackageHistoricalJob", 201),
        (base + "/jobs/{job_id}", "get", "PackageHistoricalJobView", 200),
        (base + "/jobs/{job_id}/control", "post", "PackageHistoricalJob", 200),
    ]
    for path, verb, schema_name, status in bindings:
        operation = actual.get("paths", {}).get(path, {}).get(verb)
        if operation is None:
            continue
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {
            "default": {"$ref": "#/components/responses/DomainError"},
            str(status): {
                "description": "Independent retrospective research only; no formal/online/model qualification.",
                "headers": {"ETag": {"schema": TEXT}},
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + schema_name}}
                },
            },
        }
    return actual
