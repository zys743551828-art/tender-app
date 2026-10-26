"""Native full-rule jobs preserve original intent across current-evidence renewal."""
# ruff: noqa: F401,F811

import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_cost_quotes_pg import quote
from test_input_renewals_pg import (
    ADMIN_DSN,
    api,
    exact,
    fresh_program,
    pdf_data,
    requirements,
    saved,
    wire,
    wire_digests,
    world,
)
from test_input_renewals_pg import database as renewal_database
from test_input_renewals_pg import ready as renewal_ready
from test_input_renewals_pg import record as record_renewal
from test_input_renewals_pg import reread as read_renewal
from test_verification_commands_pg import begin
from test_verification_program_pg import observation
from test_verification_program_pg import record as finish_program

from packages.model_governance import material_cost_quotes as prices
from packages.model_governance import material_input_authority as authority
from packages.model_governance import material_input_renewals as renewals
from packages.model_governance import material_judgment_jobs as jobs

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_JUDGMENT_JOBS_PG") != "1",
    reason="explicit fresh native judgment-job fixture required",
)
SUBMITTER = "fusion_material_job_submitter"
OTHER = "fusion_other_material_job_submitter"


@pytest.fixture(scope="module")
def database():
    base = renewal_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    installed = False
    try:
        owner.execute(jobs.SQL_FILE.read_text(encoding="utf-8"))
        installed = True
        factories = {}
        for role in (SUBMITTER, OTHER):
            assert not owner.execute("SELECT FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            created.append(role)
            owner.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(jobs.GROUP), sql.Identifier(role))
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=role, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[role] = factory
        with factories[SUBMITTER]() as c, factories[OTHER]() as other:
            yield value | {
                "job_submitter": c,
                "job_submitter_factory": factories[SUBMITTER],
                "other_job_submitter": other,
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
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(jobs.GROUP))
                    )


def publish(w, renewed, **changes):
    owner = w["database"]["owner"]
    d = renewed.metadata["document"]
    now = datetime.now(timezone.utc)
    source = owner.execute(
        "SELECT c.actor,c.document FROM material_verification.commands c JOIN material_input_authority.verifications v ON (v.document->>'program_command_row_id')::uuid=c.id WHERE v.id=%s",
        (d["admission_verification_id"],),
    ).fetchone()
    values = {
        "id": str(uuid4()),
        "submit_login": SUBMITTER,
        "submit_login_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (SUBMITTER,)
        ).fetchone()["oid"],
        "request_login": source["actor"],
        "request_login_oid": source["document"]["recorded_by_oid"],
        "renewal_profile_id": d["profile_id"],
        "renewal_profile_digest": d["profile_digest"],
        "origin": "synthetic_mechanism",
        "job_method_digest": jobs.method_digest(),
        "job_sql_method_digest": owner.execute(
            "SELECT material_judgment_job.native_method_digest() AS v"
        ).fetchone()["v"],
        "database_oid": owner.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()["oid"],
        "database_name": owner.info.dbname,
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(hours=1),
    } | changes
    owner.execute(
        sql.SQL("INSERT INTO material_judgment_job.profiles ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    owner.execute(
        "INSERT INTO material_judgment_job.profile_heads VALUES(%s,%s,1,true) ON CONFLICT(submit_login) DO UPDATE SET profile_id=excluded.profile_id,revision=excluded.revision,enabled=true",
        (values["submit_login"], values["id"]),
    )
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') AS v FROM material_judgment_job.profiles p WHERE id=%s",
        (values["id"],),
    ).fetchone()["v"]
    return values["id"], checksum


def ready(wire, monkeypatch, *, age=120, budget=None, **changes):
    w, _, _ = wire
    data = renewal_ready(wire, monkeypatch, age=age)
    args = data[-1]
    if budget is not None:
        sealed, quoted = data[2:4]
        d = quoted.metadata["document"]
        replacement = quote(
            w,
            {
                "seal_id": sealed.metadata["document"]["seal_id"],
                "expected_seal_digest": sealed.metadata["digest"],
                "policy_id": d["policy_id"],
                "expected_policy_digest": d["policy_digest"],
                "command_id": str(uuid4()),
                "max_attempts_per_slot": 5,
                "budget_currency": "USD",
                "budget_ceiling_minor": budget,
                "expected_method_digest": prices.method_digest(),
            },
        )
        args = args | {
            "quote_id": replacement.metadata["document"]["quote_id"],
            "expected_quote_digest": replacement.metadata["digest"],
        }
        data = (*data[:3], replacement, data[4], args)
    renewed = record_renewal(w, args)
    profile_id, profile_digest = publish(w, renewed, **changes)
    return (
        data,
        renewed,
        {
            "renewal_id": renewed.metadata["document"]["renewal_id"],
            "expected_renewal_digest": renewed.metadata["digest"],
            "profile_id": profile_id,
            "expected_profile_digest": profile_digest,
            "command_id": str(uuid4()),
            "expected_method_digest": jobs.method_digest(),
        },
    )


