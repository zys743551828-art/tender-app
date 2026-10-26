"""Bounded two-page, nonmerged, nonrepeating-header table continuation policy."""

MAX_ROWS = 12
PAGE_EDGE_SLACK = 72


def variants(table):
    """Each fragment is reconstructed from an exact contiguous frozen row range."""
    yield table
    if not 2 <= table["rows"] <= MAX_ROWS or any(
        cell["cell"]["attrs"]["rowspan"] != 1 or cell["cell"]["attrs"]["colspan"] != 1
        for cell in table["cells"]
    ):
        return
    signatures = [
        tuple(cell["text"] for cell in table["cells"] if cell["row"] == row)
        for row in range(table["rows"])
    ]
    # Identical rows cannot independently prove which original row was continued.
    if len(set(signatures)) != len(signatures):
        return
    for split in range(1, table["rows"]):
        for start, end in ((0, split), (split, table["rows"])):
            yield table | {
                "rows": end - start,
                "source_rows": [start, end],
                "cells": [
                    cell | {"row": cell["row"] - start}
                    for cell in table["cells"]
                    if start <= cell["row"] < end
                ],
            }


def maximal(candidate, lines, tolerance):
    """Do not accept a sub-grid hiding an extra attached header or omitted row."""
    left, bottom, right, top = candidate["bbox"]
    return not any(
        kind == "v"
        and (abs(value - left) <= tolerance or abs(value - right) <= tolerance)
        and (
            (low < bottom - tolerance and high >= bottom - tolerance)
            or (low <= top + tolerance and high > top + tolerance)
        )
        for kind, value, low, high in lines
    )


def edge_allowed(candidate, table, height, style):
    start, _ = table["source_rows"]
    if start == 0:
        return candidate["bbox"][1] <= style["margin_bottom_twips"] / 20 + PAGE_EDGE_SLACK
    return candidate["bbox"][3] >= height - style["margin_top_twips"] / 20 - PAGE_EDGE_SLACK


def assemble(table, fragments, tolerance):
    if len(fragments) != 2:
        return None
    first, last = sorted(fragments, key=lambda part: part["physical_page"])
    if not (
        first["source_rows"][0] == 0
        and first["source_rows"][1] == last["source_rows"][0]
        and last["source_rows"][1] == table["rows"]
        and last["physical_page"] == first["physical_page"] + 1
        and all(
            abs(a - b) <= tolerance
            for a, b in zip(first["page_size"], last["page_size"], strict=True)
        )
        and abs(first["bbox"][0] - last["bbox"][0]) <= tolerance
        and abs(first["bbox"][2] - last["bbox"][2]) <= tolerance
    ):
        return None
    return {
        "node_id": table["node_id"],
        "physical_page": first["physical_page"],
        "bbox": first["bbox"],
        "fragments": [first, last],
        "cells": [
            cell | {"physical_page": part["physical_page"]}
            for part in (first, last)
            for cell in part["cells"]
        ],
    }


def edge_band(candidate, table, height, style):
    """The first fragment ends body content; the next begins it, with no extra header."""
    if table["source_rows"][0] == 0:
        return style["margin_bottom_twips"] / 20, candidate["bbox"][1] - 1
    return candidate["bbox"][3] + 1, height - style["margin_top_twips"] / 20


def clear_edge_text(candidate, table, characters, height, style):
    low, high = edge_band(candidate, table, height, style)
    return (
        not any(low < box[3] and box[1] < high for _, box, _ in characters) if low < high else True
    )
