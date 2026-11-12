"""Local, read-only review of inferred chapter candidates; never repairs evidence.

Run: python -m qa.chapter_candidate_review PARSE.json NEW_PRIVATE_REPORT.json
The output contains private source text. Keep it outside Git and do not share it
without authorization. Only candidates already emitted by the parser are reviewed.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
from pathlib import Path


def _box(block):
    value = block.get("bbox")
    if not isinstance(value, list) or len(value) != 4:
        return None
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in value):
        return None
    if value[2] <= value[0] or value[3] <= value[1]:
        return None
    return value


def _context(block):
    if block is None:
        return None
    return copy.deepcopy(
        {key: block.get(key) for key in ("id", "text_content", "bbox", "confidence", "kind")}
    )


def review_candidates(parsed):
    """Return review prompts, not verified headings, omissions or corrections."""
    locations = {}
    for page in parsed["pages"]:
        blocks = page["blocks"]
        for index, block in enumerate(blocks):
            key = (page["physical_page"], block["id"])
            if key in locations:
                raise ValueError("DUPLICATE_EVIDENCE_REFERENCE")
            locations[key] = (page, blocks, index)
    rows = []
    for chapter in parsed["chapters"]:
        key = (chapter["physical_page"], chapter["evidence_id"])
        if key not in locations:
            raise ValueError("CHAPTER_EVIDENCE_NOT_FOUND")
        page, blocks, index = locations[key]
        block = blocks[index]
        previous = blocks[index - 1] if index else None
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        signals = ["PARSER_CANDIDATE_REQUIRES_HUMAN_REVIEW"]
        if re.match(r"^\d", block["text_content"].lstrip()):
            signals.append("NUMERIC_PREFIX_MAY_BE_HEADING_OR_BODY")
            a, b = _box(previous or {}), _box(block)
            width = page.get("width")
            if a and b and isinstance(width, (int, float)) and math.isfinite(width) and width > 0:
                height = max(a[3] - a[1], b[3] - b[1])
                if (
                    0 <= b[1] - a[3] <= height
                    and a[2] - a[0] >= width * 0.65
                    and b[2] - b[0] >= width * 0.65
                    and abs(a[2] - b[2]) <= height
                ):
                    signals.append("ADJACENT_WIDE_LINES_CHECK_FOR_CONTINUATION")
        rows.append(
            {
                "physical_page": chapter["physical_page"],
                "evidence_id": chapter["evidence_id"],
                "parser_title": chapter["title"],
                "parser_inferred": chapter.get("inferred"),
                "signals": signals,
                "previous_same_page_block": _context(previous),
                "candidate_block": _context(block),
                "next_same_page_block": _context(following),
                "review_decision": "not_reviewed",
            }
        )
    return {
        "report_version": 1,
        "purpose": "private_human_review_only",
        "evidence_modified": False,
        "automatic_heading_acceptance": False,
        "coverage": parsed.get("coverage"),
        "gaps": copy.deepcopy(parsed.get("gaps")),
        "limits": [
            "Signals are prompts, not confidence scores or correctness judgments.",
            "No signal does not mean a correct heading; inspect the original page.",
            "Context is parser block order on the same page, not verified reading order.",
            "No missing headings, cross-page or multi-column continuity are assessed.",
            "Review decisions here do not change parser output or formal eligibility.",
        ],
        "candidates": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    parsed = json.loads(args.source.read_text(encoding="utf-8"))
    report = review_candidates(parsed)
    # Never overwrite an original or an earlier human review.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
