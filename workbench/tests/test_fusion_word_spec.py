"""Offline installation identity checks; no Docker, DB or model calls."""

import os
import subprocess
import sys
from copy import deepcopy

import pytest

from deploy import fusion_word_spec as word
from packages.authoring import prebuilt_generated, prebuilt_rich
from packages.word_intake import prebuilt


@pytest.fixture
def word_bundle():
    identity = prebuilt._fixed()
    external = {"identity": identity, "profile_digest": prebuilt.digest(identity)}
    return {
        "version": word.VERSION,
        "image": prebuilt.IMAGE,
        "profiles": {
            "external": external,
            "page": prebuilt_generated.profile_for(external),
            "rich": prebuilt_rich.profile_for(external),
        },
    }


@pytest.fixture
def binding(word_bundle, monkeypatch):
    # Base contract has its own full-profile tests. Keep this overlay test offline
    # and assert every public entry delegates to that unchanged validator.
    checked = []
    monkeypatch.setattr(word.base, "validate_role", lambda profile: checked.append(profile))
    base_profile = {
        "role": "worker",
        "plan_digest": "b" * 64,
        "plan": {
            "model_configured": False,
            "name": "full_word",
            "origin": "http://127.0.0.1:5189",
            "images": {"python": "python@sha256:" + "c" * 64, "web": "web@sha256:" + "d" * 64},
        },
    }
    request = {
        "version": word.DESKTOP_VERSION,
        "instance_id": "a" * 32,
        "name": base_profile["plan"]["name"],
        "origin": base_profile["plan"]["origin"],
        "python_image": base_profile["plan"]["images"]["python"],
        "web_image": base_profile["plan"]["images"]["web"],
        "word": word_bundle,
    }
    return request, base_profile, checked


def test_bundle_uses_only_host_preparation_and_current_profile_factories(
    word_bundle, monkeypatch, tmp_path
):
    receipts = []

    def prepare(*, receipt):
        receipts.append(receipt)
        return deepcopy(word_bundle["profiles"]["external"])

    monkeypatch.setattr(prebuilt, "build_profile", prepare)
    receipt = tmp_path / "resources.json"
    assert word.bundle(receipt) == word_bundle
    assert receipts == [receipt]


@pytest.mark.parametrize("attack", ["extra", "image", "external", "page", "rich", "missing"])
def test_unknown_and_rehashed_stale_profiles_fail_closed(word_bundle, attack):
    value = deepcopy(word_bundle)
    if attack == "extra":
        value["command"] = "untrusted"
    elif attack == "image":
        value["image"] = "other@sha256:" + "f" * 64
    elif attack == "missing":
        del value["profiles"]["page"]
    else:
        profile = value["profiles"][attack]
        profile["identity"]["unknown"] = True
        # Even a recomputed envelope digest cannot qualify changed behavior.
        profile["profile_digest"] = prebuilt.digest(profile["identity"])
    with pytest.raises(word.base.ConfigurationError, match="FULL_WORD_BUNDLE_INVALID"):
        word.validate_bundle(value)


def test_installation_binds_role_plan_instance_and_does_not_alias_request(binding):
    request, profile, checked = binding
    installed = word.installation(request, profile, "worker")
    assert installed["base_plan_digest"] == profile["plan_digest"]
    assert installed["instance_id"] == request["instance_id"]
    word.validate_installation(installed, profile, "worker")
    assert len(checked) == 3
    request["word"]["image"] = "changed"
    assert installed["bundle"]["image"] == prebuilt.IMAGE


@pytest.mark.parametrize(
    "field", ["version", "name", "origin", "python_image", "web_image", "instance_id", "extra"]
)
def test_request_binding_changes_are_rejected(binding, field):
    request, profile, _ = binding
    request[field] = "foreign"
    with pytest.raises(word.base.ConfigurationError):
        word.installation(request, profile, "worker")


@pytest.mark.parametrize("field", ["version", "instance_id", "base_plan_digest", "role", "extra"])
def test_installed_role_cannot_be_rebound(binding, field):
    request, profile, _ = binding
    installed = word.installation(request, profile, "worker")
    installed[field] = "foreign"
    with pytest.raises(word.base.ConfigurationError, match="FULL_WORD_INSTALLATION_INVALID"):
        word.validate_installation(installed, profile, "worker")


