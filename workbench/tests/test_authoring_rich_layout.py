"""Joint geometry uses actual native image, table, caption and navigation proofs."""

import pytest
import test_authoring_rich_caption_pdf as caption_cases
import test_authoring_rich_renderer as renderer_cases

from packages.authoring import (
    page_navigation,
    rich_caption_pdf,
    rich_docx,
    rich_layout,
    rich_pdf,
    rich_renderer,
    rich_table_pdf,
    rich_verification,
    templates,
)


def inspect(*, kind=("image", "table"), attack=None, mode="chapter_start_new_page"):
    data, snapshot, materials, roots = caption_cases.specimen(
        kind=kind, count=2, attack=attack, navigation=True
    )
    images = rich_pdf.inspect_images(data, snapshot, materials, templates.DEFAULT_STYLE)
    tables = rich_table_pdf.inspect_tables(data, snapshot, roots, templates.DEFAULT_STYLE)
    entries = rich_docx.navigation_entries(snapshot)
    entries[0]["expected_start_page"] = 2
    navigation = page_navigation.inspect_navigation(
        data, entries, mode=mode, style=templates.DEFAULT_STYLE
    )
    captions = rich_caption_pdf.inspect_captions(
        data, snapshot, images, tables, templates.DEFAULT_STYLE
    )
    assert images["coverage"] == tables["coverage"] == captions["coverage"] == "complete", (
        images,
        tables,
        captions,
    )
    assert navigation["navigation_coverage"] == "complete", navigation
    return rich_layout.inspect_layout(snapshot, images, tables, navigation), (
        data,
        snapshot,
        materials,
    )


@pytest.mark.parametrize("kind", [("image", "table"), ("table", "image")])
def test_mixed_objects_in_frozen_order_and_own_section_pass(kind):
    proof, _ = inspect(kind=kind)
    assert proof["coverage"] == "complete", proof
    assert [item["kind"] for item in proof["objects"]] == list(kind)
    assert all(
        item["section_start_page"] == item["section_content_end_page"] == 2
        for item in proof["objects"]
    )


@pytest.mark.parametrize("kind", [("image", "table"), ("table", "image")])
def test_independently_correct_objects_and_captions_cannot_swap_mixed_order(kind):
    proof, _ = inspect(kind=kind, attack="mixed_swap")
    assert proof["gaps"] == ["AUTHORING_RICH_OBJECT_ORDER_UNVERIFIED"]


def test_table_and_image_cannot_migrate_to_toc_page():
    proof, _ = inspect(attack="on_toc")
    assert proof["gaps"] == ["AUTHORING_RICH_OBJECT_SECTION_UNVERIFIED"]


def test_continuous_mode_keeps_section_gap():
    proof, _ = inspect(mode="continuous")
    assert proof["gaps"] == ["AUTHORING_RICH_OBJECT_SECTION_UNVERIFIED"]


def test_mixed_order_gap_reaches_combined_rich_inspection():
    _, (data, snapshot, materials) = inspect(attack="mixed_swap")
    _, _, profile, _, _ = renderer_cases.rich_input.__wrapped__()
    source = rich_docx.assemble(snapshot, materials)
    manifest = rich_verification.manifest(source, snapshot, materials)
    prepared = rich_renderer.prepare(source, snapshot, materials, manifest, profile)
    result = rich_renderer.inspect_pdf(data, prepared)
    assert "AUTHORING_RICH_OBJECT_ORDER_UNVERIFIED" in result["gaps"]
    assert result["rich_layout_correspondence"]["coverage"] == "partial"


@pytest.mark.parametrize("kind", [("image", "table"), ("table", "image")])
def test_parallel_objects_do_not_invent_a_single_column_order(kind):
    proof, _ = inspect(kind=kind, attack="mixed_parallel")
    assert proof["gaps"] == ["AUTHORING_RICH_OBJECT_ORDER_UNVERIFIED"]


def test_incomplete_measured_object_taints_joint_layout():
    data, snapshot, materials, roots = caption_cases.specimen(
        kind=("image", "table"), count=2, navigation=True
    )
    data = data.replace(b"\xff\x00\x00" * 40 * 30, b"\x00\xff\x00" * 40 * 30)
    images = rich_pdf.inspect_images(data, snapshot, materials, templates.DEFAULT_STYLE)
    tables = rich_table_pdf.inspect_tables(data, snapshot, roots, templates.DEFAULT_STYLE)
    proof = rich_layout.inspect_layout(snapshot, images, tables, {})
    assert images["coverage"] == "partial"
    assert proof["gaps"] == ["AUTHORING_RICH_OBJECT_LAYOUT_UNVERIFIED"]
