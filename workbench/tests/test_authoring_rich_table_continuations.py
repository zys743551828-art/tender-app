"""Synthetic real PDF pages; no Word converter or production qualification."""

import copy
import io

import pypdfium2 as pdfium
import pytest
import test_authoring_rich as rich_cases
import test_authoring_rich_table_pdf as cases
from PIL import Image
from reportlab.pdfgen import canvas

from packages.authoring import rich_content, rich_layout, rich_table_pdf


def table(rows=4, header=False):
    value = rich_cases.table(
        *[
            rich_cases.row(rich_cases.cell(), rich_cases.cell(), rich_cases.cell())
            for _ in range(rows)
        ]
    )
    value["attrs"]["caption"] = ""
    for origin in rich_content.table_grid(value)["origins"]:
        origin["cell"]["content"] = [
            rich_cases.paragraph(f"R{origin['row']}C{origin['column']}:120")
        ]
        origin["cell"]["attrs"]["header"] = header and origin["row"] == 0
    return value


def pages(block, *, split=2, attack=None):
    first, last = copy.deepcopy(block), copy.deepcopy(block)
    first["content"], last["content"] = first["content"][:split], last["content"][split:]
    if attack == "repeat_header":
        last["content"].insert(0, copy.deepcopy(block["content"][0]))
    if attack == "missing":
        last["content"].pop()
    if attack == "row_swap":
        last["content"].reverse()
    if attack == "duplicate_row":
        last["content"][1] = copy.deepcopy(last["content"][0])
    prefix = cases.pdf(first, top=72 + 40 * split if attack != "middle" else 600)
    suffix = cases.pdf(
        last,
        top=16838 / 20 - 72,
        left=90 if attack == "shift" else 72,
        attack="white_cover" if attack == "covered" else None,
    )
    if attack in {"detached_header", "leading_image", "padding"}:
        buffer = io.BytesIO()
        output = canvas.Canvas(buffer, pagesize=(11906 / 20, 16838 / 20), invariant=1)

        def draw_rows(rows, top):
            for r, row in enumerate(rows):
                for col, cell in enumerate(row["content"]):
                    left, bottom = 72 + 90 * col, top - 40 * (r + 1)
                    output.setFillColorRGB(231 / 255, 230 / 255, 230 / 255) if cell["attrs"][
                        "header"
                    ] else output.setFillColorRGB(1, 1, 1)
                    output.rect(left, bottom, 90, 40, stroke=0, fill=1)
                    output.setStrokeColorRGB(0, 0, 0)
                    output.setLineWidth(0.5)
                    output.rect(left, bottom, 90, 40, stroke=1, fill=0)
                    output.setFillColorRGB(0, 0, 0)
                    output.setFont("Helvetica", 10)
                    output.drawString(
                        left + 5, bottom + 22, cell["content"][0]["content"][0]["text"]
                    )

        draw_rows(last["content"], 720)
        if attack == "detached_header":
            draw_rows(block["content"][:1], 770)
        if attack == "leading_image":
            with Image.new("RGB", (20, 20), "black") as image:
                output.drawInlineImage(image, 72, 744, 20, 20)
        output.showPage()
        output.save()
        suffix = buffer.getvalue()
    parts = [prefix, suffix]
    if attack == "page_swap":
        parts.reverse()
    if attack == "gap":
        blank = pdfium.PdfDocument.new()
        page = blank.new_page(11906 / 20, 16838 / 20)
        page.close()
        buffer = io.BytesIO()
        blank.save(buffer)
        blank.close()
        parts.insert(1, buffer.getvalue())
    if attack == "duplicate_fragment":
        parts.append(suffix)
    document = pdfium.PdfDocument.new()
    try:
        for part in parts:
            source = pdfium.PdfDocument(part)
            try:
                document.import_pages(source)
            finally:
                source.close()
        result = io.BytesIO()
        document.save(result)
        return result.getvalue()
    finally:
        document.close()


@pytest.mark.parametrize("header,split", [(False, 1), (False, 2), (True, 2), (True, 3)])
def test_two_page_exact_contiguous_rows_preserve_cell_identity(header, split):
    block = table(header=header)
    snapshot, _, roots = cases.source([block])
    proof = rich_table_pdf.inspect_tables(pages(block, split=split), snapshot, roots, cases.STYLE)
    assert proof["coverage"] == "complete", proof
    matched = proof["tables"][0]
    assert [part["physical_page"] for part in matched["fragments"]] == [1, 2]
    assert [part["source_rows"] for part in matched["fragments"]] == [[0, split], [split, 4]]
    assert [(cell["row"], cell["column"]) for cell in matched["cells"]] == [
        (r, c) for r in range(4) for c in range(3)
    ]
    assert len({cell["node_id"] for cell in matched["cells"]}) == 12


@pytest.mark.parametrize(
    "attack",
    [
        "repeat_header",
        "missing",
        "row_swap",
        "duplicate_row",
        "page_swap",
        "gap",
        "shift",
        "covered",
        "middle",
        "duplicate_fragment",
        "detached_header",
        "leading_image",
    ],
)
def test_unsupported_or_corrupted_continuations_stay_partial(attack):
    block = table(header=True)
    snapshot, _, roots = cases.source([block])
    proof = rich_table_pdf.inspect_tables(pages(block, attack=attack), snapshot, roots, cases.STYLE)
    assert proof["coverage"] == "partial", (attack, proof)
    assert proof["matched_tables"] == 0


def test_identical_source_rows_do_not_invent_row_identity():
    block = table()
    for row in block["content"]:
        for cell in row["content"]:
            cell["content"] = [rich_cases.paragraph("same")]
    snapshot, _, roots = cases.source([block])
    proof = rich_table_pdf.inspect_tables(pages(block), snapshot, roots, cases.STYLE)
    assert proof["coverage"] == "partial"


def test_every_fragment_must_belong_to_its_frozen_section():
    block = table()
    snapshot, _, roots = cases.source([block])
    tables = rich_table_pdf.inspect_tables(pages(block), snapshot, roots, cases.STYLE)
    assert tables["coverage"] == "complete"
    # Explicit synthetic navigation proof isolates the section-range consumer.
    # This does not claim real named-destination or Word pagination acceptance.
    nodes = snapshot["authoring_structure"]["nodes"]
    navigation = {
        "mode": "chapter_start_new_page",
        "navigation_coverage": "complete",
        "page_count": 2,
        "entries": [
            {
                "node_id": node["section_id"],
                "start_page": 1 if i == 0 else 2,
                "title_bbox": [72, 780, 200, 800],
            }
            for i, node in enumerate(nodes)
        ],
    }
    images = {"coverage": "complete", "images": []}
    if len(nodes) == 1:
        navigation["page_count"] = 1
    proof = rich_layout.inspect_layout(snapshot, images, tables, navigation)
    assert "AUTHORING_RICH_OBJECT_SECTION_UNVERIFIED" in proof["gaps"]


def test_blank_continuation_padding_is_allowed_within_the_bound():
    block = table(header=True)
    snapshot, _, roots = cases.source([block])
    proof = rich_table_pdf.inspect_tables(
        pages(block, attack="padding"), snapshot, roots, cases.STYLE
    )
    assert proof["coverage"] == "complete", proof
