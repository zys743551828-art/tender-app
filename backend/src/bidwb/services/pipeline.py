"""自动评审流水线：资料齐了就依次解析 → 提取规则 → 冻结输入 → 核对与预测，不需要人逐步点。

``advance`` 是幂等的状态推进：每次调用先读出项目当前的资料、规则、事实与各任务状态，再只做“下一步”
（入队一个任务或冻结一次输入）。上传完成、任一任务成功、规则或事实变化时调用；回收器定期兜底。
入队与冻结都带确定的幂等键，重复调用不会产生重复任务或快照。

人只在两处介入：确认关键规则（可以晚一点，报告会标明“依据未确认”）和处理报告里的问题。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import Connection

from bidwb import db, source_effectivity, tasks, term_conflicts
from bidwb.access import Actor, require_project
from bidwb.errors import DomainError
from bidwb.logs import get_logger
from bidwb.schemas import PipelineStatus, PipelineStep, SnapshotRequest
from bidwb.services import action_context, audit, current_materials, snapshots
from bidwb.services import findings as findings_service
from bidwb.services import projects as projects_service
from bidwb.services import rules as rules_service
from bidwb.storage import ObjectStore
from bidwb.util import new_id, sha256_hex

log = get_logger(__name__)
_ACTIVE_JOB = frozenset({"queued", "running", "waiting_input", "cancel_requested"})
DRIVING_KINDS = frozenset({"parse", "rules", "diagnosis", "prediction"})  # 结束后需要推进下一步的任务种类
_PIPELINE_STATES = ("materials_pending", "ready_to_analyze", "analyzing", "analysis_failed", "issues_open", "ready_to_submit")
StepState = Literal["waiting", "running", "done", "failed"]


@dataclass
class _Plan:
    """项目当前输入与任务的快照；``advance`` 与 ``status`` 都基于它。"""

    missing: list[str] = field(default_factory=list)
    tender_ids: list[str] = field(default_factory=list)
    body_id: str | None = None
    parse: StepState = "waiting"
    parse_message: str | None = None
    package_id: str | None = None
    rules_job: db.Row | None = None
    fact_set_id: str | None = None
    snapshot_id: str | None = None
    held_snapshot_id: str | None = None  # 资料没变、只有规则或事实更正时沿用的上一轮：由人决定何时重新评审
    diagnosis_job: db.Row | None = None
    prediction_job: db.Row | None = None


def _job_state(job: db.Row | None) -> StepState:
    if job is None:
        return "waiting"
    if job["state"] == "succeeded":
        return "done"
    return "running" if job["state"] in _ACTIVE_JOB else "failed"


def _latest_job(
    conn: Connection, project_id: str, kind: str, *, snapshot_id: str | None = None, input_ids: list[str] | None = None
) -> db.Row | None:
    if snapshot_id is not None:
        return db.one(
            conn,
            "SELECT id,state,error_code,coverage_json->>'status' AS coverage FROM jobs WHERE project_id=:p AND kind=:k AND snapshot_id=:s ORDER BY created_at DESC, id DESC LIMIT 1",
            {"p": project_id, "k": kind, "s": snapshot_id},
        )
    return db.one(
        conn,
        """SELECT id,state,error_code,coverage_json->>'status' AS coverage FROM jobs WHERE project_id=:p AND kind=:k
           AND input_json->'file_version_ids' = CAST(:ids AS jsonb) ORDER BY created_at DESC, id DESC LIMIT 1""",
        {"p": project_id, "k": kind, "ids": json.dumps(input_ids or [])},
    )


def _current_versions(conn: Connection, project_id: str) -> tuple[list[db.Row], db.Row | None]:
    """招标文件与补遗各取最新版本；正文取最近上传的正文文件的最新版本。"""
    latest = current_materials.heads(conn, project_id)
    tender = [v for v in latest if v["role"] in snapshots.TENDER_ROLES]
    bodies = sorted((v for v in latest if v["role"] == "body"), key=lambda v: (v["source_obtained_at"], v["source_id"]), reverse=True)
    return tender, (bodies[0] if bodies else None)


def _parse_state(conn: Connection, project_id: str, needed: list[db.Row]) -> tuple[StepState, str | None]:
    """所需资料的解析进度：任一份解析失败（含解析任务本身失败）→ failed；仍有未解析的 → running。"""
    if db.scalar(
        conn,
        "SELECT count(*) FROM word_conversions WHERE project_id=:p AND source_version_id=ANY(:v)",
        {"p": project_id, "v": [v["id"] for v in needed]},
    ):
        return "failed", "请在对应 Word 原稿处核对并采用生成的 PDF，或只补交此稿的 PDF"
    dead = {
        r["version_id"]
        for r in db.all_(
            conn,
            """SELECT DISTINCT input_json->>'file_version_id' AS version_id FROM jobs
               WHERE project_id=:p AND kind='parse' AND state IN ('failed','cancelled') AND input_json->>'file_version_id' = ANY(:ids)""",
            {"p": project_id, "ids": [v["id"] for v in needed]},
        )
    }
    failed = [v for v in needed if v["coverage"] == "failed" or (v["coverage"] is None and v["id"] in dead)]
    if failed:
        return "failed", "、".join(f"“{v['original_name']}”" for v in failed) + " 解析失败，请重新上传"
    if any(v["coverage"] is None for v in needed):
        return "running", None
    pending = db.all_(
        conn,
        """SELECT file_version_id FROM (
             SELECT DISTINCT ON (file_version_id) file_version_id,gaps_json FROM parses
             WHERE project_id=:p AND file_version_id = ANY(:v) ORDER BY file_version_id,created_at DESC,id DESC
           ) latest WHERE gaps_json ? 'recognition_verification_required'""",
        {"p": project_id, "v": [v["id"] for v in needed]},
    )
    if pending:
        return "failed", "资料只有待核验的识别结果，请对照原页核验后补交可复制文字的 PDF；不会用未核验文字启动评审"
    return "done", None


def _inspect(conn: Connection, project_id: str) -> _Plan:
    plan = _Plan()
    tender, body = _current_versions(conn, project_id)
    if not any(v["role"] == "tender" for v in tender):
        plan.missing.append("tender")
    if body is None:
        plan.missing.append("body")
    if plan.missing:
        return plan
    assert body is not None
    plan.tender_ids = sorted(v["id"] for v in tender)
    plan.body_id = body["id"]
    plan.parse, plan.parse_message = _parse_state(conn, project_id, [*tender, body])
    if plan.parse != "done":
        return plan
    package = rules_service.latest_package(conn, project_id)
    if package is not None and sorted(package["source_versions_json"]) == plan.tender_ids:
        plan.package_id = package["id"]
    else:
        plan.rules_job = _latest_job(conn, project_id, "rules", input_ids=plan.tender_ids)
        return plan
    facts = db.one(conn, "SELECT id FROM fact_sets WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    plan.fact_set_id = facts["id"] if facts else None
    snap = db.one(
        conn,
        """SELECT s.id FROM input_snapshots s
           WHERE s.project_id=:p AND s.body_version_id=:b AND s.rule_set_id=:r AND s.fact_set_id IS NOT DISTINCT FROM :f
             AND (SELECT array_agg(sf.file_version_id ORDER BY sf.file_version_id) FROM snapshot_files sf WHERE sf.snapshot_id=s.id) = :ids
           ORDER BY s.as_of DESC, s.id DESC LIMIT 1""",
        {"p": project_id, "b": plan.body_id, "r": plan.package_id, "f": plan.fact_set_id, "ids": sorted([*plan.tender_ids, plan.body_id])},
    )
    shown = snap["id"] if snap is not None else None
    if snap is not None:
        plan.snapshot_id = snap["id"]
    else:
        last = last_reviewed(conn, project_id)
        if last is not None and last["body_version_id"] == plan.body_id and set(last["files"]) == {*plan.tender_ids, plan.body_id}:
            plan.held_snapshot_id = shown = last["id"]
    if shown is not None:
        plan.diagnosis_job = _latest_job(conn, project_id, "diagnosis", snapshot_id=shown)
        plan.prediction_job = _latest_job(conn, project_id, "prediction", snapshot_id=shown)
    return plan


def last_reviewed(conn: Connection, project_id: str) -> db.Row | None:
    """最近一个诊断成功的输入快照及其资料版本集合。"""
    return db.one(
        conn,
        """SELECT s.id,s.body_version_id,s.rule_set_id,s.fact_set_id,
                  (SELECT array_agg(sf.file_version_id ORDER BY sf.file_version_id) FROM snapshot_files sf WHERE sf.snapshot_id=s.id) AS files
           FROM input_snapshots s
           WHERE s.project_id=:p AND EXISTS (SELECT 1 FROM jobs d WHERE d.snapshot_id=s.id AND d.kind='diagnosis' AND d.state='succeeded')
           ORDER BY s.as_of DESC, s.id DESC LIMIT 1""",
        {"p": project_id},
    )


def _set_project_state(conn: Connection, project_id: str, state: str) -> None:
    db.run(
        conn,
        "UPDATE projects SET state=:s, revision=revision+1 WHERE id=:p AND state = ANY(:from) AND state<>:s",
        {"s": state, "p": project_id, "from": list(_PIPELINE_STATES)},
    )


def _needs_new_round(plan: _Plan) -> bool:
    """还没有人发起、需要新开的工作：规则未提取且没有提取任务，或输入有变化而本轮尚未冻结。"""
    if plan.missing or plan.parse != "done":
        return False
    if plan.package_id is None:
        return plan.rules_job is None
    return plan.snapshot_id is None and plan.held_snapshot_id is None


def _may_start(conn: Connection, project_id: str, restart: bool) -> bool:
    """能否开新一轮：项目开着“自动开始评审”，或人要求过开始而这次要求还没被一轮冻结用掉。

    要求用一个标记表示（冻结时清除），不比较不同主机的时钟。
    """
    if restart or projects_service.settings_of(conn, project_id).auto_start:
        return True
    return db.scalar(conn, "SELECT analysis_requested_at FROM projects WHERE id=:p", {"p": project_id}) is not None


def _await_inputs(conn: Connection, project_id: str, plan: _Plan, restart: bool) -> bool:
    """资料、解析、规则提取这几个环节还没就绪时处理并返回 True（本次到此为止）。"""
    if plan.missing:
        _set_project_state(conn, project_id, "materials_pending")
        return True
    if plan.parse != "done":
        _set_project_state(conn, project_id, "analysis_failed" if plan.parse == "failed" else "analyzing")
        return True
    if _needs_new_round(plan) and not _may_start(conn, project_id, restart):
        if last_reviewed(conn, project_id) is None:
            _set_project_state(conn, project_id, "ready_to_analyze")  # 资料齐了，等人点“开始评审”
        else:
            settle(conn, project_id)  # 旧报告仍有效，项目状态回到它对应的状态（输入已变则不能是“可登记提交”）
        return True
    if plan.package_id is not None:
        return False
    state = _job_state(plan.rules_job)
    # 已完成却没有对应的规则包：提取期间资料又变了，那次结果作废，需要针对当前资料重新提取
    if plan.rules_job is None or state == "done" or (state == "failed" and restart):
        retry = f":{new_id('try')}" if plan.rules_job is not None else ""
        tasks.enqueue_rules(conn, project_id, plan.tender_ids, f"auto:rules:{sha256_hex(','.join(plan.tender_ids))}{retry}")
        state = "running"
    _set_project_state(conn, project_id, "analysis_failed" if state == "failed" else "analyzing")
    return True


def _snapshot_request(plan: _Plan) -> SnapshotRequest:
    assert plan.body_id is not None
    assert plan.package_id is not None
    return SnapshotRequest(
        body_version_id=plan.body_id,
        rule_set_id=plan.package_id,
        fact_set_id=plan.fact_set_id,
        file_version_ids=[*plan.tender_ids, plan.body_id],
        reference_dataset_id=None,
    )


def _freeze(conn: Connection, store: ObjectStore, project_id: str, plan: _Plan) -> str:
    return snapshots.freeze_inputs(conn, store, None, project_id, _snapshot_request(plan), new_id("req"))


def advance(conn: Connection, store: ObjectStore, project_id: str, *, restart: bool = False) -> None:
    """推进一步；``restart`` 为真时，失败的环节用新的幂等键重新入队，已完成的环节不重做。"""
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})  # 同一项目的推进串行，避免并发重复冻结
    plan = _inspect(conn, project_id)
    if _await_inputs(conn, project_id, plan, restart):
        return
    assert plan.body_id is not None
    if plan.held_snapshot_id is not None and not restart:
        settle(conn, project_id)  # 资料没变，只是规则或事实有更正：由人决定何时重新评审，不自动开新一轮
        return
    if plan.snapshot_id is None:
        try:
            with conn.begin_nested():
                plan.snapshot_id = _freeze(conn, store, project_id, plan)
        except DomainError as exc:  # 输入不满足冻结条件（如资料晚于截止时间）：如实中断，原因在流水线状态里给出
            log.warning("pipeline_freeze_rejected", project_id=project_id, code=exc.code)
            _set_project_state(conn, project_id, "analysis_failed")
            return
        db.run(conn, "UPDATE projects SET analysis_requested_at=NULL WHERE id=:p", {"p": project_id})  # 开始评审的要求已用掉
        plan.diagnosis_job = plan.prediction_job = None  # 新一轮：上一轮（沿用的）任务不算数
    snapshot_id = plan.snapshot_id
    retry = f":{new_id('try')}" if restart else ""
    state = _job_state(plan.diagnosis_job)
    incomplete = state == "done" and plan.diagnosis_job is not None and plan.diagnosis_job["coverage"] != "complete"
    if plan.diagnosis_job is None or (restart and (state == "failed" or incomplete)):
        tasks.enqueue_diagnosis(conn, project_id, snapshot_id, f"auto:diagnosis:{snapshot_id}{retry}")
        state = "running"
    if state != "done":
        _set_project_state(conn, project_id, "analysis_failed" if state == "failed" else "analyzing")
        return
    if plan.prediction_job is None or (_job_state(plan.prediction_job) == "failed" and restart):
        tasks.enqueue(
            conn,
            project_id=project_id,
            kind="prediction",
            purpose="research",
            snapshot_id=snapshot_id,
            idempotency_key=f"auto:prediction:{snapshot_id}{retry if plan.prediction_job else ''}",
            input_json={"snapshot_id": snapshot_id},
            input_sha256=db.scalar(conn, "SELECT sha256 FROM input_snapshots WHERE id=:s", {"s": snapshot_id}),
        )
    settle(conn, project_id)


def settle(conn: Connection, project_id: str) -> None:
    """只对齐项目状态，不入队、不冻结：按最近一轮的问题对账；当前输入已经变了（报告落后）时不能停在“可登记提交”。

    问题复核、规则更正、事实变化、功能开关变化之后都调用。
    """
    findings_service.reconcile_project_state(conn, project_id)
    last = last_reviewed(conn, project_id)
    if last is not None and _stale_reasons(conn, project_id, _inspect(conn, project_id), last):
        db.run(
            conn,
            "UPDATE projects SET state='issues_open', revision=revision+1 WHERE id=:p AND state='ready_to_submit'",
            {"p": project_id},
        )


def advance_active(conn: Connection, store: ObjectStore, limit: int = 50) -> int:
    """回收器的兜底：把仍在“分析中”的项目再推一步（消息或回调丢失时不会卡住）。返回处理的项目数。"""
    rows = db.all_(conn, "SELECT id FROM projects WHERE state='analyzing' ORDER BY id LIMIT :n", {"n": limit})
    for row in rows:
        try:
            with conn.begin_nested():  # 一个项目出错不影响同批其他项目
                advance(conn, store, row["id"])
        except Exception:
            log.warning("pipeline_advance_failed", project_id=row["id"], exc_info=True)
    return len(rows)


# ------------------------------------------------------------------ 状态
def _step(key: str, state: StepState, job: db.Row | None = None, message: str | None = None) -> PipelineStep:
    return PipelineStep(key=key, state=state, task_id=job["id"] if job else None, message=message)


def _freeze_blocker(conn: Connection, project_id: str, plan: _Plan) -> tuple[StepState, str | None]:
    """输入待冻结时，用只读校验说明能否冻结：不能时给出原因（如资料晚于截止时间），而不是一直显示“进行中”。"""
    try:
        snapshots.check_inputs(conn, project_id, _snapshot_request(plan))
    except DomainError as exc:
        return "failed", f"本轮输入不能冻结：{exc.message}"
    return "running", None


StaleReason = Literal["body_updated", "tender_updated", "rules_changed", "facts_changed"]


def _stale_reasons(conn: Connection, project_id: str, plan: _Plan, last: db.Row | None) -> list[StaleReason]:
    """最近一轮完成的评审和当前输入相比，哪些已经变了。"""
    stale: list[StaleReason] = []
    if last is None or plan.missing:
        return stale
    files = set(last["files"])
    if plan.body_id and last["body_version_id"] != plan.body_id:
        stale.append("body_updated")
    if plan.tender_ids and not set(plan.tender_ids) <= files:
        stale.append("tender_updated")
    latest_pkg = rules_service.latest_package(conn, project_id)
    if latest_pkg is not None and latest_pkg["id"] != last["rule_set_id"] and sorted(latest_pkg["source_versions_json"]) == plan.tender_ids:
        stale.append("rules_changed")
    newest_facts = db.one(conn, "SELECT id FROM fact_sets WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    if (newest_facts["id"] if newest_facts else None) != last["fact_set_id"]:
        stale.append("facts_changed")
    return stale


def status(conn: Connection, actor: Actor, project_id: str) -> PipelineStatus:
    require_project(conn, actor, project_id)
    plan = _inspect(conn, project_id)
    materials: StepState = "waiting" if plan.missing else plan.parse
    steps = [_step("materials", materials, message=plan.parse_message)]
    rules_state: StepState = "done" if plan.package_id else (_job_state(plan.rules_job) if materials == "done" else "waiting")
    steps.append(_step("rules", rules_state, plan.rules_job))
    review_state: StepState = _job_state(plan.diagnosis_job) if (plan.snapshot_id or plan.held_snapshot_id) else "waiting"
    review_message: str | None = None
    if rules_state == "done" and plan.snapshot_id is None and plan.held_snapshot_id is None:
        review_state, review_message = _freeze_blocker(conn, project_id, plan)  # 规则就绪、输入待冻结
    steps.append(_step("review", review_state, plan.diagnosis_job, review_message))
    steps.append(_step("prediction", _job_state(plan.prediction_job) if review_state == "done" else "waiting", plan.prediction_job))
    if plan.missing:
        stage: Literal["waiting_materials", "waiting_start", "running", "done", "failed"] = "waiting_materials"
    elif _needs_new_round(plan) and not _may_start(conn, project_id, restart=False):
        stage = "waiting_start"
        if review_state == "running":
            steps[2] = _step("review", "waiting")
    elif any(s.state == "failed" for s in steps[:3]):
        stage = "failed"
    elif review_state == "done":
        stage = "done"
    else:
        stage = "running"
    last = last_reviewed(conn, project_id)
    rounds = db.scalar(
        conn,
        "SELECT count(DISTINCT snapshot_id) FROM jobs WHERE project_id=:p AND kind='diagnosis' AND state='succeeded'",
        {"p": project_id},
    )
    stale = _stale_reasons(conn, project_id, plan, last)
    total = unconfirmed = 0
    verification_required = False
    package = rules_service.latest_package(conn, project_id)
    if package is not None:
        effective = rules_service.effective_rules(conn, project_id, package["id"])
        total = len(effective)
        unconfirmed = sum(1 for r in effective if r["basis"] == "unconfirmed")
        all_rules = db.all_(conn, "SELECT * FROM rule_items WHERE package_id=:k AND project_id=:p", {"k": package["id"], "p": project_id})
        verification_required = bool(
            term_conflicts.pending(package["terms_json"]) or source_effectivity.pending_count(package["effectivity_json"], all_rules)
        )
    return PipelineStatus(
        project_id=project_id,
        stage=stage,
        steps=steps,
        missing=plan.missing,
        snapshot_id=last["id"] if last else None,
        round_no=int(rounds) if rounds else None,
        stale_reasons=stale,
        rules_total=total,
        rules_unconfirmed=unconfirmed,
        input_verification_required=verification_required,
        word_pdf_required=bool(
            db.scalar(
                conn,
                "SELECT count(*) FROM word_conversions WHERE project_id=:p AND source_version_id=ANY(:v)",
                {"p": project_id, "v": [*plan.tender_ids, *([plan.body_id] if plan.body_id else [])]},
            )
        ),
    )


def restart(
    conn: Connection, store: ObjectStore, actor: Actor, project_id: str, expected_context: str | None = None, request_id: str = "pipeline"
) -> PipelineStatus:
    """开始或重新评审：失败的环节重试；资料、规则或事实有更新时，基于最新输入开始新一轮。"""
    require_project(conn, actor, project_id)
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})
    action_context.require_current(conn, project_id, expected_context)
    if _needs_new_round(_inspect(conn, project_id)):  # 记下“要开始新一轮”，提取规则等异步环节完成后据此继续
        db.run(conn, "UPDATE projects SET analysis_requested_at=now() WHERE id=:p", {"p": project_id})
    advance(conn, store, project_id, restart=True)
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="analysis.request",
        object_kind="project",
        object_id=project_id,
        request_id=request_id,
        details={"expected_context": expected_context},
    )
    return status(conn, actor, project_id)
