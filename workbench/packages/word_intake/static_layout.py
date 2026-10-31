"""Project admitted static OOXML into existing PDFium/RICH correspondence checks.

This is an inspector, not a renderer or an authoring import. It supports one
explicit page section, plain static stories, fixed native tables and inline
opaque rasters. Unknown source constructs keep their original layout gap.
"""

from __future__ import annotations

import io
import posixpath
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pypdfium2 as pdfium

from packages.authoring import (
    generated_renderer,
    rich_content,
    rich_images,
    rich_pdf,
    rich_table_pdf,
)
from packages.domain.runtime import DomainError, sha
from packages.word_intake.inspection import _xml

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
Q = "{" + W + "}"


def identity():
    return {
        "protocol": "word-static-correspondence/1",
        "source_digest": sha(Path(__file__).read_bytes()),
        "table_inspector": rich_table_pdf.identity(),
        "image_inspector_digest": sha(Path(rich_pdf.__file__).read_bytes()),
        "image_normalizer_digest": sha(Path(rich_images.__file__).read_bytes()),
        "table_schema_digest": rich_content.SCHEMA_DIGEST,
        "table_projection_digest": sha(Path(rich_content.__file__).read_bytes()),
        "body_projection_digest": sha(Path(generated_renderer.__file__).read_bytes()),
    }


def normalize(text):
    return "".join(unicodedata.normalize("NFKC", text).split())


def _text(element):
    return "".join(item.text or "" for item in element.iter(Q + "t"))


def _id(source_digest, key):
    return str(uuid5(NAMESPACE_URL, source_digest + ":" + key))


def _table(table, key):
    properties = table.find(Q + "tblPr")
    if (
        properties is None
        or (layout := properties.find(Q + "tblLayout")) is None
        or layout.get(Q + "type") != "fixed"
    ):
        raise ValueError("SOURCE_TABLE_LAYOUT_UNSUPPORTED")
    if (
        properties.find(Q + "tblpPr") is not None
        or (alignment := properties.find(Q + "jc")) is not None
        and alignment.get(Q + "val") != "left"
    ):
        raise ValueError("SOURCE_TABLE_POSITION_UNSUPPORTED")
    if (indent := properties.find(Q + "tblInd")) is not None and indent.get(Q + "w", "0") != "0":
        raise ValueError("SOURCE_TABLE_INDENT_UNSUPPORTED")
    widths = [int(n.attrib[Q + "w"]) for n in table.findall(Q + "tblGrid/" + Q + "gridCol")]
    rows = table.findall(Q + "tr")
    header = rows[0].find(Q + "trPr/" + Q + "tblHeader") if rows else None
    repeat = header is not None and header.get(Q + "val", "1") in {"1", "true", "on"}
    attrs = {"id": key, "column_widths_twips": widths, "caption": ""}
    if repeat:
        attrs["pagination"] = rich_content.SCHEMA["table_pagination"]
    result: dict[str, Any] = {"type": "table", "attrs": attrs, "content": []}
    for y, row in enumerate(rows):
        projected: dict[str, Any] = {
            "type": "tableRow",
            "attrs": {"id": f"{key}:r{y}"},
            "content": [],
        }
        for x, cell in enumerate(row.findall(Q + "tc")):
            if any(cell.find(Q + "tcPr/" + Q + n) is not None for n in ("gridSpan", "vMerge")):
                raise ValueError("SOURCE_TABLE_SPAN_UNSUPPORTED")
            if any(child.tag not in {Q + "tcPr", Q + "p"} for child in cell):
                raise ValueError("SOURCE_TABLE_CONTENT_UNSUPPORTED")
            paragraphs = [
                {"type": "paragraph", "content": [{"type": "text", "text": _text(p)}]}
                for p in cell.findall(Q + "p")
            ]
            projected["content"].append(
                {
                    "type": "tableCell",
                    "attrs": {
                        "id": f"{key}:r{y}c{x}",
                        "colspan": 1,
                        "rowspan": 1,
                        "header": repeat and y == 0,
                    },
                    "content": paragraphs,
                }
            )
        result["content"].append(projected)
    rich_content.table_grid(result)
    return result


