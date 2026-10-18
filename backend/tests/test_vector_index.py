"""真实 PostgreSQL 向量距离、范围隔离、派生索引权限与故障回退。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from bidwb import db, tasks
from bidwb.embeddings import DIMENSIONS, EmbeddingUnavailable, Encoded
from bidwb.messaging import InMemoryBus
from bidwb.services import evidence, parse_identity, vector_index
from bidwb.workers.handlers import default_handlers
from bidwb.workers.runner import WorkerRunner
from tests.pdfs import make_pdf
from tests.test_files_and_parse import PROJECT, _setup, _upload

pytestmark = pytest.mark.integration


class Encoder:
    """受控单位向量只用于证明数据库距离与过滤；真实模型质量另由冻结查询评测。"""

    def encode(self, texts: list[str], *, query: bool = False) -> Encoded:
        del query
        return Encoded([[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts], [False] * len(texts))


def _enable_vector(engine: Engine) -> None:
    with engine.begin() as conn:
        if not db.scalar(conn, "SELECT EXISTS(SELECT 1 FROM pg_available_extensions WHERE name='vector')"):
            pytest.skip("当前 PostgreSQL 没有安装 pgvector")
        db.run(conn, "CREATE EXTENSION IF NOT EXISTS vector")


@pytest.fixture
def materials(api_factory: Any, make_member: Any, store: Any, engine: Engine, worker_container: Any) -> tuple[Any, str, str, str, str]:
    api, pid = _setup(api_factory, make_member)
    first = _upload(api, store, pid, make_pdf([["旧版工期120天"]]))[1].json()
    current = _upload(api, store, pid, make_pdf([["新版工期180天"]]), version_of=first["file_id"])[1].json()
    other_pid = api.post("/projects", {**PROJECT, "title": "另一个项目"}).json()["project_id"]
    _upload(api, store, other_pid, make_pdf([["其他项目工期999天"]]))
    _upload(api, store, pid, make_pdf([["官方成绩工期888天"]]), role="official_result")
    bus = InMemoryBus()
    with worker_container.engine.begin() as conn:
        tasks.relay_outbox(conn, bus.producer())
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="vector-test-parse")
    while runner.poll_once():
        pass
    with engine.begin() as conn:
        artifact = db.scalar(conn, "SELECT artifact_id FROM file_versions WHERE id=:v", {"v": first["version_id"]})
        db.run(
            conn,
            """INSERT INTO rule_packages(id,project_id,revision,status,artifact_id,source_versions_json,created_at)
               VALUES ('rpk_test',:p,1,'candidate',:a,'[]',now())""",
            {"p": pid, "a": artifact},
        )
        db.run(
            conn,
            """INSERT INTO input_snapshots(id,project_id,body_version_id,rule_set_id,as_of,contract_version,sha256,manifest_artifact_id,parse_inputs_json,coverage_gaps_json)
               VALUES ('snp_test',:p,:v,'rpk_test',now(),'input-v2',:h,:a,CAST(:inputs AS jsonb),'[]')""",
            {
                "p": pid,
                "v": first["version_id"],
                "h": "a" * 64,
                "a": artifact,
                "inputs": json.dumps(parse_identity.capture(conn, pid, [first["version_id"]])[0]),
            },
        )
        db.run(conn, "INSERT INTO snapshot_files VALUES ('snp_test',:p,:v)", {"p": pid, "v": first["version_id"]})
    return api, pid, other_pid, first["version_id"], current["version_id"]


def test_vector_search_filters_current_snapshot_project_and_purpose(
    materials: tuple[Any, str, str, str, str], engine: Engine, worker_engine: Engine, settings: Any, monkeypatch: Any
) -> None:
    _enable_vector(engine)
    api, pid, other_pid, old, current = materials
    encoder = Encoder()
    assert vector_index.rebuild(worker_engine, pid, encoder) == 2  # type: ignore[arg-type]
    assert vector_index.rebuild(worker_engine, other_pid, encoder) == 1  # type: ignore[arg-type]
    assert vector_index.rebuild(worker_engine, pid, encoder) == 2  # type: ignore[arg-type]  幂等回填
    settings.retrieval_backend, settings.embedding_model_dir = "pgvector", "test-local-model"
    monkeypatch.setattr(evidence, "get_embedder", lambda _: encoder)
    request = {"query": "工期", "top_k": 50, "mode": "hybrid"}
    live = api.post(f"/projects/{pid}/search", request).json()
    assert live["mode_used"] == "hybrid" and live["index_state"] == "ready"
    assert {hit["evidence"]["version_id"] for hit in live["hits"]} == {current}
    frozen = api.post(f"/projects/{pid}/search", {**request, "snapshot_id": "snp_test"}).json()
    assert {hit["evidence"]["version_id"] for hit in frozen["hits"]} == {old}
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM evidence_embeddings") == 3
        assert db.scalar(conn, "SELECT count(*) FROM evidence_embeddings WHERE project_id=:p", {"p": pid}) == 2


def test_vector_distance_uses_only_explicit_allowed_ids(materials: Any, engine: Engine, worker_engine: Engine) -> None:
    _enable_vector(engine)
    _, pid, other_pid, _, _ = materials
    vector_index.rebuild(worker_engine, pid, Encoder())  # type: ignore[arg-type]
    vector_index.rebuild(worker_engine, other_pid, Encoder())  # type: ignore[arg-type]
    with engine.begin() as conn:
        rows = db.all_(conn, "SELECT id,quote FROM evidence WHERE project_id=:p ORDER BY id", {"p": pid})
        allowed = [(row["id"], row["quote"]) for row in rows if "官方" not in row["quote"]]
        db.run(
            conn, "UPDATE evidence_embeddings SET embedding=:v WHERE evidence_id=:i", {"v": [0.0, 1.0] + [0.0] * 510, "i": allowed[0][0]}
        )
        hits, _ = vector_index.dense_rank(conn, pid, allowed, [1.0] + [0.0] * 511, 50)
        assert [hit.index for hit in hits] == [1, 0]
        assert hits[0].score == pytest.approx(1.0) and hits[1].score == pytest.approx(0.0)
        # 即便调用方误给了另一个项目的 ID，数据库 project_id 条件仍会阻止越界。
        with pytest.raises(EmbeddingUnavailable, match="incomplete"):
            vector_index.dense_rank(conn, other_pid, allowed, [1.0] + [0.0] * 511, 50)
        assert db.scalar(conn, "SELECT 1") == 1


@pytest.mark.parametrize("failure", ["missing", "fingerprint", "hash", "extension", "inference"])
def test_vector_failure_falls_back_without_mutating_evidence(
    materials: Any, engine: Engine, worker_engine: Engine, settings: Any, monkeypatch: Any, failure: str
) -> None:
    _enable_vector(engine)
    api, pid, _, _, current = materials
    encoder = Encoder()
    vector_index.rebuild(worker_engine, pid, encoder)  # type: ignore[arg-type]
    with engine.begin() as conn:
        if failure == "missing":
            db.run(conn, "DELETE FROM evidence_embeddings")
        elif failure == "fingerprint":
            db.run(conn, "UPDATE evidence_embeddings SET model_fingerprint=:m", {"m": "b" * 64})
        elif failure == "hash":
            db.run(conn, "UPDATE evidence_embeddings SET quote_sha256=:h", {"h": "c" * 64})
        elif failure == "extension":
            db.run(conn, "DROP EXTENSION vector")
    settings.retrieval_backend, settings.embedding_model_dir = "pgvector", "test-local-model"
    if failure == "inference":

        def unavailable(_: str) -> None:
            raise EmbeddingUnavailable("embedding_inference_failed")

        monkeypatch.setattr(evidence, "get_embedder", unavailable)
    else:
        monkeypatch.setattr(evidence, "get_embedder", lambda _: encoder)
    result = api.post(f"/projects/{pid}/search", {"query": "工期", "top_k": 5, "mode": "hybrid"}).json()
    assert result["mode_used"] == "keyword" and result["index_state"] == "unavailable" and result["gaps"]
    assert {hit["evidence"]["version_id"] for hit in result["hits"]} == {current}
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM evidence WHERE semantic_review <> 'pending'") == 0


def test_vector_database_rejects_nonfinite_values(materials: Any, engine: Engine, worker_engine: Engine) -> None:
    _, pid, _, _, _ = materials
    vector_index.rebuild(worker_engine, pid, Encoder())  # type: ignore[arg-type]
    with pytest.raises(IntegrityError), engine.begin() as conn:
        db.run(conn, "UPDATE evidence_embeddings SET embedding=:v", {"v": [float("nan")] * DIMENSIONS})


@pytest.mark.parametrize("unavailable", [False, True])
def test_parse_builds_vectors_atomically_or_keeps_native_text(
    api_factory: Any,
    make_member: Any,
    store: Any,
    engine: Engine,
    worker_container: Any,
    settings: Any,
    monkeypatch: Any,
    unavailable: bool,
) -> None:
    settings.retrieval_backend, settings.embedding_model_dir = "pgvector", "test-local-model"
    if unavailable:

        def fail(_: str) -> None:
            raise EmbeddingUnavailable("embedding_model_hash_mismatch")

        monkeypatch.setattr(vector_index, "get_embedder", fail)
    else:
        monkeypatch.setattr(vector_index, "get_embedder", lambda _: Encoder())
    api, pid = _setup(api_factory, make_member)
    _upload(api, store, pid, make_pdf([["本项目施工工期180天"]]))
    bus = InMemoryBus()
    with worker_container.engine.begin() as conn:
        tasks.relay_outbox(conn, bus.producer())
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="vector-parse")
    assert runner.poll_once()
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT state FROM jobs") == "succeeded"
        assert db.scalar(conn, "SELECT count(*) FROM evidence") == 1
        assert db.scalar(conn, "SELECT count(*) FROM evidence_embeddings") == (0 if unavailable else 1)


def test_database_error_rolls_back_only_vector_savepoint(materials: Any, engine: Engine) -> None:
    _enable_vector(engine)
    _, pid, _, _, _ = materials
    with engine.begin() as conn:
        row = db.one(conn, "SELECT id,quote FROM evidence WHERE project_id=:p LIMIT 1", {"p": pid})
        db.run(conn, "ALTER TABLE evidence_embeddings RENAME TO unavailable_index")
        with pytest.raises(EmbeddingUnavailable, match="index_unavailable"):
            vector_index.dense_rank(conn, pid, [(row["id"], row["quote"])], [1.0] + [0.0] * 511, 5)
        assert db.scalar(conn, "SELECT 1") == 1
        db.run(conn, "ALTER TABLE unavailable_index RENAME TO evidence_embeddings")


def test_truncated_embeddings_are_reported(materials: Any, engine: Engine, worker_engine: Engine, settings: Any, monkeypatch: Any) -> None:
    _enable_vector(engine)
    api, pid, _, _, _ = materials
    vector_index.rebuild(worker_engine, pid, Encoder())  # type: ignore[arg-type]
    with engine.begin() as conn:
        db.run(conn, "UPDATE evidence_embeddings SET truncated=true")
    settings.retrieval_backend, settings.embedding_model_dir = "pgvector", "test-local-model"
    monkeypatch.setattr(evidence, "get_embedder", lambda _: Encoder())
    result = api.post(f"/projects/{pid}/search", {"query": "工期", "top_k": 5, "mode": "hybrid"}).json()
    assert result["mode_used"] == "hybrid"
    assert any(gap.startswith("embedding_documents_truncated:") for gap in result["gaps"])
