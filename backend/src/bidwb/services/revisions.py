"""改稿建议：发起（异步任务）、查询、采纳与驳回。

边界：系统只给出“哪一段、怎么改、依据哪条事实”的差异建议，不改写 PDF 正文。采纳表示使用者接受这份建议并去修改正文，
相关问题进入“待修改”；修改后的新正文版本由上传流程产生，复检（recheck）在后续批次实现。
建议本身追加保存；采纳/驳回是 ``reviews`` 里的一行，状态由最新一行与“基础版本是否仍是该文件最新版”推导。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection

from bidwb import db, tasks
from bidwb.access import Actor, require_project
from bidwb.errors import Conflict, NotFound, Unprocessable
from bidwb.schemas import AdoptRequest, ArtifactRef, RejectRevisionRequest, Revision, RevisionRequest, Task
from bidwb.services import audit
from bidwb.storage import ObjectStore
from bidwb.util import canonical_json, new_id, sha256_hex, utcnow

REVISION_KIND = "revision"


def _latest_version(conn: Connection, project_id: str, version_id: str) -> bool:
    from bidwb.services import current_materials  # noqa: PLC0415

    if db.scalar(conn, "SELECT count(*) FROM word_pdf_links WHERE pdf_version_id=:v", {"v": version_id}):
        return current_materials.active_body(conn, project_id) == version_id
    row = db.one(
        conn,
        """SELECT fv.id FROM file_versions fv WHERE fv.project_id=:p AND fv.file_id=(SELECT file_id FROM file_versions WHERE id=:v)
                          ORDER BY fv.obtained_at DESC, fv.id DESC LIMIT 1""",
        {"p": project_id, "v": version_id},
    )
    return row is not None and row["id"] == version_id


def propose(conn: Connection, actor: Actor, project_id: str, req: RevisionRequest, idempotency_key: str, request_id: str) -> Task:
    require_project(conn, actor, project_id)
    snapshot = db.one(
        conn,
        "SELECT sha256,body_version_id,fact_set_id FROM input_snapshots WHERE id=:s AND project_id=:p",
        {"s": req.snapshot_id, "p": project_id},
    )
    if snapshot is None:
        raise NotFound("snapshot_not_found")
    if snapshot["body_version_id"] != req.base_version_id:
        raise Unprocessable("base_version_mismatch", "基础版本必须是快照里的正文版本")
    if not _latest_version(conn, project_id, req.base_version_id):
        raise Conflict("base_version_stale", "正文已有更新版本，请基于最新版发起")
    finding_ids = sorted(set(req.finding_ids))
    rows = db.all_(
        conn,
        """SELECT f.id,s.state FROM findings f JOIN finding_states s ON s.finding_id=f.id
                            WHERE f.project_id=:p AND f.snapshot_id=:s AND f.id = ANY(:ids)""",
        {"p": project_id, "s": req.snapshot_id, "ids": finding_ids},
    )
    if len(rows) != len(finding_ids):
        raise NotFound("finding_not_found", "问题不存在或不属于该快照")
    unconfirmed = [r["id"] for r in rows if r["state"] != "confirmed"]
    if unconfirmed:
        raise Conflict("finding_not_confirmed", "只能针对已确认的问题生成建议", finding_ids=unconfirmed)
    fact_ids = sorted(set(req.allowed_fact_ids))
    if fact_ids:
        ok = db.all_(
            conn,
            "SELECT id FROM fact_items WHERE project_id=:p AND confirmation='confirmed' AND id = ANY(:ids)",
            {"p": project_id, "ids": fact_ids},
        )
        if len(ok) != len(fact_ids):
            raise Unprocessable("fact_not_confirmed", "允许使用的事实必须都是本项目已确认的事实")
    payload = {"base_version_id": req.base_version_id, "finding_ids": finding_ids, "allowed_fact_ids": fact_ids, "scope": req.scope}
    job_id, created = tasks.enqueue(
        conn,
        project_id=project_id,
        kind="revision",
        purpose="business",
        snapshot_id=req.snapshot_id,
        idempotency_key=f"{actor.member_id}:{idempotency_key}:{sha256_hex(canonical_json(payload))}",
        input_json=payload,
        input_sha256=sha256_hex(canonical_json({**payload, "snapshot_sha256": snapshot["sha256"]})),
    )
    if created:
        audit.record(
            conn,
            actor_id=actor.member_id,
            project_id=project_id,
            action="revision.propose",
            object_kind="task",
            object_id=job_id,
            request_id=request_id,
            details=payload,
        )
    return tasks.get_task(conn, actor, job_id)


_SQL = """SELECT r.*, a.sha256 AS a_sha, a.media_type AS a_type, a.byte_size AS a_size, a.contract_version AS a_cv,
       (SELECT decision FROM reviews v WHERE v.object_kind='revision' AND v.object_id=r.id ORDER BY reviewed_at DESC, id DESC LIMIT 1) AS decision
       FROM revisions r JOIN artifacts a ON a.id=r.diff_artifact_id """


def _revision(conn: Connection, row: db.Row) -> Revision:
    if row["decision"] == "confirm":
        status = "adopted"
    elif row["decision"] == "reject":
        status = "rejected"
    else:
        status = "proposed" if _latest_version(conn, row["project_id"], row["base_version_id"]) else "stale"
    reviews = db.all_(
        conn, "SELECT id FROM reviews WHERE object_kind='revision' AND object_id=:i ORDER BY reviewed_at, id", {"i": row["id"]}
    )
    return Revision(
        revision_id=row["id"],
        project_id=row["project_id"],
        base_version_id=row["base_version_id"],
        finding_ids=row["finding_ids_json"],
        allowed_fact_ids=row["allowed_fact_ids_json"],
        status=status,
        target_version_id=row["target_version_id"],
        diff_artifact=ArtifactRef(
            artifact_id=row["diff_artifact_id"],
            sha256=row["a_sha"],
            media_type=row["a_type"],
            byte_size=row["a_size"],
            contract_version=row["a_cv"],
        ),
        review_ids=[r["id"] for r in reviews],
    )


def list_revisions(conn: Connection, actor: Actor, project_id: str) -> list[Revision]:
    require_project(conn, actor, project_id)
    rows = db.all_(conn, _SQL + "WHERE r.project_id=:p ORDER BY r.created_at DESC, r.id DESC", {"p": project_id})
    return [_revision(conn, r) for r in rows]


def get_diff(conn: Connection, store: ObjectStore, actor: Actor, revision_id: str) -> dict[str, Any]:
    """改稿建议的差异正文（产物 JSON）：逐条的原文、替换文、依据，以及被丢弃的候选与原因。"""
    row = db.one(conn, _SQL + "WHERE r.id=:i", {"i": revision_id})
    if row is None:
        raise NotFound("revision_not_found")
    require_project(conn, actor, row["project_id"])
    key = db.scalar(conn, "SELECT object_key FROM artifacts WHERE id=:a", {"a": row["diff_artifact_id"]})
    diff: dict[str, Any] = json.loads(store.get(key))
    return diff


def _load_for_review(conn: Connection, actor: Actor, revision_id: str, base_version_id: str) -> db.Row:
    row = db.one(conn, _SQL + "WHERE r.id=:i FOR UPDATE OF r", {"i": revision_id})
    if row is None:
        raise NotFound("revision_not_found")
    require_project(conn, actor, row["project_id"])
    if row["decision"] is not None:
        raise Conflict("revision_already_reviewed", "该建议已处理", status="adopted" if row["decision"] == "confirm" else "rejected")
    if base_version_id != row["base_version_id"] or not _latest_version(conn, row["project_id"], row["base_version_id"]):
        raise Conflict("base_version_stale", "正文已有更新版本，这份建议已过期", base_version_id=row["base_version_id"])
    return row


def _record(conn: Connection, actor: Actor, row: db.Row, decision: str, reason: str, request_id: str) -> str:
    review_id = new_id("rev")
    db.run(
        conn,
        """INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
                    VALUES (:i,:p,:k,:o,:v,:d,:r,:a,:now)""",
        {
            "i": review_id,
            "p": row["project_id"],
            "k": REVISION_KIND,
            "o": row["id"],
            "v": row["base_version_id"],
            "d": decision,
            "r": reason,
            "a": actor.member_id,
            "now": utcnow(),
        },
    )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=row["project_id"],
        action=f"revision.{decision}",
        object_kind="revision",
        object_id=row["id"],
        request_id=request_id,
        details={"base_version_id": row["base_version_id"]},
    )
    return review_id


def adopt(conn: Connection, store: ObjectStore, actor: Actor, revision_id: str, req: AdoptRequest, request_id: str) -> Revision:
    if req.edited_diff_artifact_id is not None:
        raise Unprocessable("edited_diff_unsupported", "暂不支持提交人工编辑后的差异；请直接修改正文后上传新版本")
    row = _load_for_review(conn, actor, revision_id, req.base_version_id)
    diff: dict[str, Any] = json.loads(
        store.get(db.scalar(conn, "SELECT object_key FROM artifacts WHERE id=:a", {"a": row["diff_artifact_id"]}))
    )
    if not diff.get("edits"):
        raise Conflict("revision_empty", "这份建议没有任何通过校验的修改（候选均被丢弃），无可采纳；请驳回，或调整范围后重新生成建议")
    review_id = _record(conn, actor, row, "confirm", "采纳改稿建议", request_id)
    db.run(
        conn,
        """UPDATE finding_states SET state='revision_pending', revision=revision+1, last_review_id=:r
                    WHERE finding_id = ANY(:ids) AND state='confirmed'""",
        {"r": review_id, "ids": row["finding_ids_json"]},
    )
    return _revision(conn, db.one(conn, _SQL + "WHERE r.id=:i", {"i": revision_id}) or row)


def reject(conn: Connection, actor: Actor, revision_id: str, req: RejectRevisionRequest, request_id: str) -> Revision:
    row = _load_for_review(conn, actor, revision_id, req.base_version_id)
    _record(conn, actor, row, "reject", req.reason, request_id)
    return _revision(conn, db.one(conn, _SQL + "WHERE r.id=:i", {"i": revision_id}) or row)
