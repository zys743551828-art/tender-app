"""Synthetic real PDF geometry/raster tests, never Office or business qualification."""

import io
import re
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest
import test_authoring_rich as rich_cases
import test_authoring_rich_caption_pdf as caption_cases
import test_authoring_rich_table_pdf as table_cases
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from packages.authoring import prebuilt_pdf, rich_table_pdf, templates
from packages.authoring.build import W


def encoded_caption_pdf(data, mapping, *, attack=None):
    """Rewrite synthetic name dictionaries and rebuild their exact byte offsets."""
    objects = re.findall(rb"\d+ 0 obj\n(.*?)\nendobj\n", data, re.S)
    for alias, name in mapping.items():
        original = b"(" + name.encode() + b")"
        encoded = b"(" + alias.encode() + b")"
        objects[0] = objects[0].replace(original, encoded)
    first = next(alias for alias in mapping if alias.startswith("cap5F"))
    if attack == "unknown":
        objects[0] = objects[0].replace(first.encode(), b"cap5F" + b"0" * 32)
    if attack == "collision":
        match = re.search(rb"\(" + first.encode() + rb"\) (\[[^]]+\])", objects[0])
        assert match
        duplicate = b"(" + mapping[first].encode() + b") " + match[1]
        objects[0] = objects[0].replace(match[0], match[0] + b" " + duplicate)
    output, offsets = bytearray(b"%PDF-1.7\n"), []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


@pytest.mark.parametrize("kind", ["image", "table"])
@pytest.mark.parametrize("attack", [None, "wrong_dest", "unknown", "collision", "digit", "cover"])
def test_exact_source_caption_aliases_keep_all_original_checks(kind, attack):
    original, snapshot, materials, roots = caption_cases.specimen(
        kind=kind, attack=attack if attack in {"wrong_dest", "digit", "cover"} else None
    )
    mapping = prebuilt_pdf._caption_name_mapping(
        {"snapshot": snapshot, "pagination": None, "roots": roots}
    )
    data = encoded_caption_pdf(original, mapping, attack=attack)
    images = caption_cases.rich_pdf.inspect_images(
        data, snapshot, materials, templates.DEFAULT_STYLE
    )
    tables = rich_table_pdf.inspect_tables(data, snapshot, roots, templates.DEFAULT_STYLE)
    inspector = caption_cases.rich_caption_pdf.inspect_captions
    # Old default sees only the canonical name in the collision case.
    assert inspector(data, snapshot, images, tables, templates.DEFAULT_STYLE)["coverage"] == (
        "complete" if attack == "collision" else "partial"
    )
    proof = inspector(data, snapshot, images, tables, templates.DEFAULT_STYLE, name_mapping=mapping)
    assert proof["coverage"] == ("complete" if attack is None else "partial"), proof
    if attack is None:
        assert proof["render_pixels"] > 0 and len(proof["captions"]) == 1
        assert (
            inspector(original, snapshot, images, tables, templates.DEFAULT_STYLE)["coverage"]
            == "complete"
        )


@pytest.mark.parametrize("attack", ["missing", "duplicate", "unknown"])
def test_source_bookmarks_must_match_expected_full_identities(attack):
    _, snapshot, _, roots = caption_cases.specimen()
    root = roots["word/document.xml"]
    bookmark = next(root.iter("{" + W + "}bookmarkStart"))
    if attack == "duplicate":
        root.append(deepcopy(bookmark))
    else:
        bookmark.set("{" + W + "}name", "unknown" if attack == "unknown" else "")
    with pytest.raises(ValueError, match="CAPTION_SOURCE_BOOKMARK_SET"):
        prebuilt_pdf._caption_name_mapping(
            {"snapshot": snapshot, "pagination": None, "roots": roots}
        )


def test_caption_alias_mapping_rejects_wrong_suffix_or_prefix():
    import pypdfium2 as pdfium

    data, _, _, _ = caption_cases.specimen()
    document = pdfium.PdfDocument(data)
    try:
        for mapping in [
            {"cap5F" + "1" * 32: "cap_" + "2" * 32},
            {"sec5F" + "1" * 32: "cap_" + "1" * 32},
        ]:
            with pytest.raises(ValueError, match="CAPTION_DESTINATION_MAPPING"):
                caption_cases.rich_caption_pdf._destinations(document, name_mapping=mapping)
    finally:
        document.close()


