"""研究产出的登记与发布路由：打分模型（``scoring-model/1``）与比较锚点包（``anchor-pack/1``）。

登记在一个事务里写齐追溯链：产物（原件与评估报告存对象存储）→ 数据集快照 → 实验 → 方法包 → 验证 → 发布，
再把发布路由（目标 × 环境 × 范围）指向新的发布，``revision`` 加一。业务（business）与影子（shadow）环境各自独立；
影子环境的结果只写进预测明细供对照，不展示。撤下路由即回到未校准（不删除任何登记记录，它们是追加保存的）。

路由目标：``technical_total``（打分模型）、``anchor_pack``（锚点包）。范围键目前只有 ``default``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Connection

from bidwb import db
from bidwb.errors import NotFound
from bidwb.services import audit
from bidwb.storage import ObjectStore, artifact_key
from bidwb.util import new_id, sha256_hex, utcnow

Environment = Literal["business", "shadow"]
SCOPE_KEY = "default"
TARGET_SCORING = "technical_total"
TARGET_ANCHORS = "anchor_pack"


@dataclass(frozen=True)
class Registration:
    """一份待登记的研究产出。``payload`` 与 ``report`` 原样存为产物。"""

    target: str
    schema: str  # 契约版本，写入方法包与产物
    identity: str  # 内容标识（model_id / pack_id）
    payload: bytes
    components: dict[str, Any]  # 方法包里供运行时读取的内容（锚点包只放摘要，正文在产物里）
    report: bytes
    report_contract: str
    method: str
    code_sha256: str
    protocol: str
    member_count: int
    grouping: str
    created_at: datetime
    scope_text: str  # 人读的适用范围


@dataclass(frozen=True)
class Registered:
    release_id: str
    bundle_id: str
    revision: int
    previous_release_id: str | None
    unchanged: bool  # 同一内容已是该环境的生效发布：什么都没写


def _member_by_login(conn: Connection, login: str) -> str:
    row = db.one(
        conn,
        "SELECT m.id FROM identities i JOIN members m ON m.id=i.member_id WHERE i.provider='local' AND i.subject=:s AND m.active",
        {"s": login},
    )
    if row is None:
        raise NotFound("member_not_found", f"没有登录名为 {login} 的有效成员")
    return str(row["id"])


def _store_artifact(conn: Connection, store: ObjectStore, data: bytes, contract: str) -> str:
    artifact_id = new_id("art")
    key = artifact_key(artifact_id)
    store.put(key, data, "application/json")
    db.run(
        conn,
        """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
           VALUES (:i,:sha,:k,:n,'application/json',:cv,:now,'committed')""",
        {"i": artifact_id, "sha": sha256_hex(data), "k": key, "n": len(data), "cv": contract, "now": utcnow()},
    )
    return artifact_id


ROUTE_SQL = """SELECT rr.target, rr.environment, rr.scope_key, rr.revision, r.id AS release_id, r.validation_id, r.released_at,
       r.scope AS release_scope, b.id AS bundle_id, b.contract_version, b.components_json, a.object_key AS artifact_key
