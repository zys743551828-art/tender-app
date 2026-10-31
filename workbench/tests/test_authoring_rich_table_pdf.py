"""Real synthetic PDF bytes test the inspector, not LibreOffice/M1 qualification."""

import copy
import io
import json
from pathlib import Path
from xml.etree import ElementTree as ET  # nosec B405 - constructs trusted test XML only

import pypdfium2 as pdfium
import pytest
import test_authoring_generated as generated_cases
import test_authoring_rich as rich_cases
from reportlab.pdfgen import canvas

from packages.authoring import (
    rich_content,
    rich_docx,
    rich_renderer,
    rich_table_pdf,
    rich_verification,
)
from packages.domain.runtime import sha

STYLE = {
    "margin_top_twips": 1440,
    "margin_bottom_twips": 1440,
    "margin_left_twips": 1440,
    "margin_right_twips": 1440,
}


@pytest.fixture(autouse=True)
def no_converter(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Table PDF mechanism tests do not invoke a converter")

    monkeypatch.setattr(rich_renderer.sandbox, "_docker", forbidden)


def table(*, merged=False, header=False):
    if merged:
        result = rich_cases.table(
            rich_cases.row(rich_cases.cell(2, 2), rich_cases.cell()),
            rich_cases.row(rich_cases.cell()),
            rich_cases.row(rich_cases.cell(3)),
        )
    else:
        result = rich_cases.table(
            rich_cases.row(rich_cases.cell(), rich_cases.cell(), rich_cases.cell()),
            rich_cases.row(rich_cases.cell(), rich_cases.cell(), rich_cases.cell()),
        )
    result["attrs"]["caption"] = ""
    for index, origin in enumerate(rich_content.table_grid(result)["origins"]):
        cell = origin["cell"]
        cell["content"] = [rich_cases.paragraph(f"Cell{index + 1}:120")]
        cell["attrs"]["header"] = header and origin["row"] == 0
    return result


def source(blocks):
    snapshot = generated_cases.snapshot.__wrapped__()
    snapshot["sections"][0]["content"] = blocks
    source = rich_docx.assemble(snapshot, [])
    roots = rich_verification.verify_container(source, [], page_number=True)
    return snapshot, source, roots


def pdf(
    block,
    *,
    attack=None,
    top=720,
    left=72,
    duplicate=False,
    filled=False,
    border_rgb=(0, 0, 0),
    border_width=0.5,
    header_rgb=(231, 230, 230),
    cap_grid=False,
    width_scale=1,
):
    """Draw an explicit synthetic table independently from the inspector."""
    buffer = io.BytesIO()
    output = canvas.Canvas(buffer, pagesize=(11906 / 20, 16838 / 20), invariant=1)

    def draw(top):
        checked = rich_content.table_grid(block)
        widths = [value / 20 * width_scale for value in checked["column_widths_twips"]]
        if attack == "column_width":
            widths[0] += 12
            widths[1] -= 12
        columns = [left]
        for width in widths:
            columns.append(columns[-1] + width)
        rows = [top - index * 40 for index in range(len(checked["grid"]) + 1)]
        borders = set()
        for index, origin in enumerate(checked["origins"]):
            attrs = origin["cell"]["attrs"]
            row, col = origin["row"], origin["column"]
            x0, x1 = columns[col], columns[col + attrs["colspan"]]
            y1, y0 = rows[row], rows[row + attrs["rowspan"]]
            if attrs["header"]:
                output.setFillColorRGB(*(channel / 255 for channel in header_rgb))
                output.rect(x0, y0, x1 - x0, y1 - y0, stroke=0, fill=1)
            borders.update([(x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)])
            text = origin["cell"]["content"][0]["content"][0]["text"]
            if attack == "digit" and index == 0:
                text = text.replace("120", "12")
            if attack == "cell_swap" and index < 2:
                text = f"Cell{2 - index}:120"
            x = x0 + 5 if not (attack == "cross_border" and index == 0) else x1 - 10
            output.setFillColorRGB(1, 1, 1) if attack == "white_text" else output.setFillColorRGB(
                0, 0, 0
            )
            output.setFont("Helvetica", 10)
            output.saveState()
            if attack == "clipped_text" and index == 0:
                clipping = output.beginPath()
                clipping.rect(x, y1 - 20, 10, 20)
                output.clipPath(clipping, stroke=0)
            textobject = output.beginText(x, y1 - 18)
            if attack == "hidden_text":
                textobject.setTextRenderMode(3)
            textobject.textOut(text)
            output.drawText(textobject)
            output.restoreState()
        if attack == "extra_text":
            output.setFillColorRGB(0, 0, 0)
            output.drawString(left + 60, top - 30, "EXTRA")
        output.setStrokeColorRGB(*(channel / 255 for channel in border_rgb))
        output.setFillColorRGB(*(channel / 255 for channel in border_rgb))
        output.setLineWidth(border_width)
        if attack == "dashed":
            output.setDash(2, 2)
        if cap_grid:
            half = border_width / 2
            borders = {
                (
                    columns[0] + (-half if y in {rows[0], rows[-1]} else half),
                    y,
                    columns[-1] + (half if y in {rows[0], rows[-1]} else -half),
                    y,
                )
                for y in rows
            } | {
                (
                    x,
                    rows[-1] + (-half if x in {columns[0], columns[-1]} else half),
                    x,
                    rows[0] + (half if x in {columns[0], columns[-1]} else -half),
                )
                for x in columns
            }
        for x0, y0, x1, y1 in sorted(borders):
            if attack == "missing_vertical" and x0 == x1 == columns[1]:
                continue
            if attack == "missing_horizontal" and y0 == y1 == rows[1]:
                continue
            if attack == "cap_split" and y0 == y1 == rows[0]:
                middle = (x0 + x1) / 2
                output.line(x0, y0, middle, y1)
                output.line(middle, y0, x1, y1)
                continue
            if attack == "cap_cross" and x0 == x1 == columns[1]:
                output.line(x0 + 5, y0, x1, y1)
                continue
            if filled:
                if x0 == x1:
                    output.rect(x0 - 0.25, y0, 0.5, y1 - y0, fill=1, stroke=0)
                else:
                    output.rect(x0, y0 - 0.25, x1 - x0, 0.5, fill=1, stroke=0)
            else:
                output.line(x0, y0, x1, y1)
        if attack == "extra_merged_divider":
            output.line(columns[1], rows[2], columns[1], rows[0])
        if attack == "covered_border":
            output.setFillColorRGB(1, 1, 1)
            output.rect(columns[1] - 1, rows[-1] + 10, 2, 15, fill=1, stroke=0)
        if attack == "black_border_cover":
            output.setFillColorRGB(0, 0, 0)
            output.rect(columns[1] - 0.25, rows[-1], 0.5, top - rows[-1], fill=1, stroke=0)
        if attack in {"white_cover", "black_cover", "sparse_cover"}:
            white = attack != "black_cover"
            output.setFillColorRGB(1 if white else 0, 1 if white else 0, 1 if white else 0)
            output.rect(
                left + 6, top - 20, 48 if attack != "sparse_cover" else 1, 11, fill=1, stroke=0
            )
        if attack == "unexpected_background":
            output.setFillColorRGB(0.8, 0.8, 0.8)
            output.rect(left + 55, top - 32, 15, 10, fill=1, stroke=0)

    draw(top)
    if duplicate:
        draw(top - 200)
    output.showPage()
    output.save()
    return buffer.getvalue()


@pytest.mark.parametrize(
    "merged,header,filled",
    [(False, False, False), (False, True, False), (True, False, False), (True, True, True)],
)
def test_actual_grid_spans_cell_text_and_pixels_are_measured(merged, header, filled):
    block = table(merged=merged, header=header)
    snapshot, _, roots = source([block])
    data = pdf(block, filled=filled)
    result = rich_table_pdf.inspect_tables(data, snapshot, roots, STYLE)
    assert result["coverage"] == "complete", result
    assert result["expected_tables"] == result["matched_tables"] == 1
    assert result["pdf_digest"] == sha(data)
    row = result["tables"][0]
    assert row["node_id"] == block["attrs"]["id"]
    assert row["physical_page"] == 1 and row["bbox"] == [72, 600 if merged else 640, 342, 720]
    assert len(row["cells"]) == (4 if merged else 6)
    assert result["render_pixels"] > 0
    assert "Cell1" not in json.dumps(result)


SOURCE_BORDER = (100, 116, 139)
SOURCE_HEADER = (226, 232, 240)
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def colored_source(block):
    snapshot, _, roots = source([block])
    table_xml = next(roots["word/document.xml"].iter(WORD + "tbl"))
    props = table_xml.find(WORD + "tblPr")
    assert props is not None
    for old in props.findall(WORD + "tblBorders"):
        props.remove(old)
    borders = ET.SubElement(props, WORD + "tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        ET.SubElement(
            borders,
            WORD + edge,
            {WORD + "val": "single", WORD + "sz": "4", WORD + "color": "64748B"},
        )
    cells = list(table_xml.iter(WORD + "tc"))
    origins = rich_content.table_grid(block)["origins"]
    assert len(cells) == len(origins)
    for cell, origin in zip(cells, origins, strict=True):
        cell_props = cell.find(WORD + "tcPr")
        assert cell_props is not None
        for old in list(cell_props):
            if old.tag in {WORD + "shd", WORD + "tcBorders"}:
                cell_props.remove(old)
        if origin["cell"]["attrs"]["header"]:
            ET.SubElement(cell_props, WORD + "shd", {WORD + "fill": "E2E8F0"})
    return snapshot, roots


@pytest.mark.parametrize("cap_grid", [False, True])
def test_source_visuals_measure_actual_ooxml_colors_without_changing_default(cap_grid):
    block = table(header=True)
    snapshot, roots = colored_source(block)
    data = pdf(block, border_rgb=SOURCE_BORDER, header_rgb=SOURCE_HEADER, cap_grid=cap_grid)
    default = rich_table_pdf.inspect_tables(data, snapshot, roots, STYLE)
    assert default["coverage"] == "partial"
    result = rich_table_pdf.inspect_tables(data, snapshot, roots, STYLE, source_visuals=True)
    assert result["coverage"] == "complete", result
    assert result["expected_tables"] == result["matched_tables"] == 1
    expected = rich_table_pdf._expected(snapshot, roots, source_visuals=True)[0]
    assert expected["source_visual"] == {"border_rgb": SOURCE_BORDER, "border_width_pt": 0.5}
    assert expected["cells"][0]["source_fill"] == (*SOURCE_HEADER, 255)


@pytest.mark.parametrize(
    "attack",
    [
        "wrong_color",
        "wrong_fill",
        "wrong_width",
        "missing_vertical",
        "hidden_text",
        "white_cover",
        "covered_border",
        "black_border_cover",
        "extra_text",
        "cell_swap",
        "digit",
    ],
)
def test_source_visual_defects_cannot_pass(attack):
    block = table(header=True)
    snapshot, roots = colored_source(block)
    data = pdf(
        block,
        border_rgb=(0, 0, 0) if attack == "wrong_color" else SOURCE_BORDER,
        header_rgb=(231, 230, 230) if attack == "wrong_fill" else SOURCE_HEADER,
        border_width=1 if attack == "wrong_width" else 0.5,
        attack=attack,
    )
    result = rich_table_pdf.inspect_tables(data, snapshot, roots, STYLE, source_visuals=True)
    assert result["coverage"] == "partial", (attack, result)


@pytest.mark.parametrize(
    "attack",
    ["missing_vertical", "missing_horizontal", "cap_split", "cap_cross", "cell_swap", "extra_text"],
)
def test_source_cap_grid_does_not_invent_edges_or_cell_correspondence(attack):
    block = table(header=True)
    snapshot, roots = colored_source(block)
    result = rich_table_pdf.inspect_tables(
        pdf(
            block, border_rgb=SOURCE_BORDER, header_rgb=SOURCE_HEADER, cap_grid=True, attack=attack
        ),
        snapshot,
        roots,
        STYLE,
        source_visuals=True,
    )
    assert result["coverage"] == "partial", (attack, result)


@pytest.mark.parametrize("width_scale", [1, 0.5])
def test_source_cap_multiple_wrong_grids_cannot_be_combined_or_reused(width_scale):
    block = table(header=True)
    snapshot, roots = colored_source(block)
    result = rich_table_pdf.inspect_tables(
        pdf(
            block,
            border_rgb=SOURCE_BORDER,
            header_rgb=SOURCE_HEADER,
            cap_grid=True,
            duplicate=True,
            width_scale=width_scale,
        ),
        snapshot,
        roots,
        STYLE,
        source_visuals=True,
    )
    assert result["coverage"] == "partial", result


@pytest.mark.parametrize("change", ["theme", "mixed_border", "invisible", "pattern", "style"])
def test_unproven_source_visuals_are_not_expected_color_overrides(change):
    block = table(header=True)
    snapshot, roots = colored_source(block)
    table_xml = next(roots["word/document.xml"].iter(WORD + "tbl"))
    props = table_xml.find(WORD + "tblPr")
    assert props is not None
    borders = props.find(WORD + "tblBorders")
    assert borders is not None
    if change == "theme":
        borders[0].set(WORD + "themeColor", "accent1")
    elif change == "mixed_border":
        borders[0].set(WORD + "color", "000000")
    elif change == "invisible":
        for edge in borders:
            edge.set(WORD + "color", "FFFFFF")
    elif change == "pattern":
        next(table_xml.iter(WORD + "shd")).set(WORD + "val", "pct50")
    else:
        ET.SubElement(props, WORD + "tblStyle", {WORD + "val": "unknown-inherited"})
    result = rich_table_pdf.inspect_tables(
        pdf(block, border_rgb=SOURCE_BORDER, header_rgb=SOURCE_HEADER),
        snapshot,
        roots,
        STYLE,
        source_visuals=True,
    )
    assert result["gaps"] == ["AUTHORING_TABLE_SOURCE_UNVERIFIED"]


def test_source_visual_mode_cannot_be_an_arbitrary_expected_color_dict():
    block = table()
    snapshot, _, roots = source([block])
    result = rich_table_pdf.inspect_tables(
        pdf(block), snapshot, roots, STYLE, source_visuals={"border_rgb": (0, 0, 0)}
    )
    assert result["gaps"] == ["AUTHORING_TABLE_SOURCE_UNVERIFIED"]


@pytest.mark.parametrize(
    "attack",
    [
        "digit",
        "cell_swap",
        "cross_border",
        "white_text",
        "hidden_text",
        "clipped_text",
        "missing_vertical",
        "missing_horizontal",
        "column_width",
        "dashed",
        "covered_border",
        "white_cover",
        "black_cover",
        "sparse_cover",
        "unexpected_background",
    ],
)
def test_real_pdf_defects_never_receive_complete(attack):
    block = table()
    snapshot, _, roots = source([block])
    result = rich_table_pdf.inspect_tables(pdf(block, attack=attack), snapshot, roots, STYLE)
    assert result["coverage"] == "partial", (attack, result)
    assert result["matched_tables"] == 0
    assert "AUTHORING_TABLE_PDF_GEOMETRY_UNVERIFIED" in result["gaps"]


def test_divider_through_merged_cell_is_not_a_valid_original_grid():
    block = table(merged=True)
    snapshot, _, roots = source([block])
    result = rich_table_pdf.inspect_tables(
        pdf(block, attack="extra_merged_divider"), snapshot, roots, STYLE
    )
    assert result["coverage"] == "partial" and result["matched_tables"] == 0


def test_table_outside_frozen_body_is_rejected():
    block = table()
    snapshot, _, roots = source([block])
    result = rich_table_pdf.inspect_tables(pdf(block, left=40), snapshot, roots, STYLE)
    assert result["coverage"] == "partial" and result["matched_tables"] == 0


def test_two_identical_occurrences_are_ambiguous():
    block = table()
    snapshot, _, roots = source([block])
    result = rich_table_pdf.inspect_tables(pdf(block, duplicate=True), snapshot, roots, STYLE)
    assert result["coverage"] == "partial" and result["matched_tables"] == 0
    assert "AUTHORING_TABLE_MATCH_AMBIGUOUS" in result["gaps"]


def test_one_pdf_table_cannot_satisfy_two_frozen_tables():
    first = table()
    second = table()
    snapshot, _, roots = source([first, second])
    result = rich_table_pdf.inspect_tables(pdf(first), snapshot, roots, STYLE)
    assert result["coverage"] == "partial"
    assert "AUTHORING_TABLE_ORDER_OR_REUSE_UNVERIFIED" in result["gaps"]


def test_unobservable_fully_merged_row_stays_partial():
    block = rich_cases.table(rich_cases.row(rich_cases.cell(3, 2)), rich_cases.row())
    block["content"][0]["content"][0]["content"] = [rich_cases.paragraph("Merged120")]
    snapshot, _, roots = source([block])
    result = rich_table_pdf.inspect_tables(pdf(block), snapshot, roots, STYLE)
    assert result["coverage"] == "partial"


def test_table_split_over_two_actual_pdf_pages_stays_partial():
    block = table()
    snapshot, _, roots = source([block])
    document = pdfium.PdfDocument.new()
    try:
        for row in block["content"]:
            part = copy.deepcopy(block)
            part["content"] = [row]
            page_source = pdfium.PdfDocument(pdf(part))
            try:
                document.import_pages(page_source)
            finally:
                page_source.close()
        buffer = io.BytesIO()
        document.save(buffer)
    finally:
        document.close()
    result = rich_table_pdf.inspect_tables(buffer.getvalue(), snapshot, roots, STYLE)
    assert result["coverage"] == "partial" and result["matched_tables"] == 0


@pytest.mark.parametrize(
    "constant,value",
    [
        ("MAX_CANDIDATES", 1),
        ("MAX_RENDER_PIXELS", 1),
        ("MAX_PAGE_OBJECTS", 1),
        ("MAX_PAGE_CHARS", 1),
        ("MAX_TOTAL_CHARS", 1),
        ("MAX_PAGE_SEGMENTS", 1),
        ("MAX_WORK_UNITS", 1),
    ],
)
def test_resource_limit_is_partial_not_success_or_silent_drop(monkeypatch, constant, value):
    block = table()
    snapshot, _, roots = source([block])
    monkeypatch.setattr(rich_table_pdf, constant, value)
    result = rich_table_pdf.inspect_tables(pdf(block), snapshot, roots, STYLE)
    assert result["coverage"] == "partial"
    assert "AUTHORING_TABLE_INSPECTION_INCOMPLETE" in result["gaps"]


def test_combined_work_budget_limits_geometry_and_cell_comparisons(monkeypatch):
    block = table()
    snapshot, _, roots = source([block])
    data = pdf(block)
    before = rich_table_pdf.inspect_tables(data, snapshot, roots, STYLE)
    assert before["coverage"] == "complete" and before["work_units"] > 300
    # Neither page objects, characters, segments nor candidate count is excessive.
    # Their combined work still has an independent deterministic upper bound.
    monkeypatch.setattr(rich_table_pdf, "MAX_WORK_UNITS", 300)
    result = rich_table_pdf.inspect_tables(data, snapshot, roots, STYLE)
    assert result["coverage"] == "partial" and result["work_units"] > 300
    assert result["render_pixels"] == 0
    assert "AUTHORING_TABLE_INSPECTION_INCOMPLETE" in result["gaps"]


def test_source_count_and_bad_pdf_do_not_pass():
    block = table()
    snapshot, _, roots = source([block])
    assert rich_table_pdf.inspect_tables(b"broken", snapshot, roots, STYLE)["coverage"] == "partial"
    missing = copy.deepcopy(snapshot)
    missing["sections"][0]["content"] = []
    assert rich_table_pdf.inspect_tables(pdf(block), missing, roots, STYLE)["gaps"] == [
        "AUTHORING_TABLE_SOURCE_UNVERIFIED"
    ]


def test_rich_inspection_uses_measured_table_proof_and_keeps_other_gaps():
    block = table()
    snapshot, docx, _ = source([block])
    base = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/authoring-rich-static-checks/word03-base-profile.json"
        ).read_text()
    )
    profile = rich_renderer.profile_for(base)
    manifest = rich_verification.manifest(docx, snapshot, [])
    prepared = rich_renderer.prepare(docx, snapshot, [], manifest, profile)
    result = rich_renderer.inspect_pdf(pdf(block), prepared)
    assert result["table_correspondence"]["coverage"] == "complete"
    assert "AUTHORING_TABLE_PDF_GEOMETRY_UNVERIFIED" not in result["gaps"]
    # This synthetic PDF has no real DOCX conversion, generated title, footer or TOC.
    assert result["gaps"] and "AUTHORING_COMPLETE_BODY_TEXT_UNVERIFIED" in result["gaps"]
    assert profile["identity"]["protocol"] == "authoring-rich-sandbox/7"
    assert profile["identity"]["table_inspector"] == rich_table_pdf.identity()


@pytest.mark.parametrize(
    "change", ["old_protocol", "previous_protocol", "missing_inspector", "foreign_build"]
)
def test_old_rich_or_changed_inspector_profile_requires_fresh_qualification(change):
    block = table()
    snapshot, docx, _ = source([block])
    base = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/authoring-rich-static-checks/word03-base-profile.json"
        ).read_text()
    )
    profile = rich_renderer.profile_for(base)
    if change == "old_protocol":
        profile["identity"]["protocol"] = "authoring-rich-sandbox/4"
    elif change == "previous_protocol":
        profile["identity"]["protocol"] = "authoring-rich-sandbox/6"
    elif change == "missing_inspector":
        del profile["identity"]["table_inspector"]
    else:
        profile["identity"]["table_inspector"]["pdfium_build"] = "foreign-build"
    profile["profile_digest"] = sha(profile["identity"])
    result = rich_renderer.render_once(
        docx, snapshot, [], rich_verification.manifest(docx, snapshot, []), profile
    )
    assert result["state"] == "failed" and result["error_code"] == "AUTHORING_RICH_PROFILE_CHANGED"
    assert result["conversion_attempted"] is False
