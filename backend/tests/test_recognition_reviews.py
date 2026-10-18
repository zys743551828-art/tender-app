"""核验追加、数字确认、历史隔离、并发与晚到解析的真实库验证。"""

import threading
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from bidwb import db, parse_enrichment, tasks
from bidwb.ai.handlers import _evidence_rows
from bidwb.messaging import InMemoryBus
from bidwb.services import parse_identity, snapshots
from bidwb.services.pipeline import _parse_state
from bidwb.workers.handlers import default_handlers
from bidwb.workers.runner import WorkerRunner
from tests.pdfs import make_pdf
from tests.test_files_and_parse import _recognition_result, _run_parse, _setup, _upload
from tests.test_product_logic import _flow, _ready

pytestmark = pytest.mark.integration


def _setup_candidates(
    api_factory: Any, make_member: Any, store: Any, worker_container: Any, monkeypatch: Any, *, scan: bool = False
) -> tuple[Any, str, str, dict[str, Any]]:
    worker_container.settings.parse_enrichment_enabled = True
    monkeypatch.setattr(parse_enrichment, "enrich_document", _recognition_result)
    api, pid = _setup(api_factory, make_member)
    version = _upload(api, store, pid, make_pdf([[] if scan else ["原生施工条款内容"]], image_first=True))[1].json()["version_id"]
    _run_parse(worker_container)
    listed = api.get(f"/files/{version}/recognition")
    assert listed.status_code == 200, listed.text
    return api, pid, version, listed.json()


