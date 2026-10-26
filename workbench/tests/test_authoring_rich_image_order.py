"""Real PDF bytes: frozen image order follows page geometry, not paint order."""

import copy
import io
from uuid import uuid4

import pypdfium2 as pdfium
import pytest
from PIL import Image

from packages.authoring import rich_images, rich_pdf, templates


def specimen(
    *,
    swapped=False,
    separate_pages=False,
    reverse_paint=False,
    repeated=False,
    side_by_side=False,
    overlap=False,
):
    materials, blocks = [], []
    for index in range(2):
        with Image.new("RGB", (40, 30), "red" if index == 0 or repeated else "blue") as pixels:
            encoded = io.BytesIO()
            pixels.save(encoded, format="PNG")
        normalized = rich_images.normalize(encoded.getvalue(), "image/png")
        asset, version = str(uuid4()), str(uuid4())
        materials.append(
            {
                "asset_id": asset,
                "asset_revision": 1,
                "asset_version_id": version,
                "bytes": normalized["bytes"],
                "normalization_proof": normalized["proof"],
            }
        )
        blocks.append(
            {
                "type": "image",
                "attrs": {
                    "id": f"image-{index}",
                    "asset_id": asset,
                    "asset_revision": 1,
                    "asset_version_id": version,
                    "width_twips": 2400,
                    "height_twips": 1800,
                },
            }
        )
    # Separate sections deliberately test global, not just intra-section, ordering.
    snapshot = {"sections": [{"content": [block]} for block in blocks]}
    document = pdfium.PdfDocument.new()
    bitmaps = []
    try:
        for page_index in range(2 if separate_pages else 1):
            page = document.new_page(11906 / 20, 16838 / 20)
            try:
                indices = [page_index] if separate_pages else [0, 1]
                if reverse_paint:
                    indices.reverse()
                for position in indices:
                    source = 1 - position if swapped else position
                    with Image.open(io.BytesIO(materials[source]["bytes"])) as pixels:
                        bitmap = pdfium.PdfBitmap.from_pil(pixels, recopy=True)
                    bitmaps.append(bitmap)
                    image = pdfium.PdfImage.new(document)
                    image.set_bitmap(bitmap)
                    left = 72 + (150 * position if side_by_side else 0)
                    bottom = (
                        600 if separate_pages or side_by_side or overlap else 600 - 150 * position
                    )
                    image.set_matrix(pdfium.PdfMatrix(120, 0, 0, 90, left, bottom))
                    page.insert_obj(image)
                page.gen_content()
            finally:
                page.close()
        encoded = io.BytesIO()
        document.save(encoded)
        return encoded.getvalue(), snapshot, materials
    finally:
        document.close()
        for bitmap in bitmaps:
            bitmap.close()


@pytest.mark.parametrize("separate_pages", [False, True])
def test_swapping_distinct_images_keeps_pixels_but_must_not_pass_order(separate_pages):
    proof = rich_pdf.inspect_images(
        *specimen(swapped=True, separate_pages=separate_pages), templates.DEFAULT_STYLE
    )
    assert proof["matched_drawings"] == 2
    assert all(not image["gaps"] for image in proof["images"])
    assert proof["coverage"] == "partial", proof
    assert "AUTHORING_IMAGE_ORDER_UNVERIFIED" in proof["gaps"]


@pytest.mark.parametrize("separate_pages", [False, True])
@pytest.mark.parametrize("repeated", [False, True])
@pytest.mark.parametrize("reverse_paint", [False, True])
def test_geometry_order_and_repeated_assets_are_independent_of_paint_order(
    separate_pages, repeated, reverse_paint
):
    data, snapshot, materials = specimen(
        separate_pages=separate_pages, repeated=repeated, reverse_paint=reverse_paint
    )
    before = copy.deepcopy(snapshot)
    proof = rich_pdf.inspect_images(data, snapshot, materials, templates.DEFAULT_STYLE)
    assert proof["coverage"] == "complete", proof
    assert [image["node_id"] for image in proof["images"]] == ["image-0", "image-1"]
    assert snapshot == before


@pytest.mark.parametrize("options", [{"side_by_side": True}, {"overlap": True, "repeated": True}])
def test_inline_images_without_unique_vertical_order_remain_partial(options):
    proof = rich_pdf.inspect_images(*specimen(**options), templates.DEFAULT_STYLE)
    assert proof["coverage"] == "partial", proof
    assert "AUTHORING_IMAGE_ORDER_UNVERIFIED" in proof["gaps"]
