"""Real native outbox, purpose leases and optional isolated real Kafka transport."""

# ruff: noqa: F401,F811
import asyncio
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import psycopg
import pytest
from confluent_kafka import TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from test_material_execution_attempts_pg import WORKER as EXECUTION_WORKER
from test_material_execution_attempts_pg import begin_args, payload
from test_material_execution_attempts_pg import database as execution_database
from test_package_technical_material import Stream
from test_preparation_leases_pg import (
    ADMIN_DSN,
    api,
    exact,
    pdf_data,
    requirements,
    saved,
    wire,
    world,
)
from test_preparation_leases_pg import ready as preparation_ready

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_execution_dispatch as dispatch
from packages.model_governance import material_execution_runtime as runtime
from packages.model_governance import material_preparation_leases as preparation
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_DISPATCH_PG") != "1",
    reason="explicit isolated material dispatch native fixture required",
)
RELAY = "fusion_material_dispatch_relay"
WORKER = "fusion_material_dispatch_worker"
OTHER = "fusion_other_material_dispatch_worker"
BOOTSTRAP = os.environ.get("FUSION_MATERIAL_DISPATCH_KAFKA_BOOTSTRAP")


@pytest.fixture(scope="module")
def database():
    base = execution_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    installed = False
    try:
        owner.execute(dispatch.SQL_FILE.read_text(encoding="utf-8"))
        installed = True
        factories = {}
        for role, purpose in ((RELAY, "relay"), (WORKER, "worker"), (OTHER, "worker")):
            assert (
                owner.execute(
                    "SELECT 1 AS present FROM pg_roles WHERE rolname=%s", (role,)
                ).fetchone()
                is None
            )
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            created.append(role)
            owner.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(dispatch.GROUPS[purpose]), sql.Identifier(role)
                )
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=role, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[role] = factory
        with (
            factories[RELAY]() as relay,
            factories[WORKER]() as worker,
            factories[OTHER]() as other,
        ):
            yield value | {
                "dispatch_relay": relay,
                "dispatch_relay_factory": factories[RELAY],
                "dispatch_worker": worker,
                "dispatch_worker_factory": factories[WORKER],
                "other_dispatch_worker": other,
            }
    finally:
        try:
            next(base)
        except StopIteration:
            pass
        finally:
            if installed:
                with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
                    for role in created + list(dispatch.GROUPS.values()):
                        admin.execute(
                            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                        )


