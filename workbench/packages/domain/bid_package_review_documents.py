"""Exact member evidence reader for package inputs; never picks the latest parse.

Database evidence matching is not original-byte verification or execution readiness.
The caller owns a repeatable-read snapshot; object storage belongs outside that transaction.
"""

from typing import Any

from packages.domain.bid_package_repository import read_parse_identity
from packages.domain.bid_packages import PackageError, require


def read_member(c: Any, bid: str, member: dict[str, Any]) -> dict[str, Any]:
    frozen = member["parse"]
    require(frozen["status"] == "frozen", "PACKAGE_REVIEW_PARSE_UNPROVEN")
    row = c.execute(
        """SELECT v.id AS document_version_id,v.blob_id,b.digest,b.byte_size,b.object_key,
        p.id AS parse_id,p.parser_digest,p.config_digest,p.page_count,p.coverage,p.gaps
        FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id
        JOIN design.parse_runs p ON p.bid_id=v.bid_id AND p.document_version_id=v.id
        WHERE v.bid_id=%s AND v.id=%s AND p.id=%s""",
        (bid, member["document_version_id"], frozen["parse_run_id"]),
    ).fetchone()
    require(row is not None, "PACKAGE_REVIEW_DOCUMENT_BINDING_MISMATCH")
    require(
        row["digest"] == member["file_digest"] and row["page_count"] == member["page_count"],
        "PACKAGE_REVIEW_DOCUMENT_BINDING_MISMATCH",
    )
    actual = read_parse_identity(
        c, bid, member["document_version_id"], frozen["parse_run_id"], lock=False
    )
    require(
        actual.parser_digest == frozen["parser_digest"]
        and actual.config_digest == frozen["config_digest"]
        and actual.evidence_digest == frozen["evidence_digest"],
        "PACKAGE_REVIEW_EVIDENCE_CHANGED",
    )
    pages = c.execute(
        "SELECT physical_page,quality,gaps FROM design.pages WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page",
        (bid, frozen["parse_run_id"]),
    ).fetchall()
    blocks = c.execute(
        """SELECT id,physical_page,ordinal,kind,text_content,bbox,structure,digest
        FROM design.evidence_blocks WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page,ordinal,id""",
        (bid, frozen["parse_run_id"]),
    ).fetchall()
    return dict(row) | {"member_id": member["member_id"], "pages": pages, "blocks": blocks}


def evidence_matches(c: Any, manifest: dict[str, Any]) -> bool:
    # Unknown parses have their own policy blocker; they are never guessed from time/latest.
    expected_errors = {
        "PACKAGE_REVIEW_DOCUMENT_BINDING_MISMATCH",
        "PACKAGE_REVIEW_EVIDENCE_CHANGED",
        "PACKAGE_PARSE_BINDING_MISMATCH",
        "PACKAGE_PARSE_INCOMPLETE",
        "PACKAGE_EVIDENCE_DIGEST_MISMATCH",
    }
    for role in ("target", "authority"):
        for member in manifest[role]["manifest"]["members"]:
            if member["parse"]["status"] != "frozen":
                continue
            try:
                read_member(c, manifest["bid_id"], member)
            except PackageError as error:
                if error.code not in expected_errors:
                    raise
                return False
    return True
