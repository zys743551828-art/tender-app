"""Narrow prebuilt-provider PDF representations, preserving business checks.

Only four-stroke half-width table joins and a frozen, linked TOC's visible dot
leaders are normalized. Source text, numbers, captions and raster rules remain.
"""

from __future__ import annotations

import ctypes as C
import math
import re
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from packages.authoring import (
    generated_renderer,
    page_navigation,
    rich_docx,
    rich_renderer,
)
from packages.authoring.build import W
from packages.domain.runtime import sha

PROTOCOL = "authoring-prebuilt-PDF-representations/1"
STROKE_CAP_MODEL = "four_stroke_half_width_joins/1"
geometry = rich_renderer.rich_table_pdf


def _source_entries(prepared):
    """Recognize the producer's exact, frozen right-aligned dot-tab paragraphs."""
    style = prepared["config"]
    if not style["toc_enabled"]:
        return []
    entries = rich_docx.navigation_entries(prepared["snapshot"], prepared["pagination"])
    paragraphs = (
        prepared["roots"]["word/document.xml"].find("{" + W + "}body").findall("{" + W + "}p")
    )
    offset = 2 if style["cover_enabled"] else 0
    for index, entry in enumerate(entries, 1):
        paragraph = paragraphs[offset + index]
        tabs = paragraph.findall("{" + W + "}pPr/{" + W + "}tabs/{" + W + "}tab")
        links = paragraph.findall("{" + W + "}hyperlink")
        if (
            len(tabs) != 1
            or tabs[0].get("{" + W + "}leader") != "dot"
            or tabs[0].get("{" + W + "}val") != "right"
            or tabs[0].get("{" + W + "}pos")
            != str(11906 - style["margin_left_twips"] - style["margin_right_twips"] - 60)
            or len(links) != 1
            or links[0].get("{" + W + "}anchor") != entry["anchor"]
            or "".join(node.text or "" for node in links[0].iter("{" + W + "}t")) != entry["title"]
        ):
            raise ValueError("TOC_SOURCE_LEADER_NOT_FROZEN")
    return entries


def _suffix(chars, box, expected, style, width):
    """Return only opaque, regularly spaced dots between title and frozen value."""
    selected = sorted(
        [
            item
            for item in chars
            if item[1][0] >= box[2] and item[1][1] >= box[1] - 1 and item[1][3] <= box[3] + 1
        ],
        key=lambda item: item[1][0],
    )
    literal = "".join(item[0] for item in selected)
    value = "—" if expected is None else str(expected)
    if not re.fullmatch(r"\.{0,2000}" + re.escape(value), literal):
        raise ValueError("TOC_SUFFIX_HAS_UNEXPECTED_TEXT")
    if any(
        not supported or bbox[2] > width - style["margin_right_twips"] / 20 + 1
        for _, bbox, supported in selected
    ):
        raise ValueError("TOC_SUFFIX_UNSUPPORTED_GEOMETRY")
    if any(a[1][2] >= b[1][0] for a, b in zip(selected, selected[1:], strict=False)):
        raise ValueError("TOC_SUFFIX_OVERLAPPING_GLYPHS")
    value_chars = selected[-len(value) :]
    tab_right = 11906 / 20 - style["margin_right_twips"] / 20 - 3
    if not value_chars or abs(value_chars[-1][1][2] - tab_right) > 1:
        raise ValueError("TOC_VALUE_NOT_AT_FROZEN_RIGHT_TAB")
    dots = selected[: -len(value)]
    if len(dots) == 1:
        raise ValueError("TOC_SINGLE_DOT_IS_NOT_A_LEADER")
    if dots:
        first = dots[0][1]
        if any(
            abs(bbox[1] - first[1]) > 0.05
            or abs(bbox[3] - first[3]) > 0.05
            or abs((bbox[2] - bbox[0]) - (first[2] - first[0])) > 0.05
            for _, bbox, _ in dots
        ):
            raise ValueError("TOC_LEADER_GLYPHS_NOT_REGULAR")
        pitches = [b[1][0] - a[1][0] for a, b in zip(dots, dots[1:], strict=False)]
        if (
            dots[0][1][0] - box[2] > 2 * pitches[0]
            or value_chars[0][1][0] - dots[-1][1][2] > 2 * pitches[0]
        ):
            raise ValueError("TOC_LEADER_DOES_NOT_SPAN_TAB")
        if any(abs(pitch - pitches[0]) > 0.05 for pitch in pitches):
            raise ValueError("TOC_LEADER_SPACING_NOT_REGULAR")
    return dots


