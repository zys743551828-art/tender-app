"""Exact one-document parse method and result validation; no body/material adoption."""

import json
import math
from pathlib import Path

from packages.domain.parsing_profile import configured_parser
from packages.domain.runtime import DomainError, sha
from packages.parsing.physical_pdf import CONFIG_DIGEST, PARSER_DIGEST

HANDLER = "document-parse/1"
STEP = "parse-document"
KIND = "document-parse-start"
MAX_BYTES = 100 * 1024 * 1024
MAX_PAGES = 1000
ROOT = Path(__file__).resolve().parents[2]


def implementation_digest():
    return sha(
        {
            name: sha((ROOT / name).read_bytes())
            for name in (
                "packages/domain/document_parse_policy.py",
                "packages/domain/document_parses.py",
                "packages/parsing/physical_pdf.py",
                "packages/parsing/http_port.py",
                "apps/worker/document_parse_handlers.py",
                "packages/authoring/package_outputs.py",
            )
        }
    )


def method():
    """The optional loopback parser identity probe must run without an open DB."""
    parser = configured_parser()
    return {
        "protocol": "document-parse-method/1",
        "mode": "configured_local" if parser else "physical_text_only",
        "parser_digest": parser.parser_digest if parser else PARSER_DIGEST,
        "config_digest": parser.config_digest if parser else CONFIG_DIGEST,
        "implementation_digest": implementation_digest(),
        "max_bytes": MAX_BYTES,
        "max_pages": MAX_PAGES,
    }, parser


def invalid():
    raise DomainError(
        "DOCUMENT_PARSE_RESULT_INVALID", "解析结果的页、文本、摘要或覆盖声明不一致", 409
    )


def normalize(result, selected, *, frozen=False):
    """Preserve actual geometry/structure. No rounding or completeness upgrade."""
    try:
        if (
            result.get("parser_digest") != selected["parser_digest"]
            or result.get("config_digest") != selected["config_digest"]
            or result["coverage"] not in {"usable", "complete", "partial", "failed"}
            or not isinstance(result["pages"], list)
            or not isinstance(result["gaps"], list)
            or not 0 <= len(result["pages"]) <= MAX_PAGES
        ):
            invalid()
        coverage = "complete" if result["coverage"] == "usable" else result["coverage"]
        if selected["mode"] == "physical_text_only" and coverage == "complete":
            invalid()
        gaps = []
        for gap in result["gaps"]:
            if isinstance(gap, dict):
                if type(gap["physical_page"]) is not int or not isinstance(gap["code"], str):
                    invalid()
                gap = f"物理页{gap['physical_page']}:{gap['code']}"
            if not isinstance(gap, str) or not 1 <= len(gap) <= 1000:
                invalid()
            gaps.append(gap)
        if len(gaps) > 10000 or (coverage == "complete" and (gaps or not result["pages"])):
            invalid()
        pages, block_count = [], 0
        for index, original in enumerate(result["pages"], start=1):
            width, height = original["width"], original["height"]
            if (
                original["physical_page"] != index
                or type(original["physical_page"]) is not int
                or type(width) not in {int, float}
                or type(height) not in {int, float}
                or not math.isfinite(width * height)
                or min(width, height) <= 0
                or type(original["rotation"]) is not int
                or original["rotation"] not in {0, 90, 180, 270}
                or original["quality"] not in {"usable", "partial", "failed"}
                or not isinstance(original["gaps"], list)
                or any(not isinstance(g, str) or len(g) > 1000 for g in original["gaps"])
            ):
                invalid()
            if coverage == "complete" and (original["quality"] != "usable" or original["gaps"]):
                invalid()
            blocks = original.get("blocks")
            if blocks is None:
                text = original["text"]
                blocks = (
                    [
                        {
                            "ordinal": 0,
                            "kind": "text",
                            "text_content": text,
                            "digest": sha(text.encode()),
                            "bbox": None,
                        }
                    ]
                    if text.strip()
                    else []
                )
            if not isinstance(blocks, list):
                invalid()
            normalized = []
            for ordinal, block in enumerate(blocks):
                text = block["text_content"]
                area = block["bbox"]
                if (
                    block["ordinal"] != ordinal
                    or type(block["ordinal"]) is not int
                    or block.get("physical_page", index) != index
                    or block["kind"] not in {"text", "table", "visual_observation"}
                    or not isinstance(text, str)
                    or len(text.encode()) > 8 * 1024 * 1024
                    or "\x00" in text
                    or sha(text.encode()) != block["digest"]
                ):
                    invalid()
                if area is not None and (
                    not isinstance(area, list)
                    or len(area) != 4
                    or any(type(x) not in {int, float} or not math.isfinite(x) for x in area)
                    or not 0 <= area[0] < area[2] <= width
                    or not 0 <= area[1] < area[3] <= height
                ):
                    invalid()
                if frozen:
                    structure = block["structure"]
                    if structure is not None and (
                        not isinstance(structure, dict)
                        or not set(structure) <= {"method", "chapter_path", "confidence", "tables"}
                    ):
                        invalid()
                else:
                    structure = {
                        key: block[key]
                        for key in ("method", "chapter_path", "confidence")
                        if key in block
                    }
                    if block["kind"] == "table":
                        structure["tables"] = [
                            table for table in original.get("tables", []) if table["bbox"] == area
                        ]
                normalized.append(
                    {
                        "ordinal": ordinal,
                        "kind": block["kind"],
                        "text_content": text,
                        "digest": block["digest"],
                        "bbox": area,
                        "structure": structure or None,
                    }
                )
            block_count += len(normalized)
            if block_count > 100000:
                invalid()
            pages.append(
                {
                    key: original[key]
                    for key in ("physical_page", "width", "height", "rotation", "quality", "gaps")
                }
                | {"blocks": normalized}
            )
        parsed = {
            "pages": pages,
            "coverage": coverage,
            "gaps": gaps,
            "parser_digest": selected["parser_digest"],
            "config_digest": selected["config_digest"],
        }
        encoded(parsed)
        return parsed
    except (
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        AttributeError,
        UnicodeError,
        RecursionError,
    ) as error:
        raise DomainError("DOCUMENT_PARSE_RESULT_INVALID", "解析结果未满足原页协议", 409) from error


def encoded(value):
    # PostgreSQL JSONB cannot represent NUL, including an escaped NUL in a key or
    # a nested table cell. Reject it before publication without altering text.
    pending, seen = [value], set()
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if "\x00" in item:
                invalid()
        elif isinstance(item, (dict, list)) and id(item) not in seen:
            seen.add(id(item))
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    invalid()
                pending.extend(item.keys())
                pending.extend(item.values())
            else:
                pending.extend(item)
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(raw) > 64 * 1024 * 1024:
        raise DomainError("DOCUMENT_PARSE_RESULT_TOO_LARGE", "解析内容超过单次安全保存上限", 413)
    return raw
