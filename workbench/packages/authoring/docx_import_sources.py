"""Exact Word-original authority for import and subsequent frozen-content uses.

No parser or object I/O occurs here. A verified, received Word original can
become a published original root without claiming text, PDF, or vector coverage.
Frozen provenance is checked from core immutable records, not candidate tables.
"""

from copy import deepcopy
from datetime import datetime
from uuid import UUID

from packages.domain.runtime import DomainError, clean, fetch, now, sha
from packages.knowledge import sources
from packages.rag.indexing import original_source_id
from packages.word_intake.inspection import DOCX

MAX_DOCX_BYTES = 32 * 1024 * 1024
PROVENANCE_PROTOCOL = "authoring-word-import-source/1"
IMAGE_PROTOCOL = "authoring-word-import-image-source/1"


def invalid(message="Word 导入原件或来源资格已变化", code="AUTHORING_WORD_IMPORT_SOURCE_INVALID"):
    raise DomainError(code, message, 409)


def original(c, bid, document):
    if (
        c.execute("SELECT to_regclass('design.word_intake_receipts') AS item").fetchone()["item"]
        is None
    ):
        raise DomainError("AUTHORING_WORD_IMPORT_NOT_CONFIGURED", "尚未配置 Word 原件接收能力", 503)
    row = c.execute(
        """SELECT v.id,v.bid_id,v.original_name,v.obtained_at,v.artifact_kind,
        blob.id AS blob_id,blob.digest,blob.byte_size,blob.media_type,blob.object_key,
        w.upload_id,w.verify_operation_id,w.inspection_digest,w.inspection_report,
        u.state AS upload_state,u.verified_version_id,u.declared_digest,u.declared_size,u.role,
        coalesce(fv.file_id,x.file_id) AS file_id,
        coalesce(fv.revision,x.expected_file_revision) AS file_revision,
        x.id AS binding_id,f.role AS file_role
        FROM design.document_versions v JOIN design.blobs blob ON blob.id=v.blob_id
        JOIN design.word_intake_receipts w ON w.bid_id=v.bid_id AND w.document_version_id=v.id
        JOIN design.uploads u ON u.id=w.upload_id AND u.bid_id=w.bid_id
        JOIN design.upload_transfers t ON t.bid_id=u.bid_id AND t.upload_id=u.id
        JOIN design.upload_bindings x ON x.id=t.current_binding_id AND x.bid_id=u.bid_id AND x.upload_id=u.id
        LEFT JOIN design.document_file_versions fv ON fv.bid_id=v.bid_id AND fv.version_id=v.id
        JOIN design.document_files f ON f.bid_id=v.bid_id AND f.id=coalesce(fv.file_id,x.file_id)
        WHERE v.bid_id=%s AND v.id=%s""",
        (bid, document),
    ).fetchone()
    if row is None:
        raise DomainError(
            "AUTHORING_WORD_IMPORT_ORIGINAL_NOT_FOUND", "请选择本项目已接收的精确 Word 原件", 404
        )
    if (
        row["media_type"] != DOCX
        or row["artifact_kind"] not in {"source_original", "bid_body"}
        or row["role"] not in {"body", "tender", "supplement", "drawing", "boq"}
        or row["file_role"] != row["role"]
        or row["upload_state"] != "verified"
        or row["verified_version_id"] != row["id"]
        or row["declared_digest"] != row["digest"]
        or row["declared_size"] != row["byte_size"]
        or row["inspection_report"].get("schema") != "word-intake-inspection/1"
        or sha(row["inspection_report"]) != row["inspection_digest"]
    ):
        invalid("原件版本、上传核验、用途或接收回执无法相互核对")
    if not 0 < row["byte_size"] <= MAX_DOCX_BYTES:
        raise DomainError("AUTHORING_WORD_IMPORT_SIZE_LIMIT", "Word 导入原件超过 32 MiB", 413)
    if row["obtained_at"] > now():
        invalid("原件取得时间尚未到达，不能用于当前编写")
    if c.execute(
        "SELECT 1 FROM design.material_assignments WHERE bid_id=%s AND document_version_id=%s AND role='official_result' LIMIT 1",
        (bid, document),
    ).fetchone():
        invalid("官方结果资料不能转作当前投标正文来源")
    return row