def _linked_box(document, page, textpage, row, title):
    cursor, link = C.c_int(), raw.FPDF_LINK()
    candidates = []
    count = 0
    while raw.FPDFLink_Enumerate(page, cursor, link):
        count += 1
        if count > page_navigation.MAX_LINKS:
            raise ValueError("TOC_LINK_LIMIT")
        if raw.FPDFLink_GetAction(link):
            continue
        destination = page_navigation._dest(document, raw.FPDFLink_GetDest(document, link))
        if not destination or destination["page"] != row["start_page"]:
            continue
        rect = raw.FS_RECTF()
        if not raw.FPDFLink_GetAnnotRect(link, rect):
            continue
        box = [float(rect.left), float(rect.bottom), float(rect.right), float(rect.top)]
        if not all(math.isfinite(value) for value in box) or box[0] >= box[2] or box[1] >= box[3]:
            continue
        if generated_renderer.normalize(
            textpage.get_text_bounded(*box)
        ) == generated_renderer.normalize(title):
            candidates.append(box)
    if len(candidates) != 1:
        raise ValueError("TOC_TITLE_LINK_NOT_UNIQUE")
    return candidates[0]


def inspect_leaders(data, prepared, navigation):
    """Measure decoration without modifying PDF bytes or general text extraction."""
    result: dict[str, Any] = {"protocol": PROTOCOL, "coverage": "partial", "gaps": [], "rows": []}
    removed = set()
    document = None
    try:
        entries = _source_entries(prepared)
        if not entries or navigation["navigation_coverage"] != "complete":
            raise ValueError("TOC_NAVIGATION_NOT_COMPLETE")
        rows = navigation["entries"]
        if [row["node_id"] for row in rows] != [entry["node_id"] for entry in entries]:
            raise ValueError("TOC_SOURCE_NAVIGATION_MISMATCH")
        style = prepared["config"]
        document = pdfium.PdfDocument(data)
        pixels = 0
        for entry, row in zip(entries, rows, strict=True):
            number = row["toc_origin_page"]
            if type(number) is not int or not 1 <= number < row["start_page"] <= len(document):
                raise ValueError("TOC_NOT_BEFORE_CHAPTER")
            page = document[number - 1]
            textpage = page.get_textpage()
            actual = layer = None
            try:
                width, height = page.get_size()
                chars, _ = geometry._characters(page)
                box = _linked_box(document, page, textpage, row, entry["title"])
                dots = _suffix(chars, box, entry["expected_start_page"], style, width)
                if dots:
                    area = (
                        2 * math.ceil(width * geometry.SCALE) * math.ceil(height * geometry.SCALE)
                    )
                    pixels += area
                    if pixels > geometry.MAX_RENDER_PIXELS:
                        raise ValueError("TOC_LEADER_RASTER_LIMIT")
                    actual, layer = geometry._rasters(document, page, number - 1)
                    left = min(item[1][0] for item in dots)
                    bottom = min(item[1][1] for item in dots)
                    right = max(item[1][2] for item in dots)
                    top = max(item[1][3] for item in dots)
                    candidate = {
                        "edges": [],
                        "cells": [
                            {
                                "bbox": [left - 2, bottom - 2, right + 2, top + 2],
                                "text": "." * len(dots),
                                "cell": {"attrs": {"header": False}},
                            }
                        ],
                    }
                    if not geometry._visible(candidate, actual, layer, height):
                        raise ValueError("TOC_LEADER_NOT_VISIBLE")
                for text, bbox, _ in dots:
                    key = (number, text, tuple(bbox))
                    if key in removed:
                        raise ValueError("TOC_LEADER_REUSED")
                    removed.add(key)
                result["rows"].append(
                    {
                        "node_id": entry["node_id"],
                        "physical_page": number,
                        "title_link_bbox": box,
                        "dot_count": len(dots),
                        "expected_value": entry["expected_start_page"],
                    }
                )
            finally:
                if actual is not None:
                    actual.close()
                if layer is not None:
                    layer.close()
                textpage.close()
                page.close()
        body, raw_body = [], []
        total = 0
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                height = page.get_height()
                total += textpage.count_chars()
                if total > geometry.MAX_TOTAL_CHARS:
                    raise ValueError("TOC_BODY_CHARACTER_LIMIT")
                for char in range(textpage.count_chars()):
                    value = textpage.get_text_range(index=char, count=1)
                    if not value or value.isspace():
                        continue
                    bbox = textpage.get_charbox(char)
                    if (
                        bbox[3] <= style["margin_bottom_twips"] / 20 - 3
                        or bbox[1] >= height - style["margin_top_twips"] / 20 + 3
                    ):
                        continue
                    raw_body.append(value)
                    if (index + 1, value, tuple(bbox)) not in removed:
                        body.append(value)
            finally:
                textpage.close()
                page.close()
        expected = generated_renderer.normalize(
            generated_renderer.expected_body(prepared["body_roots"])
        )
        observed = generated_renderer.normalize("".join(body))
        result.update(
            {
                "expected_body_digest": sha(expected),
                "actual_body_digest": sha(observed),
                "raw_body_digest": sha(generated_renderer.normalize("".join(raw_body))),
                "removed_dot_count": len(removed),
                "render_pixels": pixels,
            }
        )
        if observed != expected:
            raise ValueError("TOC_FILTERED_BODY_NOT_EXACT")
        result["coverage"] = "complete"
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, pdfium.PdfiumError):
        result["gaps"] = ["AUTHORING_TOC_DECORATION_UNVERIFIED"]
    finally:
        if document is not None:
            document.close()
    return result


