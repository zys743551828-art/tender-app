"""Versioned Word import candidates, private previews, and atomic explicit append.

Object reads, OOXML parsing and staging never hold a database connection. The
candidate does not change a draft; only an acknowledged append consumes it.
"""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID, uuid5

from botocore.exceptions import BotoCoreError, ClientError
from psycopg.types.json import Jsonb

from packages.authoring import docx_import_contracts as contracts
from packages.authoring import docx_import_sources as provenance
from packages.authoring import rich_assets, rich_images, structure_repository
from packages.authoring.repository import draft_etag, lock_draft
from packages.authoring.structure_model import MAX_ACTIVE, MAX_NODES, node, ordered, validate_tree
from packages.domain import storage
from packages.domain.runtime import DomainError, audit, clean, connection, fetch, match, now, sha
from packages.domain.work_access import begin

PREPARE_KIND = "prepare-authoring-word-import"
RESOLVE_KIND = "resolve-authoring-word-import"
PROTOCOL = "authoring-word-import-candidate/1"
NAMESPACE = UUID("f6f70857-cf03-4b29-a4fd-d5c211d0a878")
MAX_CANDIDATE_BYTES = 16 * 1024 * 1024
SELECT = """SELECT i.*,r.result AS resolution
 FROM design.authoring_word_imports i
 LEFT JOIN design.authoring_word_import_resolutions r ON r.candidate_id=i.id"""


def parser_module():
    from packages.authoring import docx_import_parser

    return docx_import_parser


def require_available(c):
    for table, privileges in (
        ("word_intake_receipts", ("SELECT",)),
        ("authoring_word_imports", ("SELECT", "INSERT")),
        ("authoring_word_import_resolutions", ("SELECT", "INSERT")),
        ("authoring_structure_versions", ("SELECT", "INSERT")),
    ):
        name = "design." + table
        if c.execute("SELECT to_regclass(%s) AS item", (name,)).fetchone()[
            "item"
        ] is None or not all(
            c.execute("SELECT has_table_privilege(current_user,%s,%s) AS ok", (name, p)).fetchone()[
                "ok"
            ]
            for p in privileges
        ):
            raise DomainError(
                "AUTHORING_WORD_IMPORT_NOT_CONFIGURED",
                "尚未配置完整 Word 导入能力与分离角色授权",
                503,
            )
    rich_assets.require_available(c)


def capabilities(c):
    parser = parser_module()
    method = parser.method_identity()
    unavailable = None
    try:
        require_available(c)
    except DomainError as error:
        unavailable = {"code": error.code, "message": error.message}
    return {
        "enabled": unavailable is None,
        "unavailable_reason": unavailable,
        "method_digest": sha(method),
        "method": method,
        "supported": list(method["supported"]),
        "limitations": [
            "仅导入明确支持的可编辑结构；页面版式按工作台模板重新生成，原件继续保留。",
            "修订、动态域及外部关系阻止应用；不会自动接受修订、执行域或下载外部内容。",
            "转换限制逐项确认；不支持的结构不能通过勾选确认绕过。",
            "图片使用实际 PNG/JPEG 原件及已校验的规范 PNG；复杂图形另行标明。",
        ],
        "limits": {
            "max_docx_bytes": provenance.MAX_DOCX_BYTES,
            "max_candidate_bytes": MAX_CANDIDATE_BYTES,
            "max_sections": method["limits"]["sections"],
            "max_images": method["limits"]["images"],
        },
        "append_only": True,
        "requires_registered_original": True,
        "requires_loss_acknowledgement": True,
    }


def request_scope(bid, draft, body):
    return {"bid_id": str(bid), "draft_id": str(draft), **body}


def checked_key(key):
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(ord(char) < 32 for char in key):
        raise DomainError("IDEMPOTENCY_REQUIRED", "请保留有效的 Word 导入操作幂等键", 428)


