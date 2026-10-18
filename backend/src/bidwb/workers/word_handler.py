"""转换回执在租约保护的提交事务内保存；PDF 有独立原件和解析任务。"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePath
from typing import Any

from sqlalchemy import Connection

from bidwb import db
from bidwb.services import files, word_materials
from bidwb.storage import content_key
from bidwb.word_conversion import ConversionUnavailable, convert_word
from bidwb.workers.handlers import HandlerFailure, HandlerOutput, JobContext


def convert_handler(ctx: JobContext, version_id: str, name: str, data: bytes) -> HandlerOutput | HandlerFailure:
    settings = ctx.settings
    pdf: bytes | None = None
    report: dict[str, Any]
    try:
        if not settings.word_input_dir or not settings.word_output_dir or not settings.word_renderer_fingerprint:
            raise ConversionUnavailable("word_renderer_not_configured")
        converted = convert_word(
            data,
            name,
            input_dir=settings.word_input_dir,
            output_dir=settings.word_output_dir,
            renderer_fingerprint=settings.word_renderer_fingerprint,
            checkpoint=ctx.checkpoint,
        )
        report, pdf = converted.report, converted.pdf
    except ConversionUnavailable as error:
        report = {
            "state": "failed",
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "conversion_attempted": False if str(error) == "word_renderer_not_configured" else None,
            "error_code": str(error),
            "gaps": [],
        }
    ctx.checkpoint()
    claim = ctx.claim
    if pdf is None:

        def failed(conn: Connection) -> None:
            word_materials.record_conversion(conn, claim.project_id, version_id, claim.job_id, claim.attempt, report, None)

        return HandlerFailure("word_pdf_required", "Word 暂不能自动转换；请在此原稿处补交 PDF，无需重传其他资料", failed)
    digest = hashlib.sha256(pdf).hexdigest()
    key = content_key(digest)
    ctx.store.put(key, pdf, "application/pdf")
    ctx.checkpoint()

    def finalize(conn: Connection, _receipt_artifact_id: str) -> None:
        word_materials.lock(conn, claim.project_id)
        original = word_materials.source(conn, claim.project_id, version_id)
        artifact = files._artifact_for(conn, sha256=digest, size=len(pdf), media_type="application/pdf", key=key, status="committed")
        pdf_id = files._insert_version(
            conn,
            {
                "project_id": claim.project_id,
                "role": original["role"],
                "actor_id": original["created_by"],
                "original_name": PurePath(name).stem + ".转换.pdf",
            },
            artifact,
            None,
        )
        conversion = word_materials.record_conversion(conn, claim.project_id, version_id, claim.job_id, claim.attempt, report, pdf_id)
        link = word_materials.link_pdf(conn, claim.project_id, original, pdf_id, "controlled_render", None, conversion)
        if (
            report["state"] == "converted"
            and word_materials.current(conn, original)
            and not db.scalar(conn, "SELECT count(*) FROM word_pdf_adoptions WHERE source_version_id=:v", {"v": version_id})
        ):
            word_materials.adopt(
                conn, claim.project_id, version_id, link, None, "固定方法转换且文字、字体及有限布局检查无缺口；评审对象为实际 PDF"
            )
        word_materials.enqueue_parse(conn, claim.project_id, pdf_id, f"parse:{pdf_id}")

    return HandlerOutput(json.dumps(report, ensure_ascii=False).encode(), "application/json", "word-conversion-1", finalize)
