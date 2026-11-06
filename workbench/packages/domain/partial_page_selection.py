"""Versioned, non-qualifying identities for user-selected partial PDF pages.

This module is intentionally separate from the complete parse/package binding.
It does not grant review, model, export, or business qualification.
"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from uuid import UUID

from packages.domain.review_identity import digest

VERSION = "partial-page-selection/1"
MAX_PAGES = 1000
MAX_BLOCKS = 20000


class SelectionError(ValueError):
    """A stable code without source text, filenames, or credential values."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SelectionError(code)


def _id(value: object) -> bool:
    try:
        return str(UUID(str(value))) == str(value)
    except (ValueError, TypeError, AttributeError):
        return False


def _sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def candidate(*, source, pages, blocks, first_page, last_page, purpose):
    """Build a bounded identity; confirmation and persistence are separate.

    Caller must obtain all inputs from one authenticated database snapshot and
    must recheck the resulting digest before any later use. Text is verified but
    is not copied into this identity. Unknown/gapped pages remain explicit.
    """
    _require(
        isinstance(source, dict)
        and set(source)
        == {
            "bid_id",
            "document_version_id",
            "parse_run_id",
            "file_digest",
            "parser_digest",
            "config_digest",
            "page_count",
            "coverage",
            "gaps",
        }
        and all(_id(source[k]) for k in ("bid_id", "document_version_id", "parse_run_id"))
        and all(_sha(source[k]) for k in ("file_digest", "parser_digest", "config_digest"))
        and source["coverage"] in {"complete", "partial"}
        and isinstance(source["gaps"], list)
        and all(
            isinstance(g, str)
            or (
                isinstance(g, dict)
                and set(g) == {"physical_page", "code"}
                and type(g["physical_page"]) is int
                and 1 <= g["physical_page"] <= MAX_PAGES
                and isinstance(g["code"], str)
            )
            for g in source["gaps"]
        ),
        "PARTIAL_SCOPE_SOURCE_INVALID",
    )
    count = source["page_count"]
    _require(type(count) is int and 1 <= count <= MAX_PAGES, "PARTIAL_SCOPE_PAGE_COUNT_INVALID")
    _require(
        all(not isinstance(gap, dict) or gap["physical_page"] <= count for gap in source["gaps"]),
        "PARTIAL_SCOPE_SOURCE_INVALID",
    )
    _require(
        type(first_page) is int
        and type(last_page) is int
        and 1 <= first_page <= last_page <= count,
        "PARTIAL_SCOPE_RANGE_INVALID",
    )
    _require(
        purpose in {"technical_reference", "requirement_reference"}, "PARTIAL_SCOPE_PURPOSE_INVALID"
    )
    _require(
        isinstance(pages, list)
        and len(pages) == count
        and all(
            isinstance(page, dict)
            and set(page) == {"physical_page", "quality", "gaps"}
            and type(page["physical_page"]) is int
            and page["physical_page"] == index
            and page["quality"] in {"usable", "partial", "failed"}
            and isinstance(page["gaps"], list)
            and all(isinstance(g, str) for g in page["gaps"])
            for index, page in enumerate(pages, 1)
        ),
        "PARTIAL_SCOPE_PAGES_INVALID",
    )
    _require(isinstance(blocks, list) and len(blocks) <= MAX_BLOCKS, "PARTIAL_SCOPE_BLOCK_LIMIT")
    seen = set()
    ordinals = set()
    selected = []
    for block in blocks:
        _require(
            isinstance(block, dict)
            and set(block) == {"id", "physical_page", "ordinal", "kind", "text_content", "digest"}
            and _id(block["id"])
            and block["id"] not in seen
            and type(block["physical_page"]) is int
            and 1 <= block["physical_page"] <= count
            and type(block["ordinal"]) is int
            and block["ordinal"] >= 0
            and (block["physical_page"], block["ordinal"]) not in ordinals
            and block["kind"] in {"text", "table", "visual_observation"}
            and isinstance(block["text_content"], str)
            and _sha(block["digest"])
            and hashlib.sha256(block["text_content"].encode("utf-8")).hexdigest()
            == block["digest"],
            "PARTIAL_SCOPE_BLOCK_INVALID",
        )
        seen.add(block["id"])
        ordinals.add((block["physical_page"], block["ordinal"]))
        if first_page <= block["physical_page"] <= last_page:
            selected.append(
                {k: block[k] for k in ("id", "physical_page", "ordinal", "kind", "digest")}
            )
    selected.sort(key=lambda item: (item["physical_page"], item["ordinal"], item["id"]))
    omitted = []
    if first_page > 1:
        omitted.append({"first_page": 1, "last_page": first_page - 1})
    if last_page < count:
        omitted.append({"first_page": last_page + 1, "last_page": count})
    manifest = {
        "version": VERSION,
        "source": deepcopy(source),
        "purpose": purpose,
        "selection": {"first_page": first_page, "last_page": last_page},
        "selected_pages": deepcopy(pages[first_page - 1 : last_page]),
        "selected_blocks": selected,
        "omitted_ranges": omitted,
        "coverage": "partial",
        "manual_confirmation_recorded": False,
        "original_bytes_reverified": False,
        "model_execution_allowed": False,
        "formal_qualification": False,
    }
    return {"manifest": manifest, "digest": digest(manifest)}
