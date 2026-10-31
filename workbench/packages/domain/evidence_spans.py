"""Exact, uniquely identified same-page source spans over frozen evidence blocks."""

from typing import Any


def unique_cross_block_span(documents, text, cited_ids):
    """Return raw character ranges only for a unique contiguous, fully cited match.

    Offsets are zero-based Python Unicode code-point offsets, with an exclusive end.
    No whitespace, punctuation, case, or other source characters are changed.
    """
    if not isinstance(text, str) or not text:
        return None
    candidates = []
    for document in documents:
        if not document.get("document_version_id") or not document.get("parse_id"):
            continue
        blocks = document.get("blocks", [])
        groups: list[list[dict[str, Any]]] = []
        for block in blocks:
            if (
                not isinstance(block.get("physical_page"), int)
                or not isinstance(block.get("ordinal"), int)
                or not isinstance(block.get("text_content"), str)
                or not block.get("id")
            ):
                groups.append([])
                continue
            if (
                not groups
                or not groups[-1]
                or block["physical_page"] != groups[-1][-1]["physical_page"]
                or block["ordinal"] != groups[-1][-1]["ordinal"] + 1
            ):
                groups.append([])
            groups[-1].append(block)
        for group in groups:
            if not group:
                continue
            source = "".join(block["text_content"] for block in group)
            start = source.find(text)
            while start != -1:
                end = start + len(text)
                # A substring cut from the middle of a clause can discard a
                # qualifier. Only complete sentence-like boundaries qualify.
                previous = source[:start].rstrip()
                start_boundary = (bool(previous) and previous[-1] in "。！？") or (
                    not previous and group[0]["ordinal"] == 0
                )
                end_boundary = text[-1] in "。！？"
                position = 0
                pieces = []
                for block in group:
                    next_position = position + len(block["text_content"])
                    lo, hi = max(start, position), min(end, next_position)
                    if lo < hi:
                        pieces.append(
                            {
                                "evidence_id": str(block["id"]),
                                "ordinal": block["ordinal"],
                                "start": lo - position,
                                "end": hi - position,
                            }
                        )
                    position = next_position
                candidates.append(
                    {
                        "document_version_id": str(document["document_version_id"]),
                        "parse_id": str(document["parse_id"]),
                        "physical_page": group[0]["physical_page"],
                        "blocks": pieces,
                        "complete_boundary": start_boundary and end_boundary,
                    }
                )
                if len(candidates) > 1:
                    return None
                start = source.find(text, start + 1)
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if (
        len(candidate["blocks"]) < 2
        or not candidate.pop("complete_boundary")
        or not all(piece["evidence_id"] in cited_ids for piece in candidate["blocks"])
        or any(
            right["ordinal"] != left["ordinal"] + 1
            for left, right in zip(candidate["blocks"], candidate["blocks"][1:], strict=False)
        )
    ):
        return None
    return candidate