FROM release_routes rr JOIN releases r ON r.id=rr.release_id JOIN model_bundles b ON b.id=r.bundle_id JOIN artifacts a ON a.id=b.artifact_id """


def routed(conn: Connection, target: str, environment: Environment) -> db.Row | None:
    """该目标在该环境当前生效的发布（含方法包内容与原件位置）；没有路由时为 ``None``。"""
    return db.one(
        conn,
        ROUTE_SQL + "WHERE rr.target=:t AND rr.environment=:e AND rr.scope_key=:k",
        {"t": target, "e": environment, "k": SCOPE_KEY},
    )


def routes(conn: Connection) -> list[db.Row]:
    return db.all_(conn, ROUTE_SQL + "ORDER BY rr.target, rr.environment, rr.scope_key")


def register(
    conn: Connection, store: ObjectStore, reg: Registration, *, environment: Environment, reviewer_login: str, request_id: str = "cli"
) -> Registered:
    """登记并路由。调用方负责契约校验与业务环境的放行门槛；这里只保证追溯链完整、路由原子切换。"""
    reviewer = _member_by_login(conn, reviewer_login)
    current = db.one(
        conn,
        """SELECT rr.release_id, rr.revision, b.components_json FROM release_routes rr JOIN releases r ON r.id=rr.release_id
           JOIN model_bundles b ON b.id=r.bundle_id WHERE rr.target=:t AND rr.environment=:e AND rr.scope_key=:k FOR UPDATE OF rr""",
        {"t": reg.target, "e": environment, "k": SCOPE_KEY},
    )
    if current is not None and _identity(current["components_json"]) == reg.identity:
        bundle = db.scalar(conn, "SELECT bundle_id FROM releases WHERE id=:r", {"r": current["release_id"]})
        return Registered(current["release_id"], str(bundle), current["revision"], None, unchanged=True)
    now = utcnow()
    payload_id = _store_artifact(conn, store, reg.payload, reg.schema)
    report_id = _store_artifact(conn, store, reg.report, reg.report_contract)
    purpose = f"{reg.target}_{environment}"
    dataset_id, experiment_id, bundle_id = new_id("dst"), new_id("exp"), new_id("mdl")
    validation_id, release_id = new_id("val"), new_id("rel")
    db.run(
        conn,
        """INSERT INTO dataset_snapshots(id,purpose,protocol_version,manifest_artifact_id,member_count,grouping,time_cutoff,created_at)
           VALUES (:i,:pu,:pv,:m,:n,:g,:cut,:now)""",
        {
            "i": dataset_id,
            "pu": purpose,
            "pv": reg.protocol,
            "m": report_id,
            "n": reg.member_count,
            "g": reg.grouping,
            "cut": reg.created_at,
            "now": now,
        },
    )
    db.run(
        conn,
        """INSERT INTO experiments(id,dataset_id,protocol_version,strategy,code_sha256,config_artifact_id,status,report_artifact_id,started_at)
           VALUES (:i,:d,:pv,:s,:c,:cfg,'succeeded',:rep,:at)""",
        {
            "i": experiment_id,
            "d": dataset_id,
            "pv": reg.protocol,
            "s": reg.method,
            "c": reg.code_sha256,
            "cfg": payload_id,
            "rep": report_id,
            "at": reg.created_at,
        },
    )
    db.run(
        conn,
        """INSERT INTO model_bundles(id,target,contract_version,components_json,experiment_id,artifact_id,registered_at)
           VALUES (:i,:t,:cv,CAST(:c AS jsonb),:e,:a,:now)""",
        {
            "i": bundle_id,
            "t": reg.target,
            "cv": reg.schema,
            "c": json.dumps(reg.components, ensure_ascii=False),
            "e": experiment_id,
            "a": payload_id,
            "now": now,
        },
    )
    db.run(
        conn,
        """INSERT INTO validations(id,bundle_id,dataset_id,purpose,status,scope,report_artifact_id,reviewer_id,validated_at)
           VALUES (:i,:b,:d,:pu,'passed',:sc,:rep,:who,:now)""",
        {
            "i": validation_id,
            "b": bundle_id,
            "d": dataset_id,
            # 业务环境的发布要求业务用途的验证（触发器强制）；影子环境只是研究对照
            "pu": "technical_total_business" if environment == "business" else "research",
            "sc": reg.scope_text,
            "rep": report_id,
            "who": reviewer,
            "now": now,
        },
    )
    previous = current["release_id"] if current else None
    db.run(
        conn,
        """INSERT INTO releases(id,bundle_id,validation_id,environment,scope,previous_release_id,actor_id,released_at)
           VALUES (:i,:b,:v,:e,:sc,:prev,:who,:now)""",
        {
            "i": release_id,
            "b": bundle_id,
            "v": validation_id,
            "e": environment,
            "sc": reg.scope_text,
            "prev": previous,
            "who": reviewer,
            "now": now,
        },
    )
    revision = db.scalar(
        conn,
        """INSERT INTO release_routes(target,environment,scope_key,release_id,revision) VALUES (:t,:e,:k,:r,1)
           ON CONFLICT (target,environment,scope_key) DO UPDATE SET release_id=EXCLUDED.release_id, revision=release_routes.revision+1
           RETURNING revision""",
        {"t": reg.target, "e": environment, "k": SCOPE_KEY, "r": release_id},
    )
    audit.record(
        conn,
        actor_id=reviewer,
        project_id=None,
        action=f"{reg.target}.release",
        object_kind="release",
        object_id=release_id,
        request_id=request_id,
        details={"environment": environment, "identity": reg.identity, "bundle_id": bundle_id, "previous_release_id": previous},
    )
    return Registered(release_id, bundle_id, int(revision), previous, unchanged=False)


def unroute(conn: Connection, *, target: str, environment: Environment, actor_login: str | None, request_id: str = "cli") -> str:
    """撤下路由，返回被撤下的发布 ID。没有路由时报 ``route_not_found``。"""
    actor = _member_by_login(conn, actor_login) if actor_login else None
    row = db.one(
        conn,
        "DELETE FROM release_routes WHERE target=:t AND environment=:e AND scope_key=:k RETURNING release_id",
        {"t": target, "e": environment, "k": SCOPE_KEY},
    )
    if row is None:
        raise NotFound("route_not_found", f"{target} 在 {environment} 环境没有生效的发布")
    audit.record(
        conn,
        actor_id=actor,
        project_id=None,
        action=f"{target}.unroute",
        object_kind="release",
        object_id=row["release_id"],
        request_id=request_id,
        details={"environment": environment},
    )
    return str(row["release_id"])


def _identity(components: dict[str, Any]) -> str | None:
    value = components.get("model_id") or components.get("pack_id")
    return str(value) if value else None
