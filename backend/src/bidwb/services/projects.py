"""项目与项目设置。"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import JSONB

from bidwb import db
from bidwb.access import Actor, require_project
from bidwb.errors import NotFound, PreconditionFailed, Unprocessable
from bidwb.schemas import Project, ProjectCreate, ProjectSettings, ProjectUpdate
from bidwb.services import audit
from bidwb.util import new_id, utcnow

_UPDATABLE = ("title", "tender_number", "lot", "round", "region", "engineering_type", "deadline")
_PROJECTS = sa.table(
    "projects", sa.column("id"), sa.column("revision"), sa.column("settings_json", JSONB), *(sa.column(c) for c in _UPDATABLE)
)
_LIST_SQL = """SELECT p.id, p.title, p.tender_number, p.lot, p.round, p.region, p.engineering_type, p.deadline, p.state, p.revision,
              p.owner_id, p.created_at, p.settings_json
       FROM projects p ORDER BY p.deadline NULLS LAST, p.created_at DESC"""
_GET_SQL = """SELECT p.id, p.title, p.tender_number, p.lot, p.round, p.region, p.engineering_type, p.deadline, p.state, p.revision,
              p.owner_id, p.created_at, p.settings_json FROM projects p WHERE p.id = :id"""


def _to_project(row: db.Row) -> Project:
    return Project(
        project_id=row["id"],
        title=row["title"],
        tender_number=row["tender_number"],
        lot=row["lot"],
        round=row["round"],
        region=row["region"],
        engineering_type=row["engineering_type"],
        deadline=row["deadline"],
        state=row["state"],
        revision=row["revision"],
        owner_id=row["owner_id"],
        created_at=row["created_at"],
        settings=ProjectSettings.model_validate(row["settings_json"]),
    )


def settings_of(conn: Connection, project_id: str) -> ProjectSettings:
    """项目的功能开关（缺省的键取默认值）；项目不存在时取全部默认值。"""
    row = db.one(conn, "SELECT settings_json FROM projects WHERE id=:p", {"p": project_id})
    return ProjectSettings.model_validate(row["settings_json"] if row else {})


def list_projects(conn: Connection, actor: Actor) -> list[Project]:
    del actor
    return [_to_project(r) for r in db.all_(conn, _LIST_SQL)]


def get_project(conn: Connection, actor: Actor, project_id: str) -> Project:
    del actor
    row = db.one(conn, _GET_SQL, {"id": project_id})
    if row is None:
        raise NotFound("project_not_found")
    return _to_project(row)


def create_project(conn: Connection, actor: Actor, data: ProjectCreate, request_id: str) -> Project:
    project_id = new_id("prj")
    db.run(
        conn,
        """INSERT INTO projects(id,title,tender_number,lot,round,region,engineering_type,deadline,state,revision,owner_id,created_at,settings_json)
           VALUES (:id,:title,:tn,:lot,:round,:region,:et,:deadline,'materials_pending',1,:owner,:now,CAST(:settings AS jsonb))""",
        {
            "id": project_id,
            "title": data.title,
            "tn": data.tender_number,
            "lot": data.lot,
            "round": data.round,
            "region": data.region,
            "et": data.engineering_type,
            "deadline": data.deadline,
            "owner": actor.member_id,
            "now": utcnow(),
            "settings": json.dumps(data.settings.model_dump()),
        },
    )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="project.create",
        object_kind="project",
        object_id=project_id,
        request_id=request_id,
        details={"title": data.title},
    )
    return get_project(conn, actor, project_id)


def _lock_revision(conn: Connection, project_id: str, if_match: int) -> int:
    row = db.one(conn, "SELECT revision FROM projects WHERE id=:id FOR UPDATE", {"id": project_id})
    if row is None:
        raise NotFound("project_not_found")
    if row["revision"] != if_match:
        raise PreconditionFailed("stale_version", "项目已被他人修改，请刷新后重试", current_revision=row["revision"])
    return int(row["revision"])


def update_project(conn: Connection, actor: Actor, project_id: str, data: ProjectUpdate, if_match: int, request_id: str) -> Project:
    require_project(conn, actor, project_id)
    changes: dict[str, Any] = {k: getattr(data, k) for k in data.model_fields_set if k in _UPDATABLE}
    if "settings" in data.model_fields_set:
        if data.settings is None:
            raise Unprocessable("invalid_field", "settings 不能为空")
        changes["settings_json"] = data.settings.model_dump()
    if not changes:
        raise Unprocessable("empty_update", "没有可更新的字段")
    for required in ("title", "round"):
        if required in changes and changes[required] is None:
            raise Unprocessable("invalid_field", f"{required} 不能为空")
    _lock_revision(conn, project_id, if_match)
    conn.execute(sa.update(_PROJECTS).where(_PROJECTS.c.id == project_id).values({**changes, "revision": _PROJECTS.c.revision + 1}))
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="project.update",
        object_kind="project",
        object_id=project_id,
        request_id=request_id,
        details={"fields": sorted(changes), **({"settings": data.settings.model_dump()} if data.settings is not None else {})},
    )
    return get_project(conn, actor, project_id)