def prepare(source: bytes):
    """Called only after bounded whole-package admission by the Worker."""
    try:
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            document = _xml(archive.read("word/document.xml"))
            if document.tag != Q + "document":
                return None
            sections = list(document.iter(Q + "sectPr"))
            if len(sections) != 1:
                return None
            section = sections[0]
            size, margins = section.find(Q + "pgSz"), section.find(Q + "pgMar")
            if size is None or margins is None or section.find(Q + "titlePg") is not None:
                return None
            if (columns := section.find(Q + "cols")) is not None and columns.get(
                Q + "num", "1"
            ) != "1":
                return None
            style = {
                "page_width_twips": int(size.attrib[Q + "w"]),
                "page_height_twips": int(size.attrib[Q + "h"]),
            }
            style.update(
                {
                    "margin_" + side + "_twips": int(margins.attrib[Q + side])
                    for side in ("top", "bottom", "left", "right")
                }
            )
            if (
                any(not 0 < v <= 30000 for v in style.values())
                or style["margin_top_twips"] + style["margin_bottom_twips"]
                >= style["page_height_twips"]
                or style["margin_left_twips"] + style["margin_right_twips"]
                >= style["page_width_twips"]
            ):
                return None
            relationships = _xml(archive.read("word/_rels/document.xml.rels"))
            relations = {item.attrib["Id"]: item for item in relationships}
            stories = {}
            for kind in ("header", "footer"):
                references = section.findall(Q + kind + "Reference")
                if len(references) > 1:
                    return None
                stories[kind] = ""
                if references:
                    ref = references[0]
                    relation = relations[ref.attrib["{" + R + "}id"]]
                    if (
                        ref.get(Q + "type") != "default"
                        or relation.get("TargetMode", "Internal") != "Internal"
                        or not relation.get("Type", "").endswith("/" + kind)
                    ):
                        return None
                    path = posixpath.normpath(posixpath.join("word", relation.attrib["Target"]))
                    story = _xml(archive.read(path))
                    if story.tag != Q + ("hdr" if kind == "header" else "ftr") or any(
                        n.tag != Q + "p" for n in story
                    ):
                        return None
                    if any(
                        n.tag.rsplit("}", 1)[-1]
                        in {
                            "drawing",
                            "pict",
                            "fldSimple",
                            "fldChar",
                            "instrText",
                            "vanish",
                            "webHidden",
                            "numPr",
                        }
                        for n in story.iter()
                    ):
                        return None
                    stories[kind] = _text(story)
            body = document.find(Q + "body")
            if body is None:
                return None
            unsupported = []
            if any(
                node.get(Q + "type", "textWrapping") not in {"page", "textWrapping"}
                for node in document.iter(Q + "br")
            ):
                unsupported.append("WORD_STATIC_SOURCE_CONSTRUCT_UNSUPPORTED")
            if any(
                n.tag.rsplit("}", 1)[-1]
                in {
                    "vanish",
                    "webHidden",
                    "numPr",
                    "anchor",
                    "srcRect",
                    "txbxContent",
                    "pgBorders",
                    "textDirection",
                    "framePr",
                    "pageBreakBefore",
                }
                for n in document.iter()
            ):
                unsupported.append("WORD_STATIC_SOURCE_CONSTRUCT_UNSUPPORTED")
            source_digest, blocks, materials = sha(source), [], []
            normalized_images, image_pixels, image_count = {}, 0, 0
            object_chunks, chunk = {}, 0
            object_text_ranges, text_offset = {}, 0
            roots = {
                "word/document.xml": document,
                "word/numbering.xml": _xml(archive.read("word/numbering.xml"))
                if "word/numbering.xml" in archive.namelist()
                else _xml(f'<w:numbering xmlns:w="{W}"/>'.encode()),
            }
            for name in ("word/styles.xml", "word/settings.xml"):
                if name in archive.namelist():
                    roots[name] = _xml(archive.read(name))
            for number, element in enumerate(body):
                key = _id(source_digest, f"block:{number}")
                if element.tag == Q + "tbl":
                    if any(n.get(Q + "type") == "page" for n in element.iter(Q + "br")):
                        raise ValueError("SOURCE_TABLE_INTERNAL_PAGE_BREAK_UNSUPPORTED")
                    blocks.append(_table(element, key))
                    object_chunks[key] = chunk
                    object_text_ranges[key] = [
                        text_offset,
                        text_offset + len(normalize(_text(element))),
                    ]
                    text_offset += len(normalize(_text(element)))
                elif element.tag == Q + "p":
                    drawings = list(element.iter(Q + "drawing"))
                    if not drawings:
                        text_offset += len(normalize(_text(element)))
                        chunk += sum(n.get(Q + "type") == "page" for n in element.iter(Q + "br"))
                        continue
                    if len(drawings) != 1 or _text(element).strip():
                        raise ValueError("SOURCE_INLINE_IMAGE_TEXT_UNSUPPORTED")
                    for properties in [
                        element.find(Q + "pPr"),
                        *roots.get(
                            "word/styles.xml", _xml(f'<w:styles xmlns:w="{W}"/>'.encode())
                        ).iter(Q + "pPr"),
                    ]:
                        if properties is None:
                            continue
                        if (align := properties.find(Q + "jc")) is not None and align.get(
                            Q + "val"
                        ) != "left":
                            raise ValueError("SOURCE_IMAGE_ALIGNMENT_UNSUPPORTED")
                        if (indent := properties.find(Q + "ind")) is not None and any(
                            value != "0" for value in indent.attrib.values()
                        ):
                            raise ValueError("SOURCE_IMAGE_INDENT_UNSUPPORTED")
                    inline = drawings[0].find("{" + WP + "}inline")
                    if inline is None or any(
                        n.tag.rsplit("}", 1)[-1] in {"anchor", "srcRect"} for n in inline.iter()
                    ):
                        raise ValueError("SOURCE_IMAGE_PLACEMENT_UNSUPPORTED")
                    extent, blip = (
                        inline.find("{" + WP + "}extent"),
                        inline.find(".//{" + A + "}blip"),
                    )
                    if extent is None or blip is None:
                        raise ValueError("SOURCE_IMAGE_UNDECLARED")
                    transform = inline.find(".//{" + A + "}xfrm")
                    if (
                        transform is None
                        or transform.get("rot", "0") != "0"
                        or any(
                            transform.get(key, "0") not in {"0", "false", "off"}
                            for key in ("flipH", "flipV")
                        )
                    ):
                        raise ValueError("SOURCE_IMAGE_TRANSFORM_UNSUPPORTED")
                    offset, transformed_extent = (
                        transform.find("{" + A + "}off"),
                        transform.find("{" + A + "}ext"),
                    )
                    if (
                        offset is None
                        or transformed_extent is None
                        or any(offset.get(key, "0") != "0" for key in ("x", "y"))
                        or any(
                            transformed_extent.get(key) != extent.get(key) for key in ("cx", "cy")
                        )
                    ):
                        raise ValueError("SOURCE_IMAGE_TRANSFORM_UNSUPPORTED")
                    geometry = inline.find(".//{" + A + "}prstGeom")
                    if (
                        len(blip)
                        or geometry is None
                        or geometry.get("prst") != "rect"
                        or any(len(node) for node in inline.iter("{" + A + "}effectLst"))
                    ):
                        raise ValueError("SOURCE_IMAGE_EFFECT_UNSUPPORTED")
                    relation = relations[blip.attrib["{" + R + "}embed"]]
                    if relation.get("TargetMode", "Internal") != "Internal" or not relation.get(
                        "Type", ""
                    ).endswith("/image"):
                        raise ValueError("SOURCE_IMAGE_RELATIONSHIP")
                    path = posixpath.normpath(posixpath.join("word", relation.attrib["Target"]))
                    if not path.lower().endswith(".png"):
                        raise ValueError("SOURCE_IMAGE_CODEC_UNSUPPORTED")
                    image_count += 1
                    if image_count > 500:
                        raise ValueError("SOURCE_IMAGE_COUNT_LIMIT")
                    if path not in normalized_images:
                        normalized = rich_images.normalize(archive.read(path), "image/png")
                        image_pixels += (
                            normalized["proof"]["width_px"] * normalized["proof"]["height_px"]
                        )
                        if image_pixels > 32_000_000:
                            raise ValueError("SOURCE_IMAGE_PIXEL_LIMIT")
                        normalized_images[path] = normalized
                    normalized = normalized_images[path]
                    version = _id(source_digest, path)
                    materials.append(
                        {
                            "asset_id": version,
                            "asset_version_id": version,
                            "asset_revision": 1,
                            "bytes": normalized["bytes"],
                            "normalization_proof": normalized["proof"],
                        }
                    )
                    blocks.append(
                        {
                            "type": "image",
                            "attrs": {
                                "id": key,
                                "asset_id": version,
                                "asset_version_id": version,
                                "asset_revision": 1,
                                "width_twips": int(extent.attrib["cx"]) / 635,
                                "height_twips": int(extent.attrib["cy"]) / 635,
                            },
                        }
                    )
                    before_drawing = 0
                    for node in element.iter():
                        if node is drawings[0]:
                            break
                        if node.tag == Q + "br" and node.get(Q + "type") == "page":
                            before_drawing += 1
                    object_chunks[key] = chunk + before_drawing
                    object_text_ranges[key] = [text_offset, text_offset]
                    chunk += sum(n.get(Q + "type") == "page" for n in element.iter(Q + "br"))
                elif element.tag != Q + "sectPr":
                    unsupported.append("WORD_STATIC_SOURCE_CONSTRUCT_UNSUPPORTED")
            pieces = []
            for node in body.iter():
                if node.tag == Q + "t":
                    pieces.append(node.text or "")
                elif node.tag == Q + "br" and node.get(Q + "type") == "page":
                    pieces.append("\f")
            return {
                "style": style,
                "stories": stories,
                "roots": roots,
                "snapshot": {"sections": [{"content": blocks}]},
                "materials": materials,
                "body_chunks": "".join(pieces).split("\f"),
                "unsupported": unsupported,
                "source_digest": source_digest,
                "object_chunks": object_chunks,
                "object_text_ranges": object_text_ranges,
            }
    except (KeyError, ValueError, TypeError, DomainError, zipfile.BadZipFile):
        return None


