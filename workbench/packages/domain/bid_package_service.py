"""Authenticated API orchestration; derive identities from committed originals only."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from packages.domain import bid_package_repository as repository
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
from packages.domain.review_identity import canonical
from packages.domain.runtime import DomainError, clean, etag, fetch, sha
from packages.identity import pagination
from packages.knowledge import sources
from packages.lifecycle.service import assert_work_writable


def lock_bid(c, bid_id):
    fetch(c, "SELECT id FROM design.bids WHERE id=%s FOR UPDATE", (bid_id,))


def directory(
    c, bid_id, collection, *, limit=20, cursor=None, kind=None, package_id=None, document_id=None
):
    """Signed keyset discovery; exact IDs, never choose latest parse or body."""
    fetch(c, "SELECT id FROM design.bids WHERE id=%s", (bid_id,))
    scope = sha(
        {
            "directory": "bid-package-" + collection + "/1",
            "bid_id": str(bid_id),
            "package_id": str(package_id) if package_id else None,
            "document_id": str(document_id) if document_id else None,
            "kind": kind,
        }
    )
    after = pagination.decode(cursor, scope)
    last_id = after[-1] if after else None
    if collection == "heads":
        rows = repository._all(
            c,
            """SELECT p.id,p.bid_id,p.kind,h.revision_id,h.revision,h.digest
        FROM design.bid_packages p JOIN design.bid_package_heads h ON h.package_id=p.id
        WHERE p.bid_id=%s AND (%s::text IS NULL OR p.kind=%s) AND (%s::uuid IS NULL OR p.id>%s)
        ORDER BY p.id LIMIT %s""",
            (bid_id, kind, kind, last_id, last_id, limit + 1),
        )
    elif collection == "revisions":
        fetch(
            c, "SELECT id FROM design.bid_packages WHERE bid_id=%s AND id=%s", (bid_id, package_id)
        )
        rows = repository._all(
            c,
            """SELECT r.id,r.package_id,r.revision,r.digest,r.created_at
        FROM design.bid_package_revisions r WHERE r.package_id=%s
        AND (%s::uuid IS NULL OR (r.revision,r.id)<(%s::bigint,%s))
        ORDER BY r.revision DESC,r.id DESC LIMIT %s""",
            (package_id, last_id, after[0] if after else None, last_id, limit + 1),
        )
    elif collection == "documents":
        roles = ["tender", "supplement", "drawing", "boq"] if kind == "authority" else ["body"]
        rows = repository._all(
            c,
            """SELECT d.id,d.bid_id,v.file_id,v.revision AS file_revision,
        d.original_name AS filename,f.role,d.artifact_kind,b.digest AS sha256,
        EXISTS(SELECT 1 FROM design.uploads u WHERE u.bid_id=d.bid_id AND u.verified_version_id=d.id
        AND u.state='verified' AND u.role=f.role AND u.declared_digest=b.digest AND u.declared_size=b.byte_size) AS verified_upload
        FROM design.document_file_versions v JOIN design.document_files f ON f.id=v.file_id
        JOIN design.document_versions d ON d.id=v.version_id AND d.bid_id=v.bid_id
        JOIN design.blobs b ON b.id=d.blob_id WHERE d.bid_id=%s AND f.role=ANY(%s)
        AND (%s::uuid IS NULL OR d.id>%s) ORDER BY d.id LIMIT %s""",
            (bid_id, roles, last_id, last_id, limit + 1),
        )
    else:
        fetch(
            c,
            "SELECT id FROM design.document_versions WHERE bid_id=%s AND id=%s",
            (bid_id, document_id),
        )
        rows = repository._all(
            c,
            """SELECT id,document_version_id,coverage,page_count,gaps,
        parser_digest,config_digest,created_at FROM design.parse_runs WHERE bid_id=%s AND document_version_id=%s
        AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s""",
            (bid_id, document_id, last_id, last_id, limit + 1),
        )
    items = clean(rows[:limit])
    return {
        "items": items,
        "has_more": len(rows) > limit,
        "next_cursor": pagination.encode(
            scope,
            [str(items[-1]["revision"]) if collection == "revisions" else "", items[-1]["id"]],
        )
        if len(rows) > limit
        else None,
    }


def head(c, bid_id, package_id):
    row = repository._one(
        c,
        """SELECT h.revision_id::text,h.digest FROM design.bid_package_heads h
        JOIN design.bid_packages p ON p.id=h.package_id WHERE p.bid_id=%s AND p.id=%s""",
        (bid_id, package_id),
    )
    if row is None:
        raise PackageError("PACKAGE_NOT_FOUND")
    return repository.load_revision(c, str(bid_id), row["revision_id"])


def head_tag(package):
    return etag("bid-package-head", package.package_id, package.manifest_digest)


def historical(c, bid_id, package_id, revision_id):
    package = repository.load_revision(c, str(bid_id), str(revision_id))
    require(package.package_id == str(package_id), "PACKAGE_REVISION_NOT_FOUND")
    return package


def evidence_directory(c, bid_id, package_id, revision_id, *, limit=20, cursor=None):
    """Discover IDs within the exact saved parse/parts; historical sources remain identifiable."""
    package = historical(c, bid_id, package_id, revision_id)
    scope = sha(
        {
            "directory": "bid-package-evidence/1",
            "bid_id": str(bid_id),
            "package_id": str(package_id),
            "revision_id": str(revision_id),
            "package_digest": package.manifest_digest,
        }
    )
    after = pagination.decode(cursor, scope)
    if after and after[0] != "":
        raise DomainError("INVALID_CURSOR", "资料包证据游标不属于当前冻结修订", 422)
    last_id = after[-1] if after else None
    ranges = [
        {
            "document_version_id": member.document_version_id,
            "parse_run_id": member.parse.parse_run_id,
            "part_id": part.part_id,
            "first_page": part.first_page,
            "last_page": part.last_page,
        }
        for member in package.members
        if member.parse.status == "frozen"
        for part in member.parts
    ]
    rows = repository._all(
        c,
        """WITH frozen AS (
          SELECT * FROM jsonb_to_recordset(%s::jsonb) AS f(
            document_version_id uuid,parse_run_id uuid,part_id text,first_page integer,last_page integer))
        SELECT e.id,p.document_version_id,p.id AS parse_run_id,e.physical_page,
          array_agg(DISTINCT f.part_id ORDER BY f.part_id) AS part_ids
        FROM frozen f JOIN design.parse_runs p
          ON p.id=f.parse_run_id AND p.document_version_id=f.document_version_id AND p.bid_id=%s
        JOIN design.evidence_blocks e ON e.bid_id=p.bid_id AND e.parse_id=p.id
          AND e.physical_page BETWEEN f.first_page AND f.last_page
        WHERE (%s::uuid IS NULL OR e.id>%s)
        GROUP BY e.id,p.document_version_id,p.id,e.physical_page ORDER BY e.id LIMIT %s""",
        (Jsonb(ranges), bid_id, last_id, last_id, limit + 1),
    )
    items = clean(rows[:limit])
    return {
        "revision_id": package.revision_id,
        "package_digest": package.manifest_digest,
        "items": items,
        "has_more": len(rows) > limit,
        "next_cursor": pagination.encode(scope, ["", items[-1]["id"]])
        if len(rows) > limit
        else None,
    }


def view(c, package):
    return {
        "manifest": package.manifest(),
        "digest": package.manifest_digest,
        "identity": repository.load_frozen_identity(c, package.scope.bid_id, package.revision_id),
        # Storage eligibility is explicitly not source effectivity/compliance/score readiness.
        "storage_eligible": package.formal_eligible,
        "review_ready": False,
    }


def manifest_bytes(c, bid_id, package_id, revision_id):
    package = historical(c, bid_id, package_id, revision_id)
    # Decode/validate only the persisted immutable manifest. Never read current materials/profile.
    return canonical(package.manifest()), package.manifest_digest


def current_scope(c, bid_id):
    row = repository._one(c, "SELECT design.identity_snapshot_v2(%s) AS value", (bid_id,))
    value = row["value"] if row else None
    if not isinstance(value, dict) or not value.get("lot_id"):
        raise PackageError("PACKAGE_STABLE_LOT_REQUIRED")
    return BidScope(
        value["engineering_project_id"],
        value["lot_id"],
        value["round_id"],
        str(bid_id),
        value["bidder_id"],
        value["binding_status"],
    )


def member(c, scope, kind, item):
    row = repository._one(
        c,
        """SELECT f.id::text AS file_id,f.role,v.revision,b.digest,b.byte_size,d.artifact_kind
        FROM design.document_file_versions v JOIN design.document_files f ON f.id=v.file_id
        JOIN design.document_versions d ON d.bid_id=v.bid_id AND d.id=v.version_id
        JOIN design.blobs b ON b.id=d.blob_id
        WHERE v.bid_id=%s AND v.version_id=%s FOR SHARE OF f""",
        (scope.bid_id, item["document_version_id"]),
    )
    if row is None:
        raise PackageError("PACKAGE_COMMITTED_DOCUMENT_REQUIRED")
    allowed = (
        {"tender", "supplement", "drawing", "boq"} if kind == PackageKind.AUTHORITY else {"body"}
    )
    require(row["role"] in allowed, "PACKAGE_DOCUMENT_ROLE_REJECTED")
    require(
        row["artifact_kind"]
        == ("source_original" if kind == PackageKind.AUTHORITY else "bid_body"),
        "PACKAGE_ORIGINAL_REQUIRED",
    )
    prohibited = repository._one(
        c,
        """WITH RECURSIVE provenance(id,policy_class) AS (
        SELECT id,policy_class FROM retrieval.source_nodes WHERE document_version_id=%s
        UNION SELECT n.id,n.policy_class FROM provenance p
        JOIN retrieval.lineage_edges e ON e.child_id=p.id
        JOIN retrieval.source_nodes n ON n.id=e.parent_id)
        SELECT id FROM provenance WHERE policy_class<>'prebid_content' LIMIT 1""",
        (item["document_version_id"],),
    )
    require(prohibited is None, "PACKAGE_SOURCE_POLICY_REJECTED")
    verified = repository._one(
        c,
        """SELECT id FROM design.uploads WHERE bid_id=%s AND verified_version_id=%s
        AND state='verified' AND role=%s AND declared_digest=%s AND declared_size=%s LIMIT 1""",
        (scope.bid_id, item["document_version_id"], row["role"], row["digest"], row["byte_size"]),
    )
    require(verified is not None, "PACKAGE_VERIFIED_UPLOAD_REQUIRED")
    parse_id = item.get("parse_run_id")
    if parse_id:
        identity = repository.read_parse_identity(
            c, scope.bid_id, item["document_version_id"], parse_id
        )
        run = repository._one(
            c, "SELECT page_count FROM design.parse_runs WHERE id=%s", (parse_id,)
        )
        if run is None:
            raise PackageError("PACKAGE_PARSE_BINDING_MISMATCH")
        page_count = run["page_count"]
    else:
        require(not item["parts"], "PACKAGE_PARSE_SELECTION_REQUIRED")
        identity = ParseIdentity("not_frozen", reason="No exact parse run selected")
        page_count = None
    return PackageMember(
        item["member_id"],
        item["document_version_id"],
        row["digest"],
        "authority" if kind == PackageKind.AUTHORITY else "own",
        f"document-file:{row['file_id']}:revision:{row['revision']}",
        scope,
        tuple(item["purposes"]),
        page_count,
        identity,
        tuple(
            DocumentPart(**(p | {"heading_path": tuple(p.get("heading_path", []))}))
            for p in item["parts"]
        ),
    )


def create_revision(c, bid_id, body, previous=None):
    assert_work_writable(c, bid_id)
    # Same graph authority lock as all source/lineage writers. Keep bid -> graph -> parse.
    # READ COMMITTED obtains a fresh policy snapshot after any preceding graph writer.
    sources.lock_graph(c)
    scope = current_scope(c, bid_id)
    if previous:
        require(
            all(
                getattr(scope, k) == getattr(previous.scope, k)
                for k in ("engineering_project_id", "lot_id", "round_id", "bid_id", "bidder_id")
            ),
            "PACKAGE_PROFILE_SCOPE_MISMATCH",
        )
    kind = previous.kind if previous else PackageKind(body["kind"])
    package = PackageRevision(
        previous.package_id if previous else str(uuid4()),
        str(uuid4()),
        previous.revision + 1 if previous else 1,
        kind,
        scope,
        tuple(member(c, scope, kind, item) for item in body["members"]),
        previous.manifest_digest if previous else None,
    )
    repository.save_revision(
        c, package, expected_digest=previous.manifest_digest if previous else None
    )
    return package
