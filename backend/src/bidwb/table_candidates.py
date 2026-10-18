"""原页网格与 OCR 归属候选，不推断合并单元格或跨页语义。"""

from __future__ import annotations

from bisect import bisect_right
from itertools import pairwise
from typing import Any

SCHEMA = "table-candidates-1"


def _centres(values: list[int]) -> list[int]:
    groups: list[list[int]] = []
    for value in values:
        if not groups or value > groups[-1][-1] + 1:
            groups.append([])
        groups[-1].append(value)
    return [round(sum(group) / len(group)) for group in groups]


def assign_cells(xs: list[float], ys: list[float], lines: list[dict[str, Any]]) -> dict[str, Any]:
    """只归属完整落在一个格内的 OCR 行，跨格或重叠行保留为未归属。"""
    cells: list[list[list[int]]] = [[[] for _ in xs[1:]] for _ in ys[1:]]
    unassigned: list[int] = []
    for index, line in enumerate(lines):
        x0, y0, x1, y1 = line["bbox"]
        if x1 <= xs[0] or x0 >= xs[-1] or y1 <= ys[0] or y0 >= ys[-1]:
            continue
        col = bisect_right(xs, (x0 + x1) / 2) - 1
        row = bisect_right(ys, (y0 + y1) / 2) - 1
        if (
            0 <= row < len(cells)
            and 0 <= col < len(cells[0])
            and x0 >= xs[col] - 0.002
            and x1 <= xs[col + 1] + 0.002
            and y0 >= ys[row] - 0.002
            and y1 <= ys[row + 1] + 0.002
        ):
            cells[row][col].append(index)
        else:
            unassigned.append(index)
    rows = [
        ["\n".join(lines[i]["text"] for i in sorted(indices, key=lambda i: (lines[i]["bbox"][1], lines[i]["bbox"][0]))) for indices in row]
        for row in cells
    ]
    return {
        "rows": rows,
        "bbox": [xs[0], ys[0], xs[-1], ys[-1]],
        "source": "raster_grid",
        "column_boundaries": xs,
        "row_boundaries": ys,
        "cell_line_indices": cells,
        "unassigned_line_indices": unassigned,
        "issues": ["ocr_cell_assignment_ambiguous"] if unassigned else [],
    }


def raster_tables(image: Any, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """隔离识别进程内使用现有 OpenCV；仅支持近水平／垂直的完整清晰网格。"""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    binary = (gray < 180).astype(np.uint8) * 255
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((1, max(30, width // 20)), dtype=np.uint8))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((max(30, height // 20), 1), dtype=np.uint8))
    contours, _ = cv2.findContours(cv2.bitwise_or(horizontal, vertical), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables: list[dict[str, Any]] = []
    for contour in sorted(contours, key=lambda item: (cv2.boundingRect(item)[1], cv2.boundingRect(item)[0])):
        x, y, w, h = cv2.boundingRect(contour)
        if w < width * 0.15 or h < 40:
            continue
        xs = _centres(np.flatnonzero(np.count_nonzero(vertical[y : y + h, x : x + w], axis=0) >= h * 0.8).tolist())
        ys = _centres(np.flatnonzero(np.count_nonzero(horizontal[y : y + h, x : x + w], axis=1) >= w * 0.8).tolist())
        if not (3 <= len(xs) <= 101 and 3 <= len(ys) <= 1001):
            continue
        if min(b - a for a, b in pairwise(xs)) < 8 or min(b - a for a, b in pairwise(ys)) < 8:
            continue
        tables.append(assign_cells([round((x + v) / width, 6) for v in xs], [round((y + v) / height, 6) for v in ys], lines))
        if len(tables) == 20:
            break
    return tables


def structure_catalog(enrichment: dict[str, Any]) -> dict[str, Any]:
    """原生／扫描表均保留原页，跨页只记录重复表头和列对齐的候选对。"""
    tables = []
    for page in sorted(enrichment.get("pages", []), key=lambda item: item["physical_page"]):
        for index, table in enumerate(page.get("tables", [])):
            tables.append({"table_id": f"table_{page['physical_page']}_{index}", "physical_page": page["physical_page"], **table})
    links = []
    for left in tables:
        for right in tables:
            if right["physical_page"] != left["physical_page"] + 1 or left["bbox"][3] < 0.75 or right["bbox"][1] > 0.25:
                continue
            if len(left["rows"]) < 2 or len(right["rows"]) < 2:
                continue
            first, second = _header(left["rows"][0]), _header(right["rows"][0])
            if len(first) < 2 or first != second or sum(bool(cell) for cell in first) < 2:
                continue
            if max(abs(left["bbox"][i] - right["bbox"][i]) for i in (0, 2)) > 0.02:
                continue
            lx, rx = left.get("column_boundaries"), right.get("column_boundaries")
            if lx is None or rx is None or len(lx) != len(rx) or any(abs(a - b) > 0.02 for a, b in zip(lx, rx, strict=True)):
                continue
            if len(lx) != len(first) + 1:
                continue
            links.append(
                {
                    "from_table_id": left["table_id"],
                    "to_table_id": right["table_id"],
                    "from_page": left["physical_page"],
                    "to_page": right["physical_page"],
                    "reason": "adjacent_pages_repeated_header_aligned_columns",
                    "review": "pending",
                }
            )
    return {"schema": SCHEMA, "review": "pending", "tables": tables, "cross_page_candidates": links}


def _header(row: list[str | None]) -> list[str]:
    return ["".join((cell or "").split()) for cell in row]
