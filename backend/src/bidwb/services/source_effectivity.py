"""补遗条款效力：先预览范围，再由人带原文决定，追加新包并保留历史。"""

from __future__ import annotations

import copy
import hashlib

from botocore.exceptions import BotoCoreError
from sqlalchemy import Connection

from bidwb import db, retrieval
from bidwb import source_effectivity as effectivity
from bidwb.access import Actor, require_project
from bidwb.ai.sections import build_sections
from bidwb.checks import Passage
from bidwb.errors import Conflict, NotFound, PreconditionFailed, Unavailable, Unprocessable
from bidwb.schemas import (
    AffectedSection,
    EffectivityDecision,
    EffectivityPreview,
    EffectivityPreviewRequest,
    EffectivityRequest,
    EvidenceRef,
    RuleSet,
)
from bidwb.services import audit, current_materials, evidence, rules
from bidwb.storage import ObjectStore, ObjectStoreError
from bidwb.util import new_id


def _scope(
    conn: Connection, project_id: str, request: EffectivityPreviewRequest
) -> tuple[db.Row, list[db.Row], list[db.Row], list[db.Row]]:
    package = rules.latest_package(conn, project_id)
    if package is None:
        raise NotFound("rules_not_extracted")
    if request.object_version != str(package["revision"]):
        raise PreconditionFailed("stale_version", "规则包已有更新，请重新查看补遗影响")
    if sorted(package["source_versions_json"]) != rules.current_tender_version_ids(conn, project_id):
        raise PreconditionFailed("stale_inputs", "招标文件或补遗已有更新，请先等待当前规则提取完成")
    if request.old_version_id == request.new_version_id:
        raise Unprocessable("effectivity_same_source", "请选择不同的原资料和补遗")
    versions = db.all_(
        conn,
        """SELECT fv.id,f.role,a.object_key,a.sha256,a.byte_size,a.status
           FROM file_versions fv JOIN files f ON f.id=fv.file_id AND f.project_id=fv.project_id
           JOIN artifacts a ON a.id=fv.artifact_id WHERE fv.project_id=:p AND fv.id=ANY(:ids)""",
        {"p": project_id, "ids": [request.old_version_id, request.new_version_id]},
    )
    by_id = {row["id"]: row for row in versions}
    if len(versions) != 2 or any(row["id"] not in package["source_versions_json"] for row in versions):
        raise NotFound("effectivity_source_not_found")
    if by_id[request.new_version_id]["role"] != "supplement":
        raise Unprocessable("effectivity_supplement_required", "新依据必须是当前补遗资料")
    all_rules = db.all_(
        conn, "SELECT * FROM rule_items WHERE package_id=:k AND project_id=:p ORDER BY id", {"k": package["id"], "p": project_id}
    )
    rule_ids = [item["id"] for item in all_rules]
    bindings = db.all_(
        conn,
        """SELECT r.id,e.file_version_id FROM rule_items r
           JOIN evidence e ON e.project_id=r.project_id AND r.evidence_ids_json ? e.id
           WHERE r.project_id=:p AND r.id=ANY(:ids)""",
        {"p": project_id, "ids": rule_ids},
    )
    sources: dict[str, set[str]] = {}
    for row in bindings:
        sources.setdefault(row["id"], set()).add(row["file_version_id"])
    eligible = [item for item in all_rules if request.old_version_id in sources.get(item["id"], set())]
    selected = set(request.rule_ids)
    if request.action == "whole_replace":
        if selected:
            raise Unprocessable("effectivity_whole_scope", "整份替代由系统列出所有原资料条款，无需混用局部选择")
        affected = eligible
    else:
        if not selected or not selected <= {item["id"] for item in eligible}:
            raise Unprocessable("effectivity_rule_scope", "请选择原资料对应的当前条款，不能选择其他资料或旧包的条款")
        affected = [item for item in eligible if item["id"] in selected]
    if not affected:
        raise Unprocessable("effectivity_no_rules", "原资料没有可对应的当前条款，请核对来源")
    mixed = [item for item in affected if sources[item["id"]] != {request.old_version_id}]
    return package, affected, mixed, versions


def _related_sections(conn: Connection, project_id: str, affected: list[db.Row]) -> list[AffectedSection]:
    version = current_materials.active_body(conn, project_id)
    if version is None:
        return []
    rows = db.all_(
        conn,
        """SELECT id,physical_page,quote FROM evidence WHERE project_id=:p AND file_version_id=:v
           AND (kind='text' OR semantic_review='supported') ORDER BY seq,id""",
        {"p": project_id, "v": version},
    )
    sections = build_sections([Passage(row["id"], row["physical_page"], row["quote"]) for row in rows])
    by_id = {row["id"]: row["quote"] for row in rows}
    texts = ["\n".join(by_id[identity] for identity in section.evidence_ids) for section in sections]
    ranked = retrieval.rank("\n".join(item["statement"] for item in affected), texts, 5)
    return [
        AffectedSection(
            title=sections[item.index].label, evidence=evidence.evidence_for_ids(conn, project_id, sections[item.index].evidence_ids[:3])
        )
        for item in ranked
    ]


