"""项目、项目设置与评审流水线。"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import Connection

from bidwb.access import Actor
from bidwb.api.deps import Body, Ctr, CurrentSession, IdemKey, IfMatch, mutate
from bidwb.logs import get_logger
from bidwb.runtime import Container
from bidwb.schemas import PipelineStatus, Project, ProjectCreate, ProjectOverview, ProjectUpdate
from bidwb.services import pipeline, projects, report

router = APIRouter(tags=["projects"])
log = get_logger(__name__)


@router.get("/projects", response_model=list[ProjectOverview], operation_id="listProjects")
def list_projects(session: CurrentSession, ctr: Ctr) -> list[ProjectOverview]:
    """项目总览：每个项目带一行摘要（未处理的否决风险、预测、下一步），与报告同源。"""
    with ctr.engine.connect() as conn:
        return [
            ProjectOverview(**p.model_dump(), summary=report.summary(conn, session.actor, p.project_id))
            for p in projects.list_projects(conn, session.actor)
        ]


@router.post("/projects", response_model=Project, operation_id="createProject")
def create_project(body: ProjectCreate, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(ctr, session, key, "POST /projects", body, lambda c: projects.create_project(c, session.actor, body, session.request_id))


@router.get("/projects/{project_id}", response_model=Project, operation_id="getProject")
def get_project(project_id: str, session: CurrentSession, ctr: Ctr) -> Project:
    with ctr.engine.connect() as conn:
        return projects.get_project(conn, session.actor, project_id)


@router.patch("/projects/{project_id}", response_model=Project, operation_id="updateProject")
def update_project(project_id: str, body: ProjectUpdate, session: CurrentSession, key: IdemKey, if_match: IfMatch, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"PATCH /projects/{project_id}",
        [body.model_dump(mode="json", exclude_unset=True), if_match],
        lambda c: _updated(
            c, ctr, session.actor, projects.update_project(c, session.actor, project_id, body, if_match, session.request_id)
        ),
    )


def _updated(conn: Connection, ctr: Container, actor: Actor, project: Project) -> Project:
    """功能开关变化后推进一次：打开“自动开始评审”时立即开始；其余开关只影响状态对齐与报告呈现。"""
    if ctr.settings.auto_analysis:
        try:
            with conn.begin_nested():
                pipeline.advance(conn, ctr.store, project.project_id)
        except Exception:
            log.warning("pipeline_advance_failed", project_id=project.project_id, exc_info=True)
    else:
        pipeline.settle(conn, project.project_id)
    return projects.get_project(conn, actor, project.project_id)  # 推进可能改变了状态与版本号


@router.get("/projects/{project_id}/pipeline", response_model=PipelineStatus, operation_id="getPipeline")
def get_pipeline(project_id: str, session: CurrentSession, ctr: Ctr) -> PipelineStatus:
    with ctr.engine.connect() as conn:
        return pipeline.status(conn, session.actor, project_id)


@router.post("/projects/{project_id}/analysis", response_model=PipelineStatus, status_code=202, operation_id="restartAnalysis")
def restart_analysis(project_id: str, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    """重新评审：失败的环节重试；资料、规则或事实有更新时基于最新输入开始新一轮。"""
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/analysis",
        {},
        lambda c: pipeline.restart(c, ctr.store, session.actor, project_id),
    )
