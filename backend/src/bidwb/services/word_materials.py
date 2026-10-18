"""原件、PDF 对应声明与采用决定；转换结果到达不改变原稿的先后顺序。"""

from __future__ import annotations

import json
from pathlib import PurePath
from typing import Any

from sqlalchemy import Connection

from bidwb import db, tasks
from bidwb.errors import Conflict, NotFound, Unprocessable
from bidwb.schemas import WordPdfCandidate, WordStatus
from bidwb.services import audit
from bidwb.util import new_id

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def is_word(name: str, media_type: str) -> bool:
    return media_type in {DOCX, "application/msword"} or PurePath(name).suffix.lower() in {".doc", ".docx"}


def family(name: str, media_type: str) -> str:
    if is_word(name, media_type):
        return "word"
    return "pdf" if media_type == "application/pdf" or name.lower().endswith(".pdf") else "other"


def source(conn: Connection, project_id: str, version_id: str) -> db.Row:
    row = db.one(
        conn,
        """SELECT fv.*,f.role,a.sha256,a.media_type FROM file_versions fv
       JOIN files f ON f.id=fv.file_id JOIN artifacts a ON a.id=fv.artifact_id
       WHERE fv.id=:v AND fv.project_id=:p AND a.status='committed'""",
        {"v": version_id, "p": project_id},
    )
    if row is None:
        raise NotFound("file_not_found")
    if not is_word(row["original_name"], row["media_type"]):
        raise Unprocessable("word_source_required", "请选择 Word 原稿")
    return row


def current(conn: Connection, row: db.Row) -> bool:
    latest = db.scalar(
        conn, "SELECT id FROM file_versions WHERE file_id=:f ORDER BY obtained_at DESC,id DESC LIMIT 1", {"f": row["file_id"]}
    )
    return bool(latest == row["id"])


def lock(conn: Connection, project_id: str) -> None:
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})


def adopt(conn: Connection, project_id: str, version_id: str, link_id: str, actor_id: str | None, reason: str) -> None:
    lock(conn, project_id)
    original = source(conn, project_id, version_id)
    if not current(conn, original):
        raise Conflict("word_source_stale", "该 Word 已有新版本，请为最新原稿提供或核对 PDF")
    link = db.one(
        conn,
        "SELECT * FROM word_pdf_links WHERE id=:l AND project_id=:p AND source_version_id=:v",
        {"l": link_id, "p": project_id, "v": version_id},
    )
    if link is None:
        raise NotFound("word_pdf_link_not_found")
    if not db.scalar(
        conn,
        """SELECT NOT EXISTS(SELECT 1 FROM file_versions n WHERE n.file_id=p.file_id AND (n.obtained_at,n.id)>(p.obtained_at,p.id))
        FROM file_versions p WHERE p.id=:v""",
        {"v": link["pdf_version_id"]},
    ):
        raise Conflict("word_pdf_stale", "PDF 已有更新版本，请核对最新文件")
    if not reason.strip():
        raise Unprocessable("reason_required", "请说明采用依据")
    adoption = new_id("wad")
    db.run(
        conn,
        """INSERT INTO word_pdf_adoptions(id,project_id,source_version_id,pdf_version_id,link_id,actor_id,reason)
       VALUES (:i,:p,:v,:pdf,:l,:a,:r)""",
        {"i": adoption, "p": project_id, "v": version_id, "pdf": link["pdf_version_id"], "l": link_id, "a": actor_id, "r": reason},
    )
    audit.record(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        action="word.pdf_adopted",
        object_kind="word_pdf_adoption",
        object_id=adoption,
        request_id=adoption,
        details={"source_version_id": version_id, "pdf_version_id": link["pdf_version_id"], "method": link["method"], "reason": reason},
    )


def link_pdf(
    conn: Connection, project_id: str, original: db.Row, pdf_id: str, method: str, actor_id: str | None, conversion_id: str | None = None
) -> str:
    pdf = db.one(
        conn,
        """SELECT fv.file_id,f.role,a.media_type FROM file_versions fv JOIN files f ON f.id=fv.file_id
        JOIN artifacts a ON a.id=fv.artifact_id WHERE fv.id=:v AND fv.project_id=:p""",
        {"v": pdf_id, "p": project_id},
    )
    if pdf is None or pdf["media_type"] != "application/pdf" or pdf["file_id"] == original["file_id"] or pdf["role"] != original["role"]:
        raise Unprocessable("word_pdf_identity_invalid", "实际 PDF 必须与原稿同用途，并保存在独立文件中")
    identity = new_id("wpl")
    db.run(
        conn,
        """INSERT INTO word_pdf_links(id,project_id,source_version_id,pdf_version_id,method,conversion_id,created_by)
        VALUES (:i,:p,:v,:pdf,:m,:c,:a)""",
        {"i": identity, "p": project_id, "v": original["id"], "pdf": pdf_id, "m": method, "c": conversion_id, "a": actor_id},
    )
    return identity


def record_conversion(
    conn: Connection, project_id: str, version_id: str, job_id: str, attempt: int, report: dict[str, Any], pdf_id: str | None
) -> str:
    identity = new_id("wcv")
    db.run(
        conn,
        """INSERT INTO word_conversions(id,project_id,source_version_id,job_id,attempt,state,report_json,pdf_version_id)
        VALUES (:i,:p,:v,:j,:a,:s,CAST(:r AS jsonb),:pdf)""",
        {
            "i": identity,
            "p": project_id,
            "v": version_id,
            "j": job_id,
            "a": attempt,
            "s": report["state"],
            "r": json.dumps(report, ensure_ascii=False),
            "pdf": pdf_id,
        },
    )
    return identity


def status(conn: Connection, project_id: str, version_id: str) -> WordStatus:
    original = source(conn, project_id, version_id)
    receipt = db.one(
        conn,
        "SELECT state,report_json FROM word_conversions WHERE source_version_id=:v ORDER BY created_at DESC,id DESC LIMIT 1",
        {"v": version_id},
    )
    adoption = db.scalar(
        conn,
        "SELECT pdf_version_id FROM word_pdf_adoptions WHERE source_version_id=:v ORDER BY created_at DESC,id DESC LIMIT 1",
        {"v": version_id},
    )
    candidates = db.all_(
        conn,
        """SELECT l.*,c.report_json FROM word_pdf_links l LEFT JOIN word_conversions c ON c.id=l.conversion_id
        WHERE l.source_version_id=:v ORDER BY l.created_at DESC,l.id DESC""",
        {"v": version_id},
    )
    return WordStatus(
        current=current(conn, original),
        state=receipt["state"] if receipt else "waiting",
        error_code=receipt["report_json"].get("error_code") if receipt else None,
        adopted_pdf_version_id=adoption,
        candidates=[
            WordPdfCandidate(
                link_id=r["id"], pdf_version_id=r["pdf_version_id"], method=r["method"], gaps=(r["report_json"] or {}).get("gaps", [])
            )
            for r in candidates
        ],
    )


def enqueue_parse(conn: Connection, project_id: str, version_id: str, key: str) -> str:
    identity, _ = tasks.enqueue(
        conn, project_id=project_id, kind="parse", purpose="business", idempotency_key=key, input_json={"file_version_id": version_id}
    )
    return identity
