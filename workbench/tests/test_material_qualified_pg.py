"""Opt-in native boundaries. Synthetic declarations are not capability evidence."""
# ruff: noqa: F401,F811

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from test_judgment_jobs_pg import ready as job_ready
from test_judgment_jobs_pg import start
from test_material_execution_attempts_pg import (
    WORKER,
    api,
    begin,
    database,
    exact,
    execute,
    pdf_data,
    ready,
    requirements,
    saved,
    wire,
    world,
)
from test_preparation_leases_pg import publish as publish_preparation

from packages.domain.runtime import sha
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_judgment_jobs as jobs
from packages.model_governance import material_qualification_guard as guard
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import package_technical_complete_vision as vision

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_EXECUTION_PG") != "1",
    reason="explicit isolated native qualification/job/budget PG17 fixture required",
)
ROOT = Path(__file__).resolve().parents[1]


def install(owner):
    owner.execute((ROOT / "deploy/sql/material-qualification.sql").read_text())
    owner.execute((ROOT / "deploy/sql/material-qualified-execution.sql").read_text())


@pytest.fixture(autouse=True)
def cleanup(database):
    yield
    database["owner"].execute("DROP SCHEMA IF EXISTS material_qualification CASCADE")


def execution_profile(w, args, currency):
    owner = w["database"]["owner"]
    prep, prep_digest = publish_preparation(
        w,
        SimpleNamespace(
            metadata={
                "document": {
                    "profile_id": args["profile_id"],
                    "profile_digest": args["expected_profile_digest"],
                }
            }
        ),
        lease_seconds=120,
    )
    account, identity = str(uuid4()), str(uuid4())
    owner.execute(
        "INSERT INTO material_execution.accounts VALUES(%s,%s,90000000,'synthetic_mechanism')",
        (account, currency),
    )
    owner.execute("INSERT INTO material_execution.balances VALUES(%s,0,0)", (account,))
    now = datetime.now(timezone.utc)
    values = {
        "id": identity,
        "worker_login": WORKER,
        "worker_login_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (WORKER,)
        ).fetchone()["oid"],
        "preparation_profile_id": prep,
        "preparation_profile_digest": prep_digest,
        "account_id": account,
        "origin": "synthetic_mechanism",
        "execution_method_digest": execution.method_digest(),
        "execution_sql_method_digest": owner.execute(
            "SELECT material_execution.native_method_digest() AS value"
        ).fetchone()["value"],
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
        (WORKER, identity),
    )
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') AS value FROM material_execution.profiles p WHERE id=%s",
        (identity,),
    ).fetchone()["value"]
    return identity, checksum, account


def seed(owner, args, executor, requests=None, mutate=None, guard_digest=None):
    renewal = owner.execute(
        "SELECT * FROM material_input_renewal.records WHERE id=%s", (args["renewal_id"],)
    ).fetchone()
    sealed = owner.execute(
        "SELECT * FROM material_input_seal.records WHERE id=%s", (renewal["seal_id"],)
    ).fetchone()
    quote = owner.execute(
        "SELECT * FROM material_cost_quote.quotes WHERE id=%s", (renewal["quote_id"],)
    ).fetchone()
    price = owner.execute(
        "SELECT price_policy FROM material_cost_quote.policies WHERE id=%s", (quote["policy_id"],)
    ).fetchone()["price_policy"]
    actor = owner.execute(
        "SELECT id FROM design.members WHERE active ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    proof = owner.execute(
        "SELECT v.id,b.digest FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s LIMIT 1",
        (renewal["bid_id"],),
    ).fetchone()
    qualification_id, decision_id = str(uuid4()), str(uuid4())
    binding = {
        "scope_digest": sealed["document"]["scope_digest"],
        "input_digest": sealed["document"]["material_input_digest"],
        "seal_id": str(sealed["id"]),
        "seal_digest": sealed["digest"],
        "quote_id": str(quote["id"]),
        "quote_digest": quote["digest"],
        "job_profile_id": args["profile_id"],
        "job_profile_digest": args["expected_profile_digest"],
        "execution_profile_id": executor[0],
        "execution_profile_digest": executor[1],
        "account_id": executor[2],
        "profile_digest": vision.profile_digest(),
        "serializer_digest": vision.serializer_digest(),
        "judgment_method_digest": vision.judgment_method_digest(),
    }
    doc = {
        "version": "material-qualification-review/1",
        "binding": binding,
        "price": price,
        "evidence": {
            kind: {
                "document_version_id": str(proof["id"]),
                "digest": proof["digest"],
                "note": "Synthetic fixture, not provider evidence",
            }
            for kind in ("price", "capacity", "validation")
        },
        "requests": requests
        if requests is not None
        else [
            {"rule_id": rule, "request_digest": sha(rule), "body_byte_count": 1, "input_tokens": 1}
            for rule in quote["document"]["quote"]["rule_ids"]
        ],
        "valid_from": price["valid_from"],
        "valid_until": price["valid_until"],
    }
    if mutate is not None:
        mutate(doc)
    owner.execute(
        "INSERT INTO material_qualification.records(id,bid_id,scope_id,document,digest,created_by) VALUES(%s,%s,%s,%s,%s,%s)",
        (qualification_id, renewal["bid_id"], renewal["scope_id"], Jsonb(doc), sha(doc), actor),
    )
    owner.execute(
        "INSERT INTO material_qualification.decisions(id,record_id,revision,decision,actor_id,reason) VALUES(%s,%s,1,'approved',%s,'synthetic fixture approval')",
        (decision_id, qualification_id, actor),
    )
    owner.execute(
        "INSERT INTO material_qualification.heads VALUES(%s,%s,1)", (qualification_id, decision_id)
    )
    request = {
        "version": "material-qualified-job-request/1",
        "scope_digest": binding["scope_digest"],
        "qualification_id": qualification_id,
        "qualification_digest": sha(doc),
        "qualification_revision": 1,
        "renewal_id": args["renewal_id"],
        "renewal_digest": args["expected_renewal_digest"],
    }
    document = {
        "version": "material-qualified-job-intent/1",
        "guard_digest": guard_digest or guard.method_digest(),
        "request_key_digest": sha("synthetic"),
        "request": request,
        "command": {"version": "material-job-command/1", "operation": "start", "arguments": args},
    }
    owner.execute(
        "INSERT INTO design.commands(id,actor_id,command_kind,target_id,idempotency_key,request_digest) VALUES(%s,%s,'qualified-test',%s,%s,%s)",
        (args["command_id"], actor, renewal["scope_id"], args["command_id"], sha(document)),
    )
    owner.execute(
        "INSERT INTO material_qualification.intents VALUES(%s,%s,%s,%s,%s,%s,1,%s,%s)",
        (
            args["command_id"],
            actor,
            renewal["bid_id"],
            renewal["scope_id"],
            qualification_id,
            sha(doc),
            Jsonb(document),
            sha(document),
        ),
    )
    return qualification_id, actor


