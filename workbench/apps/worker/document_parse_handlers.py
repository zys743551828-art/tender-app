"""One exact original, transaction-free byte/parser IO, fenced append-only publish."""

import hashlib
from contextlib import closing

from botocore.exceptions import BotoCoreError, ClientError
from psycopg.types.json import Jsonb

from packages.domain import document_parse_policy as policy
from packages.domain import document_parses as repository
from packages.domain import storage
from packages.domain.runtime import DomainError, audit, clean, connection, fetch, sha, uid
from packages.knowledge import sources
from packages.parsing.http_port import ParsingUnavailable
from packages.parsing.physical_pdf import extract


def _record(c, message):
    if message["handler_version"] != policy.HANDLER or message["step_key"] != policy.STEP:
        raise DomainError("DOCUMENT_PARSE_TASK_INVALID", "原件解析阶段不匹配", 409)
    row = clean(
        fetch(
            c,
            "SELECT * FROM design.document_parse_requests WHERE bid_id=%s AND id=%s",
            (message["bid_id"], message["payload_ref"]),
        )
    )
    if (
        row["operation_id"] != message["operation_id"]
        or row["input_digest"] != message["input_digest"]
        or sha(row["input_manifest"]) != row["input_digest"]
    ):
        raise DomainError("DOCUMENT_PARSE_TASK_INVALID", "解析任务与固定申请身份不一致", 409)
    context, document = repository.capture(
        c, row["bid_id"], row["document_version_id"], row["input_manifest"]["method"]
    )
    if (
        context != row["input_manifest"]
        or context["method"]["implementation_digest"] != policy.implementation_digest()
    ):
        raise DomainError(
            "DOCUMENT_PARSE_CONTEXT_CHANGED", "原件、来源资格或解析实现变化，未使用迟到结果", 409
        )
    return row, document


def _bytes(document):
    """Bounded digest+length verification and buffering outside every transaction."""
    size = document["byte_size"]
    if type(size) is not int or not 0 < size <= policy.MAX_BYTES:
        raise DomainError("DOCUMENT_PARSE_ORIGINAL_TOO_LARGE", "原件大小超过解析上限", 413)
    try:
        response = storage.client().get_object(Bucket=storage.bucket(), Key=document["object_key"])
        parts, count, digest = [], 0, hashlib.sha256()
        with closing(response["Body"]) as stream:
            while True:
                part = stream.read(min(1024 * 1024, size - count + 1))
                if not part:
                    break
                count += len(part)
                if count > size:
                    raise DomainError("ORIGINAL_BYTES_CORRUPTED", "原件实际字节大小不一致", 409)
                digest.update(part)
                parts.append(part)
        if count != size or digest.hexdigest() != document["digest"]:
            raise DomainError("ORIGINAL_BYTES_CORRUPTED", "原件实际摘要不一致", 409)
        data = b"".join(parts)
        if not data.startswith(b"%PDF-"):
            raise DomainError("DOCUMENT_PARSE_ORIGINAL_UNSUPPORTED", "原件不是有效的 PDF 字节", 422)
        return data
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "NotFound", "404"}:
            raise DomainError("ORIGINAL_NOT_AVAILABLE", "所选原件目前不可读取", 409) from None
        raise DomainError(
            "OBJECT_STORE_UNAVAILABLE", "对象存储读取失败", 503, retryable=True
        ) from None
    except (BotoCoreError, OSError):
        raise DomainError(
            "OBJECT_STORE_UNAVAILABLE", "对象存储读取失败", 503, retryable=True
        ) from None


