"""任务处理器接口与解析处理器。

处理器只“计算并交出结果”，不自己提交：它返回 ``HandlerOutput``（产物字节 + 一个在提交事务内执行的 ``finalize``）。
运行器在同一个事务里先校验租约（``commit_result``）再执行 ``finalize`` 写领域记录，因此租约已丢的旧尝试
不可能留下半截的解析/证据/问题记录。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from sqlalchemy import Connection, Engine, text

from bidwb import db, parsing
from bidwb.config import Settings
from bidwb.storage import ObjectStore
from bidwb.tasks import Claim
from bidwb.util import new_id, utcnow

Finalize = Callable[[Connection, str], None]  # (连接, 已提交的产物 ID)


class LeaseLost(Exception):
    """租约已丢失或任务被请求取消：处理器应立即停止，不再写任何东西。"""


@dataclass(frozen=True)
class HandlerOutput:
    artifact_bytes: bytes
    media_type: str
    contract_version: str
    finalize: Finalize
    coverage: dict[str, Any] | None = None  # 结果覆盖度（诊断）：随任务保存并对外展示；不完整时项目不得进入可登记提交
    message: str = ""  # 覆盖不完整时面向人的中文提示


@dataclass(frozen=True)
class HandlerFailure:
    """确定性失败（重试也不会好）：任务标记失败并记录错误码。"""

    error_code: str
    message: str = ""  # 面向人的中文原因，写进任务失败事件与日志；错误码才是对外契约


@dataclass
class JobContext:
    claim: Claim
    engine: Engine
    store: ObjectStore
    settings: Settings
    checkpoint: Callable[[], None]  # 长计算中定期调用；租约丢失时抛 LeaseLost


class Handler(Protocol):
    def __call__(self, ctx: JobContext) -> HandlerOutput | HandlerFailure: ...


# ------------------------------------------------------------------ 解析
def parse_handler(ctx: JobContext) -> HandlerOutput | HandlerFailure:
    version_id = ctx.claim.input_json.get("file_version_id")
    if not isinstance(version_id, str):
        return HandlerFailure("invalid_job_input")
    with ctx.engine.connect() as conn:
        row = db.one(
            conn,
            """SELECT a.object_key,a.media_type,a.status,a.sha256 FROM file_versions fv JOIN artifacts a ON a.id=fv.artifact_id
               WHERE fv.id=:v AND fv.project_id=:p""",
            {"v": version_id, "p": ctx.claim.project_id},
        )
    if row is None or row["status"] != "committed":
        return HandlerFailure("file_version_not_found")
    data = ctx.store.get(row["object_key"])  # 存储异常向上抛，由运行器按暂时性故障重试
    ctx.checkpoint()
    document: parsing.ParsedDocument
    if row["media_type"] != "application/pdf" and not data.startswith(b"%PDF"):
        document = parsing.ParsedDocument(page_count=0, gaps=["unsupported_media_type"])
    else:
        try:
            document = parsing.parse_pdf(data)
        except parsing.ParseError:
            document = parsing.ParsedDocument(page_count=0, gaps=["unreadable_pdf"])
    ctx.checkpoint()
    if document.coverage == "failed":
        # 读不出文字（非 PDF、加密、纯扫描件）：确定性失败，重试也不会好。任务标记失败并说明原因，
        # 不写解析记录——这样界面显示“解析失败”，快照也不会把它当作可用输入。
        if "unsupported_media_type" in document.gaps:
            return HandlerFailure("parse_unsupported", "只支持 PDF 格式，请转换为 PDF 后重新上传")
        return HandlerFailure("parse_unreadable", "没有读到文字（可能是扫描件或加密文件），请提供可复制文字的 PDF 后重新上传")
    summary = {
        "parser_version": parsing.PARSER_VERSION,
        "file_version_id": version_id,
        "source_sha256": row["sha256"],
        "page_count": document.page_count,
        "coverage": document.coverage,
        "gaps": document.gaps,
        "chunk_count": len(document.chunks),
        "page_text_chars": document.page_text_chars,
        "coverage_scope": "native_text_and_raster_presence",
        "pages": [asdict(page) for page in document.pages],
    }
    claim = ctx.claim

    def finalize(conn: Connection, artifact_id: str) -> None:
        parse_id = new_id("prs")
        db.run(
            conn,
            """INSERT INTO parses(id,project_id,file_version_id,parser_version,page_count,coverage,gaps_json,artifact_id,created_at)
               VALUES (:i,:p,:v,:pv,:n,:c,CAST(:g AS jsonb),:a,:now)""",
            {
                "i": parse_id,
                "p": claim.project_id,
                "v": version_id,
                "pv": parsing.PARSER_VERSION,
                "n": document.page_count,
                "c": document.coverage,
                "g": json.dumps(document.gaps),
                "a": artifact_id,
                "now": utcnow(),
            },
        )
        if document.chunks:
            conn.execute(
                text("""INSERT INTO evidence(id,project_id,file_version_id,parse_id,physical_page,printed_page,quote,kind,seq,bbox_json,semantic_review)
                        VALUES (:id,:p,:v,:parse,:page,NULL,:quote,'text',:seq,CAST(:bbox AS jsonb),'pending')"""),
                [
                    {
                        "id": new_id("evd"),
                        "p": claim.project_id,
                        "v": version_id,
                        "parse": parse_id,
                        "page": c.physical_page,
                        "quote": c.quote,
                        "seq": seq,
                        "bbox": json.dumps(c.bbox) if c.bbox is not None else None,
                    }
                    for seq, c in enumerate(document.chunks)
                ],
            )

    return HandlerOutput(json.dumps(summary, ensure_ascii=False, sort_keys=True).encode(), "application/json", "parse-v1", finalize)


def default_handlers() -> dict[str, Handler]:
    return {"parse": parse_handler}