def ensure_original(c, bid, document):
    """Explicit import preparation only; never republish withdrawn originals."""
    sources.lock_graph(c)
    row = original(c, bid, document)
    identity = original_source_id(document)
    c.execute(
        """INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest)
        VALUES(%s,%s,'document','prebid_content',%s,%s) ON CONFLICT(id) DO NOTHING""",
        (identity, document, row["obtained_at"], row["digest"]),
    )
    c.execute(
        """INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from)
        VALUES(%s,1,'candidate',%s) ON CONFLICT(source_id) DO NOTHING""",
        (identity, row["obtained_at"]),
    )
    sources.lock_heads(c, [identity])
    node = fetch(c, "SELECT * FROM retrieval.source_nodes WHERE id=%s", (identity,))
    if (
        node["document_version_id"] != document
        or node["digest"] != row["digest"]
        or node["kind"] != "document"
        or node["policy_class"] != "prebid_content"
        or node["known_at"] != row["obtained_at"]
    ):
        invalid("原件的不可变来源身份与已接收文件不一致")
    invalid_ancestor = c.execute(
        """SELECT 1 FROM retrieval.source_ancestors a
        JOIN retrieval.source_nodes n ON n.id=a.ancestor_id
        LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
        LEFT JOIN design.document_versions v ON v.id=n.document_version_id
        WHERE a.source_id=%s AND (n.kind<>'document' OR n.policy_class<>'prebid_content'
        OR v.bid_id IS DISTINCT FROM %s OR n.known_at>clock_timestamp()
        OR h.status IS NULL OR h.status='withdrawn' OR h.valid_from>clock_timestamp()
        OR h.valid_until<=clock_timestamp() OR (n.id<>%s AND h.status<>'published')) LIMIT 1""",
        (identity, bid, identity),
    ).fetchone()
    if invalid_ancestor:
        invalid("原件或祖先已撤回、用途不符或当前未生效，不能重新发布")
    c.execute(
        "UPDATE retrieval.source_heads SET status='published',revision=revision+1 WHERE source_id=%s AND status='candidate'",
        (identity,),
    )
    return capture(c, bid, document, lock_sources=True)


def capture(c, bid, document, *, lock_sources=True):
    document = UUID(str(document))
    row = original(c, bid, document)
    identity = original_source_id(document)
    if lock_sources:
        sources.lock_graph(c)
        sources.lock_heads(c, [identity])
    node = c.execute("SELECT * FROM retrieval.source_nodes WHERE id=%s", (identity,)).fetchone()
    if (
        node is None
        or node["kind"] != "document"
        or node["policy_class"] != "prebid_content"
        or node["document_version_id"] != document
        or node["digest"] != row["digest"]
        or node["known_at"] != row["obtained_at"]
    ):
        invalid("原件缺少精确且有效的已登记来源")
    authority = sources.authority_manifest(c, [identity], now())
    if any(
        item["kind"] != "document" or item["policy_class"] != "prebid_content" for item in authority
    ):
        invalid("原件或祖先用途不允许本次编写")
    if c.execute(
        """SELECT 1 FROM retrieval.source_ancestors a
        JOIN retrieval.source_nodes n ON n.id=a.ancestor_id
        LEFT JOIN design.document_versions v ON v.id=n.document_version_id
        LEFT JOIN design.blobs b ON b.id=v.blob_id
        WHERE a.source_id=%s AND (v.bid_id IS DISTINCT FROM %s OR b.digest IS DISTINCT FROM n.digest
        OR v.obtained_at>clock_timestamp() OR EXISTS(SELECT 1 FROM design.material_assignments m
        WHERE m.bid_id=v.bid_id AND m.document_version_id=v.id AND m.role='official_result')) LIMIT 1""",
        (identity, bid),
    ).fetchone():
        invalid("原件祖先不是本项目可用于投标准备的准确文件")
    public = clean(
        {
            "document_version_id": document,
            "digest": row["digest"],
            "byte_size": row["byte_size"],
            "media_type": row["media_type"],
            "filename": row["original_name"],
            "role": row["role"],
            "file_id": row["file_id"],
            "file_revision": row["file_revision"],
            "intake_digest": row["inspection_digest"],
        }
    )
    context = {
        "source": public,
        "source_id": str(identity),
        "authority": authority,
        "receipt": clean(
            {
                name: row[name]
                for name in ("upload_id", "verify_operation_id", "inspection_digest", "binding_id")
            }
        ),
        "obtained_at": clean(row["obtained_at"]),
        "locator_digest": sha(row["object_key"].encode()),
    }
    return context, clean(dict(row))


