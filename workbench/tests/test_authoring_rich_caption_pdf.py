"""Synthetic native PDF objects/named destinations, never a converter result."""

import io
from uuid import uuid4

import pytest
import test_authoring_generated as generated_cases
import test_authoring_rich as rich_cases
import test_authoring_rich_renderer as renderer_cases
from PIL import Image

from packages.authoring import (
    rich_caption_pdf,
    rich_captions,
    rich_docx,
    rich_images,
    rich_pdf,
    rich_renderer,
    rich_table_pdf,
    rich_verification,
    templates,
)


def specimen(*, kind="image", count=1, attack=None, multiline=False, navigation=False):
    snapshot = generated_cases.snapshot.__wrapped__()
    if navigation:
        snapshot["sections"][0]["attrs"]["title"] = "Alpha"
    blocks, materials = [], []
    for index in range(count):
        block_kind = kind[index] if isinstance(kind, tuple) else kind
        if block_kind == "table":
            block = rich_cases.table(
                rich_cases.row(rich_cases.cell(), rich_cases.cell(), rich_cases.cell())
            )
            for cell in block["content"][0]["content"]:
                cell["content"] = [rich_cases.paragraph(str(120 + index))]
        else:
            raw = io.BytesIO()
            with Image.new("RGB", (40, 30), "red") as pixels:
                pixels.save(raw, format="PNG")
            normalized = rich_images.normalize(raw.getvalue(), "image/png")
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
            block = {
                "type": "image",
                "attrs": {
                    "id": uuid4().hex,
                    "asset_id": asset,
                    "asset_revision": 1,
                    "asset_version_id": version,
                    "width_twips": 2400,
                    "height_twips": 1800,
                    "alt": "synthetic",
                    "caption": "",
                },
            }
        block["attrs"]["caption"] = "Figure 120"
        blocks.append(block)
    snapshot["sections"][0]["content"] = blocks
    source = rich_docx.assemble(snapshot, materials)
    roots = rich_verification.verify_container(source, materials, page_number=True)
    entries = rich_captions.entries(snapshot)
    objects = [b"", b""]

    def add(data):
        objects.append(data.encode() if isinstance(data, str) else data)
        return len(objects)

    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pixels = b"\xff\x00\x00" * 40 * 30
    image = add(
        b"<< /Type /XObject /Subtype /Image /Width 40 /Height 30 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length "
        + str(len(pixels)).encode()
        + b" >>\nstream\n"
        + pixels
        + b"\nendstream"
    )
    pages = [add(b""), add(b"")]
    streams = [[], []]
    names = []
    annots = []
    body_page = 1 if navigation and attack != "on_toc" else 0
    if navigation:
        nav = rich_docx.navigation_entries(snapshot)[0]
        names.append(f"({nav['anchor']}) [{pages[1]} 0 R /XYZ 72 770 0]")
        streams[0].extend(
            [f"BT /F1 12 Tf 72 750 Td ({nav['title']}) Tj ET", "BT /F1 12 Tf 400 750 Td (2) Tj ET"]
        )
        streams[1].append(f"BT /F1 18 Tf 72 750 Td ({nav['title']}) Tj ET")
        annots.append(
            add(
                f"<< /Type /Annot /Subtype /Link /Rect [72 744 330 762] /Border [0 0 0] /Dest [{pages[1]} 0 R /XYZ 72 770 0] >>"
            )
        )
    for index, entry in enumerate(entries):
        block_kind = blocks[index]["type"]
        position = count - index - 1 if attack == "mixed_swap" else index
        top = 700 if attack == "mixed_parallel" else 700 - position * 220
        left = 240 if attack == "mixed_parallel" and block_kind == "table" else 72
        bottom = top - (90 if block_kind == "image" else 40)
        if block_kind == "image":
            streams[body_page].append(f"q 120 0 0 90 72 {bottom} cm /Im Do Q")
        else:
            streams[body_page].extend(
                [
                    f"0 G 0.5 w {left} {bottom} m {left + 270} {bottom} l S",
                    f"{left} {top} m {left + 270} {top} l S",
                ]
            )
            for x in [left, left + 90, left + 180, left + 270]:
                streams[body_page].append(f"{x} {bottom} m {x} {top} l S")
            for x in [left + 5, left + 95, left + 185]:
                streams[body_page].append(f"BT /F1 10 Tf {x} {top - 18} Td ({120 + index}) Tj ET")
        baseline = bottom - (80 if attack == "far" else 20)
        if attack == "above":
            baseline = top + 20
        page = 1 if attack == "other_page" else body_page
        text = "Figure 12" if attack == "digit" else "Figure 120"
        commands = (
            [("Figure", baseline), ("120", baseline - 16)] if multiline else [(text, baseline)]
        )
        for label, y in commands:
            color = "1 g" if attack == "white" else "0 g"
            mode = "3 Tr" if attack == "hidden" else "0 Tr"
            streams[page].append(f"BT {color} {mode} /F1 12 Tf {left} {y} Td ({label}) Tj ET")
        if attack in {"cover", "black_cover"}:
            color = "1" if attack == "cover" else "0"
            streams[page].append(f"{color} g 72 {baseline - 3} 80 16 re f")
        if attack == "intervening":
            streams[page].append(f"BT 0 g /F1 5 Tf 72 {bottom - 5} Td (other) Tj ET")
        name = entries[1 - index]["anchor"] if attack == "swap" else entry["anchor"]
        target = baseline + (200 if attack == "wrong_dest" else 12)
        if attack != "missing":
            names.append(f"({name}) [{pages[page]} 0 R /XYZ 72 {target} 0]")
        if attack == "duplicate":
            names.append(f"({name}) [{pages[page]} 0 R /XYZ 72 {target} 0]")
    for index in range(2):
        stream = "\n".join(streams[index]).encode()
        content = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        annotations = " ".join(f"{value} 0 R" for value in annots) if index == 0 else ""
        objects[pages[index] - 1] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font} 0 R >> /XObject << /Im {image} 0 R >> >> /Contents {content} 0 R /Annots [{annotations}] >>".encode()
        )
    objects[0] = (
        "<< /Type /Catalog /Pages 2 0 R /Names << /Dests << /Names ["
        + " ".join(sorted(names))
        + "] >> >> >>"
    ).encode()
    objects[1] = (
        "<< /Type /Pages /Count 2 /Kids [" + " ".join(f"{p} 0 R" for p in pages) + "] >>"
    ).encode()
    data, offsets = bytearray(b"%PDF-1.7\n"), [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data), snapshot, materials, roots


