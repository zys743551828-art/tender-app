"""候选核验追加新解析，原证据、旧输入和历史决定保持。"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from bidwb import db
from bidwb.access import Actor
from bidwb.errors import Conflict, NotFound, Unprocessable
from bidwb.schemas import RecognitionCandidates, RecognitionReview, RecognitionReviewRequest, TableContinuation, TableStructurePreview
from bidwb.services import audit, current_materials, evidence, files, pipeline
from bidwb.services.files import CONTRACT_VERSION
from bidwb.storage import ObjectStore, artifact_key
from bidwb.util import canonical_json, new_id, sha256_hex, utcnow, xml_safe

PARSER = "human-verified-1"
PAGE_SIZE = 20
MAX_EVIDENCE = 20000


def table_preview(
    conn: Connection,
    store: ObjectStore,
    actor: Actor,
    version_id: str,
    table_index: int = 0,
    row_offset: int = 0,
    expected_parse_id: str | None = None,
) -> TableStructurePreview:
    version = files.get_version(conn, actor, version_id)
    parse = _latest(conn, version.project_id, version_id)
    if expected_parse_id is not None and (parse is None or expected_parse_id != parse["id"]):
        raise Conflict("recognition_parse_stale", "识别依据已有变化，请刷新候选后重新核对")
    result = TableStructurePreview(
        version_id=version_id,
        parse_id=parse["id"] if parse else None,
        state="not_evaluated",
        table_count=0,
        table_index=table_index,
        row_offset=row_offset,
    )
    if parse is None or parse["artifact_id"] is None:
        return result
    artifact = db.one(conn, "SELECT object_key,sha256 FROM artifacts WHERE id=:i", {"i": parse["artifact_id"]})
    if artifact is None:
        return result
    payload = store.get(artifact["object_key"])
    if sha256_hex(payload) != artifact["sha256"]:
        raise Conflict("recognition_artifact_corrupt", "原解析产物校验失败，无法展示结构候选")
    summary = json.loads(payload)
    catalog = summary.get("table_structures") if isinstance(summary, dict) else None
    if not isinstance(catalog, dict) or catalog.get("schema") != "table-candidates-1":
        return result
    tables = catalog["tables"]
    result.state, result.table_count = "candidate_preview", len(tables)
    result.issues = ["original_structure_not_verified", "selected_pages_only"]
    if table_index >= len(tables):
        return result
    selected = tables[table_index]
    rows = selected["rows"]
    indices = selected.get("cell_line_indices")
    result.table_id = selected["table_id"]
    result.physical_page = selected["physical_page"]
    result.source = selected.get("source", "native_table")
    result.bbox = selected["bbox"]
    result.row_count = len(rows)
    result.rows = rows[row_offset : row_offset + PAGE_SIZE]
    result.next_row_offset = row_offset + PAGE_SIZE if row_offset + PAGE_SIZE < len(rows) else None
    result.cell_line_indices = indices[row_offset : row_offset + PAGE_SIZE] if indices is not None else None
    result.unassigned_line_indices = selected.get("unassigned_line_indices", [])
    result.column_boundaries = selected.get("column_boundaries")
    result.row_boundaries = selected.get("row_boundaries")
    result.issues.extend(selected.get("issues", []))
    result.continuations = [
        TableContinuation.model_validate(link)
        for link in catalog.get("cross_page_candidates", [])
        if selected["table_id"] in (link["from_table_id"], link["to_table_id"])
    ]
    return TableStructurePreview.model_validate(result.model_dump())


def numbers_required(quote: str) -> bool:
    return any(c.isdigit() or c in "零〇一二两三四五六七八九十百千万亿%‰" for c in quote)


def _current(conn: Connection, project_id: str, version_id: str, role: str) -> bool:
    return version_id in {row["id"] for row in current_materials.heads(conn, project_id)} and (
        role != "body" or current_materials.active_body(conn, project_id) == version_id
    )


def _running(conn: Connection, project_id: str, version_id: str) -> bool:
    return bool(
        db.scalar(
            conn,
            """SELECT EXISTS(SELECT 1 FROM jobs WHERE project_id=:p AND kind='parse'
        AND input_json->>'file_version_id'=:v AND state IN ('queued','running','waiting_input','cancel_requested'))""",
            {"p": project_id, "v": version_id},
        )
    )


def _latest(conn: Connection, project_id: str, version_id: str) -> db.Row | None:
    return db.one(
        conn,
        "SELECT * FROM parses WHERE project_id=:p AND file_version_id=:v ORDER BY created_at DESC,id DESC LIMIT 1",
        {"p": project_id, "v": version_id},
    )


def _review(conn: Connection, review_id: str) -> RecognitionReview:
    row = db.one(
        conn,
        """SELECT r.*,e.quote AS original_quote,n.quote AS result_quote,m.display_name FROM recognition_reviews r
        JOIN evidence e ON e.id=r.source_evidence_id JOIN evidence n ON n.id=r.result_evidence_id
        JOIN members m ON m.id=r.actor_id WHERE r.id=:i""",
        {"i": review_id},
    )
    if row is None:
        raise NotFound("recognition_review_not_found")
    return RecognitionReview(
        review_id=row["id"],
        parent_parse_id=row["parent_parse_id"],
        result_parse_id=row["result_parse_id"],
        source_evidence_id=row["source_evidence_id"],
        result_evidence_id=row["result_evidence_id"],
        decision=row["decision"],
        original_quote=row["original_quote"],
        result_quote=row["result_quote"],
        reason=row["reason"],
        actor_name=row["display_name"],
        created_at=row["created_at"],
    )


def candidates(conn: Connection, actor: Actor, version_id: str, offset: int = 0) -> RecognitionCandidates:
    version = files.get_version(conn, actor, version_id)
    parse = _latest(conn, version.project_id, version_id)
    rows = db.all_(
        conn,
        "SELECT id,semantic_review FROM evidence WHERE project_id=:p AND parse_id=:r AND kind<>'text' ORDER BY seq,id",
        {"p": version.project_id, "r": parse["id"] if parse else None},
    )
    history = db.all_(
        conn,
        "SELECT id FROM recognition_reviews WHERE project_id=:p AND file_version_id=:v ORDER BY created_at DESC,id DESC LIMIT 20",
        {"p": version.project_id, "v": version_id},
    )
    return RecognitionCandidates(
        version_id=version_id,
        parse_id=parse["id"] if parse else None,
        can_review=bool(
            parse
            and version.role != "official_result"
            and _current(conn, version.project_id, version_id, version.role)
            and not _running(conn, version.project_id, version_id)
        ),
        coverage_gaps=list(parse["gaps_json"]) if parse else ["unparsed"],
        total=len(rows),
        pending_count=sum(row["semantic_review"] == "pending" for row in rows),
        offset=offset,
        next_offset=offset + PAGE_SIZE if offset + PAGE_SIZE < len(rows) else None,
        items=evidence.evidence_for_ids(conn, version.project_id, [row["id"] for row in rows[offset : offset + PAGE_SIZE]], annotate=False),
        history=[_review(conn, row["id"]) for row in history],
    )


def _gaps(parent: db.Row, rows: list[dict[str, Any]]) -> list[str]:
    gaps = list(parent["gaps_json"])
    candidates_pending = any(row["kind"] != "text" and row["semantic_review"] == "pending" for row in rows)
    covered = {row["physical_page"] for row in rows if row["kind"] == "text" or row["semantic_review"] == "supported"}
    all_pages = bool(parent["page_count"] and covered >= set(range(1, parent["page_count"] + 1)))
    if not any(row["kind"] == "text" for row in rows):
        gaps = [gap for gap in gaps if gap != "recognition_verification_required"]
        if candidates_pending or not all_pages:
            gaps.append("recognition_verification_required")
    if not candidates_pending:
        gaps = [gap for gap in gaps if gap != "recognition_candidates_pending"]
        if all_pages:
            gaps = [gap for gap in gaps if gap != "recognition_verification_required"]
    return list(dict.fromkeys([*gaps, "human_verified_candidates_partial"]))


def _derive(
    conn: Connection,
    store: ObjectStore,
    project_id: str,
    version_id: str,
    parent: db.Row,
    rows: list[dict[str, Any]],
    selected: dict[str, Any],
    req: RecognitionReviewRequest,
    actor: Actor,
) -> str:
    review_id, parse_id, art_id = new_id("rcv"), new_id("prs"), new_id("art")
    mapping = {row["id"]: new_id("evd") for row in rows}
    result_id = mapping[selected["id"]]
    selected["quote"] = req.corrected_quote if req.decision == "correct" else selected["quote"]
    selected["semantic_review"] = "unsupported" if req.decision == "reject" else "supported"
    gaps = _gaps(parent, rows)
    source = (
        db.scalar(conn, "SELECT object_key FROM artifacts WHERE id=:i", {"i": parent["artifact_id"]}) if parent["artifact_id"] else None
    )
    raw = store.get(source) if source else b"{}"
    expected = db.scalar(conn, "SELECT sha256 FROM artifacts WHERE id=:i", {"i": parent["artifact_id"]}) if source else None
    if expected is not None and sha256_hex(raw) != expected:
        raise Conflict("recognition_artifact_corrupt", "原解析产物校验失败，无法核验")
    summary = json.loads(raw)
    if not isinstance(summary, dict):
        raise Conflict("recognition_artifact_corrupt", "原解析产物结构不完整，无法核验")
    summary.update(
        {
            "parser_version": PARSER,
            "parent_parse_id": parent["id"],
            "review_id": review_id,
            "evidence_map": mapping,
            "coverage": "partial",
            "gaps": gaps,
            "human_reviewed_evidence_id": result_id,
            "decision": req.decision,
            "source_evidence_id": req.evidence_id,
            "reviewed_quote": selected["quote"],
            "retrieval_index": {"state": "needs_rebuild"},
        }
    )
    payload = canonical_json(summary).encode()
    key = artifact_key(art_id)
    store.put(key, payload, "application/json")
    now = utcnow()
    db.run(
        conn,
        """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
        VALUES (:i,:sha,:k,:n,'application/json',:cv,:now,'committed')""",
        {"i": art_id, "sha": sha256_hex(payload), "k": key, "n": len(payload), "cv": CONTRACT_VERSION, "now": now},
    )
    db.run(
        conn,
        """INSERT INTO parses(id,project_id,file_version_id,parser_version,page_count,coverage,gaps_json,artifact_id,created_at)
        VALUES (:i,:p,:v,:pv,:n,'partial',CAST(:g AS jsonb),:a,:now)""",
        {
            "i": parse_id,
            "p": project_id,
            "v": version_id,
            "pv": PARSER,
            "n": parent["page_count"],
            "g": json.dumps(gaps),
            "a": art_id,
            "now": max(now, parent["created_at"] + timedelta(microseconds=1)),
        },
    )
    conn.execute(
        text("""INSERT INTO evidence(id,project_id,file_version_id,parse_id,physical_page,printed_page,quote,kind,seq,bbox_json,semantic_review)
        VALUES (:i,:p,:v,:r,:page,:printed,:quote,:kind,:seq,CAST(:bbox AS jsonb),:state)"""),
        [
            {
                "i": mapping[row["id"]],
                "p": project_id,
                "v": version_id,
                "r": parse_id,
                "page": row["physical_page"],
                "printed": row["printed_page"],
                "quote": row["quote"],
                "kind": row["kind"],
                "seq": row["seq"],
                "bbox": json.dumps(row["bbox_json"]),
                "state": row["semantic_review"],
            }
            for row in rows
        ],
    )
    db.run(
        conn,
        """INSERT INTO recognition_reviews(id,project_id,file_version_id,parent_parse_id,result_parse_id,source_evidence_id,result_evidence_id,
        decision,reason,actor_id,reviewed_original,reviewed_numbers,evidence_map_json,created_at)
        VALUES (:i,:p,:v,:parent,:result,:source,:e,:d,:reason,:actor,true,:numbers,CAST(:map AS jsonb),:now)""",
        {
            "i": review_id,
            "p": project_id,
            "v": version_id,
            "parent": parent["id"],
            "result": parse_id,
            "source": req.evidence_id,
            "e": result_id,
            "d": req.decision,
            "reason": req.reason,
            "actor": actor.member_id,
            "numbers": req.reviewed_numbers,
            "map": json.dumps(mapping),
            "now": now,
        },
    )
    return review_id


def review(
    conn: Connection, store: ObjectStore, actor: Actor, version_id: str, req: RecognitionReviewRequest, request_id: str
) -> RecognitionReview:
    version = files.get_version(conn, actor, version_id)
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": version.project_id})
    if version.role == "official_result" or not _current(conn, version.project_id, version_id, version.role):
        raise Conflict("recognition_source_stale", "请在当前采用的资料版本上核验")
    if _running(conn, version.project_id, version_id):
        raise Conflict("recognition_parse_running", "该资料仍有解析任务，请等待完成后重新查看候选")
    parent = _latest(conn, version.project_id, version_id)
    if parent is None or parent["id"] != req.expected_parse_id:
        raise Conflict("recognition_parse_stale", "识别依据已有变化，请刷新候选后重新核对")
    rows = [
        dict(row)
        for row in db.all_(
            conn,
            "SELECT * FROM evidence WHERE project_id=:p AND parse_id=:r ORDER BY seq,id LIMIT :limit",
            {"p": version.project_id, "r": parent["id"], "limit": MAX_EVIDENCE + 1},
        )
    ]
    if len(rows) > MAX_EVIDENCE:
        raise Conflict("recognition_review_too_large", "该资料证据量超出单次核验上限，请拆分资料")
    selected = next((row for row in rows if row["id"] == req.evidence_id and row["kind"] != "text"), None)
    if selected is None:
        raise NotFound("recognition_candidate_not_found")
    if not req.reviewed_original:
        raise Unprocessable("recognition_original_not_reviewed", "请先对照原页核对该候选")
    if xml_safe(req.reason) != req.reason:
        raise Unprocessable("recognition_reason_invalid", "核验说明不能包含无效控制字符")
    if req.decision == "correct":
        if req.corrected_quote is None or req.corrected_quote == selected["quote"] or xml_safe(req.corrected_quote) != req.corrected_quote:
            raise Unprocessable("recognition_correction_invalid", "订正内容须与当前摘录不同，且不能包含无效控制字符")
    elif req.corrected_quote is not None:
        raise Unprocessable("recognition_unexpected_correction", "仅订正操作可以提交新的摘录")
    if req.decision != "reject" and numbers_required(selected["quote"] + (req.corrected_quote or "")) and not req.reviewed_numbers:
        raise Unprocessable("recognition_numbers_not_reviewed", "请单独核对数字、符号与单位")
    identity = _derive(conn, store, version.project_id, version_id, parent, rows, selected, req, actor)
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=version.project_id,
        action="recognition.review",
        object_kind="recognition_review",
        object_id=identity,
        request_id=request_id,
        details={"decision": req.decision, "parent_parse_id": parent["id"], "source_evidence_id": req.evidence_id},
    )
    db.run(conn, "UPDATE projects SET revision=revision+1 WHERE id=:p", {"p": version.project_id})
    pipeline.settle(conn, version.project_id)
    return _review(conn, identity)
