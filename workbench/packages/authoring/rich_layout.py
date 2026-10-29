"""Joint single-column table/image ordering and measured section ownership."""

from typing import Any

from packages.authoring import structure_model

PROTOCOL = "authoring-PDF-rich-layout/2"
POSITION_EPSILON = 0.001


def inspect_layout(snapshot, images, tables, navigation):
    result: dict[str, Any] = {
        "protocol": PROTOCOL,
        "coverage": "complete",
        "gaps": [],
        "objects": [],
    }
    nodes = structure_model.ordered(snapshot["authoring_structure"]["nodes"])
    counters = {"image": 0, "table": 0}
    for section_index, section in enumerate(snapshot["sections"]):
        for block in section["content"]:
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
                return result | {
                    "coverage": "partial",
                    "gaps": ["AUTHORING_RICH_OBJECT_LAYOUT_UNVERIFIED"],
                }
            for part in records[index].get("fragments", [records[index]]):
                result["objects"].append(
                    {
                        "kind": kind,
                        "node_id": block["attrs"]["id"],
                        "section_index": section_index,
                        **{key: part[key] for key in ("physical_page", "bbox")},
                    }
                )
    if not result["objects"]:
        return result
    for previous, current in zip(result["objects"], result["objects"][1:], strict=False):
        if not (
            previous["physical_page"] < current["physical_page"]
            or (
                previous["physical_page"] == current["physical_page"]
                and previous["bbox"][1] + POSITION_EPSILON >= current["bbox"][3]
            )
        ):
            result["gaps"].append("AUTHORING_RICH_OBJECT_ORDER_UNVERIFIED")
            break
    rows = navigation["entries"]
    if (
        navigation["mode"] != "chapter_start_new_page"
        or navigation["navigation_coverage"] != "complete"
        or len(nodes) != len(snapshot["sections"])
        or [row["node_id"] for row in rows] != [node["section_id"] for node in nodes]
    ):
        result["gaps"].append("AUTHORING_RICH_OBJECT_SECTION_UNVERIFIED")
    else:
        for item in result["objects"]:
            index, page = item["section_index"], item["physical_page"]
            row = rows[index]
            end = (
                rows[index + 1]["start_page"] - 1
                if index + 1 < len(rows)
                else navigation["page_count"]
            )
            item["section_id"] = nodes[index]["section_id"]
            item["section_start_page"], item["section_content_end_page"] = row["start_page"], end
            if not (
                row["start_page"] <= page <= end
                and (page != row["start_page"] or item["bbox"][3] <= row["title_bbox"][1] + 0.01)
            ):
                result["gaps"].append("AUTHORING_RICH_OBJECT_SECTION_UNVERIFIED")
                break
    result["gaps"] = list(dict.fromkeys(result["gaps"]))
    result["coverage"] = "partial" if result["gaps"] else "complete"
    return result
