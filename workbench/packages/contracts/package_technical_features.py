"""Closed CPU feature projection; this packet grants no input or provider authority."""

from copy import deepcopy


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def array(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


ID = {"type": "string", "format": "uuid", "pattern": "^[0-9a-f-]{36}$"}
SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
KEY = {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r"\S"}
OPAQUE = {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r"^[!-~]+$"}
PARTS = {**array(KEY, 2000, 1), "uniqueItems": True}
DIMENSIONS = ("specificity", "validity", "consistency")
DIAGNOSTICS = ("supported", "unsupported", "uncertain")
BINDING = obj(
    {
        "scope_id": ID,
        "scope_digest": SHA,
        "input_digest": SHA,
        "identity_digest": SHA,
        "rule_set_digest": SHA,
        "judgment_method_digest": SHA,
        "provider_profile_digest": SHA,
        "input_verification_digest": SHA,
        "frozen_documents_digest": SHA,
        "input_as_of": {"type": "string", "format": "date-time", "maxLength": 40},
    }
)
REGION = {
    "type": ["array", "null"],
    "items": {"type": "integer", "minimum": 0, "maximum": 100000},
    "minItems": 4,
    "maxItems": 4,
}
CITATION = obj(
    {
        "evidence_id": ID,
        "document_version_id": ID,
        "parse_run_id": ID,
        "physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
        "page_image_digest": SHA,
        "quote": {"type": "string", "maxLength": 16000},
        "region": REGION,
    }
)
JUDGMENT = obj(
    {
        "status": {"enum": ["valid", "invalid", "unable_to_judge"]},
        "coverage": {"enum": ["complete", "partial", "failed"]},
        "band_id": {"anyOf": [KEY, {"type": "null"}]},
        "reason": {"type": "string", "minLength": 1, "maxLength": 12000},
        "covered_part_ids": {**array(KEY, 2000), "uniqueItems": True},
        "dimensions": obj({key: {"enum": list(DIAGNOSTICS)} for key in DIMENSIONS}),
        "evidence": array(CITATION, 2000),
    }
)
EVIDENCE = obj(
    {
        "evidence_id": ID,
        "document_version_id": ID,
        "parse_run_id": ID,
        "physical_page": {"type": "integer", "minimum": 1, "maximum": 100000},
        "part_ids": PARTS,
        "text": {"type": "string", "maxLength": 16000},
        "text_digest": SHA,
        "page_image_digest": SHA,
        "page_width": {"type": "integer", "minimum": 1, "maximum": 100000},
        "page_height": {"type": "integer", "minimum": 1, "maximum": 100000},
    }
)
RULE = obj(
    {
        "rule_id": ID,
        "rule_digest": SHA,
        "semantic_input_digest": SHA,
        "request_digest": SHA,
        "required_part_ids": PARTS,
        "band_ids": {**array(KEY, 100), "uniqueItems": True},
    }
)
ATTEMPT = obj(
    {
        "rule_id": ID,
        "slot": {"type": "integer", "minimum": 1, "maximum": 3},
        "attempt": {"type": "integer", "minimum": 1, "maximum": 5},
        "call_id": ID,
        "semantic_input_digest": SHA,
        "request_digest": SHA,
        "judgment_method_digest": SHA,
        "provider_profile_digest": SHA,
        "state": {"enum": ["succeeded", "failed", "unknown"]},
        "response_model": {"anyOf": [OPAQUE, {"type": "null"}]},
        "response_id": {"anyOf": [OPAQUE, {"type": "null"}]},
        "response_digest": {"anyOf": [SHA, {"type": "null"}]},
        "judgment_digest": {"anyOf": [SHA, {"type": "null"}]},
        "judgment": {"anyOf": [JUDGMENT, {"type": "null"}]},
    }
)
SCHEMA = obj(
    {
        "version": {"const": "package-technical-feature-projection/2"},
        "binding": BINDING,
        "provider": obj({"provider_id": OPAQUE, "model_alias": OPAQUE, "response_model": OPAQUE}),
        "max_attempts_per_slot": {"type": "integer", "minimum": 1, "maximum": 5},
        "rules": array(RULE, 400, 1),
        "evidence_catalog": array(EVIDENCE, 20000, 1),
        "attempts": array(ATTEMPT, 6000),
    }
)

COUNT3 = {"type": "integer", "minimum": 0, "maximum": 3}
SLOTS = {**array({"type": "integer", "minimum": 1, "maximum": 3}, 3), "uniqueItems": True}
FEATURES = obj(
    {
        "band_votes": array(obj({"band_id": KEY, "count": COUNT3}), 100),
        "modal_band_ids": {**array(KEY, 100), "uniqueItems": True},
        "band_disagreement": {"type": "boolean"},
        "dimension_votes": obj(
            {dimension: obj({state: COUNT3 for state in DIAGNOSTICS}) for dimension in DIMENSIONS}
        ),
    }
)
OUTPUT_SCHEMA = obj(
    {
        "version": {"const": "package-technical-features/2"},
        "binding": BINDING,
        "provider": SCHEMA["properties"]["provider"],
        "source_projection_digest": SHA,
        "feature_method_digest": SHA,
        "feature_coverage": {"enum": ["complete", "partial"]},
        "expected_rule_count": {"type": "integer", "minimum": 1, "maximum": 400},
        "complete_rule_count": {"type": "integer", "minimum": 0, "maximum": 400},
        "items": array(
            obj(
                {
                    "rule_id": ID,
                    "rule_digest": SHA,
                    "attempt_count": {"type": "integer", "minimum": 0, "maximum": 15},
                    "valid_slot_count": COUNT3,
                    "valid_slots": SLOTS,
                    "missing_valid_slots": SLOTS,
                    "unresolved_slots": SLOTS,
                    "call_ids": {**array(ID, 3), "uniqueItems": True},
                    "response_ids": {**array(OPAQUE, 3), "uniqueItems": True},
                    "cited_evidence_ids": {**array(ID, 6000), "uniqueItems": True},
                    "features": {"anyOf": [FEATURES, {"type": "null"}]},
                }
            ),
            400,
            1,
        ),
        "raw_numeric_total": {"type": "null"},
        "formal_prediction": {"type": "null"},
        **{
            key: {"const": False}
            for key in (
                "input_authority_granted",
                "original_bytes_reverified",
                "visual_readability_verified",
                "formal_prediction_eligible",
                "training_eligible",
                "metrics_eligible",
            )
        },
        "limitations": {**array(KEY, 8, 1), "uniqueItems": True},
        "digest": SHA,
    }
)


def schema():
    return deepcopy(SCHEMA)


def output_schema():
    return deepcopy(OUTPUT_SCHEMA)
