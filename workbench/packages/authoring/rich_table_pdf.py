"""Measured single-page and restricted two-page native-table correspondence.

The inspector grants no renderer, submission, or source qualification. It accepts
only a complete visible black grid, exact frozen cell text and expected cell
backgrounds. Unsupported splits, unobservable row boundaries, complex PDF graphics and
ambiguous occurrences remain partial rather than inheriting DOCX qualification.
"""

from __future__ import annotations

import ctypes as C
import math
import unicodedata
from pathlib import Path
from typing import Any, cast

import PIL
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import Image, ImageChops

from packages.authoring import generated_renderer, rich_content
from packages.authoring import rich_table_continuations as continuation
from packages.authoring.build import W
from packages.domain.runtime import sha

PROTOCOL = "authoring-PDF-table-correspondence/3"
MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 1000
MAX_TABLES = 500
MAX_PAGE_OBJECTS = 20000
MAX_PAGE_SEGMENTS = 40000
MAX_PAGE_CHARS = 200000
MAX_TOTAL_CHARS = 2000000
MAX_CANDIDATES = 2000
MAX_WORK_UNITS = 5_000_000
MAX_RENDER_PIXELS = 64_000_000
SCALE = 2
POSITION_TOLERANCE = 0.75
JOIN_TOLERANCE = 0.2


def identity():
    return {
        "protocol": PROTOCOL,
        "source_digest": sha(Path(__file__).read_bytes()),
        "pdfium_wrapper": str(pdfium.PYPDFIUM_INFO),
        "pdfium_build": str(pdfium.PDFIUM_INFO),
        "pillow_version": PIL.__version__,
        "scope": "single_page_or_bounded_two_page_exact_rows_and_isolated_raster",
        "continuation_policy_digest": sha(Path(continuation.__file__).read_bytes()),
        "continuation_max_rows": continuation.MAX_ROWS,
        "continuation_page_edge_slack_pt": continuation.PAGE_EDGE_SLACK,
        "render_scale": SCALE,
        "max_render_pixels": MAX_RENDER_PIXELS,
        "max_candidates": MAX_CANDIDATES,
        "max_work_units": MAX_WORK_UNITS,
        "position_tolerance_pt": POSITION_TOLERANCE,
        "join_tolerance_pt": JOIN_TOLERANCE,
    }


def _normalized(text):
    # No digit deletion, case folding or compatibility-character substitution.
    return "".join(unicodedata.normalize("NFC", text).split())


def _expected(snapshot, roots):
    blocks = [
        block
        for section in snapshot["sections"]
        for block in section["content"]
        if block["type"] == "table"
    ]
    native = list(roots["word/document.xml"].iter("{" + W + "}tbl"))
    if len(blocks) != len(native) or len(blocks) > MAX_TABLES:
        raise ValueError("TABLE_SOURCE_COUNT")
    result = []
    for block, table in zip(blocks, native, strict=True):
        checked = rich_content.table_grid(block)
        cells = [
            cell
            for cell in table.iter("{" + W + "}tc")
            if (merge := cell.find("{" + W + "}tcPr/{" + W + "}vMerge")) is None
            or merge.get("{" + W + "}val") == "restart"
        ]
        if len(cells) != len(checked["origins"]):
            raise ValueError("TABLE_SOURCE_CELL_COUNT")
        expected = []
        for origin, cell in zip(checked["origins"], cells, strict=True):
            text = _normalized(
                generated_renderer.expected_body(
                    {"word/document.xml": cell, "word/numbering.xml": roots["word/numbering.xml"]}
                )
            )
            expected.append(origin | {"text": text})
        result.append(
            {
                "node_id": block["attrs"]["id"],
                "widths": [value / 20 for value in checked["column_widths_twips"]],
                "rows": len(checked["grid"]),
                "repeat_header": "pagination" in block["attrs"],
                "cells": expected,
            }
        )
    return result


def _color(obj, *, stroke=False):
    channels = [C.c_uint() for _ in range(4)]
    get = raw.FPDFPageObj_GetStrokeColor if stroke else raw.FPDFPageObj_GetFillColor
    return tuple(value.value for value in channels) if get(obj, *channels) else None