def start(w, args, connection=None):
    return jobs.start(w["database"]["job_submitter"] if connection is None else connection, **args)


def reread(w, job):
    with w["database"]["job_submitter_factory"]() as c:
        return jobs.read(
            c,
            job_id=job.metadata["document"]["job_id"],
            expected_job_digest=job.metadata["digest"],
            expected_method_digest=jobs.method_digest(),
        )


def renew_again(wire, monkeypatch, data):
    w, _, _ = wire
    current, logical = fresh_program(wire, data[0], monkeypatch)
    return record_renewal(
        w,
        data[-1]
        | {
            "verification_id": current.metadata["document"]["verification_id"],
            "expected_verification_digest": current.metadata["digest"],
            "command_id": logical,
        },
    )


def refresh_args(job, renewed, revision=1):
    return {
        "job_id": job.metadata["document"]["job_id"],
        "expected_job_digest": job.metadata["digest"],
        "renewal_id": renewed.metadata["document"]["renewal_id"],
        "expected_renewal_digest": renewed.metadata["digest"],
        "expected_revision": revision,
        "command_id": str(uuid4()),
        "expected_method_digest": jobs.method_digest(),
    }


def test_native_job_all_slots_original_intent_and_current_evidence_history(wire, monkeypatch):
    w, state, _ = wire
    data, first, args = ready(wire, monkeypatch, age=5)
    job = start(w, args)
    before = reread(w, job)
    d = job.metadata["document"]
    assert before.record == job and before.metadata["current"]["software_preparation_current"]
    assert before.metadata["current"]["software_budget_sufficient"] and state["attempts"] == 12
    assert start(w, args) == job
    assert d["rule_ids"] == [
        r["rule_id"] for r in data[1].metadata["rules"] if r["selection"] == "include"
    ]
    assert len(d["slots"]) == len(d["rule_ids"]) * 3 and all(not d[k] for k in jobs.FALSE_FIELDS)
    owner = w["database"]["owner"]
    initial = owner.execute(
        "SELECT command_id FROM material_verification.commands WHERE id=%s",
        (data[0].metadata["document"]["program_command_row_id"],),
    ).fetchone()
    assert d["intent_command_id"] == str(initial["command_id"])
    with pytest.raises(jobs.JudgmentJobError, match="INTENT_ALREADY_REGISTERED"):
        start(w, args | {"command_id": str(uuid4())})
    renewed = renew_again(wire, monkeypatch, data)
    change = refresh_args(job, renewed)
    event = jobs.refresh(w["database"]["job_submitter"], **change)
    assert jobs.refresh(w["database"]["job_submitter"], **change) == event
    observed = reread(w, job)
    assert (
        observed.record == job
        and observed.evidence == event
        and observed.metadata["current"]["evidence_revision"] == 2
    )
    assert observed.metadata["current"]["software_preparation_current"]
    with pytest.raises(jobs.JudgmentJobError, match="INTENT_ALREADY_REGISTERED"):
        start(
            w,
            args
            | {
                "renewal_id": change["renewal_id"],
                "expected_renewal_digest": change["expected_renewal_digest"],
                "command_id": str(uuid4()),
            },
        )
    with pytest.raises(jobs.JudgmentJobError, match="REVISION_CONFLICT"):
        jobs.refresh(w["database"]["job_submitter"], **(change | {"command_id": str(uuid4())}))
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM material_judgment_job.jobs WHERE intent_command_id=%s",
            (d["intent_command_id"],),
        ).fetchone()["n"]
        == 1
    )
    outbox = owner.execute(
        "SELECT event_type,payload FROM material_judgment_job.outbox WHERE job_id=%s",
        (d["job_id"],),
    ).fetchone()
    assert outbox["payload"] == {"job_id": d["job_id"], "generation": 1}
    assert wire_digests(data[1], data[0].binding)[0] == d["material_input_digest"]
    recorded = owner.execute(
        "SELECT document->>'recorded_at' AS v FROM material_verification.program_results WHERE id=(SELECT program_result_id FROM material_input_authority.verifications WHERE id=%s)",
        (renewed.metadata["document"]["current_verification_id"],),
    ).fetchone()["v"]
    deadline = datetime.fromisoformat(recorded.replace("Z", "+00:00")) + timedelta(seconds=5)
    time.sleep(max(0, (deadline - datetime.now(timezone.utc)).total_seconds()) + 0.05)
    expired = reread(w, job)
    assert (
        expired.record == job
        and expired.evidence == event
        and not expired.metadata["current"]["software_preparation_current"]
    )
    assert start(w, args) == job and jobs.refresh(w["database"]["job_submitter"], **change) == event
    directory = os.environ.get("FUSION_JUDGMENT_JOBS_EVIDENCE")
    if directory:
        Path(directory, "judgment-jobs-proof.json").write_text(
            json.dumps(
                {
                    "method_digest": jobs.method_digest(),
                    "job": job.metadata,
                    "initial": before.metadata,
                    "refreshed": observed.metadata,
                    "expired": expired.metadata,
                    "outbox": outbox,
                    "actual_loopback_gets": state["attempts"],
                    "original_intent_unique": True,
                    "complete_rules_and_three_native_slots": True,
                    "evidence_refresh_preserves_job_input_quote_and_slots": True,
                    "synthetic_renderer_stub": True,
                    "actual_renderer_used": False,
                    "synthetic_material_and_configuration": True,
                    "actual_human_review": False,
                    "model_calls_created": 0,
                    "provider_attempts": 0,
                    "fee_ledger_reserved": False,
                    "execution_authorized": False,
                    "outbox_delivered": False,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_sql_method_digest", "e" * 64),
        ("renewal_profile_digest", "e" * 64),
        ("submit_login_oid", 1),
        ("request_login_oid", 1),
        ("database_oid", 1),
        ("database_name", "wrong_database"),
        ("origin", "current_prebid"),
    ],
)
def test_profile_method_identity_realm_and_request_epoch_reject(wire, monkeypatch, field, value):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch, **{field: value})
    with pytest.raises(jobs.JudgmentJobError, match="CURRENT_STATE_UNAVAILABLE"):
        start(w, args)