def insert_profile(owner, schema, values):
    owner.execute(
        sql.SQL("INSERT INTO {}.profiles ({}) VALUES ({})").format(
            sql.Identifier(schema),
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    return owner.execute(
        sql.SQL(
            "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') AS v FROM {}.profiles p WHERE id=%s"
        ).format(sql.Identifier(schema)),
        (values["id"],),
    ).fetchone()["v"]


def prepare(
    wire, monkeypatch, *, mode="production_admission", dispatch_seconds=120, profile_seconds=3600
):
    w, state, url = wire
    data, job, prep_args = preparation_ready(wire, monkeypatch, lease_seconds=120)
    owner = w["database"]["owner"]
    now = datetime.now(timezone.utc)
    db_oid = owner.execute(
        "SELECT oid FROM pg_database WHERE datname=current_database()"
    ).fetchone()["oid"]
    oids = {
        name: owner.execute("SELECT oid FROM pg_roles WHERE rolname=%s", (name,)).fetchone()["oid"]
        for name in (RELAY, WORKER, EXECUTION_WORKER)
    }
    execution_id = execution_digest = account_id = None
    if mode == "synthetic_mechanism":
        account_id = str(uuid4())
        owner.execute(
            "INSERT INTO material_execution.accounts VALUES(%s,%s,90000000,'synthetic_mechanism')",
            (account_id, job.metadata["document"]["currency"]),
        )
        owner.execute("INSERT INTO material_execution.balances VALUES(%s,0,0)", (account_id,))
        values = {
            "id": str(uuid4()),
            "worker_login": EXECUTION_WORKER,
            "worker_login_oid": oids[EXECUTION_WORKER],
            "preparation_profile_id": prep_args["profile_id"],
            "preparation_profile_digest": prep_args["expected_profile_digest"],
            "account_id": account_id,
            "origin": "synthetic_mechanism",
            "execution_method_digest": execution.method_digest(),
            "execution_sql_method_digest": owner.execute(
                "SELECT material_execution.native_method_digest() AS v"
            ).fetchone()["v"],
            "preflight_method_digest": preflight.method_digest(),
            "serializer_digest": vision.serializer_digest(),
            "provider_profile_digest": vision.profile_digest(),
            "judgment_method_digest": vision.judgment_method_digest(),
            "database_oid": db_oid,
            "database_name": owner.info.dbname,
            "valid_from": now - timedelta(minutes=1),
            "valid_until": now + timedelta(hours=1),
        }
        execution_id = values["id"]
        execution_digest = insert_profile(owner, "material_execution", values)
        owner.execute(
            "INSERT INTO material_execution.profile_heads VALUES(%s,%s,1,true) ON CONFLICT(worker_login) DO UPDATE SET profile_id=excluded.profile_id,revision=1,enabled=true",
            (EXECUTION_WORKER, execution_id),
        )
    values = {
        "id": str(uuid4()),
        "relay_login": RELAY,
        "relay_login_oid": oids[RELAY],
        "worker_login": WORKER,
        "worker_login_oid": oids[WORKER],
        "job_profile_id": job.metadata["document"]["profile_id"],
        "job_profile_digest": job.metadata["document"]["profile_digest"],
        "preparation_profile_id": prep_args["profile_id"],
        "preparation_profile_digest": prep_args["expected_profile_digest"],
        "execution_profile_id": execution_id,
        "execution_profile_digest": execution_digest,
        "mode": mode,
        "origin": "synthetic_mechanism",
        "lease_seconds": dispatch_seconds,
        "dispatch_method_digest": dispatch.method_digest(),
        "dispatch_sql_method_digest": owner.execute(
            "SELECT material_dispatch.native_method_digest() AS v"
        ).fetchone()["v"],
        "database_oid": db_oid,
        "database_name": owner.info.dbname,
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(seconds=profile_seconds),
    }
    profile_digest = insert_profile(owner, "material_dispatch", values)
    owner.execute(
        "INSERT INTO material_dispatch.profile_heads VALUES(%s,%s,1,true)",
        (values["job_profile_id"], values["id"]),
    )
    event_id = str(
        owner.execute(
            "SELECT id FROM material_judgment_job.outbox WHERE job_id=%s",
            (job.metadata["document"]["job_id"],),
        ).fetchone()["id"]
    )
    bundle = material.bind_input(
        data[1],
        data[0].binding,
        expected_context_digest=data[1].metadata["digest"],
        expected_binding_digest=digest(data[0].binding),
        expected_method_digest=material.method_digest(),
    )
    return {
        "world": w,
        "job": job,
        "bundle": bundle,
        "prep_args": prep_args,
        "profile_id": execution_id,
        "profile_digest": execution_digest,
        "dispatch_profile_id": values["id"],
        "dispatch_profile_digest": profile_digest,
        "method_digest": execution.method_digest(),
        "dispatch_method": dispatch.method_digest(),
        "account_id": account_id,
        "message": {
            "version": "material-judgment-task/1",
            "event_id": event_id,
            "job_id": job.metadata["document"]["job_id"],
            "generation": 1,
        },
        "url": url,
        "state": state,
        "profile_until": values["valid_until"],
    }


def relay_claim(lane, *, connection=None, command=None):
    return dispatch.claim_publication(
        connection or lane["world"]["database"]["dispatch_relay"],
        profile_id=lane["dispatch_profile_id"],
        expected_profile_digest=lane["dispatch_profile_digest"],
        command_id=command or str(uuid4()),
        expected_method_digest=lane["dispatch_method"],
    )


def worker_claim(lane, *, connection=None, message=None, command=None):
    return dispatch.claim_delivery(
        connection or lane["world"]["database"]["dispatch_worker"],
        lane["message"] if message is None else message,
        command_id=command or str(uuid4()),
        expected_method_digest=lane["dispatch_method"],
    )


def finish(lane, observed, *, connection=None, failure="LIVE_QUALIFICATION_UNAVAILABLE"):
    return dispatch.finish(
        connection or lane["world"]["database"]["dispatch_worker"],
        observed,
        failure=failure,
        expected_method_digest=lane["dispatch_method"],
    )


def counts(lane):
    owner = lane["world"]["database"]["owner"]
    job_id = lane["message"]["job_id"]
    return owner.execute(
        "SELECT (SELECT count(*) FROM material_judgment_job.outbox WHERE job_id=%s) AS events,(SELECT count(*) FROM material_execution.attempts WHERE job_id=%s) AS attempts,(SELECT count(*) FROM material_execution.reservations WHERE job_id=%s) AS reservations,(SELECT count(*) FROM material_preparation.leases WHERE job_id=%s) AS preparations",
        (job_id,) * 4,
    ).fetchone()


def expire_dispatch(lane, purpose="worker"):
    lane["world"]["database"]["owner"].execute(
        "UPDATE material_dispatch.states SET lease_until=clock_timestamp()-interval '1 second' WHERE event_id=%s AND purpose=%s",
        (lane["message"]["event_id"], purpose),
    )


def ports(lane, handler):
    db = lane["world"]["database"]
    return runtime.MechanismPorts(
        *(
            db[k]
            for k in (
                "preparation_worker",
                "material_reader",
                "scope_verifier",
                "original_verifier",
                "parse_verifier",
                "execution_worker",
            )
        ),
        "development_s3",
        lane["url"],
        httpx.MockTransport(handler),
    )


def run(lane, *, mechanism_ports=None, connection=None):
    return asyncio.run(
        runtime.deliver(
            connection or lane["world"]["database"]["dispatch_worker"],
            lane["message"],
            expected_method_digest=lane["dispatch_method"],
            mechanism_ports=mechanism_ports,
        )
    )


def owned_preflight(lane):
    db = lane["world"]["database"]
    claimed = preparation.claim(db["preparation_worker"], **lane["prep_args"])
    p = claimed.metadata["document"]
    checked = preflight.preflight(
        db["preparation_worker"],
        lane["bundle"],
        lease_id=p["lease_id"],
        expected_lease_digest=claimed.metadata["digest"],
        expected_input_digest=lane["bundle"].metadata["digest"],
        expected_preparation_method_digest=preparation.method_digest(),
        expected_serializer_digest=vision.serializer_digest(),
        expected_method_digest=preflight.method_digest(),
    )
    return claimed, checked


def test_original_outbox_relay_is_once_owned_and_ack_loss_can_republish(wire, monkeypatch):
    lane = prepare(wire, monkeypatch)
    db = lane["world"]["database"]
    first = relay_claim(lane)
    assert (
        first.metadata["new_claim"]
        and first.metadata["lease"]["document"]["message"] == lane["message"]
    )
    assert relay_claim(lane) is None
    expire_dispatch(lane, "relay")
    second = relay_claim(lane)
    assert second.metadata["lease"]["document"]["fence"] == 2
    with pytest.raises(dispatch.MaterialDispatchError, match="LEASE_NOT_CURRENT"):
        dispatch.ack_publication(
            db["dispatch_relay"], first, expected_method_digest=lane["dispatch_method"]
        )
    acked = dispatch.ack_publication(
        db["dispatch_relay"], second, expected_method_digest=lane["dispatch_method"]
    )
    assert acked.metadata["state"] == "published" and acked.metadata["result"] is None
    assert relay_claim(lane) is None and counts(lane)["events"] == 1


@pytest.mark.parametrize("revoke", ["disabled", "expired"])
def test_production_blocks_before_readers_or_funds_and_lost_offset_ack_survives_profile_revoke(
    wire, monkeypatch, revoke
):
    lane = prepare(wire, monkeypatch, profile_seconds=25 if revoke == "expired" else 3600)
    db = lane["world"]["database"]
    before = lane["state"]["attempts"]
    result = run(lane)
    d = result.observation.metadata["result"]["document"]
    assert (
        result.acknowledge
        and d["state"] == "blocked"
        and d["failure_code"] == "LIVE_QUALIFICATION_UNAVAILABLE"
    )
    assert (
        d["blockers"] == list(dispatch.BLOCKERS)
        and d["observed_send_grants"] == d["held_minor"] == 0
    )
    assert counts(lane) == {"events": 1, "attempts": 0, "reservations": 0, "preparations": 0}
    assert lane["state"]["attempts"] == before
    if revoke == "disabled":
        db["owner"].execute(
            "UPDATE material_dispatch.profile_heads SET enabled=false WHERE profile_id=%s",
            (lane["dispatch_profile_id"],),
        )
    else:
        time.sleep(
            max(0, (lane["profile_until"] - datetime.now(timezone.utc)).total_seconds()) + 0.03
        )
    duplicate = run(lane)
    assert (
        duplicate.acknowledge
        and duplicate.observation.metadata["result"] == result.observation.metadata["result"]
    )
    reread = dispatch.read(
        db["dispatch_worker"],
        event_id=lane["message"]["event_id"],
        expected_method_digest=lane["dispatch_method"],
    )
    assert reread.metadata["result"] == result.observation.metadata["result"]


def test_worker_duplicate_never_borrows_running_token_and_takeover_fences_old_completion(
    wire, monkeypatch
):
    lane = prepare(wire, monkeypatch)
    command = str(uuid4())
    first = worker_claim(lane, command=command)
    second = worker_claim(lane)
    assert first.metadata["new_claim"] and not second.metadata["new_claim"]
    assert first.metadata["lease"] == second.metadata["lease"]
    assert not run(lane).acknowledge
    expire_dispatch(lane)
    newer = worker_claim(lane)
    assert newer.metadata["new_claim"] and newer.metadata["lease"]["document"]["fence"] == 2
    with pytest.raises(dispatch.MaterialDispatchError, match="LEASE_NOT_CURRENT"):
        finish(lane, first)
    assert finish(lane, newer).metadata["state"] == "blocked"
    assert not worker_claim(lane, command=command).metadata["new_claim"]


def test_two_native_consumers_have_one_claim_and_no_shared_transaction(wire, monkeypatch):
    lane = prepare(wire, monkeypatch)
    db = lane["world"]["database"]

    def claim_one(_):
        with db["dispatch_worker_factory"]() as c:
            observed = worker_claim(lane, connection=c)
            assert c.info.transaction_status == TransactionStatus.IDLE
            return observed

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim_one, range(2)))
    assert sum(r.metadata["new_claim"] for r in results) == 1
    assert results[0].metadata["lease"] == results[1].metadata["lease"]


