"""Owned complete-material input projection; no source or execution authority."""

from copy import deepcopy

from packages.contracts import package_technical_assets as assets
from packages.contracts.package_technical_features import (
    BINDING,
    EVIDENCE,
    ID,
    KEY,
    PARTS,
    SHA,
    array,
    obj,
)

DOCUMENT = obj(
    {
        "document_version_id": ID,
        "package_role": {"enum": ["authority", "target"]},
        "source_digest": SHA,
        "source_byte_size": {"type": "integer", "minimum": 1, "maximum": 32 * 1024 * 1024},
        "parse_run_id": ID,
        "parse_digest": SHA,
        "page_count": {"type": "integer", "minimum": 1, "maximum": 128},
        "asset_manifest_digest": SHA,
    }
)
PART = obj(
    {
        "part_id": KEY,
        "document_version_id": ID,
        "parent_part_id": {"anyOf": [KEY, {"type": "null"}]},
        "related_part_ids": {**array(KEY, 2000), "uniqueItems": True},
        "physical_pages": {
            **array({"type": "integer", "minimum": 1, "maximum": 128}, 128, 1),
            "uniqueItems": True,
        },
    }
)
RULE = obj(
    {
        "rule_id": ID,
        "rule_digest": SHA,
        "source_evidence_id": ID,
        "source_quote": {"type": "string", "minLength": 1, "maxLength": 16000},
        "source_quote_digest": SHA,
        "required_part_ids": PARTS,
        "band_ids": {**array(KEY, 100), "uniqueItems": True},
    }
)
SCHEMA = obj(
    {
        "version": {"const": "package-technical-input-projection/2"},
        "binding": BINDING,
        "documents": array(DOCUMENT, 32, 1),
        "parts": array(PART, 2000, 1),
        "rules": array(RULE, 400, 1),
        "evidence_catalog": array(EVIDENCE, 20000, 1),
    }
)

MATERIAL = obj(
    {
        "binding": BINDING,
        "documents": SCHEMA["properties"]["documents"],
        "parts": SCHEMA["properties"]["parts"],
        "pages": array(
            obj(
                {
                    "document_version_id": ID,
                    "parse_run_id": ID,
                    **assets.SCHEMA["properties"]["pages"]["items"]["properties"],
                }
            ),
            256,
            1,
        ),
        "details": array(
            obj(
                {
                    "document_version_id": ID,
                    **assets.SCHEMA["properties"]["details"]["items"]["properties"],
                }
            ),
            384,
        ),
        "evidence_catalog": SCHEMA["properties"]["evidence_catalog"],
    }
)
OUTPUT_SCHEMA = obj(
    {
        "version": {"const": "package-technical-input/2"},
        "source_projection_digest": SHA,
        "input_method_digest": SHA,
        "material": MATERIAL,
        "material_digest": SHA,
        "rule_packets": array(
            obj(
                {
                    "rule": RULE,
                    "required_part_ids": PARTS,
                    "semantic_input_digest": SHA,
                }
            ),
            400,
            1,
        ),
        "physical_page_count": {"type": "integer", "minimum": 1, "maximum": 256},
        "image_count": {"type": "integer", "minimum": 1, "maximum": 384},
        "asset_byte_count": {"type": "integer", "minimum": 1, "maximum": 64 * 1024 * 1024},
        "pixel_count": {"type": "integer", "minimum": 1, "maximum": 128_000_000},
        "text_byte_count": {"type": "integer", "minimum": 0, "maximum": 2 * 1024 * 1024},
        "all_projected_material_retained": {"const": True, "type": "boolean"},
        **{
            key: {"const": False, "type": "boolean"}
            for key in (
                "input_authority_granted",
                "original_bytes_reverified",
                "visual_readability_verified",
                "historical_byte_existence_verified",
                "provider_payload_verified",
                "execution_authorized",
                "formal_prediction_eligible",
                "training_eligible",
            )
        },
        "digest": SHA,
    }
)

CONTEXT_BINDING = deepcopy(BINDING)
CONTEXT_BINDING["properties"].pop("input_verification_digest")
CONTEXT_BINDING["required"].remove("input_verification_digest")
CONTEXT_SCHEMA = deepcopy(SCHEMA)
CONTEXT_SCHEMA["properties"]["version"] = {"const": "package-technical-context-projection/2"}
CONTEXT_SCHEMA["properties"]["binding"] = CONTEXT_BINDING
CONTEXT_MATERIAL = deepcopy(MATERIAL)
CONTEXT_MATERIAL["properties"]["binding"] = CONTEXT_BINDING
CONTEXT_OUTPUT_SCHEMA = obj(
    {
        "version": {"const": "package-technical-verification-context/2"},
        "source_projection_digest": SHA,
        "context_method_digest": SHA,
        "material": CONTEXT_MATERIAL,
        "material_digest": SHA,
        "rule_scopes": array(obj({"rule": RULE, "required_part_ids": PARTS}), 400, 1),
        "input_authority_granted": {"const": False, "type": "boolean"},
        "execution_authorized": {"const": False, "type": "boolean"},
        "digest": SHA,
    }
)
VERIFICATION_BINDING_SCHEMA = obj(
    {
        "version": {"const": "package-technical-verification-binding/2"},
        "verification_id": ID,
        "verification_receipt_digest": {"type": "string", "pattern": "^(?!0{64}$)[0-9a-f]{64}$"},
        "context_digest": SHA,
        "context_method_digest": SHA,
    }
)


def schema():
    return deepcopy(SCHEMA)


def output_schema():
    return deepcopy(OUTPUT_SCHEMA)


def context_schema():
    return deepcopy(CONTEXT_SCHEMA)


def context_output_schema():
    return deepcopy(CONTEXT_OUTPUT_SCHEMA)


def verification_binding_schema():
    return deepcopy(VERIFICATION_BINDING_SCHEMA)