def replay(c, bid, draft, actor, kind, target, key, body, condition):
    row = c.execute(
        "SELECT request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, kind, target, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha(
        {"body": request_scope(bid, draft, body), "if_match": condition}
    ):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一 Word 导入请求对应不同内容或草稿版本", 409)
    value = row["response"]
    if value is None:
        raise DomainError("COMMAND_INCOMPLETE", "原 Word 导入操作尚未形成回执，请保留原请求", 409)
    if value["body"].get("bid_id") != str(bid) or value["body"].get("draft_id") != str(draft):
        raise DomainError(
            "AUTHORING_WORD_IMPORT_SCOPE_MISMATCH", "Word 导入回执不属于当前项目草稿", 409
        )
    return value


def command_binding(command, actor, key, body, condition, bid, draft):
    return {
        "command_id": str(command.id),
        "actor_id": str(actor),
        "idempotency_key": key,
        "request_digest": sha({"body": request_scope(bid, draft, body), "if_match": condition}),
        "request": deepcopy(body),
        "if_match": condition,
    }


def target_context(c, bid, draft, body, condition):
    head = lock_draft(c, bid, draft)
    match(condition, "draft", draft, head["revision"])
    if head["revision"] != body["base_draft_revision"]:
        raise DomainError("DRAFT_REVISION_CONFLICT", "正文草稿已变化，请重新保存并预览导入", 412)
    state, contents = structure_repository.load(c, bid, draft)
    snapshot = fetch(
        c,
        "SELECT id FROM draft_snapshots WHERE draft_id=%s AND revision=%s",
        (draft, head["revision"]),
    )
    return {
        "base_draft_revision": head["revision"],
        "base_snapshot_id": str(snapshot["id"]),
        "before_digest": sha({"state": state, "contents": contents}),
        "node_count": len(state["nodes"]),
        "context": structure_repository.context(c, bid),
        "authority": structure_repository.validate_use(c, bid, state, contents),
        "existing_sections": [
            {
                "section_id": item["section_id"],
                "parent_id": item["parent_id"],
                "ordinal": item["ordinal"],
                "title": contents[item["section_id"]]["attrs"]["title"],
            }
            for item in ordered(state["nodes"])
        ],
    }


def planned_sections(candidate, parsed):
    identities = {item["key"]: str(uuid5(candidate, item["key"])) for item in parsed["sections"]}
    return [
        deepcopy(item)
        | {
            "section_id": identities[item["key"]],
            "parent_id": identities[item["parent_key"]] if item["parent_key"] is not None else None,
            "content": imported_content(candidate, item["content"]),
        }
        for item in parsed["sections"]
    ]


def imported_content(candidate, content):
    """Candidate-owned node IDs keep two explicit imports from sharing bookmarks."""
    copied = deepcopy(content)

    def visit(node):
        if "id" in node.get("attrs", {}):
            node["attrs"]["id"] = str(uuid5(candidate, "node:" + node["attrs"]["id"]))
        for child in node.get("content", []):
            visit(child)

    visit(copied)
    return copied


def mapped_nodes(candidate, parsed):
    return [
        item
        | {
            "node_id": str(uuid5(candidate, item["section_key"]))
            if item["kind"] == "section_title"
            else str(uuid5(candidate, "node:" + item["node_id"]))
        }
        for item in parsed["mapping"]
    ]


def stage_images(bid, candidate, parsed):
    staged = []
    for image in parsed["images"]:
        objects = {}
        for variant, data, media in (
            ("original", image["original_bytes"], image["source_media_type"]),
            ("normalized", image["bytes"], "image/png"),
        ):
            digest = sha(data)
            locator = (
                f"authoring-images/{bid}/word-import/{candidate}/{image['key']}/{digest}.{variant}"
            )
            storage.put(locator, data, media)
            actual = storage.get(locator)
            if len(actual) != len(data) or sha(actual) != digest:
                raise DomainError(
                    "AUTHORING_WORD_IMPORT_IMAGE_CHANGED", "导入图片对象回读与实际字节不同", 503
                )
            objects[variant] = {
                "object_key": locator,
                "digest": digest,
                "byte_size": len(data),
                "media_type": media,
            }
        staged.append(
            {
                "key": image["key"],
                "source_part": image["source_part"],
                "normalization_proof": image["normalization_proof"],
                **objects,
            }
        )
    return staged