def checked_digest(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        invalid("导入来源摘要无效")
    return value


def checked_uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        invalid("导入来源身份不是规范 UUID")
    return value


def checked_time(value):
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        invalid("导入来源时间缺少时区或无法解释")


def checked_source_context(context):
    """Pure, exact shape validation before either active filtering or DB access."""
    try:
        if not isinstance(context, dict) or set(context) != {
            "source",
            "source_id",
            "authority",
            "receipt",
            "obtained_at",
            "locator_digest",
        }:
            invalid("导入原件上下文字段不完整")
        source, receipt = context["source"], context["receipt"]
        if not isinstance(source, dict) or set(source) != {
            "document_version_id",
            "digest",
            "byte_size",
            "media_type",
            "filename",
            "role",
            "file_id",
            "file_revision",
            "intake_digest",
        }:
            invalid("导入原件描述字段不完整")
        document = UUID(checked_uuid(source["document_version_id"]))
        checked_uuid(source["file_id"])
        checked_digest(source["digest"])
        checked_digest(source["intake_digest"])
        checked_digest(context["locator_digest"])
        checked_time(context["obtained_at"])
        if (
            context["source_id"] != str(original_source_id(document))
            or source["media_type"] != DOCX
            or source["role"] not in {"body", "tender", "supplement", "drawing", "boq"}
            or type(source["byte_size"]) is not int
            or not 0 < source["byte_size"] <= MAX_DOCX_BYTES
            or type(source["file_revision"]) is not int
            or source["file_revision"] < 1
            or not isinstance(source["filename"], str)
            or not source["filename"]
        ):
            invalid("导入原件描述与来源身份不一致")
        if not isinstance(receipt, dict) or set(receipt) != {
            "upload_id",
            "verify_operation_id",
            "inspection_digest",
            "binding_id",
        }:
            invalid("导入接收回执字段不完整")
        for name in ("upload_id", "verify_operation_id", "binding_id"):
            checked_uuid(receipt[name])
        if receipt["inspection_digest"] != source["intake_digest"]:
            invalid("导入原件与接收回执摘要不一致")
        authority = context["authority"]
        if not isinstance(authority, list) or not 1 <= len(authority) <= 10000:
            invalid("导入来源缺少完整祖先清单")
        seen = set()
        for item in authority:
            if not isinstance(item, dict) or set(item) != {
                "source_id",
                "ancestor_id",
                "kind",
                "policy_class",
                "known_at",
                "digest",
                "revision",
                "status",
                "valid_from",
                "valid_until",
            }:
                invalid("导入来源祖先字段不完整")
            ancestor = checked_uuid(item["ancestor_id"])
            checked_digest(item["digest"])
            checked_time(item["known_at"])
            checked_time(item["valid_from"])
            if item["valid_until"] is not None:
                checked_time(item["valid_until"])
            if (
                item["source_id"] != context["source_id"]
                or ancestor in seen
                or item["kind"] != "document"
                or item["policy_class"] != "prebid_content"
                or item["status"] != "published"
                or type(item["revision"]) is not int
                or item["revision"] < 1
            ):
                invalid("导入来源祖先身份、用途或效力不匹配")
            if ancestor == context["source_id"] and (
                item["digest"] != source["digest"] or item["known_at"] != context["obtained_at"]
            ):
                invalid("导入原件根来源与文件身份不一致")
            seen.add(ancestor)
        if context["source_id"] not in seen:
            invalid("导入来源祖先清单缺少原件根")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        invalid("导入原件上下文无法解释")
    return context


def provenance(bid, draft, candidate, digest, manifest):
    value = {
        "protocol": PROVENANCE_PROTOCOL,
        "bid_id": str(bid),
        "draft_id": str(draft),
        "candidate_id": str(candidate),
        "candidate_digest": digest,
        "method_digest": manifest["method_digest"],
        "content_digest": manifest["parsed"]["content_digest"],
        "source_context": manifest["source_context"],
        "section_ids": [item["section_id"] for item in manifest["sections"]],
    }
    return value | {"proof_digest": sha(value)}


def checked_imports(metadata):
    """Validate every original proof, including currently inactive imports."""
    if not isinstance(metadata, dict):
        invalid("导入来源元数据不是对象")
    imports = metadata.get("word_import_sources", [])
    if not isinstance(imports, list) or len(imports) > 500:
        invalid("导入来源清单格式或数量不符合冻结协议")
    expected = {
        "protocol",
        "bid_id",
        "draft_id",
        "candidate_id",
        "candidate_digest",
        "method_digest",
        "content_digest",
        "source_context",
        "section_ids",
        "proof_digest",
    }
    seen = set()
    for item in imports:
        if not isinstance(item, dict) or set(item) != expected:
            invalid("导入来源证明字段不完整")
        try:
            checked_source_context(item["source_context"])
            source = item["source_context"]["source"]
            identity = UUID(source["document_version_id"])
            candidate = UUID(item["candidate_id"])
            checked_uuid(item["draft_id"])
            if (
                item["protocol"] != PROVENANCE_PROTOCOL
                or candidate in seen
                or not isinstance(item["section_ids"], list)
                or not item["section_ids"]
                or len(item["section_ids"]) > 500
                or len(set(item["section_ids"])) != len(item["section_ids"])
                or sha({k: v for k, v in item.items() if k != "proof_digest"})
                != item["proof_digest"]
            ):
                invalid("导入来源证明摘要、项目或章节身份不匹配")
            for section in item["section_ids"]:
                checked_uuid(section)
            checked_uuid(item["bid_id"])
            if item["source_context"].get("source_id") != str(original_source_id(identity)):
                invalid("导入原件来源身份与文档版本不匹配")
            for name in ("candidate_digest", "method_digest", "content_digest", "proof_digest"):
                checked_digest(item[name])
        except (KeyError, TypeError, ValueError, AttributeError):
            invalid("导入来源证明无法解释")
        seen.add(candidate)
    return imports


def checked_copies(metadata):
    copies = metadata.get("word_import_copies", [])
    if not isinstance(copies, list) or len(copies) > 2000:
        invalid("导入来源的复制映射超过允许范围")
    parents = {}
    for item in copies:
        try:
            if not isinstance(item, dict) or set(item) != {
                "source_section_id",
                "target_section_id",
            }:
                raise ValueError
            source, target = item["source_section_id"], item["target_section_id"]
            if (
                str(UUID(source)) != source
                or str(UUID(target)) != target
                or source == target
                or target in parents
            ):
                raise ValueError
            parents[target] = source
        except (TypeError, ValueError, AttributeError):
            invalid("导入章节复制关系必须为唯一且规范的不同章节身份")
    for target in parents:
        visited, current = set(), target
        while current in parents:
            if current in visited:
                invalid("导入来源的章节复制关系不能成环")
            visited.add(current)
            current = parents[current]
    return parents


def active_imports(metadata, *, section_ids=None):
    imports = checked_imports(metadata)
    parents = checked_copies(metadata)
    if section_ids is None:
        return imports
    try:
        active = {str(UUID(str(value))) for value in section_ids}
    except (TypeError, ValueError, AttributeError):
        invalid("活动章节身份无效")
    selected = []
    for item in imports:
        ancestors = set(item["section_ids"])
        for section in active:
            current = section
            while current not in ancestors and current in parents:
                current = parents[current]
            if current in ancestors:
                selected.append(item)
                break
    return selected


def import_source_ids(metadata, *, section_ids=None):
    return sorted(
        {
            item["source_context"]["source_id"]
            for item in active_imports(metadata, section_ids=section_ids)
        }
    )


def extend_import_copies(metadata, copied_from):
    """Preserve immutable import proofs; record provenance of real chapter copies."""
    imports = checked_imports(metadata)
    parents = checked_copies(metadata)
    result = deepcopy(metadata)
    if not imports or not copied_from:
        return result
    prospective = deepcopy(metadata)
    prospective["word_import_copies"] = deepcopy(metadata.get("word_import_copies", [])) + [
        {"source_section_id": source, "target_section_id": target}
        for target, source in copied_from.items()
    ]
    combined = checked_copies(prospective)
    imported = {identity for item in imports for identity in item["section_ids"]}
    additions = []
    for target, source in sorted(copied_from.items()):
        current = source
        while current not in imported and current in combined:
            current = combined[current]
        if current in imported:
            additions.append({"source_section_id": source, "target_section_id": target})
    if additions:
        result["word_import_copies"] = [
            {"source_section_id": source, "target_section_id": target}
            for target, source in parents.items()
        ] + additions
    return result


def assert_import_sources(c, bid, metadata, *, section_ids=None, lock_sources=True):
    """Check active original/copy provenance with either RC locks or read-only RR."""
    values, direct = [], []
    for item in active_imports(metadata, section_ids=section_ids):
        if item["bid_id"] != str(bid):
            invalid("导入来源证明不属于当前项目")
        identity = UUID(item["source_context"]["source"]["document_version_id"])
        current, _ = capture(c, bid, identity, lock_sources=lock_sources)
        if current != item["source_context"]:
            invalid("导入原件或祖先效力与已确认候选不同，请重新核对")
        values.append(
            {
                "candidate_id": item["candidate_id"],
                "proof_digest": item["proof_digest"],
                "source_context": current,
            }
        )
        direct.append(current["source_id"])
    return {
        "protocol": "authoring-word-import-authority/1",
        "items": values,
        "direct_source_ids": sorted(set(direct)),
    }


def image_source(candidate, bid, manifest, source_part):
    value = {
        "protocol": IMAGE_PROTOCOL,
        "bid_id": str(bid),
        "candidate_id": str(candidate),
        "candidate_digest": sha(manifest),
        "source_part": source_part,
        "source_context": deepcopy(manifest["source_context"]),
    }
    return value | {"proof_digest": sha(value)}


def checked_image_source(proof):
    if not isinstance(proof, dict):
        invalid("图片规范化证明不是对象")
    if "word_import_source" not in proof:
        if proof.get("input_origin") == "external_docx_embedded_raster":
            invalid("Word 图片缺少原件来源证明")
        return None
    item = proof["word_import_source"]
    try:
        if not isinstance(item, dict) or set(item) != {
            "protocol",
            "bid_id",
            "candidate_id",
            "candidate_digest",
            "source_part",
            "source_context",
            "proof_digest",
        }:
            invalid("Word 图片来源证明字段不完整")
        checked_uuid(item["bid_id"])
        checked_uuid(item["candidate_id"])
        checked_digest(item["candidate_digest"])
        checked_digest(item["proof_digest"])
        checked_source_context(item["source_context"])
        if (
            item["protocol"] != IMAGE_PROTOCOL
            or proof.get("input_origin") != "external_docx_embedded_raster"
            or not isinstance(item["source_part"], str)
            or not item["source_part"].startswith("word/media/")
            or any(part in {"", ".", ".."} for part in item["source_part"].split("/"))
            or sha({k: v for k, v in item.items() if k != "proof_digest"}) != item["proof_digest"]
        ):
            invalid("Word 图片来源摘要、路径或协议不一致")
    except (KeyError, TypeError, ValueError, AttributeError):
        invalid("Word 图片来源证明无法解释")
    return item


def image_import_source_ids(proof):
    item = checked_image_source(proof)
    return [item["source_context"]["source_id"]] if item else []


def assert_image_import_source(c, bid, proof, *, lock_sources=True):
    item = checked_image_source(proof)
    values, direct = [], []
    if item:
        if item["bid_id"] != str(bid):
            invalid("Word 图片原件不属于当前项目")
        current, _ = capture(
            c,
            bid,
            UUID(item["source_context"]["source"]["document_version_id"]),
            lock_sources=lock_sources,
        )
        if current != item["source_context"]:
            invalid("Word 图片原件或祖先效力与已确认来源不同")
        values.append(
            {
                "candidate_id": item["candidate_id"],
                "proof_digest": item["proof_digest"],
                "source_context": current,
            }
        )
        direct.append(current["source_id"])
    return {
        "protocol": "authoring-word-import-image-authority/1",
        "items": values,
        "direct_source_ids": direct,
    }
