"""PG17 dispatch boundary tests; target qualification is an explicit no-op fixture."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from packages.assistant import budget
from packages.domain.runtime import DomainError, sha


@pytest.fixture(scope="module")
def dispatch_database():
    dsn = os.environ.get("FUSION_RECONCILIATION_TEST_DSN")
    if not dsn:
        pytest.skip("Explicit disposable reconciliation PG17 DSN required")
    with psycopg.connect(dsn) as c:
        assert c.info.dbname == "fusion_budget_rpc" or c.info.dbname.startswith(
            "tender_fusion_reconcile_"
        )
        assert 170000 <= c.info.server_version < 180000
        c.execute("CREATE SCHEMA design")
        definitions = {
            "assistant_jobs": "id uuid,kind text,scope text,bid_id uuid,operation_id uuid,actor_id uuid,input_manifest jsonb,input_digest text,intent_digest text",
            "assistant_logical_intents": "id uuid,job_id uuid,actor_id uuid,target jsonb,origin_action_id uuid",
            "assistant_budget_reservations": "job_id uuid,intent_id uuid,actor_id uuid,state text,dispatched_at timestamptz,price_id uuid,output_upper integer,input_upper integer,currency text,reserved_minor bigint,member_budget_id uuid,project_budget_id uuid,global_budget_id uuid,global_call_id uuid,project_call_id uuid",
            "assistant_price_versions": "id uuid,provider text,model text,valid_from timestamptz,valid_until timestamptz,output_hard_ceiling integer,input_hard_ceiling integer,currency text,input_per_million_minor bigint,output_per_million_minor bigint",
            "assistant_budget_versions": "id uuid,scope text,owner_key text,revision integer,window_from timestamptz,window_until timestamptz,limit_minor bigint",
            "action_consumptions": "action_id uuid,result jsonb",
            "assistant_global_runs": "id uuid,state text,cancel_requested_at timestamptz,lease_until timestamptz,max_tokens integer,input_digest text,fence bigint,owner_token uuid",
            "assistant_global_calls": "id uuid,run_id uuid,state text,profile_digest text,intent_digest text,max_tokens integer,usage jsonb",
            "operations": "id uuid,bid_id uuid,state text,cancel_requested_at timestamptz,handler_version text",
            "model_calls": "id uuid,operation_id uuid,state text,profile_digest text,logical_call_key text,attempt_no integer,research_run_id uuid,reserved_amount numeric,usage jsonb",
            "step_receipts": "operation_id uuid,state text,lease_until timestamptz,step_key text,input_digest text,fence bigint,owner_token uuid",
            "operation_steps": "operation_id uuid,step_key text,input_digest text,handler_version text,dispatch_generation bigint",
            "assistant_budget_events": "job_id uuid,event_type text,payload jsonb",
        }
        for table, columns in definitions.items():
            c.execute(f"CREATE TABLE design.{table}({columns})")
        c.execute(
            "CREATE FUNCTION design.assistant_check_target(jsonb,uuid) RETURNS void LANGUAGE plpgsql AS $$ BEGIN RETURN; END $$"
        )
        c.execute(
            "CREATE FUNCTION design.assistant_assert_job_authority(uuid) RETURNS void LANGUAGE plpgsql AS $$ BEGIN RETURN; END $$"
        )
        c.execute(
            "CREATE FUNCTION design.assistant_budget_obligation(uuid) RETURNS bigint LANGUAGE sql AS $$ SELECT 0::bigint $$"
        )
        source = (Path(__file__).parents[1] / "packages/assistant/sql/intent-budget.sql").read_text(
            encoding="utf-8"
        )
        start = source.index("CREATE FUNCTION design.assistant_dispatch_budget(")
        c.execute(source[start : source.index("END $$;", start) + len("END $$;")])
        try:
            yield c
        finally:
            c.rollback()


@pytest.fixture
def connection(dispatch_database):
    with dispatch_database.transaction(force_rollback=True):
        yield dispatch_database


def seed(c, scope="global", kind="answer"):
    job, call, actor, intent, price, bid, operation, owner = [uuid4() for _ in range(8)]
    policies = [uuid4() for _ in range(3)]
    profile = {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "port": "generation/1",
        "purpose": "assistant" if kind == "answer" else "authoring",
        "formal_scoring_eligible": False,
    }
    digest = "b" * 64
    intent_digest = "c" * 64
    step = "assistant-answer" if kind == "answer" else "authoring-generate"
    handler = "assistant/1" if kind == "answer" else "authoring-generate/1"
    step_digest = sha({"id": str(job), "digest": digest})
    now = datetime.now(UTC)
    before, after = now - timedelta(hours=1), now + timedelta(hours=1)
    manifest = {
        "logical_intent": {"id": str(intent), "profile": profile, "price_version_id": str(price)},
        "request": {"max_tokens": 2048},
    }
    c.execute(
        "INSERT INTO design.assistant_jobs VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (job, kind, scope, bid, operation, actor, Jsonb(manifest), digest, intent_digest),
    )
    c.execute(
        "INSERT INTO design.assistant_logical_intents VALUES(%s,%s,%s,'{}',NULL)",
        (intent, job, actor),
    )
    c.execute(
        "INSERT INTO design.assistant_price_versions VALUES(%s,'deepseek','deepseek-flash',%s,%s,8192,100,'USD',1000000,1000000)",
        (price, before, after),
    )
    for identifier, policy_scope in zip(policies, ["member", "project", "global"], strict=True):
        c.execute(
            "INSERT INTO design.assistant_budget_versions VALUES(%s,%s,'synthetic',1,%s,%s,5000)",
            (identifier, policy_scope, before, after),
        )
    c.execute(
        "INSERT INTO design.assistant_budget_reservations VALUES(%s,%s,%s,'held',NULL,%s,2048,100,'USD',2148,%s,%s,%s,NULL,NULL)",
        (job, intent, actor, price, *policies),
    )
    c.execute(
        "INSERT INTO design.assistant_global_runs VALUES(%s,'running',NULL,%s,2048,%s,1,%s)",
        (job, after, digest, owner),
    )
    c.execute(
        "INSERT INTO design.assistant_global_calls VALUES(%s,%s,'reserved',%s,%s,2048,%s)",
        (
            call,
            job,
            sha(profile),
            intent_digest,
            Jsonb({"reservation": {"owner": str(owner), "fence": 1}}),
        ),
    )
    c.execute(
        "INSERT INTO design.operations VALUES(%s,%s,'running',NULL,%s)", (operation, bid, handler)
    )
    reservation = {
        "max_tokens": 2048,
        "step_key": step,
        "input_digest": step_digest,
        "generation": 1,
        "fence": 1,
        "owner": str(owner),
    }
    c.execute(
        "INSERT INTO design.model_calls VALUES(%s,%s,'reserved',%s,%s,1,NULL,NULL,%s)",
        (
            call,
            operation,
            sha(profile),
            "assistant.answer/1" if kind == "answer" else "authoring.generate/1",
            Jsonb({"reservation": reservation}),
        ),
    )
    c.execute(
        "INSERT INTO design.step_receipts VALUES(%s,'running',%s,%s,%s,1,%s)",
        (operation, after, step, step_digest, owner),
    )
    c.execute(
        "INSERT INTO design.operation_steps VALUES(%s,%s,%s,%s,1)",
        (operation, step, step_digest, handler),
    )
    return job, call


def dispatch(c, job, call):
    return c.execute("SELECT design.assistant_dispatch_budget(%s,%s)", (job, call)).fetchone()[0]


def rejected(c, job, call):
    before = c.execute(
        "SELECT to_jsonb(r) FROM design.assistant_budget_reservations r WHERE job_id=%s", (job,)
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
        dispatch(c, job, call)
    assert (
        c.execute(
            "SELECT to_jsonb(r) FROM design.assistant_budget_reservations r WHERE job_id=%s", (job,)
        ).fetchone()[0]
        == before
    )
    assert (
        c.execute(
            "SELECT count(*) FROM design.assistant_budget_events WHERE job_id=%s", (job,)
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "scope,kind", [("global", "answer"), ("project", "answer"), ("project", "authoring")]
)
def test_valid_native_identity_matches_python_hash_and_dispatches_once(connection, scope, kind):
    job, call = seed(connection, scope, kind)
    result = dispatch(connection, job, call)
    assert result["state"] == "sent"
    assert result["reserved_minor"] == 2148
    with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        dispatch(connection, job, call)
    assert (
        connection.execute(
            "SELECT count(*) FROM design.assistant_budget_events WHERE job_id=%s", (job,)
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("scope", ["global", "project"])
@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE design.assistant_jobs SET input_manifest=jsonb_set(input_manifest,'{logical_intent,profile,model}','\"deepseek-v4-pro\"')",
        "UPDATE design.assistant_jobs SET input_manifest=jsonb_set(input_manifest,'{logical_intent,profile,provider}','\"other\"')",
        "UPDATE design.assistant_jobs SET input_manifest=jsonb_set(input_manifest,'{logical_intent,profile,purpose}','\"core_review\"')",
        "UPDATE design.assistant_jobs SET input_manifest=jsonb_set(input_manifest,'{logical_intent,profile,formal_scoring_eligible}','true')",
        "UPDATE design.assistant_jobs SET input_manifest=jsonb_set(input_manifest,'{logical_intent,profile,extra}','true')",
        "UPDATE design.assistant_jobs SET input_manifest=jsonb_set(input_manifest,'{logical_intent,price_version_id}','\"00000000-0000-0000-0000-000000000000\"')",
        "UPDATE design.assistant_jobs SET input_manifest=jsonb_set(input_manifest,'{request,max_tokens}','8192')",
        "UPDATE design.assistant_jobs SET input_manifest=jsonb_set(input_manifest,'{request,max_tokens}','null')",
        "UPDATE design.assistant_budget_reservations SET output_upper=8192",
        "UPDATE design.assistant_budget_reservations SET input_upper=1",
        "UPDATE design.assistant_budget_reservations SET currency='CNY'",
        "UPDATE design.assistant_budget_reservations SET reserved_minor=1",
        "UPDATE design.assistant_price_versions SET model='deepseek-v4-pro'",
        "UPDATE design.assistant_price_versions SET valid_until=clock_timestamp()-interval '1 hour'",
    ],
)
def test_frozen_profile_price_and_amount_mutations_reject_before_dispatch(
    connection, scope, mutation
):
    job, call = seed(connection, scope)
    connection.execute(mutation)
    rejected(connection, job, call)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE design.assistant_global_calls SET max_tokens=8192; UPDATE design.assistant_global_runs SET max_tokens=8192",
        "UPDATE design.assistant_global_calls SET max_tokens=8192",
        "UPDATE design.assistant_global_runs SET max_tokens=8192",
        "UPDATE design.assistant_global_calls SET profile_digest=repeat('0',64)",
        "UPDATE design.assistant_global_calls SET intent_digest=repeat('0',64)",
        "UPDATE design.assistant_global_runs SET input_digest=repeat('0',64)",
        "UPDATE design.assistant_global_runs SET fence=2,owner_token='00000000-0000-0000-0000-000000000001'",
        "UPDATE design.assistant_global_calls SET usage='{}'",
        "UPDATE design.assistant_global_calls SET usage=jsonb_set(usage,'{reservation,fence}','\"1\"')",
    ],
)
def test_global_native_tampering_rejected(connection, mutation):
    job, call = seed(connection)
    connection.execute(mutation)
    rejected(connection, job, call)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE design.model_calls SET profile_digest=repeat('0',64)",
        "UPDATE design.model_calls SET logical_call_key='core.review/1'",
        "UPDATE design.model_calls SET attempt_no=2",
        "UPDATE design.model_calls SET research_run_id='00000000-0000-0000-0000-000000000001'",
        "UPDATE design.model_calls SET reserved_amount=0.1",
        "UPDATE design.model_calls SET usage=jsonb_set(usage,'{reservation,max_tokens}','8192')",
        "UPDATE design.model_calls SET usage=jsonb_set(usage,'{reservation,step_key}','\"wrong\"')",
        "UPDATE design.model_calls SET usage=jsonb_set(usage,'{reservation,input_digest}','\"wrong\"')",
        "UPDATE design.model_calls SET usage=jsonb_set(usage,'{reservation,generation}','2')",
        "UPDATE design.model_calls SET usage=jsonb_set(usage,'{reservation,fence}','2')",
        "UPDATE design.model_calls SET usage=jsonb_set(usage,'{reservation,owner}','\"wrong\"')",
        "UPDATE design.operations SET handler_version='core/1'",
        "UPDATE design.operation_steps SET handler_version='core/1'",
        "UPDATE design.step_receipts SET lease_until=clock_timestamp()-interval '1 hour'",
    ],
)
def test_project_native_step_and_attempt_tampering_rejected(connection, mutation):
    job, call = seed(connection, "project")
    connection.execute(mutation)
    rejected(connection, job, call)


def test_budget_identity_rpc_error_is_exposed_as_controlled_conflict(connection):
    job, call = seed(connection)
    connection.execute("UPDATE design.assistant_budget_reservations SET reserved_minor=1")
    with pytest.raises(DomainError) as error:
        budget.rpc(connection, "assistant_dispatch_budget", job, call)
    assert error.value.code == "ASSISTANT_BUDGET_IDENTITY_INVALID"
    assert error.value.status == 409
