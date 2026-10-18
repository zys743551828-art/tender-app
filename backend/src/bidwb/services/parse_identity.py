"""冻结解析与证据集合；旧快照缺少精确身份时拒绝重放，不根据时间猜测。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection

from bidwb import db
from bidwb.errors import Conflict, NotFound


def capture(conn: Connection, project_id: str, version_ids: Sequence[str]) -> tuple[dict[str, Any], list[str]]:
    """一个语句读取解析及证据，保证同一次数据库可见性；空解析也有明确记录。"""
    rows = db.all_(
        conn,
        """SELECT fv.id,p.id AS parse_id,p.page_count,p.coverage,p.gaps_json,
                  COALESCE((SELECT jsonb_agg(e.id ORDER BY e.seq,e.id) FROM evidence e
                    WHERE e.parse_id=p.id AND e.project_id=fv.project_id AND e.file_version_id=fv.id),'[]'::jsonb) AS evidence_ids
           FROM file_versions fv LEFT JOIN LATERAL (
             SELECT id,page_count,coverage,gaps_json FROM parses
             WHERE file_version_id=fv.id AND project_id=fv.project_id ORDER BY created_at DESC,id DESC LIMIT 1
           ) p ON true WHERE fv.project_id=:p AND fv.id=ANY(:v) ORDER BY fv.id""",
        {"p": project_id, "v": list(version_ids)},
    )
    inputs: dict[str, Any] = {}
    gaps: list[str] = []
    for row in rows:
        identity = row["id"]
        inputs[identity] = {"parse_id": row["parse_id"], "page_count": row["page_count"], "evidence_ids": row["evidence_ids"]}
        if row["parse_id"] is None:
            gaps.append(f"{identity}:unparsed")
        elif row["coverage"] != "complete":
            gaps.append(f"{identity}:{row['coverage']}")
            gaps.extend(f"{identity}:{gap}" for gap in row["gaps_json"])
    return inputs, gaps


def frozen(conn: Connection, project_id: str, snapshot_id: str) -> dict[str, Any]:
    row = db.one(conn, "SELECT parse_inputs_json FROM input_snapshots WHERE id=:s AND project_id=:p", {"s": snapshot_id, "p": project_id})
    if row is None:
        raise NotFound("snapshot_not_found")
    if row["parse_inputs_json"] is None:
        raise Conflict("snapshot_parse_identity_unknown", "该历史快照未冻结解析与证据身份，请保留原报告并发起新版评审")
    return dict(row["parse_inputs_json"])


def evidence_ids(conn: Connection, project_id: str, snapshot_id: str, version_ids: Sequence[str]) -> list[str]:
    inputs = frozen(conn, project_id, snapshot_id)
    return [identity for version in version_ids for identity in inputs.get(version, {}).get("evidence_ids", [])]


def is_current(conn: Connection, project_id: str, snapshot_id: str) -> bool:
    row = db.one(conn, "SELECT parse_inputs_json FROM input_snapshots WHERE id=:s AND project_id=:p", {"s": snapshot_id, "p": project_id})
    if row is None or row["parse_inputs_json"] is None:
        return False
    current, _ = capture(conn, project_id, sorted(row["parse_inputs_json"]))
    return bool(current == row["parse_inputs_json"])


def require_fact_evidence_current(conn: Connection, project_id: str, fact_set_id: str | None) -> None:
    if fact_set_id is None:
        return
    facts = db.all_(
        conn,
        """SELECT f.id,f.name,e.id AS evidence_id,e.quote FROM fact_items f JOIN evidence e
        ON e.project_id=f.project_id AND f.evidence_ids_json ? e.id
        WHERE f.project_id=:p AND f.fact_set_id=:f AND f.confirmation='confirmed'""",
        {"p": project_id, "f": fact_set_id},
    )
    if not facts:
        return
    edges: dict[str, str] = {}
    for row in db.all_(conn, "SELECT evidence_map_json FROM recognition_reviews WHERE project_id=:p", {"p": project_id}):
        edges.update(row["evidence_map_json"])
    changed: set[str] = set()
    for fact in facts:
        identity = fact["evidence_id"]
        seen: set[str] = set()
        while identity in edges and identity not in seen:
            seen.add(identity)
            identity = edges[identity]
        if identity == fact["evidence_id"]:
            continue
        result = db.one(conn, "SELECT quote,semantic_review FROM evidence WHERE id=:i AND project_id=:p", {"i": identity, "p": project_id})
        if result is None or result["quote"] != fact["quote"] or result["semantic_review"] == "unsupported":
            changed.add(fact["name"])
    if changed:
        raise Conflict("recognition_facts_stale", "核验订正影响已确认事实，请到依据页核对并登记新的事实集", fact_names=sorted(changed))
