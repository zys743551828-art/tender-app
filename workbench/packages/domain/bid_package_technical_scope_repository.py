"""Bounded exact technical-scope persistence, context and receipts. No external IO."""

from copy import deepcopy
from datetime import datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from packages.domain import bid_package_requirement_repository as inventories
from packages.domain import bid_package_rule_correction_repository as rules
from packages.domain import package_technical_scope as policy
from packages.domain.bid_package_review_documents import generated_observations, read_member
from packages.domain.bid_package_service import historical, view
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, clean, etag, sha
from packages.rag.indexing import original_source_id, parse_source_id

KIND = "package-technical-scope-freeze"
EVENT = "package.technical_scope_frozen"
RELATION = "design.bid_package_technical_scopes"
MAX_ORIGINAL_BYTES = policy.LIMITS["original_bytes"]


def tag(revision, fingerprint):
    return etag("package-technical-scope-context", revision, fingerprint)


def require_schema(c):
    row = c.execute("SELECT to_regclass(%s) AS relation", (RELATION,)).fetchone()
    if row["relation"] is None:
        policy.failure("UNAVAILABLE", "技术范围冻结数据库尚未安装", 503)
    if not c.execute(
        "SELECT has_table_privilege(current_user,%s,'SELECT') AND has_column_privilege(current_user,%s,'manifest','INSERT') AS allowed",
        (RELATION, RELATION),
    ).fetchone()["allowed"]:
        policy.failure("UNAVAILABLE", "当前运行角色没有技术范围冻结的最小权限", 503)
    if not c.execute(
        "SELECT EXISTS(SELECT FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='uuid-ossp' AND e.extversion='1.1' AND n.nspname='public') AND to_regprocedure('public.uuid_generate_v5(uuid,text)') IS NOT NULL AS available"
    ).fetchone()["available"]:
        policy.failure("UNAVAILABLE", "技术范围缺少已审的uuid-ossp 1.1来源身份依赖", 503)


def request_body(scope, body):
    return {"scope": list(scope), **body}


def command_digest(scope, body, condition):
    return sha({"body": request_body(scope, body), "if_match": condition})


