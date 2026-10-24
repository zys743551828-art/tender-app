"""Complete native material /3 references; never database or model authority."""

from copy import deepcopy

from packages.contracts.package_technical_features import ID, SHA, obj

NONZERO_SHA = {"type": "string", "pattern": "^(?!0{64}$)[0-9a-f]{64}$"}
BINDING = obj(
    {
        "version": {"const": "package-technical-verification-binding/3"},
        "verification_id": ID,
        "verification_receipt_digest": NONZERO_SHA,
        "context_digest": SHA,
        "context_method_digest": SHA,
    }
)
CONTEXT_HEADER = obj(
    {
        "version": {"const": "package-technical-material-context/3"},
        "source_observation_digest": SHA,
        "source_material_digest": SHA,
        "context_method_digest": SHA,
        "provider_profile_digest": NONZERO_SHA,
        "judgment_method_digest": NONZERO_SHA,
        "input_as_of": {"type": "string", "format": "date-time", "maxLength": 40},
        "bid_id": ID,
        "scope_id": ID,
        "scope_digest": SHA,
    }
)
REQUEST_RECEIPT = obj(
    {
        "version": {"const": "package-technical-complete-vision-request/3"},
        **{
            key: SHA
            for key in (
                "input_digest",
                "context_digest",
                "serializer_digest",
                "profile_digest",
                "judgment_method_digest",
                "semantic_input_digest",
                "request_digest",
            )
        },
        "rule_id": ID,
        "body_byte_count": {"type": "integer", "minimum": 1, "maximum": 48 * 1024 * 1024},
        "image_count": {"type": "integer", "minimum": 1, "maximum": 384},
        "complete_native_material_serialized": {"type": "boolean", "const": True},
        **{
            key: {"type": "boolean", "const": False}
            for key in (
                "native_binding_verified",
                "model_token_limit_verified",
                "visual_readability_verified",
                "execution_authorized",
            )
        },
    }
)


def binding_schema():
    return deepcopy(BINDING)
