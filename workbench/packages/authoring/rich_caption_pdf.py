"""Bounded same-page caption proof: stable destinations, text and visible pixels.

This internal inspector consumes same-call object proofs from the exact PDF.
Missing named destinations, split captions and unsupported graphics stay partial.
"""

from __future__ import annotations

import ctypes as C
import math
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from packages.authoring import page_navigation, rich_captions
from packages.authoring import rich_table_pdf as geometry
from packages.domain.runtime import sha

PROTOCOL = "authoring-PDF-caption-correspondence/2"
MAX_NAMES = 2000
MAX_WORK = 5_000_000
MAX_PIXELS = 64_000_000
MAX_LINES = 100


def _destinations(document):
    count = raw.FPDF_CountNamedDests(document)
    if count > MAX_NAMES:
        raise ValueError("CAPTION_DESTINATION_LIMIT")
    result = {}
    for index in range(count):
        length = C.c_long()
        if not raw.FPDF_GetNamedDest(document, index, None, length) or not 0 < length.value <= 2048:
            raise ValueError("CAPTION_DESTINATION_NAME")
        buffer = C.create_string_buffer(length.value)
        dest = raw.FPDF_GetNamedDest(document, index, buffer, length)
        if not dest or not 0 < length.value <= len(buffer):
            raise ValueError("CAPTION_DESTINATION_NAME")
        name = buffer.raw[: length.value].decode("utf-16-le").rstrip("\0")
        if name.startswith("cap_"):
            if name in result:
                raise ValueError("CAPTION_DESTINATION_DUPLICATE")
            result[name] = page_navigation._dest(document, dest)
    return result


def _lines(characters):
    result: list[list[Any]] = []
    for char in sorted(characters, key=lambda item: (-(item[1][1] + item[1][3]) / 2, item[1][0])):
        middle = (char[1][1] + char[1][3]) / 2
        if not result or abs(middle - result[-1][0]) > 3:
            result.append([middle, []])
        result[-1][1].append(char)
    return [sorted(line, key=lambda item: item[1][0]) for _, line in result]


def _candidates(lines, text, destination, style, width, height, budget):
    expected = geometry._normalized(text)
    if not expected:
        return []
    result = []
    for start, first in enumerate(lines):
        budget[0] += len(first)
        if budget[0] > MAX_WORK:
            raise ValueError("CAPTION_WORK_LIMIT")
        if (
            not min(item[1][1] for item in first) - 1
            <= destination
            <= max(item[1][3] for item in first) + 24
        ):
            continue
        joined = ""
        used: list[Any] = []
        for line in lines[start : start + MAX_LINES]:
            # Account for accumulated-prefix and bbox scans, not only new glyphs.
            budget[0] += len(line) + 6 * len(used) + len(joined)
            if budget[0] > MAX_WORK:
                raise ValueError("CAPTION_WORK_LIMIT")
            if used and min(item[1][1] for item in used) - max(item[1][3] for item in line) > 24:
                break
            joined += geometry._normalized("".join(item[0] for item in line))
            used.extend(line)
            if not expected.startswith(joined):
                break
            if joined != expected:
                continue
            box = [
                min(c[1][0] for c in used),
                min(c[1][1] for c in used),
                max(c[1][2] for c in used),
                max(c[1][3] for c in used),
            ]
            if (
                all(item[2] for item in used)
                and box[0] >= style["margin_left_twips"] / 20
                and box[1] >= style["margin_bottom_twips"] / 20
                and box[2] <= width - style["margin_right_twips"] / 20
                and box[3] <= height - style["margin_top_twips"] / 20
            ):
                result.append(box)
            break
    return result


