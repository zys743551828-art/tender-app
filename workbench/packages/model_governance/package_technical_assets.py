"""Static page views and lossless same-raster crops; not a public PDF sandbox.

Untrusted production input requires a separately installed isolated asset worker.
This module has no DB, object-store, provider, environment or qualification port.
"""

import math
import sys
import time
import zlib
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium
from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts import package_technical_assets as contract
from packages.domain import review_identity
from packages.domain.review_identity import canonical, digest
from packages.model_governance import technical_png as png
from packages.parsing import pdfium_guard

MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_PIXELS = 128_000_000
MAX_TOTAL_BYTES = png.MAX_BYTES
MAX_PAGES = 128
MAX_MANIFEST_BYTES = 512 * 1024
SCALE = 3
SOFT_SECONDS = 30


@dataclass(frozen=True, repr=False)
class PageAssetBundle:
    manifest: dict
    blobs: dict[str, bytes]


def _source(module):
    filename = getattr(module, "__file__", None)
    if not isinstance(filename, str):
        png.fail("PAGE_ASSET_METHOD_UNAVAILABLE")
    try:
        return png.digest_bytes(Path(filename).read_bytes())
    except OSError:
        png.fail("PAGE_ASSET_METHOD_UNAVAILABLE")


def _shared_descriptor():
    return {
        "schema_digest": digest(contract.schema()),
        "regions_schema_digest": digest(contract.regions_schema()),
        "contract_source": _source(contract),
        "canonical_source": _source(review_identity),
        "codec_source": _source(png),
        "codec": "rgb8-filter0/1",
        "zlib_compile": zlib.ZLIB_VERSION,
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
        "python_version": list(sys.version_info[:3]),
        "schema_validator_version": version("jsonschema"),
        "maximum_bytes": MAX_TOTAL_BYTES,
        "maximum_manifest_bytes": MAX_MANIFEST_BYTES,
        "maximum_page_pixels": png.MAX_PIXELS,
        "maximum_dimension": png.MAX_DIMENSION,
    }


def render_descriptor():
    return {
        **_shared_descriptor(),
        "version": "package-technical-page-render-method/2",
        "source": png.digest_bytes(Path(__file__).read_bytes()),
        "guard_source": _source(pdfium_guard),
        "pdfium_wrapper": str(pdfium.PYPDFIUM_INFO),
        "pdfium_engine": str(pdfium.PDFIUM_INFO),
        "platform": sys.platform,
        "pixels_per_pdfium_canvas_unit": SCALE,
        "physical_dpi_verified": False,
        "maximum_source_bytes": MAX_SOURCE_BYTES,
        "maximum_pages": MAX_PAGES,
        "maximum_total_pixels": MAX_TOTAL_PIXELS,
        "soft_seconds": SOFT_SECONDS,
        "annotations": True,
        "forms": "reject_canonical_or_orphan_widget",
        "resampling": "none",
        "hard_isolation_installed": False,
    }


def render_method_digest():
    return digest(render_descriptor())


def crop_method_digest():
    return digest(
        {
            **_shared_descriptor(),
            "version": "package-technical-page-crop-method/2",
            "source": png.digest_bytes(Path(__file__).read_bytes()),
            "coordinate_space": "parent_page_pixels_top_left",
            "detail_order": "physical_page_then_request_order",
            "maximum_total_pixels": MAX_TOTAL_PIXELS,
            "soft_seconds": SOFT_SECONDS,
            "resampling": "none",
            "retain_all_parent_pages": True,
        }
    )


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _asset(data, width, height, identity):
    checksum = png.digest_bytes(data)
    return {
        "id": digest({**identity, "sha256": checksum}),
        "sha256": checksum,
        "byte_size": len(data),
        "width": width,
        "height": height,
        "media_type": "image/png",
    }


def _finish(manifest, blobs):
    manifest["digest"] = digest({key: value for key, value in manifest.items() if key != "digest"})
    bundle = PageAssetBundle(manifest, blobs)
    verify_bundle(bundle, expected_manifest_digest=manifest["digest"])
    return bundle


