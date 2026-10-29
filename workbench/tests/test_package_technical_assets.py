"""Current synthetic PDF derivations; never historical existence or readability proof."""

import io
import os
import struct
import zlib
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from packages.domain.review_identity import digest
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import technical_png as png
from packages.parsing import pdfium_guard, physical_pdf

DOCUMENT = str(UUID(int=9001))


def original(*, form=False, size=(420, 595)):
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=size, invariant=1)
    pdf.setFont("Helvetica", 16)
    pdf.drawString(30, size[1] - 45, "Current synthetic rendering fixture")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(30, size[1] - 70, "Full pages are retained; crops are not resampled.")
    if form:
        pdf.acroForm.textfield(
            name="synthetic_field", value="123", x=30, y=100, width=100, height=20
        )
        pdf.showPage()
    else:
        pdf.setFillColorRGB(1, 0, 0)
        pdf.rect(30, 150, 120, 70, fill=1, stroke=0)
        pdf.setFillColorRGB(0, 0, 1)
        pdf.rect(180, 150, 150, 70, fill=1, stroke=0)
        pdf.setFillColorRGB(0, 0, 0)
        pdf.drawString(30, 235, "Red and blue are source content, not score features.")
        pdf.showPage()
        pdf.setPageRotation(90)
        pdf.drawString(30, 250, "Second physical page with declared rotation.")
    pdf.save()
    return output.getvalue()


def render(data):
    return assets.render_static_pdf(
        data,
        document_version_id=DOCUMENT,
        expected_source_digest=png.digest_bytes(data),
        expected_source_size=len(data),
        expected_method_digest=assets.render_method_digest(),
    )


@pytest.fixture(scope="module")
def baseline():
    return render(original())


def regions(bundle):
    first = bundle.manifest["pages"][0]["asset"]
    return [
        {
            "physical_page": 1,
            "parent_image_digest": first["sha256"],
            "rectangle": [60, 1050, 1140, 1450],
        }
    ]


def crop(bundle, requests=None):
    return assets.crop_page_assets(
        bundle,
        requests if requests is not None else regions(bundle),
        expected_manifest_digest=bundle.manifest["digest"],
        expected_method_digest=assets.crop_method_digest(),
    )


def clone(bundle):
    return assets.PageAssetBundle(deepcopy(bundle.manifest), dict(bundle.blobs))


def reseal(bundle):
    bundle.manifest["digest"] = digest(
        {key: value for key, value in bundle.manifest.items() if key != "digest"}
    )


def verify(bundle):
    return assets.verify_bundle(bundle, expected_manifest_digest=bundle.manifest["digest"])


def test_actual_pdfium_renders_every_page_and_independent_pillow_reads_rgb(
    baseline, record_testsuite_property
):
    m = baseline.manifest
    assert m["page_count"] == 2 and [row["physical_page"] for row in m["pages"]] == [1, 2]
    assert m["pages"][1]["rotation"] == 90
    first = m["pages"][0]["asset"]
    assert (first["width"], first["height"]) == (1260, 1785)
    for page in m["pages"]:
        a = page["asset"]
        with Image.open(io.BytesIO(baseline.blobs[a["id"]])) as image:
            image.load()
            assert image.mode == "RGB" and image.size == (a["width"], a["height"])
    with Image.open(io.BytesIO(baseline.blobs[first["id"]])) as image:
        assert image.getpixel((270, 1230)) == (255, 0, 0)
        assert image.getpixel((720, 1230)) == (0, 0, 255)
    assert m["render_scope"] == "all_pdfium_page_viewports"
    assert not any(
        m[key]
        for key in (
            "input_authority_granted",
            "visual_readability_verified",
            "historical_byte_existence_verified",
            "isolated_execution_verified",
            "font_reproducibility_verified",
        )
    )
    assert assets.render_descriptor()["physical_dpi_verified"] is False
    record_testsuite_property("page_render_method_digest", assets.render_method_digest())
    record_testsuite_property("page_crop_method_digest", assets.crop_method_digest())
    record_testsuite_property("pdfium_version", str(assets.pdfium.PDFIUM_INFO))
    record_testsuite_property("pdfium_wrapper", str(assets.pdfium.PYPDFIUM_INFO))
    _export_current_synthetic_evidence(baseline)