def revoke(owner, qualification, actor):
    identity = str(uuid4())
    owner.execute(
        "INSERT INTO material_qualification.decisions VALUES(%s,%s,2,'revoked',%s,'withdrawn',clock_timestamp())",
        (identity, qualification, actor),
    )
    owner.execute(
        "UPDATE material_qualification.heads SET revision=2,decision_id=%s WHERE record_id=%s",
        (identity, qualification),
    )


def test_native_job_and_outbox_accept_once_then_replay_after_revoke(wire, monkeypatch):
    w, _, _ = wire
    _, _, args = job_ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    currency = owner.execute(
        "SELECT q.document#>>'{quote,currency}' AS value FROM material_input_renewal.records r JOIN material_cost_quote.quotes q ON q.id=r.quote_id WHERE r.id=%s",
        (args["renewal_id"],),
    ).fetchone()["value"]
    executor = execution_profile(w, args, currency)
    install(owner)
    qualification, actor = seed(owner, args, executor)

    def submit():
        with w["database"]["job_submitter_factory"]() as connection:
            return start(w, args, connection)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(submit), pool.submit(submit)
        job = first.result(timeout=10)
        assert second.result(timeout=10) == job
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM material_qualification.acceptances WHERE intent_id=%s",
            (args["command_id"],),
        ).fetchone()["n"]
        == 1
    )
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM material_judgment_job.outbox WHERE job_id=%s",
            (job.metadata["document"]["job_id"],),
        ).fetchone()["n"]
        == 1
    )
    revoke(owner, qualification, actor)
    assert start(w, args) == job


def qualified_lane(wire, monkeypatch):
    lane = ready(wire, monkeypatch)
    owner = lane["world"]["database"]["owner"]
    d = lane["job"].metadata["document"]
    args = {
        "renewal_id": d["initial_renewal_id"],
        "expected_renewal_digest": d["initial_renewal_digest"],
        "profile_id": d["profile_id"],
        "expected_profile_digest": d["profile_digest"],
        "command_id": d["command_id"],
        "expected_method_digest": jobs.method_digest(),
    }
    install(owner)
    requests = [
        {k: r[k] for k in ("rule_id", "request_digest", "body_byte_count")} | {"input_tokens": 1}
        for r in lane["checked"].metadata["requests"]
    ]
    qualification, actor = seed(
        owner, args, (lane["profile_id"], lane["profile_digest"], lane["account_id"]), requests
    )
    # Explicit prepared-job fixture for execution-boundary tests. Job creation
    # itself is covered by the separate real start/outbox test above.
    owner.execute(
        "INSERT INTO material_qualification.acceptances(intent_id,job_id,job_digest,document) VALUES(%s,%s,%s,%s)",
        (d["command_id"], d["job_id"], lane["job"].metadata["digest"], Jsonb(d)),
    )
    return lane, owner, qualification, actor