def verify_bundle(bundle, *, expected_manifest_digest):
    if (
        not isinstance(bundle, PageAssetBundle)
        or not isinstance(bundle.manifest, dict)
        or not isinstance(bundle.blobs, dict)
    ):
        png.fail("PAGE_ASSET_BUNDLE_INVALID")
    try:
        metadata_size = len(canonical(bundle.manifest))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        png.fail("PAGE_ASSET_MANIFEST_INVALID")
    if metadata_size > MAX_MANIFEST_BYTES or len(bundle.blobs) > 256:
        png.fail("PAGE_ASSET_METADATA_LIMIT")
    manifest, blobs = deepcopy(bundle.manifest), dict(bundle.blobs)
    if not Draft202012Validator(contract.schema(), format_checker=FormatChecker()).is_valid(
        manifest
    ):
        png.fail("PAGE_ASSET_MANIFEST_INVALID")
    if (
        manifest["digest"] != expected_manifest_digest
        or digest({key: value for key, value in manifest.items() if key != "digest"})
        != expected_manifest_digest
    ):
        png.fail("PAGE_ASSET_MANIFEST_DIGEST_MISMATCH")
    if [row["physical_page"] for row in manifest["pages"]] != list(
        range(1, manifest["page_count"] + 1)
    ):
        png.fail("PAGE_ASSET_PAGE_SET_INCOMPLETE")
    derived = bool(manifest["details"])
    if any(
        (manifest[key] is not None) != derived
        for key in ("crop_method_digest", "parent_manifest_digest", "cropped_at")
    ):
        png.fail("PAGE_ASSET_DERIVATION_INVALID")
    if derived:
        baseline = deepcopy(manifest)
        baseline.update(
            crop_method_digest=None, parent_manifest_digest=None, cropped_at=None, details=[]
        )
        baseline.pop("digest")
        if digest(baseline) != manifest["parent_manifest_digest"]:
            png.fail("PAGE_ASSET_PARENT_MANIFEST_MISMATCH")
    all_assets = [row["asset"] for row in manifest["pages"] + manifest["details"]]
    asset_ids = [asset["id"] for asset in all_assets]
    if len(set(asset_ids)) != len(asset_ids) or set(asset_ids) != set(blobs):
        png.fail("PAGE_ASSET_BLOB_SET_MISMATCH")
    if sum(asset["width"] * asset["height"] for asset in all_assets) > MAX_TOTAL_PIXELS:
        png.fail("PAGE_ASSET_TOTAL_PIXEL_LIMIT")
    if (
        any(not isinstance(data, bytes) for data in blobs.values())
        or sum(len(data) for data in blobs.values()) > MAX_TOTAL_BYTES
    ):
        png.fail("PAGE_ASSET_BYTE_LIMIT")
    for asset in all_assets:
        data = blobs[asset["id"]]
        if (
            len(data) != asset["byte_size"]
            or png.digest_bytes(data) != asset["sha256"]
            or png.png_size(data) != (asset["width"], asset["height"])
        ):
            png.fail("PAGE_ASSET_BLOB_MISMATCH")
    pages = {row["physical_page"]: row["asset"] for row in manifest["pages"]}
    seen: set[tuple[int, int, int, int, int]] = set()
    for detail in manifest["details"]:
        parent = pages.get(detail["physical_page"])
        rectangle = detail["rectangle"]
        if (
            not parent
            or detail["parent_asset_id"] != parent["id"]
            or detail["parent_image_digest"] != parent["sha256"]
        ):
            png.fail("PAGE_ASSET_PARENT_MISMATCH")
        _rectangle(rectangle, parent["width"], parent["height"])
        key = (detail["physical_page"], rectangle[0], rectangle[1], rectangle[2], rectangle[3])
        if key in seen or (detail["asset"]["width"], detail["asset"]["height"]) != (
            rectangle[2] - rectangle[0],
            rectangle[3] - rectangle[1],
        ):
            png.fail("PAGE_ASSET_CROP_GEOMETRY_INVALID")
        seen.add(key)
    for page_no, parent in pages.items():
        details = [row for row in manifest["details"] if row["physical_page"] == page_no]
        if not details:
            continue
        width, _, rgb = png.decode_rgb(blobs[parent["id"]])
        for detail in details:
            left, top, right, bottom = detail["rectangle"]
            _, _, crop = png.decode_rgb(blobs[detail["asset"]["id"]])
            stride = (right - left) * 3
            if any(
                crop[(row - top) * stride : (row - top + 1) * stride]
                != rgb[(row * width + left) * 3 : (row * width + right) * 3]
                for row in range(top, bottom)
            ):
                png.fail("PAGE_ASSET_CROP_PIXELS_MISMATCH")
    return manifest, blobs


def _rectangle(value, width, height):
    if not isinstance(value, list) or len(value) != 4 or any(type(v) is not int for v in value):
        png.fail("PAGE_ASSET_REGION_INVALID")
    left, top, right, bottom = value
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
        png.fail("PAGE_ASSET_REGION_INVALID")


def _box(values):
    if values is None:
        return None
    if len(values) != 4 or any(not math.isfinite(value) for value in values):
        png.fail("PAGE_ASSET_PDF_GEOMETRY_INVALID")
    return [str(float(value)) for value in values]


