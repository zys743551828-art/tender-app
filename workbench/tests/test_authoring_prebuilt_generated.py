"""New provider admission/dispatch only; never Docker, models or real conversion."""

from copy import deepcopy

import pytest
import test_authoring_generated as cases

from packages.authoring import generated_docx, generated_renderer, prebuilt_generated
from packages.domain.errors import DomainError
from packages.word_intake import prebuilt
from packages.word_intake.inspection import inspect_docx


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("No external execution in provider wrapper unit tests")
    monkeypatch.setattr(prebuilt, "_call", blocked)
    monkeypatch.setattr(prebuilt, "_Run", blocked)
    monkeypatch.setattr(prebuilt, "_render_generated", blocked)
    monkeypatch.setattr(generated_renderer.sandbox, "_docker", blocked)


@pytest.fixture
def page_input():
    snapshot = cases.snapshot.__wrapped__()
    source = generated_docx.assemble(snapshot)
    manifest = generated_docx.producer_manifest(source, snapshot)
    identity = prebuilt._fixed()
    provider = {"identity": identity, "profile_digest": prebuilt.digest(identity)}
    return snapshot, source, manifest, prebuilt_generated.profile_for(provider)


def test_new_profile_accepts_exact_page_without_old_word03_gate(page_input, monkeypatch):
    snapshot, source, manifest, profile = page_input
    def blocked(*args):
        raise AssertionError("New PAGE admission must not call the frozen old profile gate")
    monkeypatch.setattr(generated_renderer, "profile_for", blocked)
    value = prebuilt_generated.prepare(source, snapshot, manifest, profile)
    assert value["proof"]["source_docx_digest"] == prebuilt.digest(source)
    assert value["proof"]["page_number"] is True
    assert profile["identity"]["generator_digest"] == manifest["generator_digest"]
    assert profile["identity"]["protocol"] == prebuilt_generated.PROTOCOL
    assert "base_profile" not in profile["identity"]
    assert not inspect_docx(source)["conversion_eligible"]


def test_rehashed_foreign_docx_cannot_be_admitted(page_input):
    snapshot, source, _, profile = page_input
    source += b"extra foreign bytes"
    manifest = generated_docx.producer_manifest(source, snapshot)
    with pytest.raises(DomainError):
        prebuilt_generated.prepare(source, snapshot, manifest, profile)


@pytest.mark.parametrize("key,value", [
    ("protocol", generated_renderer.PROTOCOL),
    ("dynamic_field_policy", "all_fields"),
    ("pdf_inspector_digest", "0" * 64),
])
def test_rehashed_old_or_weakened_profile_rejected_before_port(page_input, tmp_path, key, value):
    snapshot, source, manifest, profile = page_input
    profile = deepcopy(profile)
    profile["identity"][key] = value
    profile["profile_digest"] = prebuilt.digest(profile["identity"])
    result = prebuilt_generated.render(source, snapshot, manifest, profile, receipt=tmp_path / "r.json")
    assert result["state"] == "failed"
    assert result["error_code"] == "AUTHORING_PREBUILT_PROFILE_CHANGED"
    assert not result["conversion_attempted"]


def test_existing_pdf_checker_and_source_proof_survive_provider_boundary(page_input, monkeypatch, tmp_path):
    snapshot, source, manifest, profile = page_input
    checker = generated_renderer.inspect_pdf
    def fake_port(data, provider, *, receipt, admit, inspect_pdf):
        assert data == source and inspect_pdf is checker
        prepared = admit()
        assert prepared["font_inspection"]["requested_fonts"] == [prepared["config"]["font"]]
        # A concurrent caller mutation cannot change the admitted expected body.
        snapshot["sections"].clear()
        assert prepared["proof"]["source_docx_digest"] == prebuilt.digest(source)
        return {"state": "succeeded", "coverage": "partial", "gaps": ["AUTHORING_PAGE_NUMBER_OR_FOOTER_UNVERIFIED"],
                "chain": {"profile_digest": provider["profile_digest"]}, "pdf": b"synthetic-only",
                "measurements": {"page_count": 1, "gaps": ["AUTHORING_PAGE_NUMBER_OR_FOOTER_UNVERIFIED"]}}
    monkeypatch.setattr(prebuilt, "_render_generated", fake_port)
    result = prebuilt_generated.render(source, snapshot, manifest, profile, receipt=tmp_path / "r.json")
    assert result["coverage"] == "partial"
    assert result["correspondence"]["gaps"] == result["gaps"]
    assert result["chain"]["generator_digest"] == profile["identity"]["generator_digest"]
    assert result["chain"]["provider_profile_digest"] != result["chain"]["profile_digest"]
    assert result["protocol"] == prebuilt_generated.PROTOCOL


def test_provider_failure_stays_failed_without_creating_old_qualification(page_input, monkeypatch, tmp_path):
    snapshot, source, manifest, profile = page_input
    def failed(data, provider, **kwargs):
        kwargs["admit"]()
        return prebuilt._failure(data, provider, "WORD_CONVERSION_TIMEOUT", True)
    monkeypatch.setattr(prebuilt, "_render_generated", failed)
    result = prebuilt_generated.render(source, snapshot, manifest, profile, receipt=tmp_path / "r.json")
    assert result["state"] == "failed" and result["pdf"] is None
    assert result["error_code"] == "WORD_CONVERSION_TIMEOUT"
    assert result["protocol"] != generated_renderer.PROTOCOL
