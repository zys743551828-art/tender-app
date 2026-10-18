"""显式构建派生向量；查询仅用经权限、项目和版本过滤的证据 ID，不在搜索请求内建索引。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from bidwb import db
from bidwb.embeddings import MODEL_FINGERPRINT, EmbeddingUnavailable, Encoded, LocalEmbedder, get_embedder, validate_vector
from bidwb.retrieval import Scored


def quote_digest(quote: str) -> str:
    return hashlib.sha256(quote.encode()).hexdigest()


def prepare(model_dir: str, texts: Sequence[str], checkpoint: Callable[[], None]) -> Encoded:
    embedder = get_embedder(model_dir)
    vectors: list[list[float]] = []
    truncated: list[bool] = []
    for start in range(0, len(texts), 32):
        checkpoint()
        encoded = embedder.encode(texts[start : start + 32])
        vectors.extend(encoded.vectors)
        truncated.extend(encoded.truncated)
    checkpoint()
    return Encoded(vectors, truncated)


def store(conn: Connection, project_id: str, evidence: Sequence[tuple[str, str]], encoded: Encoded) -> None:
    if not evidence:
        return
    if encoded.model_fingerprint != MODEL_FINGERPRINT:
        raise EmbeddingUnavailable("embedding_fingerprint_mismatch")
    for vector in encoded.vectors:
        validate_vector(vector)
    conn.execute(
        text("""INSERT INTO evidence_embeddings(evidence_id,project_id,model_fingerprint,quote_sha256,embedding,truncated)
                VALUES (:id,:p,:m,:h,:v,:t)
                ON CONFLICT(evidence_id,model_fingerprint) DO UPDATE
                SET quote_sha256=EXCLUDED.quote_sha256,embedding=EXCLUDED.embedding,truncated=EXCLUDED.truncated,
                    created_at=now()"""),
        [
            {"id": item[0], "p": project_id, "m": MODEL_FINGERPRINT, "h": quote_digest(item[1]), "v": vector, "t": truncated}
            for item, vector, truncated in zip(evidence, encoded.vectors, encoded.truncated, strict=True)
        ],
    )


def rebuild(engine: Engine, project_id: str, embedder: LocalEmbedder) -> int:
    """运维／worker 角色按项目回填，每批提交可安全重跑；不索引官方成绩资料。"""
    with engine.connect() as conn:
        rows = db.all_(
            conn,
            """SELECT e.id,e.quote FROM evidence e
               JOIN file_versions fv ON fv.id=e.file_version_id AND fv.project_id=e.project_id
               JOIN files f ON f.id=fv.file_id AND f.project_id=fv.project_id
               WHERE e.project_id=:p AND f.role <> 'official_result' ORDER BY e.id""",
            {"p": project_id},
        )
    for start in range(0, len(rows), 32):
        batch = rows[start : start + 32]
        encoded = embedder.encode([row["quote"] for row in batch])
        with engine.begin() as conn:
            store(conn, project_id, [(row["id"], row["quote"]) for row in batch], encoded)
    return len(rows)


def dense_rank(
    conn: Connection, project_id: str, evidence: Sequence[tuple[str, str]], query_vector: Sequence[float], top_k: int
) -> tuple[list[Scored], bool]:
    """先物化允许范围再精确余弦排序；缺块／旧模型／错文本哈希时整路回退。"""
    validate_vector(query_vector)
    if not evidence:
        return [], False
    ids = [item[0] for item in evidence]
    positions = {item[0]: i for i, item in enumerate(evidence)}
    hashes = {item[0]: quote_digest(item[1]) for item in evidence}
    try:
        # 扩展缺失或索引损坏不能让调用方的读事务进入 aborted 状态。
        with conn.begin_nested():
            if not db.scalar(conn, "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')"):
                raise EmbeddingUnavailable("hybrid_extension_unavailable")
            indexed = db.all_(
                conn,
                """SELECT evidence_id,quote_sha256,truncated FROM evidence_embeddings
                   WHERE project_id=:p AND model_fingerprint=:m AND evidence_id=ANY(:ids)""",
                {"p": project_id, "m": MODEL_FINGERPRINT, "ids": ids},
            )
            if len(indexed) != len(ids) or any(hashes[row["evidence_id"]] != row["quote_sha256"] for row in indexed):
                raise EmbeddingUnavailable("hybrid_index_incomplete")
            vector_text = "[" + ",".join(str(float(value)) for value in query_vector) + "]"
            rows = db.all_(
                conn,
                """WITH allowed AS MATERIALIZED (
                     SELECT evidence_id,embedding FROM evidence_embeddings
                     WHERE project_id=:p AND model_fingerprint=:m AND evidence_id=ANY(:ids))
                   SELECT evidence_id,1-(embedding::vector(512) <=> CAST(:q AS vector(512))) AS score
                   FROM allowed ORDER BY embedding::vector(512) <=> CAST(:q AS vector(512)),evidence_id LIMIT :k""",
                {"p": project_id, "m": MODEL_FINGERPRINT, "ids": ids, "q": vector_text, "k": top_k},
            )
        return [Scored(positions[row["evidence_id"]], float(row["score"])) for row in rows], any(row["truncated"] for row in indexed)
    except SQLAlchemyError as exc:
        raise EmbeddingUnavailable("hybrid_index_unavailable") from exc
