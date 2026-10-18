"""Full fresh schemas and actual native fact confirmation/authority/budget; no provider I/O."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_bid_package_repository import add_document, seed

from deploy.bootstrap_fresh import BASE_SQL, ROOT
from packages.assistant import context, conversations, global_runtime, intent_identity, jobs
from packages.domain.fact_sets import replace_set
from packages.domain.human_decisions import append_decision
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.runtime import etag, sha
from packages.rag.indexing import ensure_parse_sources, withdraw_source


@pytest.fixture(scope="module")
def live_database():
    dsn = os.environ.get("FUSION_BUDGET_LIVE_TEST_DSN")
    if not dsn:
        pytest.skip("Explicit disposable fusion_budget_live database required")
    with psycopg.connect(dsn, autocommit=True) as c:
        assert c.info.dbname == "fusion_budget_live"
        assert 170000 <= c.info.server_version < 180000
        assert c.execute("SELECT to_regnamespace('design') IS NULL").fetchone()[0]
        for path in (
            *BASE_SQL,
            "packages/assistant/sql/assistant.sql",
            "packages/assistant/sql/live-facts.sql",
            "packages/assistant/sql/intent-budget.sql",
        ):
            c.execute((ROOT / path).read_text(encoding="utf-8"))
    try:
        yield dsn
    finally:
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("DROP SCHEMA design,retrieval CASCADE")


def connect(dsn):
    c = psycopg.connect(dsn, row_factory=dict_row)
    c.execute("SET LOCAL search_path=design,public")
    c.execute("SET LOCAL statement_timeout='8s'")
    return c


@pytest.fixture
def world(live_database, monkeypatch, request):
    monkeypatch.setenv("WORKBENCH_ENV_FILE", "explicit-live-test-no-profile")
    transport = httpx.MockTransport(lambda request: pytest.fail("No model HTTP permitted"))
    monkeypatch.setattr(
        DeepSeekClient,
        "from_env",
        lambda: SimpleNamespace(model="deepseek-flash", _transport=transport),
    )
    with connect(live_database) as c:
        try:
            w = seed(c)
            bid, actor = UUID(w["scope"].bid_id), UUID(w["actor"])
            member = w["member"]
            version, parse = UUID(member.document_version_id), UUID(member.parse.parse_run_id)
            c.execute("UPDATE bid_profiles SET current_body_id=%s WHERE bid_id=%s", (version, bid))
            root, source = ensure_parse_sources(c, bid, parse, publish_readable=True)
            if getattr(request, "param", {}).get("expires"):
                c.execute(
                    "UPDATE retrieval.source_heads SET valid_until=clock_timestamp()+interval '5 seconds' WHERE source_id=%s",
                    (source,),
                )
            evidence = c.execute(
                "SELECT id FROM evidence_blocks WHERE parse_id=%s ORDER BY physical_page,ordinal LIMIT 1",
                (parse,),
            ).fetchone()["id"]
            other_evidence = evidence
            if getattr(request, "param", {}).get("separate_first"):
                other = add_document(c, w["scope"], w["actor"])
                snapshot = uuid4()
                c.execute(
                    "INSERT INTO material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,1,'{}',%s)",
                    (snapshot, bid, sha({})),
                )
                c.execute(
                    "INSERT INTO material_assignments VALUES(%s,%s,%s,'other',0)",
                    (snapshot, bid, UUID(other.document_version_id)),
                )
                c.execute(
                    "UPDATE bid_profiles SET current_material_id=%s WHERE bid_id=%s",
                    (snapshot, bid),
                )
                ensure_parse_sources(c, bid, UUID(other.parse.parse_run_id), publish_readable=True)
                other_evidence = c.execute(
                    "SELECT id FROM evidence_blocks WHERE parse_id=%s ORDER BY physical_page,ordinal LIMIT 1",
                    (UUID(other.parse.parse_run_id),),
                ).fetchone()["id"]
            for index, name in enumerate(intent_identity.IDENTITY_FACTS):
                replace_set(
                    c,
                    bid,
                    actor,
                    "native synthetic identity fact",
                    kind="add",
                    new_fact={
                        "subject": "project",
                        "scope": "current bid",
                        "name": name,
                        "value": "synthetic-" + name + ":" + str(bid),
                        "unit": None,
                        "evidence_ids": [str(evidence if index == 0 else other_evidence)],
                        "reason": "native original-page confirmation",
                    },
                )
            identity = intent_identity.project_identity(c, bid)
            price = uuid4()
            c.execute(
                """INSERT INTO assistant_price_versions(id,version,provider,model,currency,input_per_million_minor,output_per_million_minor,input_hard_ceiling,output_hard_ceiling,source_kind,source_uri,source_sha256,verified_at,valid_from,valid_until)
              VALUES(%s,%s,'deepseek','deepseek-flash','USD',1000000,1000000,100,8192,'explicit_mock_fixture','https://synthetic.invalid/tariff',%s,clock_timestamp(),clock_timestamp()-interval '1 hour',clock_timestamp()+interval '1 hour')""",
                (price, str(price), "a" * 64),
            )
            for scope, owner in [
                ("global", "assistant"),
                ("member", str(actor)),
                ("project", identity["canonical_project_key"]),
            ]:
                c.execute(
                    """INSERT INTO assistant_budget_versions(id,scope,owner_key,currency,revision,limit_minor,window_from,window_until,configured_reason)
                 VALUES(%s,%s,%s,'USD',(SELECT coalesce(max(revision),0)+1 FROM assistant_budget_versions WHERE scope=%s AND owner_key=%s),1000000,clock_timestamp()-interval '1 hour',clock_timestamp()+interval '1 hour','native synthetic test limit')""",
                    (uuid4(), scope, owner, scope, owner),
                )
            command = uuid4()
            c.execute(
                "INSERT INTO commands(id,actor_id,command_kind,target_id,idempotency_key,request_digest) VALUES(%s,%s,'synthetic.assistant',%s,%s,%s)",
                (command, actor, bid, str(command), sha(str(command))),
            )
            conversation = conversations.ensure_main(c, bid, actor, command)
            yield w | {
                "c": c,
                "bid": bid,
                "actor": actor,
                "root": root,
                "source": source,
                "parse": parse,
                "version": version,
                "command": command,
                "conversation": conversation,
                "identity": identity,
                "dsn": live_database,
            }
        finally:
            c.rollback()


def queue(w):
    return jobs.queue_answer(
        w["c"],
        w["actor"],
        UUID(w["conversation"]["id"]),
        {
            "client_message_id": str(uuid4()),
            "text": "Explain this actual project identity",
            "source_selection": [],
            "max_tokens": 10,
        },
        w["command"],
        bid=w["bid"],
        condition=etag("conversation", w["conversation"]["id"], w["conversation"]["revision"]),
    )


def target(w):
    return intent_identity.resolve(w["c"], w["actor"], {}, w["bid"])


def test_native_carryover_five_facts_match_actual_sql_authority(world):
    t = target(world)
    for proof in t["proof"]["identity_facts"]:
        world["c"].execute(
            "SELECT design.assistant_assert_live_fact(%s,%s)", (world["bid"], Jsonb(proof))
        )
    assert queue(world)["budget"]["state"] == "held"


@pytest.mark.parametrize("which", ["root", "source"])
def test_only_withdrawing_source_without_fact_changes_rejects_frozen_live_proof(world, which):
    t = target(world)
    c = world["c"]
    revision = c.execute(
        "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (world[which],)
    ).fetchone()["revision"]
    if which == "root":
        withdraw_source(c, world["bid"], world[which], revision)
    else:
        c.execute("SELECT pg_advisory_xact_lock(90127,1)")
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (world["source"],),
        )
    for proof in t["proof"]["identity_facts"]:
        with (
            pytest.raises(
                psycopg.errors.CheckViolation, match="ASSISTANT_TARGET_IDENTITY_UNPROVEN"
            ),
            c.transaction(),
        ):
            c.execute(
                "SELECT design.assistant_assert_live_fact(%s,%s)", (world["bid"], Jsonb(proof))
            )


def native_call(w, result):
    c = w["c"]
    job_id = UUID(result["id"])
    row = jobs.job(c, job_id)
    op = row["operation_id"]
    owner, call = uuid4(), uuid4()
    plan = c.execute("SELECT * FROM operation_steps WHERE operation_id=%s", (op,)).fetchone()
    c.execute("UPDATE operations SET state='running' WHERE id=%s", (op,))
    c.execute(
        """INSERT INTO step_receipts(operation_id,step_key,input_digest,fence,attempt_count,state,owner_token,lease_until)
      VALUES(%s,%s,%s,1,1,'running',%s,clock_timestamp()+interval '120 seconds')""",
        (op, plan["step_key"], plan["input_digest"], owner),
    )
    reservation = {
        "max_tokens": 10,
        "step_key": plan["step_key"],
        "input_digest": plan["input_digest"],
        "generation": plan["dispatch_generation"],
        "fence": 1,
        "owner": str(owner),
    }
    c.execute(
        """INSERT INTO model_calls(id,operation_id,logical_call_key,attempt_no,request_digest,profile_digest,state,usage)
      VALUES(%s,%s,'assistant.answer/1',1,%s,%s,'reserved',%s)""",
        (
            call,
            op,
            sha("synthetic request"),
            sha(row["input_manifest"]["logical_intent"]["profile"]),
            Jsonb({"reservation": reservation}),
        ),
    )
    return job_id, call


def mutate_live(w, change):
    c = w["c"]
    if change in {"root", "source"}:
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (w[change],),
        )
    elif change == "expired":
        c.execute(
            "UPDATE retrieval.source_heads SET valid_from=clock_timestamp()-interval '1 hour',valid_until=clock_timestamp()-interval '1 millisecond' WHERE source_id=%s",
            (w["source"],),
        )
    elif change == "role":
        c.execute("UPDATE bid_profiles SET current_body_id=NULL WHERE bid_id=%s", (w["bid"],))
    elif change == "new_parse":
        c.execute(
            """INSERT INTO parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps,created_at)
          VALUES(%s,%s,%s,%s,%s,2,'complete','[]',clock_timestamp())""",
            (uuid4(), w["bid"], w["version"], "b" * 64, "c" * 64),
        )


@pytest.mark.parametrize("change", ["root", "source", "expired", "role", "new_parse"])
@pytest.mark.parametrize("stage", ["reserve", "dispatch"])
def test_actual_budget_rpcs_reject_changed_live_facts_without_releasing_hold(world, change, stage):
    c = world["c"]
    result = queue(world)
    job, call = native_call(world, result)
    mutate_live(world, change)
    before = c.execute(
        "SELECT to_jsonb(r) AS value FROM assistant_budget_reservations r WHERE job_id=%s", (job,)
    ).fetchone()["value"]
    events = c.execute(
        "SELECT count(*) AS n FROM assistant_budget_events WHERE job_id=%s", (job,)
    ).fetchone()["n"]
    query, args = (
        ("SELECT design.assistant_reserve_budget(%s)", (job,))
        if stage == "reserve"
        else ("SELECT design.assistant_dispatch_budget(%s,%s)", (job, call))
    )
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="ASSISTANT_TARGET_IDENTITY_UNPROVEN"),
        c.transaction(),
    ):
        c.execute(query, args)
    assert (
        c.execute(
            "SELECT to_jsonb(r) AS value FROM assistant_budget_reservations r WHERE job_id=%s",
            (job,),
        ).fetchone()["value"]
        == before
    )
    assert (
        c.execute(
            "SELECT count(*) AS n FROM assistant_budget_events WHERE job_id=%s", (job,)
        ).fetchone()["n"]
        == events
    )


def test_actual_dispatch_accepts_valid_native_carryover_basis(world):
    result = queue(world)
    job, call = native_call(world, result)
    saved = (
        world["c"]
        .execute("SELECT design.assistant_dispatch_budget(%s,%s) AS value", (job, call))
        .fetchone()["value"]
    )
    assert saved["state"] == "sent" and saved["reserved_minor"] == 110


@pytest.mark.parametrize(
    "change", ["missing_basis", "closure", "fact_identity", "missing_reference"]
)
def test_forged_or_missing_native_proof_cannot_grant_qualification(world, change):
    proof = target(world)["proof"]["identity_facts"][0]
    if change == "missing_basis":
        del proof["basis"]
    elif change == "closure":
        proof["source_closure"] = proof["source_closure"][:-1]
    elif change == "fact_identity":
        proof["basis"]["fact_identity"] = "0" * 64
    else:
        proof["basis"]["evidence"]["references"] = []
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="ASSISTANT_TARGET_IDENTITY_UNPROVEN"),
        world["c"].transaction(),
    ):
        world["c"].execute(
            "SELECT design.assistant_assert_live_fact(%s,%s)", (world["bid"], Jsonb(proof))
        )


def concurrent_dispatch(w, job, call, blocker):
    graph_locked, dispatched = Event(), Event()

    def hold_graph():
        with connect(w["dsn"]) as c:
            c.execute("SELECT pg_advisory_xact_lock(90127,1)")
            graph_locked.set()
            assert dispatched.wait(timeout=3)
            blocker(c)

    def send_gate():
        assert graph_locked.wait(timeout=3)
        try:
            with connect(w["dsn"]) as c:
                dispatched.set()
                c.execute("SELECT design.assistant_dispatch_budget(%s,%s)", (job, call))
        except psycopg.errors.CheckViolation as error:
            return error.diag.message_primary
        return "unexpected-authorized"

    with ThreadPoolExecutor(max_workers=2) as pool:
        held, sent = pool.submit(hold_graph), pool.submit(send_gate)
        held.result(timeout=10)
        assert sent.result(timeout=10) == "ASSISTANT_TARGET_IDENTITY_UNPROVEN"
    with connect(w["dsn"]) as c:
        assert c.execute(
            "SELECT state,reserved_minor FROM assistant_budget_reservations WHERE job_id=%s", (job,)
        ).fetchone() == {"state": "held", "reserved_minor": 110}
        assert (
            c.execute(
                "SELECT count(*) AS n FROM assistant_budget_events WHERE job_id=%s AND event_type='dispatched'",
                (job,),
            ).fetchone()["n"]
            == 0
        )


def test_actual_withdrawal_wins_dispatch_race_without_deadlock_or_fee_release(world):
    job, call = native_call(world, queue(world))
    world["c"].commit()

    def withdrawing(c):
        revision = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (world["root"],)
        ).fetchone()["revision"]
        withdraw_source(c, world["bid"], world["root"], revision)

    concurrent_dispatch(world, job, call, withdrawing)


@pytest.mark.parametrize("world", [{"expires": True}], indirect=True)
def test_source_expiring_while_waiting_for_graph_is_rechecked_at_dispatch(world):
    job, call = native_call(world, queue(world))
    world["c"].commit()

    def wait_until_expired(c):
        delay = c.execute(
            "SELECT greatest(extract(epoch FROM valid_until-clock_timestamp()),0) AS seconds FROM retrieval.source_heads WHERE source_id=%s",
            (world["source"],),
        ).fetchone()["seconds"]
        assert 0 <= delay <= 6
        Event().wait(float(delay) + 0.1)

    concurrent_dispatch(world, job, call, wait_until_expired)


def test_actual_global_reserve_locks_target_bid_before_run_and_does_not_deadlock(
    world, monkeypatch
):
    c = world["c"]
    main = jobs.ensure_global(c, world["actor"], world["command"])
    ref = {"kind": "project", "id": str(world["bid"]), "trace_id": None}
    ref["version"] = context.resolve(c, ref)["version"]
    result = jobs.queue_answer(
        c,
        world["actor"],
        UUID(main["id"]),
        {
            "client_message_id": str(uuid4()),
            "text": "Global synthetic project reference",
            "source_selection": [ref],
            "target": {"kind": "project", "id": str(world["bid"])},
            "max_tokens": 10,
        },
        world["command"],
        condition=etag("conversation", main["id"], main["revision"]),
    )
    row = jobs.job(c, UUID(result["id"]))
    lease = {"owner": uuid4(), "fence": 1}
    c.execute(
        "UPDATE assistant_global_runs SET state='running',fence=1,owner_token=%s,lease_until=clock_timestamp()+interval '120 seconds' WHERE id=%s",
        (lease["owner"], row["id"]),
    )
    c.commit()
    monkeypatch.setattr(global_runtime, "connection", lambda *_: connect(world["dsn"]))
    attempted, bid_locked = Event(), Event()
    actual_lock = global_runtime.lock_job_target

    def target_lock(connection, frozen):
        attempted.set()
        return actual_lock(connection, frozen)

    monkeypatch.setattr(global_runtime, "lock_job_target", target_lock)

    def ordinary_bid_then_run():
        with connect(world["dsn"]) as connection:
            connection.execute("SELECT id FROM bids WHERE id=%s FOR UPDATE", (world["bid"],))
            bid_locked.set()
            assert attempted.wait(timeout=3)
            connection.execute(
                "SELECT id FROM assistant_global_runs WHERE id=%s FOR UPDATE", (row["id"],)
            )

    def global_reserve():
        assert bid_locked.wait(timeout=3)
        return global_runtime.reserve(
            row, lease, {"max_tokens": 10}, row["input_manifest"]["logical_intent"]["profile"]
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner, reserved = pool.submit(ordinary_bid_then_run), pool.submit(global_reserve)
        owner.result(timeout=8)
        call, created = reserved.result(timeout=8)
    assert created and call["usage"]["reservation"]["owner"] == str(lease["owner"])


def test_native_confirmed_decision_without_basis_is_never_inferred(world):
    c = world["c"]
    proof = target(world)["proof"]["identity_facts"][0]
    decision = append_decision(
        c,
        world["bid"],
        world["actor"],
        "fact",
        UUID(proof["id"]),
        {
            "decision": "confirmed",
            "reason": "synthetic missing immutable basis",
            "evidence_ids": proof["evidence_ids"],
        },
        basis=None,
    )
    proof["decision_id"] = str(decision["id"])
    proof["basis"] = None
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="ASSISTANT_TARGET_IDENTITY_UNPROVEN"),
        c.transaction(),
    ):
        c.execute("SELECT design.assistant_assert_live_fact(%s,%s)", (world["bid"], Jsonb(proof)))


def test_latest_native_carryover_mapping_must_keep_original_equivalence_digest(world):
    c = world["c"]
    proof = target(world)["proof"]["identity_facts"][0]
    c.execute(
        """INSERT INTO audit_entries(id,actor_id,bid_id,event_type,payload,created_at)
      VALUES(%s,%s,%s,'facts.set_replaced',%s,clock_timestamp())""",
        (
            uuid4(),
            world["actor"],
            world["bid"],
            Jsonb(
                {
                    "carryovers": [
                        {
                            "new_fact_id": proof["id"],
                            "from_fact_id": str(uuid4()),
                            "from_decision_id": proof["decision_id"],
                            "equivalence_digest": "0" * 64,
                        }
                    ]
                }
            ),
        ),
    )
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="ASSISTANT_TARGET_IDENTITY_UNPROVEN"),
        c.transaction(),
    ):
        c.execute("SELECT design.assistant_assert_live_fact(%s,%s)", (world["bid"], Jsonb(proof)))


def test_new_internal_helpers_do_not_confer_worker_or_public_fact_access(world):
    for signature in (
        "design.assistant_assert_live_fact(uuid,jsonb)",
        "design.assistant_assert_job_authority(uuid)",
    ):
        row = (
            world["c"]
            .execute(
                """SELECT has_function_privilege('tender_worker',%s,'EXECUTE') AS worker,
          EXISTS(SELECT FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=to_regprocedure(%s) AND a.grantee=0 AND a.privilege_type='EXECUTE') AS public""",
                (signature, signature),
            )
            .fetchone()
        )
        assert row == {"worker": False, "public": False}


@pytest.mark.parametrize("world", [{"expires": True, "separate_first": True}], indirect=True)
def test_one_final_clock_rechecks_early_fact_after_later_fact_processing(world):
    c = world["c"]
    result = queue(world)
    source = (ROOT / "packages/assistant/sql/live-facts.sql").read_text(encoding="utf-8")
    start = source.index("CREATE FUNCTION design.assistant_assert_live_fact(")
    actual = source[start : source.index("END $$;", start) + len("END $$;")]
    c.execute(
        actual.replace(
            "design.assistant_assert_live_fact(", "design.assistant_assert_live_fact_unpaused(", 1
        )
    )
    c.execute(
        "REVOKE ALL ON FUNCTION design.assistant_assert_live_fact_unpaused(uuid,jsonb) FROM PUBLIC"
    )
    # The fixture adds delay only after the real last fact check. Its source is
    # unbounded; the first fact alone expires during that processing interval.
    c.execute(f"""CREATE OR REPLACE FUNCTION design.assistant_assert_live_fact(bid uuid,proof jsonb) RETURNS void
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
      DECLARE delay numeric; BEGIN
       PERFORM design.assistant_assert_live_fact_unpaused(bid,proof);
       IF proof->>'name'='bidder_identity_identifier' THEN
        SELECT greatest(extract(epoch FROM valid_until-clock_timestamp()),0) INTO delay
         FROM retrieval.source_heads WHERE source_id='{world["source"]}'::uuid;
        PERFORM pg_sleep(delay::double precision+0.05);
       END IF;
      END $$""")
    remaining = c.execute(
        "SELECT extract(epoch FROM valid_until-clock_timestamp()) AS seconds FROM retrieval.source_heads WHERE source_id=%s",
        (world["source"],),
    ).fetchone()["seconds"]
    assert 0.2 < remaining <= 5
    started = monotonic()
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="ASSISTANT_TARGET_IDENTITY_UNPROVEN"),
        c.transaction(),
    ):
        c.execute("SELECT design.assistant_assert_job_authority(%s)", (UUID(result["id"]),))
    assert monotonic() - started >= float(remaining)
