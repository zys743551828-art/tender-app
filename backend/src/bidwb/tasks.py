"""任务协议（TECH-001 §7）：事务性发件箱、条件租约、结果条件提交、回收。

PostgreSQL 是任务状态的唯一事实来源；Kafka 只负责通知。因此：
* 入队：``jobs`` 与 ``outbox_events`` 在同一事务写入，要么都在，要么都不在；
* 领取：一条条件 ``UPDATE``，抢不到就直接放弃，不依赖消息的“只投递一次”；
* 提交：同时核对租约令牌（只存哈希）、attempt、输入摘要和已提交的产物，旧尝试写不进来；
* 回收：租约过期的任务回到 ``queued`` 并重新发件，尝试用尽才标记失败。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor, require_project
from bidwb.config import LEASE_SECONDS_MAX, LEASE_SECONDS_MIN
from bidwb.errors import Conflict, NotFound, Unprocessable
from bidwb.messaging import Producer
from bidwb.schemas import ArtifactRef, Task, TaskCoverage, TaskEvent, TaskRequest
from bidwb.services import audit, parse_identity
from bidwb.util import canonical_json, new_id, new_token, sha256_hex, utcnow

KIND_CLASS = {
    "parse": "parse",
    "rules": "parse",
    "diagnosis": "ai",
    "revision": "ai",
    "recheck": "ai",
    "prediction": "ai",
    "experiment": "experiment",
    "export": "export",
}
SNAPSHOT_FREE_KINDS = frozenset({"parse", "rules"})
# 通用入口 POST /projects/{id}/tasks 目前不接受任何任务种类：解析、规则提取、核对、预测由自动评审流水线入队，
# 改稿有专用入口，复检、实验、导出尚未作为任务实现。种类上线时把它加进这里，并补上对应的入队校验。
CREATABLE_KINDS: frozenset[str] = frozenset()
MAX_ATTEMPTS_CEILING = 10
RETRY_EXTRA_ATTEMPTS = 3


# ------------------------------------------------------------------ 入队
def enqueue(
    conn: Connection,
    *,
    project_id: str,
    kind: str,
    purpose: str,
    idempotency_key: str,
    input_json: dict[str, Any],
    snapshot_id: str | None = None,
    bundle_id: str | None = None,
    input_sha256: str | None = None,
) -> tuple[str, bool]:
    """写入 jobs 与 outbox_events。返回 ``(job_id, 是否新建)``；同幂等键重复调用返回已有任务且不再发件。"""
    if kind not in KIND_CLASS:
        raise Unprocessable("invalid_task_kind", f"未知任务种类：{kind}")
    job_id = new_id("job")
    now = utcnow()
    inserted = db.one(
        conn,
        """INSERT INTO jobs(id,project_id,snapshot_id,bundle_id,kind,purpose,state,stage,idempotency_key,input_sha256,input_json,job_class,created_at)
           VALUES (:id,:p,:snap,:bundle,:kind,:purpose,'queued','queued',:idem,:sha,CAST(:input AS jsonb),:cls,:now)
           ON CONFLICT (project_id,idempotency_key) DO NOTHING RETURNING id""",
        {
            "id": job_id,
            "p": project_id,
            "snap": snapshot_id,
            "bundle": bundle_id,
            "kind": kind,
            "purpose": purpose,
            "idem": idempotency_key,
            "sha": input_sha256 or sha256_hex(canonical_json(input_json)),
            "input": json.dumps(input_json, ensure_ascii=False),
            "cls": KIND_CLASS[kind],
            "now": now,
        },
    )
    if inserted is None:
        existing = db.one(conn, "SELECT id FROM jobs WHERE project_id=:p AND idempotency_key=:k", {"p": project_id, "k": idempotency_key})
        if existing is None:  # 并发回滚后消失的极端情况
            raise Conflict("enqueue_race", "任务入队冲突，请重试")
        return str(existing["id"]), False
    _emit(conn, job_id, now)
    _event(conn, job_id, 0, "queued", state="queued", stage="queued")
    return job_id, True


def _emit(conn: Connection, job_id: str, now: datetime) -> None:
    row = db.one(conn, "SELECT job_class,project_id,attempt FROM jobs WHERE id=:id", {"id": job_id})
    if row is None:
        raise NotFound("job")
    db.run(
        conn,
        "INSERT INTO outbox_events(topic,message_key,payload_json) VALUES (:t,:k,CAST(:p AS jsonb))",
        {"t": f"job.{row['job_class']}", "k": row["project_id"], "p": json.dumps({"job_id": job_id, "attempt_hint": row["attempt"] + 1})},
    )
    db.run(conn, "UPDATE jobs SET dispatched_at=:now, dispatch_count=dispatch_count+1 WHERE id=:id", {"now": now, "id": job_id})


def _event(
    conn: Connection,
    job_id: str,
    attempt: int,
    kind: str,
    *,
    state: str,
    stage: str,
    artifact_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    details = {"state": state, "stage": stage, **(extra or {})}
    db.run(
        conn,
        """INSERT INTO job_events(id,job_id,attempt,kind,artifact_id,details_json,created_at)
           VALUES (:id,:job,:attempt,:kind,:art,CAST(:d AS jsonb),:now)""",
        {
            "id": new_id("evt"),
            "job": job_id,
            "attempt": attempt,
            "kind": kind,
            "art": artifact_id,
            "d": json.dumps(details, ensure_ascii=False),
            "now": utcnow(),
        },
    )


def create_task(conn: Connection, actor: Actor, project_id: str, req: TaskRequest, idempotency_key: str, request_id: str) -> Task:
    """浏览器发起的任务（快照类）：核对项目存在、快照归属、方法包与业务用途放行，再持久入队。"""
    require_project(conn, actor, project_id)
    if req.kind not in CREATABLE_KINDS:
        raise Unprocessable(
            "kind_not_creatable_here",
            f"“{req.kind}”类任务不能通过该接口创建：解析、规则提取、诊断、改稿请使用各自的专用接口，其余种类尚未实现",
            kind=req.kind,
        )
    snapshot = db.one(conn, "SELECT sha256 FROM input_snapshots WHERE id=:s AND project_id=:p", {"s": req.snapshot_id, "p": project_id})
    if snapshot is None:
        raise NotFound("snapshot_not_found")
    if db.one(conn, "SELECT 1 AS x FROM model_bundles WHERE id=:b", {"b": req.bundle_id}) is None:
        raise NotFound("bundle_not_found")
    if (
        req.purpose == "business"
        and db.one(
            conn,
            """SELECT 1 AS x FROM release_routes rr JOIN releases r ON r.id = rr.release_id
           WHERE rr.environment='business' AND r.bundle_id=:b LIMIT 1""",
            {"b": req.bundle_id},
        )
        is None
    ):
        raise Conflict("purpose_not_released", "该方法包未放行用于业务用途", purpose=req.purpose)
    job_id, created = enqueue(
        conn,
        project_id=project_id,
        kind=req.kind,
        purpose=req.purpose,
        snapshot_id=req.snapshot_id,
        bundle_id=req.bundle_id,
        idempotency_key=f"{actor.member_id}:{idempotency_key}:{sha256_hex(canonical_json(req.model_dump()))}",
        input_json={"snapshot_id": req.snapshot_id},
        input_sha256=snapshot["sha256"],
    )
    if created:
        audit.record(
            conn,
            actor_id=actor.member_id,
            project_id=project_id,
            action="task.create",
            object_kind="task",
            object_id=job_id,
            request_id=request_id,
            details={"kind": req.kind, "purpose": req.purpose},
        )
    return get_task(conn, actor, job_id)


def start_rules_extraction(conn: Connection, actor: Actor, project_id: str, idempotency_key: str, request_id: str) -> Task:
    """对项目当前的招标文件与补遗（每个文件的最新版本）发起规则提取。"""
    require_project(conn, actor, project_id)
    # 每个招标文件/补遗只取最新版本；最新版本没有解析成功时明确失败，而不是悄悄退回旧版本
    versions = db.all_(
        conn,
        """SELECT DISTINCT ON (f.id) fv.id, fv.original_name,
                  (SELECT ps.coverage FROM parses ps WHERE ps.file_version_id=fv.id ORDER BY ps.created_at DESC, ps.id DESC LIMIT 1) AS coverage
           FROM file_versions fv JOIN files f ON f.id=fv.file_id
           WHERE fv.project_id=:p AND f.role IN ('tender','supplement')
           ORDER BY f.id, fv.obtained_at DESC, fv.id DESC""",
        {"p": project_id},
    )
    if not versions:
        raise Conflict("no_parsed_tender", "还没有解析成功的招标文件或补遗")
    bad = [v for v in versions if v["coverage"] is None or v["coverage"] == "failed"]
    if bad:
        names = "、".join(f"“{v['original_name']}”" for v in bad)
        raise Conflict(
            "tender_version_not_parsed",
            f"招标文件或补遗{names}的最新版本尚未解析成功（未解析或解析失败），请等待解析完成或重新上传后再提取规则",
            file_version_ids=[v["id"] for v in bad],
        )
    ids = sorted(v["id"] for v in versions)
    job_id, created = enqueue_rules(conn, project_id, ids, f"{actor.member_id}:{idempotency_key}")
    if created:
        audit.record(
            conn,
            actor_id=actor.member_id,
            project_id=project_id,
            action="rules.extract",
            object_kind="task",
            object_id=job_id,
            request_id=request_id,
            details={"file_version_ids": ids},
        )
    return get_task(conn, actor, job_id)


def enqueue_rules(conn: Connection, project_id: str, version_ids: list[str], idempotency_key: str) -> tuple[str, bool]:
    return enqueue(
        conn,
        project_id=project_id,
        kind="rules",
        purpose="business",
        idempotency_key=idempotency_key,
        input_json={"file_version_ids": sorted(version_ids)},
    )


def enqueue_diagnosis(conn: Connection, project_id: str, snapshot_id: str, idempotency_key: str) -> tuple[str, bool]:
    snapshot = db.one(conn, "SELECT sha256 FROM input_snapshots WHERE id=:s AND project_id=:p", {"s": snapshot_id, "p": project_id})
    if snapshot is None:
        raise NotFound("snapshot_not_found")
    parse_identity.frozen(conn, project_id, snapshot_id)
    return enqueue(
        conn,
        project_id=project_id,
        kind="diagnosis",
        purpose="business",
        snapshot_id=snapshot_id,
        idempotency_key=idempotency_key,
        input_json={"snapshot_id": snapshot_id},
        input_sha256=snapshot["sha256"],
    )


def start_diagnosis(conn: Connection, actor: Actor, project_id: str, snapshot_id: str, idempotency_key: str, request_id: str) -> Task:
    require_project(conn, actor, project_id)
    job_id, created = enqueue_diagnosis(conn, project_id, snapshot_id, f"{actor.member_id}:{idempotency_key}:{snapshot_id}")
    if created:
        audit.record(
            conn,
            actor_id=actor.member_id,
            project_id=project_id,
            action="diagnosis.start",
            object_kind="task",
            object_id=job_id,
            request_id=request_id,
            details={"snapshot_id": snapshot_id},
        )
    return get_task(conn, actor, job_id)


# ------------------------------------------------------------------ 查询
_TASK_SQL = """SELECT j.id,j.project_id,j.snapshot_id,j.bundle_id,j.kind,j.purpose,j.state,j.stage,j.attempt,j.input_sha256,
       j.error_code,j.created_at,j.coverage_json,
       (SELECT e.details_json->>'message' FROM job_events e WHERE e.job_id=j.id ORDER BY e.created_at DESC, e.id DESC LIMIT 1) AS message,
       a.id AS art_id,a.sha256 AS art_sha,a.media_type AS art_type,a.byte_size AS art_size,a.contract_version AS art_cv
       FROM jobs j LEFT JOIN artifacts a ON a.id = j.output_artifact_id """


def _task_from(row: db.Row) -> Task:
    artifact = (
        ArtifactRef(
            artifact_id=row["art_id"],
            sha256=row["art_sha"],
            media_type=row["art_type"],
            byte_size=row["art_size"],
            contract_version=row["art_cv"],
        )
        if row["art_id"]
        else None
    )
    return Task(
        task_id=row["id"],
        project_id=row["project_id"],
        snapshot_id=row["snapshot_id"],
        bundle_id=row["bundle_id"],
        kind=row["kind"],
        purpose=row["purpose"],
        state=row["state"],
        stage=row["stage"],
        attempt=row["attempt"],
        input_sha256=row["input_sha256"],
        output_artifact=artifact,
        error_code=row["error_code"],
        created_at=row["created_at"],
        message=row["message"],
        coverage=TaskCoverage.model_validate(row["coverage_json"]) if row["coverage_json"] else None,
    )


def get_task(conn: Connection, actor: Actor, task_id: str) -> Task:
    row = db.one(conn, _TASK_SQL + "WHERE j.id=:id", {"id": task_id})
    if row is None:
        raise NotFound("task_not_found")
    require_project(conn, actor, row["project_id"])
    return _task_from(row)


def list_tasks(conn: Connection, actor: Actor, project_id: str, limit: int = 50) -> list[Task]:
    require_project(conn, actor, project_id)
    rows = db.all_(conn, _TASK_SQL + "WHERE j.project_id=:p ORDER BY j.created_at DESC LIMIT :n", {"p": project_id, "n": limit})
    return [_task_from(r) for r in rows]


def list_events(conn: Connection, actor: Actor, task_id: str, after_event_id: str | None = None) -> list[tuple[str, TaskEvent]]:
    """返回 ``(事件 ID, 事件)``，按发生顺序；``after_event_id`` 之后的事件用于 SSE 续传。"""
    job = db.one(conn, "SELECT project_id FROM jobs WHERE id=:id", {"id": task_id})
    if job is None:
        raise NotFound("task_not_found")
    require_project(conn, actor, job["project_id"])
    cursor = None
    if after_event_id:
        cursor = db.one(conn, "SELECT created_at FROM job_events WHERE id=:e AND job_id=:j", {"e": after_event_id, "j": task_id})
    rows = db.all_(
        conn,
        """SELECT id,attempt,kind,details_json,created_at FROM job_events
           WHERE job_id=:j AND (CAST(:after AS timestamptz) IS NULL OR (created_at, id) > (CAST(:after AS timestamptz), :aid))
           ORDER BY created_at, id""",
        {"j": task_id, "after": cursor["created_at"] if cursor else None, "aid": after_event_id or ""},
    )
    return [
        (
            r["id"],
            TaskEvent(
                task_id=task_id,
                attempt=r["attempt"],
                kind=r["kind"],
                state=r["details_json"].get("state", "queued"),
                stage=r["details_json"].get("stage", ""),
                at=r["created_at"],
                message=r["details_json"].get("message"),
                coverage=TaskCoverage.model_validate(r["details_json"]["coverage"]) if r["details_json"].get("coverage") else None,
            ),
        )
        for r in rows
    ]


# ------------------------------------------------------------------ 人工干预
def cancel_task(conn: Connection, actor: Actor, task_id: str, request_id: str) -> Task:
    job = db.one(conn, "SELECT project_id,state,attempt FROM jobs WHERE id=:id FOR UPDATE", {"id": task_id})
    if job is None:
        raise NotFound("task_not_found")
    require_project(conn, actor, job["project_id"])
    if job["state"] == "queued":
        db.run(conn, "UPDATE jobs SET state='cancelled',stage='cancelled',finished_at=:now WHERE id=:id", {"now": utcnow(), "id": task_id})
        _event(conn, task_id, job["attempt"], "cancelled", state="cancelled", stage="cancelled")
    elif job["state"] in {"running", "waiting_input"}:
        db.run(conn, "UPDATE jobs SET state='cancel_requested' WHERE id=:id", {"id": task_id})
        _event(conn, task_id, job["attempt"], "cancel_requested", state="cancel_requested", stage="running")
    elif job["state"] not in {"cancel_requested", "cancelled"}:
        raise Conflict("task_not_cancellable", "任务已结束，不能取消", state=job["state"])
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=job["project_id"],
        action="task.cancel",
        object_kind="task",
        object_id=task_id,
        request_id=request_id,
    )
    return get_task(conn, actor, task_id)


def retry_task(conn: Connection, actor: Actor, task_id: str, request_id: str) -> Task:
    """失败任务重新排队：追加 3 次尝试额度，总额度不超过 10。"""
    job = db.one(conn, "SELECT project_id,state,attempt,max_attempts FROM jobs WHERE id=:id FOR UPDATE", {"id": task_id})
    if job is None:
        raise NotFound("task_not_found")
    require_project(conn, actor, job["project_id"])
    if job["state"] != "failed":
        raise Conflict("task_not_retryable", "只有失败的任务可以重试", state=job["state"])
    new_max = job["attempt"] + RETRY_EXTRA_ATTEMPTS
    if new_max > MAX_ATTEMPTS_CEILING:
        raise Conflict("retry_limit_reached", "该任务已多次失败，请检查输入后创建新任务")
    db.run(
        conn,
        """UPDATE jobs SET state='queued',stage='queued',error_code=NULL,finished_at=NULL,max_attempts=:m WHERE id=:id""",
        {"m": new_max, "id": task_id},
    )
    _emit(conn, task_id, utcnow())
    _event(conn, task_id, job["attempt"], "retried", state="queued", stage="queued")
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=job["project_id"],
        action="task.retry",
        object_kind="task",
        object_id=task_id,
        request_id=request_id,
    )
    return get_task(conn, actor, task_id)


# ------------------------------------------------------------------ 发件箱中继
def relay_outbox(conn: Connection, producer: Producer, batch: int = 100) -> int:
    """先发送并等待确认，再标记已发布。

    确认与标记之间进程崩溃只会导致重发，由消费端去重吸收；发送失败的行保留未发布并累计失败次数。
    ``SKIP LOCKED`` 让多个中继实例互不阻塞。
    """
    sent = 0
    rows = db.all_(
        conn,
        """SELECT id,event_id,topic,message_key,payload_json FROM outbox_events
           WHERE published_at IS NULL ORDER BY id FOR UPDATE SKIP LOCKED LIMIT :n""",
        {"n": batch},
    )
    for row in rows:
        try:
            producer.send(row["topic"], row["message_key"], json.dumps(row["payload_json"]).encode(), str(row["event_id"]))
        except Exception as exc:
            db.run(
                conn,
                "UPDATE outbox_events SET publish_attempts=publish_attempts+1,last_error=:e WHERE id=:id",
                {"e": str(exc)[:200], "id": row["id"]},
            )
            continue
        db.run(conn, "UPDATE outbox_events SET published_at=now(),publish_attempts=publish_attempts+1 WHERE id=:id", {"id": row["id"]})
        sent += 1
    return sent


def consume_once(conn: Connection, consumer: str, event_id: str) -> bool:
    """去重登记；返回 False 表示这条消息已处理过。登记与随后的领取应处于同一事务。"""
    return (
        db.one(
            conn,
            "INSERT INTO processed_messages(consumer,event_id) VALUES (:c, CAST(:e AS uuid)) ON CONFLICT DO NOTHING RETURNING 1 AS ok",
            {"c": consumer, "e": event_id},
        )
        is not None
    )


# ------------------------------------------------------------------ worker 侧
@dataclass(frozen=True)
class Claim:
    job_id: str
    attempt: int
    lease_token: str
    lease_until: datetime
    kind: str
    project_id: str
    input_sha256: str
    input_json: dict[str, Any]
    snapshot_id: str | None


def _check_lease_seconds(seconds: int) -> None:
    if not LEASE_SECONDS_MIN <= seconds <= LEASE_SECONDS_MAX:
        raise Unprocessable("invalid_lease_seconds", f"租约时长必须在 {LEASE_SECONDS_MIN}–{LEASE_SECONDS_MAX} 秒")


def claim_job(
    conn: Connection, job_id: str, worker_id: str, job_class: str, lease_seconds: int, now: datetime | None = None
) -> Claim | None:
    """单条条件 UPDATE：未被持有、或租约已过期，且属于本 worker 类别才可领取。抢不到返回 ``None``。"""
    _check_lease_seconds(lease_seconds)
    now = now or utcnow()
    token = new_token()
    row = db.one(
        conn,
        """UPDATE jobs SET state='running',stage='running',attempt=attempt+1,worker_id=:w,lease_token_hash=:h,lease_until=:until
           WHERE id=:id AND job_class=:cls AND attempt<max_attempts
             AND (state='queued' OR (state IN ('running','cancel_requested') AND lease_until<:now))
           RETURNING attempt,kind,project_id,input_sha256,input_json,snapshot_id""",
        {
            "w": worker_id,
            "h": sha256_hex(token),
            "until": now + timedelta(seconds=lease_seconds),
            "id": job_id,
            "cls": job_class,
            "now": now,
        },
    )
    if row is None:
        return None
    _event(conn, job_id, row["attempt"], "claimed", state="running", stage="running", extra={"worker_id": worker_id})
    return Claim(
        job_id,
        row["attempt"],
        token,
        now + timedelta(seconds=lease_seconds),
        row["kind"],
        row["project_id"],
        row["input_sha256"],
        dict(row["input_json"]),
        row["snapshot_id"],
    )


def renew_lease(conn: Connection, claim: Claim, lease_seconds: int, now: datetime | None = None) -> datetime:
    """续租。租约已丢（过期被回收、被取消后重领等）抛 ``Conflict('lease_lost')``，调用方必须停止写入。"""
    _check_lease_seconds(lease_seconds)
    now = now or utcnow()
    until = now + timedelta(seconds=lease_seconds)
    row = db.one(
        conn,
        """UPDATE jobs SET lease_until=:until WHERE id=:id AND state IN ('running','cancel_requested') AND attempt=:a
             AND lease_token_hash=:h AND lease_until>=:now RETURNING state""",
        {"until": until, "id": claim.job_id, "a": claim.attempt, "h": sha256_hex(claim.lease_token), "now": now},
    )
    if row is None:
        raise Conflict("lease_lost", "任务租约已失效")
    if row["state"] == "cancel_requested":
        raise Conflict("cancel_requested", "任务已被请求取消")
    return until


def acknowledge_cancel(conn: Connection, claim: Claim) -> None:
    """worker 看到取消请求后确认停止。"""
    updated = db.run(
        conn,
        """UPDATE jobs SET state='cancelled',stage='cancelled',finished_at=:now,lease_token_hash=NULL,lease_until=NULL,worker_id=NULL
           WHERE id=:id AND state='cancel_requested' AND attempt=:a AND lease_token_hash=:h""",
        {"now": utcnow(), "id": claim.job_id, "a": claim.attempt, "h": sha256_hex(claim.lease_token)},
    )
    if updated:
        _event(conn, claim.job_id, claim.attempt, "cancelled", state="cancelled", stage="cancelled")


def commit_result(
    conn: Connection,
    claim: Claim,
    *,
    input_sha256: str,
    artifact_id: str | None,
    error_code: str | None = None,
    error_message: str | None = None,
    coverage: dict[str, Any] | None = None,
    message: str | None = None,
    now: datetime | None = None,
) -> None:
    """条件提交。成功需要已提交（committed）的产物；失败只记录错误码。旧尝试、过期租约、输入不符一律 ``lease_lost``/``input_mismatch``。"""
    now = now or utcnow()
    job = db.one(
        conn,
        "SELECT state,attempt,lease_token_hash,lease_until,input_sha256 FROM jobs WHERE id=:id FOR UPDATE",
        {"id": claim.job_id},
    )
    if job is None:
        raise NotFound("job")
    if (
        job["state"] != "running"
        or job["attempt"] != claim.attempt
        or job["lease_token_hash"] != sha256_hex(claim.lease_token)
        or job["lease_until"] < now
    ):
        raise Conflict("lease_lost", "任务租约已失效，结果未提交")
    if input_sha256 != job["input_sha256"]:
        raise Conflict("input_hash_mismatch", "输入摘要与任务不一致")
    if artifact_id is not None:
        art = db.one(conn, "SELECT status FROM artifacts WHERE id=:a", {"a": artifact_id})
        if art is None or art["status"] != "committed":
            raise Unprocessable("artifact_not_committed", "产物尚未核验提交")
        db.run(
            conn,
            """UPDATE jobs SET state='succeeded',stage='done',output_artifact_id=:a,finished_at=:now,coverage_json=CAST(:cov AS jsonb),
                      lease_token_hash=NULL,lease_until=NULL,worker_id=NULL WHERE id=:id""",
            {"a": artifact_id, "now": now, "id": claim.job_id, "cov": json.dumps(coverage) if coverage is not None else None},
        )
        _event(
            conn,
            claim.job_id,
            claim.attempt,
            "succeeded",
            state="succeeded",
            stage="done",
            artifact_id=artifact_id,
            extra={**({"coverage": coverage} if coverage is not None else {}), **({"message": message} if message else {})},
        )
    else:
        db.run(
            conn,
            """UPDATE jobs SET state='failed',stage='failed',error_code=:e,finished_at=:now,
                      lease_token_hash=NULL,lease_until=NULL,worker_id=NULL WHERE id=:id""",
            {"e": error_code or "worker_failed", "now": now, "id": claim.job_id},
        )
        _event(
            conn,
            claim.job_id,
            claim.attempt,
            "failed",
            state="failed",
            stage="failed",
            extra={"error_code": error_code or "worker_failed", **({"message": error_message} if error_message else {})},
        )


def release_for_retry(conn: Connection, claim: Claim, error_code: str) -> str:
    """暂时性故障（依赖服务不可用）：把任务放回队列重新发件；尝试用尽则失败。返回新状态。"""
    row = db.one(
        conn,
        "SELECT attempt,max_attempts FROM jobs WHERE id=:id AND state='running' AND attempt=:a AND lease_token_hash=:h FOR UPDATE",
        {"id": claim.job_id, "a": claim.attempt, "h": sha256_hex(claim.lease_token)},
    )
    if row is None:
        raise Conflict("lease_lost", "任务租约已失效")
    if row["attempt"] >= row["max_attempts"]:
        db.run(
            conn,
            """UPDATE jobs SET state='failed',stage='failed',error_code=:e,finished_at=:now,
                        lease_token_hash=NULL,lease_until=NULL,worker_id=NULL WHERE id=:id""",
            {"e": error_code, "now": utcnow(), "id": claim.job_id},
        )
        _event(conn, claim.job_id, claim.attempt, "failed", state="failed", stage="failed", extra={"error_code": error_code})
        return "failed"
    db.run(
        conn,
        "UPDATE jobs SET state='queued',stage='queued',lease_token_hash=NULL,lease_until=NULL,worker_id=NULL WHERE id=:id",
        {"id": claim.job_id},
    )
    _emit(conn, claim.job_id, utcnow())
    _event(conn, claim.job_id, claim.attempt, "retrying", state="queued", stage="queued", extra={"error_code": error_code})
    return "queued"


def set_stage(conn: Connection, claim: Claim, stage: str) -> None:
    """记录阶段进度（仅当租约仍属于本次尝试）。"""
    updated = db.run(
        conn,
        "UPDATE jobs SET stage=:s WHERE id=:id AND state='running' AND attempt=:a AND lease_token_hash=:h",
        {"s": stage, "id": claim.job_id, "a": claim.attempt, "h": sha256_hex(claim.lease_token)},
    )
    if updated == 0:
        raise Conflict("lease_lost", "任务租约已失效")
    _event(conn, claim.job_id, claim.attempt, "stage", state="running", stage=stage)


# ------------------------------------------------------------------ 回收器
def reap(conn: Connection, now: datetime | None = None, redispatch_after_seconds: int = 120) -> dict[str, int]:
    """过期租约回到 queued 并重新发件；尝试用尽标记失败；长时间未被领取的 queued 任务重发。"""
    now = now or utcnow()
    out = {"requeued": 0, "failed": 0, "redispatched": 0, "cancelled": 0}
    expired = db.all_(
        conn,
        "SELECT id,attempt,max_attempts,state FROM jobs WHERE state IN ('running','cancel_requested') AND lease_until<:now FOR UPDATE SKIP LOCKED",
        {"now": now},
    )
    for job in expired:
        if job["state"] == "cancel_requested":
            db.run(
                conn,
                "UPDATE jobs SET state='cancelled',stage='cancelled',finished_at=:now,lease_token_hash=NULL,lease_until=NULL,worker_id=NULL WHERE id=:id",
                {"now": now, "id": job["id"]},
            )
            _event(conn, job["id"], job["attempt"], "cancelled", state="cancelled", stage="cancelled")
            out["cancelled"] += 1
        elif job["attempt"] >= job["max_attempts"]:
            db.run(
                conn,
                """UPDATE jobs SET state='failed',stage='failed',error_code='lease_expired_attempts_exhausted',finished_at=:now,
                                lease_token_hash=NULL,lease_until=NULL,worker_id=NULL WHERE id=:id""",
                {"now": now, "id": job["id"]},
            )
            _event(
                conn,
                job["id"],
                job["attempt"],
                "failed",
                state="failed",
                stage="failed",
                extra={"error_code": "lease_expired_attempts_exhausted"},
            )
            out["failed"] += 1
        else:
            db.run(
                conn,
                "UPDATE jobs SET state='queued',stage='queued',lease_token_hash=NULL,lease_until=NULL,worker_id=NULL WHERE id=:id",
                {"id": job["id"]},
            )
            _emit(conn, job["id"], now)
            _event(conn, job["id"], job["attempt"], "requeued", state="queued", stage="queued")
            out["requeued"] += 1
    cutoff = now - timedelta(seconds=redispatch_after_seconds)
    stale = db.all_(
        conn,
        "SELECT id FROM jobs WHERE state='queued' AND (dispatched_at IS NULL OR dispatched_at<:cutoff) FOR UPDATE SKIP LOCKED",
        {"cutoff": cutoff},
    )
    for job in stale:
        _emit(conn, job["id"], now)
        out["redispatched"] += 1
    return out