def test_crop_keeps_all_full_pages_and_matches_independent_pillow_pixel_crop(baseline):
    before = deepcopy(baseline.manifest)
    derived = crop(baseline)
    assert baseline.manifest == before
    assert derived.manifest["pages"] == baseline.manifest["pages"]
    assert derived.manifest["parent_manifest_digest"] == baseline.manifest["digest"]
    assert derived.manifest["rendered_at"] == baseline.manifest["rendered_at"]
    detail = derived.manifest["details"][0]
    parent = baseline.manifest["pages"][0]["asset"]
    with (
        Image.open(io.BytesIO(baseline.blobs[parent["id"]])) as image,
        Image.open(io.BytesIO(derived.blobs[detail["asset"]["id"]])) as piece,
    ):
        assert piece.tobytes() == image.crop(tuple(detail["rectangle"])).tobytes()
        assert piece.size == (1080, 400)
    assert set(baseline.blobs) < set(derived.blobs)
    verify(derived)


def test_png_encoder_does_not_require_pdfium_to_pil(monkeypatch):
    monkeypatch.setattr(
        assets.pdfium.PdfBitmap, "to_pil", lambda *_: pytest.fail("production must not call Pillow")
    )
    assert render(original()).manifest["page_count"] == 2


@pytest.mark.parametrize("orphan", [False, True])
def test_canonical_and_orphan_widgets_are_refused_before_rendering(orphan, monkeypatch):
    data = original(form=True)
    if orphan:
        assert b"/AcroForm" in data
        data = data.replace(b"/AcroForm", b"/NoFormsX")
    monkeypatch.setattr(
        assets.pdfium.PdfPage,
        "render",
        lambda *_a, **_k: pytest.fail("must reject interactive source before rendering"),
    )
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_INTERACTIVE_PDF_UNSUPPORTED"):
        render(data)


def test_original_source_and_method_are_checked_before_native_loading(monkeypatch):
    data = original()
    monkeypatch.setattr(
        assets.pdfium, "PdfDocument", lambda *_: pytest.fail("native load forbidden")
    )
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_SOURCE_MISMATCH"):
        assets.render_static_pdf(
            data,
            document_version_id=DOCUMENT,
            expected_source_digest="0" * 64,
            expected_source_size=len(data),
            expected_method_digest=assets.render_method_digest(),
        )
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_METHOD_MISMATCH"):
        assets.render_static_pdf(
            data,
            document_version_id=DOCUMENT,
            expected_source_digest=png.digest_bytes(data),
            expected_source_size=len(data),
            expected_method_digest="0" * 64,
        )


@pytest.mark.parametrize("policy", ["pages", "total_pixels", "bytes"])
def test_limits_reject_whole_output_instead_of_dropping_pages(policy, monkeypatch):
    if policy == "pages":
        monkeypatch.setattr(assets, "MAX_PAGES", 1)
        code = "PAGE_ASSET_PAGE_LIMIT"
    elif policy == "total_pixels":
        monkeypatch.setattr(assets, "MAX_TOTAL_PIXELS", 1)
        code = "PAGE_ASSET_TOTAL_PIXEL_LIMIT"
    else:
        monkeypatch.setattr(assets, "MAX_TOTAL_BYTES", 1)
        code = "PAGE_ASSET_BYTE_LIMIT"
    with pytest.raises(png.PageAssetError, match=code):
        render(original())


def test_oversize_canvas_is_rejected_before_bitmap_allocation(monkeypatch):
    data = original(size=(4000, 4000))
    monkeypatch.setattr(
        assets.pdfium.PdfPage, "render", lambda *_a, **_k: pytest.fail("allocation forbidden")
    )
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_PIXEL_LIMIT"):
        render(data)


@pytest.mark.parametrize(
    "rectangle",
    [
        [-1, 0, 10, 10],
        [0, 0, 9999, 10],
        [0, 0, 10, 9999],
        [10, 0, 5, 10],
        [0, 0, 0, 10],
        [False, 0, 10, 10],
        [1.0, 0, 10, 10],
    ],
)
def test_crop_never_escapes_parent_or_coerces_coordinates(baseline, rectangle):
    requested = regions(baseline)
    requested[0]["rectangle"] = rectangle
    with pytest.raises(png.PageAssetError):
        crop(baseline, requested)


