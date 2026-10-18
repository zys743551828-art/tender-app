"""Actual budget DDL/reserve/obligation in isolated PG17; target authority is a no-op."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.assistant.intent_identity import keys
from packages.domain.runtime import sha

SOURCE = Path(__file__).parents[1] / "packages/assistant/sql/intent-budget.sql"
TABLES = (
    "assistant_price_versions",
    "assistant_budget_versions",
    "assistant_logical_intents",
    "assistant_budget_reservations",
    "assistant_budget_events",
)
FUNCTIONS = (
    "assistant_normalize_question",
    "assistant_budget_obligation",
    "assistant_reserve_budget",
)


def extracted_inputs():
    source = SOURCE.read_text(encoding="utf-8")
    result = {}
    for name in TABLES:
        start = source.index(f"CREATE TABLE design.{name} (")
        result[name] = source[start : source.index(";", start) + 1]
    for name in FUNCTIONS:
        start = source.index(f"CREATE FUNCTION design.{name}(")
        result[name] = source[start : source.index("$$;", source.index("AS $$", start)) + 3]
    return result


@pytest.fixture(scope="module")
def aggregate_database():
    dsn = os.environ.get("FUSION_BUDGET_AGGREGATE_TEST_DSN")
    if not dsn:
        pytest.skip("Explicit disposable fusion_budget_aggregate database required")
    with psycopg.connect(dsn, autocommit=True) as c:
        assert c.info.dbname == "fusion_budget_aggregate"
        assert 170000 <= c.info.server_version < 180000
        c.execute("CREATE SCHEMA design")
        c.execute("CREATE DOMAIN design.sha256 AS text CHECK(VALUE ~ '^[a-f0-9]{64}$')")
        definitions = {
            "members": "id uuid PRIMARY KEY",
            "proposed_actions": "id uuid PRIMARY KEY",
            "assistant_jobs": "id uuid PRIMARY KEY,actor_id uuid,origin_action_id uuid,kind text,input_manifest jsonb,intent_digest text,operation_id uuid",
            "model_calls": "id uuid PRIMARY KEY,operation_id uuid,state text",
            "assistant_global_calls": "id uuid PRIMARY KEY,run_id uuid,state text",
            "operations": "id uuid PRIMARY KEY,state text",
            "assistant_global_runs": "id uuid PRIMARY KEY,state text",
            "section_revisions": "section_id uuid,digest text",
        }
        for name, definition in definitions.items():
            c.execute(f"CREATE TABLE design.{name}({definition})")
        for statement in extracted_inputs().values():
            c.execute(statement)
        c.execute(
            "CREATE FUNCTION design.assistant_check_target(jsonb,uuid) RETURNS void LANGUAGE plpgsql AS $$ BEGIN RETURN; END $$"
        )
        c.execute(
            "CREATE FUNCTION design.assistant_assert_job_authority(uuid) RETURNS void LANGUAGE plpgsql AS $$ BEGIN RETURN; END $$"
        )
    try:
        yield dsn
    finally:
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("DROP SCHEMA design CASCADE")


def connect(dsn):
    c = psycopg.connect(dsn, row_factory=dict_row)
    c.execute("SET LOCAL search_path=design,public")
    c.execute("SET LOCAL statement_timeout='5s'")
    c.execute("SET LOCAL lock_timeout='3s'")
    return c


@pytest.fixture
def world(aggregate_database):
    dsn = aggregate_database
    with connect(dsn) as c:
        c.execute(
            "TRUNCATE design.members,design.proposed_actions,design.assistant_jobs,design.model_calls,design.assistant_global_calls,design.operations,design.assistant_global_runs,design.section_revisions,design.assistant_price_versions,design.assistant_budget_versions CASCADE"
        )
        actor, other, price = uuid4(), uuid4(), uuid4()
        project, other_project = sha("synthetic-project-a"), sha("synthetic-project-b")
        for member in (actor, other):
            c.execute("INSERT INTO members VALUES(%s)", (member,))
        now = datetime.now(UTC)
        c.execute(
            """INSERT INTO assistant_price_versions(id,version,provider,model,currency,input_per_million_minor,output_per_million_minor,input_hard_ceiling,output_hard_ceiling,source_kind,source_uri,source_sha256,verified_at,valid_from,valid_until)
            VALUES(%s,'synthetic-v1','deepseek','deepseek-flash','USD',1000000,1000000,10,8192,'explicit_mock_fixture','https://synthetic.invalid/tariff',%s,%s,%s,%s)""",
            (price, "a" * 64, now, now - timedelta(hours=1), now + timedelta(hours=1)),
        )
        policies = {}
        for scope, owner in [
            ("global", "assistant"),
            ("member", str(actor)),
            ("member", str(other)),
            ("project", project),
            ("project", other_project),
        ]:
            identity = uuid4()
            c.execute(
                """INSERT INTO assistant_budget_versions(id,scope,owner_key,currency,revision,limit_minor,window_from,window_until,configured_reason)
                VALUES(%s,%s,%s,'USD',1,1000,%s,%s,'synthetic limit')""",
                (identity, scope, owner, now - timedelta(hours=1), now + timedelta(hours=1)),
            )
            policies[scope, owner] = identity
    return {
        "dsn": dsn,
        "actor": actor,
        "other": other,
        "project": project,
        "other_project": other_project,
        "price": price,
        "policies": policies,
    }


def candidate(world, actor=None, project=None, *, general=False):
    actor, project = actor or world["actor"], project or world["project"]
    job, intent, target_id = uuid4(), uuid4(), uuid4()
    target_key = "general:" + str(actor) if general else project + ":finding:" + str(target_id)
    purpose = "general_reference" if general else "finding_explanation"
    normalized, coarse, anti = keys(
        "synthetic independent finding " + str(target_id), target_key, purpose
    )
    target = {
        "kind": "finding",
        "id": str(target_id),
        "purpose": "finding_explanation",
        "target_key": target_key,
        "canonical_project_key": project,
    }
    if general:
        project = None
        target = {
            "kind": "general",
            "id": None,
            "proof": None,
            "purpose": purpose,
            "target_key": target_key,
            "canonical_project_key": None,
        }
    manifest = {
        "request": {"text": normalized, "max_tokens": 10},
        "logical_intent": {
            "id": str(intent),
            "target": target,
            "explicit_send": True,
            "price_version_id": str(world["price"]),
        },
    }
    with connect(world["dsn"]) as c:
        c.execute(
            "INSERT INTO assistant_jobs VALUES(%s,%s,NULL,'answer',%s,%s,NULL)",
            (job, actor, Jsonb(manifest), anti),
        )
        c.execute(
            """INSERT INTO assistant_logical_intents(id,job_id,actor_id,request_mode,normalized_question,purpose,target_key,coarse_key,anti_resend_key,canonical_project_key,target,explicit_send)
            VALUES(%s,%s,%s,'new_question',%s,%s,%s,%s,%s,%s,%s,true)""",
            (
                intent,
                job,
                actor,
                normalized,
                purpose,
                target_key,
                coarse,
                anti,
                project,
                Jsonb(target),
            ),
        )
    return job


def reserve(dsn, job, barrier=None):
    try:
        with connect(dsn) as c:
            if barrier:
                barrier.wait(timeout=3)
            result = c.execute(
                "SELECT design.assistant_reserve_budget(%s) AS value", (job,)
            ).fetchone()["value"]
        return result
    except psycopg.errors.CheckViolation as error:
        return error.diag.message_primary


@pytest.mark.parametrize("scope", ["global", "member", "project"])
def test_actual_three_scope_concurrent_admission_cannot_overspend(world, scope):
    owner = {"global": "assistant", "member": str(world["actor"]), "project": world["project"]}[
        scope
    ]
    policy = world["policies"][scope, owner]
    with connect(world["dsn"]) as c:
        c.execute("UPDATE assistant_budget_versions SET limit_minor=30 WHERE id=%s", (policy,))
    jobs = [candidate(world), candidate(world)]
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, world["dsn"], job, barrier) for job in jobs]
        results = [future.result(timeout=7) for future in futures]
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("ASSISTANT_BUDGET_EXHAUSTED") == 1
    with connect(world["dsn"]) as c:
        assert (
            c.execute(
                "SELECT design.assistant_budget_obligation(%s) AS amount", (policy,)
            ).fetchone()["amount"]
            == 20
        )
        assert (
            c.execute("SELECT count(*) AS n FROM assistant_budget_reservations").fetchone()["n"]
            == 1
        )


def test_project_budget_is_shared_across_members(world):
    policy = world["policies"]["project", world["project"]]
    with connect(world["dsn"]) as c:
        c.execute("UPDATE assistant_budget_versions SET limit_minor=30 WHERE id=%s", (policy,))
    assert isinstance(reserve(world["dsn"], candidate(world)), dict)
    assert (
        reserve(world["dsn"], candidate(world, actor=world["other"]))
        == "ASSISTANT_BUDGET_EXHAUSTED"
    )


def test_member_budget_is_shared_across_projects(world):
    policy = world["policies"]["member", str(world["actor"])]
    with connect(world["dsn"]) as c:
        c.execute("UPDATE assistant_budget_versions SET limit_minor=30 WHERE id=%s", (policy,))
    assert isinstance(reserve(world["dsn"], candidate(world)), dict)
    assert (
        reserve(world["dsn"], candidate(world, project=world["other_project"]))
        == "ASSISTANT_BUDGET_EXHAUSTED"
    )


@pytest.mark.parametrize("scope", ["member", "project"])
def test_distinct_scope_owners_do_not_share_that_limit(world, scope):
    owner = str(world["actor"]) if scope == "member" else world["project"]
    with connect(world["dsn"]) as c:
        c.execute(
            "UPDATE assistant_budget_versions SET limit_minor=20 WHERE id=%s",
            (world["policies"][scope, owner],),
        )
    assert isinstance(reserve(world["dsn"], candidate(world)), dict)
    second = (
        candidate(world, actor=world["other"])
        if scope == "member"
        else candidate(world, project=world["other_project"])
    )
    assert isinstance(reserve(world["dsn"], second), dict)


def test_prior_window_unknown_retains_original_obligation(world):
    job = candidate(world)
    assert isinstance(reserve(world["dsn"], job), dict)
    current_policy = uuid4()
    with connect(world["dsn"]) as c:
        call = uuid4()
        c.execute("INSERT INTO assistant_global_calls VALUES(%s,%s,'unknown')", (call, job))
        c.execute(
            "UPDATE assistant_budget_reservations SET state='unknown',global_call_id=%s,dispatched_at=clock_timestamp() WHERE job_id=%s",
            (call, job),
        )
        c.execute(
            """INSERT INTO assistant_budget_versions(id,scope,owner_key,currency,revision,limit_minor,window_from,window_until,configured_reason)
            VALUES(%s,'global','assistant','USD',2,30,clock_timestamp(),clock_timestamp()+interval '1 hour','next synthetic window')""",
            (current_policy,),
        )
        assert (
            c.execute(
                "SELECT design.assistant_budget_obligation(%s) AS amount", (current_policy,)
            ).fetchone()["amount"]
            == 20
        )
    assert reserve(world["dsn"], candidate(world)) == "ASSISTANT_BUDGET_EXHAUSTED"


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_mismatched_currency_policy_fails_closed(world, missing):
    with connect(world["dsn"]) as c:
        policy = world["policies"]["member", str(world["actor"])]
        if missing:
            c.execute("DELETE FROM assistant_budget_versions WHERE id=%s", (policy,))
        else:
            c.execute("UPDATE assistant_budget_versions SET currency='CNY' WHERE id=%s", (policy,))
    assert reserve(world["dsn"], candidate(world)) == "ASSISTANT_BUDGET_NOT_CONFIGURED"


def test_global_budget_combines_distinct_members_and_projects(world):
    with connect(world["dsn"]) as c:
        c.execute(
            "UPDATE assistant_budget_versions SET limit_minor=30 WHERE id=%s",
            (world["policies"]["global", "assistant"],),
        )
    assert isinstance(reserve(world["dsn"], candidate(world)), dict)
    assert (
        reserve(
            world["dsn"], candidate(world, actor=world["other"], project=world["other_project"])
        )
        == "ASSISTANT_BUDGET_EXHAUSTED"
    )


@pytest.mark.parametrize("general", [False, True])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_non_read_committed_rpc_rejects_general_and_project_before_side_effects(
    world, general, isolation
):
    job = candidate(world, general=general)
    with psycopg.connect(world["dsn"]) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
        with (
            pytest.raises(
                psycopg.errors.InvalidTransactionState, match="ASSISTANT_REQUIRES_READ_COMMITTED"
            ),
            c.transaction(),
        ):
            c.execute("SELECT design.assistant_reserve_budget(%s)", (job,))
    with connect(world["dsn"]) as c:
        assert (
            c.execute("SELECT count(*) AS n FROM assistant_budget_reservations").fetchone()["n"]
            == 0
        )
        assert c.execute("SELECT count(*) AS n FROM assistant_budget_events").fetchone()["n"] == 0
        assert (
            c.execute(
                "SELECT count(*) AS n FROM assistant_logical_intents WHERE job_id=%s", (job,)
            ).fetchone()["n"]
            == 1
        )


def test_general_target_is_valid_under_read_committed(world):
    result = reserve(world["dsn"], candidate(world, general=True))
    assert isinstance(result, dict) and result["reserved_minor"] == 20
