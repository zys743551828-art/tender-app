"""Actual RPC in an explicitly named disposable PG17 database; no archived DDL."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

RPC_PATH = Path(__file__).parents[1] / "packages/assistant/sql/intent-budget.sql"


def rpc_source():
    source = RPC_PATH.read_text(encoding="utf-8")
    start = source.index("CREATE FUNCTION design.assistant_reconcile_budget(")
    return source[start : source.index("END $$;", start) + len("END $$;")]


def test_rpc_declares_server_side_null_and_terminal_guards():
    source = rpc_source()
    for argument in ("decision", "amount", "proof_reference", "proof_sha"):
        assert f"{argument} IS NULL" in source
    assert source.count("(native.state IN ('failed','cancelled')) IS DISTINCT FROM true") == 2


@pytest.fixture(scope="module")
def database():
    dsn = os.environ.get("FUSION_RECONCILIATION_TEST_DSN")
    if not dsn:
        pytest.skip("Explicit disposable reconciliation PG17 DSN required; no production access")
    with psycopg.connect(dsn) as c:
        assert c.info.dbname == "fusion_budget_rpc" or c.info.dbname.startswith(
            "tender_fusion_reconcile_"
        )
        assert 170000 <= c.info.server_version < 180000
        c.execute("CREATE SCHEMA design")
        c.execute("CREATE DOMAIN design.sha256 AS text CHECK(VALUE ~ '^[a-f0-9]{64}$')")
        c.execute(
            "CREATE TABLE design.assistant_jobs(id uuid PRIMARY KEY,scope text,operation_id uuid)"
        )
        c.execute("CREATE TABLE design.assistant_global_runs(id uuid PRIMARY KEY,state text)")
        c.execute("CREATE TABLE design.operations(id uuid PRIMARY KEY,state text)")
        for table in ("assistant_global_calls", "model_calls"):
            c.execute(f"CREATE TABLE design.{table}(id uuid PRIMARY KEY,state text,usage jsonb)")
        c.execute("""CREATE TABLE design.assistant_budget_reservations(
            job_id uuid PRIMARY KEY,state text,reserved_minor bigint,currency text,
            charged_minor bigint,settled_at timestamptz,requires_manual_reconciliation boolean,
            global_call_id uuid,project_call_id uuid)""")
        c.execute("""CREATE TABLE design.assistant_budget_events(
            job_id uuid,event_type text,payload jsonb)""")
        c.execute(rpc_source())
        try:
            yield c
        finally:
            # The whole fixture, including schema and function, stays uncommitted.
            c.rollback()


@pytest.fixture
def connection(database):
    with database.transaction(force_rollback=True):
        yield database


def seed(c, scope="global", native_state="failed", reservation_state="unknown"):
    job, operation, call = uuid4(), uuid4(), uuid4()
    c.execute("INSERT INTO design.assistant_jobs VALUES(%s,%s,%s)", (job, scope, operation))
    if native_state != "missing":
        table = "assistant_global_runs" if scope == "global" else "operations"
        c.execute(
            f"INSERT INTO design.{table} VALUES(%s,%s)",
            (job if scope == "global" else operation, native_state),
        )
    table = "assistant_global_calls" if scope == "global" else "model_calls"
    c.execute(f"INSERT INTO design.{table} VALUES(%s,'unknown','{{}}')", (call,))
    c.execute(
        """INSERT INTO design.assistant_budget_reservations VALUES(
        %s,%s,100,'USD',NULL,NULL,true,%s,%s)""",
        (
            job,
            reservation_state,
            call if scope == "global" else None,
            call if scope == "project" else None,
        ),
    )
    return job


def snapshot(c, job):
    return c.execute(
        """SELECT to_jsonb(r),
        (SELECT count(*) FROM design.assistant_budget_events WHERE job_id=r.job_id),
        (SELECT to_jsonb(g) FROM design.assistant_global_calls g WHERE g.id=r.global_call_id),
        (SELECT to_jsonb(p) FROM design.model_calls p WHERE p.id=r.project_call_id)
        FROM design.assistant_budget_reservations r WHERE r.job_id=%s""",
        (job,),
    ).fetchone()


def reconcile(
    c, job, decision="confirmed_billed", amount=10, proof="synthetic-proof-reference", sha="a" * 64
):
    return c.execute(
        "SELECT design.assistant_reconcile_budget(%s,%s,%s,%s,%s)",
        (job, decision, amount, proof, sha),
    ).fetchone()[0]


def rejected_unchanged(c, job, **arguments):
    before = snapshot(c, job)
    with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
        reconcile(c, job, **arguments)
    assert snapshot(c, job) == before


@pytest.mark.parametrize("scope", ["global", "project"])
@pytest.mark.parametrize(
    "arguments",
    [
        {"decision": None},
        {"amount": None},
        {"proof": None},
        {"sha": None},
        {"decision": None, "amount": 0, "proof": None, "sha": None},
        {"proof": ""},
        {"proof": " " * 20},
        {"proof": "\t\n" * 10},
        {"proof": "too-short"},
        {"sha": ""},
        {"sha": "g" * 64},
        {"decision": "unsupported"},
        {"amount": -1},
        {"amount": 101},
    ],
)
def test_invalid_arguments_preserve_unknown_hold_and_manual_flag(connection, scope, arguments):
    rejected_unchanged(connection, seed(connection, scope), **arguments)


@pytest.mark.parametrize("scope", ["global", "project"])
@pytest.mark.parametrize(
    "decision", ["confirmed_not_sent", "confirmed_billed", "confirmed_zero_charge_failure"]
)
@pytest.mark.parametrize("amount", [0, 1, 100])
def test_decision_amount_matrix(connection, scope, decision, amount):
    job = seed(connection, scope)
    if decision != "confirmed_billed" and amount != 0:
        rejected_unchanged(connection, job, decision=decision, amount=amount)
        return
    result = reconcile(connection, job, decision=decision, amount=amount)
    assert result["state"] == ("released" if decision == "confirmed_not_sent" else "settled")
    assert result["charged_minor"] == amount
    assert result["requires_manual_reconciliation"] is False
    assert snapshot(connection, job)[1] == 1
    assert (
        connection.execute(
            "SELECT payload->>'proof_sha256' FROM design.assistant_budget_events WHERE job_id=%s",
            (job,),
        ).fetchone()[0]
        == "a" * 64
    )


@pytest.mark.parametrize("scope", ["global", "project"])
@pytest.mark.parametrize("native_state", [None, "running", "pending", "succeeded", "missing"])
def test_nonterminal_or_missing_native_preserves_original_hold(connection, scope, native_state):
    rejected_unchanged(connection, seed(connection, scope, native_state=native_state))


@pytest.mark.parametrize("scope", ["global", "project"])
@pytest.mark.parametrize("state", [None, "held", "released", "settled"])
def test_non_reconcilable_reservation_state_is_rejected(connection, scope, state):
    rejected_unchanged(connection, seed(connection, scope, reservation_state=state))


@pytest.mark.parametrize("scope", ["global", "project"])
def test_second_reconciliation_cannot_change_charge_or_duplicate_audit(connection, scope):
    job = seed(connection, scope, native_state="cancelled", reservation_state="sent")
    reconcile(connection, job, amount=100)
    rejected_unchanged(connection, job, decision="confirmed_not_sent", amount=0)
