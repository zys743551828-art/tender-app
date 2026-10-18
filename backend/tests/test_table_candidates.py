from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from bidwb.parse_enrichment import PageEnrichment, candidate_chunks
from bidwb.table_candidates import assign_cells, structure_catalog


def test_cell_assignment_retains_empty_and_ambiguous_lines() -> None:
    lines = [
        {"text": "工程", "bbox": [0.12, 0.12, 0.3, 0.18]},
        {"text": "15.12", "bbox": [0.6, 0.12, 0.8, 0.18]},
        {"text": "跨格不应猜测", "bbox": [0.3, 0.25, 0.7, 0.3]},
        {"text": "页外正文", "bbox": [0.1, 0.8, 0.8, 0.9]},
    ]
    table = assign_cells([0.1, 0.5, 0.9], [0.1, 0.2, 0.4], lines)
    assert table["rows"] == [["工程", "15.12"], ["", ""]]
    assert table["cell_line_indices"] == [[[0], [1]], [[], []]]
    assert table["unassigned_line_indices"] == [2]
    payload = {
        "physical_page": 1,
        "source_sha256": "fixture",
        "ocr_status": "recognized_pending",
        "table_status": "extracted_pending",
        "lines": [{**line, "confidence": 0.99} for line in lines],
        "tables": [table],
    }
    PageEnrichment.model_validate(payload)
    chunks = candidate_chunks({"pages": [payload]})
    tables = [chunk for chunk in chunks if chunk.kind == "table"]
    assert len(tables) == 1 and tables[0].source == "raster_grid" and tables[0].numeric_review_required
    assert tables[0].quote == "工程 | 15.12"
    assert any(chunk.quote == "跨格不应猜测" and chunk.kind == "visual_observation" for chunk in chunks)
    payload["tables"][0]["cell_line_indices"][0][0] = [99]
    with pytest.raises(ValidationError, match="invalid OCR line references"):
        PageEnrichment.model_validate(payload)


def test_continuation_needs_adjacent_edges_header_and_column_positions() -> None:
    left = {"rows": [["工程", "金额"], ["A", "15.12"]], "bbox": [0.1, 0.5, 0.9, 0.95], "column_boundaries": [0.1, 0.5, 0.9]}
    right = {"rows": [["工程", "金额"], ["B", "16"]], "bbox": [0.1, 0.05, 0.9, 0.5], "column_boundaries": [0.1, 0.5, 0.9]}
    payload = {"pages": [{"physical_page": 1, "tables": [left]}, {"physical_page": 2, "tables": [right]}]}
    result = structure_catalog(payload)
    assert len(result["cross_page_candidates"]) == 1
    assert result["cross_page_candidates"][0]["review"] == "pending"
    assert result["tables"][0]["rows"] == left["rows"] and result["tables"][1]["rows"] == right["rows"]
    for mutation in ("header", "columns", "edge", "nonadjacent", "unknown"):
        changed = deepcopy(payload)
        table = changed["pages"][1]["tables"][0]
        if mutation == "header":
            table["rows"][0] = ["工期", "天数"]
        elif mutation == "columns":
            table["column_boundaries"] = [0.1, 0.7, 0.9]
        elif mutation == "edge":
            table["bbox"][1] = 0.4
        elif mutation == "nonadjacent":
            changed["pages"][1]["physical_page"] = 3
        else:
            table.pop("column_boundaries")
        assert structure_catalog(changed)["cross_page_candidates"] == []
