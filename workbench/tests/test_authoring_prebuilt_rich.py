"""Pure new-provider RICH admission and original measured TOC fixed-point rules."""

from copy import deepcopy

import pytest
import test_authoring_page_navigation as navigation_cases
import test_authoring_rich_renderer as rich_cases

from packages.authoring import (
    page_navigation,
    prebuilt_pdf,
    prebuilt_rich,
    rich_docx,
    rich_renderer,
    rich_verification,
)
from packages.domain.errors import DomainError
from packages.word_intake import prebuilt
from packages.word_intake.inspection import inspect_docx


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("No Docker or HTTP in new RICH wrapper unit tests")

    monkeypatch.setattr(prebuilt, "_call", blocked)
    monkeypatch.setattr(prebuilt, "_Run", blocked)
    monkeypatch.setattr(prebuilt, "_render_generated", blocked)
    monkeypatch.setattr(rich_renderer.sandbox, "_docker", blocked)


@pytest.fixture
def rich_input():
    snapshot, materials, _, pagination, source = rich_cases.rich_input.__wrapped__()
    identity = prebuilt._fixed()
    provider = {"identity": identity, "profile_digest": prebuilt.digest(identity)}
    return snapshot, materials, prebuilt_rich.profile_for(provider), pagination, source


def test_exact_table_image_and_page_admitted_without_old_profile_gate(rich_input, monkeypatch):
    snapshot, materials, profile, pagination, source = rich_input

    def blocked(*args):
        raise AssertionError("New RICH must not fake an old Word03 profile")

    monkeypatch.setattr(rich_renderer, "profile_for", blocked)
    manifest = rich_verification.manifest(source, snapshot, materials, pagination=pagination)
    value = prebuilt_rich.prepare(
        source, snapshot, materials, manifest, profile, pagination=pagination
    )
    assert value["proof"]["native_table_count"] == 1
    assert value["proof"]["image_drawing_count"] == 1
    assert not inspect_docx(source)["conversion_eligible"]
    assert profile["identity"]["protocol"] != rich_renderer.PROTOCOL
    assert "base_profile" not in profile["identity"]


def test_rehashed_foreign_rich_source_or_changed_image_material_refused(rich_input):
    snapshot, materials, profile, pagination, source = rich_input
    altered = source + b"foreign trailing bytes"
    manifest = rich_verification.manifest(altered, snapshot, materials, pagination=pagination)
    with pytest.raises(DomainError):
        prebuilt_rich.prepare(
            altered, snapshot, materials, manifest, profile, pagination=pagination
        )
    changed = deepcopy(materials)
    changed[0]["bytes"] += b"x"
    original_manifest = rich_verification.manifest(
        source, snapshot, materials, pagination=pagination
    )
    with pytest.raises(DomainError):
        prebuilt_rich.prepare(
            source, snapshot, changed, original_manifest, profile, pagination=pagination
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_layout_passes", 4),
        ("dynamic_field_policy", "arbitrary_fields"),
        ("navigation_policy", "trust_requested_page_numbers"),
        ("pdf_inspector_digest", "0" * 64),
    ],
)
def test_rehashed_weakened_rich_profile_never_reaches_provider(rich_input, tmp_path, field, value):
    snapshot, materials, profile, pagination, source = rich_input
    profile = deepcopy(profile)
    profile["identity"][field] = value
    profile["profile_digest"] = prebuilt.digest(profile["identity"])
    manifest = rich_verification.manifest(source, snapshot, materials, pagination=pagination)
    result = prebuilt_rich.render_once(
        source,
        snapshot,
        materials,
        manifest,
        profile,
        pagination=pagination,
        receipt=tmp_path / "r.json",
    )
    assert result["state"] == "failed"
    assert result["error_code"] == "AUTHORING_PREBUILT_RICH_PROFILE_CHANGED"


