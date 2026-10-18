"""Bounded real PG lock counterexamples and actual-runtime replay/recovery checks."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.assistant import budget, global_runtime
from packages.domain.runtime import DomainError, sha


@pytest.fixture(scope="module")
def lock_database():
    dsn = os.environ.get("FUSION_BUDGET_LOCK_TEST_DSN")
    if not dsn:
        pytest.skip("Dedicated disposable fusion_budget_lock database required")
    with psycopg.connect(dsn, autocommit=True) as c:
        assert c.info.dbname == "fusion_budget_lock"
        assert 170000 <= c.info.server_version < 180000
        c.execute("CREATE SCHEMA design")
        tables = {
            "assistant_jobs": "id uuid PRIMARY KEY,scope text,operation_id uuid",
            "assistant_global_runs": "id uuid PRIMARY KEY,state text,fence bigint,owner_token uuid,lease_until timestamptz,cancel_requested_at timestamptz,max_tokens integer",
            "assistant_global_calls": "id uuid PRIMARY KEY,run_id uuid,state text DEFAULT 'reserved',profile_digest text,request_digest text,intent_digest text,max_tokens integer,usage jsonb,provider_request_id text",
            "model_calls": "id uuid PRIMARY KEY,operation_id uuid,state text,usage jsonb",
            "operations": "id uuid PRIMARY KEY,state text",
            "assistant_price_versions": "id uuid PRIMARY KEY,input_per_million_minor bigint,output_per_million_minor bigint",
            "assistant_budget_reservations": "job_id uuid PRIMARY KEY,intent_id uuid,price_id uuid,state text,reserved_minor bigint,input_upper integer,output_upper integer,charged_minor bigint,settled_at timestamptz,dispatched_at timestamptz,global_call_id uuid,project_call_id uuid,requires_manual_reconciliation boolean",
            "assistant_budget_events": "job_id uuid,event_type text,payload jsonb",
        }
        for name, definition in tables.items():
            c.execute(f"CREATE TABLE design.{name}({definition})")
        c.execute(
            "CREATE FUNCTION design.assistant_reserve_budget(uuid) RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$"
        )
        source = (Path(__file__).parents[1] / "packages/assistant/sql/intent-budget.sql").read_text(
            encoding="utf-8"
        )
        start = source.index("CREATE FUNCTION design.assistant_settle_budget(")
        c.execute(source[start : source.index("END $$;", start) + len("END $$;")])
    try:
        yield dsn
    finally:
        # This schema was created above only after exact dedicated database checks.
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("DROP SCHEMA design CASCADE")


@contextmanager
def connect(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        c.execute("SET LOCAL search_path=design,public")
        c.execute("SET LOCAL statement_timeout='4s'")
        c.execute("SET LOCAL lock_timeout='3s'")
        c.execute("SET LOCAL deadlock_timeout='100ms'")
        yield c


def seed(dsn, billing="unknown"):
    job, call, owner, intent, price = [uuid4() for _ in range(5)]
    intent_digest = sha(str(job))
    profile, request = {"model": "synthetic"}, {"max_tokens": 2048}
    with connect(dsn) as c:
        c.execute("INSERT INTO assistant_jobs VALUES(%s,'global',NULL)", (job,))
        c.execute(
            "INSERT INTO assistant_global_runs VALUES(%s,'running',1,%s,%s,NULL,2048)",
            (job, owner, datetime.now(UTC) + timedelta(minutes=5)),
        )
        c.execute(
            "INSERT INTO assistant_global_calls VALUES(%s,%s,'unknown',%s,%s,%s,2048,%s,NULL)",
            (
                call,
                job,
                sha(profile),
                sha(request),
                intent_digest,
                Jsonb({"billing_state": billing}),
            ),
        )
        c.execute("INSERT INTO assistant_price_versions VALUES(%s,1000000,1000000)", (price,))
        c.execute(
            "INSERT INTO assistant_budget_reservations VALUES(%s,%s,%s,'unknown',2148,100,2048,NULL,NULL,clock_timestamp(),%s,NULL,false)",
            (job, intent, price, call),
        )
    row = {
        "id": job,
        "intent_digest": intent_digest,
        "input_manifest": {
            "kind": "answer",
            "context": {"projects": [], "sources": []},
            "logical_intent": {
                "id": str(intent),
                "price_version_id": str(price),
                "profile": profile,
            },
        },
    }
    return row, {"owner": owner, "fence": 1}, call, request, profile


@pytest.mark.parametrize("table", ["assistant_global_runs", "assistant_global_calls"])
def test_original_inverse_lock_order_has_actual_pg_deadlock(lock_database, table):
    row, _, call, _, _ = seed(lock_database)
    object_id = row["id"] if table.endswith("runs") else call
    barrier = Barrier(2)

    def contender(row_first):
        try:
            with connect(lock_database) as c:
                if row_first:
                    c.execute(f"SELECT id FROM {table} WHERE id=%s FOR UPDATE", (object_id,))
                else:
                    c.execute("SELECT pg_advisory_xact_lock(90129,1)")
                barrier.wait(timeout=2)
                if row_first:
                    c.execute("SELECT pg_advisory_xact_lock(90129,1)")
                else:
                    c.execute(f"SELECT id FROM {table} WHERE id=%s FOR UPDATE", (object_id,))
            return "completed"
        except psycopg.errors.DeadlockDetected:
            return "deadlock"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(contender, first) for first in (True, False)]
        assert sorted(f.result(timeout=5) for f in futures) == ["completed", "deadlock"]


def test_actual_fixed_reserve_replay_completes_without_releasing_unknown(
    lock_database, monkeypatch
):
    row, lease, call, request, profile = seed(lock_database)
    monkeypatch.setattr(global_runtime, "connection", lambda *_: connect(lock_database))
    run_locked, replay_started = Event(), Event()

    def dispatch_holder():
        with connect(lock_database) as c:
            global_runtime.locked_execution(c, row["id"], lease)
            run_locked.set()
            assert replay_started.wait(timeout=2)
            c.execute("SELECT pg_advisory_xact_lock(90127,1)")
            c.execute("SELECT pg_advisory_xact_lock(90129,1)")

    def replay():
        assert run_locked.wait(timeout=2)
        replay_started.set()
        return global_runtime.reserve(row, lease, request, profile)

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder, repeat = pool.submit(dispatch_holder), pool.submit(replay)
        holder.result(timeout=5)
        saved, created = repeat.result(timeout=5)
    assert saved["id"] == call and created is False
    with connect(lock_database) as c:
        assert c.execute(
            "SELECT state,reserved_minor,charged_minor FROM assistant_budget_reservations WHERE job_id=%s",
            (row["id"],),
        ).fetchone() == {"state": "unknown", "reserved_minor": 2148, "charged_minor": None}
        assert (
            c.execute(
                "SELECT count(*) AS n FROM assistant_global_calls WHERE run_id=%s", (row["id"],)
            ).fetchone()["n"]
            == 1
        )


def test_actual_failure_commits_native_before_waiting_for_budget(lock_database, monkeypatch):
    row, _, call, _, _ = seed(lock_database)
    monkeypatch.setattr(global_runtime, "connection", lambda *_: connect(lock_database))
    budget_locked, failure_waiting = Event(), Event()
    original_settle = budget.settle

    def settled(c, job):
        failure_waiting.set()
        return original_settle(c, job)

    monkeypatch.setattr(budget, "settle", settled)

    def observer():
        with connect(lock_database) as c:
            c.execute("SELECT pg_advisory_xact_lock(90129,1)")
            budget_locked.set()
            assert failure_waiting.wait(timeout=2)
            c.execute(
                "UPDATE assistant_global_calls SET usage=usage||'{\"observed\":true}' WHERE id=%s",
                (call,),
            )

    def failing():
        assert budget_locked.wait(timeout=2)
        global_runtime.failure(call, DomainError("SYNTHETIC_UNKNOWN", "synthetic", 409), sent=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        observe, fail = pool.submit(observer), pool.submit(failing)
        observe.result(timeout=5)
        fail.result(timeout=5)
    with connect(lock_database) as c:
        saved = c.execute(
            "SELECT state,reserved_minor,charged_minor FROM assistant_budget_reservations WHERE job_id=%s",
            (row["id"],),
        ).fetchone()
        assert saved == {"state": "unknown", "reserved_minor": 2148, "charged_minor": None}


def test_new_native_call_freezes_original_lease_without_backfilling_old_calls(
    lock_database, monkeypatch
):
    row, lease, call, request, profile = seed(lock_database)
    with connect(lock_database) as c:
        c.execute("DELETE FROM assistant_global_calls WHERE id=%s", (call,))
        c.execute(
            "UPDATE assistant_budget_reservations SET state='held',dispatched_at=NULL,global_call_id=NULL WHERE job_id=%s",
            (row["id"],),
        )
    monkeypatch.setattr(global_runtime, "connection", lambda *_: connect(lock_database))
    saved, created = global_runtime.reserve(row, lease, request, profile)
    assert created is True
    assert saved["state"] == "reserved"
    assert saved["usage"] == {
        "reservation": {"owner": str(lease["owner"]), "fence": lease["fence"]}
    }


@pytest.mark.parametrize(
    "billing,state,charge",
    [("unknown", "unknown", None), ("not_sent", "released", 0), ("usage_reported", "settled", 30)],
)
def test_terminal_tick_recovers_native_commit_crash_window(lock_database, billing, state, charge):
    row, _, call, _, _ = seed(lock_database)
    # Simulate committed native write and process loss before its separate settle.
    usage = {"billing_state": billing, "actual": {"prompt_tokens": 10, "completion_tokens": 20}}
    with connect(lock_database) as c:
        c.execute(
            "UPDATE assistant_global_calls SET state='failed',usage=%s WHERE id=%s",
            (Jsonb(usage), call),
        )
        c.execute("UPDATE assistant_global_runs SET state='failed' WHERE id=%s", (row["id"],))
    with connect(lock_database) as c:
        budget.terminal_tick(c, [row["id"]])
    with connect(lock_database) as c:
        saved = c.execute(
            "SELECT state,charged_minor,reserved_minor FROM assistant_budget_reservations WHERE job_id=%s",
            (row["id"],),
        ).fetchone()
        assert saved == {"state": state, "charged_minor": charge, "reserved_minor": 2148}