def compute(message, lease=None):
    with connection(True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        before, original = _record(c, message)
    selected, parser = policy.method()
    if selected != before["input_manifest"]["method"]:
        raise DomainError(
            "DOCUMENT_PARSE_METHOD_CHANGED", "解析能力身份变化，请读取当前方法后重新申请", 409
        )
    data = _bytes(original)
    try:
        raw = parser.parse(data) if parser else extract(data, max_pages=policy.MAX_PAGES)
    except ParsingUnavailable as error:
        raise DomainError(
            "PARSING_RUNTIME_UNAVAILABLE", "解析服务未完成原页读取", 503, retryable=True
        ) from error
    parsed = policy.normalize(raw, selected)
    with connection(True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        after, current = _record(c, message)
    if before != after or original != current:
        raise DomainError(
            "DOCUMENT_PARSE_CONTEXT_CHANGED", "读取期间原件或来源变化，未发布解析", 409
        )
    return {
        "request_id": before["id"],
        "input_digest": before["input_digest"],
        "source_digest": original["digest"],
        "parsed": parsed,
        "parsed_digest": sha(policy.encoded(parsed)),
    }


def publish(c, message, outcome):
    # engine.finish already holds the bid / operation / current lease fence.
    sources.lock_graph(c)
    record, document = _record(c, message)
    parsed = outcome["parsed"]
    method = record["input_manifest"]["method"]
    checked = policy.normalize(parsed, method, frozen=True)
    if (
        outcome["request_id"] != record["id"]
        or outcome["input_digest"] != record["input_digest"]
        or outcome["source_digest"] != document["digest"]
        or sha(policy.encoded(parsed)) != outcome["parsed_digest"]
        or checked != parsed
        or parsed["parser_digest"] != method["parser_digest"]
        or parsed["config_digest"] != method["config_digest"]
    ):
        raise DomainError("DOCUMENT_PARSE_RESULT_CHANGED", "解析输出与原件或固定方法不一致", 409)
    parse_id = uid()
    c.execute(
        "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            parse_id,
            record["bid_id"],
            record["document_version_id"],
            method["parser_digest"],
            method["config_digest"],
            len(parsed["pages"]),
            parsed["coverage"],
            Jsonb(parsed["gaps"]),
        ),
    )
    evidence_count = 0
    for page in parsed["pages"]:
        c.execute(
            "INSERT INTO design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                record["bid_id"],
                parse_id,
                page["physical_page"],
                page["width"],
                page["height"],
                page["rotation"],
                page["quality"],
                Jsonb(page["gaps"]),
            ),
        )
        for block in page["blocks"]:
            evidence_count += 1
            c.execute(
                "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest,bbox,structure) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    uid(),
                    record["bid_id"],
                    parse_id,
                    page["physical_page"],
                    block["ordinal"],
                    block["kind"],
                    block["text_content"],
                    block["digest"],
                    Jsonb(block["bbox"]) if block["bbox"] is not None else None,
                    Jsonb(block["structure"]) if block["structure"] else None,
                ),
            )
    from apps.worker.handlers import publish_readable_source

    publish_readable_source(c, record["bid_id"], parse_id)
    result = {
        "parse_run_id": str(parse_id),
        "document_version_id": record["document_version_id"],
        "source_digest": document["digest"],
        "parser_digest": method["parser_digest"],
        "config_digest": method["config_digest"],
        "parsed_digest": outcome["parsed_digest"],
        "coverage": parsed["coverage"],
        "page_count": len(parsed["pages"]),
        "evidence_count": evidence_count,
        "gaps": parsed["gaps"][:100],
        "gap_count": len(parsed["gaps"]),
        "word_coverage_claimed": False,
    }
    c.execute(
        "INSERT INTO design.document_parse_results(request_id,bid_id,operation_id,document_version_id,parse_run_id,manifest,digest) VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (
            record["id"],
            record["bid_id"],
            record["operation_id"],
            record["document_version_id"],
            parse_id,
            Jsonb(result),
            sha(result),
        ),
    )
    output = {
        "result_ref": f"/api/v1/bids/{record['bid_id']}/documents/{record['document_version_id']}/parse-requests/{record['id']}",
        "request_id": record["id"],
        "document_version_id": record["document_version_id"],
        "parse_run_id": str(parse_id),
        "result_digest": sha(result),
        "coverage": parsed["coverage"],
        "current_body_changed": False,
        "automatically_started_review": False,
    }
    audit(
        c,
        record["actor_id"],
        record["bid_id"],
        "document.parse_published",
        {key: value for key, value in output.items() if key != "result_ref"},
    )
    return output