@pytest.mark.parametrize("change", ["page", "digest", "duplicate", "empty", "extra", "float_page"])
def test_crop_requires_explicit_unique_same_page_requests(baseline, change):
    requested = regions(baseline)
    if change == "page":
        requested[0]["physical_page"] = 3
    elif change == "float_page":
        requested[0]["physical_page"] = 1.0
    elif change == "digest":
        requested[0]["parent_image_digest"] = "0" * 64
    elif change == "duplicate":
        requested.append(deepcopy(requested[0]))
    elif change == "empty":
        requested = []
    else:
        requested[0]["quality_verified"] = True
    with pytest.raises(png.PageAssetError):
        crop(baseline, requested)


def test_changed_blob_is_refused_and_parent_metadata_is_not_repaired(baseline):
    altered = clone(baseline)
    key = next(iter(altered.blobs))
    altered.blobs[key] = altered.blobs[key][:-1] + bytes([altered.blobs[key][-1] ^ 1])
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_BLOB_MISMATCH"):
        verify(altered)
    assert baseline.manifest["digest"] != "0" * 64


def test_owned_manifest_digest_cannot_be_replaced_by_a_self_declared_one(baseline):
    altered = clone(baseline)
    frozen = baseline.manifest["digest"]
    altered.manifest["source_digest"] = "0" * 64
    reseal(altered)
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_MANIFEST_DIGEST_MISMATCH"):
        assets.verify_bundle(altered, expected_manifest_digest=frozen)


def test_crops_cannot_replace_parent_page_metadata_even_with_a_new_outer_digest(baseline):
    altered = crop(baseline)
    altered.manifest["pages"][0]["canvas_width"] = "999.0"
    reseal(altered)
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_PARENT_MANIFEST_MISMATCH"):
        verify(altered)


def test_pixel_substitution_cannot_hide_behind_correct_shape_and_hashes(baseline):
    altered = crop(baseline)
    a = altered.manifest["details"][0]["asset"]
    replacement = png.encode_rgb(
        a["width"], a["height"], (b"\xff" * (a["width"] * 3) for _ in range(a["height"]))
    )
    altered.blobs[a["id"]] = replacement
    a.update(sha256=png.digest_bytes(replacement), byte_size=len(replacement))
    reseal(altered)
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_CROP_PIXELS_MISMATCH"):
        verify(altered)


def test_a_derived_record_cannot_silently_drop_an_original_full_page(baseline):
    altered = crop(baseline)
    removed = altered.manifest["pages"].pop()
    altered.manifest["page_count"] = 1
    altered.blobs.pop(removed["asset"]["id"])
    reseal(altered)
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_PARENT_MANIFEST_MISMATCH"):
        verify(altered)


def test_deriving_from_an_existing_crop_record_requires_reselecting_the_baseline(baseline):
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_REGIONS_INVALID"):
        crop(crop(baseline))


def test_existing_text_parser_uses_same_lock_and_keeps_partial_claims():
    assert physical_pdf.LOCK is pdfium_guard.LOCK is assets.pdfium_guard.LOCK
    parsed = physical_pdf.extract(original())
    assert len(parsed["pages"]) == 2 and parsed["pages"][1]["rotation"] == 90
    assert parsed["coverage"] == "partial"
    assert parsed["gaps"] == ["TEXT_ONLY_TABLES_VISUAL_AND_LAYOUT_UNVERIFIED"]


def test_external_png_reader_and_crc_limits_are_real():
    rows = [bytes([255, 0, 0, 0, 255, 0]), bytes([0, 0, 255, 255, 255, 255])]
    data = png.encode_rgb(2, 2, rows)
    with Image.open(io.BytesIO(data)) as image:
        assert [image.getpixel((x, y)) for y in range(2) for x in range(2)] == [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 255),
        ]
    assert png.decode_rgb(data) == (2, 2, b"".join(rows))
    for bad in (data[:-1], data + b"extra", data[:20] + bytes([data[20] ^ 1]) + data[21:]):
        with pytest.raises(png.PageAssetError, match="PAGE_ASSET_PNG_INVALID"):
            png.decode_rgb(bad)


@pytest.mark.parametrize("rows", [[], [b"abc"], [b"a" * 6] * 3, [b"a" * 5, b"a" * 6]])
def test_png_rows_cannot_be_missing_truncated_or_overlong(rows):
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_RGB_INVALID"):
        png.encode_rgb(2, 2, rows)