def _black(color):
    return color is not None and color[3] == 255 and max(color[:3]) <= 16


def _matrix(obj):
    matrix = raw.FS_MATRIX()
    if not raw.FPDFPageObj_GetMatrix(obj, matrix):
        return None
    values = (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f)
    if (
        not all(math.isfinite(value) for value in values)
        or abs(matrix.b) > 0.0001
        or abs(matrix.c) > 0.0001
        or matrix.a <= 0
        or matrix.d <= 0
    ):
        return None
    return matrix


def _line(start, end):
    x0, y0 = start
    x1, y1 = end
    if abs(y1 - y0) < 0.01 and abs(x1 - x0) >= 2:
        return ("h", (y0 + y1) / 2, min(x0, x1), max(x0, x1))
    if abs(x1 - x0) < 0.01 and abs(y1 - y0) >= 2:
        return ("v", (x0 + x1) / 2, min(y0, y1), max(y0, y1))
    return None


def _stroke_cap_rectangle(records, path_count):
    """Narrow provider representation: four single strokes overlap by half-width.

    This is not a general tolerance increase. Unknown/multiple grids, extra paths,
    unequal joins or excessive extensions retain the original measurements.
    """
    if path_count != 4 or len(records) != 4:
        return None
    horizontal = [item for item in records if item[0][0] == "h"]
    vertical = [item for item in records if item[0][0] == "v"]
    if len(horizontal) != 2 or len(vertical) != 2:
        return None
    bottom, top = sorted(item[0][1] for item in horizontal)
    left, right = sorted(item[0][1] for item in vertical)
    if right - left < 4 or top - bottom < 4:
        return None
    normalized = []
    for line, stroke_width in records:
        kind, coordinate, start, end = line
        if not 0.25 <= stroke_width <= 1.5:
            return None
        low, high = (left, right) if kind == "h" else (bottom, top)
        half = stroke_width / 2
        if abs(start - (low - half)) > 0.001 or abs(end - (high + half)) > 0.001:
            return None
        normalized.append((kind, coordinate, low, high))
    return normalized