def _reject_widgets(page):
    count = pdfium.raw.FPDFPage_GetAnnotCount(page)
    if count < 0:
        png.fail("PAGE_ASSET_PDF_ANNOTATION_INVALID")
    for index in range(count):
        annotation = pdfium.raw.FPDFPage_GetAnnot(page, index)
        if not annotation:
            png.fail("PAGE_ASSET_PDF_ANNOTATION_INVALID")
        try:
            if pdfium.raw.FPDFAnnot_GetSubtype(annotation) == pdfium.raw.FPDF_ANNOT_WIDGET:
                png.fail("PAGE_ASSET_INTERACTIVE_PDF_UNSUPPORTED")
        finally:
            pdfium.raw.FPDFPage_CloseAnnot(annotation)


def render_static_pdf(
    data,
    *,
    document_version_id,
    expected_source_digest,
    expected_source_size,
    expected_method_digest,
):
    if expected_method_digest != render_method_digest():
        png.fail("PAGE_ASSET_METHOD_MISMATCH")
    if (
        type(data) is not bytes
        or not 0 < len(data) <= MAX_SOURCE_BYTES
        or not data.startswith(b"%PDF-")
    ):
        png.fail("PAGE_ASSET_PDF_INVALID")
    if (
        type(expected_source_size) is not int
        or expected_source_size != len(data)
        or png.digest_bytes(data) != expected_source_digest
    ):
        png.fail("PAGE_ASSET_SOURCE_MISMATCH")
    if not Draft202012Validator(contract.ID, format_checker=FormatChecker()).is_valid(
        document_version_id
    ):
        png.fail("PAGE_ASSET_DOCUMENT_INVALID")
    started = time.monotonic()
    pages: list[dict] = []
    blobs: dict[str, bytes] = {}
    try:
        with pdfium_guard.LOCK, closing(pdfium.PdfDocument(data)) as pdf:
            if not 1 <= len(pdf) <= MAX_PAGES:
                png.fail("PAGE_ASSET_PAGE_LIMIT")
            if pdf.get_formtype() != pdfium.raw.FORMTYPE_NONE:
                png.fail("PAGE_ASSET_INTERACTIVE_PDF_UNSUPPORTED")
            planned: list[tuple[int, int]] = []
            for index in range(len(pdf)):
                with closing(pdf[index]) as page:
                    _reject_widgets(page)
                    width, height = page.get_size()
                    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                        png.fail("PAGE_ASSET_PDF_GEOMETRY_INVALID")
                    size = (math.ceil(width * SCALE), math.ceil(height * SCALE))
                    png.dimensions(*size)
                    planned.append(size)
            if sum(w * h for w, h in planned) > MAX_TOTAL_PIXELS:
                png.fail("PAGE_ASSET_TOTAL_PIXEL_LIMIT")
            for index, size in enumerate(planned):
                if time.monotonic() - started > SOFT_SECONDS:
                    png.fail("PAGE_ASSET_SOFT_DEADLINE")
                with closing(pdf[index]) as page:
                    with closing(
                        page.render(
                            scale=SCALE,
                            rotation=0,
                            crop=(0, 0, 0, 0),
                            may_draw_forms=False,
                            force_bitmap_format=pdfium.raw.FPDFBitmap_BGR,
                            rev_byteorder=True,
                            draw_annots=True,
                            fill_color=(255, 255, 255, 255),
                            limit_image_cache=True,
                        )
                    ) as bitmap:
                        if (
                            (bitmap.width, bitmap.height) != size
                            or bitmap.mode != "RGB"
                            or bitmap.stride != size[0] * 3
                        ):
                            png.fail("PAGE_ASSET_BITMAP_INVALID")
                        buffer = memoryview(bitmap.buffer).cast("B")
                        encoded = png.encode_rgb(
                            *size,
                            (
                                buffer[row * bitmap.stride : (row + 1) * bitmap.stride]
                                for row in range(bitmap.height)
                            ),
                            limit=MAX_TOTAL_BYTES - sum(len(value) for value in blobs.values()),
                        )
                    asset = _asset(
                        encoded,
                        *size,
                        {
                            "kind": "full_page",
                            "document": document_version_id,
                            "source": expected_source_digest,
                            "physical_page": index + 1,
                            "render_method": expected_method_digest,
                        },
                    )
                    pages.append(
                        {
                            "physical_page": index + 1,
                            "rotation": page.get_rotation(),
                            "canvas_width": str(float(page.get_width())),
                            "canvas_height": str(float(page.get_height())),
                            "media_box": _box(page.get_mediabox()),
                            "crop_box": _box(page.get_cropbox(fallback_ok=False)),
                            "asset": asset,
                        }
                    )
                    blobs[asset["id"]] = encoded
    except png.PageAssetError:
        raise
    except Exception:
        raise png.PageAssetError("PAGE_ASSET_PDF_RENDER_FAILED") from None
    if time.monotonic() - started > SOFT_SECONDS:
        png.fail("PAGE_ASSET_SOFT_DEADLINE")
    manifest = {
        "version": "package-technical-page-assets/2",
        "document_version_id": document_version_id,
        "source_digest": expected_source_digest,
        "source_byte_size": len(data),
        "render_method_digest": expected_method_digest,
        "crop_method_digest": None,
        "parent_manifest_digest": None,
        "rendered_at": _now(),
        "cropped_at": None,
        "pixel_format": "rgb8-filter0/1",
        "render_scope": "all_pdfium_page_viewports",
        "page_count": len(pages),
        "pages": pages,
        "details": [],
        "full_pages_retained": True,
        **{
            key: False
            for key in (
                "input_authority_granted",
                "visual_readability_verified",
                "historical_byte_existence_verified",
                "isolated_execution_verified",
                "font_reproducibility_verified",
            )
        },
        "limitations": [
            "CURRENT_DERIVATION_NOT_HISTORICAL_BYTE_PROOF",
            "PIXELS_NOT_READABILITY_PROOF",
            "PDFIUM_CANVAS_UNITS_NOT_VERIFIED_DPI",
            "FONT_AND_COLOR_REPRODUCTION_NOT_CERTIFIED",
            "ISOLATED_WORKER_REQUIRED_BEFORE_PUBLIC_USE",
        ],
    }
    return _finish(manifest, blobs)


