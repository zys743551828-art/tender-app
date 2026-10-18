"""证据读取与检索。证据只来自已冻结快照允许的文件版本，永远可回溯到原件页码与原文。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import Connection

from bidwb import db, retrieval
from bidwb.access import Actor, require_project
from bidwb.config import Settings
from bidwb.embeddings import EmbeddingUnavailable, get_embedder
from bidwb.errors import NotFound
from bidwb.schemas import EvidenceRef, SearchHit, SearchRequest, SearchResult
from bidwb.services import vector_index

_EVIDENCE_SQL = """SELECT e.id,e.project_id,e.file_version_id,a.sha256 AS source_sha256,e.physical_page,e.printed_page,e.quote,e.kind,
       p.parser_version,e.bbox_json,e.semantic_review,f.role AS file_role,fv.original_name AS file_name
       FROM evidence e JOIN parses p ON p.id=e.parse_id JOIN file_versions fv ON fv.id=e.file_version_id AND fv.project_id=e.project_id
       JOIN files f ON f.id=fv.file_id AND f.project_id=fv.project_id JOIN artifacts a ON a.id=fv.artifact_id """


def _ref(row: db.Row) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=row["id"],
        project_id=row["project_id"],
        version_id=row["file_version_id"],
        file_role=row["file_role"],
        file_name=row["file_name"],
        source_sha256=row["source_sha256"],
        physical_page=row["physical_page"],
        printed_page=row["printed_page"],
        quote=row["quote"],
        kind=row["kind"],
        parser_version=row["parser_version"],
        bbox=row["bbox_json"],
        semantic_review=row["semantic_review"],
    )


def get_evidence(conn: Connection, actor: Actor, evidence_id: str) -> EvidenceRef:
    row = db.one(conn, _EVIDENCE_SQL + "WHERE e.id=:i", {"i": evidence_id})
    if row is None:
        raise NotFound("evidence_not_found")
    require_project(conn, actor, row["project_id"])
    return _ref(row)


def evidence_for_ids(conn: Connection, project_id: str, evidence_ids: Iterable[str]) -> list[EvidenceRef]:
    """按给定顺序返回本项目内的证据；不属于本项目的 ID 被忽略（调用方应已验权）。"""
    ids = list(dict.fromkeys(evidence_ids))
    if not ids:
        return []
    rows = db.all_(conn, _EVIDENCE_SQL + "WHERE e.project_id=:p AND e.id = ANY(:ids)", {"p": project_id, "ids": ids})
    by_id = {r["id"]: _ref(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def snapshot_version_ids(conn: Connection, project_id: str, snapshot_id: str) -> list[str]:
    rows = db.all_(
        conn,
        "SELECT file_version_id FROM snapshot_files WHERE snapshot_id=:s AND project_id=:p ORDER BY file_version_id",
        {"s": snapshot_id, "p": project_id},
    )
    return [r["file_version_id"] for r in rows]


def current_version_ids(conn: Connection, project_id: str) -> list[str]:
    """项目当前资料：每个文件的最新已提交版本（官方成绩资料不在其中，它不能进入分析）。"""
    rows = db.all_(
        conn,
        """SELECT fv.id FROM file_versions fv JOIN files f ON f.id=fv.file_id JOIN artifacts a ON a.id=fv.artifact_id
           WHERE fv.project_id=:p AND a.status='committed' AND f.role <> 'official_result'
             AND fv.id = (SELECT l.id FROM file_versions l WHERE l.file_id=fv.file_id ORDER BY l.obtained_at DESC, l.id DESC LIMIT 1)
           ORDER BY fv.id""",
        {"p": project_id},
    )
    return [r["id"] for r in rows]


def search(conn: Connection, actor: Actor, project_id: str, req: SearchRequest, settings: Settings | None = None) -> SearchResult:
    """检索证据。给了 ``snapshot_id`` 就限定在该轮固定下来的文件版本内；不给则检索项目当前资料
    （录入第一批事实时还没有任何一轮诊断，必须能直接检索）。可选 pgvector 通道缺少模型、扩展或完整索引时回退关键词。"""
    require_project(conn, actor, project_id)
    if req.snapshot_id is None:
        versions = current_version_ids(conn, project_id)
    else:
        versions = snapshot_version_ids(conn, project_id, req.snapshot_id)
        if not versions:
            raise NotFound("snapshot_not_found")
    rows = db.all_(
        conn,
        _EVIDENCE_SQL + "WHERE e.project_id=:p AND e.file_version_id = ANY(:v) ORDER BY fv.obtained_at, fv.id, e.seq, e.id",
        {"p": project_id, "v": versions},
    )
    refs: Sequence[EvidenceRef] = [_ref(r) for r in rows]
    if req.mode == "hybrid" and settings is not None and settings.retrieval_backend == "pgvector":
        try:
            if not settings.embedding_model_dir:
                raise EmbeddingUnavailable("embedding_model_not_configured")
            query = get_embedder(settings.embedding_model_dir).encode([req.query], query=True)
            dense, truncated = vector_index.dense_rank(
                conn, project_id, [(ref.evidence_id, ref.quote) for ref in refs], query.vectors[0], max(50, req.top_k)
            )
            texts = [ref.quote for ref in refs]
            fused = retrieval.reciprocal_rank_fusion(
                [retrieval.rank(req.query, texts, 50), retrieval.rank_exact(req.query, texts, 50), dense], req.top_k
            )
            gaps = (["embedding_query_truncated:查询超出模型长度"] if query.truncated[0] else []) + (
                ["embedding_documents_truncated:部分证据向量只覆盖前512个词元"] if truncated else []
            )
            return SearchResult(
                snapshot_id=req.snapshot_id,
                mode_used="hybrid",
                index_state="ready",
                hits=[SearchHit(evidence=refs[item.index], score=round(item.score, 6), channel="fused") for item in fused],
                gaps=gaps,
            )
        except EmbeddingUnavailable as exc:
            fallback_gap = f"{exc}:使用关键词通道"
    else:
        fallback_gap = "hybrid_index_unavailable:使用关键词通道"
    hits = [
        SearchHit(evidence=refs[s.index], score=round(s.score, 6), channel="keyword")
        for s in retrieval.rank(req.query, [r.quote for r in refs], req.top_k)
    ]
    gaps = [fallback_gap] if req.mode == "hybrid" else []
    return SearchResult(
        snapshot_id=req.snapshot_id,
        mode_used="keyword",
        index_state="unavailable" if req.mode == "hybrid" else "ready",
        hits=hits,
        gaps=gaps,
    )