def _paths(page, *, stroke_cap_model=None):
    """Read native top-level strokes or thin solid rectangles, never OCR lines."""
    count = raw.FPDFPage_CountObjects(page)
    if not 0 <= count <= MAX_PAGE_OBJECTS:
        raise ValueError("TABLE_OBJECT_LIMIT")
    lines = []
    unsupported = False
    segment_count = 0
    stroke_records = []
    path_count = 0
    for index in range(count):
        obj = raw.FPDFPage_GetObject(page, index)
        kind = raw.FPDFPageObj_GetType(obj)
        if kind in {raw.FPDF_PAGEOBJ_FORM, raw.FPDF_PAGEOBJ_SHADING, raw.FPDF_PAGEOBJ_UNKNOWN}:
            unsupported = True
        if kind != raw.FPDF_PAGEOBJ_PATH:
            continue
        path_count += 1
        matrix = _matrix(obj)
        fill, stroke = C.c_int(), C.c_int()
        if matrix is None or not raw.FPDFPath_GetDrawMode(obj, fill, stroke):
            continue
        count_segments = raw.FPDFPath_CountSegments(obj)
        segment_count += max(0, count_segments)
        if count_segments < 0 or segment_count > MAX_PAGE_SEGMENTS:
            raise ValueError("TABLE_SEGMENT_LIMIT")
        points: list[tuple[float, float]] = []
        paths: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        valid = True
        for position in range(count_segments):
            segment = raw.FPDFPath_GetPathSegment(obj, position)
            kind = raw.FPDFPathSegment_GetType(segment)
            x, y = C.c_float(), C.c_float()
            if (
                kind not in {raw.FPDF_SEGMENT_MOVETO, raw.FPDF_SEGMENT_LINETO}
                or not raw.FPDFPathSegment_GetPoint(segment, x, y)
                or not math.isfinite(x.value)
                or not math.isfinite(y.value)
            ):
                valid = False
                break
            point = (x.value * matrix.a + matrix.e, y.value * matrix.d + matrix.f)
            points.append(point)
            if kind == raw.FPDF_SEGMENT_MOVETO:
                if current:
                    paths.append(current)
                current = [point]
            elif current:
                current.append(point)
            else:
                valid = False
                break
            if raw.FPDFPathSegment_GetClose(segment) and current and current[-1] != current[0]:
                current.append(current[0])
        if current:
            paths.append(current)
        if not valid or not points:
            continue
        if (
            stroke.value
            and fill.value == raw.FPDF_FILLMODE_NONE
            and _black(_color(obj, stroke=True))
        ):
            width = C.c_float()
            if (
                not raw.FPDFPageObj_GetStrokeWidth(obj, width)
                or not 0.25 <= width.value * min(matrix.a, matrix.d)
                or width.value * max(matrix.a, matrix.d) > 1.5
                or raw.FPDFPageObj_GetDashCount(obj) != 0
            ):
                continue
            for path in paths:
                for start, end in zip(path, path[1:], strict=False):
                    if (line := _line(start, end)) is not None:
                        lines.append(line)
            if (
                len(paths) == 1
                and len(paths[0]) == 2
                and abs(matrix.a - matrix.d) <= 0.0001
                and (single := _line(paths[0][0], paths[0][1])) is not None
            ):
                stroke_records.append((single, width.value * matrix.a))
        elif fill.value != raw.FPDF_FILLMODE_NONE and not stroke.value and _black(_color(obj)):
            # LibreOffice may export an opaque border as a thin filled rectangle.
            if len(paths) != 1:
                continue
            path = paths[0]
            if len(path) != 5 or path[0] != path[-1]:
                continue
            xs, ys = sorted({p[0] for p in path}), sorted({p[1] for p in path})
            if len(xs) != 2 or len(ys) != 2:
                continue
            if any(_line(a, b) is None for a, b in zip(path, path[1:], strict=False)):
                # Short sides are under the normal line minimum; require axis alignment.
                if any(
                    abs(a[0] - b[0]) > 0.01 and abs(a[1] - b[1]) > 0.01
                    for a, b in zip(path, path[1:], strict=False)
                ):
                    continue
            if 0.25 <= ys[1] - ys[0] <= 1.5 and xs[1] - xs[0] >= 2:
                lines.append(("h", sum(ys) / 2, xs[0], xs[1]))
            elif 0.25 <= xs[1] - xs[0] <= 1.5 and ys[1] - ys[0] >= 2:
                lines.append(("v", sum(xs) / 2, ys[0], ys[1]))
    if stroke_cap_model is not None:
        if stroke_cap_model != "four_stroke_half_width_joins/1":
            raise ValueError("TABLE_STROKE_CAP_MODEL_UNSUPPORTED")
        normalized = _stroke_cap_rectangle(stroke_records, path_count)
        if normalized is not None:
            lines = normalized
    return _merge(lines), unsupported


def _merge(lines):
    result: list[tuple[str, float, float, float]] = []
    for orientation, coordinate, low, high in sorted(lines):
        if (
            result
            and result[-1][0] == orientation
            and abs(result[-1][1] - coordinate) <= JOIN_TOLERANCE
            and low <= result[-1][3] + JOIN_TOLERANCE
        ):
            previous = result[-1]
            result[-1] = (orientation, previous[1], min(previous[2], low), max(previous[3], high))
        else:
            result.append((orientation, coordinate, low, high))
    return result


def _work(budget, count):
    budget["work_units"] += count
    if budget["work_units"] > MAX_WORK_UNITS:
        raise ValueError("TABLE_COMBINED_WORK_LIMIT")


def _covers(lines, expected, budget):
    _work(budget, len(lines))
    orientation, coordinate, low, high = expected
    intervals = sorted(
        (a, b)
        for kind, value, a, b in lines
        if kind == orientation and abs(coordinate - value) <= POSITION_TOLERANCE
    )
    position = low
    for start, end in intervals:
        if end < position - JOIN_TOLERANCE:
            continue
        if start > position + JOIN_TOLERANCE:
            return False
        position = max(position, end)
        if position >= high - JOIN_TOLERANCE:
            return True
    return False


