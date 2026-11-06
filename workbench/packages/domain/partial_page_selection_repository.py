"""Private, read-only observation of a user-selected page range.

This is not a complete-parse binding and is never a model dispatch permit.
"""

from packages.domain.partial_page_selection import SelectionError, candidate
from packages.domain.runtime import DomainError, clean


def observe(c, bid_id, document_id, parse_id, first_page, last_page, purpose, *, current):
    row = c.execute(
        """SELECT p.bid_id::text,p.document_version_id::text,p.id::text AS parse_run_id,
        b.digest::text AS file_digest,p.parser_digest::text,p.config_digest::text,
        p.page_count,p.coverage,p.gaps,profile.current_material_id::text AS current_material_id,
        EXISTS(SELECT 1 FROM design.material_assignments a
          WHERE a.bid_id=p.bid_id AND a.snapshot_id=profile.current_material_id
          AND a.document_version_id=p.document_version_id) AS current_document,
        EXISTS(SELECT 1 FROM design.uploads u WHERE u.bid_id=p.bid_id
          AND u.verified_version_id=p.document_version_id AND u.state='verified'
          AND u.declared_digest=b.digest AND u.declared_size=b.byte_size AND u.role=f.role) AS verified_upload,
        d.artifact_kind,f.role
        FROM design.parse_runs p JOIN design.document_versions d
          ON d.id=p.document_version_id AND d.bid_id=p.bid_id
        JOIN design.blobs b ON b.id=d.blob_id
        JOIN design.document_file_versions fv ON fv.bid_id=d.bid_id AND fv.version_id=d.id
        JOIN design.document_files f ON f.id=fv.file_id AND f.bid_id=fv.bid_id
        JOIN design.bid_profiles profile ON profile.bid_id=p.bid_id
        WHERE p.bid_id=%s AND p.document_version_id=%s AND p.id=%s"""
        + (" FOR SHARE OF p" if current else ""),
        (bid_id, document_id, parse_id),
    ).fetchone()
    if (
        row is None
        or not row["verified_upload"]
        or row["artifact_kind"] not in {"source_original", "bid_body"}
        or row["role"] not in {"tender", "supplement", "drawing", "boq", "body", "other"}
    ):
        raise DomainError(
            "PARTIAL_SCOPE_SOURCE_UNAVAILABLE", "未找到已核验的原件及指定解析记录。", 404
        )
    prohibited = c.execute(
        """WITH RECURSIVE provenance(id,policy_class) AS (
        SELECT id,policy_class FROM retrieval.source_nodes WHERE document_version_id=%s
        UNION SELECT n.id,n.policy_class FROM provenance p
        JOIN retrieval.lineage_edges e ON e.child_id=p.id
        JOIN retrieval.source_nodes n ON n.id=e.parent_id)
        SELECT id FROM provenance WHERE policy_class<>'prebid_content' LIMIT 1""",
        (document_id,),
    ).fetchone()
    if prohibited is not None:
        raise DomainError(
            "PARTIAL_SCOPE_SOURCE_POLICY_REJECTED", "该来源不适用于当前投标前参考。", 409
        )
    if current and not row["current_document"]:
        raise DomainError("PARTIAL_SCOPE_SOURCE_NOT_CURRENT", "请选择当前已入库的原件。", 409)
    source = clean(
        {
            key: row[key]
            for key in (
                "bid_id",
                "document_version_id",
                "parse_run_id",
                "file_digest",
                "parser_digest",
                "config_digest",
                "page_count",
                "coverage",
                "gaps",
            )
        }
    )
    pages = clean(
        c.execute(
            "SELECT physical_page,quality,gaps FROM design.pages WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page",
            (bid_id, parse_id),
        ).fetchall()
    )
    blocks = clean(
        c.execute(
            """SELECT id::text,physical_page,ordinal,kind,text_content,digest::text
        FROM design.evidence_blocks WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page,ordinal,id LIMIT 20001""",
            (bid_id, parse_id),
        ).fetchall()
    )
    try:
        value = candidate(
            source=source,
            pages=pages,
            blocks=blocks,
            first_page=first_page,
            last_page=last_page,
            purpose=purpose,
        )
    except SelectionError as error:
        raise DomainError(str(error), "页范围或解析依据无法核验。", 409) from error
    return value, bool(row["current_document"]), row["current_material_id"]