def _caption_name_mapping(prepared):
    """Bind LibreOffice's underscore escape to exact verified source bookmarks."""
    expected = [
        entry["anchor"] for entry in rich_renderer.rich_captions.entries(prepared["snapshot"])
    ] + [
        entry["anchor"]
        for entry in rich_docx.navigation_entries(prepared["snapshot"], prepared["pagination"])
    ]
    actual = [
        node.get("{" + W + "}name")
        for node in prepared["roots"]["word/document.xml"].iter("{" + W + "}bookmarkStart")
    ]
    if (
        len(expected) != len(set(expected))
        or len(actual) != len(set(actual))
        or set(actual) != set(expected)
        or any(re.fullmatch(r"(?:cap|sec)_[0-9a-f]{32}", name) is None for name in expected)
    ):
        raise ValueError("CAPTION_SOURCE_BOOKMARK_SET")
    return {name[:3] + "5F" + name[4:]: name for name in expected}


def inspect_pdf(data, prepared):
    """Same joint inspectors as RICH, plus the two explicit representations."""
    images = rich_renderer.rich_pdf.inspect_images(
        data, prepared["snapshot"], prepared["materials"], prepared["config"]
    )
    mode = prepared["pagination"]["mode"] if prepared["pagination"] else "continuous"
    navigation = page_navigation.inspect_navigation(
        data,
        rich_docx.navigation_entries(prepared["snapshot"], prepared["pagination"]),
        mode=mode,
        style=prepared["config"],
    )
    tables = geometry.inspect_tables(
        data,
        prepared["snapshot"],
        prepared["roots"],
        prepared["config"],
        stroke_cap_model=STROKE_CAP_MODEL,
    )
    body_roots = rich_renderer.rich_repeated_headers.body_roots(prepared["roots"], tables)
    body = generated_renderer.inspect_pdf(data, prepared | {"roots": body_roots})
    body["frozen_source_body_digest"] = sha(
        generated_renderer.normalize(generated_renderer.expected_body(prepared["roots"]))
    )
    leaders = None
    if "AUTHORING_COMPLETE_BODY_TEXT_UNVERIFIED" in body["gaps"]:
        leaders = inspect_leaders(data, prepared | {"body_roots": body_roots}, navigation)
        if leaders["coverage"] == "complete":
            body["gaps"] = [
                gap for gap in body["gaps"] if gap != "AUTHORING_COMPLETE_BODY_TEXT_UNVERIFIED"
            ]
            body["raw_body_digest"] = body["actual_body_digest"]
            body["actual_body_digest"] = leaders["actual_body_digest"]
    image_sections = rich_renderer.rich_pdf.inspect_image_sections(
        prepared["snapshot"], images, navigation
    )
    try:
        mapping = _caption_name_mapping(prepared)
    except (KeyError, TypeError, ValueError):
        captions = {"coverage": "partial", "gaps": ["AUTHORING_CAPTION_PDF_UNVERIFIED"]}
    else:
        captions = rich_renderer.rich_caption_pdf.inspect_captions(
            data, prepared["snapshot"], images, tables, prepared["config"], name_mapping=mapping
        )
    layout = rich_renderer.rich_layout.inspect_layout(
        prepared["snapshot"], images, tables, navigation
    )
    result = body | {
        "gaps": list(
            dict.fromkeys(
                body["gaps"]
                + images["gaps"]
                + navigation["gaps"]
                + tables["gaps"]
                + image_sections["gaps"]
                + captions["gaps"]
                + layout["gaps"]
            )
        ),
        "raster_correspondence": images,
        "navigation": navigation,
        "table_correspondence": tables,
        "image_section_correspondence": image_sections,
        "caption_correspondence": captions,
        "rich_layout_correspondence": layout,
        "provider_pdf_policy": PROTOCOL,
    }
    if leaders is not None:
        result["toc_decoration_correspondence"] = leaders
    return result