def _clusters(values):
    result: list[float] = []
    for value in sorted(values):
        if not result or value - result[-1] > POSITION_TOLERANCE:
            result.append(value)
    return result


def _geometry(table, lines, budget):
    _work(budget, len(lines))
    width = sum(table["widths"])
    horizontals = [
        line
        for line in lines
        if line[0] == "h" and abs(line[3] - line[2] - width) <= POSITION_TOLERANCE
    ]
    for _, top, left, right in horizontals:
        for _, bottom, x0, x1 in horizontals:
            budget["candidates"] += 1
            _work(budget, 1)
            if budget["candidates"] > MAX_CANDIDATES:
                raise ValueError("TABLE_CANDIDATE_LIMIT")
            if (
                top - bottom < table["rows"] * 4
                or abs(x0 - left) > POSITION_TOLERANCE
                or abs(x1 - right) > POSITION_TOLERANCE
            ):
                continue
            if not _covers(lines, ("v", left, bottom, top), budget) or not _covers(
                lines, ("v", right, bottom, top), budget
            ):
                continue
            _work(budget, len(lines))
            rows = sorted(
                _clusters(
                    [
                        value
                        for kind, value, a, b in lines
                        if kind == "h"
                        and bottom - POSITION_TOLERANCE <= value <= top + POSITION_TOLERANCE
                        and b > left + 1
                        and a < right - 1
                    ]
                ),
                reverse=True,
            )
            if len(rows) != table["rows"] + 1 or any(
                a - b < 4 for a, b in zip(rows, rows[1:], strict=False)
            ):
                continue
            columns = [left]
            for size in table["widths"]:
                columns.append(columns[-1] + size)
            if any(value < 4 for value in table["widths"]):
                continue
            cells, edges = [], []
            _work(budget, len(table["cells"]))
            for origin in table["cells"]:
                attrs = origin["cell"]["attrs"]
                row, column = origin["row"], origin["column"]
                x0, x1 = columns[column], columns[column + attrs["colspan"]]
                y1, y0 = rows[row], rows[row + attrs["rowspan"]]
                cells.append(origin | {"bbox": (x0, y0, x1, y1)})
                edges.extend(
                    [("h", y0, x0, x1), ("h", y1, x0, x1), ("v", x0, y0, y1), ("v", x1, y0, y1)]
                )
            edges = _merge(edges)
            if not all(_covers(lines, line, budget) for line in edges):
                continue
            # An extra divider through a merged cell must not be mistaken for its grid.
            actual = []
            _work(budget, len(lines))
            for kind, value, a, b in lines:
                minimum, maximum = (bottom, top) if kind == "h" else (left, right)
                start, end = (left, right) if kind == "h" else (bottom, top)
                if (
                    minimum - POSITION_TOLERANCE <= value <= maximum + POSITION_TOLERANCE
                    and min(end, b) - max(start, a) > 1
                ):
                    actual.append((kind, value, max(start, a), min(end, b)))
            if all(_covers(edges, line, budget) for line in actual):
                yield {"bbox": (left, bottom, columns[-1], top), "cells": cells, "edges": edges}


def _characters(page):
    textpage = page.get_textpage()
    result = []
    try:
        count = textpage.count_chars()
        if not 0 <= count <= MAX_PAGE_CHARS:
            raise ValueError("TABLE_CHARACTER_LIMIT")
        for index in range(count):
            code = raw.FPDFText_GetUnicode(textpage, index)
            if not code or code > 0x10FFFF or chr(code).isspace():
                continue
            bbox = textpage.get_charbox(index)
            if not all(math.isfinite(value) for value in bbox):
                raise ValueError("TABLE_TEXT_GEOMETRY")
            obj = raw.FPDFText_GetTextObject(textpage, index)
            clip = raw.FPDFPageObj_GetClipPath(obj) if obj else None
            supported = bool(
                obj
                and bbox[0] < bbox[2]
                and bbox[1] < bbox[3]
                and _matrix(obj) is not None
                and raw.FPDFTextObj_GetTextRenderMode(obj) == 0
                and _black(_color(obj))
                # A valid empty CPDF_ClipPath has HasRef=false and a -1 count in
                # PDFium. Retained clipping paths have a positive count. The
                # nonnull handle here comes from a live actual text object.
                and clip
                and raw.FPDFClipPath_CountPaths(clip) in {-1, 0}
            )
            result.append((chr(code), bbox, supported))
        return result, count
    finally:
        textpage.close()