def _object_order(prepared, tables, images, end_pages, boundaries, page_count, positions=None):
    """Reuse the RICH source-order relation; also respect explicit source breaks."""
    if tables["coverage"] != "complete" or images["coverage"] != "complete":
        return False
    rows = {row.get("node_id"): row for row in [*tables["tables"], *images["images"]]}
    ordered = []
    for block in prepared["snapshot"]["sections"][0]["content"]:
        key = block["attrs"]["id"]
        if key not in rows:
            return False
        chunk = prepared["object_chunks"][key]
        lower, upper = 1, page_count
        if chunk:
            previous = end_pages.get(boundaries[chunk - 1], [])
            if len(previous) != 1:
                return False
            lower = previous[0] + 1
        if chunk < len(boundaries):
            following = end_pages.get(boundaries[chunk], [])
            if len(following) != 1:
                return False
            upper = following[0]
        parts = rows[key].get("fragments", [rows[key]])
        for part in parts:
            if not lower <= part["physical_page"] <= upper:
                return False
            if (
                block.get("type") == "table"
                and "style" in prepared
                and abs(part["bbox"][0] - prepared["style"]["margin_left_twips"] / 20)
                > rich_table_pdf.POSITION_TOLERANCE
            ):
                return False
            ordered.append(part)
        if "object_text_ranges" in prepared:
            if positions is None:
                return False
            start, end = prepared["object_text_ranges"][key]
            first, last = parts[0], parts[-1]
            if start:
                previous = positions[start - 1]
                if not (
                    previous[0] < first["physical_page"]
                    or previous[0] == first["physical_page"]
                    and previous[1][1] + 0.001 >= first["bbox"][3]
                ):
                    return False
            if end < len(positions):
                following = positions[end]
                if not (
                    following[0] > last["physical_page"]
                    or following[0] == last["physical_page"]
                    and following[1][3] <= last["bbox"][1] + 0.001
                ):
                    return False
    return all(
        before["physical_page"] < after["physical_page"]
        or (
            before["physical_page"] == after["physical_page"]
            and before["bbox"][1] + 0.001 >= after["bbox"][3]
        )
        for before, after in zip(ordered, ordered[1:], strict=False)
    )