def cap_pdf(*, attack=None):
    output = io.BytesIO()
    drawing = canvas.Canvas(output, pagesize=(11906 / 20, 16838 / 20), invariant=1)
    left, bottom, right, top = 72, 680, 342, 720
    if attack == "width":
        right += 5
    extra = 0.3 if attack == "over_half" else 0.25
    drawing.setLineWidth(0.5)
    for y in [bottom, top]:
        drawing.line(left - extra, y, right + extra, y)
    for x in [left, right]:
        drawing.line(x, bottom - extra, x, top + extra)
    if attack in {"divider", "duplicate"}:
        x = left + 90 if attack == "divider" else left
        drawing.line(x, bottom, x, top)
    drawing.setFont("Helvetica", 10)
    drawing.drawString(
        right - 5 if attack == "text_outside" else left + 5,
        top - 18,
        "Cell1:12" if attack == "digit" else "Cell1:120",
    )
    if attack == "cover":
        # Image overlay leaves the four path objects intact: raster checks,
        # rather than merely the path-count guard, must reject hidden text.
        image = Image.new("RGB", (60, 14), "white")
        drawing.drawImage(ImageReader(image), left + 4, top - 21, width=60, height=14)
        image.close()
    drawing.showPage()
    drawing.save()
    return output.getvalue()


def cap_input():
    block = rich_cases.table(rich_cases.row(rich_cases.cell(3)))
    block["attrs"]["caption"] = ""
    block["content"][0]["content"][0]["content"] = [rich_cases.paragraph("Cell1:120")]
    snapshot, _, roots = table_cases.source([block])
    return snapshot, roots


def test_cap_model_keeps_old_default_and_runs_source_cell_raster_checks():
    snapshot, roots = cap_input()
    data = cap_pdf()
    original = rich_table_pdf.inspect_tables(data, snapshot, roots, table_cases.STYLE)
    measured = rich_table_pdf.inspect_tables(
        data, snapshot, roots, table_cases.STYLE, stroke_cap_model=prebuilt_pdf.STROKE_CAP_MODEL
    )
    assert original["coverage"] == "partial"
    assert measured["coverage"] == "complete", measured
    assert measured["render_pixels"] > 0 and measured["matched_tables"] == 1
    assert measured["tables"][0]["bbox"] == [72.0, 680.0, 342.0, 720.0]
    assert measured["tables"][0]["cells"][0]["colspan"] == 3


@pytest.mark.parametrize(
    "attack", ["width", "over_half", "divider", "duplicate", "text_outside", "digit", "cover"]
)
def test_cap_model_does_not_hide_extra_geometry_wrong_text_or_occlusion(attack):
    snapshot, roots = cap_input()
    value = rich_table_pdf.inspect_tables(
        cap_pdf(attack=attack),
        snapshot,
        roots,
        table_cases.STYLE,
        stroke_cap_model=prebuilt_pdf.STROKE_CAP_MODEL,
    )
    assert value["coverage"] == "partial"
    assert value["matched_tables"] == 0
    if attack == "cover":
        assert value["render_pixels"] > 0