def _cell_text(candidate, characters, budget):
    groups: list[list[str]] = [[] for _ in candidate["cells"]]
    _work(budget, len(characters))
    left, bottom, right, top = candidate["bbox"]
    for text, (x0, y0, x1, y1), supported in characters:
        if x1 <= left or x0 >= right or y1 <= bottom or y0 >= top:
            continue
        matches = []
        _work(budget, len(candidate["cells"]))
        for index, cell in enumerate(candidate["cells"]):
            a, b, c, d = cell["bbox"]
            # The entire glyph box must lie in the raster-checked cell interior.
            if x0 >= a + 1.5 and x1 <= c - 1.5 and y0 >= b + 1.5 and y1 <= d - 1.5:
                matches.append(index)
        if len(matches) != 1 or not supported:
            return False
        groups[matches[0]].append(text)
    return all(
        _normalized("".join(text)) == cell["text"]
        for text, cell in zip(groups, candidate["cells"], strict=True)
    )


def _rasters(document, page, index):
    """Use native same-PDF glyphs in an isolated layer, with no obscuring objects."""
    actual_bitmap = page.render(scale=SCALE, draw_annots=True)
    try:
        actual = actual_bitmap.to_pil().convert("RGB")
    finally:
        actual_bitmap.close()
    isolated = pdfium.PdfDocument.new()
    reference_page = reference_bitmap = None
    try:
        isolated.import_pages(document, [index])
        reference_page = isolated[0]
        for obj in list(reference_page.get_objects(max_depth=0)):
            if obj.type != raw.FPDF_PAGEOBJ_TEXT:
                reference_page.remove_obj(obj)
                obj.close()
        reference_page.gen_content()
        reference_bitmap = reference_page.render(
            scale=SCALE, fill_color=(0, 0, 0, 0), draw_annots=False
        )
        return actual, reference_bitmap.to_pil().convert("RGBA")
    except BaseException:
        actual.close()
        raise
    finally:
        if reference_bitmap is not None:
            reference_bitmap.close()
        if reference_page is not None:
            reference_page.close()
        isolated.close()


def _visible(candidate, actual, text_layer, height):
    pixels = actual.load()
    for kind, coordinate, low, high in candidate["edges"]:
        # Every pixel-length along every border must retain visible black ink.
        center = round((height - coordinate if kind == "h" else coordinate) * SCALE)
        start, end = (low, high) if kind == "h" else (height - high, height - low)
        for position in range(math.ceil(start * SCALE), math.floor(end * SCALE) + 1):
            samples = [
                (position, p) if kind == "h" else (p, position)
                for p in range(center - 1, center + 2)
            ]
            if not any(
                0 <= x < actual.width and 0 <= y < actual.height and max(pixels[x, y]) <= 208
                for x, y in samples
            ):
                return False
    for cell in candidate["cells"]:
        left, bottom, right, top = cell["bbox"]
        box = (
            math.ceil(left * SCALE) + 2,
            math.ceil((height - top) * SCALE) + 2,
            math.floor(right * SCALE) - 2,
            math.floor((height - bottom) * SCALE) - 2,
        )
        if (
            box[0] < 0
            or box[1] < 0
            or box[2] > actual.width
            or box[3] > actual.height
            or box[2] <= box[0]
            or box[3] <= box[1]
        ):
            return False
        color = (231, 230, 230, 255) if cell["cell"]["attrs"]["header"] else (255, 255, 255, 255)
        base = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), color)
        layer = text_layer.crop(box)
        observed = actual.crop(box)
        reference = difference = composited = None
        try:
            composited = Image.alpha_composite(base, layer)
            reference = composited.convert("RGB")
            difference = ImageChops.difference(observed, reference)
            extrema = cast(tuple[tuple[int, int], ...], difference.getextrema())
            if max(maximum for _, maximum in extrema) > 3:
                return False
            # An extracted nonempty cell cannot be accepted as a blank rendered cell.
            alpha = layer.getchannel("A")
            try:
                if cell["text"] and alpha.getextrema()[1] < 128:
                    return False
            finally:
                alpha.close()
        finally:
            base.close()
            layer.close()
            observed.close()
            for item in (reference, difference, composited):
                if item is not None:
                    item.close()
    return True