def test_base_contract_failure_is_not_swallowed(binding, monkeypatch):
    request, profile, _ = binding

    def reject(value):
        raise word.base.ConfigurationError("FULL_ROLE_PROFILE_BINDING_INVALID")

    monkeypatch.setattr(word.base, "validate_role", reject)
    with pytest.raises(word.base.ConfigurationError, match="FULL_ROLE_PROFILE_BINDING_INVALID"):
        word.installation(request, profile, "worker")


def test_import_never_bootstraps_business_configuration_and_validation_requires_opt_out():
    environment = {key: value for key, value in os.environ.items() if key != "WORKBENCH_ENV_FILE"}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    script = """
import os,sys
from deploy import fusion_word_spec as word
assert 'packages.domain.runtime' not in sys.modules
before=dict(os.environ)
try:
    word.validate_bundle({})
except word.base.ConfigurationError as error:
    assert str(error)=='FULL_WORD_EXPLICIT_ENV_REQUIRED'
else:
    raise AssertionError('explicit opt-out required')
assert before==dict(os.environ)
assert 'packages.domain.runtime' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], env=environment, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


@pytest.mark.parametrize("role", ["api", "worker", "controller"])
@pytest.mark.parametrize("with_parser", [False, True])
def test_real_word_profile_installation_preserves_each_role_with_optional_parser(
    binding, role, with_parser
):
    from deploy import fusion_parsing_spec as parsing

    request, profile, checked = binding
    profile["role"] = role
    if with_parser:
        request["parser"] = parsing.descriptor("synthetic-parser@sha256:" + "e" * 64)
        profile["plan"]["parser"] = deepcopy(request["parser"])
    profile["plan_digest"] = word.base.digest(profile["plan"])
    installed = word.installation(request, profile, role)
    word.validate_installation(installed, profile, role)
    assert installed == {
        "version": word.INSTALLATION_VERSION,
        "instance_id": request["instance_id"],
        "base_plan_digest": profile["plan_digest"],
        "role": role,
        "bundle": request["word"],
    }
    assert checked == [profile, profile, profile]


@pytest.mark.parametrize(
    "attack", ["request_only", "plan_only", "different_image", "extra_request_field"]
)
def test_parser_request_cannot_bind_another_plan_or_expand_word_request(binding, attack):
    from deploy import fusion_parsing_spec as parsing

    request, profile, _ = binding
    request["parser"] = parsing.descriptor("synthetic-parser@sha256:" + "e" * 64)
    profile["plan"]["parser"] = deepcopy(request["parser"])
    if attack == "request_only":
        del profile["plan"]["parser"]
    elif attack == "plan_only":
        del request["parser"]
    elif attack == "different_image":
        request["parser"] = parsing.descriptor("different-parser@sha256:" + "f" * 64)
    else:
        request["parser_url"] = "http://other:8812"
    profile["plan_digest"] = word.base.digest(profile["plan"])
    with pytest.raises(word.base.ConfigurationError, match="FULL_WORD_REQUEST_BINDING_INVALID"):
        word.installation(request, profile, "worker")


@pytest.mark.parametrize(
    "attack", ["url", "transport", "image", "version", "extra", "null", "list"]
)
def test_equal_but_malformed_parser_descriptors_do_not_bypass_word_installation(binding, attack):
    from deploy import fusion_parsing_spec as parsing

    request, profile, _ = binding
    value = parsing.descriptor("synthetic-parser@sha256:" + "e" * 64)
    if attack == "null":
        value = None
    elif attack == "list":
        value = []
    elif attack == "url":
        value["url"] = "http://other:8812"
    elif attack == "transport":
        value["transport"] = "arbitrary"
    elif attack == "image":
        value["image"] = "parser:latest"
    elif attack == "version":
        value["version"] = "parsing-installation/unknown"
    else:
        value["token"] = "synthetic-unaccepted-inline-token"
    request["parser"] = value
    profile["plan"]["parser"] = deepcopy(value)
    profile["plan_digest"] = word.base.digest(profile["plan"])
    # Even exact request/plan equality cannot qualify an invalid descriptor.
    with pytest.raises(word.base.ConfigurationError, match="FULL_PARSER_"):
        word.installation(request, profile, "worker")
