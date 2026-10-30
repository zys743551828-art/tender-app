"""Versioned PAGE-only producer adapter for the prebuilt provider.

Admission reassembles the exact frozen DOCX; no caller label authorizes fields.
The unchanged legacy PDF checker remains the layout/numbering acceptance rule.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from packages.authoring import generated_docx, generated_renderer, generated_verification
from packages.domain.errors import DomainError
from packages.domain.runtime import sha
from packages.word_intake import prebuilt

PROTOCOL = "authoring-prebuilt-generated/1"


def profile_for(provider_profile: dict) -> dict:
    prebuilt.validate_profile(provider_profile)
    identity = {
        "protocol": PROTOCOL,
        "provider_profile": deepcopy(provider_profile),
        "adapter_digest": sha(Path(__file__).read_bytes()),
        "generator_digest": sha(generated_docx.generator_identity()),
        "validator_digest": sha(Path(generated_verification.__file__).read_bytes()),
        "pdf_inspector_digest": sha(Path(generated_renderer.__file__).read_bytes()),
        "dynamic_field_policy": "one_canonical_footer_PAGE_only",
        "correspondence_policy": "complete_body_plus_per_page_geometric_header_footer_v1",
    }
    return {"identity": identity, "profile_digest": sha(identity)}


def validate_profile(profile: dict) -> None:
    try:
        if profile != profile_for(profile["identity"]["provider_profile"]):
            raise ValueError("profile changed")
    except (KeyError, TypeError, ValueError, prebuilt.PrebuiltError):
        raise DomainError(
            "AUTHORING_PREBUILT_PROFILE_CHANGED", "生成正文预构建转换资格已变化", 409
        ) from None


def prepare(source: bytes, snapshot: dict, manifest: dict, profile: dict) -> dict:
    validate_profile(profile)
    proof = generated_verification.verify(
        source, snapshot, manifest, profile["identity"]["generator_digest"]
    )
    extension = snapshot["authoring_structure"]
    config = extension["metadata"].get("effective_style", extension["style_template"]["config"])
    roots = generated_verification.verify_container(source, page_number=config["page_number"])
    return {
        "proof": proof,
        "config": config,
        "roots": roots,
        "font_inspection": {
            "requested_fonts": [config["font"]],
            "paragraphs": [
                generated_renderer.expected_body(roots),
                config["header_text"],
                config["footer_text"],
            ],
        },
    }


def failure(source: bytes, profile: dict, code: str) -> dict:
    return generated_renderer.failure(source, profile, code) | {"protocol": PROTOCOL}


def render(source: bytes, snapshot: dict, manifest: dict, profile: dict, *, receipt: Path) -> dict:
    # Freeze caller inputs across source admission, conversion and PDF inspection.
    snapshot, manifest, profile = deepcopy((snapshot, manifest, profile))
    try:
        validate_profile(profile)
        admitted = {}

        def admit():
            prepared = prepare(source, snapshot, manifest, profile)
            admitted.update(prepared["proof"])
            return prepared

        value = prebuilt._render_generated(
            source,
            profile["identity"]["provider_profile"],
            receipt=receipt,
            admit=admit,
            inspect_pdf=generated_renderer.inspect_pdf,
        )
        value["protocol"] = PROTOCOL
        if "measurements" in value:
            value["correspondence"] = value["measurements"]
        value["chain"] = (
            admitted
            | value["chain"]
            | {
                "profile_digest": profile["profile_digest"],
                "provider_profile_digest": profile["identity"]["provider_profile"][
                    "profile_digest"
                ],
                "render_protocol": PROTOCOL,
            }
        )
        return value
    except DomainError as error:
        return failure(source, profile, error.code)