def inspect_captions(data, snapshot, images, tables, style):
    """No external receipts; caller has already validated the frozen source."""
    expected = rich_captions.entries(snapshot)
    result: dict[str, Any] = {
        "protocol": PROTOCOL,
        "coverage": "partial",
        "gaps": [],
        "captions": [],
        "render_pixels": 0,
        "work_units": 0,
    }
    if not expected:
        return result | {"coverage": "complete"}
    if not isinstance(data, bytes) or not 0 < len(data) <= geometry.MAX_BYTES:
        return result | {"gaps": ["AUTHORING_CAPTION_PDF_UNVERIFIED"]}
    # Match by frozen per-kind order, not a globally assumed unique client node ID.
    origins, counters = {}, {"image": 0, "table": 0}
    for section_index, section in enumerate(snapshot["sections"]):
        for block_index, block in enumerate(section["content"]):
            kind = block["type"]
            if kind not in counters:
                continue
            proof = images if kind == "image" else tables
            records = proof["images" if kind == "image" else "tables"]
            index = counters[kind]
            counters[kind] += 1
            if (
                proof["coverage"] != "complete"
                or index >= len(records)
                or records[index]["node_id"] != block["attrs"]["id"]
            ):
                return result | {"gaps": ["AUTHORING_CAPTION_OBJECT_UNVERIFIED"]}
            origins[(section_index, block_index)] = records[index].get(
                "fragments", [records[index]]
            )[-1]
    document = None
    budget = [0]
    try:
        document = pdfium.PdfDocument(data)
        if not 0 < len(document) <= geometry.MAX_PAGES:
            raise ValueError("CAPTION_PAGE_LIMIT")
        destinations = _destinations(document)
        if set(destinations) != {item["anchor"] for item in expected}:
            raise ValueError("CAPTION_DESTINATION_SET")
        by_page: dict[int, list[Any]] = {}
        for entry in expected:
            dest = destinations[entry["anchor"]]
            origin = origins[(entry["section_index"], entry["block_index"])]
            if not dest or dest["page"] != origin["physical_page"] or dest["top"] is None:
                raise ValueError("CAPTION_DESTINATION_PAGE")
            by_page.setdefault(dest["page"], []).append((entry, dest, origin))
        used = set()
        total_chars = 0
        for number, entries in by_page.items():
            page = document[number - 1]
            actual = layer = None
            try:
                width, height = page.get_size()
                if page.get_rotation() or not 0 < width <= 1000 or not 0 < height <= 1500:
                    raise ValueError("CAPTION_PAGE_GEOMETRY")
                _, unsupported = geometry._paths(page)
                if unsupported:
                    raise ValueError("CAPTION_GRAPHICS_UNSUPPORTED")
                characters, count = geometry._characters(page)
                total_chars += count
                if total_chars > geometry.MAX_TOTAL_CHARS:
                    raise ValueError("CAPTION_CHARACTER_LIMIT")
                lines = _lines(characters)
                for entry, dest, origin in entries:
                    candidates = _candidates(
                        lines, entry["text"], dest["top"], style, width, height, budget
                    )
                    if len(candidates) != 1:
                        raise ValueError("CAPTION_TEXT_AMBIGUOUS")
                    left, bottom, right, top = box = candidates[0]
                    if not -0.001 <= origin["bbox"][1] - top <= 48:
                        raise ValueError("CAPTION_NOT_AFTER_OBJECT")
                    identity = (number, *box)
                    if identity in used:
                        raise ValueError("CAPTION_REUSED")
                    used.add(identity)
                    # A different text paragraph may not intervene between object and caption.
                    budget[0] += len(characters) + len(origins)
                    if budget[0] > MAX_WORK:
                        raise ValueError("CAPTION_WORK_LIMIT")
                    if any(
                        top + 0.5 < char[1][1] and char[1][3] < origin["bbox"][1] - 0.5
                        for char in characters
                    ):
                        raise ValueError("CAPTION_INTERVENING_TEXT")
                    if any(
                        other is not origin
                        and other["physical_page"] == number
                        and bottom < other["bbox"][3] <= origin["bbox"][1]
                        for other in origins.values()
                    ):
                        raise ValueError("CAPTION_INTERVENING_OBJECT")
                    if actual is None:
                        pixels = (
                            2
                            * math.ceil(width * geometry.SCALE)
                            * math.ceil(height * geometry.SCALE)
                        )
                        if result["render_pixels"] + pixels > MAX_PIXELS:
                            raise ValueError("CAPTION_RASTER_LIMIT")
                        result["render_pixels"] += pixels
                        actual, layer = geometry._rasters(document, page, number - 1)
                    candidate = {
                        "edges": [],
                        "cells": [
                            {
                                "bbox": [left - 2, bottom - 2, right + 2, top + 2],
                                "text": geometry._normalized(entry["text"]),
                                "cell": {"attrs": {"header": False}},
                            }
                        ],
                    }
                    if not geometry._visible(candidate, actual, layer, height):
                        raise ValueError("CAPTION_NOT_VISIBLE")
                    result["captions"].append(
                        {
                            "anchor": entry["anchor"],
                            "node_id": entry["node_id"],
                            "section_id": entry["section_id"],
                            "physical_page": number,
                            "bbox": box,
                            "text_digest": sha(geometry._normalized(entry["text"])),
                        }
                    )
            finally:
                if actual is not None:
                    actual.close()
                if layer is not None:
                    layer.close()
                page.close()
        result["coverage"] = "complete"
    except (pdfium.PdfiumError, ValueError, OverflowError, OSError):
        result["gaps"] = ["AUTHORING_CAPTION_PDF_UNVERIFIED"]
    finally:
        result["work_units"] = budget[0]
        if document is not None:
            document.close()
    return result
