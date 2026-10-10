"""任务：创建、查询、进度推送（SSE）、取消与重试。"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from bidwb import db, tasks
from bidwb.api.deps import Body, Ctr, CurrentSession, IdemKey, mutate
from bidwb.schemas import AdoptRequest, DiagnosisRequest, RejectRevisionRequest, Revision, RevisionDiff, RevisionRequest, Task, TaskRequest
from bidwb.services import revisions

router = APIRouter(tags=["tasks"])

SSE_POLL_SECONDS = 1.0
SSE_HEARTBEAT_SECONDS = 15.0
SSE_MAX_SECONDS = 600.0
_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


@router.post("/projects/{project_id}/tasks", response_model=Task, status_code=202, operation_id="createTask")
def create_task(project_id: str, body: TaskRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    """202 只表示“已持久入队”，不表示已开始或已完成。"""
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/tasks",
        body,
        lambda c: tasks.create_task(c, session.actor, project_id, body, key, session.request_id),
    )


@router.post("/projects/{project_id}/rules:extract", response_model=Task, status_code=202, operation_id="extractRules")
def extract_rules(project_id: str, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    """对当前招标文件与补遗发起规则提取；结果是待负责人逐条确认的候选规则。"""
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/rules:extract",
        {},
        lambda c: tasks.start_rules_extraction(c, session.actor, project_id, key, session.request_id),
    )


@router.post("/projects/{project_id}/diagnosis", response_model=Task, status_code=202, operation_id="startDiagnosis")
def start_diagnosis(project_id: str, body: DiagnosisRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/diagnosis",
        body,
        lambda c: tasks.start_diagnosis(c, session.actor, project_id, body.snapshot_id, key, session.request_id),
    )


@router.post("/projects/{project_id}/revisions", response_model=Task, status_code=202, operation_id="proposeRevision")
def propose_revision(project_id: str, body: RevisionRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    """按范围生成局部改稿建议；202 返回任务，完成后建议出现在 GET /projects/{id}/revisions。"""
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/revisions",
        body,
        lambda c: revisions.propose(c, session.actor, project_id, body, key, session.request_id),
    )


@router.get("/projects/{project_id}/revisions", response_model=list[Revision], operation_id="listRevisions")
def list_revisions(project_id: str, session: CurrentSession, ctr: Ctr) -> list[Revision]:
    with ctr.engine.connect() as conn:
        return revisions.list_revisions(conn, session.actor, project_id)


@router.get("/revisions/{revision_id}/diff", response_model=RevisionDiff, operation_id="getRevisionDiff")
def get_revision_diff(revision_id: str, session: CurrentSession, ctr: Ctr) -> RevisionDiff:
    with ctr.engine.connect() as conn:
        return RevisionDiff.model_validate(revisions.get_diff(conn, ctr.store, session.actor, revision_id))


@router.post("/revisions/{revision_id}/adopt", response_model=Revision, operation_id="adoptRevision")
def adopt_revision(revision_id: str, body: AdoptRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /revisions/{revision_id}/adopt",
        body,
        lambda c: revisions.adopt(c, ctr.store, session.actor, revision_id, body, session.request_id),
    )


@router.post("/revisions/{revision_id}/reject", response_model=Revision, operation_id="rejectRevision")
def reject_revision(revision_id: str, body: RejectRevisionRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /revisions/{revision_id}/reject",
        body,
        lambda c: revisions.reject(c, session.actor, revision_id, body, session.request_id),
    )


@router.get("/projects/{project_id}/tasks", response_model=list[Task], operation_id="listTasks")
def list_tasks(project_id: str, session: CurrentSession, ctr: Ctr) -> list[Task]:
    with ctr.engine.connect() as conn:
        return tasks.list_tasks(conn, session.actor, project_id)


@router.get("/tasks/{task_id}", response_model=Task, operation_id="getTask")
def get_task(task_id: str, session: CurrentSession, ctr: Ctr) -> Task:
    with ctr.engine.connect() as conn:
        return tasks.get_task(conn, session.actor, task_id)


@router.post("/tasks/{task_id}/cancel", response_model=Task, status_code=202, operation_id="cancelTask")
def cancel_task(task_id: str, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr, session, key, f"POST /tasks/{task_id}/cancel", {}, lambda c: tasks.cancel_task(c, session.actor, task_id, session.request_id)
    )


@router.post("/tasks/{task_id}/retry", response_model=Task, status_code=202, operation_id="retryTask")
def retry_task(task_id: str, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr, session, key, f"POST /tasks/{task_id}/retry", {}, lambda c: tasks.retry_task(c, session.actor, task_id, session.request_id)
    )


@router.get(
    "/tasks/{task_id}/events",
    operation_id="streamTaskEvents",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def stream_task_events(
    task_id: str,
    session: CurrentSession,
    ctr: Ctr,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """服务端推送任务进度。断线后浏览器带 ``Last-Event-ID`` 重连即可续传；任务到达终态后自动结束。"""
    with ctr.engine.connect() as conn:  # 先同步验权：无权访问时直接返回 404，而不是开一个空流
        tasks.get_task(conn, session.actor, task_id)

    def generate() -> Iterator[str]:
        cursor = last_event_id
        started = last_beat = time.monotonic()
        while time.monotonic() - started < SSE_MAX_SECONDS:
            with ctr.engine.connect() as conn:
                events = tasks.list_events(conn, session.actor, task_id, cursor)
                state = db.scalar(conn, "SELECT state FROM jobs WHERE id=:i", {"i": task_id})
            for event_id, event in events:
                cursor = event_id
                yield f"id: {event_id}\nevent: task\ndata: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"
                last_beat = time.monotonic()
            if state in _TERMINAL and not events:
                return
            if time.monotonic() - last_beat >= SSE_HEARTBEAT_SECONDS:
                yield ": keep-alive\n\n"
                last_beat = time.monotonic()
            time.sleep(SSE_POLL_SECONDS)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
