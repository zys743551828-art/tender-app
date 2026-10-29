"""Real navigation and image measurements joined on one actual synthetic PDF."""

import io

import pypdfium2 as pdfium
import pytest
import test_authoring_page_navigation as navigation_cases
import test_authoring_rich_image_order as image_cases
from PIL import Image

from packages.authoring import page_navigation, rich_pdf, structure_model


def specimen(*, placements=((2, 600), (3, 600)), owners=(0, 1), left=72, **navigation_options):
    _, image_snapshot, materials = image_cases.specimen()
    entries = navigation_cases.entries([2, 3, 5])
    snapshot = {"sections": [{"section_id": row["node_id"], "content": []} for row in entries]}
    snapshot["authoring_structure"] = {
        "nodes": [
            structure_model.node(
                row["node_id"], parent=row["parent_id"], ordinal=1 if index == 2 else 0
            )
            for index, row in enumerate(entries)
        ]
    }
    for index, owner in enumerate(owners):
        snapshot["sections"][owner]["content"].extend(image_snapshot["sections"][index]["content"])
    document = pdfium.PdfDocument(navigation_cases.small_pdf(entries, **navigation_options))
    bitmaps = []
    try:
        for index, (number, bottom) in enumerate(placements):
            page = document[number - 1]
            try:
                with Image.open(io.BytesIO(materials[index]["bytes"])) as pixels:
                    bitmap = pdfium.PdfBitmap.from_pil(pixels, recopy=True)
                bitmaps.append(bitmap)
                image = pdfium.PdfImage.new(document)
                image.set_bitmap(bitmap)
                image.set_matrix(pdfium.PdfMatrix(120, 0, 0, 90, left, bottom))
                page.insert_obj(image)
                page.gen_content()
            finally:
                page.close()
        output = io.BytesIO()
        document.save(output)
        return output.getvalue(), snapshot, materials, entries
    finally:
        document.close()
        for bitmap in bitmaps:
            bitmap.close()


def inspect(*, mode="chapter_start_new_page", **options):
    data, snapshot, materials, entries = specimen(**options)
    images = rich_pdf.inspect_images(data, snapshot, materials, navigation_cases.STYLE)
    navigation = page_navigation.inspect_navigation(
        data, entries, mode=mode, style=navigation_cases.STYLE
    )
    return rich_pdf.inspect_image_sections(snapshot, images, navigation), images, navigation


@pytest.mark.parametrize(
    "placements,owners",
    [
        (((2, 600), (3, 600)), (0, 1)),
        (((2, 600), (4, 600)), (0, 1)),
        (((2, 600), (6, 600)), (0, 2)),
    ],
)
def test_actual_image_sections_accept_own_pages_and_continuations(placements, owners):
    proof, images, navigation = inspect(placements=placements, owners=owners)
    assert images["coverage"] == navigation["coverage"] == proof["coverage"] == "complete"
    assert all(item["matched"] for item in proof["images"])
    # Parent subtree includes page 3/4, but its own content must end before Child.
    assert navigation["entries"][0]["end_page"] == 4
    assert proof["images"][0]["section_content_end_page"] == 2


@pytest.mark.parametrize(
    "placements",
    [
        ((1, 500), (3, 600)),  # parent image in TOC
        ((3, 600), (4, 600)),  # parent image migrated into child, preserving global image order
        ((2, 600), (5, 600)),  # child image migrated into next root chapter
    ],
)
def test_correct_pixels_and_order_cannot_hide_wrong_section(placements):
    proof, images, navigation = inspect(placements=placements)
    assert images["coverage"] == navigation["coverage"] == "complete"
    assert proof["coverage"] == "partial"
    assert proof["gaps"] == ["AUTHORING_IMAGE_SECTION_UNVERIFIED"]
    assert not all(item["matched"] for item in proof["images"])


@pytest.mark.parametrize(
    "options", [{"mode": "continuous"}, {"wrong_title": True}, {"missing": True}]
)
def test_incomplete_or_continuous_navigation_never_grants_section_placement(options):
    proof, images, _ = inspect(**options)
    assert images["coverage"] == "complete"
    assert proof["coverage"] == "partial" and proof["images"] == []


def test_no_images_needs_no_section_evidence():
    assert rich_pdf.inspect_image_sections({"sections": []}, {}, {})["coverage"] == "complete"


def test_image_next_to_heading_cannot_count_as_following_it():
    proof, images, navigation = inspect(placements=((2, 670), (3, 600)), left=250)
    assert images["coverage"] == navigation["coverage"] == "complete"
    assert proof["coverage"] == "partial"
    assert proof["images"][0]["matched"] is False