def inspect(**options):
    data, snapshot, materials, roots = specimen(**options)
    images = rich_pdf.inspect_images(data, snapshot, materials, templates.DEFAULT_STYLE)
    tables = rich_table_pdf.inspect_tables(data, snapshot, roots, templates.DEFAULT_STYLE)
    assert images["coverage"] == tables["coverage"] == "complete", (images, tables)
    return rich_caption_pdf.inspect_captions(
        data, snapshot, images, tables, templates.DEFAULT_STYLE
    )


@pytest.mark.parametrize("kind", ["image", "table"])
@pytest.mark.parametrize("count,multiline", [(1, False), (2, False), (1, True)])
def test_actual_anchors_disambiguate_repeated_and_multiline_captions(kind, count, multiline):
    proof = inspect(kind=kind, count=count, multiline=multiline)
    assert proof["coverage"] == "complete", proof
    assert len(proof["captions"]) == count
    assert all("text" not in item for item in proof["captions"])


@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "duplicate",
        "digit",
        "white",
        "hidden",
        "cover",
        "black_cover",
        "far",
        "above",
        "other_page",
        "wrong_dest",
        "intervening",
    ],
)
def test_caption_defects_never_inherit_correct_object_pixels(attack):
    assert inspect(attack=attack)["coverage"] == "partial"


def test_swapped_anchors_cannot_rebind_identical_labels():
    assert inspect(count=2, attack="swap")["coverage"] == "partial"


@pytest.mark.parametrize("limit", ["MAX_NAMES", "MAX_WORK", "MAX_PIXELS"])
def test_caption_limits_keep_partial(monkeypatch, limit):
    monkeypatch.setattr(rich_caption_pdf, limit, 0)
    assert inspect()["coverage"] == "partial"


def test_combined_inspector_keeps_unrelated_body_navigation_gaps():
    data, snapshot, materials, _ = specimen(kind="table")
    _, _, profile, _, _ = renderer_cases.rich_input.__wrapped__()
    source = rich_docx.assemble(snapshot, materials)
    manifest = rich_verification.manifest(source, snapshot, materials)
    prepared = rich_renderer.prepare(source, snapshot, materials, manifest, profile)
    proof = rich_renderer.inspect_pdf(data, prepared)
    assert proof["caption_correspondence"]["coverage"] == "complete"
    assert "AUTHORING_CAPTION_PDF_UNVERIFIED" not in proof["gaps"]
    assert "AUTHORING_COMPLETE_BODY_TEXT_UNVERIFIED" in proof["gaps"]