def preview(conn: Connection, actor: Actor, project_id: str, request: EffectivityPreviewRequest) -> EffectivityPreview:
    require_project(conn, actor, project_id)
    package, affected, mixed, _ = _scope(conn, project_id, request)
    return EffectivityPreview(
        rule_set_id=package["id"],
        revision=package["revision"],
        affected_rule_ids=[item["id"] for item in affected],
        mixed_source_rule_ids=[item["id"] for item in mixed],
        related_sections=_related_sections(conn, project_id, affected),
        gaps=["章节仅按当前正文关键词相关性列出，需人工核实；未命中不证明没有影响"],
    )


def source_evidence(conn: Connection, actor: Actor, project_id: str, version_id: str, query: str = "") -> list[EvidenceRef]:
    require_project(conn, actor, project_id)
    if version_id not in rules.current_tender_version_ids(conn, project_id):
        raise NotFound("effectivity_source_not_found")
    rows = db.all_(
        conn,
        evidence._EVIDENCE_SQL
        + "WHERE e.project_id=:p AND e.file_version_id=:v AND (e.kind='text' OR e.semantic_review='supported') ORDER BY e.seq,e.id",
        {"p": project_id, "v": version_id},
    )
    positions = (
        [item.index for item in retrieval.rank(query, [row["quote"] for row in rows], 30)]
        if query.strip()
        else list(range(min(30, len(rows))))
    )
    return [evidence._ref(rows[index]) for index in positions]


def _verify_basis(conn: Connection, project_id: str, request: EffectivityRequest) -> None:
    if request.action != "defer" and not request.scope_basis:
        raise Unprocessable("effectivity_basis_required", "请选取补遗原文中的替代范围依据")
    for basis in request.scope_basis:
        row = db.one(
            conn,
            "SELECT file_version_id,quote,kind,semantic_review FROM evidence WHERE id=:i AND project_id=:p",
            {"i": basis.evidence_id, "p": project_id},
        )
        if (
            row is None
            or row["file_version_id"] != request.new_version_id
            or basis.quote not in row["quote"]
            or (row["kind"] != "text" and row["semantic_review"] != "supported")
        ):
            raise Unprocessable("effectivity_basis_invalid", "效力依据必须逐字来自所选补遗的已可用原页证据")
        if request.action == "whole_replace" and any(marker in row["quote"] for marker in effectivity.LOCAL_SCOPE_MARKERS):
            raise Unprocessable("effectivity_local_scope", "原文包含局部修改或其余不变说明，不能据此确认整份替代")


def _verify_originals(store: ObjectStore, versions: list[db.Row]) -> None:
    for version in versions:
        if version["status"] != "committed":
            raise Conflict("effectivity_source_uncommitted", "效力依据原件尚未通过校验")
        try:
            data = store.get(version["object_key"])
        except (ObjectStoreError, BotoCoreError) as exc:
            raise Unavailable("effectivity_original_unavailable", "原件暂时无法读取，请稍后重试") from exc
        if len(data) != version["byte_size"] or hashlib.sha256(data).hexdigest() != version["sha256"]:
            raise Conflict("effectivity_original_mismatch", "效力依据原件字节校验不符，不能确认替代")


def decide(conn: Connection, store: ObjectStore, actor: Actor, project_id: str, request: EffectivityRequest, request_id: str) -> RuleSet:
    require_project(conn, actor, project_id)
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})
    package, affected, mixed, versions = _scope(conn, project_id, request)
    _verify_basis(conn, project_id, request)
    _verify_originals(store, versions)
    mixed_ids = {item["id"] for item in mixed}
    pending = affected if request.action == "defer" else mixed if request.action == "whole_replace" else []
    ended = (
        [item for item in affected if item["id"] not in mixed_ids]
        if request.action == "whole_replace"
        else affected
        if request.action == "partial_replace"
        else []
    )
    decision_id = new_id("sfx")
    decision = EffectivityDecision(
        decision_id=decision_id,
        old_version_id=request.old_version_id,
        new_version_id=request.new_version_id,
        action=request.action,
        reason=request.reason,
        scope_basis=request.scope_basis,
        ended_rule_ids=[item["id"] for item in ended],
        pending_rule_ids=[item["id"] for item in pending],
    )
    updated = copy.deepcopy(package["effectivity_json"])
    for item in affected:
        key = effectivity.rule_key(item)
        updated.setdefault("pending", {}).pop(key, None)
        if request.action == "retain":
            updated.setdefault("ended", {}).pop(key, None)
    for name, items in (("ended", ended), ("pending", pending)):
        for item in items:
            updated.setdefault(name, {})[effectivity.rule_key(item)] = decision_id
    updated.setdefault("decisions", []).append(decision.model_dump(mode="json"))
    new_package, _ = rules._clone_package(conn, project_id, package, effectivity=updated)
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="source.effectivity_decided",
        object_kind="rule_package",
        object_id=new_package,
        request_id=request_id,
        details={"from_package": package["id"], **decision.model_dump(mode="json")},
    )
    return rules.get_rules(conn, actor, project_id)