def test_decoder_bounds_decompression_and_rejects_nonzero_filters():
    # Valid CRCs do not make an oversized decoded payload safe.
    def packet(raw):
        return (
            png.SIGNATURE
            + png._chunk(b"IHDR", struct.pack("!IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + png._chunk(b"IDAT", zlib.compress(raw))
            + png._chunk(b"IEND", b"")
        )

    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_PNG_INVALID"):
        png.decode_rgb(packet(b"\x00" * 100))
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_PNG_FORMAT_UNSUPPORTED"):
        png.decode_rgb(packet(b"\x01abc"))


def _export_current_synthetic_evidence(baseline):
    if os.environ.get("FUSION_PAGE_ASSET_EVIDENCE") != "1":
        return
    target = Path("/evidence/technical-page-assets")
    target.mkdir(parents=True, exist_ok=True)
    derived = crop(baseline)
    assert png.digest_bytes(original()) == baseline.manifest["source_digest"]
    (target / "synthetic-source.pdf").write_bytes(original())
    for page in derived.manifest["pages"]:
        (target / f"page-{page['physical_page']}.png").write_bytes(
            derived.blobs[page["asset"]["id"]]
        )
    (target / "detail-1.png").write_bytes(
        derived.blobs[derived.manifest["details"][0]["asset"]["id"]]
    )
    import json

    (target / "manifest.json").write_text(
        json.dumps(derived.manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


@pytest.mark.parametrize(
    "key",
    [
        "input_authority_granted",
        "visual_readability_verified",
        "historical_byte_existence_verified",
        "isolated_execution_verified",
        "font_reproducibility_verified",
    ],
)
def test_renderer_receipts_cannot_grant_authority_or_backdate_existence(baseline, key):
    altered = clone(baseline)
    altered.manifest[key] = True
    reseal(altered)
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_MANIFEST_INVALID"):
        verify(altered)


def test_duplicate_pixel_pages_keep_separate_physical_identities():
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(100, 100), invariant=1)
    for _ in range(2):
        pdf.drawString(10, 50, "Same visible page")
        pdf.showPage()
    pdf.save()
    result = render(output.getvalue())
    first, second = [row["asset"] for row in result.manifest["pages"]]
    assert first["sha256"] == second["sha256"]
    assert first["id"] != second["id"] and len(result.blobs) == 2


def test_native_document_and_shared_lock_are_released_on_preflight_failure(monkeypatch):
    events = []
    close = assets.pdfium.PdfDocument.close

    def checked_close(document, *args, **kwargs):
        events.append("close")
        return close(document, *args, **kwargs)

    monkeypatch.setattr(assets.pdfium.PdfDocument, "close", checked_close)
    monkeypatch.setattr(assets, "MAX_PAGES", 1)
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_PAGE_LIMIT"):
        render(original())
    assert events
    assert pdfium_guard.LOCK.acquire(blocking=False)
    pdfium_guard.LOCK.release()


def test_soft_deadline_refuses_output_but_does_not_claim_hard_isolation(monkeypatch):
    ticks = iter((0, 31))
    monkeypatch.setattr(assets.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        assets.pdfium.PdfPage,
        "render",
        lambda *_a, **_k: pytest.fail("deadline must refuse before render"),
    )
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_SOFT_DEADLINE"):
        render(original())
    assert assets.render_descriptor()["hard_isolation_installed"] is False


def test_details_are_ordered_by_physical_page_and_keep_parent_full_images(baseline):
    second = baseline.manifest["pages"][1]["asset"]
    requested = [
        {
            "physical_page": 2,
            "parent_image_digest": second["sha256"],
            "rectangle": [0, 0, 100, 100],
        },
        *regions(baseline),
    ]
    result = crop(baseline, requested)
    assert [row["physical_page"] for row in result.manifest["details"]] == [1, 2]
    assert result.manifest["pages"] == baseline.manifest["pages"]


@pytest.mark.parametrize("bad", [b"", b"not a pdf", b"%PDF-1.7\nbroken"])
def test_bad_sources_return_explicit_failure_without_images(bad):
    with pytest.raises(png.PageAssetError):
        render(bad)


def test_crop_does_not_take_extra_unrequested_blobs(baseline):
    altered = clone(baseline)
    altered.blobs["0" * 64] = b"unrequested"
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_BLOB_SET_MISMATCH"):
        crop(altered)


def test_total_crop_budget_rejects_whole_derivation(baseline, monkeypatch):
    base_pixels = sum(
        row["asset"]["width"] * row["asset"]["height"] for row in baseline.manifest["pages"]
    )
    monkeypatch.setattr(assets, "MAX_TOTAL_PIXELS", base_pixels)
    with pytest.raises(png.PageAssetError, match="PAGE_ASSET_TOTAL_PIXEL_LIMIT"):
        crop(baseline)