def test_all_old_pdf_checks_are_the_actual_callback_and_gaps_are_preserved(
    rich_input, monkeypatch, tmp_path
):
    snapshot, materials, profile, pagination, source = rich_input
    checker = prebuilt_pdf.inspect_pdf

    def fake_port(data, provider, *, receipt, admit, inspect_pdf):
        assert inspect_pdf is checker
        prepared = admit()
        assert prepared["proof"]["image_drawing_count"] == 1
        return {
            "state": "succeeded",
            "coverage": "partial",
            "gaps": ["ACTUAL_TEST_IMAGE_ORDER_GAP"],
            "pdf": b"synthetic-only",
            "chain": {},
            "measurements": {
                "page_count": 2,
                "gaps": ["ACTUAL_TEST_IMAGE_ORDER_GAP"],
                "raster_correspondence": {"gaps": ["ACTUAL_TEST_IMAGE_ORDER_GAP"]},
            },
        }

    monkeypatch.setattr(prebuilt, "_render_generated", fake_port)
    manifest = rich_verification.manifest(source, snapshot, materials, pagination=pagination)
    result = prebuilt_rich.render_once(
        source,
        snapshot,
        materials,
        manifest,
        profile,
        pagination=pagination,
        receipt=tmp_path / "r.json",
    )
    assert result["coverage"] == "partial"
    assert result["correspondence"]["raster_correspondence"]["gaps"] == result["gaps"]
    assert result["chain"]["native_table_count"] == 1


@pytest.mark.parametrize("fail_third", [False, True])
def test_measured_fixed_point_and_failed_last_pass_keep_final_history_distinct(
    rich_input, monkeypatch, tmp_path, fail_third
):
    snapshot, materials, profile, pagination, _ = rich_input
    receipts = []

    def mock_adapter(source, snapshot, materials, manifest, profile, *, pagination, receipt):
        receipts.append(receipt)
        # Actual source reassembly verification is still required for every pass.
        prebuilt_rich.prepare(source, snapshot, materials, manifest, profile, pagination=pagination)
        if fail_third and len(receipts) == 3:
            return rich_renderer.failure(source, profile, "AUTHORING_GENERATED_CONVERSION_TIMEOUT")
        entries = rich_docx.navigation_entries(snapshot, pagination)
        data = navigation_cases.small_pdf(
            entries, starts=[len(receipts) + 1 if fail_third else 2], count=3 if fail_third else 2
        )
        nav = page_navigation.inspect_navigation(
            data,
            entries,
            mode=pagination["mode"],
            style=snapshot["authoring_structure"]["style_template"]["config"],
        )
        return {
            "state": "succeeded",
            "coverage": "partial" if nav["gaps"] else "complete",
            "gaps": nav["gaps"],
            "pdf": data,
            "correspondence": {"navigation": nav},
        }

    monkeypatch.setattr(prebuilt_rich, "render_once", mock_adapter)
    result = prebuilt_rich.render(
        snapshot, materials, profile, mode=pagination["mode"], receipt=tmp_path / "run.json"
    )
    assert len(set(receipts)) == len(receipts) == (3 if fail_third else 2)
    if fail_third:
        assert result["state"] == "failed" and result["pdf"] is None
        assert "navigation_proof" not in result and "navigation_history_proof" in result
    else:
        assert result["navigation_proof"]["fixed_point"] is True
    assert len(result["render_iterations"]) == 2


def test_missing_profile_keeps_verified_docx_without_conversion(rich_input, tmp_path):
    snapshot, materials, _, pagination, source = rich_input
    result = prebuilt_rich.render(
        snapshot, materials, None, mode=pagination["mode"], receipt=tmp_path / "r.json"
    )
    assert result["state"] == "failed" and result["docx"] == source
    assert result["render_iterations"] == []


