"""Stable, bounded caption identities for owned rich-source generation only."""

from typing import Any

from packages.authoring import structure_model
from packages.domain.runtime import DomainError, sha

PROTOCOL = "authoring-rich-caption-anchors/1"
MAX_CAPTIONS = 1000


def entries(snapshot):
    nodes = structure_model.ordered(snapshot["authoring_structure"]["nodes"])
    result: list[dict[str, Any]] = []
    for section_index, (node, section) in enumerate(zip(nodes, snapshot["sections"], strict=True)):
        for block_index, block in enumerate(section["content"]):
            if block["type"] not in {"table", "image"} or not block["attrs"]["caption"]:
                continue
            identity = {"section_id": node["section_id"], "node_id": block["attrs"]["id"]}
            result.append(
                identity
                | {
                    "kind": block["type"],
                    "section_index": section_index,
                    "block_index": block_index,
                    "anchor": "cap_" + sha(identity)[:32],
                    "bookmark_id": 501 + len(result),
                    "text": block["attrs"]["caption"],
                }
            )
    if len(result) > MAX_CAPTIONS or len({item["anchor"] for item in result}) != len(result):
        raise DomainError("AUTHORING_CAPTION_IDENTITY_INVALID", "图表图注身份重复或超过1000项", 422)
    return result
