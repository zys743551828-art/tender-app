"""Real BGE/PG enterprise-knowledge path over an explicit one-page synthetic PDF.

Only the object port is an in-memory fixture. Models, tokenizer, SQL, distinct
API/Worker permissions, publication, retrieval, references and withdrawal are real.
This is software integration evidence, never a company-relevance benchmark.
"""

import io
import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from packages.domain.runtime import Command, DomainError, connection, now
from packages.knowledge import bridge, rag_api
from packages.knowledge.rag_index import compute_index
from packages.knowledge.rag_repository import prepare_index, publish_index, schedule_index
from packages.knowledge.rag_search import cite_unit, reference_history, trace_history
from packages.rag.http_port import DenseHttp, LexicalHttp
from tests import test_knowledge_integration as base

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_RAG_REAL") != "1", reason="Real local BGE/PG opt-in"
)


def test_real_knowledge_publish_embed_scope_cite_and_withdraw(monkeypatch):
    from reportlab.pdfgen import canvas

    from packages.domain import storage

    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(595, 842))
    pdf.drawString(40, 790, "Clause T0030 requires concrete C30. Synthetic reference only.")
    pdf.showPage()
    pdf.save()
    original = stream.getvalue()

    class ActualSyntheticPdf:
        def read_bytes(self):
            return original

    monkeypatch.setattr(base, "Path", lambda path: ActualSyntheticPdf())
    objects = {}
    monkeypatch.setattr(storage, "put", lambda key, data, media: objects.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: objects[key])
    env = base.environment.__wrapped__()
    # The older helper predates stable lot identity. Explicitly register and bind
    # a real lot for each synthetic project; never weaken the production guard.
    from packages.identity.repository import record_binding

    with connection() as c:
        for bid in (env["origin"], env["target"], env["foreign"]):
            current = c.execute(
                "SELECT r.id,r.engineering_project_id FROM bid_profiles p JOIN bid_rounds r ON r.id=p.round_id WHERE p.bid_id=%s",
                (bid,),
            ).fetchone()
            lot = uuid4()
            c.execute(
                "INSERT INTO engineering_lots(id,engineering_project_id,label) VALUES(%s,%s,'合成明确标段')",
                (lot, current["engineering_project_id"]),
            )
            c.execute(
                "UPDATE bid_rounds SET lot_id=%s,lot='合成明确标段' WHERE id=%s",
                (lot, current["id"]),
            )
            record_binding(
                c, bid, env["actor"], None, reason="合成用例明确核对稳定标段", confirmed=True
            )
    active = base.publish(
        env,
        env["body"]
        | {
            "content": "Clause T0030 requires concrete C30. Reference only; verify current project applicability."
        },
    )
    dense = DenseHttp()
    lexical = LexicalHttp(dense)
    with connection() as c:
        command = Command(c, env["actor"], "real-knowledge-index", env["item"], uuid4().hex, {})
        scheduled = schedule_index(c, env["item"], env["actor"], command.id, dense)
        command.finish(scheduled, 202)
    with connection(True) as c:
        prepared = prepare_index(c, UUID(scheduled["index_id"]))
    computed = compute_index(
        prepared, dense, dense, lexical, lexical_dictionary_digest=dense.lexical_dictionary_digest
    )
    with connection(True) as c:
        published = publish_index(c, computed)
        assert published["state"] == "ready"
    body = {
        "query": "T0030 C30",
        "purpose": "authoring",
        "limit": 2,
        "knowledge_ids": [str(env["item"])],
    }
    key = uuid4().hex
    response, replayed = rag_api.retrieve(env["target"], env["actor"], key, body)
    assert not replayed
    result = response["body"]
    assert len(result["hits"]) == 2
    assert set(result["route"]) == {"dense_exact", "simple_fts", "numeric_exact", "rrf", "rerank"}
    replay, replayed = rag_api.retrieve(env["target"], env["actor"], key, body)
    assert replayed and replay == response
    wrong, _ = rag_api.retrieve(env["foreign"], env["actor"], uuid4().hex, body)
    assert wrong["body"]["hits"] == []
    with connection() as c:
        assert not bridge.eligible_knowledge_sources(
            c, env["target"], "authoring", now() - timedelta(days=2)
        )["eligible"]
        with pytest.raises(DomainError):
            bridge.eligible_knowledge_sources(c, env["target"], "formal_score", now())
        hit = next(h for h in result["hits"] if h["unit_kind"] == "original_quote")
        reference = cite_unit(
            c,
            UUID(result["trace_id"]),
            env["actor"],
            {
                "unit_id": hit["unit_id"],
                "quote": hit["text"],
                "target_kind": "project",
                "target_object_id": str(env["target"]),
                "applicability_reason": "Synthetic fixture explicitly checked; reference only",
            },
            None,
        )
        assert not reference["project_fact_created"]
        assert reference["quote"] == env["body"]["source_refs"][0]["excerpt"]
    with connection() as c:
        base.action(c, env, "withdraw", active["revision"])
    with pytest.raises(DomainError):
        rag_api.retrieve(env["target"], env["actor"], key, body)
    with connection() as c:
        history = reference_history(c, UUID(reference["citation_id"]))
        assert history["reference"] == reference and history["current_reasons"]
        trace = trace_history(c, UUID(result["trace_id"]))
        assert trace["retrieval"] == result and trace["current_reasons"]
