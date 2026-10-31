"""Word installation overlay; the underlying full/1 role contract stays intact."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path

from deploy import fusion_full_spec as base
from packages.domain.errors import DomainError
from packages.word_intake import prebuilt

VERSION = "word-conversion-installation/2"
INSTALLATION_VERSION = "fusion-word-role/2"
DESKTOP_VERSION = "fusion-desktop-full/2"
PROFILE_FILES = {
    "external": "word-external.json",
    "page": "word-page.json",
    "rich": "word-rich.json",
}
ROLE_LANES = {
    "api": ("external", "page", "rich"),
    "worker": ("external",),
    "controller": ("external",),
}


def _producer_profiles():
    # Legacy authoring imports bootstrap domain.runtime. The composition root
    # must explicitly opt out of development dotenv before those imports occur.
    # Do not mutate the caller's environment from this library.
    if not os.environ.get("WORKBENCH_ENV_FILE"):
        raise base.ConfigurationError("FULL_WORD_EXPLICIT_ENV_REQUIRED")
    from packages.authoring import prebuilt_generated, prebuilt_rich

    return prebuilt_generated, prebuilt_rich


def validate_bundle(value):
    """Recheck current source-qualified profiles, without Docker or conversion."""
    prebuilt_generated, prebuilt_rich = _producer_profiles()
    try:
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "image", "profiles"}
            or value["version"] != VERSION
            or value["image"] != prebuilt.IMAGE
            or not isinstance(value["profiles"], dict)
            or set(value["profiles"]) != set(PROFILE_FILES)
        ):
            raise ValueError()
        profiles = value["profiles"]
        prebuilt.validate_profile(profiles["external"])
        prebuilt_generated.validate_profile(profiles["page"])
        prebuilt_rich.validate_profile(profiles["rich"])
        if any(
            profiles[lane]["identity"]["provider_profile"] != profiles["external"]
            for lane in ("page", "rich")
        ):
            raise ValueError()
    except (KeyError, TypeError, ValueError, DomainError, prebuilt.PrebuiltError):
        raise base.ConfigurationError("FULL_WORD_BUNDLE_INVALID") from None


def bundle(receipt: Path) -> dict:
    """Host-only installation preparation; never called by a business runtime."""
    prebuilt_generated, prebuilt_rich = _producer_profiles()
    external = prebuilt.build_profile(receipt=receipt)
    result = {
        "version": VERSION,
        "image": prebuilt.IMAGE,
        "profiles": {
            "external": external,
            "page": prebuilt_generated.profile_for(external),
            "rich": prebuilt_rich.profile_for(external),
        },
    }
    validate_bundle(result)
    return result


def validate_installation(value, base_profile, role):
    base.validate_role(base_profile)
    if (
        role not in ROLE_LANES
        or base_profile["role"] != role
        or not isinstance(value, dict)
        or set(value) != {"version", "instance_id", "base_plan_digest", "role", "bundle"}
        or value["version"] != INSTALLATION_VERSION
        or value["role"] != role
        or value["base_plan_digest"] != base_profile["plan_digest"]
        or not isinstance(value["instance_id"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", value["instance_id"])
    ):
        raise base.ConfigurationError("FULL_WORD_INSTALLATION_INVALID")
    validate_bundle(value["bundle"])


def installation(request, base_profile, role) -> dict:
    """Bind a desktop request to one already validated full/1 role profile."""
    base.validate_role(base_profile)
    if (
        not isinstance(request, dict)
        or set(request)
        != {"version", "instance_id", "name", "origin", "python_image", "web_image", "word"}
        | ({"model_configured"} if "model_configured" in request else set())
        | ({"parser"} if "parser" in request else set())
        or request["version"] != DESKTOP_VERSION
        or request["name"] != base_profile["plan"]["name"]
        or request["origin"] != base_profile["plan"]["origin"]
        or request["python_image"] != base_profile["plan"]["images"]["python"]
        or request["web_image"] != base_profile["plan"]["images"]["web"]
        or request.get("model_configured", False) is not base_profile["plan"]["model_configured"]
        or ("parser" in request) != ("parser" in base_profile["plan"])
        or request.get("parser") != base_profile["plan"].get("parser")
    ):
        raise base.ConfigurationError("FULL_WORD_REQUEST_BINDING_INVALID")
    if "parser" in request:
        from deploy.fusion_parsing_spec import validate as validate_parser

        validate_parser(request["parser"])
    result = {
        "version": INSTALLATION_VERSION,
        "instance_id": request["instance_id"],
        "base_plan_digest": base_profile["plan_digest"],
        "role": role,
        "bundle": deepcopy(request["word"]),
    }
    validate_installation(result, base_profile, role)
    return result
