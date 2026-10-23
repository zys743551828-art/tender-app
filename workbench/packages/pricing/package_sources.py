"""Quote only explicitly selected package parses; never resolve a latest parse/body.

The formula uses existing immutable storage. This module supplies its additional
current-use authority, rechecked before publication, simulation and plan saving.
"""

from datetime import datetime
from uuid import UUID

from packages.domain import bid_package_requirement_repository as inventories
from packages.domain.bid_package_review_documents import read_member
from packages.domain.bid_package_review_policy import physical_gaps
from packages.domain.bid_package_service import historical, view
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, clean, etag, now, require_read_committed, sha
from packages.pricing import sources
from packages.rag.indexing import original_source_id, parse_source_id


def fail(code, message):
    raise DomainError("PRICING_PACKAGE_" + code, message, 409)


def _effective(head, bid, at):
    def instant(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

    known, start, end = (instant(head[key]) for key in ("known_at", "valid_from", "valid_until"))
    return (
        head["bid_id"] == str(bid)
        and head["policy_class"] == "prebid_content"
        and head["status"] == "published"
        and known is not None
        and known <= at
        and start is not None
        and start <= at
        and (end is None or end > at)
    )


def observe(c, *, bid, binding):
    require_read_committed(c)
    # Same serialization order as package/source writers, including read-time authority checks.
    profile = sources.enabled_bid(c, bid, lock=True)
    c.execute("SELECT pg_advisory_xact_lock(90127,1)")
    try:
        target = historical(c, bid, binding["package_id"], binding["revision_id"])
        authority = historical(
            c, bid, binding["authority_package_id"], binding["authority_revision_id"]
        )
        if target.kind.value != "bid" or authority.kind.value != "authority":
            fail("KIND_MISMATCH", "请明确选择投标包和对应的招标补遗包")
        if target.scope != authority.scope or target.scope.bidder_status != "confirmed":
            fail("IDENTITY_MISMATCH", "报价两包的工程、标段、轮次或投标主体不一致或未确认")
        if not target.members or not authority.members or not authority.formal_eligible:
            fail("INPUT_INCOMPLETE", "报价需要实际投标包和已完整解析的招标补遗包")
        if physical_gaps(authority.manifest(), "authority"):
            fail("AUTHORITY_GAP", "招标补遗包存在未声明页段，不能据部分条款报价")
        current_identity = c.execute(
            "SELECT design.identity_snapshot_v2(%s) AS value", (bid,)
        ).fetchone()["value"]
        selected = [view(c, target), view(c, authority)]
        if any(item["identity"]["digest"] != current_identity["digest"] for item in selected):
            fail("IDENTITY_CHANGED", "当前项目主体或轮次已变化，请重新选择对应资料包")
        heads = c.execute(
            "SELECT package_id::text,revision_id::text FROM design.bid_package_heads WHERE package_id=ANY(%s::uuid[]) ORDER BY package_id",
            ([target.package_id, authority.package_id],),
        ).fetchall()
        heads = {row["package_id"]: row["revision_id"] for row in heads}
        if any(heads.get(item.package_id) != item.revision_id for item in (target, authority)):
            fail("REVISION_CHANGED", "投标包或招标补遗包已有新修订，旧方案仅保留历史原值")
        for member in authority.manifest()["members"]:
            read_member(c, str(bid), member)
    except PackageError as error:
        raise DomainError(error.code, "明确选择的报价包或精确解析无法核验", 409) from error
    ids = []
    for package in (target, authority):
        for member in package.members:
            expected = [(original_source_id(UUID(member.document_version_id)), member.file_digest)]
            if member.parse.status == "frozen":
                expected.append(
                    (parse_source_id(UUID(member.parse.parse_run_id)), member.file_digest)
                )
            for identity, expected_digest in expected:
                node = c.execute(
                    "SELECT document_version_id::text,digest,kind FROM retrieval.source_nodes WHERE id=%s",
                    (identity,),
                ).fetchone()
                if (
                    node is None
                    or node["document_version_id"] != member.document_version_id
                    or node["digest"] != expected_digest
                    or node["kind"] != "document"
                ):
                    fail("SOURCE_UNPROVEN", "包内原件或所选解析的来源身份尚未完整登记")
                ids.append(identity)
            if (
                member.parse.status == "frozen"
                and not c.execute(
                    "SELECT 1 FROM retrieval.lineage_edges WHERE child_id=%s AND parent_id=%s",
                    (expected[1][0], expected[0][0]),
                ).fetchone()
            ):
                fail("LINEAGE_UNPROVEN", "所选解析未关联包内的确切原件")
    ancestry = sources.parent_heads(c, sorted(set(ids)))
    at = now()
    if {row["source_id"] for row in ancestry} != {str(identity) for identity in ids} or any(
        not _effective(row, bid, at) for row in ancestry
    ):
        fail("SOURCE_STALE", "包内资料或其祖先已失效、未发布、用途不符或属于其他项目")
    documents = c.execute(
        """SELECT v.version_id::text AS document_version_id,f.role FROM design.document_file_versions v
        JOIN design.document_files f ON f.id=v.file_id WHERE v.bid_id=%s
        AND v.version_id=ANY(%s::uuid[]) AND f.role IN ('tender','supplement')
        ORDER BY f.role,v.version_id""",
        (bid, [member.document_version_id for member in authority.members]),
    ).fetchall()
    members = {member.document_version_id: member for member in authority.members}
    scope = {
        "bid_id": str(bid),
        "round_id": target.scope.round_id,
        "effective_documents": [
            dict(row) | {"digest": members[row["document_version_id"]].file_digest}
            for row in documents
        ],
    }
    if not documents:
        fail("RULE_SOURCE_MISSING", "所选招标补遗包没有可用于报价条款的招标文件或补遗")
    head = inventories.head(c, target.revision_id)
    rule_set = c.execute(
        "SELECT current_rule_set_id FROM design.bid_profiles WHERE bid_id=%s", (bid,)
    ).fetchone()["current_rule_set_id"]
    snapshot = {
        "version": "package-pricing-authority/1",
        "binding": binding,
        "package_digest": target.manifest_digest,
        "authority_digest": authority.manifest_digest,
        "identity_digest": current_identity["digest"],
        "source_heads_digest": sha(ancestry),
        "rule_set_id": str(rule_set) if rule_set else None,
        "inventory_id": head["id"] if head else None,
        "inventory_digest": head["digest"] if head else None,
    }
    return scope, members, clean(snapshot), ancestry, profile


def context(c, bid, binding):
    scope, members, snapshot, heads, profile = observe(c, bid=bid, binding=binding)
    value = {
        "bid_id": str(bid),
        "material_snapshot_id": None,
        "material_revision": profile["material_revision"],
        "scope": scope,
        "parses": [
            {
                "id": members[item["document_version_id"]].parse.parse_run_id,
                "document_version_id": item["document_version_id"],
            }
            for item in scope["effective_documents"]
        ],
        "source_heads": [
            {
                key: row[key]
                for key in ("id", "digest", "revision", "status", "valid_from", "valid_until")
            }
            for row in heads
        ],
        "package_binding": binding,
        "package_snapshot": snapshot,
    }
    return value, etag("package-pricing-context", bid, sha(value))


def exact_sources(c, *, bid, quotes, binding):
    scope, members, snapshot, _, _ = observe(c, bid=bid, binding=binding)
    allowed = {item["document_version_id"] for item in scope["effective_documents"]}
    ids, seen = [], set()
    for quote in quotes:
        if quote["evidence_id"] in seen:
            fail("DUPLICATE_EVIDENCE", "请合并相同原页证据的支持字段")
        seen.add(quote["evidence_id"])
        member = members.get(str(quote["document_version_id"]))
        if (
            member is None
            or member.document_version_id not in allowed
            or str(quote["parse_id"]) != member.parse.parse_run_id
            or str(quote["source_id"]) != str(parse_source_id(UUID(member.parse.parse_run_id)))
            or not any(
                part.first_page <= quote["physical_page"] <= part.last_page for part in member.parts
            )
        ):
            fail("QUOTE_OUTSIDE_SELECTION", "报价原文不属于明确选择包的冻结解析与页段")
        row = c.execute(
            """SELECT e.text_content,h.revision FROM design.evidence_blocks e
            JOIN retrieval.source_heads h ON h.source_id=%s
            WHERE e.bid_id=%s AND e.id=%s AND e.parse_id=%s AND e.physical_page=%s""",
            (
                quote["source_id"],
                bid,
                quote["evidence_id"],
                quote["parse_id"],
                quote["physical_page"],
            ),
        ).fetchone()
        if row is None or row["revision"] != quote["source_revision"]:
            fail("QUOTE_CHANGED", "报价引文或来源版本已变化，请重新读取明确选择的原页")
        if not quote["quote"].strip() or quote["quote"].strip() != row["text_content"].strip():
            raise DomainError("PRICING_QUOTE_INVALID", "请引用完整证据块，不得省略同段条件", 422)
        ids.append(UUID(str(quote["source_id"])))
    parents = sources.parent_heads(c, sorted(set(ids)))
    if any(row["kind"] != "document" for row in parents):
        fail(
            "RULE_ANCESTOR_UNSUPPORTED",
            "报价条款须有原件与解析来源，当前不接受推导特征作为条款祖先",
        )
    return {
        "scope": scope,
        "ancestor_heads": parents,
        "package_snapshot": snapshot,
    }


def source_choices(c, bid, binding, *, limit=50, cursor=None):
    scope, members, _, _, _ = observe(c, bid=bid, binding=binding)
    parses = [
        members[item["document_version_id"]].parse.parse_run_id
        for item in scope["effective_documents"]
    ]
    rows = c.execute(
        """SELECT e.*,p.document_version_id,d.original_name FROM design.evidence_blocks e
        JOIN design.parse_runs p ON p.id=e.parse_id JOIN design.document_versions d ON d.id=p.document_version_id
        WHERE e.bid_id=%s AND e.parse_id=ANY(%s::uuid[]) AND (%s::uuid IS NULL OR e.id>%s)
        ORDER BY e.id LIMIT %s""",
        (bid, parses, cursor, cursor, limit + 1),
    ).fetchall()
    choices = []
    for row in rows[:limit]:
        source_id = parse_source_id(row["parse_id"])
        head = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source_id,)
        ).fetchone()
        choices.append(
            {
                "source_id": str(source_id),
                "source_revision": head["revision"] if head else None,
                "document_version_id": str(row["document_version_id"]),
                "parse_id": str(row["parse_id"]),
                "physical_page": row["physical_page"],
                "evidence_id": str(row["id"]),
                "filename": row["original_name"],
                "quote": row["text_content"],
                "source_registered": head is not None,
            }
        )
    return {
        "items": choices,
        "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
    }