def crop_page_assets(bundle, regions, *, expected_manifest_digest, expected_method_digest):
    if expected_method_digest != crop_method_digest():
        png.fail("PAGE_ASSET_CROP_METHOD_MISMATCH")
    started = time.monotonic()
    manifest, blobs = verify_bundle(bundle, expected_manifest_digest=expected_manifest_digest)
    if manifest["details"] or not Draft202012Validator(contract.regions_schema()).is_valid(regions):
        png.fail("PAGE_ASSET_REGIONS_INVALID")
    pages = {row["physical_page"]: row["asset"] for row in manifest["pages"]}
    grouped: dict[int, list[dict]] = {}
    seen: set[tuple[int, int, int, int, int]] = set()
    for region in regions:
        if type(region["physical_page"]) is not int:
            png.fail("PAGE_ASSET_REGION_INVALID")
        page = pages.get(region["physical_page"])
        if not page or region["parent_image_digest"] != page["sha256"]:
            png.fail("PAGE_ASSET_PARENT_MISMATCH")
        _rectangle(region["rectangle"], page["width"], page["height"])
        r = region["rectangle"]
        key = (region["physical_page"], r[0], r[1], r[2], r[3])
        if key in seen:
            png.fail("PAGE_ASSET_REGION_DUPLICATE")
        seen.add(key)
        grouped.setdefault(region["physical_page"], []).append(region)
    if (
        sum(page["width"] * page["height"] for page in pages.values())
        + sum(
            (r["rectangle"][2] - r["rectangle"][0]) * (r["rectangle"][3] - r["rectangle"][1])
            for r in regions
        )
        > MAX_TOTAL_PIXELS
    ):
        png.fail("PAGE_ASSET_TOTAL_PIXEL_LIMIT")
    details = []
    for page_no in sorted(grouped):
        requests = grouped[page_no]
        if time.monotonic() - started > SOFT_SECONDS:
            png.fail("PAGE_ASSET_SOFT_DEADLINE")
        page = pages[page_no]
        width, _, rgb = png.decode_rgb(blobs[page["id"]])
        for request in requests:
            left, top, right, bottom = request["rectangle"]
            row_width = (right - left) * 3
            rows = (
                rgb[(row * width + left) * 3 : (row * width + left) * 3 + row_width]
                for row in range(top, bottom)
            )
            encoded = png.encode_rgb(
                right - left,
                bottom - top,
                rows,
                limit=MAX_TOTAL_BYTES - sum(len(value) for value in blobs.values()),
            )
            asset = _asset(
                encoded,
                right - left,
                bottom - top,
                {
                    "kind": "detail",
                    "parent": page["id"],
                    "rectangle": request["rectangle"],
                    "crop_method": expected_method_digest,
                },
            )
            details.append(
                {
                    "physical_page": page_no,
                    "parent_asset_id": page["id"],
                    "parent_image_digest": page["sha256"],
                    "rectangle": list(request["rectangle"]),
                    "asset": asset,
                }
            )
            blobs[asset["id"]] = encoded
    manifest.update(
        crop_method_digest=expected_method_digest,
        parent_manifest_digest=expected_manifest_digest,
        cropped_at=_now(),
        details=details,
    )
    result = _finish(manifest, blobs)
    if time.monotonic() - started > SOFT_SECONDS:
        png.fail("PAGE_ASSET_SOFT_DEADLINE")
    return result
