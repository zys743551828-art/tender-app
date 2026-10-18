"""失败凭据与任务状态同事务，旧尝试不能写入领域记录。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import Connection, Engine

from bidwb import db, tasks
from bidwb.errors import Unprocessable
from bidwb.messaging import InMemoryBus
from bidwb.runtime import Container
from bidwb.services import audit
from bidwb.tasks import Claim
from bidwb.workers.handlers import HandlerFailure
from bidwb.workers.runner import WorkerRunner
from tests.test_tasks_protocol import _enqueue

pytestmark = pytest.mark.integration


def prepare(engine: Engine, container: Container) -> tuple[Claim, WorkerRunner]:
    with engine.begin() as conn:
        job = _enqueue(conn)
        claim = tasks.claim_job(conn, job, container.settings.worker_id, "parse", 60)
        assert claim is not None
    bus = InMemoryBus()
    return claim, WorkerRunner(container, "parse", bus.consumer(["job.parse"]), {}, consumer_name="failure-receipt-test")


def receipt(conn: Connection, claim: Claim) -> None:
    audit.record(
        conn,
        actor_id=None,
        project_id=claim.project_id,
        action="conversion.failed",
        object_kind="task",
        object_id=claim.job_id,
        request_id="synthetic-receipt",
        details={"source_sha256": "a" * 64},
    )


def test_failure_handler_commits_receipt_once_with_failure_state(engine: Engine, worker_container: Container) -> None:
    claim, runner = prepare(engine, worker_container)
    runner.handlers["parse"] = lambda ctx: HandlerFailure(
        "word_content_not_supported", "请为此文件补交 PDF", lambda conn: receipt(conn, ctx.claim)
    )
    runner.execute(claim)
    runner.execute(claim)
    with engine.connect() as conn:
        job = db.one(conn, "SELECT state,error_code,output_artifact_id FROM jobs WHERE id=:i", {"i": claim.job_id})
        assert job["state"] == "failed" and job["error_code"] == "word_content_not_supported" and job["output_artifact_id"] is None
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='conversion.failed'") == 1
        assert db.scalar(conn, "SELECT count(*) FROM job_events WHERE kind='failed'") == 1


@pytest.mark.parametrize("stale", ["expired", "cancel_requested", "wrong_input", "reclaimed"])
def test_rejected_attempt_never_appends_failure_receipt(engine: Engine, worker_container: Container, stale: str) -> None:
    claim, runner = prepare(engine, worker_container)
    with engine.begin() as conn:
        if stale in {"expired", "reclaimed"}:
            db.run(conn, "UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=:i", {"i": claim.job_id})
        if stale == "cancel_requested":
            db.run(conn, "UPDATE jobs SET state='cancel_requested' WHERE id=:i", {"i": claim.job_id})
        if stale == "reclaimed":
            tasks.reap(conn)
            new = tasks.claim_job(conn, claim.job_id, "new-worker", "parse", 60)
            assert new is not None and new.attempt == claim.attempt + 1
    if stale == "wrong_input":
        claim = replace(claim, input_sha256="0" * 64)
    runner._fail(claim, "word_conversion_failed", finalize=lambda conn: receipt(conn, claim))
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='conversion.failed'") == 0
        assert db.scalar(conn, "SELECT count(*) FROM job_events WHERE kind='failed'") == 0


def test_receipt_error_rolls_back_job_failure_and_event(engine: Engine, worker_container: Container) -> None:
    claim, runner = prepare(engine, worker_container)

    def invalid(conn: Connection) -> None:
        receipt(conn, claim)
        raise Unprocessable("synthetic_receipt_invalid")

    runner._fail(claim, "word_conversion_failed", finalize=invalid)
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT state FROM jobs WHERE id=:i", {"i": claim.job_id}) == "running"
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='conversion.failed'") == 0
        assert db.scalar(conn, "SELECT count(*) FROM job_events WHERE kind='failed'") == 0
