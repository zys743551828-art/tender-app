"""任务协议：事务性发件箱、领取、租约、结果条件提交、回收。需要真实 PostgreSQL。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Engine

from bidwb import db, tasks
from bidwb.errors import Conflict, Unprocessable
from bidwb.messaging import InMemoryBus
from bidwb.util import new_id, utcnow

pytestmark = pytest.mark.integration

LEASE = 60


def _seed_project(conn) -> str:
    db.run(conn, "INSERT INTO members(id,display_name,active,created_at) VALUES ('mem_a','甲',true,now())")
    db.run(
        conn,
        """INSERT INTO projects(id,title,lot,round,region,engineering_type,state,owner_id,created_at)
                    VALUES ('prj_a','项目','一标段',1,'合肥','市政','materials_pending','mem_a',now())""",
    )
    return "prj_a"


def _artifact(conn, status: str = "committed") -> str:
    art = new_id("art")
    db.run(
        conn,
        """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
                    VALUES (:i,repeat('a',64),:k,1,'application/json','t',now(),:s)""",
        {"i": art, "k": f"k/{art}", "s": status},
    )
    return art


def _enqueue(conn) -> str:
    pid = _seed_project(conn)
    job_id, created = tasks.enqueue(
        conn, project_id=pid, kind="parse", purpose="research", idempotency_key="parse:v1", input_json={"file_version_id": "v1"}
    )
    assert created
    return job_id


def test_enqueue_writes_job_and_outbox_atomically(engine: Engine) -> None:
    with engine.begin() as conn:
        job_id = _enqueue(conn)
        assert db.scalar(conn, "SELECT count(*) FROM outbox_events WHERE topic='job.parse'") == 1
        again, created = tasks.enqueue(
            conn, project_id="prj_a", kind="parse", purpose="research", idempotency_key="parse:v1", input_json={"file_version_id": "v1"}
        )
        assert (again, created) == (job_id, False)
        assert db.scalar(conn, "SELECT count(*) FROM outbox_events") == 1  # 重复入队不再发件


def test_rolled_back_enqueue_leaves_no_outbox(engine: Engine) -> None:
    with pytest.raises(RuntimeError), engine.begin() as conn:
        _enqueue(conn)
        raise RuntimeError("boom")
    with engine.begin() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM jobs") == 0
        assert db.scalar(conn, "SELECT count(*) FROM outbox_events") == 0


def test_relay_publishes_and_keeps_failed_rows(engine: Engine) -> None:
    bus = InMemoryBus()
    with engine.begin() as conn:
        _enqueue(conn)
    bus.fail_next = 1
    with engine.begin() as conn:
        assert tasks.relay_outbox(conn, bus.producer()) == 0
        assert db.one(conn, "SELECT publish_attempts,published_at FROM outbox_events")["published_at"] is None
    with engine.begin() as conn:
        assert tasks.relay_outbox(conn, bus.producer()) == 1
    assert len(bus.sent) == 1 and bus.sent[0].topic == "job.parse"


def test_claim_is_exclusive_and_class_scoped(engine: Engine) -> None:
    with engine.begin() as conn:
        job_id = _enqueue(conn)
    with engine.begin() as conn:
        assert tasks.claim_job(conn, job_id, "w1", "ai", LEASE) is None  # 类别不符
        first = tasks.claim_job(conn, job_id, "w1", "parse", LEASE)
        assert first is not None and first.attempt == 1
        assert tasks.claim_job(conn, job_id, "w2", "parse", LEASE) is None  # 已被持有


def test_commit_requires_current_lease_input_and_committed_artifact(engine: Engine) -> None:
    with engine.begin() as conn:
        job_id = _enqueue(conn)
        claim = tasks.claim_job(conn, job_id, "w1", "parse", LEASE)
        assert claim
        staged = _artifact(conn, "staged")
        committed = _artifact(conn)
    with pytest.raises(Conflict, match="input_hash_mismatch"), engine.begin() as conn:
        tasks.commit_result(conn, claim, input_sha256="0" * 64, artifact_id=committed)
    with pytest.raises(Unprocessable), engine.begin() as conn:
        tasks.commit_result(conn, claim, input_sha256=claim.input_sha256, artifact_id=staged)
    with engine.begin() as conn:
        tasks.commit_result(conn, claim, input_sha256=claim.input_sha256, artifact_id=committed)
        assert db.one(conn, "SELECT state,lease_token_hash FROM jobs")["state"] == "succeeded"
    with pytest.raises(Conflict, match="lease_lost"), engine.begin() as conn:  # 重复提交
        tasks.commit_result(conn, claim, input_sha256=claim.input_sha256, artifact_id=committed)


def test_expired_lease_is_reaped_and_old_attempt_cannot_commit(engine: Engine) -> None:
    with engine.begin() as conn:
        job_id = _enqueue(conn)
        old = tasks.claim_job(conn, job_id, "w1", "parse", LEASE)
        assert old
        art = _artifact(conn)
    later = utcnow() + timedelta(seconds=LEASE + 5)
    with engine.begin() as conn:
        assert tasks.reap(conn, later)["requeued"] == 1
        new = tasks.claim_job(conn, job_id, "w2", "parse", LEASE, now=later)
        assert new and new.attempt == 2
    with pytest.raises(Conflict, match="lease_lost"), engine.begin() as conn:
        tasks.commit_result(conn, old, input_sha256=old.input_sha256, artifact_id=art, now=later)


def test_attempts_exhausted_marks_failed(engine: Engine) -> None:
    with engine.begin() as conn:
        job_id = _enqueue(conn)
        db.run(conn, "UPDATE jobs SET max_attempts=1")
        assert tasks.claim_job(conn, job_id, "w1", "parse", LEASE)
    with engine.begin() as conn:
        assert tasks.reap(conn, utcnow() + timedelta(seconds=LEASE + 5))["failed"] == 1
        assert db.one(conn, "SELECT state,error_code FROM jobs")["error_code"] == "lease_expired_attempts_exhausted"


def test_renew_extends_and_detects_cancel(engine: Engine) -> None:
    with engine.begin() as conn:
        job_id = _enqueue(conn)
        claim = tasks.claim_job(conn, job_id, "w1", "parse", LEASE)
        assert claim
        tasks.renew_lease(conn, claim, LEASE)
        db.run(conn, "UPDATE jobs SET state='cancel_requested' WHERE id=:i", {"i": job_id})
    with pytest.raises(Conflict, match="cancel_requested"), engine.begin() as conn:
        tasks.renew_lease(conn, claim, LEASE)


def test_consume_dedupe(engine: Engine) -> None:
    event = "6f0e6b0e-2f5a-4c1c-9a39-0a1d6d0e1111"
    with engine.begin() as conn:
        assert tasks.consume_once(conn, "worker-parse", event) is True
        assert tasks.consume_once(conn, "worker-parse", event) is False
        assert tasks.consume_once(conn, "worker-ai", event) is True


def test_job_inputs_are_immutable(engine: Engine) -> None:
    with engine.begin() as conn:
        _enqueue(conn)
    with pytest.raises(Exception, match="immutable_job_input"), engine.begin() as conn:
        db.run(conn, "UPDATE jobs SET input_json = CAST(:v AS jsonb)", {"v": '{"x": 1}'})