def test_roles_ids_and_native_method_drift_fail_before_any_write(wire, monkeypatch):
    lane = prepare(wire, monkeypatch)
    db = lane["world"]["database"]
    for role in (
        "owner",
        "job_submitter",
        "preparation_worker",
        "execution_worker",
        "dispatch_relay",
        "other_dispatch_worker",
    ):
        with pytest.raises(dispatch.MaterialDispatchError):
            worker_claim(lane, connection=db[role])
    for changed in (
        lane["message"] | {"job_id": str(uuid4())},
        lane["message"] | {"event_id": str(uuid4())},
    ):
        with pytest.raises(dispatch.MaterialDispatchError, match="MESSAGE_MISMATCH"):
            worker_claim(lane, message=changed)
    for connection in (db["dispatch_worker"], db["dispatch_relay"]):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM material_judgment_job.outbox")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM material_execution.attempts")
    original = dispatch.method_digest
    monkeypatch.setattr(dispatch, "method_digest", lambda: "0" * 64)
    with pytest.raises(dispatch.MaterialDispatchError, match="METHOD_MISMATCH"):
        worker_claim(lane)
    monkeypatch.setattr(dispatch, "method_digest", original)
    assert counts(lane) == {"events": 1, "attempts": 0, "reservations": 0, "preparations": 0}


def test_native_recovery_preflight_all_slots_and_reread_are_wired(wire, monkeypatch):
    lane = prepare(wire, monkeypatch, mode="synthetic_mechanism")
    db = lane["world"]["database"]
    before = lane["state"]["attempts"]
    posts = []

    async def handler(request):
        assert all(
            db[k].info.transaction_status == TransactionStatus.IDLE
            for k in ("dispatch_worker", "preparation_worker", "execution_worker")
        )
        posts.append(request.content)
        return httpx.Response(
            200,
            stream=Stream(payload(lane, len(posts) - 1)),
            headers={"x-request-id": "synthetic-dispatch-request-" + str(len(posts))},
        )

    configured = ports(lane, handler)
    result = run(lane, mechanism_ports=configured)
    d = result.observation.metadata["result"]["document"]
    assert d["state"] == "mechanism_completed" and d["preparation_fenced"]
    assert d["observed_send_grants"] == len(posts) == len(lane["job"].metadata["document"]["slots"])
    assert d["financial_state"] == "completed" and d["held_minor"] == 0 and d["estimated_minor"] > 0
    assert lane["state"]["attempts"] == before + 2
    for index in range(0, len(posts), 3):
        assert posts[index] == posts[index + 1] == posts[index + 2]
    duplicate = run(lane, mechanism_ports=configured)
    assert duplicate.observation.metadata["result"] == result.observation.metadata["result"]
    assert len(posts) == d["observed_send_grants"] and lane["state"]["attempts"] == before + 2
    assert all(d[k] is False for k in dispatch.FALSE_FIELDS)


def test_unknown_charge_is_durable_and_duplicate_never_reads_or_sends_again(wire, monkeypatch):
    lane = prepare(wire, monkeypatch, mode="synthetic_mechanism")
    posts = []

    async def handler(request):
        posts.append(request.content)
        raise httpx.ReadError("synthetic disconnect after request")

    configured = ports(lane, handler)
    result = run(lane, mechanism_ports=configured)
    d = result.observation.metadata["result"]["document"]
    assert d["state"] == "billing_unresolved" and d["financial_state"] == "unknown"
    assert (
        d["held_minor"] > 0
        and d["estimated_minor"] == 0
        and d["observed_send_grants"] == len(posts) == 1
    )
    before = lane["state"]["attempts"]
    duplicate = run(lane, mechanism_ports=configured)
    assert duplicate.observation.metadata["result"] == result.observation.metadata["result"]
    assert len(posts) == 1 and lane["state"]["attempts"] == before


def test_terminal_commit_fences_worker_paused_after_both_heartbeats_before_begin(wire, monkeypatch):
    lane = prepare(wire, monkeypatch, mode="synthetic_mechanism")
    db = lane["world"]["database"]
    old = worker_claim(lane)
    claimed, checked = owned_preflight(lane)
    dispatch.heartbeat(db["dispatch_worker"], old, expected_method_digest=lane["dispatch_method"])
    preparation.heartbeat(
        db["preparation_worker"],
        lease_id=claimed.metadata["document"]["lease_id"],
        expected_lease_digest=claimed.metadata["digest"],
        command_id=str(uuid4()),
        expected_method_digest=preparation.method_digest(),
    )
    expire_dispatch(lane)

    async def forbidden(request):
        pytest.fail("terminal delivery allowed a new model request")

    newer = run(lane, mechanism_ports=ports(lane, forbidden))
    result = newer.observation.metadata["result"]["document"]
    assert (
        result["state"] == "blocked"
        and result["failure_code"] == "PREPARATION_FAILED"
        and result["preparation_fenced"]
    )
    assert result["held_minor"] == result["observed_send_grants"] == 0
    with pytest.raises(preparation.PreparationError, match="LEASE_NOT_CURRENT"):
        preparation.heartbeat(
            db["preparation_worker"],
            lease_id=claimed.metadata["document"]["lease_id"],
            expected_lease_digest=claimed.metadata["digest"],
            command_id=str(uuid4()),
            expected_method_digest=preparation.method_digest(),
        )
    with pytest.raises(execution.MaterialExecutionError, match="CURRENT_STATE_UNAVAILABLE"):
        execution.begin_attempt(db["execution_worker"], checked, **begin_args(lane))
    assert counts(lane)["attempts"] == counts(lane)["reservations"] == 0


def test_grant_committed_before_terminal_keeps_hold_and_late_usage_is_charged(wire, monkeypatch):
    lane = prepare(wire, monkeypatch, mode="synthetic_mechanism")
    db = lane["world"]["database"]
    terminal = []
    posts = []

    async def handler(request):
        posts.append(request.content)
        expire_dispatch(lane)
        with db["dispatch_worker_factory"]() as newer_connection:
            newer = await runtime.deliver(
                newer_connection,
                lane["message"],
                expected_method_digest=lane["dispatch_method"],
                mechanism_ports=ports(lane, handler),
            )
            terminal.append(newer.observation.metadata["result"]["document"])
        return httpx.Response(
            200,
            stream=Stream(payload(lane, 0)),
            headers={"x-request-id": "synthetic-late-response"},
        )

    result = run(lane, mechanism_ports=ports(lane, handler))
    assert result.acknowledge and len(posts) == len(terminal) == 1
    assert (
        terminal[0]["financial_state"] == "in_flight"
        and terminal[0]["held_minor"] > 0
        and terminal[0]["observed_send_grants"] == 1
    )
    assert terminal[0]["preparation_fenced"] and terminal[0]["state"] == "billing_unresolved"
    row = (
        db["owner"]
        .execute(
            "SELECT o.document,b.estimated_minor,b.held_minor,b.state FROM material_execution.outcomes o JOIN material_execution.attempts a ON a.id=o.attempt_id JOIN material_execution.job_balances b ON b.job_id=a.job_id WHERE a.job_id=%s",
            (lane["message"]["job_id"],),
        )
        .fetchone()
    )
    assert row["estimated_minor"] > 0 and row["held_minor"] > 0 and row["state"] == "paused_stale"
    assert (
        row["document"]["billing_state"] == "usage_reported"
        and row["document"]["valid_slot"] is False
    )
    assert row["document"]["source_current_at_settlement"] is False


def test_native_overgrant_and_returned_method_corruption_roll_back_delivery(wire, monkeypatch):
    lane = prepare(wire, monkeypatch)
    db = lane["world"]["database"]
    owner = db["owner"]
    owner.execute(
        sql.SQL("GRANT SELECT ON material_dispatch.states TO {}").format(sql.Identifier(WORKER))
    )
    try:
        with pytest.raises(dispatch.MaterialDispatchError):
            worker_claim(lane)
    finally:
        owner.execute(
            sql.SQL("REVOKE SELECT ON material_dispatch.states FROM {}").format(
                sql.Identifier(WORKER)
            )
        )
    original = dispatch._observation

    def corrupt(value, purpose):
        value = deepcopy(value)
        value["lease"]["document"]["dispatch_method_digest"] = "0" * 64
        value["lease"]["digest"] = digest(value["lease"]["document"])
        return original(value, purpose)

    monkeypatch.setattr(dispatch, "_observation", corrupt)
    with pytest.raises(dispatch.MaterialDispatchError, match="NATIVE_RESULT_INVALID"):
        worker_claim(lane)
    assert (
        owner.execute(
            "SELECT 1 AS present FROM material_dispatch.states WHERE event_id=%s",
            (lane["message"]["event_id"],),
        ).fetchone()
        is None
    )


@pytest.mark.skipif(not BOOTSTRAP, reason="explicit isolated real Kafka bootstrap required")
@pytest.mark.parametrize("mode", ["production_admission", "synthetic_mechanism"])
def test_real_kafka_original_outbox_ack_loss_duplicate_and_unknown_no_resend(
    wire, monkeypatch, mode
):
    lane = prepare(wire, monkeypatch, mode=mode)
    db = lane["world"]["database"]
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP, "log_level": 0})
    topics = admin.list_topics(timeout=10).topics
    if runtime.TOPIC not in topics:
        admin.create_topics([NewTopic(runtime.TOPIC, num_partitions=1, replication_factor=1)])[
            runtime.TOPIC
        ].result(timeout=15)
    producer = runtime.producer(BOOTSTRAP)
    consumer = runtime.consumer(BOOTSTRAP, group="fusion-material-" + uuid4().hex)
    partition = TopicPartition(runtime.TOPIC, 0)
    start = consumer.get_watermark_offsets(partition, timeout=10, cached=False)[1]
    consumer.assign([TopicPartition(runtime.TOPIC, 0, start)])
    posts = []

    async def handler(request):
        posts.append(request.content)
        raise httpx.ReadError("synthetic unknown through real Kafka")

    configured = ports(lane, handler) if mode == "synthetic_mechanism" else None
    original = dispatch.ack_publication
    monkeypatch.setattr(
        dispatch, "ack_publication", lambda *a, **k: dispatch.fail("SYNTHETIC_LOST_NATIVE_ACK")
    )
    args = {
        "profile_id": lane["dispatch_profile_id"],
        "expected_profile_digest": lane["dispatch_profile_digest"],
        "expected_method_digest": lane["dispatch_method"],
    }
    try:
        with pytest.raises(dispatch.MaterialDispatchError, match="SYNTHETIC_LOST_NATIVE_ACK"):
            runtime.relay_once(db["dispatch_relay"], producer, **args)
        monkeypatch.setattr(dispatch, "ack_publication", original)
        expire_dispatch(lane, "relay")
        published = runtime.relay_once(db["dispatch_relay"], producer, **args)
        assert published.metadata["state"] == "published"

        class LostOffsetAck:
            # The actual broker commits successfully. Only the local return is
            # lost, so runtime must rewind the actual assigned Kafka partition.
            def poll(self, timeout):
                return consumer.poll(timeout)

            def seek(self, position):
                return consumer.seek(position)

            def commit(self, **kwargs):
                consumer.commit(**kwargs)
                raise RuntimeError("synthetic lost offset acknowledgment")

        deadline = time.monotonic() + 90
        with pytest.raises(dispatch.MaterialDispatchError, match="OFFSET_UNCONFIRMED"):
            while time.monotonic() < deadline:
                runtime.consume_once(
                    db["dispatch_worker"],
                    LostOffsetAck(),
                    expected_method_digest=lane["dispatch_method"],
                    mechanism_ports=configured,
                    timeout=1,
                )
        assert consumer.committed([partition], timeout=10)[0].offset == start + 1
        db["owner"].execute(
            "UPDATE material_dispatch.profile_heads SET enabled=false WHERE profile_id=%s",
            (lane["dispatch_profile_id"],),
        )
        receipts = []
        deadline = time.monotonic() + 90
        while len(receipts) < 2 and time.monotonic() < deadline:
            observed = runtime.consume_once(
                db["dispatch_worker"],
                consumer,
                expected_method_digest=lane["dispatch_method"],
                mechanism_ports=configured,
                timeout=1,
            )
            if observed is not None:
                receipts.append(observed)
        assert len(receipts) == 2 and all(r.acknowledge for r in receipts)
        assert (
            receipts[0].observation.metadata["result"] == receipts[1].observation.metadata["result"]
        )
        document = receipts[0].observation.metadata["result"]["document"]
        assert len(posts) == (1 if mode == "synthetic_mechanism" else 0)
        assert document["state"] == (
            "billing_unresolved" if mode == "synthetic_mechanism" else "blocked"
        )
        assert consumer.committed([partition], timeout=10)[0].offset >= start + 2
        assert counts(lane)["attempts"] == len(posts) and counts(lane)["events"] == 1
    finally:
        consumer.close()
        producer.flush(5)