def prepare(bid, draft, actor, key, body, condition, *, final_auth=None):
    contracts.validate("AuthoringWordImportPrepareRequest", body)
    checked_key(key)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = replay(c, bid, draft, actor, PREPARE_KIND, draft, key, body, condition)
    if old is not None:
        return old, True
    parser = parser_module()
    method = parser.method_identity()
    if sha(method) != body["method_digest"]:
        raise DomainError(
            "AUTHORING_WORD_IMPORT_METHOD_CHANGED", "Word 导入方法已变化，请重新读取能力后申请", 409
        )
    document = UUID(body["source_document_version_id"])
    candidate = uuid5(NAMESPACE, f"{bid}:{draft}:{actor}:{key}")
    with connection() as c:
        require_available(c)
        target = target_context(c, bid, draft, body, condition)
        source_context, source = provenance.ensure_original(c, bid, document)
        if (
            source["digest"] != body["source_digest"]
            or source["byte_size"] != body["source_byte_size"]
        ):
            raise DomainError(
                "AUTHORING_WORD_IMPORT_ORIGINAL_CHANGED",
                "所选 Word 版本的摘要或字节长度不一致",
                409,
            )
        audit(
            c,
            actor,
            bid,
            "authoring.word_import_prepared",
            {
                "candidate_id": str(candidate),
                "draft_id": str(draft),
                "source_document_version_id": str(document),
                "source_digest": source["digest"],
                "request_digest": sha(request_scope(bid, draft, body)),
            },
        )
    # Database and graph locks are gone before any original/object processing.
    try:
        data = storage.get(source["object_key"])
        if len(data) != source["byte_size"] or sha(data) != source["digest"]:
            raise DomainError(
                "AUTHORING_WORD_IMPORT_ORIGINAL_CHANGED", "Word 原件字节与登记摘要不一致", 409
            )
        parsed = parser.parse_docx(data)
        if (
            parsed["method"] != method
            or parsed["source_digest"] != source["digest"]
            or parsed["source_byte_size"] != source["byte_size"]
        ):
            raise DomainError(
                "AUTHORING_WORD_IMPORT_METHOD_CHANGED", "解析过程的原件或方法身份不一致", 409
            )
        public = parser.public_result(parsed)
        sections = planned_sections(candidate, public)
        if (
            len(sections) + len(target["existing_sections"]) > MAX_ACTIVE
            or len(sections) + target["node_count"] > MAX_NODES
        ):
            raise DomainError(
                "AUTHORING_WORD_IMPORT_DRAFT_CAPACITY",
                "追加后章节将超过草稿容量，请先拆分原件或整理当前草稿",
                422,
            )
        staged = stage_images(bid, candidate, parsed)
        if final_auth is not None and str(final_auth()) != str(actor):
            raise DomainError(
                "AUTHORING_WORD_IMPORT_ACTOR_CHANGED", "登录成员变化，未保存新的导入候选", 409
            )
        if parser.method_identity() != method:
            raise DomainError(
                "AUTHORING_WORD_IMPORT_METHOD_CHANGED",
                "计算期间导入方法发生变化，请重新读取能力",
                409,
            )
        with connection() as c:
            command = begin(
                c,
                actor,
                PREPARE_KIND,
                draft,
                key,
                request_scope(bid, draft, body),
                condition,
                bid=bid,
            )
            if command.replay is not None:
                return command.replay, True
            current_target = target_context(c, bid, draft, body, condition)
            current_source, _ = provenance.capture(c, bid, document)
            if current_target != target:
                raise DomainError(
                    "AUTHORING_WORD_IMPORT_CONTEXT_CHANGED",
                    "准备期间正文、事实或格式依据已变化，请重新预览",
                    409,
                )
            if current_source != source_context:
                raise DomainError(
                    "AUTHORING_WORD_IMPORT_SOURCE_CHANGED",
                    "准备期间原件或祖先效力已变化，请重新核对",
                    409,
                )
            manifest = {
                "protocol": PROTOCOL,
                "candidate_id": str(candidate),
                "bid_id": str(bid),
                "draft_id": str(draft),
                "source_context": source_context,
                "target": target,
                "method_digest": body["method_digest"],
                "parsed": public,
                "sections": sections,
                "staged_images": staged,
                "reason": body["reason"],
                "preparation": command_binding(command, actor, key, body, condition, bid, draft),
            }
            try:
                encoded = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()
            except (ValueError, UnicodeError, RecursionError):
                raise DomainError(
                    "AUTHORING_WORD_IMPORT_RESULT_INVALID", "导入候选包含无效的结构值", 422
                ) from None
            if len(encoded) > MAX_CANDIDATE_BYTES:
                raise DomainError(
                    "AUTHORING_WORD_IMPORT_CANDIDATE_TOO_LARGE",
                    "完整导入候选超过 16 MiB，未截断内容",
                    413,
                )
            fingerprint = sha(manifest)
            c.execute(
                """INSERT INTO design.authoring_word_imports(id,bid_id,draft_id,source_document_version_id,base_draft_revision,base_snapshot_id,command_id,created_by,manifest,digest)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    candidate,
                    bid,
                    draft,
                    document,
                    target["base_draft_revision"],
                    UUID(target["base_snapshot_id"]),
                    command.id,
                    actor,
                    Jsonb(manifest),
                    fingerprint,
                ),
            )
            audit(
                c,
                actor,
                bid,
                "authoring.word_import_candidate_created",
                {
                    "candidate_id": str(candidate),
                    "draft_id": str(draft),
                    "candidate_digest": fingerprint,
                },
                command.id,
            )
            value = load(c, bid, draft, candidate)
            return command.finish(
                value,
                201,
                {"Location": f"/api/v1/bids/{bid}/drafts/{draft}/word-imports/{candidate}"},
            ), False
    except (ClientError, BotoCoreError, OSError):
        raise DomainError(
            "AUTHORING_WORD_IMPORT_STORAGE_UNAVAILABLE",
            "原件或图片存储未确认，请保留原请求后重试",
            503,
            retryable=True,
        ) from None


def checked_row(row):
    manifest = row["manifest"]
    if (
        sha(manifest) != row["digest"]
        or manifest.get("protocol") != PROTOCOL
        or manifest.get("candidate_id") != str(row["id"])
        or manifest.get("bid_id") != str(row["bid_id"])
        or manifest.get("draft_id") != str(row["draft_id"])
        or manifest.get("source_context", {}).get("source", {}).get("document_version_id")
        != str(row["source_document_version_id"])
        or manifest.get("target", {}).get("base_draft_revision") != row["base_draft_revision"]
        or manifest.get("target", {}).get("base_snapshot_id") != str(row["base_snapshot_id"])
        or manifest.get("preparation", {}).get("command_id") != str(row["command_id"])
        or manifest.get("preparation", {}).get("actor_id") != str(row["created_by"])
    ):
        raise DomainError("AUTHORING_WORD_IMPORT_RECORD_CORRUPT", "导入候选与固定身份不一致", 500)
    try:
        parsed = manifest["parsed"]
        provenance.checked_source_context(manifest["source_context"])
        if (
            parsed["protocol"] != "authoring-docx-import/1"
            or parsed["content_digest"] != parser_module().result_digest(parsed)
            or manifest["method_digest"] != sha(parsed["method"])
            or parsed["source_digest"] != manifest["source_context"]["source"]["digest"]
            or parsed["source_byte_size"] != manifest["source_context"]["source"]["byte_size"]
            or manifest["sections"] != planned_sections(row["id"], parsed)
        ):
            raise ValueError
        originals = {image["key"]: image for image in parsed["images"]}
        staged = manifest["staged_images"]
        if len(originals) != len(parsed["images"]) or len(staged) != len(originals):
            raise ValueError
        seen = set()
        for item in staged:
            original = originals[item["key"]]
            proof = original["normalization_proof"]
            if (
                item["key"] in seen
                or item["source_part"] != original["source_part"]
                or item["normalization_proof"] != proof
                or item["original"]["digest"] != original["source_digest"]
                or item["original"]["byte_size"] != original["source_byte_size"]
                or item["original"]["media_type"] != original["source_media_type"]
                or item["normalized"]["digest"] != proof["output_digest"]
                or item["normalized"]["byte_size"] != proof["output_byte_size"]
                or item["normalized"]["media_type"] != "image/png"
            ):
                raise ValueError
            prefix = f"authoring-images/{row['bid_id']}/word-import/{row['id']}/{item['key']}/"
            for variant in ("original", "normalized"):
                if item[variant]["object_key"] != prefix + item[variant]["digest"] + "." + variant:
                    raise ValueError
            seen.add(item["key"])
    except (KeyError, TypeError, ValueError, AttributeError, DomainError):
        raise DomainError(
            "AUTHORING_WORD_IMPORT_RECORD_CORRUPT", "导入候选内容、映射或原件证明不一致", 500
        ) from None
    return manifest


def row_for(c, bid, draft, candidate):
    row = c.execute(
        SELECT + " WHERE i.bid_id=%s AND i.draft_id=%s AND i.id=%s", (bid, draft, candidate)
    ).fetchone()
    if row is None:
        raise DomainError("AUTHORING_WORD_IMPORT_NOT_FOUND", "未找到当前项目草稿的导入候选", 404)
    return row


def summary(row, *, manifest=None):
    manifest = checked_row(row) if manifest is None else manifest
    parsed = manifest["parsed"]
    resolved = row["resolution"]
    return clean(
        {
            "candidate_id": row["id"],
            "bid_id": row["bid_id"],
            "draft_id": row["draft_id"],
            "candidate_digest": row["digest"],
            "source": manifest["source_context"]["source"],
            "base_draft_revision": row["base_draft_revision"],
            "method_digest": manifest["method_digest"],
            "state": resolved["state"]
            if resolved
            else "ready"
            if parsed["can_apply"]
            else "blocked",
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "section_count": len(parsed["sections"]),
            "image_count": len(parsed["images"]),
            "warning_count": sum(item["severity"] == "warning" for item in parsed["issues"]),
            "blocker_count": sum(item["severity"] == "blocker" for item in parsed["issues"]),
        }
    )


def view(row):
    manifest = checked_row(row)
    parsed = manifest["parsed"]
    images = []
    for item in manifest["staged_images"]:
        proof = item["normalization_proof"]
        images.append(
            {
                "key": item["key"],
                "source_part": item["source_part"],
                "source_digest": item["original"]["digest"],
                "source_byte_size": item["original"]["byte_size"],
                "source_media_type": item["original"]["media_type"],
                "media_type": "image/png",
                "digest": item["normalized"]["digest"],
                "byte_size": item["normalized"]["byte_size"],
                "width_px": proof["width_px"],
                "height_px": proof["height_px"],
            }
        )
    return summary(row, manifest=manifest) | {
        "protocol": PROTOCOL,
        "base_snapshot_id": str(row["base_snapshot_id"]),
        "base_draft_etag": draft_etag(row["draft_id"], row["base_draft_revision"]),
        "before_digest": manifest["target"]["before_digest"],
        "existing_sections": manifest["target"]["existing_sections"],
        "method": parsed["method"],
        "sections": manifest["sections"],
        "mapping": mapped_nodes(row["id"], parsed),
        "images": images,
        "issues": parsed["issues"],
        "can_apply": bool(parsed["can_apply"] and row["resolution"] is None),
        "current_validity": "rechecked_on_append",
        "append_only": True,
        "reason": manifest["reason"],
        "preparation": manifest["preparation"],
        "resolution": clean(row["resolution"]),
    }


def load(c, bid, draft, candidate):
    return view(row_for(c, bid, draft, candidate))


def history(c, bid, draft, cursor=None, limit=20):
    fetch(c, "SELECT id FROM design.drafts WHERE id=%s AND bid_id=%s", (draft, bid))
    if type(limit) is not int or not 1 <= limit <= 50:
        raise DomainError("AUTHORING_WORD_IMPORT_INVALID", "导入历史每页应为 1 至 50 项", 422)
    try:
        after = UUID(str(cursor)) if cursor else None
    except (ValueError, TypeError, AttributeError):
        raise DomainError("INVALID_CURSOR", "导入历史游标无效", 422) from None
    cursor_time = None
    if after is not None:
        cursor_time = fetch(
            c,
            "SELECT created_at FROM design.authoring_word_imports WHERE bid_id=%s AND draft_id=%s AND id=%s",
            (bid, draft, after),
        )["created_at"]
    # The immutable table validates each manifest on insertion. A history page
    # projects only metadata; 50 full candidates could otherwise read 800 MiB.
    rows = c.execute(
        """SELECT i.id AS candidate_id,i.bid_id,i.draft_id,i.digest AS candidate_digest,
        i.manifest#>'{source_context,source}' AS source,i.base_draft_revision,
        i.manifest->>'method_digest' AS method_digest,i.created_at,i.created_by,
        CASE WHEN r.decision='append' THEN 'applied' WHEN r.decision='reject' THEN 'rejected'
        WHEN i.manifest#>'{parsed,can_apply}'='true'::jsonb THEN 'ready' ELSE 'blocked' END AS state,
        jsonb_array_length(i.manifest->'sections') AS section_count,
        jsonb_array_length(i.manifest->'staged_images') AS image_count,
        (SELECT count(*) FROM jsonb_array_elements(i.manifest#>'{parsed,issues}') e(item)
         WHERE item->>'severity'='warning') AS warning_count,
        (SELECT count(*) FROM jsonb_array_elements(i.manifest#>'{parsed,issues}') e(item)
         WHERE item->>'severity'='blocker') AS blocker_count
        FROM design.authoring_word_imports i
        LEFT JOIN design.authoring_word_import_resolutions r ON r.candidate_id=i.id
        WHERE i.bid_id=%s AND i.draft_id=%s
        AND (%s::uuid IS NULL OR (i.created_at,i.id)<(%s,%s))
        ORDER BY i.created_at DESC,i.id DESC LIMIT %s""",
        (bid, draft, after, cursor_time, after, limit + 1),
    ).fetchall()
    return {
        "bid_id": str(bid),
        "draft_id": str(draft),
        "items": clean(rows[:limit]),
        "has_more": len(rows) > limit,
        "next_cursor": str(rows[limit - 1]["candidate_id"]) if len(rows) > limit else None,
    }


def image_descriptor(c, bid, draft, candidate, image_key):
    manifest = checked_row(row_for(c, bid, draft, candidate))
    image = next(
        (item for item in manifest["staged_images"] if item["key"] == str(image_key)), None
    )
    if image is None:
        raise DomainError("AUTHORING_WORD_IMPORT_IMAGE_NOT_FOUND", "候选没有这张精确图片", 404)
    return deepcopy(image["normalized"])


def verify_staged(manifest):
    for image in manifest["staged_images"]:
        for variant in ("original", "normalized"):
            descriptor = image[variant]
            data = storage.get(descriptor["object_key"])
            if len(data) != descriptor["byte_size"] or sha(data) != descriptor["digest"]:
                raise DomainError(
                    "AUTHORING_WORD_IMPORT_IMAGE_CHANGED", "候选图片字节与已预览的摘要不同", 409
                )
            if variant == "normalized":
                rich_images.verify_normalized(data, image["normalization_proof"])


def append_candidate(c, bid, draft, candidate, actor, manifest, condition):
    target = manifest["target"]
    head = lock_draft(c, bid, draft)
    match(condition, "draft", draft, head["revision"])
    if head["revision"] != target["base_draft_revision"]:
        raise DomainError("DRAFT_REVISION_CONFLICT", "正文已变化，候选保留但不能覆盖新修订", 412)
    state, contents = structure_repository.load(c, bid, draft)
    if sha({"state": state, "contents": contents}) != target["before_digest"]:
        raise DomainError("DRAFT_REVISION_CONFLICT", "正文或章节树已变化，请重新创建导入预览", 412)
    current_source, _ = provenance.capture(
        c, bid, UUID(manifest["source_context"]["source"]["document_version_id"])
    )
    if current_source != manifest["source_context"]:
        raise DomainError(
            "AUTHORING_WORD_IMPORT_SOURCE_CHANGED", "原件或祖先效力在预览后变化，未追加正文", 409
        )
    if (
        structure_repository.context(c, bid) != target["context"]
        or structure_repository.validate_use(c, bid, state, contents) != target["authority"]
    ):
        raise DomainError(
            "AUTHORING_WORD_IMPORT_CONTEXT_CHANGED",
            "正文事实、要求或格式依据已变化，请重新预览",
            409,
        )
    bindings = {}
    for item in manifest["staged_images"]:
        proof = deepcopy(item["normalization_proof"]) | {
            "input_origin": "external_docx_embedded_raster",
            "word_import_source": provenance.image_source(
                candidate, bid, manifest, item["source_part"]
            ),
        }
        value = rich_assets.insert(
            c,
            bid,
            actor,
            "Word 导入图片 " + item["key"][:12],
            manifest["reason"],
            [],
            proof,
            item["original"],
            item["normalized"],
        )
        bindings[item["key"]] = {
            "asset_id": value["asset_id"],
            "asset_revision": value["revision"],
            "asset_version_id": value["id"],
        }
    materialized = parser_module().materialize_sections(manifest["parsed"], bindings)
    after = deepcopy(state)
    texts = deepcopy(contents)
    top_ordinal = sum(item["parent_id"] is None and not item["deleted"] for item in state["nodes"])
    children: dict[str, int] = {}
    planned = {item["key"]: item for item in manifest["sections"]}
    for item in materialized:
        mapping = planned[item["key"]]
        parent = mapping["parent_id"]
        ordinal = top_ordinal if parent is None else children.get(parent, 0)
        if parent is None:
            top_ordinal += 1
        else:
            children[parent] = ordinal + 1
        after["nodes"].append(node(mapping["section_id"], parent=parent, ordinal=ordinal))
        texts[mapping["section_id"]] = imported_content(candidate, item["content"])
    validate_tree(after["nodes"])
    after["nodes"] = ordered(after["nodes"], include_deleted=True)
    for ordinal, item in enumerate(ordered(after["nodes"])):
        texts[item["section_id"]]["attrs"]["ordinal"] = ordinal
    return after, texts, head["revision"]


def resolve(bid, draft, candidate, actor, key, body, condition, *, final_auth=None):
    contracts.validate("AuthoringWordImportResolveRequest", body)
    checked_key(key)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = replay(c, bid, draft, actor, RESOLVE_KIND, candidate, key, body, condition)
        if old is not None:
            return old, True
        row = row_for(c, bid, draft, candidate)
        manifest = checked_row(row)
    if row["digest"] != body["candidate_digest"]:
        raise DomainError("AUTHORING_WORD_IMPORT_CANDIDATE_CHANGED", "确认的候选摘要不一致", 409)
    if row["resolution"] is not None:
        raise DomainError(
            "AUTHORING_WORD_IMPORT_ALREADY_RESOLVED", "该候选已经处理，请读取原回执", 409
        )
    if body["decision"] == "append":
        if not manifest["parsed"]["can_apply"] or any(
            item["severity"] == "blocker" for item in manifest["parsed"]["issues"]
        ):
            raise DomainError(
                "AUTHORING_WORD_IMPORT_BLOCKED", "候选仍有不支持的结构，不能确认后绕过", 409
            )
        required = {
            item["id"] for item in manifest["parsed"]["issues"] if item["severity"] == "warning"
        }
        if set(body["acknowledged_issue_ids"]) != required:
            raise DomainError(
                "AUTHORING_WORD_IMPORT_LOSS_ACK_REQUIRED", "请逐项确认此候选的全部转换限制", 422
            )
        if sha(parser_module().method_identity()) != manifest["method_digest"]:
            raise DomainError(
                "AUTHORING_WORD_IMPORT_METHOD_CHANGED",
                "导入方法已更新，请保留历史候选并重新预览",
                409,
            )
        try:
            verify_staged(manifest)
        except (ClientError, BotoCoreError, OSError):
            raise DomainError(
                "AUTHORING_WORD_IMPORT_STORAGE_UNAVAILABLE",
                "候选图片存储未确认，请保留原请求后重试",
                503,
                retryable=True,
            ) from None
    if final_auth is not None and str(final_auth()) != str(actor):
        raise DomainError(
            "AUTHORING_WORD_IMPORT_ACTOR_CHANGED", "登录成员已变化，未应用导入候选", 409
        )
    with connection() as c:
        command = begin(
            c,
            actor,
            RESOLVE_KIND,
            candidate,
            key,
            request_scope(bid, draft, body),
            condition,
            bid=bid,
            work=False,
        )
        if command.replay is not None:
            return command.replay, True
        # begin already holds the bid row lock. Candidates are append-only and
        # deliberately grant no UPDATE capability needed by SELECT FOR UPDATE.
        current = row_for(c, bid, draft, candidate)
        if current["resolution"] is not None:
            raise DomainError(
                "AUTHORING_WORD_IMPORT_ALREADY_RESOLVED",
                "该候选已被另一操作处理，请读取历史回执",
                409,
            )
        result = {
            "bid_id": str(bid),
            "draft_id": str(draft),
            "candidate_id": str(candidate),
            "candidate_digest": row["digest"],
            "decision": body["decision"],
            "state": "applied" if body["decision"] == "append" else "rejected",
            "created_section_ids": [],
            "draft_revision": None,
            "snapshot_id": None,
            "snapshot_digest": None,
            "resolved_at": now().isoformat(),
            "command": command_binding(command, actor, key, body, condition, bid, draft),
        }
        if body["decision"] == "append":
            require_available(c)
            after, texts, revision = append_candidate(
                c, bid, draft, candidate, actor, manifest, condition
            )
            imports = after["metadata"].setdefault("word_import_sources", [])
            imports.append(provenance.provenance(bid, draft, candidate, row["digest"], manifest))
            provenance.assert_import_sources(
                c,
                bid,
                after["metadata"],
                section_ids={item["section_id"] for item in after["nodes"] if not item["deleted"]},
            )
            saved = structure_repository.commit(c, bid, draft, actor, after, texts, revision)
            result.update(
                {name: saved[name] for name in ("draft_revision", "snapshot_id", "snapshot_digest")}
            )
            result["created_section_ids"] = [item["section_id"] for item in manifest["sections"]]
        c.execute(
            """INSERT INTO design.authoring_word_import_resolutions(candidate_id,bid_id,draft_id,command_id,resolved_by,decision,result,digest)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                candidate,
                bid,
                draft,
                command.id,
                actor,
                body["decision"],
                Jsonb(result),
                sha(result),
            ),
        )
        audit(
            c,
            actor,
            bid,
            "authoring.word_import_resolved",
            {
                "candidate_id": str(candidate),
                "draft_id": str(draft),
                "decision": body["decision"],
                "candidate_digest": row["digest"],
            },
            command.id,
        )
        headers = (
            {"ETag": draft_etag(draft, result["draft_revision"])}
            if result["draft_revision"]
            else {}
        )
        return command.finish(result, headers=headers), False
