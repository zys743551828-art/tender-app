"""Standalone exact-file parse requests. Never moves material or current-body heads."""

from psycopg.types.json import Jsonb

from packages.authoring.package_outputs import observe_admission
from packages.contracts.document_parses_api import validate
from packages.domain import document_parse_policy as policy
from packages.domain.runtime import (
    DomainError,
    audit,
    clean,
    connection,
    enqueue_plan,
    fetch,
    now,
    sha,
    uid,
)
from packages.domain.work_access import begin
from packages.identity import pagination
from packages.knowledge import sources
from packages.rag.indexing import original_source_id

EVENT = "document.parse_requested"
SELECT = """SELECT r.*,o.kind AS operation_kind,o.state AS operation_state,
 o.input_digest AS operation_digest,o.handler_version,o.created_at AS operation_created_at,
 o.finished_at,s.output->>'error_code' AS error_code,result.manifest AS result
 FROM design.document_parse_requests r
 JOIN design.operations o ON o.id=r.operation_id AND o.bid_id=r.bid_id
 LEFT JOIN design.step_receipts s ON s.operation_id=o.id AND s.step_key='parse-document' AND s.input_digest=o.input_digest
 LEFT JOIN design.document_parse_results result ON result.request_id=r.id AND result.bid_id=r.bid_id"""


def capture(c, bid, document, method):
    row = c.execute(
        """SELECT d.id,d.bid_id,d.original_name,d.artifact_kind,d.obtained_at,
        b.digest,b.byte_size,b.media_type,b.object_key,v.file_id,v.revision AS file_revision,f.role
        FROM design.document_versions d JOIN design.blobs b ON b.id=d.blob_id
        JOIN design.document_file_versions v ON v.version_id=d.id AND v.bid_id=d.bid_id
        JOIN design.document_files f ON f.id=v.file_id AND f.bid_id=v.bid_id
        WHERE d.bid_id=%s AND d.id=%s""",
        (bid, document),
    ).fetchone()
    if row is None:
        raise DomainError(
            "DOCUMENT_PARSE_ORIGINAL_NOT_FOUND", "所选文件尚未提交为本项目的精确原件", 404
        )
    if (
        row["media_type"] != "application/pdf"
        or row["artifact_kind"] not in {"source_original", "bid_body"}
        or row["role"] not in {"body", "tender", "supplement", "drawing", "boq"}
    ):
        raise DomainError(
            "DOCUMENT_PARSE_ORIGINAL_UNSUPPORTED",
            "此入口读取已提交 PDF 原页；Word 须先完成受控转换",
            422,
        )
    if not 0 < row["byte_size"] <= policy.MAX_BYTES:
        raise DomainError(
            "DOCUMENT_PARSE_ORIGINAL_TOO_LARGE", "原件超过本轮解析的 100 MiB 上限", 413
        )
    admitted = observe_admission(c, bid, document)
    if admitted is not None:
        if admitted["state"] != "matched":
            raise DomainError(
                "DOCUMENT_PARSE_GENERATED_UNPROVEN",
                "生成文件尚未明确采用或其当前来源资格已变化",
                409,
            )
        qualification = {"kind": "adopted_generated", "identity_digest": sha(admitted)}
    else:
        upload = c.execute(
            """SELECT id,role,declared_digest,declared_size FROM design.uploads
            WHERE bid_id=%s AND verified_version_id=%s AND state='verified'
            AND role=%s AND declared_digest=%s AND declared_size=%s ORDER BY id""",
            (bid, document, row["role"], row["digest"], row["byte_size"]),
        ).fetchall()
        if len(upload) != 1:
            raise DomainError(
                "DOCUMENT_PARSE_ORIGINAL_UNPROVEN", "原件缺少精确上传核验或生成文件采用凭证", 409
            )
        qualification = {"kind": "verified_upload", "identity_digest": sha(clean(upload[0]))}
    root = original_source_id(document)
    node = c.execute("SELECT * FROM retrieval.source_nodes WHERE id=%s", (root,)).fetchone()
    if node is None:
        source = {"root_id": str(root), "state": "unregistered", "authority_digest": sha([])}
    else:
        if (
            str(node["document_version_id"]) != str(document)
            or node["kind"] != "document"
            or node["digest"] != row["digest"]
            or node["policy_class"] != "prebid_content"
        ):
            raise DomainError(
                "DOCUMENT_PARSE_SOURCE_INVALID", "原件来源身份或用途限制无法核对", 409
            )
        authority = sources.authority_manifest(c, [root], now())
        if any(item["policy_class"] != "prebid_content" for item in authority):
            raise DomainError(
                "DOCUMENT_PARSE_SOURCE_INVALID", "原件祖先用途不允许本轮投标准备使用", 409
            )
        source = {"root_id": str(root), "state": "published", "authority_digest": sha(authority)}
    context = clean(
        {
            "protocol": "document-parse-context/1",
            "bid_id": str(bid),
            "document_version_id": str(document),
            "document": {
                "sha256": row["digest"],
                "byte_size": row["byte_size"],
                "media_type": row["media_type"],
                "filename": row["original_name"],
                "file_id": row["file_id"],
                "file_revision": row["file_revision"],
                "role": row["role"],
                "artifact_kind": row["artifact_kind"],
                "locator_digest": sha(row["object_key"].encode()),
            },
            "qualification": qualification,
            "source": source,
            "method": method,
            "current_body_changed": False,
            "automatically_started_review": False,
            "word_coverage_claimed": False,
        }
    )
    return context, clean(dict(row))


