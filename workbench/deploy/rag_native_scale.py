"""Synthetic row-capacity probes using real BGE vectors and production exact SQL.

Repeated synthetic clauses intentionally reuse the *same real model output*.
The receipt always exposes distinct text/vector counts. This measures 1k/10k/50k
eligible document chunks, not the cost of embedding 50k distinct documents, and
does not raise the separate enterprise-knowledge 5k-unit authority limit.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.rag import search
from packages.rag.http_port import DenseHttp, LexicalHttp, RerankHttp
from packages.rag.indexing import ensure_parse_sources, ensure_profile
from packages.rag.repository import RetrievalScope

NAMESPACE = UUID("d2303564-1035-4bc2-a5d0-e63444ed5f90")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[
        min(len(ordered) - 1, max(0, __import__("math").ceil(len(ordered) * fraction) - 1))
    ]


def connection(values, role):
    return psycopg.connect(values[role.upper() + "_DATABASE_DSN"], row_factory=dict_row)


def seed(values, size, corpus, lexemes, vectors, token_counts, identity):
    """Bind every synthetic COPY row to a real parse/page/source identity.

    COPY is a capacity-fixture loader, not the production indexing receipt. The
    independently executed smoke suite covers staged production publication.
    """
    bid, actor, version, blob, parse = (uuid4() for _ in range(5))
    page_count = (size + 19) // 20
    with connection(values, "api") as c:
        c.execute("INSERT INTO design.members(id,display_name) VALUES(%s,'合成容量夹具')", (actor,))
        c.execute(
            "INSERT INTO design.bids(id,title,settings,created_by) VALUES(%s,'合成检索容量，不是业务原件','{}',%s)",
            (bid, actor),
        )
        c.execute(
            "INSERT INTO design.blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,1,'application/pdf')",
            (blob, digest(str(blob)), "synthetic-scale-no-physical-object/" + str(blob)),
        )
        c.execute(
            "INSERT INTO design.document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'容量SQL夹具非实际原件.pdf',now()-interval '1 day','source_original',%s)",
            (version, bid, blob, actor),
        )
        c.execute(
            "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,%s,'partial',%s)",
            (
                parse,
                bid,
                version,
                digest("synthetic parse-table fixture"),
                digest(str(parse)),
                page_count,
                Jsonb(
                    [
                        "Capacity SQL fixture, no actual PDF parse; repeated clauses reuse real embeddings"
                    ]
                ),
            ),
        )
        with c.cursor().copy(
            "COPY design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) FROM STDIN"
        ) as copy:
            for page in range(1, page_count + 1):
                copy.write_row((bid, parse, page, 595, 842, 0, "usable", Jsonb([])))
        with c.cursor().copy(
            "COPY design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) FROM STDIN"
        ) as copy:
            for i in range(size):
                text = corpus[i % len(corpus)]
                evidence_id = uuid5(parse, f"evidence:{i}")
                copy.write_row(
                    (evidence_id, bid, parse, i // 20 + 1, i % 20, "text", text, digest(text))
                )
    started = time.monotonic()
    with connection(values, "worker") as c:
        _, source = ensure_parse_sources(c, bid, parse, publish_readable=True)
        profile = ensure_profile(c, identity)
        with c.cursor().copy(
            "COPY retrieval.chunks(id,source_id,parse_id,physical_page,ordinal,chapter_path,evidence_ids,text_content,lexemes,token_count,digest) FROM STDIN"
        ) as copy:
            for i in range(size):
                k = i % len(corpus)
                text = corpus[k]
                copy.write_row(
                    (
                        uuid5(parse, f"chunk:{i}"),
                        source,
                        parse,
                        i // 20 + 1,
                        i,
                        ["合成容量"],
                        [uuid5(parse, f"evidence:{i}")],
                        text,
                        lexemes[k],
                        token_counts[k],
                        digest(text),
                    )
                )
        with c.cursor().copy(
            "COPY retrieval.embeddings(chunk_id,profile_id,embedding) FROM STDIN"
        ) as copy:
            for i in range(size):
                copy.write_row((uuid5(parse, f"chunk:{i}"), profile, vectors[i % len(vectors)]))
    index_seconds = time.monotonic() - started
    with connection(values, "api") as c:
        totals = c.execute(
            "SELECT count(*) AS chunks,count(e.chunk_id) AS embeddings,count(DISTINCT ch.digest) AS distinct_texts FROM retrieval.chunks ch LEFT JOIN retrieval.embeddings e ON e.chunk_id=ch.id AND e.profile_id=%s WHERE ch.source_id=%s",
            (profile, source),
        ).fetchone()
        if totals["chunks"] != size or totals["embeddings"] != size:
            raise ValueError("RAG_SCALE_INCOMPLETE_CORPUS")
        postgres = c.execute("SELECT version() AS version").fetchone()["version"]
        vector_version = c.execute(
            "SELECT extversion FROM pg_extension WHERE extname='vector'"
        ).fetchone()["extversion"]
        allowed = c.execute(
            "SELECT count(*) AS n FROM retrieval.eligible_chunks(%s,clock_timestamp(),ARRAY[]::uuid[],false)",
            ([source],),
        ).fetchone()["n"]
        if allowed != size:
            raise ValueError("RAG_SCALE_SCOPE_WAS_REDUCED")
    return (
        bid,
        parse,
        source,
        profile,
        {
            "eligible_chunks": allowed,
            "stored_embeddings": totals["embeddings"],
            "distinct_texts_and_real_embeddings": totals["distinct_texts"],
            "fixture_copy_index_seconds": index_seconds,
            "postgres": postgres,
            "pgvector": vector_version,
            "index_ingestion": "explicit nonowner COPY capacity fixture; production staged publication tested separately",
        },
    )


def measure(values, sizes, unique_texts):
    # This routine runs only inside its disposable acceptance process.
    os.environ.update({key: values[key] for key in ("RAG_RUNTIME_URL", "RAG_RUNTIME_TOKEN")})
    dense = DenseHttp()
    lexical = LexicalHttp(dense)
    corpus = [
        f"条款T{i:04d}：道路施工现场应设置围挡，高度至少{2 + i % 3}米，检查编号K{i:04d}。"
        for i in range(unique_texts)
    ]
    started = time.monotonic()
    vectors = dense.embed(corpus)
    embedding_seconds = time.monotonic() - started
    encoded = [json.dumps(v, separators=(",", ":")) for v in vectors]
    lexemes = [lexical.lexemes(text) for text in corpus]
    token_counts = [len(dense.offsets(text)) for text in corpus]
    queries = [f"T{i:04d} 围挡高度" for i in (0, 3, 7, unique_texts - 1)]
    started = time.monotonic()
    query_vectors = dense.embed(queries)
    query_embedding_seconds = time.monotonic() - started
    query_lexemes = [lexical.lexemes(query) for query in queries]
    results = []
    for size in sorted(sizes):
        bid, parse, source, profile, record = seed(
            values, size, corpus, lexemes, encoded, token_counts, dense.identity
        )
        scope = RetrievalScope(bid, "compliance", (source,), datetime.now(timezone.utc))
        timings, rerank_times, checks = [], [], []
        for repeat in range(3):
            for query, vector, words in zip(queries, query_vectors, query_lexemes, strict=True):
                started = time.monotonic()
                with connection(values, "api") as c:
                    c.execute("SET TRANSACTION READ ONLY")
                    rows = search.candidates(
                        c, scope, profile, json.dumps(vector), words, query=query
                    )
                timings.append(time.monotonic() - started)
                if repeat == 0:
                    started = time.monotonic()
                    selected, route, reranker_identity = search.rerank(
                        query, rows, RerankHttp(dense)
                    )
                    rerank_times.append(time.monotonic() - started)
                    if not reranker_identity or not route.endswith("+reranker"):
                        raise ValueError("RAG_SCALE_EXPECTED_REAL_RERANKER")
                    with connection(values, "api") as c:
                        for hit in selected:
                            original = c.execute(
                                "SELECT text_content,physical_page FROM design.evidence_blocks WHERE id=ANY(%s) AND parse_id=%s",
                                (hit["evidence_ids"], parse),
                            ).fetchone()
                            if (
                                original is None
                                or original["text_content"] != hit["text_content"]
                                or original["physical_page"] != hit["physical_page"]
                            ):
                                raise ValueError("RAG_SCALE_CITATION_MISMATCH")
                    checks.append(
                        {
                            "query_id": digest(query),
                            "hits": len(selected),
                            "literal_target_in_top8": any(
                                query.split()[0] in h["text_content"] for h in selected
                            ),
                            "citation_original_page_verified": True,
                            "route": route,
                            "actual_reranker_identity": reranker_identity,
                        }
                    )
        record.update(
            requested_chunks=size,
            query_count=len(timings),
            first_query_seconds=timings[0],
            hybrid_sql_p50_seconds=statistics.median(timings),
            hybrid_sql_p95_seconds=percentile(timings, 0.95),
            actual_rerank_p50_seconds=statistics.median(rerank_times),
            actual_rerank_p95_seconds=percentile(rerank_times, 0.95),
            synthetic_reference_checks=checks,
        )
        results.append(record)
        print(
            json.dumps(
                {
                    "stage": "real_rag_scale_completed",
                    "chunks": size,
                    "eligible_chunks": record["eligible_chunks"],
                    "p95_seconds": record["hybrid_sql_p95_seconds"],
                }
            ),
            flush=True,
        )
    return {
        "scope": "document-chunk full allowed scope; not enterprise knowledge scope or production concurrency",
        "corpus_kind": "synthetic repeated clauses with independently identified evidence and pages",
        "distinct_texts_embedded": unique_texts,
        "actual_embedding_seconds": embedding_seconds,
        "query_embedding_seconds": query_embedding_seconds,
        "corpus_text_digest": digest(json.dumps(corpus, ensure_ascii=False)),
        "embedding_profile": dense.identity,
        "lexical_dictionary_digest": dense.lexical_dictionary_digest,
        "dimensions": 1024,
        "normalized": True,
        "distance": "cosine",
        "enterprise_knowledge_max_units_unchanged": 5000,
        "rows": results,
        "business_relevance_quality": "not_measured_no_labeled_company_corpus",
    }
