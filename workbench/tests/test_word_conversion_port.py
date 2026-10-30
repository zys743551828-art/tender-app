"""Frozen protocol selection preserves original qualification and fails closed."""

import json
from copy import deepcopy

import pytest

from packages.domain.errors import DomainError
from packages.word_intake import conversion, prebuilt, renderer
from packages.word_intake.repository import controlled_qualified


def test_disabled_and_legacy_profiles_keep_the_original_port(monkeypatch):
    monkeypatch.delenv("WORD_RENDER_PROFILE_PATH", raising=False)
    expected = {"identity": {"enabled": False}, "profile_digest": "legacy"}
    monkeypatch.setattr(renderer, "configured_profile", lambda: expected)
    monkeypatch.setattr(renderer, "render", lambda source, profile: (source, profile))
    assert conversion.configured_profile() is expected
    assert conversion.render(b"original", expected) == (b"original", expected)


def test_selected_new_profile_is_validated_without_loading_legacy_assets(monkeypatch, tmp_path):
    identity = prebuilt._fixed()
    expected = {"identity": identity, "profile_digest": prebuilt.digest(identity)}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(expected), encoding="utf-8")
    monkeypatch.setenv("WORD_RENDER_PROFILE_PATH", str(path))
    monkeypatch.setattr(
        renderer, "configured_profile", lambda: pytest.fail("legacy assets accessed")
    )
    assert conversion.configured_profile() == expected
    expected["identity"]["options"]["network"] = "bridge"
    expected["profile_digest"] = prebuilt.digest(expected["identity"])
    path.write_text(json.dumps(expected), encoding="utf-8")
    with pytest.raises(DomainError) as caught:
        conversion.configured_profile()
    assert caught.value.code == "WORD_RENDER_PROFILE_INVALID"


def qualified_new_result():
    return {
        "protocol": prebuilt.PROTOCOL,
        "state": "succeeded",
        "coverage": "complete",
        "conversion_attempted": True,
        "gaps": [],
        "isolation": {"checks": {key: True for key in prebuilt.ISOLATION_CHECKS}},
        "chain": {
            key: "a" * 64
            for key in (
                "source_docx_digest",
                "pdf_digest",
                "profile_digest",
                "renderer_digest",
                "fontset_digest",
                "options_digest",
            )
        },
    }


def test_new_receipt_needs_every_observed_safety_check_and_content_identity():
    result = qualified_new_result()
    assert controlled_qualified(result)
    for key in prebuilt.ISOLATION_CHECKS:
        changed = deepcopy(result)
        changed["isolation"]["checks"].pop(key)
        assert not controlled_qualified(changed), key
        changed["isolation"]["checks"][key] = False
        assert not controlled_qualified(changed), key
    for key in result["chain"]:
        changed = deepcopy(result)
        changed["chain"][key] = "not-a-digest"
        assert not controlled_qualified(changed), key
    for key, value in (
        ("coverage", "partial"),
        ("conversion_attempted", False),
        ("gaps", ["WORD_FONT_SUBSTITUTED"]),
    ):
        changed = deepcopy(result)
        changed[key] = value
        assert not controlled_qualified(changed)


def test_protocol_switch_never_promotes_an_old_isolation_shape():
    from packages.word_intake.repository import REQUIRED_ISOLATION

    result = qualified_new_result()
    result["isolation"] = {key: True for key in REQUIRED_ISOLATION}
    assert not controlled_qualified(result)
    result.pop("protocol")
    assert controlled_qualified(result)