def test_insufficient_complete_budget_creates_no_partial_job_slots_or_outbox(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch, budget=0)
    with pytest.raises(jobs.JudgmentJobError, match="BUDGET_INSUFFICIENT"):
        start(w, args)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_judgment_job.jobs WHERE command_id=%s",
            (args["command_id"],),
        )
        .fetchone()["n"]
        == 0
    )


def test_new_verification_case_cannot_revive_revoked_original_request(wire, monkeypatch):
    w, _, _ = wire
    data, _, args = ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    admission = data[0].metadata["document"]
    original_case = admission["program_case_id"]
    case = dict(
        owner.execute(
            "SELECT * FROM material_verification.cases WHERE id=%s", (original_case,)
        ).fetchone()
    )
    case["id"] = str(uuid4())
    owner.execute(
        sql.SQL("INSERT INTO material_verification.cases ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, case)),
            sql.SQL(",").join(sql.Placeholder() for _ in case),
        ),
        list(case.values()),
    )
    owner.execute("INSERT INTO material_verification.case_heads VALUES(%s,1,true)", (case["id"],))
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(c)),'UTF8')),'hex') AS v FROM material_verification.cases c WHERE id=%s",
        (case["id"],),
    ).fetchone()["v"]
    logical = str(uuid4())
    ticket = begin(w, (admission["program_profile_id"], case["id"], checksum), logical)
    staged = (None, ticket)
    result = finish_program(w, staged, observation(wire, staged, monkeypatch))
    current = authority.qualify(
        w["database"]["input_verifier"],
        program_result_id=result.metadata["document"]["result_id"],
        expected_program_result_digest=result.metadata["digest"],
        policy_id=admission["policy_id"],
        expected_policy_digest=admission["policy_digest"],
        command_id=logical,
        expected_method_digest=authority.method_digest(),
    )
    renewed = record_renewal(
        w,
        data[-1]
        | {
            "verification_id": current.metadata["document"]["verification_id"],
            "expected_verification_digest": current.metadata["digest"],
            "command_id": logical,
        },
    )
    owner.execute(
        "UPDATE material_verification.case_heads SET enabled=false,revision=revision+1 WHERE case_id=%s",
        (original_case,),
    )
    assert read_renewal(w, renewed).metadata["current"]["software_evidence_current"]
    with pytest.raises(jobs.JudgmentJobError, match="CURRENT_STATE_UNAVAILABLE"):
        start(
            w,
            args
            | {
                "renewal_id": renewed.metadata["document"]["renewal_id"],
                "expected_renewal_digest": renewed.metadata["digest"],
            },
        )