def read_context(bid, document):
    method, _ = policy.method()
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        context, _ = capture(c, bid, document, method)
    return {"context": context, "context_digest": sha(context)}


def view(row):
    row = clean(row)
    manifest = row["input_manifest"]
    if (
        sha(manifest) != row["input_digest"]
        or row["operation_digest"] != row["input_digest"]
        or row["handler_version"] != policy.HANDLER
        or row["operation_kind"] != policy.STEP
        or manifest["bid_id"] != row["bid_id"]
        or manifest["document_version_id"] != row["document_version_id"]
    ):
        raise DomainError("DOCUMENT_PARSE_RECORD_CORRUPT", "解析申请与操作身份无法核对", 500)
    return {
        "protocol": "document-parse-request/1",
        "id": row["id"],
        "bid_id": row["bid_id"],
        "document_version_id": row["document_version_id"],
        "actor_id": row["actor_id"],
        "created_at": row["created_at"],
        "context": manifest,
        "context_digest": row["input_digest"],
        "reason": row["reason"],
        "operation": {
            "id": row["operation_id"],
            "kind": row["operation_kind"],
            "state": row["operation_state"],
            "input_digest": row["operation_digest"],
            "handler_version": row["handler_version"],
            "error_code": row["error_code"],
            "created_at": row["operation_created_at"],
            "finished_at": row["finished_at"],
        },
        "result": row["result"],
        "current_body_changed": False,
        "automatically_started_review": False,
    }


def load(c, bid, document, request_id):
    row = c.execute(
        SELECT + " WHERE r.bid_id=%s AND r.document_version_id=%s AND r.id=%s",
        (bid, document, request_id),
    ).fetchone()
    if row is None:
        raise DomainError("DOCUMENT_PARSE_REQUEST_NOT_FOUND", "此项目原件的解析申请不存在", 404)
    return view(row)


def replay(c, bid, document, actor, key, body):
    row = c.execute(
        "SELECT request_digest,response FROM design.commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, policy.KIND, document, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != sha({"body": {"bid_id": str(bid), **body}, "if_match": None}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一解析命令对应不同输入", 409)
    response = row["response"]
    if response is None:
        raise DomainError("COMMAND_INCOMPLETE", "原解析申请尚未形成回执", 409)
    if response["body"]["request"]["bid_id"] != str(bid) or response["body"]["request"][
        "document_version_id"
    ] != str(document):
        raise DomainError("DOCUMENT_PARSE_SCOPE_MISMATCH", "解析回执不属于所选项目原件", 409)
    return response