def _visible_text(data, tables, style):
    """Reuse the RICH isolated-glyph raster test, including headers and footers."""
    if tables["coverage"] != "complete":
        return {"coverage": "partial", "gaps": ["WORD_TEXT_VISIBILITY_UNVERIFIED"]}, []
    verified: dict[int, list[Any]] = {}
    for table in tables["tables"]:
        for part in table.get("fragments", [table]):
            verified.setdefault(part["physical_page"], []).append(part["bbox"])
    render_pixels = work = checked = 0
    positions: list[tuple[int, Any, str]] = []
    document = pdfium.PdfDocument(data)
    try:
        for index in range(len(document)):
            page = document[index]
            actual = layer = None
            try:
                width, height = page.get_size()
                characters, _ = rich_table_pdf._characters(page)
                outside = []
                for char, box, supported in characters:
                    x0, y0, x1, y1 = box
                    if (
                        y0 >= style["margin_bottom_twips"] / 20
                        and y1 <= height - style["margin_top_twips"] / 20
                    ):
                        positions.extend((index + 1, box, c) for c in normalize(char))
                    if not supported or x0 < 0 or y0 < 0 or x1 > width or y1 > height:
                        return {
                            "coverage": "partial",
                            "gaps": ["WORD_TEXT_VISIBILITY_UNVERIFIED"],
                        }, []
                    if any(
                        left <= x0 <= x1 <= right and bottom <= y0 <= y1 <= top
                        for left, bottom, right, top in verified.get(index + 1, [])
                    ):
                        continue
                    outside.append((char, box))
                if not outside:
                    continue
                render_pixels += 2 * int(width * 2 + 1) * int(height * 2 + 1)
                if render_pixels > rich_table_pdf.MAX_RENDER_PIXELS:
                    return {"coverage": "partial", "gaps": ["WORD_TEXT_VISIBILITY_BUDGET"]}, []
                actual, layer = rich_table_pdf._rasters(document, page, index)
                for char, (x0, y0, x1, y1) in outside:
                    work += int((x1 - x0 + 6) * (y1 - y0 + 6) * 4)
                    if work > rich_table_pdf.MAX_WORK_UNITS:
                        return {"coverage": "partial", "gaps": ["WORD_TEXT_VISIBILITY_BUDGET"]}, []
                    candidate = {
                        "edges": [],
                        "cells": [
                            {
                                "bbox": [x0 - 3, y0 - 3, x1 + 3, y1 + 3],
                                "text": char,
                                "cell": {"attrs": {"header": False}},
                            }
                        ],
                    }
                    if not rich_table_pdf._visible(candidate, actual, layer, height):
                        return {
                            "coverage": "partial",
                            "gaps": ["WORD_TEXT_VISIBILITY_UNVERIFIED"],
                        }, []
                    checked += 1
            finally:
                if actual is not None:
                    actual.close()
                if layer is not None:
                    layer.close()
                page.close()
    finally:
        document.close()
    return {
        "coverage": "complete",
        "gaps": [],
        "checked_outside_table_characters": checked,
        "render_pixels": render_pixels,
        "work_units": work,
    }, positions