def inspect_tables(data, snapshot, roots, style, *, stroke_cap_model=None):
    result: dict[str, Any] = {
        "protocol": PROTOCOL,
        "pdf_digest": sha(data) if isinstance(data, bytes) and len(data) <= MAX_BYTES else None,
        "coverage": "partial",
        "gaps": [],
        "expected_tables": 0,
        "matched_tables": 0,
        "render_pixels": 0,
        "work_units": 0,
        "tables": [],
    }
    gaps = []
    try:
        expected = _expected(snapshot, roots)
    except (KeyError, TypeError, ValueError):
        result["gaps"] = ["AUTHORING_TABLE_SOURCE_UNVERIFIED"]
        return result
    result["expected_tables"] = len(expected)
    if not expected:
        return result | {"coverage": "complete"}
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        return result | {"gaps": ["AUTHORING_TABLE_PDF_BYTES_INVALID"]}
    matches: list[list[dict]] = [[] for _ in expected]
    fragments: list[list[dict]] = [[] for _ in expected]
    budget, total_chars = {"candidates": 0, "work_units": 0}, 0
    try:
        document = pdfium.PdfDocument(data)
    except (pdfium.PdfiumError, ValueError):
        return result | {"gaps": ["AUTHORING_TABLE_PDF_UNREADABLE"]}
    try:
        if not 0 < len(document) <= MAX_PAGES:
            return result | {"gaps": ["AUTHORING_TABLE_PAGE_LIMIT"]}
        for page_index in range(len(document)):
            page = document[page_index]
            actual = text_layer = None
            try:
                width, height = page.get_size()
                if page.get_rotation() != 0 or not 0 < width <= 1000 or not 0 < height <= 1500:
                    gaps.append("AUTHORING_TABLE_PAGE_GEOMETRY_UNSUPPORTED")
                    continue
                lines, unsupported = _paths(page, stroke_cap_model=stroke_cap_model)
                if not lines:
                    continue
                characters, count = _characters(page)
                total_chars += count
                if total_chars > MAX_TOTAL_CHARS:
                    raise ValueError("TABLE_TOTAL_CHARACTER_LIMIT")
                for index, original in enumerate(expected):
                    if 2 <= original["rows"] <= continuation.MAX_ROWS:
                        _work(budget, 2 * original["rows"] * len(original["cells"]))
                    for table in continuation.variants(original):
                        for candidate in _geometry(table, lines, budget):
                            if "source_rows" in table:
                                _work(budget, len(lines) + len(characters))
                            if "source_rows" in table and not (
                                continuation.maximal(candidate, lines, POSITION_TOLERANCE)
                                and continuation.edge_allowed(candidate, table, height, style)
                                and continuation.clear_edge_text(
                                    candidate, table, characters, height, style
                                )
                            ):
                                continue
                            left, bottom, right, top = candidate["bbox"]
                            if (
                                unsupported
                                or left < style["margin_left_twips"] / 20 - 1
                                or right > width - style["margin_right_twips"] / 20 + 1
                                or bottom < style["margin_bottom_twips"] / 20 - 1
                                or top > height - style["margin_top_twips"] / 20 + 1
                            ):
                                continue
                            if not _cell_text(candidate, characters, budget):
                                continue
                            if actual is None:
                                area = 2 * math.ceil(width * SCALE) * math.ceil(height * SCALE)
                                if result["render_pixels"] + area > MAX_RENDER_PIXELS:
                                    raise ValueError("TABLE_RASTER_LIMIT")
                                result["render_pixels"] += area
                                actual, text_layer = _rasters(document, page, page_index)
                            if not _visible(candidate, actual, text_layer, height):
                                continue
                            if "source_rows" in table:
                                low, high = continuation.edge_band(candidate, table, height, style)
                                if low < high:
                                    box = (
                                        math.ceil(style["margin_left_twips"] / 20 * SCALE),
                                        math.ceil((height - high) * SCALE),
                                        math.floor(
                                            (width - style["margin_right_twips"] / 20) * SCALE
                                        ),
                                        math.floor((height - low) * SCALE),
                                    )
                                    if box[2] > box[0] and box[3] > box[1]:
                                        _work(
                                            budget,
                                            max(0, box[2] - box[0]) * max(0, box[3] - box[1]),
                                        )
                                        band = actual.crop(box)
                                        try:
                                            if any(
                                                minimum < 252 for minimum, _ in band.getextrema()
                                            ):
                                                continue
                                        finally:
                                            band.close()
                            (fragments if "source_rows" in table else matches)[index].append(
                                {
                                    "node_id": table["node_id"],
                                    **(
                                        {
                                            "source_rows": table["source_rows"],
                                            "page_size": [width, height],
                                        }
                                        if "source_rows" in table
                                        else {}
                                    ),
                                    "physical_page": page_index + 1,
                                    "bbox": list(candidate["bbox"]),
                                    "cells": [
                                        {
                                            "node_id": cell["cell"]["attrs"]["id"],
                                            "row": cell.get(
                                                "source_row",
                                                cell["row"] + table.get("source_rows", [0])[0],
                                            ),
                                            **(
                                                {"repeated_header": True}
                                                if cell.get("repeated_header")
                                                else {}
                                            ),
                                            "column": cell["column"],
                                            "rowspan": cell["cell"]["attrs"]["rowspan"],
                                            "colspan": cell["cell"]["attrs"]["colspan"],
                                            "bbox": list(cell["bbox"]),
                                            "text_digest": sha(cell["text"]),
                                            "character_count": len(cell["text"]),
                                        }
                                        for cell in candidate["cells"]
                                    ],
                                }
                            )
            except (pdfium.PdfiumError, ValueError, OverflowError, OSError):
                gaps.append("AUTHORING_TABLE_INSPECTION_INCOMPLETE")
                break
            finally:
                if actual is not None:
                    actual.close()
                if text_layer is not None:
                    text_layer.close()
                page.close()
        for index, parts in enumerate(fragments):
            if parts:
                combined = continuation.assemble(expected[index], parts, POSITION_TOLERANCE)
                if combined is None:
                    gaps.append("AUTHORING_TABLE_CONTINUATION_UNVERIFIED")
                else:
                    matches[index].append(combined)
        rows = [items[0] for items in matches if len(items) == 1]
        if len(rows) != len(expected):
            gaps.append("AUTHORING_TABLE_PDF_GEOMETRY_UNVERIFIED")
        if any(len(items) > 1 for items in matches):
            gaps.append("AUTHORING_TABLE_MATCH_AMBIGUOUS")
        placements = [part for row in rows for part in row.get("fragments", [row])]
        previous = None
        for row in placements:
            left, bottom, right, top = row["bbox"]
            order = (row["physical_page"], -top, left)
            if previous is not None and order <= previous:
                gaps.append("AUTHORING_TABLE_ORDER_OR_REUSE_UNVERIFIED")
            previous = order
        for index, row in enumerate(placements):
            for other in placements[index + 1 :]:
                a, b, c, d = row["bbox"]
                e, f, g, h = other["bbox"]
                if (
                    row["physical_page"] == other["physical_page"]
                    and min(c, g) > max(a, e) + POSITION_TOLERANCE
                    and min(d, h) > max(b, f) + POSITION_TOLERANCE
                ):
                    gaps.append("AUTHORING_TABLE_ORDER_OR_REUSE_UNVERIFIED")
        result["tables"] = rows
        result["matched_tables"] = len(rows)
    finally:
        result["work_units"] = budget["work_units"]
        document.close()
    result["gaps"] = list(dict.fromkeys(gaps))
    result["coverage"] = "partial" if gaps else "complete"
    return result
