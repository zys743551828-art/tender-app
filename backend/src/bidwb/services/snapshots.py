"""输入快照：冻结“这次分析到底读了哪些资料、哪版规则、哪些确认过的事实”。

快照清单作为产物保存（内容寻址、不可覆盖），其 SHA-256 即快照的 ``sha256``；
任务的 ``input_sha256`` 取自它，因此 worker 提交结果时能证明自己读的是同一份输入。
"""

from __future__ import annotations

import json

from sqlalchemy import Connection

from bidwb import db, source_effectivity, term_conflicts
from bidwb.access import Actor, require_project
from bidwb.errors import Conflict, NotFound, Unprocessable
from bidwb.schemas import InputSnapshot, SnapshotRequest
from bidwb.services import audit, current_materials, rules
from bidwb.services.files import CONTRACT_VERSION
from bidwb.storage import ObjectStore, artifact_key
from bidwb.util import canonical_json, new_id, sha256_hex, utcnow

SNAPSHOT_CONTRACT = "input-v1"
TENDER_ROLES = frozenset({"tender", "supplement"})
PARSED_ROLES = frozenset(
    {"tender", "supplement", "body", "submission"}
)  # 上传后会解析的资料用途；其余用途不解析，只在 coverage_gaps 里如实标注


def _coverage_gaps(conn: Connection, project_id: str, version_ids: list[str]) -> list[str]:
    gaps: list[str] = []
    for version_id in version_ids:
        parse = db.one(
            conn,
            "SELECT coverage,gaps_json FROM parses WHERE file_version_id=:v AND project_id=:p ORDER BY created_at DESC LIMIT 1",
            {"v": version_id, "p": project_id},
        )
        if parse is None:
            gaps.append(f"{version_id}:unparsed")
        elif parse["coverage"] != "complete":
            gaps.append(f"{version_id}:{parse['coverage']}")
            gaps.extend(f"{version_id}:{g}" for g in parse["gaps_json"])
    return gaps


def _require_complete_tender_inputs(conn: Connection, project_id: str, versions: list[db.Row]) -> None:
    """快照必须含招标文件，并覆盖项目里每个招标文件/补遗的当前最新版本：漏掉补遗会让诊断基于不完整的要求。"""
    if not any(v["role"] == "tender" for v in versions):
        raise Conflict("tender_missing", "快照必须包含招标文件，没有招标文件无法核对规则")
    current = [r for r in current_materials.heads(conn, project_id) if r["role"] in TENDER_ROLES]
    chosen = {v["id"] for v in versions}
    missing = [c for c in current if c["id"] not in chosen]
    if missing:
        names = "、".join(f"“{c['original_name']}”" for c in missing)
        raise Conflict(
            "tender_inputs_incomplete",
            f"快照缺少项目当前的招标文件/补遗最新版本：{names}，请补全后再冻结",
            version_ids=[c["id"] for c in missing],
        )


def _check_material_heads(conn: Connection, project_id: str, req: SnapshotRequest, versions: list[db.Row]) -> None:
    current_ids = {r["id"] for r in current_materials.heads(conn, project_id)}
    if any(v["id"] not in current_ids for v in versions) or req.body_version_id != current_materials.active_body(conn, project_id):
        raise Conflict("stale_inputs", "原稿或实际评审 PDF 已更新，请采用当前资料后重新评审")