def start(bid, document, actor, key, body, *, final_auth=None):
    validate("StartDocumentParse", body)
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的解析申请幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = replay(c, bid, document, actor, key, body)
    if old is not None:
        return old, True
    method, _ = policy.method()
    if final_auth is not None and str(final_auth()) != str(actor):
        raise DomainError("DOCUMENT_PARSE_ACTOR_CHANGED", "登录成员变化，未创建新解析申请", 409)
    with connection() as c:
        request_body = {"bid_id": str(bid), **body}
        command = begin(c, actor, policy.KIND, document, key, request_body, None, bid=bid)
        if command.replay is not None:
            return command.replay, True
        sources.lock_graph(c)
        context, _ = capture(c, bid, document, method)
        fingerprint = sha(context)
        if fingerprint != body["context_digest"]:
            raise DomainError(
                "DOCUMENT_PARSE_CONTEXT_CHANGED",
                "文件、来源或解析方法变化，请重新读取并明确选择",
                409,
            )
        existing = c.execute(
            SELECT
            + " WHERE r.bid_id=%s AND r.document_version_id=%s AND r.input_digest=%s AND o.state IN('queued','running','cancel_requested','succeeded') ORDER BY r.created_at,r.id LIMIT 1",
            (bid, document, fingerprint),
        ).fetchone()
        reused = existing is not None
        if existing is None:
            request_id = uid()
            operation = enqueue_plan(
                c,
                bid,
                command.id,
                policy.STEP,
                {"id": str(request_id)},
                stages=[{"key": policy.STEP, "depends_on": []}],
                handler_version=policy.HANDLER,
                topic="tender.task.document.v1",
                input_digest=fingerprint,
            )
            c.execute(
                "INSERT INTO design.document_parse_requests(id,bid_id,document_version_id,actor_id,command_id,operation_id,input_manifest,input_digest,reason) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    request_id,
                    bid,
                    document,
                    actor,
                    command.id,
                    operation["id"],
                    Jsonb(context),
                    fingerprint,
                    body["reason"],
                ),
            )
            value = load(c, bid, document, request_id)
            audit(
                c,
                actor,
                bid,
                EVENT,
                {
                    "request_id": str(request_id),
                    "document_version_id": str(document),
                    "operation_id": operation["id"],
                    "context_digest": fingerprint,
                },
                command.id,
            )
        else:
            value = view(existing)
        ack = {
            "protocol": "document-parse-start/1",
            "actor_id": str(actor),
            "command_id": str(command.id),
            "request_digest": sha({"body": request_body, "if_match": None}),
            "reused": reused,
            "request": value,
        }
        return command.finish(ack, 202), False


def read(bid, document, request_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return load(c, bid, document, request_id)


def directory(bid, document, *, limit=10, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise DomainError("INVALID_REQUEST", "每页解析申请数量须为 1 至 50", 422)
    marker = sha(
        {"directory": "document-parse/1", "bid_id": str(bid), "document_version_id": str(document)}
    )
    after = pagination.decode(cursor, marker)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        fetch(
            c, "SELECT id FROM design.document_versions WHERE bid_id=%s AND id=%s", (bid, document)
        )
        rows = c.execute(
            SELECT
            + " WHERE r.bid_id=%s AND r.document_version_id=%s AND (%s::uuid IS NULL OR r.id>%s) ORDER BY r.id LIMIT %s",
            (bid, document, after[-1] if after else None, after[-1] if after else None, limit + 1),
        ).fetchall()
        items = [view(row) for row in rows[:limit]]
    more = len(rows) > limit
    return {
        "bid_id": str(bid),
        "document_version_id": str(document),
        "items": items,
        "has_more": more,
        "next_cursor": pagination.encode(marker, ["", items[-1]["id"]]) if more else None,
    }