@pytest.mark.parametrize("bad_final_number", [False, True])
def test_real_bootstrap_unknown_toc_measures_next_pass_without_accepting_bad_final_value(
    rich_input, monkeypatch, tmp_path, bad_final_number
):
    snapshot, materials, profile, pagination, _ = rich_input
    calls = []

    def adapter(source, snapshot, materials, manifest, profile, *, pagination, receipt):
        calls.append(deepcopy(pagination))
        entries = rich_docx.navigation_entries(snapshot, pagination)
        data = navigation_cases.small_pdf(
            entries, starts=[2], count=2, wrong_number=bad_final_number and len(calls) > 1
        )
        nav = page_navigation.inspect_navigation(
            data,
            entries,
            mode=pagination["mode"],
            style=snapshot["authoring_structure"]["style_template"]["config"],
        )
        # The real service's first round has a complete measured destination,
        # but no printed number because its source explicitly contains unknown.
        if len(calls) == 1:
            nav["toc_values_verified"] = False
            nav["coverage"] = "partial"
            nav["gaps"] = list(
                dict.fromkeys(
                    [
                        *nav["gaps"],
                        "NAV_TOC_NUMBERS_NOT_AT_FIXED_POINT",
                        "NAV_TOC_PRINTED_VALUE_MISMATCH",
                    ]
                )
            )
        assert nav["navigation_coverage"] == "complete"
        return {
            "state": "succeeded",
            "coverage": "partial" if nav["gaps"] else "complete",
            "gaps": nav["gaps"],
            "pdf": data,
            "correspondence": {"navigation": nav},
        }

    monkeypatch.setattr(prebuilt_rich, "render_once", adapter)
    result = prebuilt_rich.render(
        snapshot, materials, profile, mode=pagination["mode"], receipt=tmp_path / "bootstrap.json"
    )
    assert len(calls) == 2
    assert list(calls[0]["toc_start_pages"].values()) == [None]
    assert list(calls[1]["toc_start_pages"].values()) == [2]
    final = result["navigation_proof"]["final_navigation"]
    if bad_final_number:
        assert not final["toc_values_verified"]
        assert not result["navigation_proof"]["fixed_point"]
        assert result["coverage"] == "partial"
    else:
        assert final["toc_values_verified"]


@pytest.mark.parametrize(
    "attack", ["none", "one_pass", "known_wrong_number", "known_dot", "structure", "chain"]
)
def test_bootstrap_proof_only_exempts_first_unknown_numbers(rich_input, attack):
    snapshot, materials, _, pagination, _ = rich_input
    initial_entries = rich_docx.navigation_entries(snapshot, pagination)
    # Same-length PDF content substitution preserves the PDF offsets while
    # modeling a leader next to the unknown first-pass page placeholder.
    printed = deepcopy(initial_entries)
    printed[0]["expected_start_page"] = 2
    initial_pdf = navigation_cases.small_pdf(printed, starts=[2], count=2)
    assert b"400 750 Td (2) Tj ET" in initial_pdf
    initial_pdf = initial_pdf.replace(b"400 750 Td (2) Tj ET", b"400 750 Td (.) Tj ET")
    initial_docx = rich_docx.assemble(snapshot, materials, pagination=pagination)
    iterations = [
        {"pdf_bytes": initial_pdf, "docx_bytes": initial_docx, "entries": initial_entries}
    ]
    if attack != "one_pass":
        page = 3 if attack == "chain" else 2
        final_pagination = {
            "mode": pagination["mode"],
            "toc_start_pages": {node_id: page for node_id in pagination["toc_start_pages"]},
        }
        final_entries = rich_docx.navigation_entries(snapshot, final_pagination)
        if attack == "structure":
            final_entries[0]["title"] += " changed"
        final_pdf = navigation_cases.small_pdf(
            final_entries, starts=[page], count=page, wrong_number=attack == "known_wrong_number"
        )
        if attack == "known_dot":
            final_pdf = final_pdf.replace(b"400 750 Td (2) Tj ET", b"400 750 Td (.) Tj ET")
        iterations.append(
            {
                "pdf_bytes": final_pdf,
                "docx_bytes": rich_docx.assemble(snapshot, materials, pagination=final_pagination),
                "entries": final_entries,
            }
        )
    value = prebuilt_rich.converge_navigation(
        iterations,
        context_digest="a" * 64,
        mode=pagination["mode"],
        style=snapshot["authoring_structure"]["style_template"]["config"],
    )
    assert value["protocol"] == prebuilt_rich.NAVIGATION_PROTOCOL
    if attack == "none":
        assert value["fixed_point"] and value["coverage"] == "complete"
        assert value["bootstrap"]["intermediate_gaps"]
        assert value["final_navigation"]["toc_values_verified"]
    else:
        assert not value["fixed_point"] and value["coverage"] == "partial"
    if attack == "structure":
        assert "NAV_TOC_STRUCTURE_CHANGED_BETWEEN_RENDERS" in value["gaps"]
    if attack == "chain":
        assert "NAV_TOC_ITERATION_NOT_DERIVED_FROM_PREVIOUS_MEASUREMENT" in value["gaps"]