def test_other_roles_and_other_assigned_login_cannot_register(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    for key in (
        "owner",
        "native_registrar",
        "verification_program",
        "input_verifier",
        "input_sealer",
        "cost_quoter",
        "input_renewer",
        "other_job_submitter",
    ):
        with pytest.raises(jobs.JudgmentJobError):
            start(w, args, w["database"][key])


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE material_judgment_job.profile_heads SET enabled=false,revision=revision+1",
        "UPDATE material_input_renewal.profile_heads SET revision=revision+1",
        "UPDATE material_cost_quote.policy_heads SET enabled=false,revision=revision+1",
        "UPDATE material_input_authority.policy_heads SET revision=revision+1",
        "UPDATE design.bid_profiles SET phase='closed'",
    ],
)
def test_revocation_keeps_job_but_removes_current_preparation(wire, monkeypatch, mutation):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    job = start(w, args)
    w["database"]["owner"].execute(mutation)
    observed = reread(w, job)
    assert (
        observed.record == job and not observed.metadata["current"]["software_preparation_current"]
    )
    assert start(w, args) == job


def test_four_connections_create_one_job_slots_and_outbox(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)

    def run(_):
        with w["database"]["job_submitter_factory"]() as c:
            return start(w, args, c)

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(run, range(4)))
    assert all(record == records[0] for record in records)
    with pytest.raises(jobs.JudgmentJobError, match="COMMAND_CONFLICT"):
        start(w, args | {"expected_renewal_digest": "d" * 64})


def test_native_return_validation_rolls_back_all_job_artifacts(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch, job_method_digest="e" * 64)
    owner = w["database"]["owner"]
    before = owner.execute(
        "SELECT (SELECT count(*) FROM material_judgment_job.jobs) AS jobs,(SELECT count(*) FROM material_judgment_job.slots) AS slots,(SELECT count(*) FROM material_judgment_job.outbox) AS outbox"
    ).fetchone()
    with pytest.raises(jobs.JudgmentJobError, match="NATIVE_RESULT_INVALID"):
        start(w, args)
    assert (
        owner.execute(
            "SELECT (SELECT count(*) FROM material_judgment_job.jobs) AS jobs,(SELECT count(*) FROM material_judgment_job.slots) AS slots,(SELECT count(*) FROM material_judgment_job.outbox) AS outbox"
        ).fetchone()
        == before
    )


@pytest.mark.parametrize(
    "change,restore",
    [
        (
            "GRANT SELECT ON material_judgment_job.slots TO PUBLIC",
            "REVOKE SELECT ON material_judgment_job.slots FROM PUBLIC",
        ),
        (
            "GRANT EXECUTE ON FUNCTION material_judgment_job.lock_inputs(uuid) TO tender_material_judgment_submit",
            "REVOKE EXECUTE ON FUNCTION material_judgment_job.lock_inputs(uuid) FROM tender_material_judgment_submit",
        ),
        (
            "ALTER FUNCTION material_input_renewal.current_context(uuid,uuid,uuid,uuid) SET TimeZone='Asia/Shanghai'",
            "ALTER FUNCTION material_input_renewal.current_context(uuid,uuid,uuid,uuid) SET TimeZone='UTC'",
        ),
    ],
)
def test_grants_or_dependency_method_drift_fail_closed(wire, monkeypatch, change, restore):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    owner.execute(change)
    try:
        with pytest.raises(jobs.JudgmentJobError):
            start(w, args)
    finally:
        owner.execute(restore)


def test_operator_command_registers_one_native_outbox_and_recovers(wire, monkeypatch):
    from packages.model_governance import material_job_commands as commands

    w, _, _ = wire
    data, _, args = ready(wire, monkeypatch)
    connection = w["database"]["job_submitter"]
    cmd = {"version": commands.VERSION, "operation": "start", "arguments": args}
    receipt = commands.execute(connection, cmd)
    assert commands.execute(connection, cmd) == receipt
    read = {
        "version": commands.VERSION,
        "operation": "read",
        "arguments": {
            "job_id": receipt["job_id"],
            "expected_job_digest": receipt["job_digest"],
            "expected_method_digest": args["expected_method_digest"],
        },
    }
    assert commands.execute(connection, read)["current"]["software_preparation_current"]
    job = start(w, args)
    renewed = renew_again(wire, monkeypatch, data)
    refresh = {
        "version": commands.VERSION,
        "operation": "refresh",
        "arguments": refresh_args(job, renewed),
    }
    assert commands.execute(connection, refresh)["evidence_revision"] == 2
    assert commands.execute(connection, read)["current"]["evidence_revision"] == 2
    count = (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_judgment_job.outbox WHERE job_id=%s",
            (receipt["job_id"],),
        )
        .fetchone()["n"]
    )
    assert count == 1 and receipt["model_requests"] == 0
