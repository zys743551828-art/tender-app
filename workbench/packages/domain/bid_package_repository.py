"""F01存储切片：调用方提供连接，事务内冻结真实主数据与解析；无API入口。

DDL依赖 core.sql -> domain.sql -> bid-packages.sql，仅用于新环境。
主体状态派生自既有identity.bound审计，绝不建立第二份可写身份状态。
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from jsonschema import Draft202012Validator
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.domain.bid_packages import (
    BidScope,
    DocumentPart,
    PackageError,
    PackageKind,
    PackageMember,
    PackageRevision,
    ParseIdentity,
    require,
)
from packages.domain.review_identity import digest


def _uuid(value: str) -> str:
    try:
        normalized = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise PackageError("PACKAGE_STORAGE_UUID_REQUIRED") from error
    require(normalized == value, "PACKAGE_STORAGE_UUID_REQUIRED")
    return normalized


def _one(c: Any, query: str, parameters: tuple[Any, ...]) -> dict[str, Any] | None:
    with c.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, parameters).fetchone()


def _all(c: Any, query: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
    with c.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, parameters).fetchall()


def _strings(value: dict[str, Any]) -> dict[str, Any]:
    return {key: str(item) if isinstance(item, UUID) else item for key, item in value.items()}


def identity_snapshot(c: Any, scope: BidScope) -> dict[str, Any]:
    """Same association fields and authority rule as identity.repository.snapshot.

    Current bid is locked, matching existing record_binding's serialization lock.
    An old package is read through load_revision, never reconstructed from this view.
    """
    row = _one(
        c,
        """SELECT p.bidder_id,b.name AS bidder_name,p.round_id,
        r.engineering_project_id,e.title AS engineering_title,e.region,e.engineering_type,
        r.lot,r.round_no,r.lot_id FROM design.bids z
        JOIN design.bid_profiles p ON p.bid_id=z.id JOIN design.bidders b ON b.id=p.bidder_id
        JOIN design.bid_rounds r ON r.id=p.round_id
        JOIN design.engineering_projects e ON e.id=r.engineering_project_id
        WHERE z.id=%s FOR UPDATE OF z,p,r,e,b""",
        (scope.bid_id,),
    )
    if row is None:
        raise PackageError("PACKAGE_PROFILE_NOT_FOUND")
    current = _strings(row)
    require(current.pop("lot_id") == scope.lot_id, "PACKAGE_LOT_BINDING_MISMATCH")
    require(
        all(
            current[field] == getattr(scope, field)
            for field in ("bidder_id", "round_id", "engineering_project_id")
        ),
        "PACKAGE_PROFILE_SCOPE_MISMATCH",
    )
    authority = _one(
        c,
        """SELECT id,payload FROM design.audit_entries
        WHERE bid_id=%s AND event_type='identity.bound'
        ORDER BY coalesce((payload->>'identity_epoch')::bigint,0) DESC,created_at DESC,id DESC LIMIT 1""",
        (scope.bid_id,),
    )
    confirmed = bool(
        authority
        and authority["payload"].get("after") == current
        and authority["payload"].get("confirmed") is True
    )
    if confirmed:
        registered = _one(
            c,
            """SELECT id FROM design.audit_entries
            WHERE event_type='identity.bidder_registered' AND payload->>'bidder_id'=%s LIMIT 1""",
            (scope.bidder_id,),
        )
        require(registered is not None, "PACKAGE_BIDDER_REGISTRATION_REQUIRED")
    status = "confirmed" if confirmed else "pending"
    require(scope.bidder_status == status, "PACKAGE_BINDING_STATUS_MISMATCH")
    value = current | {
        "binding_status": status,
        "authority_id": str(authority["id"]) if authority else None,
    }
    return value | {"digest": digest(value)}


def read_parse_identity(
    c: Any, bid_id: str, document_version_id: str, parse_run_id: str
) -> ParseIdentity:
    """Freezeable evidence identity of actual ordered DB records, not a latest-run guess.

    JSONB geometry/structure/gaps are encoded as PostgreSQL text, so protocol/1 has
    no floating point values. Evidence text must match its existing SHA256.
    The caller keeps the transaction open until save_revision freezes this run.
    """
    row = _one(
        c,
        """SELECT parser_digest,config_digest,page_count,coverage,gaps FROM design.parse_runs
        WHERE bid_id=%s AND document_version_id=%s AND id=%s FOR UPDATE""",
        (bid_id, document_version_id, parse_run_id),
    )
    if row is None:
        raise PackageError("PACKAGE_PARSE_BINDING_MISMATCH")
    pages = _all(
        c,
        """SELECT physical_page,printed_label,width::text,height::text,rotation,
        quality,gaps::text FROM design.pages WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page""",
        (bid_id, parse_run_id),
    )
    blocks = _all(
        c,
        """SELECT id::text,physical_page,ordinal,kind,text_content,
        bbox::text,structure::text,digest::text FROM design.evidence_blocks
        WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page,ordinal,id""",
        (bid_id, parse_run_id),
    )
    require(
        row["coverage"] == "complete"
        and row["gaps"] == []
        and row["page_count"] > 0
        and len(pages) == row["page_count"]
        and all(
            page["physical_page"] == ordinal
            and page["quality"] == "usable"
            and page["gaps"] == "[]"
            for ordinal, page in enumerate(pages, start=1)
        ),
        "PACKAGE_PARSE_INCOMPLETE",
    )
    require(
        all(hashlib.sha256(b["text_content"].encode()).hexdigest() == b["digest"] for b in blocks),
        "PACKAGE_EVIDENCE_DIGEST_MISMATCH",
    )
    evidence_digest = digest(
        {
            "identity_version": "package-parse-evidence/1",
            "parse_run_id": parse_run_id,
            "pages": pages,
            "blocks": blocks,
        }
    )
    return ParseIdentity(
        "frozen", parse_run_id, row["parser_digest"], row["config_digest"], evidence_digest
    )


def _freeze_member(c: Any, member: PackageMember) -> None:
    version = _one(
        c,
        """SELECT b.digest FROM design.document_versions v
        JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s AND v.id=%s FOR SHARE OF v,b""",
        (member.scope.bid_id, member.document_version_id),
    )
    require(
        version is not None and version["digest"] == member.file_digest,
        "PACKAGE_DOCUMENT_BINDING_MISMATCH",
    )
    if member.parse.status == "not_frozen":
        return
    if member.parse.parse_run_id is None:
        raise PackageError("PACKAGE_PARSE_BINDING_MISMATCH")
    actual = read_parse_identity(
        c, member.scope.bid_id, member.document_version_id, member.parse.parse_run_id
    )
    require(actual == member.parse, "PACKAGE_PARSE_BINDING_MISMATCH")
    run = _one(
        c, "SELECT page_count FROM design.parse_runs WHERE id=%s", (member.parse.parse_run_id,)
    )
    require(
        run is not None and run["page_count"] == member.page_count,
        "PACKAGE_PARSE_PAGE_COUNT_MISMATCH",
    )
    values = {
        "parse_run_id": member.parse.parse_run_id,
        "bid_id": member.scope.bid_id,
        "document_version_id": member.document_version_id,
        "file_digest": member.file_digest,
        "parser_digest": member.parse.parser_digest,
        "config_digest": member.parse.config_digest,
        "evidence_digest": member.parse.evidence_digest,
        "page_count": member.page_count,
    }
    c.execute(
        """INSERT INTO design.bid_package_parse_bindings
        (parse_run_id,bid_id,document_version_id,file_digest,parser_digest,config_digest,evidence_digest,page_count)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(parse_run_id) DO NOTHING""",
        tuple(values.values()),
    )
    stored = _one(
        c,
        "SELECT * FROM design.bid_package_parse_bindings WHERE parse_run_id=%s",
        (member.parse.parse_run_id,),
    )
    require(stored is not None and _strings(stored) == values, "PACKAGE_PARSE_ID_REBOUND")


def save_revision(
    c: Any, package: PackageRevision, *, expected_digest: str | None
) -> dict[str, Any]:
    """Atomic revision append + head CAS; identical revision replay never rewinds head.

    Requires a dedicated storage connection/transaction from the caller. No commits
    escape an enclosing transaction. Historical replay reads its saved authority.
    """
    for value in (
        package.package_id,
        package.revision_id,
        package.scope.bid_id,
        package.scope.bidder_id,
        package.scope.engineering_project_id,
        package.scope.lot_id,
        package.scope.round_id,
    ):
        _uuid(value)
    for member in package.members:
        _uuid(member.document_version_id)
        if member.parse.parse_run_id:
            _uuid(member.parse.parse_run_id)
    try:
        with c.transaction():
            return _save_revision(c, package, expected_digest)
    except psycopg.IntegrityError as error:
        raise PackageError("PACKAGE_STORAGE_CONSTRAINT_REJECTED") from error


def _save_revision(c: Any, package: PackageRevision, expected_digest: str | None) -> dict[str, Any]:
    isolation = _one(c, "SELECT current_setting('transaction_isolation') AS level", ())
    require(
        isolation is not None and isolation["level"] == "read committed",
        "PACKAGE_ISOLATION_REQUIRES_READ_COMMITTED",
    )
    # Serialize all new package writes in the same order as ordinary identity changes.
    require(
        _one(c, "SELECT id FROM design.bids WHERE id=%s FOR UPDATE", (package.scope.bid_id,))
        is not None,
        "PACKAGE_PROFILE_NOT_FOUND",
    )
    replay = _one(
        c,
        "SELECT package_id,digest FROM design.bid_package_revisions WHERE id=%s",
        (package.revision_id,),
    )
    if replay:
        require(
            str(replay["package_id"]) == package.package_id
            and replay["digest"] == package.manifest_digest,
            "PACKAGE_REVISION_REPLAY_CONFLICT",
        )
        return {"revision_id": package.revision_id, "digest": replay["digest"], "replayed": True}
    identity = identity_snapshot(c, package.scope)
    c.execute(
        """INSERT INTO design.bid_packages
        (id,bid_id,kind,engineering_project_id,lot_id,round_id,bidder_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
        (
            package.package_id,
            package.scope.bid_id,
            package.kind.value,
            package.scope.engineering_project_id,
            package.scope.lot_id,
            package.scope.round_id,
            package.scope.bidder_id,
        ),
    )
    base = _one(
        c, "SELECT * FROM design.bid_packages WHERE id=%s FOR UPDATE", (package.package_id,)
    )
    expected_base = {
        "id": package.package_id,
        "bid_id": package.scope.bid_id,
        "kind": package.kind.value,
        "engineering_project_id": package.scope.engineering_project_id,
        "lot_id": package.scope.lot_id,
        "round_id": package.scope.round_id,
        "bidder_id": package.scope.bidder_id,
    }
    require(base is not None and _strings(base) == expected_base, "PACKAGE_SCOPE_MISMATCH")
    head = _one(
        c,
        "SELECT * FROM design.bid_package_heads WHERE package_id=%s FOR UPDATE",
        (package.package_id,),
    )
    require(
        (head is None and expected_digest is None and package.revision == 1)
        or (
            head is not None
            and head["digest"] == expected_digest == package.predecessor_digest
            and package.revision == head["revision"] + 1
        ),
        "PACKAGE_CAS_MISMATCH",
    )
    # Stable lock order across packages sharing sources avoids inverse member-order deadlocks.
    for member in sorted(
        package.members, key=lambda member: member.parse.parse_run_id or member.document_version_id
    ):
        _freeze_member(c, member)
    c.execute(
        """INSERT INTO design.bid_package_revisions
        (id,package_id,revision,predecessor_digest,digest,manifest,identity_authority_id,identity_digest,bidder_status,identity_snapshot)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            package.revision_id,
            package.package_id,
            package.revision,
            package.predecessor_digest,
            package.manifest_digest,
            Jsonb(package.manifest()),
            identity["authority_id"],
            identity["digest"],
            package.scope.bidder_status,
            Jsonb(identity),
        ),
    )
    for ordinal, (member, payload) in enumerate(
        zip(package.members, package.manifest()["members"], strict=True)
    ):
        c.execute(
            """INSERT INTO design.bid_package_members
            (revision_id,member_id,ordinal,bid_id,document_version_id,file_digest,parse_run_id,payload)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                package.revision_id,
                member.member_id,
                ordinal,
                package.scope.bid_id,
                member.document_version_id,
                member.file_digest,
                member.parse.parse_run_id,
                Jsonb(payload),
            ),
        )
        for part_order, part in enumerate(member.parts):
            c.execute(
                """INSERT INTO design.bid_package_parts
                (revision_id,member_id,part_id,ordinal,category,first_page,last_page,shared_attachment,heading_path)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    package.revision_id,
                    member.member_id,
                    part.part_id,
                    part_order,
                    part.category,
                    part.first_page,
                    part.last_page,
                    part.shared_attachment,
                    Jsonb(list(part.heading_path)),
                ),
            )
    if head is None:
        c.execute(
            "INSERT INTO design.bid_package_heads VALUES(%s,%s,%s,%s)",
            (package.package_id, package.revision_id, package.revision, package.manifest_digest),
        )
    else:
        c.execute(
            """UPDATE design.bid_package_heads SET revision_id=%s,revision=%s,digest=%s
            WHERE package_id=%s AND digest=%s""",
            (
                package.revision_id,
                package.revision,
                package.manifest_digest,
                package.package_id,
                expected_digest,
            ),
        )
    return {
        "revision_id": package.revision_id,
        "digest": package.manifest_digest,
        "replayed": False,
    }


def load_revision(c: Any, bid_id: str, revision_id: str) -> PackageRevision:
    row = _one(
        c,
        """SELECT r.manifest,r.digest FROM design.bid_package_revisions r
        JOIN design.bid_packages p ON p.id=r.package_id WHERE p.bid_id=%s AND r.id=%s""",
        (_uuid(bid_id), _uuid(revision_id)),
    )
    if row is None:
        raise PackageError("PACKAGE_REVISION_NOT_FOUND")
    value = row["manifest"]
    try:
        require(
            _manifest_validator().is_valid(value) and digest(value) == row["digest"],
            "PACKAGE_STORED_MANIFEST_CORRUPT",
        )
        return _decode_manifest(value)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise PackageError("PACKAGE_STORED_MANIFEST_CORRUPT") from error


@lru_cache(maxsize=1)
def _manifest_validator() -> Draft202012Validator:
    path = Path(__file__).resolve().parents[1] / "contracts/schemas/bid-package.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _decode_manifest(value: dict[str, Any]) -> PackageRevision:
    members = []
    for item in value["members"]:
        parts = tuple(
            DocumentPart(**(part | {"heading_path": tuple(part["heading_path"])}))
            for part in item["parts"]
        )
        members.append(
            PackageMember(
                **(
                    item
                    | {
                        "scope": BidScope(**item["scope"]),
                        "purposes": tuple(item["purposes"]),
                        "parse": ParseIdentity(**item["parse"]),
                        "parts": parts,
                    }
                )
            )
        )
    return PackageRevision(
        **(
            value
            | {
                "kind": PackageKind(value["kind"]),
                "scope": BidScope(**value["scope"]),
                "members": tuple(members),
            }
        )
    )


def load_frozen_identity(c: Any, bid_id: str, revision_id: str) -> dict[str, Any]:
    row = _one(
        c,
        """SELECT r.identity_snapshot,r.identity_digest FROM design.bid_package_revisions r
        JOIN design.bid_packages p ON p.id=r.package_id WHERE p.bid_id=%s AND r.id=%s""",
        (_uuid(bid_id), _uuid(revision_id)),
    )
    if row is None:
        raise PackageError("PACKAGE_REVISION_NOT_FOUND")
    try:
        value = row["identity_snapshot"]
        require(
            isinstance(value, dict)
            and value.get("digest") == row["identity_digest"]
            and digest({k: v for k, v in value.items() if k != "digest"}) == row["identity_digest"],
            "PACKAGE_STORED_IDENTITY_CORRUPT",
        )
        return value
    except (ValueError, TypeError, KeyError) as error:
        raise PackageError("PACKAGE_STORED_IDENTITY_CORRUPT") from error