def test_revoked_qualification_rolls_back_native_budget_reservation(wire, monkeypatch):
    lane, owner, qualification, actor = qualified_lane(wire, monkeypatch)
    revoke(owner, qualification, actor)
    with pytest.raises(execution.MaterialExecutionError):
        begin(lane)
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM material_execution.reservations WHERE job_id=%s",
            (lane["job"].metadata["document"]["job_id"],),
        ).fetchone()["n"]
        == 0
    )
    balance = owner.execute(
        "SELECT * FROM material_execution.balances WHERE account_id=%s", (lane["account_id"],)
    ).fetchone()
    assert balance["held_minor"] == balance["estimated_minor"] == 0


def test_revocation_after_grant_does_not_block_unknown_billing_settlement(wire, monkeypatch):
    lane, owner, qualification, actor = qualified_lane(wire, monkeypatch)
    result = execute(
        lane, raw=b"unreadable response", callback=lambda: revoke(owner, qualification, actor)
    )
    assert result.metadata["outcome"]["document"]["billing_state"] == "unknown"
    with pytest.raises(execution.MaterialExecutionError):
        begin(lane, 1)


@pytest.mark.parametrize(
    "case", ["expired", "input_drift", "price_drift", "missing_evidence", "guard_drift"]
)
def test_native_rejection_leaves_no_job_or_outbox(wire, monkeypatch, case):
    w, _, _ = wire
    _, _, args = job_ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    currency = owner.execute(
        "SELECT q.document#>>'{quote,currency}' AS value FROM material_input_renewal.records r JOIN material_cost_quote.quotes q ON q.id=r.quote_id WHERE r.id=%s",
        (args["renewal_id"],),
    ).fetchone()["value"]
    executor = execution_profile(w, args, currency)
    install(owner)

    def mutate(doc):
        if case == "expired":
            doc["valid_until"] = "2020-01-01T00:00:00Z"
        elif case == "input_drift":
            doc["binding"]["input_digest"] = "f" * 64
        elif case == "price_drift":
            doc["price"]["input_per_million_minor"] += 1
        elif case == "missing_evidence":
            doc["evidence"] = {}

    seed(
        owner,
        args,
        executor,
        mutate=mutate,
        guard_digest="f" * 64 if case == "guard_drift" else None,
    )
    with pytest.raises(jobs.JudgmentJobError):
        start(w, args)
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM material_judgment_job.jobs WHERE command_id=%s",
            (args["command_id"],),
        ).fetchone()["n"]
        == 0
    )
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM material_qualification.acceptances WHERE intent_id=%s",
            (args["command_id"],),
        ).fetchone()["n"]
        == 0
    )


def test_concurrent_revoke_serializes_before_grant_and_rolls_back_budget(wire, monkeypatch):
    lane, owner, qualification, actor = qualified_lane(wire, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with owner.transaction():
            revoke(owner, qualification, actor)
            attempt = pool.submit(begin, lane)
            time.sleep(0.05)
            assert not attempt.done()
        with pytest.raises(execution.MaterialExecutionError):
            attempt.result(timeout=10)
    balance = owner.execute(
        "SELECT * FROM material_execution.balances WHERE account_id=%s", (lane["account_id"],)
    ).fetchone()
    assert balance["held_minor"] == balance["estimated_minor"] == 0


@pytest.mark.parametrize("unknown", [False, True])
def test_execution_status_view_tracks_settlement_after_revocation_without_capabilities(
    wire, monkeypatch, unknown
):
    lane, owner, qualification, actor = qualified_lane(wire, monkeypatch)
    kwargs = {"raw": b"unreadable response"} if unknown else {}
    result = execute(lane, callback=lambda: revoke(owner, qualification, actor), **kwargs)
    job_id = lane["job"].metadata["document"]["job_id"]
    row = owner.execute(
        "SELECT * FROM material_qualification.execution_status WHERE job_id=%s", (job_id,)
    ).fetchone()
    assert row["qualification_state"] == "revoked"
    assert row["attempt_count"] == 1 and row["unsettled_count"] == 0
    assert row["unknown_count"] == int(unknown)
    assert row["known_estimated_minor"] == result.metadata["job_balance"]["estimated_minor"]
    assert row["last_settled_at"] is not None
    assert not {"send_token", "raw_response", "document", "price_policy"} & set(row)
    assert owner.execute(
        "SELECT has_table_privilege('tender_api','material_qualification.execution_status','SELECT') AS allowed"
    ).fetchone()["allowed"]
    assert not owner.execute(
        "SELECT has_table_privilege('tender_api','material_execution.attempts','SELECT') AS allowed"
    ).fetchone()["allowed"]