def inspect_pdf(data: bytes, prepared: dict, inspection: dict):
    gaps, body, records = list(prepared["unsupported"]), [], []
    end_pages: dict[int, list[int]] = {}
    style, stories = prepared["style"], prepared["stories"]
    document = pdfium.PdfDocument(data)
    try:
        if not 0 < len(document) <= 1000:
            raise ValueError("WORD_PDF_PAGE_LIMIT")
        count, chars = len(document), 0
        for index in range(count):
            page = document[index]
            text = page.get_textpage()
            try:
                width, height = page.get_size()
                chars += text.count_chars()
                if chars > 2_000_000:
                    raise ValueError("WORD_PDF_TEXT_LIMIT")
                if (
                    abs(width - style["page_width_twips"] / 20) > 1
                    or abs(height - style["page_height_twips"] / 20) > 1
                    or page.get_rotation() != 0
                ):
                    gaps.append("WORD_PAGE_GEOMETRY_UNVERIFIED")
                top, bottom = (
                    height - style["margin_top_twips"] / 20,
                    style["margin_bottom_twips"] / 20,
                )
                header = text.get_text_bounded(bottom=top)
                footer = text.get_text_bounded(top=bottom)
                main = text.get_text_bounded(bottom=bottom, top=top)
                if normalize(header) != normalize(stories["header"]) or normalize(
                    footer
                ) != normalize(stories["footer"]):
                    gaps.append("WORD_STATIC_STORY_CORRESPONDENCE_UNVERIFIED")
                if any(c in text.get_text_bounded() for c in "\ufffd\u25a1\u25a0"):
                    gaps.append("WORD_TEXT_CORRESPONDENCE_UNVERIFIED")
                body.append(normalize(main))
                end_pages.setdefault(sum(map(len, body)), []).append(index + 1)
                records.append(
                    {
                        "physical_page": index + 1,
                        "header_matches": normalize(header) == normalize(stories["header"]),
                        "footer_matches": normalize(footer) == normalize(stories["footer"]),
                        "body_character_count": len(body[-1]),
                    }
                )
            finally:
                text.close()
                page.close()
    finally:
        document.close()
    if "".join(body) != normalize("".join(inspection["paragraphs"])):
        gaps.append("WORD_TEXT_CORRESPONDENCE_UNVERIFIED")
    offset, boundaries = 0, []
    for chunk in prepared["body_chunks"][:-1]:
        offset += len(normalize(chunk))
        boundaries.append(offset)
        if len(end_pages.get(offset, [])) != 1:
            gaps.append("WORD_EXPLICIT_PAGE_BREAK_UNVERIFIED")
    tables = rich_table_pdf.inspect_tables(
        data, prepared["snapshot"], prepared["roots"], style, source_visuals=True
    )
    images = rich_pdf.inspect_images(data, prepared["snapshot"], prepared["materials"], style)
    gaps.extend(tables["gaps"] + images["gaps"])
    visibility, positions = _visible_text(data, tables, style)
    gaps.extend(visibility["gaps"])
    if "".join(p[2] for p in positions) != "".join(body):
        gaps.append("WORD_TEXT_POSITION_CORRESPONDENCE_UNVERIFIED")
        positions = None
    ordered = _object_order(prepared, tables, images, end_pages, boundaries, count, positions)
    if not ordered:
        gaps.append("WORD_OBJECT_ORDER_OR_PAGE_BREAK_UNVERIFIED")
    supported = {"hdr", "ftr", "tbl", "drawing"}
    if (
        set(inspection["unsupported_layout_features"]) - supported
        or tables["coverage"] != "complete"
        or images["coverage"] != "complete"
    ):
        gaps.append("WORD_COMPLEX_LAYOUT_UNVERIFIED")
    if not "".join(inspection["paragraphs"]).strip():
        gaps.append("WORD_TEXT_SCOPE_EMPTY")
    return {
        "protocol": "word-static-correspondence/1",
        "page_count": count,
        "gaps": list(dict.fromkeys(gaps)),
        "stories": records,
        "table_correspondence": tables,
        "raster_correspondence": images,
        "joint_object_order_verified": ordered,
        "text_visibility": visibility,
        "scope": "one_explicit_section_static_stories_fixed_tables_inline_opaque_PNG",
    }