def _body(listed: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {
        "expected_parse_id": listed["parse_id"],
        "evidence_id": listed["items"][0]["evidence_id"],
        "decision": "accept",
        "corrected_quote": None,
        "reason": "已对照原页逐字核验",
        "reviewed_original": True,
        "reviewed_numbers": True,
        **over,
    }


@pytest.mark.parametrize("decision", ["accept", "correct", "reject"])
def test_review_appends_and_is_idempotent(api_factory, make_member, store, engine, worker_container, monkeypatch, decision) -> None:  # type: ignore[no-untyped-def]
    api, pid, version, before = _setup_candidates(api_factory, make_member, store, worker_container, monkeypatch)
    request = _body(before, decision=decision, corrected_quote="费用15.21万元" if decision == "correct" else None)
    original = before["items"][0]
    reply = api.post(f"/files/{version}/recognition:review", request, key="one-candidate-review")
    assert reply.status_code == 200, reply.text
    assert api.post(f"/files/{version}/recognition:review", request, key="one-candidate-review").json() == reply.json()
    stale = api.post(f"/files/{version}/recognition:review", request)
    assert stale.status_code == 409 and stale.json()["code"] == "recognition_parse_stale"
    after = api.get(f"/files/{version}/recognition").json()
    assert after["parse_id"] != before["parse_id"] and after["pending_count"] == 1 and len(after["history"]) == 1
    with engine.connect() as conn:
        old = db.one(conn, "SELECT quote,semantic_review FROM evidence WHERE id=:i", {"i": original["evidence_id"]})
        assert dict(old) == {"quote": original["quote"], "semantic_review": "pending"}
        current = _evidence_rows(conn, pid, [version])
        assert len(current) == (1 if decision == "reject" else 2)
        assert db.scalar(conn, "SELECT count(*) FROM recognition_reviews") == 1
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='recognition.review'") == 1
    with engine.begin() as conn:
        nested = conn.begin_nested()
        with pytest.raises(DBAPIError):
            db.run(conn, "UPDATE recognition_reviews SET reason='覆盖旧决定'")
        nested.rollback()


def test_explicit_checks_invalid_candidate_and_auth(api_factory, make_member, store, engine, worker_container, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    api, _, version, before = _setup_candidates(api_factory, make_member, store, worker_container, monkeypatch)
    cases = [
        ({"reviewed_original": False}, "recognition_original_not_reviewed"),
        ({"reviewed_numbers": False}, "recognition_numbers_not_reviewed"),
        ({"decision": "correct", "corrected_quote": before["items"][0]["quote"]}, "recognition_correction_invalid"),
        ({"corrected_quote": "不应接受"}, "recognition_unexpected_correction"),
    ]
    for over, code in cases:
        response = api.post(f"/files/{version}/recognition:review", _body(before, **over))
        assert response.status_code == 422 and response.json()["code"] == code
    unknown = api.post(f"/files/{version}/recognition:review", _body(before, evidence_id="evd_other_project"))
    assert unknown.status_code == 404
    assert api_factory().get(f"/files/{version}/recognition").status_code == 401
    assert api.http.post(f"/api/v1/files/{version}/recognition:review", json=_body(before)).status_code == 403
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM recognition_reviews") == 0


def test_pure_ocr_requires_all_candidates_and_retains_coverage_gaps(
    api_factory, make_member, store, engine, worker_container, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    api, pid, version, before = _setup_candidates(api_factory, make_member, store, worker_container, monkeypatch, scan=True)
    assert api.post(f"/files/{version}/recognition:review", _body(before)).status_code == 200
    partial = api.get(f"/files/{version}/recognition").json()
    assert "recognition_verification_required" in partial["coverage_gaps"]
    table = next(item for item in partial["items"] if item["semantic_review"] == "pending")
    assert (
        api.post(
            f"/files/{version}/recognition:review",
            _body(partial, evidence_id=table["evidence_id"], decision="reject", reviewed_numbers=False),
        ).status_code
        == 200
    )
    checked = api.get(f"/files/{version}/recognition").json()
    assert "recognition_verification_required" not in checked["coverage_gaps"]
    assert "human_verified_candidates_partial" in checked["coverage_gaps"] and any(
        "no_text_layer" in gap for gap in checked["coverage_gaps"]
    )
    accepted = next(item for item in checked["items"] if item["semantic_review"] == "supported")
    assert (
        api.post(f"/files/{version}/recognition:review", _body(checked, evidence_id=accepted["evidence_id"], decision="reject")).status_code
        == 200
    )
    rejected = api.get(f"/files/{version}/recognition").json()
    assert "recognition_verification_required" in rejected["coverage_gaps"]
    with engine.connect() as conn:
        assert _evidence_rows(conn, pid, [version]) == []
        assert _parse_state(conn, pid, [{"id": version, "coverage": "partial", "original_name": "扫描稿.pdf"}])[0] == "failed"


def test_concurrent_review_has_one_winner(api_factory, make_member, store, engine, worker_container, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    api, _, version, before = _setup_candidates(api_factory, make_member, store, worker_container, monkeypatch)
    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def apply(n: int) -> None:
        barrier.wait(timeout=10)
        statuses.append(api.post(f"/files/{version}/recognition:review", _body(before), key=f"concurrent-{n}").status_code)

    threads = [threading.Thread(target=apply, args=(n,)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert sorted(statuses) == [200, 409]
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM recognition_reviews") == 1


def test_late_old_parse_does_not_replace_review(api_factory, make_member, store, engine, worker_container, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    api, pid, version, before = _setup_candidates(api_factory, make_member, store, worker_container, monkeypatch)
    with engine.begin() as conn:
        job, _ = tasks.enqueue(
            conn, project_id=pid, kind="parse", purpose="business", input_json={"file_version_id": version}, idempotency_key="old-parse"
        )
        db.run(conn, "UPDATE jobs SET state='failed',error_code='fixture-old-failure' WHERE id=:i", {"i": job})
    verified = api.post(f"/files/{version}/recognition:review", _body(before)).json()
    retry = api.post(f"/tasks/{job}/retry")
    assert retry.status_code == 202, retry.text
    bus = InMemoryBus()
    with worker_container.engine.begin() as conn:
        tasks.relay_outbox(conn, bus.producer())
    runner = WorkerRunner(worker_container, "parse", bus.consumer(["job.parse"]), default_handlers(), consumer_name="recognition-late-test")
    while runner.poll_once():
        pass
    assert api.get(f"/tasks/{job}").json()["state"] == "succeeded"
    assert api.get(f"/files/{version}/recognition").json()["parse_id"] == verified["result_parse_id"]


def test_old_snapshot_and_fact_evidence_remain_protected(api_factory, make_member, store, engine, worker_container, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    worker_container.settings.parse_enrichment_enabled = True
    monkeypatch.setattr(parse_enrichment, "enrich_document", _recognition_result)
    flow = _flow(api_factory, make_member, store, engine, worker_container)
    rules = _ready(flow, ["confirm", "confirm"])
    before = flow.api.get(f"/files/{flow.body}/recognition").json()
    assert flow.api.post(f"/files/{flow.body}/recognition:review", _body(before)).status_code == 200
    accepted = flow.api.get(f"/files/{flow.body}/recognition").json()
    item = next(row for row in accepted["items"] if row["semantic_review"] == "supported")
    fact = {
        "name": "费用",
        "subject": "工程",
        "scope": "本项目",
        "value_decimal": "15.12",
        "unit": "万元",
        "statement": item["quote"],
        "evidence_ids": [item["evidence_id"]],
    }
    assert flow.api.post(f"/projects/{flow.pid}/facts", fact).status_code == 200
    fact_set = flow.api.get(f"/projects/{flow.pid}/facts").json()["fact_set_id"]
    snap = flow.freeze(rules, fact_set_id=fact_set).json()
    with engine.connect() as conn:
        manifest = snapshots.manifest_json(store, conn, snap["snapshot_id"])
        old_rows = _evidence_rows(conn, flow.pid, [flow.body], snap["snapshot_id"])
    corrected = flow.api.post(
        f"/files/{flow.body}/recognition:review",
        _body(accepted, evidence_id=item["evidence_id"], decision="correct", corrected_quote="费用15.21万元"),
    )
    assert corrected.status_code == 200, corrected.text
    blocked = flow.freeze(rules, fact_set_id=fact_set)
    assert blocked.status_code == 409 and blocked.json()["code"] == "recognition_facts_stale"
    with engine.connect() as conn:
        assert snapshots.manifest_json(store, conn, snap["snapshot_id"]) == manifest
        assert _evidence_rows(conn, flow.pid, [flow.body], snap["snapshot_id"]) == old_rows
        assert not parse_identity.is_current(conn, flow.pid, snap["snapshot_id"])
    assert flow.api.get(f"/files/{flow.body}/recognition?offset=20").json()["items"] == []
