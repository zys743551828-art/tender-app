"""Data-only stages for API retrieval; model HTTP runs after each DB connection closes."""

import hashlib
import math
from uuid import uuid4, uuid5

from psycopg import sql
from psycopg.types.json import Jsonb

from packages.rag.core import fuse_rankings
from packages.rag.numeric import numeric_patterns
from packages.rag.repository import source_scope_digest


def candidates(c, scope, profile_id, vector, lexemes, excluded_evidence_ids=(), *, query=""):
    foreign = c.execute(
        "SELECT n.id FROM retrieval.source_nodes n LEFT JOIN design.document_versions v ON v.id=n.document_version_id WHERE n.id=ANY(%s) AND (v.bid_id IS DISTINCT FROM %s OR n.kind<>'document')",
        (list(scope.source_ids), scope.bid_id),
    ).fetchall()
    if foreign:
        raise ValueError("Retrieval source belongs to another project")
    params = (
        list(scope.source_ids),
        scope.as_of,
        list(scope.excluded_groups),
        False,
        list(excluded_evidence_ids),
    )
    allowed = "WITH allowed AS MATERIALIZED (SELECT * FROM retrieval.eligible_chunks(%s,%s,%s,%s) WHERE NOT evidence_ids && %s::uuid[]) "
    dense = c.execute(
        sql.SQL(allowed)
        + sql.SQL(
            ", permitted_embeddings AS MATERIALIZED (SELECT c.id,e.embedding FROM allowed c JOIN retrieval.embeddings e ON e.chunk_id=c.id WHERE e.profile_id=%s) SELECT id,embedding <=> %s::vector AS distance FROM permitted_embeddings ORDER BY distance,id LIMIT 50"
        ),
        (*params, profile_id, vector),
    ).fetchall()
    lexical = c.execute(
        sql.SQL(allowed)
        + sql.SQL(
            "SELECT c.id,ts_rank_cd(c.lex_tsv,q.value) AS score FROM allowed c,plainto_tsquery('simple',%s) q(value) WHERE c.lex_tsv @@ q.value ORDER BY score DESC,c.id LIMIT 50"
        ),
        (*params, lexemes),
    ).fetchall()
    rankings = [[r["id"] for r in dense], [r["id"] for r in lexical]]
    patterns = numeric_patterns(query)
    if patterns:
        numeric = c.execute(
            sql.SQL(allowed)
            + sql.SQL(
                "SELECT c.id FROM allowed c WHERE normalize(c.text_content,NFKC) ~* ANY(%s::text[]) "
                "ORDER BY (SELECT count(*) FROM unnest(%s::text[]) AS p(pattern) "
                "WHERE normalize(c.text_content,NFKC) ~* p.pattern) DESC,c.id LIMIT 50"
            ),
            (*params, list(patterns), list(patterns)),
        ).fetchall()
        rankings.append([r["id"] for r in numeric])
    identities = [identity for identity, _ in fuse_rankings(rankings)]
    rows = c.execute(
        sql.SQL(allowed)
        + sql.SQL(
            "SELECT c.*,h.revision AS source_revision,n.document_version_id FROM allowed c JOIN retrieval.source_heads h ON h.source_id=c.source_id JOIN retrieval.source_nodes n ON n.id=c.source_id WHERE c.id=ANY(%s)"
        ),
        (*params, identities),
    ).fetchall()
    by_id = {row["id"]: dict(row) for row in rows}
    return [by_id[identity] for identity in identities if identity in by_id]


def rerank(query, rows, reranker):
    route = "exact_vector+lexical" + ("+numeric_exact" if numeric_patterns(query) else "") + "+rrf"
    identity = None
    if rows:
        try:
            scores = reranker.rank(query, [row["text_content"] for row in rows])
            if len(scores) != len(rows) or any(not math.isfinite(score) for score in scores):
                raise ValueError("Invalid reranker response")
            identity = getattr(reranker, "last_identity", None)
            if not isinstance(identity, dict) or not identity:
                raise ValueError("Reranker identity is missing")
            rows = [
                row
                for _, row in sorted(
                    zip(scores, rows, strict=True), key=lambda pair: (-pair[0], str(pair[1]["id"]))
                )
            ]
            route += "+reranker"
        except Exception:
            identity = None
            route += "+reranker_unavailable"
    return rows[:8], route, identity


def scope_identity(scope, control):
    return {
        "bid_id": str(scope.bid_id),
        "purpose": scope.purpose,
        "source_ids": [str(value) for value in scope.source_ids],
        "excluded_groups": [str(value) for value in scope.excluded_groups],
        "as_of": scope.as_of.isoformat(),
        "control": control,
    }


def trace(
    c, scope, control, manifest, query, profile_id, policy_digest, rows, route, reranker_identity
):
    identity = uuid4()
    identity_scope = scope_identity(scope, control)
    c.execute(
        "INSERT INTO retrieval.retrieval_traces(id,bid_id,purpose,query_digest,allowed_manifest_digest,profile_id,policy_digest,selected_chunk_ids,excluded_reasons) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            identity,
            scope.bid_id,
            scope.purpose,
            hashlib.sha256(query.encode()).hexdigest(),
            source_scope_digest(manifest, identity_scope),
            profile_id,
            policy_digest,
            [row["id"] for row in rows],
            Jsonb(
                {
                    "route": route,
                    "source_heads_rechecked": True,
                    "reranker_identity": reranker_identity,
                    "scope": identity_scope,
                }
            ),
        ),
    )
    return identity


def citation_id(trace_id, chunk_id):
    return uuid5(trace_id, str(chunk_id))