def toc_input(monkeypatch, *, leader="dot"):
    style = deepcopy(templates.DEFAULT_STYLE)
    style.update({"header_text": "", "footer_text": "", "cover_enabled": False})
    document = ET.Element("{" + W + "}document")
    body = ET.SubElement(document, "{" + W + "}body")

    def paragraph(text):
        p = ET.SubElement(body, "{" + W + "}p")
        ET.SubElement(ET.SubElement(p, "{" + W + "}r"), "{" + W + "}t").text = text
        return p

    paragraph("TOC")
    row = ET.SubElement(body, "{" + W + "}p")
    props = ET.SubElement(row, "{" + W + "}pPr")
    tabs = ET.SubElement(props, "{" + W + "}tabs")
    ET.SubElement(
        tabs,
        "{" + W + "}tab",
        {
            "{" + W + "}val": "right",
            "{" + W + "}leader": leader,
            "{" + W + "}pos": str(
                11906 - style["margin_left_twips"] - style["margin_right_twips"] - 60
            ),
        },
    )
    link = ET.SubElement(row, "{" + W + "}hyperlink", {"{" + W + "}anchor": "sec_test"})
    ET.SubElement(ET.SubElement(link, "{" + W + "}r"), "{" + W + "}t").text = "Alpha"
    ET.SubElement(ET.SubElement(row, "{" + W + "}r"), "{" + W + "}t").text = "2"
    paragraph("Alpha")
    paragraph("Body 3.14 has 120 days")
    roots = {
        "word/document.xml": document,
        "word/numbering.xml": ET.Element("{" + W + "}numbering"),
    }
    entries = [
        {"node_id": "section", "anchor": "sec_test", "title": "Alpha", "expected_start_page": 2}
    ]
    monkeypatch.setattr(prebuilt_pdf.rich_docx, "navigation_entries", lambda *args: entries)
    prepared = {
        "config": style,
        "roots": roots,
        "body_roots": roots,
        "snapshot": {},
        "pagination": {},
    }
    nav = {
        "navigation_coverage": "complete",
        "entries": [{"node_id": "section", "start_page": 2, "toc_origin_page": 1}],
    }
    return prepared, nav


def toc_pdf(*, attack=None):
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(11906 / 20, 16838 / 20), invariant=1)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 760, "TOC")
    pdf.drawString(72, 720, "Alpha")
    if attack == "external_link":
        pdf.linkURL("https://invalid.example/no-request", (72, 718, 103, 735))
    elif attack != "no_link":
        pdf.linkRect("", "sec_test", (72, 718, 103, 735), relative=0, thickness=0)
    if attack == "white_dots":
        pdf.setFillColorRGB(1, 1, 1)
    pdf.drawString(105, 720, "." * 122)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.drawRightString(11906 / 20 - 1440 / 20 - 3, 720, "3" if attack == "wrong_number" else "2")
    if attack == "cover_dots":
        image = Image.new("RGB", (410, 15), "white")
        pdf.drawImage(ImageReader(image), 104, 717, width=410, height=15)
        image.close()
    pdf.drawString(72, 40, "1")
    pdf.showPage()
    pdf.bookmarkPage("sec_test", fit="XYZ", left=72, top=750, zoom=0)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 750, "Alpha")
    text = (
        "Body 3..14 has 120 days"
        if attack == "body_dot"
        else "Body 3.14 has 12 days"
        if attack == "body_digit"
        else "Body 3.14 has 120 days"
    )
    pdf.drawString(72, 720, text)
    pdf.drawString(72, 40, "2")
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def test_only_frozen_visible_linked_toc_decoration_is_removed(monkeypatch):
    prepared, nav = toc_input(monkeypatch)
    result = prebuilt_pdf.inspect_leaders(toc_pdf(), prepared, nav)
    assert result["coverage"] == "complete", result
    assert result["removed_dot_count"] == 122
    assert result["actual_body_digest"] == result["expected_body_digest"]
    assert result["raw_body_digest"] != result["actual_body_digest"]
    assert result["render_pixels"] > 0


@pytest.mark.parametrize(
    "attack",
    [
        "wrong_number",
        "body_dot",
        "body_digit",
        "no_link",
        "external_link",
        "white_dots",
        "cover_dots",
        "not_frozen",
    ],
)
def test_toc_adapter_cannot_hide_numbers_other_dots_missing_links_or_invisible_ink(
    monkeypatch, attack
):
    prepared, nav = toc_input(monkeypatch, leader="none" if attack == "not_frozen" else "dot")
    result = prebuilt_pdf.inspect_leaders(toc_pdf(attack=attack), prepared, nav)
    assert result["coverage"] == "partial"
    assert result["gaps"] == ["AUTHORING_TOC_DECORATION_UNVERIFIED"]
