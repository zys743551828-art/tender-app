"""实际提交（Submission）与结果（Outcome）。

两者都追加保存：更正和官方核实都是写一条新记录并用 ``supersedes`` 指回旧记录，旧记录永远可查。
成绩只做口径与量尺校验，不推断、不补全：缺分项就保持缺失，不反推官方分项。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor, require_project
from bidwb.errors import Conflict, NotFound, Unprocessable
from bidwb.schemas import ArtifactRef, Outcome, OutcomeRequest, OutcomeVerifyRequest, Submission, SubmissionRequest
from bidwb.services import audit, current_materials, files, projects, rules
from bidwb.services.findings import OPEN_STATES
from bidwb.util import new_id, utcnow


def _artifact_ref(conn: Connection, artifact_id: str | None) -> ArtifactRef | None:
    if artifact_id is None:
        return None
    row = db.one(conn, "SELECT id,sha256,media_type,byte_size,contract_version FROM artifacts WHERE id=:i", {"i": artifact_id})
    if row is None:
        return None
    return ArtifactRef(
        artifact_id=row["id"],
        sha256=row["sha256"],
        media_type=row["media_type"],
        byte_size=row["byte_size"],
        contract_version=row["contract_version"],
    )


# ------------------------------------------------------------------ 提交


def _submission(conn: Connection, row: db.Row) -> Submission:
    return Submission(
        submission_id=row["id"],
        project_id=row["project_id"],
        body_version_id=row["body_version_id"],
        snapshot_id=row["snapshot_id"],
        submitted_at=row["submitted_at"],
        confirmation_review_id=row["confirmation_review_id"],
        receipt_artifact=_artifact_ref(conn, row["receipt_artifact_id"]),
        supersedes=row["supersedes"],
    )


def _require_snapshot_inputs_current(conn: Connection, project_id: str, snapshot_id: str) -> None:
    """快照所依据的规则包、事实集和资料必须仍是当前的：之后有变化，诊断结论就没有反映这些变化。"""
    snap = db.one(
        conn,
        "SELECT rule_set_id, fact_set_id FROM input_snapshots WHERE id=:s AND project_id=:p",
        {"s": snapshot_id, "p": project_id},
    )
    if snap is None:
        raise NotFound("snapshot_not_found")
    newest_rules = rules.latest_package(conn, project_id)
    if newest_rules is not None and newest_rules["id"] != snap["rule_set_id"]:
        raise Conflict("snapshot_stale", "规则集在这一轮诊断之后有更新，请重新诊断后再登记提交", rule_set_id=newest_rules["id"])
    newest_facts = db.one(conn, "SELECT id FROM fact_sets WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    if newest_facts is not None and newest_facts["id"] != snap["fact_set_id"]:
        raise Conflict("snapshot_stale", "事实库在这一轮诊断之后有更新，请重新诊断后再登记提交", fact_set_id=newest_facts["id"])
    included = {
        r["file_version_id"] for r in db.all_(conn, "SELECT file_version_id FROM snapshot_files WHERE snapshot_id=:s", {"s": snapshot_id})
    }
    body = current_materials.active_body(conn, project_id)
    heads = [r for r in current_materials.heads(conn, project_id) if r["role"] in {"tender", "supplement"} or r["id"] == body]
    missing = [h["id"] for h in heads if h["id"] not in included]
    if missing:
        raise Conflict("snapshot_stale", "资料在这一轮诊断之后有新版本，请重新诊断后再登记提交", version_ids=missing)


def _require_submittable_snapshot(conn: Connection, project_id: str, snapshot_id: str) -> None:
    """登记提交的闸门：快照是项目最新的、已完整诊断过、且没有未处理的关键问题。"""
    newest = db.one(conn, "SELECT id FROM input_snapshots WHERE project_id=:p ORDER BY as_of DESC, id DESC LIMIT 1", {"p": project_id})
    if newest is not None and newest["id"] != snapshot_id:
        raise Conflict(
            "snapshot_not_latest", "该快照已被更新的快照取代，请基于最新快照重新诊断并确认后再登记提交", snapshot_id=newest["id"]
        )
    _require_snapshot_inputs_current(conn, project_id, snapshot_id)
    runs = db.all_(
        conn,
        "SELECT coverage_json->>'status' AS coverage FROM jobs WHERE project_id=:p AND snapshot_id=:s AND kind='diagnosis' AND state='succeeded'",
        {"p": project_id, "s": snapshot_id},
    )
    if not runs:
        raise Conflict("snapshot_not_diagnosed", "该快照还没有成功的诊断，不能登记提交；请先完成诊断并处理问题")
    if not any(r["coverage"] == "complete" for r in runs):
        raise Conflict("diagnosis_incomplete", "该快照的诊断覆盖不完整（有规则未能完成检查），请重新诊断后再登记提交")
    pending = db.scalar(
        conn,
        "SELECT rule_set_id FROM input_snapshots WHERE id=:s AND project_id=:p",
        {"s": snapshot_id, "p": project_id},
    )
    unconfirmed = rules.unconfirmed_qualification_count(conn, project_id, pending)
    if unconfirmed and not projects.settings_of(conn, project_id).accept_rules_as_written:
        raise Conflict(
            "qualification_rules_unconfirmed",
            f"还有 {unconfirmed} 条废标／否决／强制类规则没有人工确认，这些规则决定能否入围，确认后才能登记提交",
            count=unconfirmed,
        )
    critical = db.all_(
        conn,
        """SELECT f.id FROM findings f JOIN finding_states s ON s.finding_id=f.id
           WHERE f.project_id=:p AND f.snapshot_id=:sn AND (f.severity='critical' OR f.category IN ('disqualification','response'))
             AND s.state = ANY(:open) ORDER BY f.id""",
        {"p": project_id, "sn": snapshot_id, "open": list(OPEN_STATES)},
    )
    if critical:
        raise Conflict(
            "critical_findings_open",
            f"还有 {len(critical)} 个关键或废标／响应类问题未处理完（待复核、已确认待修改、暂缓或待复检），处理完成后才能登记提交",
            finding_ids=[c["id"] for c in critical],
        )


def freeze_submission(conn: Connection, actor: Actor, project_id: str, req: SubmissionRequest, request_id: str) -> Submission:
    require_project(conn, actor, project_id)
    if req.submitted_at.tzinfo is None or req.submitted_at.utcoffset() is None:
        raise Unprocessable("submitted_at_naive", "提交时间必须带时区（例如 2026-10-01T08:00:00+08:00）")
    if req.submitted_at > utcnow():
        raise Unprocessable("submitted_at_in_future", "提交时间不能晚于当前时间；登记的是已经发生的提交")
    if db.one(conn, "SELECT 1 AS x FROM file_versions WHERE id=:v AND project_id=:p", {"v": req.body_version_id, "p": project_id}) is None:
        raise NotFound("file_not_found")
    snapshot = db.one(
        conn, "SELECT body_version_id FROM input_snapshots WHERE id=:s AND project_id=:p", {"s": req.snapshot_id, "p": project_id}
    )
    if snapshot is None:
        raise NotFound("snapshot_not_found")
    if snapshot["body_version_id"] != req.body_version_id:
        raise Unprocessable("body_version_mismatch", "提交的正文版本必须是所选快照里的正文版本")
    if not files.is_latest_version(conn, project_id, req.body_version_id):
        raise Conflict("body_version_stale", "该正文已有更新版本，请基于最新版本重新分析并确认后再登记提交")
    _require_submittable_snapshot(conn, project_id, req.snapshot_id)
    if req.receipt_artifact_id is not None:
        if _artifact_ref(conn, req.receipt_artifact_id) is None:
            raise NotFound("artifact_not_found")
        in_project = db.one(
            conn,
            """SELECT 1 AS x FROM file_versions fv JOIN artifacts a ON a.id=fv.artifact_id
               WHERE fv.project_id=:p AND fv.artifact_id=:a AND a.status='committed'""",
            {"p": project_id, "a": req.receipt_artifact_id},
        )
        if in_project is None:
            raise Unprocessable("receipt_artifact_invalid", "回执必须是本项目已上传并通过核验的文件")
    previous = db.one(conn, "SELECT id FROM submissions WHERE project_id=:p ORDER BY submitted_at DESC, id DESC LIMIT 1", {"p": project_id})
    submission_id = new_id("sub")
    # 登记提交本身就是登记人对“提交这一版”的确认：同事务写一条确认记录，随提交一并留存。
    review_id = new_id("rev")
    db.run(
        conn,
        """INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
           VALUES (:i,:p,'submission',:o,'1','confirm',:why,:a,:now)""",
        {"i": review_id, "p": project_id, "o": submission_id, "why": "登记实际提交", "a": actor.member_id, "now": utcnow()},
    )
    db.run(
        conn,
        """INSERT INTO submissions(id,project_id,body_version_id,snapshot_id,submitted_at,confirmation_review_id,receipt_artifact_id,supersedes)
           VALUES (:i,:p,:b,:s,:at,:r,:a,:sup)""",
        {
            "i": submission_id,
            "p": project_id,
            "b": req.body_version_id,
            "s": req.snapshot_id,
            "at": req.submitted_at,
            "r": review_id,
            "a": req.receipt_artifact_id,
            "sup": previous["id"] if previous else None,
        },
    )
    db.run(conn, "UPDATE projects SET state='submitted', revision=revision+1 WHERE id=:p AND state<>'submitted'", {"p": project_id})
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="submission.freeze",
        object_kind="submission",
        object_id=submission_id,
        request_id=request_id,
    )
    row = db.one(conn, "SELECT * FROM submissions WHERE id=:i", {"i": submission_id})
    assert row is not None
    return _submission(conn, row)


def list_submissions(conn: Connection, actor: Actor, project_id: str) -> list[Submission]:
    require_project(conn, actor, project_id)
    rows = db.all_(conn, "SELECT * FROM submissions WHERE project_id=:p ORDER BY submitted_at DESC, id DESC", {"p": project_id})
    return [_submission(conn, r) for r in rows]


# ------------------------------------------------------------------ 结果
def _outcome(conn: Connection, row: db.Row) -> Outcome:
    def text(value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")

    return Outcome(
        outcome_id=row["id"],
        project_id=row["project_id"],
        submission_id=row["submission_id"],
        source_kind=row["source_kind"],
        verification_status=row["verification_status"],
        target=row["target"],
        value=text(row["value_decimal"]),
        maximum=text(row["maximum_decimal"]),
        aggregation=row["aggregation"],
        stage_result=row["stage_result"],
        source_artifact=_artifact_ref(conn, row["source_artifact_id"]),
        source_page=row["source_page"],
        published_at=row["published_at"],
        known_at=row["known_at"],
        verified_by=row["verified_by"],
        supersedes=row["supersedes"],
    )


def _check_scale(req: OutcomeRequest) -> None:
    if req.target == "no_score":
        if req.value is not None or req.maximum is not None:
            raise Unprocessable("score_scale_invalid", "“无分数”结果不能带分值或满分")
        return
    if req.value is None or req.maximum is None:
        raise Unprocessable("score_scale_invalid", "有分数的结果必须同时给出分值与满分；未知请改用“无分数”并说明")
    value, maximum = Decimal(req.value), Decimal(req.maximum)
    if maximum <= 0 or value > maximum:
        raise Unprocessable("score_scale_invalid", "满分必须大于 0，且分值不得超过满分，系统不会截断或改写分值")


def record_outcome(conn: Connection, actor: Actor, project_id: str, req: OutcomeRequest, request_id: str) -> Outcome:
    require_project(conn, actor, project_id)
    _check_scale(req)
    if db.one(conn, "SELECT 1 AS x FROM submissions WHERE id=:s AND project_id=:p", {"s": req.submission_id, "p": project_id}) is None:
        raise NotFound("submission_not_found")
    if req.supersedes is not None:
        if (
            db.one(
                conn,
                "SELECT 1 AS x FROM outcomes WHERE id=:o AND project_id=:p AND submission_id=:s",
                {"o": req.supersedes, "p": project_id, "s": req.submission_id},
            )
            is None
        ):
            raise NotFound("outcome_not_found")
        if db.one(conn, "SELECT 1 AS x FROM outcomes WHERE supersedes=:o", {"o": req.supersedes}) is not None:
            raise Conflict("outcome_superseded", "被取代的记录已经被更新的记录取代，请取代最新的那条")
    if req.source_artifact_id is not None:
        _require_official_artifact(conn, project_id, req.source_artifact_id)
    outcome_id = new_id("out")
    db.run(
        conn,
        """INSERT INTO outcomes(id,project_id,submission_id,source_kind,verification_status,target,value_decimal,maximum_decimal,aggregation,
                                stage_result,source_artifact_id,source_page,published_at,known_at,supersedes)
           VALUES (:i,:p,:s,:k,'pending',:t,CAST(:v AS numeric),CAST(:m AS numeric),:agg,:stage,:art,:page,:pub,:now,:sup)""",
        {
            "i": outcome_id,
            "p": project_id,
            "s": req.submission_id,
            "k": req.source_kind,
            "t": req.target,
            "v": req.value,
            "m": req.maximum,
            "agg": req.aggregation,
            "stage": req.stage_result,
            "art": req.source_artifact_id,
            "page": req.source_page,
            "pub": req.published_at,
            "now": utcnow(),
            "sup": req.supersedes,
        },
    )
    _record_source_note(conn, project_id, outcome_id, actor, req.source_description)
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="outcome.record",
        object_kind="outcome",
        object_id=outcome_id,
        request_id=request_id,
        details={"source_kind": req.source_kind, "target": req.target},
    )
    row = db.one(conn, "SELECT * FROM outcomes WHERE id=:i", {"i": outcome_id})
    assert row is not None
    return _outcome(conn, row)


def _record_source_note(conn: Connection, project_id: str, outcome_id: str, actor: Actor, description: str) -> None:
    """结果表没有“出处说明”列，出处说明作为一条审核记录保存，与结果同事务。"""
    db.run(
        conn,
        """INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
           VALUES (:i,:p,'outcome',:o,'1','defer',:r,:a,:now)""",
        {"i": new_id("rev"), "p": project_id, "o": outcome_id, "r": description, "a": actor.member_id, "now": utcnow()},
    )


def _require_official_artifact(conn: Connection, project_id: str, artifact_id: str) -> None:
    ok = db.one(
        conn,
        """SELECT 1 AS x FROM file_versions fv JOIN files f ON f.id=fv.file_id JOIN artifacts a ON a.id=fv.artifact_id
           WHERE fv.project_id=:p AND fv.artifact_id=:a AND f.role='official_result' AND a.status='committed'""",
        {"p": project_id, "a": artifact_id},
    )
    if ok is None:
        raise Unprocessable("source_artifact_invalid", "来源必须是本项目已上传的“官方成绩”资料")


def verify_outcome(conn: Connection, actor: Actor, outcome_id: str, req: OutcomeVerifyRequest, request_id: str) -> Outcome:
    """官方核实：写一条 verified 的新结果并覆盖旧记录；只有官方来源且有原件与页码的结果才能核实。"""
    old = db.one(conn, "SELECT * FROM outcomes WHERE id=:o", {"o": outcome_id})
    if old is None:
        raise NotFound("outcome_not_found")
    project_id = old["project_id"]
    require_project(conn, actor, project_id)
    if old["source_kind"] != "official":
        raise Conflict("outcome_not_official", "只有官方来源的结果可以核实；用户报送的结果请先补充官方原件并重新登记")
    if old["verification_status"] == "verified":
        raise Conflict("outcome_already_verified", "该结果已核实")
    if db.one(conn, "SELECT 1 AS x FROM outcomes WHERE supersedes=:o", {"o": outcome_id}):
        raise Conflict("outcome_superseded", "该结果已被更新的记录取代")
    _require_official_artifact(conn, project_id, req.source_artifact_id)
    new_outcome_id = new_id("out")
    db.run(
        conn,
        """INSERT INTO outcomes(id,project_id,submission_id,source_kind,verification_status,target,value_decimal,maximum_decimal,aggregation,
                                stage_result,source_artifact_id,source_page,published_at,known_at,verified_by,supersedes)
           VALUES (:i,:p,:s,'official','verified',:t,:v,:m,:agg,:stage,:art,:page,:pub,:now,:by,:sup)""",
        {
            "i": new_outcome_id,
            "p": project_id,
            "s": old["submission_id"],
            "t": old["target"],
            "v": old["value_decimal"],
            "m": old["maximum_decimal"],
            "agg": req.aggregation,
            "stage": old["stage_result"],
            "art": req.source_artifact_id,
            "page": req.source_page,
            "pub": old["published_at"],
            "now": utcnow(),
            "by": actor.member_id,
            "sup": outcome_id,
        },
    )
    db.run(
        conn,
        """INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
           VALUES (:i,:p,'outcome',:o,'1','confirm',:r,:a,:now)""",
        {"i": new_id("rev"), "p": project_id, "o": new_outcome_id, "r": req.reason, "a": actor.member_id, "now": utcnow()},
    )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="outcome.verify",
        object_kind="outcome",
        object_id=new_outcome_id,
        request_id=request_id,
        details={"supersedes": outcome_id},
    )
    row = db.one(conn, "SELECT * FROM outcomes WHERE id=:i", {"i": new_outcome_id})
    assert row is not None
    return _outcome(conn, row)


def list_outcomes(conn: Connection, actor: Actor, project_id: str) -> list[Outcome]:
    require_project(conn, actor, project_id)
    rows = db.all_(conn, "SELECT * FROM outcomes WHERE project_id=:p ORDER BY known_at DESC, id DESC", {"p": project_id})
    return [_outcome(conn, r) for r in rows]
