"""Current metadata beside a fixed authoring snapshot, without new-use admission."""

from packages.authoring import package_outputs
from packages.authoring.repository import source_authority_manifest
from packages.domain.review_identity import digest
from packages.domain.runtime import clean
from packages.work_contexts import policy


def draft_head(c, selected):
    row = c.execute(
        """SELECT d.revision,s.id::text AS snapshot_id,s.digest AS snapshot_digest
        FROM design.drafts d LEFT JOIN design.draft_snapshots s
          ON s.bid_id=d.bid_id AND s.draft_id=d.id AND s.revision=d.revision
        WHERE d.bid_id=%s AND d.id=%s""",
        (selected["bid_id"], selected["draft_id"]),
    ).fetchone()
    baseline = {
        "revision": selected["draft_revision"],
        "snapshot_id": selected["snapshot_id"],
        "snapshot_digest": selected["snapshot_digest"],
    }
    if row is None or row["snapshot_id"] is None:
        return policy.dimension("unknown", "CURRENT_DRAFT_SNAPSHOT_MISSING", digest(baseline))
    return policy.compare(baseline, row)


def sources(c, saved, at):
    refs = package_outputs._references(saved["native"])
    imports = package_outputs._import_source_ids(saved["native"])
    ids = sorted({ref["source_id"] for ref in refs} | set(imports))
    if not ids:
        return policy.dimension("not_applicable", "NO_SOURCE_REFERENCES_DECLARED")
    baseline = {"references": refs, "import_source_ids": imports}
    rows = source_authority_manifest(c, [{"source_id": identity} for identity in ids])
    direct = c.execute(
        """SELECT n.id::text,n.document_version_id::text,h.revision FROM retrieval.source_nodes n
        LEFT JOIN retrieval.source_heads h ON h.source_id=n.id WHERE n.id=ANY(%s::uuid[]) ORDER BY n.id""",
        (ids,),
    ).fetchall()
    by_id = {row["id"]: row for row in direct}
    observed = {"graph": rows, "direct": clean(direct)}
    if set(by_id) != set(ids) or {row["source_id"] for row in rows} != set(ids):
        return policy.dimension(
            "unknown", "SOURCE_GRAPH_NOT_ESTABLISHED", digest(baseline), digest(observed)
        )
    same = all(
        by_id[ref["source_id"]]["revision"] == ref["source_revision"]
        and by_id[ref["source_id"]]["document_version_id"] == ref["document_version_id"]
        for ref in refs
    )
    if not same or not policy.effective_sources(rows, at):
        return policy.dimension(
            "changed",
            "SOURCE_REFERENCES_CHANGED_OR_INEFFECTIVE",
            digest(baseline),
            digest(observed),
        )
    # Plain saved snapshots freeze direct source references, not a historical
    # complete ancestry graph or current qualification. Never label that green.
    return policy.dimension(
        "unknown", "REFERENCES_MATCH_QUALIFICATION_UNASSESSED", digest(baseline), digest(observed)
    )


def assets(saved):
    rows = saved["image_heads"]
    if not rows:
        return policy.dimension("not_applicable", "NO_IMAGE_ASSETS_SELECTED")
    baseline = [
        {
            "asset_id": row["asset_id"],
            "revision": row["selected_revision"],
            "version_id": row["selected_version_id"],
            "state": "active",
        }
        for row in rows
    ]
    current = [
        {
            "asset_id": row["asset_id"],
            "revision": row["head_revision"],
            "version_id": row["head_version_id"],
            "state": row["head_state"],
        }
        for row in rows
    ]
    return policy.compare(baseline, current)


def observe(c, saved, at):
    return {
        "draft_head": draft_head(c, saved["selection"]),
        "sources": sources(c, saved, at),
        "assets": assets(saved),
    }