def _require_current_inputs(conn: Connection, project_id: str, req: SnapshotRequest, versions: list[db.Row]) -> None:
    """冻结前的“输入必须是当前最新且可用”校验：资料是各文件最新版本且已解析，规则包与事实集是最新的。"""
    stale = [f"{v['original_name']}（{v['id']}）" for v in versions if v["latest_id"] != v["id"]]
    if stale:
        raise Conflict(
            "stale_inputs",
            f"以下资料已有更新版本，请改用最新版本后再冻结：{'、'.join(stale)}",
            version_ids=[v["id"] for v in versions if v["latest_id"] != v["id"]],
        )
    _check_material_heads(conn, project_id, req, versions)
    unparsed = [v for v in versions if v["role"] in PARSED_ROLES and (v["coverage"] is None or v["coverage"] == "failed")]
    if unparsed:
        names = "、".join(f"“{v['original_name']}”" for v in unparsed)
        raise Conflict(
            "input_not_parsed",
            f"以下资料版本尚未解析成功（未解析或解析失败），不能进入输入：{names}",
            version_ids=[v["id"] for v in unparsed],
        )
    _require_complete_tender_inputs(conn, project_id, versions)
    package = rules.latest_package(conn, project_id, req.rule_set_id)
    if package is None:
        raise NotFound("rule_set_not_found")
    newest = rules.latest_package(conn, project_id)
    if newest is not None and newest["id"] != req.rule_set_id:
        raise Conflict("stale_inputs", "该规则包已被更新的规则包取代，请改用最新的规则包", rule_set_id=newest["id"])
    source_versions = sorted(v["id"] for v in versions if v["role"] in TENDER_ROLES)
    if sorted(package["source_versions_json"]) != source_versions:
        raise Conflict(
            "rules_source_mismatch",
            "该规则包提取自与本次快照不同的招标文件/补遗版本，规则可能已不适用，请基于当前资料重新提取规则并确认后再冻结",
            rule_source_version_ids=sorted(package["source_versions_json"]),
            snapshot_version_ids=source_versions,
        )
    if term_conflicts.pending(package["terms_json"]):
        raise Conflict("rule_terms_conflict", "招标文件与补遗中的投标条件存在不同候选，请到依据页核实采用哪一项后重新评审")
    package_rules = db.all_(conn, "SELECT * FROM rule_items WHERE package_id=:k AND project_id=:p", {"k": package["id"], "p": project_id})
    if source_effectivity.pending_count(package["effectivity_json"], package_rules):
        raise Conflict("source_effectivity_pending", "部分要求与补遗的替代关系尚待核实，请先到依据页处理补遗影响")
    newest_facts = db.one(conn, "SELECT id FROM fact_sets WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    if req.fact_set_id is None:
        if newest_facts is not None:
            raise Conflict(
                "fact_set_required",
                "项目已有已确认事实，快照必须带上最新的事实集，否则诊断会漏掉这些事实",
                fact_set_id=newest_facts["id"],
            )
    else:
        if db.one(conn, "SELECT 1 AS x FROM fact_sets WHERE id=:f AND project_id=:p", {"f": req.fact_set_id, "p": project_id}) is None:
            raise NotFound("fact_set_not_found")
        if newest_facts is not None and newest_facts["id"] != req.fact_set_id:
            raise Conflict("stale_inputs", "该事实集已被更新的事实集取代，请改用最新的事实集", fact_set_id=newest_facts["id"])


def freeze(conn: Connection, store: ObjectStore, actor: Actor, project_id: str, req: SnapshotRequest, request_id: str) -> InputSnapshot:
    require_project(conn, actor, project_id)
    snapshot_id = freeze_inputs(conn, store, actor.member_id, project_id, req, request_id)
    return get_snapshot(conn, actor, snapshot_id)


def check_inputs(conn: Connection, project_id: str, req: SnapshotRequest) -> list[str]:
    """冻结前的全部校验，不写任何东西；通过时返回排好序的资料版本 ID。流水线也用它解释“为什么冻结不了”。"""
    if req.reference_dataset_id is not None:
        raise Unprocessable("reference_dataset_unavailable", "参考数据集在评分研究功能交付之前不可用")
    version_ids = sorted(set(req.file_version_ids))
    if req.body_version_id not in version_ids:
        raise Unprocessable("body_not_in_snapshot", "正文版本必须包含在输入版本中")
    versions = db.all_(
        conn,
        """SELECT fv.id,fv.obtained_at,fv.original_name,f.role,a.status,
                  (SELECT l.id FROM file_versions l WHERE l.file_id=fv.file_id ORDER BY l.obtained_at DESC, l.id DESC LIMIT 1) AS latest_id,
                  (SELECT ps.coverage FROM parses ps WHERE ps.file_version_id=fv.id ORDER BY ps.created_at DESC, ps.id DESC LIMIT 1) AS coverage
           FROM file_versions fv JOIN files f ON f.id=fv.file_id JOIN artifacts a ON a.id=fv.artifact_id
           WHERE fv.project_id=:p AND fv.id = ANY(:ids)""",
        {"p": project_id, "ids": version_ids},
    )
    if len(versions) != len(version_ids):
        raise NotFound("file_not_found")
    by_id = {v["id"]: v for v in versions}
    if any(v["status"] != "committed" for v in versions):
        raise Conflict("file_not_committed", "存在尚未通过核验的文件版本")
    if by_id[req.body_version_id]["role"] != "body":
        raise Unprocessable("body_role_invalid", "正文版本的资料用途必须是“正文”")
    if any(v["role"] == "official_result" for v in versions):
        raise Unprocessable("official_result_not_allowed", "官方成绩资料不能进入分析输入")
    project = db.one(conn, "SELECT deadline FROM projects WHERE id=:p", {"p": project_id})
    if project and project["deadline"] is not None:
        effective_times = {r["id"]: r["obtained_at"] for r in current_materials.heads(conn, project_id)}
        late = [v["id"] for v in versions if effective_times.get(v["id"], v["obtained_at"]) > project["deadline"]]
        if late:
            raise Unprocessable("version_after_deadline", "存在截止后才取得的资料版本，不能进入输入", version_ids=late)
    _require_current_inputs(conn, project_id, req, versions)
    return version_ids


def freeze_inputs(
    conn: Connection, store: ObjectStore, actor_id: str | None, project_id: str, req: SnapshotRequest, request_id: str
) -> str:
    """冻结输入并返回快照 ID。授权由调用方负责；``actor_id`` 为 None 表示由自动流水线冻结（审计里记为系统）。"""
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})
    version_ids = check_inputs(conn, project_id, req)
    now = utcnow()

    gaps = _coverage_gaps(conn, project_id, version_ids)
    snapshot_id = new_id("snp")
    manifest = {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "contract_version": SNAPSHOT_CONTRACT,
        "file_version_ids": version_ids,
        "body_version_id": req.body_version_id,
        "rule_set_id": req.rule_set_id,
        "fact_set_id": req.fact_set_id,
        "as_of": now.isoformat(),
        "reference_dataset_id": None,
        "coverage_gaps": gaps,
        "word_sources": [dict(row) for row in current_materials.lineage(conn, project_id, version_ids)],
    }
    payload = canonical_json(manifest).encode()
    digest = sha256_hex(payload)
    artifact_id = new_id("art")
    key = artifact_key(artifact_id)
    store.put(key, payload, "application/json")
    db.run(
        conn,
        """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
           VALUES (:i,:sha,:k,:n,'application/json',:cv,:now,'committed')""",
        {"i": artifact_id, "sha": digest, "k": key, "n": len(payload), "cv": CONTRACT_VERSION, "now": now},
    )
    db.run(
        conn,
        """INSERT INTO input_snapshots(id,project_id,body_version_id,rule_set_id,fact_set_id,as_of,contract_version,sha256,manifest_artifact_id,word_sources_json)
           VALUES (:i,:p,:b,:r,:f,:now,:cv,:sha,:art,CAST(:word AS jsonb))""",
        {
            "i": snapshot_id,
            "p": project_id,
            "b": req.body_version_id,
            "r": req.rule_set_id,
            "f": req.fact_set_id,
            "now": now,
            "cv": SNAPSHOT_CONTRACT,
            "sha": digest,
            "art": artifact_id,
            "word": json.dumps(manifest["word_sources"]),
        },
    )
    for version_id in version_ids:
        db.run(
            conn,
            "INSERT INTO snapshot_files(snapshot_id,project_id,file_version_id) VALUES (:s,:p,:v)",
            {"s": snapshot_id, "p": project_id, "v": version_id},
        )
    audit.record(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        action="snapshot.freeze",
        object_kind="snapshot",
        object_id=snapshot_id,
        request_id=request_id,
        details={"sha256": digest, "files": len(version_ids), "automatic": actor_id is None},
    )
    return snapshot_id