def replay(c, actor, scope, key, body, condition):
    row = c.execute(
        "SELECT id,request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, KIND, scope[2], key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != command_digest(scope, body, condition):
        raise DomainError("IDEMPOTENCY_CONFLICT", "原幂等键对应不同的技术范围冻结请求", 409)
    if row["response"] is None:
        raise DomainError("COMMAND_INCOMPLETE", "原技术范围冻结命令尚未完成", 409)
    result = row["response"]
    ack = result["body"]
    value = load(c, scope, ack["scope"]["manifest"]["id"])
    expected_command = {
        "command_id": str(row["id"]),
        "actor_id": actor,
        "idempotency_key": key,
        "request_digest": row["request_digest"],
        "request": body,
        "if_match": condition,
    }
    if (
        ack != {"scope": value, "command": expected_command}
        or result["status"] != 201
        or result["headers"]
        != {"ETag": etag("package-technical-scope", value["manifest"]["id"], value["digest"])}
    ):
        policy.failure("CORRUPT", "原始命令回执未准确绑定所冻结技术范围", 500)
    return deepcopy(result)


def _document(c, bid, role, member):
    original = c.execute(
        "SELECT v.id::text AS document_version_id,b.digest,b.byte_size FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s AND v.id=%s",
        (bid, member["document_version_id"]),
    ).fetchone()
    if original is None or original["digest"] != member["file_digest"]:
        policy.failure("ORIGINAL_CHANGED", "确切包成员原件已缺失或摘要不一致")
    document = {
        "package_role": role,
        "member_id": member["member_id"],
        "document_version_id": member["document_version_id"],
        "file_digest": member["file_digest"],
        "byte_size": original["byte_size"],
        "parse": deepcopy(member["parse"]),
        "page_count": member["page_count"],
        "pages": [],
        "blocks": [],
    }
    if member["parse"]["status"] == "not_frozen":
        return document
    totals = c.execute(
        "SELECT count(*) AS blocks,coalesce(sum(octet_length(text_content)+octet_length(coalesce(bbox::text,''))+octet_length(coalesce(structure::text,''))+200),0) AS bytes FROM design.evidence_blocks WHERE bid_id=%s AND parse_id=%s",
        (bid, member["parse"]["parse_run_id"]),
    ).fetchone()
    if (
        totals["blocks"] > policy.LIMITS["blocks"]
        or totals["bytes"] > policy.LIMITS["snapshot_bytes"]
    ):
        policy.failure("TOO_LARGE", "原页证据超过完整技术范围容量，未截断", 413)
    page_count = c.execute(
        "SELECT count(*) AS count FROM design.pages WHERE bid_id=%s AND parse_id=%s",
        (bid, member["parse"]["parse_run_id"]),
    ).fetchone()["count"]
    if page_count > policy.LIMITS["pages"]:
        policy.failure("TOO_LARGE", "完整物理页超过技术范围容量，未截断", 413)
    actual = read_member(c, bid, member, check_generated=False)
    document["pages"] = clean(actual["pages"])
    # PostgreSQL's exact JSON text preserves geometry without inventing float
    # canonicalization or changing the package's stored parse evidence digest.
    document["blocks"] = clean(
        c.execute(
            "SELECT id::text,physical_page,ordinal,kind,text_content,digest,bbox::text AS bbox_json,structure::text AS structure_json FROM design.evidence_blocks WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page,ordinal,id",
            (bid, member["parse"]["parse_run_id"]),
        ).fetchall()
    )
    return document


def _sources(c, bid, target, authority, at):
    members = [member for value in (target, authority) for member in value["manifest"]["members"]]
    versions = {m["document_version_id"] for m in members}
    roots = {str(original_source_id(UUID(identity))) for identity in versions}
    roots.update(
        str(parse_source_id(UUID(m["parse"]["parse_run_id"])))
        for m in members
        if m["parse"]["status"] == "frozen"
    )
    nodes = clean(
        c.execute(
            "SELECT id::text,document_version_id::text,digest,kind,policy_class FROM retrieval.source_nodes WHERE id=ANY(%s::uuid[]) ORDER BY id",
            (sorted(roots),),
        ).fetchall()
    )
    rows = clean(
        c.execute(
            "SELECT a.source_id::text,n.id::text AS ancestor_id,n.document_version_id::text,n.digest,n.kind,n.policy_class,n.known_at,h.revision,h.status,h.valid_from,h.valid_until,v.bid_id::text AS document_bid,b.digest AS original_digest FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id LEFT JOIN design.document_versions v ON v.id=n.document_version_id LEFT JOIN design.blobs b ON b.id=v.blob_id WHERE a.source_id=ANY(%s::uuid[]) ORDER BY a.source_id,n.id LIMIT %s",
            (sorted(roots), policy.LIMITS["source_rows"] + 1),
        ).fetchall()
    )
    if len(rows) > policy.LIMITS["source_rows"]:
        policy.failure("TOO_LARGE", "完整来源祖先超过支持容量，未省略来源", 413)
    gaps = []
    expected_roots = {}
    expected_parse_edges = set()
    for member in members:
        expected = (member["document_version_id"], member["file_digest"])
        original_root = str(original_source_id(UUID(expected[0])))
        expected_roots[original_root] = expected
        if member["parse"]["status"] == "frozen":
            parse_root = str(parse_source_id(UUID(member["parse"]["parse_run_id"])))
            expected_roots[parse_root] = expected
            expected_parse_edges.add((parse_root, original_root))
    actual_parse_edges = {
        (str(row["child_id"]), str(row["parent_id"]))
        for row in c.execute(
            "SELECT child_id,parent_id FROM retrieval.lineage_edges WHERE child_id=ANY(%s::uuid[]) AND parent_id=ANY(%s::uuid[])",
            (
                sorted(child for child, _ in expected_parse_edges),
                sorted(parent for _, parent in expected_parse_edges),
            ),
        ).fetchall()
    }
    if not expected_parse_edges <= actual_parse_edges:
        gaps.append(
            policy.gap(
                "SOURCE_LINEAGE_UNPROVEN",
                None,
                "确切冻结解析必须直接派生自对应原件，孤立来源节点不能替代真实派生关系。",
            )
        )
    if (
        {r["id"] for r in nodes} != roots
        or {r["source_id"] for r in rows} != roots
        or {r["source_id"] for r in rows if r["source_id"] == r["ancestor_id"]} != roots
        or any(
            (row["document_version_id"], row["digest"]) != expected_roots[row["id"]]
            for row in nodes
        )
    ):
        gaps.append(
            policy.gap(
                "SOURCE_CLOSURE_UNPROVEN",
                None,
                "成员原件、冻结解析或完整祖先缺少准确来源节点，不能登记新技术范围。",
            )
        )
    for row in rows:
        try:
            valid = (
                row["document_bid"] == bid
                and row["document_version_id"] is not None
                and row["kind"] == "document"
                and row["digest"] == row["original_digest"]
                and row["policy_class"] == "prebid_content"
                and row["status"] == "published"
                and row["revision"] is not None
                and datetime.fromisoformat(row["known_at"]) <= at
                and datetime.fromisoformat(row["valid_from"]) <= at
                and (row["valid_until"] is None or datetime.fromisoformat(row["valid_until"]) > at)
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            gaps.append(
                policy.gap(
                    "SOURCE_UNAVAILABLE",
                    row["ancestor_id"],
                    "来源祖先跨项目、缺原件、用途不符、已撤回、未生效或已到期。",
                )
            )
    versions.update(
        row["document_version_id"] for row in rows if row["document_version_id"] is not None
    )
    originals = clean(
        c.execute(
            "SELECT v.id::text AS document_version_id,b.digest,b.byte_size,b.object_key FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s AND v.id=ANY(%s::uuid[]) ORDER BY v.id",
            (bid, sorted(versions)),
        ).fetchall()
    )
    if {r["document_version_id"] for r in originals} != versions:
        gaps.append(
            policy.gap("SOURCE_ORIGINAL_MISSING", None, "直接原件或祖先原件无法准确归属本项目。")
        )
    if sum(row["byte_size"] for row in originals) > MAX_ORIGINAL_BYTES:
        policy.failure("TOO_LARGE", "本次全部原件超过1GiB核验容量，请保留完整范围并分包组织", 413)
    return rows, originals, list({g["id"]: g for g in gaps}.values())


def observe(c, scope, inventory_id):
    """RR/RO or a final locked RC observation. Never asks for a latest parse."""
    target = view(c, historical(c, *scope))
    inventory = inventories.load_inventory(c, scope[0], scope[1], scope[2], inventory_id)
    authority = rules.authority(c, scope[0], inventory)
    im = inventory["manifest"]
    observed = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
    profile = clean(
        c.execute(
            "SELECT current_rule_set_id::text,phase,archived_at FROM design.bid_profiles WHERE bid_id=%s",
            (scope[0],),
        ).fetchone()
    )
    identity = c.execute("SELECT design.identity_snapshot_v2(%s) AS value", (scope[0],)).fetchone()[
        "value"
    ]
    heads = clean(
        c.execute(
            "SELECT package_id::text,revision_id::text FROM design.bid_package_heads WHERE package_id=ANY(%s::uuid[]) ORDER BY package_id",
            ([scope[1], authority["manifest"]["package_id"]],),
        ).fetchall()
    )
    inventory_head = inventories.head(c, scope[2])
    submission_head = clean(
        c.execute(
            "SELECT submission_id::text,revision FROM design.submission_heads WHERE bid_id=%s",
            (scope[0],),
        ).fetchone()
    )
    sources, originals, blocking = _sources(c, scope[0], target, authority, observed)
    if (
        profile is None
        or profile["archived_at"] is not None
        or profile["phase"] in {"closed", "terminated"}
    ):
        blocking.append(
            policy.gap(
                "PROJECT_CLOSED",
                scope[0],
                "本片仅支持当前事前范围；已关闭或归档项目不能新增当前范围。",
            )
        )
    if submission_head is not None or (profile is not None and profile["phase"] == "submitted"):
        blocking.append(
            policy.gap(
                "AFTER_SUBMISSION",
                scope[0],
                "项目已有实际提交记录；不能将事后输入登记为当前事前范围，历史范围须用独立协议。",
            )
        )
    by_package = {row["package_id"]: row["revision_id"] for row in heads}
    if (
        by_package.get(scope[1]) != scope[2]
        or by_package.get(authority["manifest"]["package_id"])
        != authority["manifest"]["revision_id"]
    ):
        blocking.append(
            policy.gap(
                "PACKAGE_HEAD_CHANGED",
                scope[2],
                "所选本方包或权威包已有新修订，请保留历史并选择当前确切输入。",
            )
        )
    if identity != target["identity"] or identity != authority["identity"]:
        blocking.append(
            policy.gap(
                "IDENTITY_CHANGED", scope[0], "当前工程、标段、轮次或投标主体与原包冻结身份不同。"
            )
        )
    if (
        inventory_head is None
        or inventory_head["id"] != inventory_id
        or inventory_head["digest"] != inventory["digest"]
        or profile is None
        or profile["current_rule_set_id"] != im["rule_set_id"]
    ):
        blocking.append(
            policy.gap(
                "INVENTORY_CHANGED",
                inventory_id,
                "要求清单或规则集已有新版，不能以旧范围登记当前输入。",
            )
        )
    current_source_snapshot = inventories._source_snapshot(
        c, scope[2], authority["manifest"]["revision_id"]
    )
    if current_source_snapshot != im["source_snapshot"]:
        blocking.append(
            policy.gap(
                "INVENTORY_SOURCES_CHANGED",
                inventory_id,
                "原清单的完整来源快照已变化，需先核对新的清单。",
            )
        )
    generated = generated_observations(
        c, {"bid_id": scope[0], "target": target, "authority": authority}
    )
    if any(row["admission"]["state"] != "matched" for row in generated):
        blocking.append(
            policy.gap(
                "GENERATED_OUTPUT_CHANGED", scope[2], "生成稿的采用、图片或原件来源资格已变化。"
            )
        )
    documents, document_bytes, block_count, page_count = [], 0, 0, 0
    for role, value in (("target", target), ("authority", authority)):
        for member in value["manifest"]["members"]:
            document = _document(c, scope[0], role, member)
            document_bytes += len(policy.bounded(document, policy.LIMITS["snapshot_bytes"]))
            block_count += len(document["blocks"])
            page_count += len(document["pages"])
            if (
                document_bytes > policy.LIMITS["snapshot_bytes"]
                or block_count > policy.LIMITS["blocks"]
                or page_count > policy.LIMITS["pages"]
            ):
                policy.failure(
                    "TOO_LARGE", "全部原页证据超过完整冻结容量，未截断或忽略未选分册", 413
                )
            documents.append(document)
    snapshot = {
        "target": target,
        "authority": authority,
        "inventory": inventory,
        "documents": documents,
        "source_snapshot": sources,
        "blocking_reasons": list({g["id"]: g for g in blocking}.values()),
        "observation": {
            "profile": profile,
            "identity": identity,
            "package_heads": heads,
            "inventory_head": clean(inventory_head),
            "current_submission_head": submission_head,
            "inventory_sources": current_source_snapshot,
            "generated_outputs": generated,
        },
        "originals": [
            {k: row[k] for k in ("document_version_id", "digest", "byte_size")} for row in originals
        ],
    }
    policy.check_snapshot(snapshot)
    return {"snapshot": snapshot, "originals": originals}


def insert(c, value):
    manifest = value["manifest"]
    scope = manifest["preview"]["manifest"]["scope"]
    c.execute(
        "INSERT INTO design.bid_package_technical_scopes(id,bid_id,package_id,revision_id,inventory_id,actor_id,command_id,manifest,digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            manifest["id"],
            scope["bid_id"],
            scope["package_id"],
            scope["revision_id"],
            scope["inventory_id"],
            manifest["actor_id"],
            manifest["command_id"],
            Jsonb(manifest),
            value["digest"],
        ),
    )


def load(c, scope, identity):
    row = c.execute(
        "SELECT manifest,digest FROM design.bid_package_technical_scopes WHERE bid_id=%s AND package_id=%s AND revision_id=%s AND id=%s",
        (*scope, identity),
    ).fetchone()
    if row is None:
        policy.failure("NOT_FOUND", "所选精确包的技术范围记录不存在", 404)
    from packages.contracts.package_technical_scope_api import validate

    validate("PackageTechnicalScopeView", row)
    if (
        digest(row["manifest"]) != row["digest"]
        or digest(row["manifest"]["preview"]["manifest"]) != row["manifest"]["preview"]["digest"]
    ):
        policy.failure("CORRUPT", "技术范围不可变摘要无法核验", 500)
    return row


def history(c, scope, cursor=None, limit=20):
    require_schema(c)
    if type(limit) is not int or not 1 <= limit <= 50:
        policy.failure("INVALID", "历史分页大小必须为1到50", 422)
    after = None
    if cursor:
        try:
            if str(UUID(cursor)) != cursor:
                raise ValueError
        except (ValueError, TypeError):
            policy.failure("INVALID_CURSOR", "历史游标不是本列表的准确记录", 422)
        after = c.execute(
            "SELECT created_at,id FROM design.bid_package_technical_scopes WHERE bid_id=%s AND package_id=%s AND revision_id=%s AND id=%s",
            (*scope, cursor),
        ).fetchone()
        if after is None:
            policy.failure("INVALID_CURSOR", "历史游标不属于所选精确包", 422)
    rows = clean(
        c.execute(
            "SELECT id::text,digest,inventory_id::text,created_at,manifest#>>'{preview,manifest,coverage,state}' AS coverage_state,(manifest#>>'{preview,manifest,coverage,selected_part_count}')::integer AS selected_part_count,(manifest#>>'{preview,manifest,coverage,included_rule_count}')::integer AS included_rule_count,false AS scoring_ready FROM design.bid_package_technical_scopes WHERE bid_id=%s AND package_id=%s AND revision_id=%s AND (%s::timestamptz IS NULL OR (created_at,id)<(%s::timestamptz,%s::uuid)) ORDER BY created_at DESC,id DESC LIMIT %s",
            (
                *scope,
                after["created_at"] if after else None,
                after["created_at"] if after else None,
                after["id"] if after else None,
                limit + 1,
            ),
        ).fetchall()
    )
    return {
        "items": rows[:limit],
        "has_more": len(rows) > limit,
        "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }
