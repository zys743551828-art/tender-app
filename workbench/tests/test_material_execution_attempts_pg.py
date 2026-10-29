"""Isolated nonowner native ledger + original /3 bytes + synthetic single HTTP send."""

# ruff: noqa: F401,F811
import asyncio
import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from queue import Queue
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from test_material_request_preflight_pg import setup as preparation_setup
from test_package_technical_material import Stream, judgment, response
from test_preparation_leases_pg import (
    ADMIN_DSN,
    api,
    claim,
    exact,
    pdf_data,
    requirements,
    saved,
    wire,
    world,
)
from test_preparation_leases_pg import database as preparation_database

from packages.domain.providers.deepseek_vision import parse_response
from packages.domain.review_identity import digest
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_preparation_leases as leases
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_technical_complete_vision as vision

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_EXECUTION_PG") != "1",
    reason="explicit isolated material execution native fixture required",
)
WORKER = "fusion_material_execution_worker"
OTHER = "fusion_other_material_execution_worker"


@pytest.fixture(scope="module")
def database():
    base = preparation_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    installed = False
    try:
        owner.execute(execution.SQL_FILE.read_text(encoding="utf-8"))
        installed = True
        factories = {}
        for role in (WORKER, OTHER):
            assert not owner.execute("SELECT FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            created.append(role)
            owner.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(execution.GROUP), sql.Identifier(role)
                )
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=role, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[role] = factory
        with factories[WORKER]() as c, factories[OTHER]() as other:
            yield value | {
                "execution_worker": c,
                "execution_worker_factory": factories[WORKER],
                "other_execution_worker": other,
            }
    finally:
        try:
            next(base)
        except StopIteration:
            pass
        finally:
            if installed:
                with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
                    for role in created:
                        admin.execute(
                            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                        )
                    admin.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(execution.GROUP))
                    )


def ready(wire, monkeypatch, *, account_limit=90_000_000):
    w, _, _ = wire
    data, job, lease, bundle, args = preparation_setup(wire, monkeypatch)
    owner = w["database"]["owner"]
    checked = preflight.preflight(w["database"]["preparation_worker"], bundle, **args)
    now = datetime.now(timezone.utc)
    account = str(uuid4())
    owner.execute(
        "INSERT INTO material_execution.accounts VALUES(%s,%s,%s,'synthetic_mechanism')",
        (account, job.metadata["document"]["currency"], account_limit),
    )
    owner.execute("INSERT INTO material_execution.balances VALUES(%s,0,0)", (account,))
    values = {
        "id": str(uuid4()),
        "worker_login": WORKER,
        "worker_login_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (WORKER,)
        ).fetchone()["oid"],
        "preparation_profile_id": lease.metadata["document"]["profile_id"],
        "preparation_profile_digest": lease.metadata["document"]["profile_digest"],
        "account_id": account,
        "origin": "synthetic_mechanism",
        "execution_method_digest": execution.method_digest(),
        "execution_sql_method_digest": owner.execute(
            "SELECT material_execution.native_method_digest() AS v"
        ).fetchone()["v"],
        "preflight_method_digest": preflight.method_digest(),
        "serializer_digest": vision.serializer_digest(),
        "provider_profile_digest": vision.profile_digest(),
        "judgment_method_digest": vision.judgment_method_digest(),
        "database_oid": owner.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()["oid"],
        "database_name": owner.info.dbname,
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(hours=1),
    }
    owner.execute(
        sql.SQL("INSERT INTO material_execution.profiles ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    owner.execute(
        "INSERT INTO material_execution.profile_heads VALUES(%s,%s,1,true) ON CONFLICT(worker_login) DO UPDATE SET profile_id=excluded.profile_id,revision=excluded.revision,enabled=true",
        (WORKER, values["id"]),
    )
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') AS v FROM material_execution.profiles p WHERE id=%s",
        (values["id"],),
    ).fetchone()["v"]
    return {
        "world": w,
        "job": job,
        "lease": lease,
        "bundle": bundle,
        "checked": checked,
        "profile_id": values["id"],
        "profile_digest": checksum,
        "account_id": account,
        "method_digest": execution.method_digest(),
    }


def begin_args(lane, index=0):
    slot = lane["job"].metadata["document"]["slots"][index]
    return {
        "profile_id": lane["profile_id"],
        "expected_profile_digest": lane["profile_digest"],
        "slot_id": slot["slot_id"],
        "rule_id": slot["rule_id"],
        "command_id": str(uuid4()),
        "expected_method_digest": lane["method_digest"],
    }


def begin(lane, index=0, *, connection=None, args=None, checked=None):
    return execution.begin_attempt(
        lane["world"]["database"]["execution_worker"] if connection is None else connection,
        lane["checked"] if checked is None else checked,
        **(begin_args(lane, index) if args is None else args),
    )


def payload(lane, index=0, **changes):
    data = judgment(lane["bundle"])
    slot = lane["job"].metadata["document"]["slots"][index]
    rule = next(
        r for r in lane["bundle"].context.metadata["rules"] if r["rule_id"] == slot["rule_id"]
    )
    data["covered_part_ids"] = rule["required_part_ids"]
    data["band_id"] = rule["bands"][0]["band_id"]
    return response(data, id="synthetic-response-" + str(index), **changes)


def execute(lane, index=0, *, raw=None, status=200, callback=None, posts=None):
    db = lane["world"]["database"]
    raw = payload(lane, index) if raw is None else raw

    async def handler(request):
        assert db["execution_worker"].info.transaction_status == TransactionStatus.IDLE
        assert db["preparation_worker"].info.transaction_status == TransactionStatus.IDLE
        row = (
            db["owner"]
            .execute(
                "SELECT state FROM material_execution.job_balances WHERE job_id=%s",
                (lane["job"].metadata["document"]["job_id"],),
            )
            .fetchone()
        )
        assert row["state"] == "in_flight"
        if posts is not None:
            posts.append(request.content)
        if callback:
            callback()
        return httpx.Response(
            status, stream=Stream(raw), headers={"x-request-id": "synthetic-request-" + str(index)}
        )

    return asyncio.run(
        execution.execute_mechanism_attempt(
            db["preparation_worker"],
            db["execution_worker"],
            lane["bundle"],
            lane["checked"],
            **begin_args(lane, index),
            expected_preflight_digest=lane["checked"].metadata["digest"],
            transport=httpx.MockTransport(handler),
        )
    )


def read(lane, record, *, connection=None):
    return execution.read(
        lane["world"]["database"]["execution_worker"] if connection is None else connection,
        attempt_id=record.metadata["attempt"]["document"]["attempt_id"],
        expected_method_digest=lane["method_digest"],
    )


def test_native_three_independent_slots_commit_before_io_and_reopen_exact_raw(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    posts, results = [], []
    slots = lane["job"].metadata["document"]["slots"]
    for index in range(len(slots)):
        leases.heartbeat(
            lane["world"]["database"]["preparation_worker"],
            lease_id=lane["lease"].metadata["document"]["lease_id"],
            expected_lease_digest=lane["lease"].metadata["digest"],
            command_id=str(uuid4()),
            expected_method_digest=leases.method_digest(),
        )
        raw_value = json.loads(payload(lane, index))
        raw_value["choices"][0]["message"]["tool_calls"] = ([], {}, False, 0, "", None)[index % 6]
        expected_raw = json.dumps(raw_value).encode()
        result = execute(lane, index, raw=expected_raw, posts=posts)
        results.append(result)
        assert result.metadata["outcome"]["document"]["valid_slot"]
        assert result.metadata["outcome"]["document"]["billing_state"] == "usage_reported"
        assert result.metadata["outcome"]["document"]["formal_prediction_eligible"] is False
        with lane["world"]["database"]["execution_worker_factory"]() as c:
            reopened = read(lane, result, connection=c)
            assert reopened == result
            assert (
                execution.response(c, reopened, expected_method_digest=lane["method_digest"])
                == expected_raw
            )
    assert len(posts) == len(slots)
    for offset in range(0, len(slots), 3):
        assert posts[offset] == posts[offset + 1] == posts[offset + 2]
    assert len({r.metadata["attempt"]["document"]["attempt_id"] for r in results}) == len(slots)
    last = results[-1].metadata
    assert last["job_balance"]["state"] == "completed"
    assert last["job_balance"]["held_minor"] == last["account_balance"]["held_minor"] == 0
    fee = sum(r.metadata["outcome"]["document"]["estimated_fee_minor"] for r in results)
    assert (
        last["job_balance"]["estimated_minor"] == last["account_balance"]["estimated_minor"] == fee
    )
    assert (
        last["job_balance"]["released_minor"]
        == last["reservation"]["document"]["reserved_minor"] - fee
    )
    replay = execute(lane, 0, posts=posts)
    assert not replay.metadata["new_send"] and len(posts) == len(slots)


def test_concurrent_commands_grant_the_logical_slot_once_and_hold_full_budget(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    factory = lane["world"]["database"]["execution_worker_factory"]

    def claim_once(_):
        with factory() as c:
            return begin(lane, connection=c)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim_once, range(2)))
    assert sum(r.metadata["new_send"] for r in results) == 1
    assert results[0].metadata["attempt"] == results[1].metadata["attempt"]
    assert (
        results[0].metadata["job_balance"]["held_minor"]
        == results[0].metadata["reservation"]["document"]["reserved_minor"]
    )
    with pytest.raises(execution.MaterialExecutionError, match="JOB_BLOCKED"):
        begin(lane, 1)
    assert not begin(lane).metadata["new_send"]


def test_unknown_response_keeps_full_hold_and_no_new_nonce_can_retry(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    posts = []
    result = execute(lane, raw=b"synthetic-private-provider-failure", status=500, posts=posts)
    m = result.metadata
    assert m["job_balance"]["state"] == "unknown"
    assert m["outcome"]["document"]["estimated_fee_minor"] is None
    assert m["outcome"]["document"]["request_id"] == "synthetic-request-0"
    assert m["job_balance"]["held_minor"] == m["reservation"]["document"]["reserved_minor"]
    assert m["account_balance"]["estimated_minor"] == 0
    assert len(posts) == 1 and not begin(lane).metadata["new_send"]
    with pytest.raises(execution.MaterialExecutionError, match="JOB_BLOCKED"):
        begin(lane, 1)
    assert (
        execution.response(
            lane["world"]["database"]["execution_worker"],
            result,
            expected_method_digest=lane["method_digest"],
        )
        == b"synthetic-private-provider-failure"
    )
    with pytest.raises(execution.MaterialExecutionError, match="NOT_FOUND"):
        read(lane, result, connection=lane["world"]["database"]["other_execution_worker"])


@pytest.mark.parametrize("change", ["revoke", "takeover", "execution_revision"])
def test_late_response_keeps_fee_but_cannot_qualify_under_lost_lease(wire, monkeypatch, change):
    lane = ready(wire, monkeypatch)
    db = lane["world"]["database"]
    old = lane["lease"].metadata["document"]

    def invalidate():
        if change == "execution_revision":
            db["owner"].execute(
                "UPDATE material_execution.profile_heads SET revision=revision+1 WHERE profile_id=%s",
                (lane["profile_id"],),
            )
        elif change == "revoke":
            db["owner"].execute(
                "UPDATE material_preparation.profile_heads SET enabled=false,revision=revision+1 WHERE profile_id=%s",
                (old["profile_id"],),
            )
        else:
            db["owner"].execute(
                "UPDATE material_preparation.states SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",
                (old["job_id"],),
            )
            new = leases.claim(
                db["preparation_worker"],
                job_id=old["job_id"],
                expected_job_digest=old["job_digest"],
                profile_id=old["profile_id"],
                expected_profile_digest=old["profile_digest"],
                command_id=str(uuid4()),
                expected_method_digest=leases.method_digest(),
            )
            assert new.metadata["document"]["fence"] == old["fence"] + 1

    result = execute(lane, callback=invalidate)
    d = result.metadata["outcome"]["document"]
    assert d["estimated_fee_minor"] > 0 and d["billing_state"] == "usage_reported"
    assert not d["source_current_at_settlement"] and not d["valid_slot"]
    assert result.metadata["job_balance"]["state"] == "paused_stale"
    assert read(lane, result) == result


def test_expiry_after_serialization_before_native_grant_spends_nothing(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    db = lane["world"]["database"]
    original = preflight.prepare_rule_request

    def expire(*args, **kwargs):
        value = original(*args, **kwargs)
        db["owner"].execute(
            "UPDATE material_preparation.states SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",
            (lane["job"].metadata["document"]["job_id"],),
        )
        return value

    monkeypatch.setattr(preflight, "prepare_rule_request", expire)
    posts = []
    with pytest.raises(execution.MaterialExecutionError, match="CURRENT_STATE_UNAVAILABLE"):
        execute(lane, posts=posts)
    assert posts == []
    assert db["owner"].execute(
        "SELECT held_minor,estimated_minor FROM material_execution.balances WHERE account_id=%s",
        (lane["account_id"],),
    ).fetchone() == {"held_minor": 0, "estimated_minor": 0}


def test_account_insufficiency_refuses_entire_job_before_first_send(wire, monkeypatch):
    lane = ready(wire, monkeypatch, account_limit=0)
    posts = []
    with pytest.raises(execution.MaterialExecutionError, match="BUDGET_INSUFFICIENT"):
        execute(lane, posts=posts)
    assert posts == []
    assert (
        not lane["world"]["database"]["owner"]
        .execute(
            "SELECT FROM material_execution.reservations WHERE job_id=%s",
            (lane["job"].metadata["document"]["job_id"],),
        )
        .fetchone()
    )


def test_invalid_complete_output_is_charged_and_cannot_be_zero_fee_retry(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    raw = response({}, id="synthetic-invalid-json-shape")
    result = execute(lane, raw=raw)
    d = result.metadata["outcome"]["document"]
    assert d["estimated_fee_minor"] > 0 and d["billing_state"] == "usage_reported"
    assert not d["valid_slot"] and result.metadata["job_balance"]["state"] == "paused_invalid"
    assert not begin(lane).metadata["new_send"]
    with pytest.raises(execution.MaterialExecutionError, match="JOB_BLOCKED"):
        begin(lane, 1)


def test_usage_over_reservation_is_recorded_uncapped_and_pauses(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    owner = lane["world"]["database"]["owner"]
    quoted = owner.execute(
        "SELECT document FROM material_cost_quote.quotes WHERE id=%s",
        (lane["job"].metadata["document"]["quote_id"],),
    ).fetchone()["document"]
    tokens = quoted["price_policy"]["context_token_capacity"] * 2
    raw = payload(
        lane,
        usage={"prompt_tokens": tokens, "completion_tokens": 4096, "total_tokens": tokens + 4096},
    )
    result = execute(lane, raw=raw)
    d = result.metadata["outcome"]["document"]
    assert d["estimated_fee_minor"] > result.metadata["attempt"]["document"]["reserved_call_minor"]
    assert d["over_reservation"] and not d["invoice_reconciled"]
    assert result.metadata["job_balance"]["state"] == "paused_overrun"
    assert result.metadata["account_balance"]["estimated_minor"] == d["estimated_fee_minor"]
    with pytest.raises(execution.MaterialExecutionError, match="JOB_BLOCKED"):
        begin(lane, 1)


def test_reused_provider_response_cannot_be_three_independent_judgments(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    first = execute(lane, 0)
    second = execute(lane, 1, raw=payload(lane, 0))
    assert first.metadata["outcome"]["document"]["valid_slot"]
    d = second.metadata["outcome"]["document"]
    assert d["duplicate_response"] and not d["valid_slot"] and d["estimated_fee_minor"] > 0
    assert second.metadata["job_balance"]["state"] == "paused_invalid"


def test_forged_usage_refused_then_idempotent_real_settlement_and_conflict(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    granted = begin(lane)
    d = granted.metadata["attempt"]["document"]
    raw = payload(lane)
    request = vision.prepare_request(
        lane["bundle"],
        d["rule_id"],
        expected_input_digest=d["request"]["input_digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )
    generated = parse_response(raw, "synthetic-request", d["request"]["request_digest"])
    submitted = execution._received(granted, lane["bundle"], request, generated=generated)
    bad = deepcopy(submitted)
    bad.metadata["usage"].update(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    c = lane["world"]["database"]["execution_worker"]
    with pytest.raises(execution.MaterialExecutionError, match="OUTCOME_INVALID"):
        execution.settle(
            c, granted, bad, command_id=str(uuid4()), expected_method_digest=lane["method_digest"]
        )
    assert read(lane, granted).metadata["job_balance"]["state"] == "in_flight"
    command = str(uuid4())
    result = execution.settle(
        c, granted, submitted, command_id=command, expected_method_digest=lane["method_digest"]
    )
    assert (
        execution.settle(
            c, granted, submitted, command_id=command, expected_method_digest=lane["method_digest"]
        )
        == result
    )
    conflict = deepcopy(submitted)
    conflict.metadata["failure_code"] = "DIFFERENT_RECEIPT"
    with pytest.raises(execution.MaterialExecutionError, match="SETTLEMENT_CONFLICT"):
        execution.settle(
            c,
            granted,
            conflict,
            command_id=str(uuid4()),
            expected_method_digest=lane["method_digest"],
        )


def test_rehashed_qualification_or_partial_preflight_cannot_grant_send(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    variants = []
    for flag in (
        "execution_authorized",
        "account_prices_verified",
        "model_token_limit_verified",
        "visual_readability_verified",
    ):
        value = deepcopy(lane["checked"].metadata)
        value[flag] = True
        variants.append(value)
    empty = deepcopy(lane["checked"].metadata)
    empty["requests"] = []
    variants.append(empty)
    extra = deepcopy(lane["checked"].metadata)
    extra["requests"][0]["image_count"] = 0
    variants.append(extra)
    for value in variants:
        value["digest"] = digest({k: v for k, v in value.items() if k != "digest"})
        with pytest.raises(execution.MaterialExecutionError, match="PREFLIGHT_INVALID"):
            begin(lane, checked=preflight.MaterialRequestPreflight(value))
    owner = lane["world"]["database"]["owner"]
    assert not owner.execute(
        "SELECT FROM material_execution.reservations WHERE job_id=%s",
        (lane["job"].metadata["document"]["job_id"],),
    ).fetchone()


def test_independent_role_no_table_or_cross_purpose_authority(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    db = lane["world"]["database"]
    for key in ("owner", "preparation_worker", "job_submitter"):
        with pytest.raises(execution.MaterialExecutionError, match="INDEPENDENT"):
            begin(lane, connection=db[key])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db["execution_worker"].execute("SELECT * FROM material_execution.attempts")
    db["owner"].execute(
        sql.SQL("GRANT {} TO {}").format(sql.Identifier(leases.GROUP), sql.Identifier(WORKER))
    )
    try:
        with pytest.raises(
            execution.MaterialExecutionError, match="INDEPENDENT_MEMBERSHIP_REQUIRED"
        ):
            begin(lane)
    finally:
        db["owner"].execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(leases.GROUP), sql.Identifier(WORKER)
            )
        )


def test_native_settlement_checks_body_rules_citations_and_duplicate_keys(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    granted = begin(lane)
    c = lane["world"]["database"]["execution_worker"]
    for change in (
        "missing_choices",
        "band",
        "quote",
        "parts",
        "digest",
        "duplicate_usage",
        "duplicate_content",
        "region",
        "dimensions",
        "fingerprint_empty",
        "fingerprint_object",
        "physical_float",
        "physical_exponent",
        "region_float",
        "usage_exponent",
        "numeric_response_id",
    ):
        value = json.loads(payload(lane))
        data = json.loads(value["choices"][0]["message"]["content"])
        if change == "missing_choices":
            value.pop("choices")
        else:
            if change == "band":
                data["band_id"] = "unpublished-band"
            elif change == "quote":
                data["evidence"][0]["quote"] = "fabricated-source-quote"
            elif change == "parts":
                data["covered_part_ids"] = []
            elif change == "region":
                data["evidence"][0]["region"] = [0, 0, 100000, 100000]
            elif change == "dimensions":
                data["dimensions"]["specificity"] = "invented-diagnostic"
            elif change == "fingerprint_empty":
                value["system_fingerprint"] = ""
            elif change == "fingerprint_object":
                value["system_fingerprint"] = {}
            elif change == "numeric_response_id":
                value["id"] = 123
            elif change == "physical_float":
                data["evidence"][0]["physical_page"] = float(data["evidence"][0]["physical_page"])
            elif change == "region_float":
                data["evidence"][0]["region"] = [0.0, 0, 1, 1]
            content = json.dumps(data)
            if change == "duplicate_content":
                content = content[:-1] + ',"status":"valid"}'
            elif change == "physical_exponent":
                page = data["evidence"][0]["physical_page"]
                content = content.replace(f'"physical_page": {page}', f'"physical_page": {page}e0')
            value["choices"][0]["message"]["content"] = content
        raw = json.dumps(value).encode()
        if change == "duplicate_usage":
            raw = raw[:-1] + b',"usage":' + json.dumps(value["usage"]).encode() + b"}"
        elif change == "usage_exponent":
            raw = raw.replace(b'"prompt_tokens": 5', b'"prompt_tokens": 5e0')
        native_digest = (
            lane["world"]["database"]["owner"]
            .execute(
                "SELECT encode(sha256(convert_to(design.package_canonical_json(%s::jsonb),'UTF8')),'hex') AS v",
                (json.dumps(data),),
            )
            .fetchone()["v"]
        )
        submitted = execution._outcome(
            granted,
            raw=raw,
            complete=True,
            billing="usage_reported",
            usage=value["usage"],
            response_id=str(value["id"]),
            request_id="synthetic-request",
            valid=True,
            judgment_digest="0" * 64 if change == "digest" else native_digest,
            failure="NONE",
        )
        with pytest.raises(execution.MaterialExecutionError, match="OUTCOME_INVALID"):
            execution.settle(
                c,
                granted,
                submitted,
                command_id=str(uuid4()),
                expected_method_digest=lane["method_digest"],
            )
    assert read(lane, granted).metadata["job_balance"]["state"] == "in_flight"
    assert read(lane, granted).metadata["outcome"] is None


def test_settlement_locks_current_source_until_immutable_outcome_commits(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    granted = begin(lane)
    d = granted.metadata["attempt"]["document"]
    request = vision.prepare_request(
        lane["bundle"],
        d["rule_id"],
        expected_input_digest=d["request"]["input_digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )
    generated = parse_response(payload(lane), "synthetic-request", d["request"]["request_digest"])
    submitted = execution._received(granted, lane["bundle"], request, generated=generated)
    db = lane["world"]["database"]
    owner = db["owner"]
    owner_dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname)
    started = Queue()

    def settle_once():
        with db["execution_worker_factory"]() as c:
            started.put(c.info.backend_pid)
            return execution.settle(
                c,
                granted,
                submitted,
                command_id=str(uuid4()),
                expected_method_digest=lane["method_digest"],
            )

    def revoke():
        with psycopg.connect(owner_dsn, autocommit=True) as c:
            started.put(c.info.backend_pid)
            c.execute(
                "UPDATE material_execution.profile_heads SET revision=revision+1 WHERE profile_id=%s",
                (lane["profile_id"],),
            )

    def blocked(pid, future):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if owner.execute(
                "SELECT EXISTS(SELECT FROM pg_locks WHERE pid=%s AND NOT granted) AS blocked",
                (pid,),
            ).fetchone()["blocked"]:
                return True
            if future.done():
                future.result()
                return False
            time.sleep(0.02)
        return False

    with (
        ThreadPoolExecutor(max_workers=2) as pool,
        psycopg.connect(owner_dsn, autocommit=True) as blocker,
    ):
        with blocker.transaction():
            blocker.execute("LOCK TABLE material_execution.outcomes IN SHARE MODE")
            settlement = pool.submit(settle_once)
            assert blocked(started.get(timeout=2), settlement)
            revoked = pool.submit(revoke)
            assert blocked(started.get(timeout=2), revoked)
            assert not revoked.done()
        result = settlement.result(timeout=10)
        revoked.result(timeout=10)
    assert result.metadata["outcome"]["document"]["source_current_at_settlement"]
    assert result.metadata["outcome"]["document"]["valid_slot"]
    assert (
        owner.execute(
            "SELECT revision FROM material_execution.profile_heads WHERE profile_id=%s",
            (lane["profile_id"],),
        ).fetchone()["revision"]
        == d["profile_head_revision"] + 1
    )


def test_internal_send_guard_is_not_public_or_directly_worker_executable(database):
    owner = database["owner"]
    assert owner.execute(
        "SELECT NOT EXISTS(SELECT FROM pg_proc p,aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
        "WHERE p.oid='material_execution.live_send_current(uuid)'::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE') AS private"
    ).fetchone()["private"]
    with database["execution_worker_factory"]() as c:
        assert not c.execute(
            "SELECT has_function_privilege(session_user,'material_execution.live_send_current(uuid)','EXECUTE') AS allowed"
        ).fetchone()["allowed"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT material_execution.live_send_current(%s)", (str(uuid4()),))