def get_snapshot(conn: Connection, actor: Actor, snapshot_id: str) -> InputSnapshot:
    row = db.one(conn, "SELECT * FROM input_snapshots WHERE id=:i", {"i": snapshot_id})
    if row is None:
        raise NotFound("snapshot_not_found")
    require_project(conn, actor, row["project_id"])
    files = db.all_(conn, "SELECT file_version_id FROM snapshot_files WHERE snapshot_id=:s ORDER BY file_version_id", {"s": snapshot_id})
    gaps = _coverage_gaps(conn, row["project_id"], [f["file_version_id"] for f in files])
    return InputSnapshot(
        snapshot_id=row["id"],
        project_id=row["project_id"],
        contract_version=SNAPSHOT_CONTRACT,
        file_version_ids=[f["file_version_id"] for f in files],
        body_version_id=row["body_version_id"],
        rule_set_id=row["rule_set_id"],
        fact_set_id=row["fact_set_id"],
        as_of=row["as_of"],
        reference_dataset_id=None,
        coverage_gaps=gaps,
        sha256=row["sha256"],
        word_sources=row["word_sources_json"],
    )


def list_snapshots(conn: Connection, actor: Actor, project_id: str) -> list[InputSnapshot]:
    require_project(conn, actor, project_id)
    rows = db.all_(conn, "SELECT id FROM input_snapshots WHERE project_id=:p ORDER BY as_of DESC, id DESC", {"p": project_id})
    return [get_snapshot(conn, actor, r["id"]) for r in rows]


def manifest_json(store: ObjectStore, conn: Connection, snapshot_id: str) -> dict[str, object]:
    """读取并校验快照清单产物（字节校验值必须等于库内 sha256），供 worker 与审计使用。"""
    row = db.one(
        conn,
        "SELECT s.sha256,a.object_key FROM input_snapshots s JOIN artifacts a ON a.id=s.manifest_artifact_id WHERE s.id=:i",
        {"i": snapshot_id},
    )
    if row is None:
        raise NotFound("snapshot_not_found")
    data = store.get(row["object_key"])
    if sha256_hex(data) != row["sha256"]:
        raise Conflict("snapshot_manifest_corrupt", "快照清单与登记的校验值不一致")
    loaded = json.loads(data)
    assert isinstance(loaded, dict)
    return loaded
