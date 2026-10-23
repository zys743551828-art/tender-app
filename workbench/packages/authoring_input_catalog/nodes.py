"""Stable nodes from an explicitly saved snapshot, with current heads only as blockers."""

from packages.assistant.generation import node_text, nodes
from packages.authoring import content, snapshot_structure
from packages.authoring_input_catalog import policy
from packages.domain.runtime import clean
from packages.work_contexts import authoring_repository


def project_blockers(c, bid):
    row = c.execute(
        "SELECT phase,archived_at FROM design.bid_profiles WHERE bid_id=%s", (bid,)
    ).fetchone()
    if row is None:
        policy.fail("NOT_FOUND", "该项目没有可读取的业务资料", 404)
    return (
        ["PROJECT_WORK_CLOSED"]
        if row["archived_at"] is not None or row["phase"] in {"closed", "terminated"}
        else []
    )


def catalog(c, bid, snapshot_id, section_id, expected_snapshot_digest, expected_section_digest):
    blockers = project_blockers(c, bid)
    saved = authoring_repository.snapshot(c, bid, snapshot_id)
    selection = saved["selection"]
    if selection["snapshot_digest"] != expected_snapshot_digest:
        policy.fail("SELECTION_CHANGED", "所选快照与预期摘要不一致，未替换为当前稿件", 412)
    matches = [s for s in saved["document"]["sections"] if s["section_id"] == section_id]
    if len(matches) != 1:
        policy.fail("NOT_FOUND", "明确快照中没有这个章节", 404)
    section = matches[0]
    if section["digest"] != expected_section_digest:
        policy.fail("SELECTION_CHANGED", "所选章节与预期正文摘要不一致", 412)
    draft = c.execute(
        "SELECT revision FROM design.drafts WHERE bid_id=%s AND id=%s",
        (bid, selection["draft_id"]),
    ).fetchone()
    heads = c.execute(
        """SELECT s.id::text AS section_id,r.revision AS selected_revision,s.head_revision
        FROM design.draft_snapshot_sections link
        JOIN design.section_revisions r ON r.bid_id=link.bid_id AND r.draft_id=link.draft_id AND r.id=link.section_revision_id
        JOIN design.sections s ON s.bid_id=r.bid_id AND s.draft_id=r.draft_id AND s.id=r.section_id
        WHERE link.bid_id=%s AND link.snapshot_id=%s ORDER BY s.id""",
        (bid, snapshot_id),
    ).fetchall()
    policy.check(draft is not None and len(heads) == len(saved["document"]["sections"]))
    if draft["revision"] != selection["draft_revision"]:
        blockers.append("AUTHORING_PACKAGE_DRAFT_CHANGED")
    if any(row["head_revision"] != row["selected_revision"] for row in heads):
        blockers.append("AUTHORING_PACKAGE_SECTION_CHANGED")
    plain = not any(content.has_rich(s["content"]) for s in saved["document"]["sections"])
    if not plain:
        blockers.append("AUTHORING_PACKAGE_RICH_TARGET_UNSUPPORTED")
    extension = snapshot_structure.snapshot_extension(saved["native"])
    supported = True
    if extension:
        bound = c.execute(
            "SELECT id::text,digest FROM design.authoring_structure_versions WHERE bid_id=%s AND snapshot_id=%s",
            (bid, snapshot_id),
        ).fetchone()
        policy.check(
            bound is not None
            and bound["id"] == extension["id"]
            and bound["digest"] == extension["digest"]
        )
        supported = not (
            extension["plans"]
            or extension["metadata"].get("format_bindings")
            or extension["metadata"].get("word_import_sources")
        )
    if not supported:
        blockers.append("AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED")
    stable = nodes(section["content"])
    policy.check(len({n["node_id"] for n in stable}) == len(stable))
    selected = [item for item in stable if item["node"]["type"] in {"paragraph", "heading"}]
    if len(selected) > 10000:
        policy.fail("CAPACITY_EXCEEDED", "完整稳定节点目录超过读取预算，未截断章节", 413)
    if not selected:
        blockers.append("AUTHORING_PACKAGE_TEXT_NODE_REQUIRED")
    return {
        "protocol": "package-authoring-node-catalog/1",
        "bid_id": bid,
        "target": {
            "draft_id": selection["draft_id"],
            "snapshot_id": snapshot_id,
            "snapshot_digest": expected_snapshot_digest,
            "base_draft_revision": selection["draft_revision"],
            "section_id": section_id,
            "section_revision_id": section["section_revision_id"],
            "base_section_revision": section["section_revision"],
            "section_digest": expected_section_digest,
            "schema_digest": section["schema_digest"],
        },
        "section_title": section["title"],
        "section_content": section["content"],
        "nodes": [
            {
                "node_id": item["node_id"],
                "before_node_digest": item["before_digest"],
                "node_type": item["node"]["type"],
                "text": node_text(item["node"]),
            }
            for item in selected
        ],
        "unsupported_stable_node_count": len(stable) - len(selected),
        "current_draft_revision": draft["revision"],
        "section_heads": clean(heads),
        "whole_snapshot_plain": plain,
        "structure_supported": supported,
        "blocking_reasons": blockers,
    }
