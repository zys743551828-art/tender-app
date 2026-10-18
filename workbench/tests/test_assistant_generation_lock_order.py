"""Actual queue entry/PG locks; budget prepare is a bounded reuse-only test port."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import psycopg
import pytest
import test_assistant_budget_lock_order as lock_fixture
from test_assistant_budget_lock_order import connect

from packages.assistant import budget, jobs
from packages.domain.runtime import DomainError


@pytest.fixture(scope="module")
def lock_database():
    yield from lock_fixture.lock_database.__wrapped__()


@pytest.fixture
def project(lock_database):
    bid = uuid4()
    with connect(lock_database) as c:
        c.execute("CREATE TABLE IF NOT EXISTS bids(id uuid PRIMARY KEY,revision integer)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS bid_profiles(bid_id uuid PRIMARY KEY,phase text,archived_at timestamptz)"
        )
        c.execute("INSERT INTO bids VALUES(%s,1)", (bid,))
        c.execute("INSERT INTO bid_profiles VALUES(%s,'working',NULL)", (bid,))
    return bid


def body():
    return {
        "section_id": str(uuid4()),
        "base_section_revision": 1,
        "instruction": "synthetic generation",
        "source_version_ids": [],
    }


def test_original_generation_budget_then_graph_order_has_real_deadlock(lock_database):
    barrier = Barrier(2)

    def contender(first, second):
        try:
            with connect(lock_database) as c:
                c.execute("SELECT pg_advisory_xact_lock(%s,1)", (first,))
                barrier.wait(timeout=2)
                c.execute("SELECT pg_advisory_xact_lock(%s,1)", (second,))
            return "completed"
        except psycopg.errors.DeadlockDetected:
            return "deadlock"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(contender, first, second)
            for first, second in [(90127, 90129), (90129, 90127)]
        ]
        assert sorted(f.result(timeout=5) for f in futures) == ["completed", "deadlock"]


def test_actual_generation_queue_locks_graph_before_budget_and_reuses_without_execution(
    lock_database, project, monkeypatch
):
    monkeypatch.setattr(jobs, "require_schema", lambda *_: None)
    reused = uuid4()
    monkeypatch.setattr(jobs, "view", lambda c, identity, actor: {"reused": identity})
    generation_started, graph_locked = Event(), Event()
    entered = []

    def prepare(c, *args, **kwargs):
        # Inspect actual locks of the real queue transaction, before this port
        # takes the budget mutex. The old queue fails here.
        assert c.execute(
            "SELECT EXISTS(SELECT FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' AND classid=90127 AND objid=1 AND granted) AS present"
        ).fetchone()["present"]
        c.execute("SELECT pg_advisory_xact_lock(90129,1)")
        c.execute("SELECT pg_advisory_xact_lock(90127,1)")
        entered.append(True)
        return {"reuse_id": reused}

    monkeypatch.setattr(budget, "prepare", prepare)

    def source_writer():
        with connect(lock_database) as c:
            c.execute("SELECT pg_advisory_xact_lock(90127,1)")
            graph_locked.set()
            assert generation_started.wait(timeout=2)
            c.execute("SELECT pg_advisory_xact_lock(90129,1)")

    def generation():
        assert graph_locked.wait(timeout=2)
        generation_started.set()
        with connect(lock_database) as c:
            return jobs.queue_generation(c, project, uuid4(), body(), uuid4())

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer, queued = pool.submit(source_writer), pool.submit(generation)
        writer.result(timeout=5)
        assert queued.result(timeout=5) == {"reused": reused}
    assert entered == [True]


def test_closed_project_still_rejects_before_budget_acceptance(lock_database, project, monkeypatch):
    monkeypatch.setattr(jobs, "require_schema", lambda *_: None)
    monkeypatch.setattr(
        budget, "prepare", lambda *args, **kwargs: pytest.fail("closed project reached budget")
    )
    with connect(lock_database) as c:
        c.execute("UPDATE bid_profiles SET phase='closed' WHERE bid_id=%s", (project,))
    with connect(lock_database) as c, pytest.raises(DomainError) as error:
        jobs.queue_generation(c, project, uuid4(), body(), uuid4())
    assert error.value.code == "PROJECT_WORK_CLOSED"
