"""诊断问题（Finding）的查询与人工复核。

Finding 本身追加保存；处理状态在 ``finding_states``（可变指针，带 revision 乐观锁）。每次复核先追加一行 ``reviews``，
再推进指针，二者同事务，所以任何一个状态都能回溯到是谁、依据什么、基于哪个版本做出的决定。
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor, require_project
from bidwb.errors import Conflict, NotFound, PreconditionFailed, Unprocessable
from bidwb.schemas import Finding, Review, ReviewRequest
from bidwb.services import audit, evidence
from bidwb.util import new_id, utcnow

FINDING_KIND = "finding"

# 状态 → 决定 → 新状态。revision_pending / recheck_pending 由修改与重查流程推进，人工只处理下面这些入口。
_TRANSITIONS: Mapping[str, Mapping[str, str]] = {
    "candidate": {"confirm": "confirmed", "reject": "rejected", "defer": "deferred", "request_facts": "deferred"},
    "deferred": {"confirm": "confirmed", "reject": "rejected", "reopen": "candidate"},
    "confirmed": {"resolve": "resolved"},
    "recheck_pending": {"resolve": "resolved", "confirm": "confirmed"},
    "revision_pending": {"reject": "rejected", "resolve": "resolved"},  # resolve：改稿采纳后，新正文已落实，人工关闭（理由必填）
    "rejected": {"reopen": "candidate"},
    "resolved": {"reopen": "candidate"},  # 误关或新正文又出现问题：回到待处理重新走复核（理由必填）
}
OPEN_STATES = ("candidate", "confirmed", "deferred", "revision_pending", "recheck_pending")

SELECT_SQL = """SELECT f.id,f.project_id,f.snapshot_id,f.run_id,f.rule_id,f.source,f.category,f.rule_basis,f.created_at,f.nature,f.impact,f.severity,f.statement,f.evidence_ids_json,f.required_facts_json,
       s.state,s.revision FROM findings f JOIN finding_states s ON s.finding_id=f.id """


def finding_from_row(conn: Connection, row: db.Row) -> Finding:
    return Finding(
        finding_id=row["id"],
        project_id=row["project_id"],
        snapshot_id=row["snapshot_id"],
        run_id=row["run_id"],
        rule_id=row["rule_id"],
        source=row["source"],
        category=row["category"],
        rule_basis=row["rule_basis"],
        nature=row["nature"],
        impact=row["impact"],
        severity=row["severity"],
        statement=row["statement"],
        evidence=evidence.evidence_for_ids(conn, row["project_id"], row["evidence_ids_json"]),
        required_facts=list(row["required_facts_json"]),
        status=row["state"],
        revision=row["revision"],
    )


def list_findings(
    conn: Connection,
    actor: Actor,
    project_id: str,
    *,
    snapshot_id: str | None = None,
    status: str | None = None,
    category: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> tuple[list[Finding], str | None]:
    """键集游标分页（默认 25、最大 100）。排序固定为（严重度档位, 创建时间, ID）。

    游标编码的是最后一条的排序键本身，而不是某一行的 ID：筛选条件变了、或那一行已不在结果里（例如状态变了）
    游标依然有效，只是从该排序位置之后继续。
    """
    require_project(conn, actor, project_id)
    limit = max(1, min(limit, 100))
    after = _decode_cursor(cursor) if cursor else None
    rows = db.all_(
        conn,
        SELECT_SQL
        + f"""WHERE f.project_id=:p AND (CAST(:snap AS text) IS NULL OR f.snapshot_id=:snap) AND (CAST(:st AS text) IS NULL OR s.state=:st) AND (CAST(:cat AS text) IS NULL OR f.category=:cat)
                  AND (CAST(:cr AS integer) IS NULL OR ({_RANK_SQL}, f.created_at, f.id) > (CAST(:cr AS integer), CAST(:cc AS timestamptz), :ci))
                  ORDER BY {_RANK_SQL}, f.created_at, f.id LIMIT :lim""",
        {
            "p": project_id,
            "snap": snapshot_id,
            "st": status,
            "cat": category,
            "cr": after[0] if after else None,
            "cc": after[1] if after else None,
            "ci": after[2] if after else None,
            "lim": limit + 1,
        },
    )
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > limit else None
    return [finding_from_row(conn, r) for r in page], next_cursor


_RANK_SQL = "CASE f.severity WHEN 'critical' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END"
_RANK = {"critical": 0, "normal": 1}


def _encode_cursor(row: db.Row) -> str:
    created: datetime = row["created_at"]
    raw = json.dumps([_RANK.get(row["severity"], 2), created.isoformat(), row["id"]])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[int, str, str]:
    try:
        rank, created, finding_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        datetime.fromisoformat(created)
        if not isinstance(rank, int) or not isinstance(finding_id, str):
            raise ValueError
    except (ValueError, TypeError, binascii.Error):
        raise Unprocessable("invalid_cursor", "分页游标无效") from None
    return rank, created, finding_id


def get_finding(conn: Connection, actor: Actor, finding_id: str) -> Finding:
    row = db.one(conn, SELECT_SQL + "WHERE f.id=:i", {"i": finding_id})
    if row is None:
        raise NotFound("finding_not_found")
    require_project(conn, actor, row["project_id"])
    return finding_from_row(conn, row)


def review_finding(conn: Connection, actor: Actor, finding_id: str, req: ReviewRequest, request_id: str) -> Review:
    row = db.one(conn, SELECT_SQL + "WHERE f.id=:i FOR UPDATE OF s", {"i": finding_id})
    if row is None:
        raise NotFound("finding_not_found")
    project_id = row["project_id"]
    require_project(conn, actor, project_id)
    newest = db.one(conn, "SELECT id FROM input_snapshots WHERE project_id=:p ORDER BY as_of DESC, id DESC LIMIT 1", {"p": project_id})
    if newest is not None and newest["id"] != row["snapshot_id"]:
        raise Conflict("snapshot_superseded", "这条问题属于已被更新轮次取代的诊断，只能查看；请在最新一轮里处理", snapshot_id=newest["id"])
    if req.object_version != str(row["revision"]):
        raise PreconditionFailed("stale_version", "该问题已被他人处理，请刷新后重新复核", current_version=str(row["revision"]))
    target = _TRANSITIONS.get(row["state"], {}).get(req.decision)
    if target is None:
        raise Conflict("transition_not_allowed", f"状态“{row['state']}”下不能执行“{req.decision}”", state=row["state"])
    review_id = new_id("rev")
    now = utcnow()
    db.run(
        conn,
        """INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
           VALUES (:i,:p,:k,:o,:v,:d,:r,:a,:now)""",
        {
            "i": review_id,
            "p": project_id,
            "k": FINDING_KIND,
            "o": finding_id,
            "v": req.object_version,
            "d": req.decision,
            "r": req.reason,
            "a": actor.member_id,
            "now": now,
        },
    )
    db.run(
        conn,
        "UPDATE finding_states SET state=:s, revision=revision+1, last_review_id=:r WHERE finding_id=:f",
        {"s": target, "r": review_id, "f": finding_id},
    )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="finding.review",
        object_kind="finding",
        object_id=finding_id,
        request_id=request_id,
        details={"decision": req.decision, "from": row["state"], "to": target},
    )
    reconcile_project_state(conn, project_id)
    return Review(
        review_id=review_id,
        project_id=project_id,
        object_id=finding_id,
        object_version=req.object_version,
        decision=req.decision,
        reason=req.reason,
        actor_id=actor.member_id,
        reviewed_at=now,
    )


def reconcile_project_state(conn: Connection, project_id: str) -> None:
    """还有未处理问题 → ``issues_open``；全部处理完且诊断覆盖完整 → ``ready_to_submit``（可以登记提交）。

    只数“最近一个做过诊断的快照”上的问题：更新的快照若还没诊断，不能让项目凭“没有问题”进入待交付；
    旧快照上遗留的未处理问题属于已被取代的输入，不再阻塞项目。该快照最近一次成功诊断的覆盖度不是 complete
    （有规则没检查成功，或一条都没检查）时，没有问题也不是“检查通过”，项目不得进入 ``ready_to_submit``，
    保持 ``issues_open`` 并由报告提示重新评审。问题复核后与诊断任务提交后（worker 的 finalize）都要调用。
    """
    latest = db.one(
        conn,
        """SELECT s.id,
                  (SELECT j.coverage_json->>'status' FROM jobs j WHERE j.snapshot_id=s.id AND j.kind='diagnosis' AND j.state='succeeded'
                   ORDER BY j.finished_at DESC, j.id DESC LIMIT 1) AS coverage
           FROM input_snapshots s
           WHERE s.project_id=:p AND EXISTS (SELECT 1 FROM jobs d WHERE d.snapshot_id=s.id AND d.kind='diagnosis' AND d.state='succeeded')
           ORDER BY s.as_of DESC, s.id DESC LIMIT 1""",
        {"p": project_id},
    )
    if latest is None:
        return
    open_count = db.scalar(
        conn,
        "SELECT count(*) FROM finding_states s JOIN findings f ON f.id=s.finding_id WHERE f.project_id=:p AND f.snapshot_id=:s AND s.state = ANY(:open)",
        {"p": project_id, "s": latest["id"], "open": list(OPEN_STATES)},
    )
    target = "ready_to_submit" if not open_count and latest["coverage"] == "complete" else "issues_open"
    db.run(
        conn,
        "UPDATE projects SET state=:t, revision=revision+1 WHERE id=:p AND state IN ('materials_pending','ready_to_analyze','analyzing','analysis_failed','issues_open','ready_to_submit') AND state<>:t",
        {"t": target, "p": project_id},
    )
