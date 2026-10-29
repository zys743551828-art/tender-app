"""Native preparation ownership, expiry, fencing and exact owned bytes."""

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
from test_judgment_jobs_pg import ADMIN_DSN, api, exact, pdf_data, requirements, saved, wire, world
from test_judgment_jobs_pg import database as job_database
from test_judgment_jobs_pg import ready as job_ready
from test_judgment_jobs_pg import start as start_job

from packages.model_governance import material_preparation_leases as leases
from packages.storage.private_cas import sha

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PREPARATION_LEASES_PG") != "1",
    reason="explicit owned preparation native fixture required",
)
WORKER = "fusion_material_preparation_worker"
OTHER = "fusion_other_preparation_worker"


@pytest.fixture(scope="module")
def database():
    base = job_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    installed = False
    try:
        owner.execute(leases.SQL_FILE.read_text(encoding="utf-8"))
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
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(leases.GROUP), sql.Identifier(role))
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=role, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[role] = factory
        with factories[WORKER]() as c, factories[OTHER]() as other:
            yield value | {
                "preparation_worker": c,
                "preparation_worker_factory": factories[WORKER],
                "other_preparation_worker": other,
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
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(leases.GROUP))
                    )


def publish(w, job, **changes):
    owner = w["database"]["owner"]
    d = job.metadata["document"]
    now = datetime.now(timezone.utc)
    values = {
        "id": str(uuid4()),
        "worker_login": WORKER,
        "worker_login_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (WORKER,)
        ).fetchone()["oid"],
        "job_profile_id": d["profile_id"],
        "job_profile_digest": d["profile_digest"],
        "origin": "synthetic_mechanism",
        "lease_seconds": 30,
        "preparation_method_digest": leases.method_digest(),
        "preparation_sql_method_digest": owner.execute(
            "SELECT material_preparation.native_method_digest() AS v"
        ).fetchone()["v"],
        "database_oid": owner.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()["oid"],
        "database_name": owner.info.dbname,
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(hours=1),
    } | changes
    owner.execute(
        sql.SQL("INSERT INTO material_preparation.profiles ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    owner.execute(
        "INSERT INTO material_preparation.profile_heads VALUES(%s,%s,1,true) ON CONFLICT(worker_login) DO UPDATE SET profile_id=excluded.profile_id,revision=excluded.revision,enabled=true",
        (values["worker_login"], values["id"]),
    )
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') AS v FROM material_preparation.profiles p WHERE id=%s",
        (values["id"],),
    ).fetchone()["v"]
    return values["id"], checksum


def ready(wire, monkeypatch, **changes):
    w, _, _ = wire
    data, _, job_args = job_ready(wire, monkeypatch)
    job = start_job(w, job_args)
    profile, checksum = publish(w, job, **changes)
    return (
        data,
        job,
        {
            "job_id": job.metadata["document"]["job_id"],
            "expected_job_digest": job.metadata["digest"],
            "profile_id": profile,
            "expected_profile_digest": checksum,
            "command_id": str(uuid4()),
            "expected_method_digest": leases.method_digest(),
        },
    )


def claim(w, args, connection=None):
    return leases.claim(
        w["database"]["preparation_worker"] if connection is None else connection, **args
    )


def refs(record):
    return {
        "lease_id": record.metadata["document"]["lease_id"],
        "expected_lease_digest": record.metadata["digest"],
        "expected_method_digest": leases.method_digest(),
    }


def inspect(w, record):
    with w["database"]["preparation_worker_factory"]() as c:
        return leases.inspect(c, **refs(record))


def test_owned_exact_context_and_all_assets_heartbeat_and_reopen(wire, monkeypatch):
    w, state, _ = wire
    data, job, args = ready(wire, monkeypatch)
    record = claim(w, args)
    observed = inspect(w, record)
    assert observed.record == record and observed.metadata["current"]["preparation_lease_current"]
    assert claim(w, args) == record and state["attempts"] == 12
    projection = leases.owned_context(w["database"]["preparation_worker"], **refs(record))
    assert projection.metadata["context"] == data[1].metadata
    assert projection.metadata["material_input"] == data[2].metadata["document"]["material_input"]
    assert (
        projection.metadata["material_input"]["digest"]
        == job.metadata["document"]["material_input_digest"]
    )
    expected = {
        sha(raw): raw
        for bundle in data[1].origin.page_bundles.values()
        for raw in bundle.blobs.values()
    }
    batch = leases.owned_assets(
        w["database"]["preparation_worker"],
        **refs(record),
        expected_object_digests=sorted(expected),
    )
    assert sorted(batch.objects) == sorted(expected)
    assert all(sha(batch.objects[key]) == sha(raw) for key, raw in expected.items())
    with pytest.raises(leases.PreparationError, match="OWNED_BATCH_INVALID"):
        leases.owned_assets(
            w["database"]["preparation_worker"],
            **refs(record),
            expected_object_digests=sorted(expected)[:-1],
        )
    for key, raw in expected.items():
        assert (
            leases.owned_asset(
                w["database"]["preparation_worker"], **refs(record), object_digest=key
            ).data
            == raw
        )
    with pytest.raises(leases.PreparationError, match="ASSET_NOT_OWNED"):
        leases.owned_asset(
            w["database"]["preparation_worker"],
            **refs(record),
            object_digest=projection.metadata["context_object_digest"],
        )
    command = str(uuid4())
    beat = leases.heartbeat(w["database"]["preparation_worker"], **refs(record), command_id=command)
    assert (
        leases.heartbeat(w["database"]["preparation_worker"], **refs(record), command_id=command)
        == beat
    )
    current = inspect(w, record)
    assert current.metadata["current"]["lease_until"] == beat.metadata["document"]["lease_until"]
    assert current.metadata["current"]["preparation_lease_current"] and state["attempts"] == 12
    directory = os.environ.get("FUSION_PREPARATION_LEASES_EVIDENCE")
    if directory:
        Path(directory, "preparation-leases-proof.json").write_text(
            json.dumps(
                {
                    "method_digest": leases.method_digest(),
                    "lease": record.metadata,
                    "reopened": observed.metadata,
                    "heartbeat": beat.metadata,
                    "after_heartbeat": current.metadata,
                    "context_digest": projection.metadata["context"]["digest"],
                    "material_input_digest": projection.metadata["material_input"]["digest"],
                    "owned_asset_digests": sorted(expected),
                    "complete_context_and_owned_image_bytes_verified": True,
                    "complete_owned_image_batch_verified": True,
                    "partial_batch_rejected": True,
                    "non_image_context_object_denied": True,
                    "projection_is_not_authorized_material_context": True,
                    "actual_loopback_gets": 12,
                    "additional_gets_for_ownership": 0,
                    "synthetic_renderer_stub": True,
                    "actual_renderer_used": False,
                    "synthetic_material_and_configuration": True,
                    "actual_human_review": False,
                    "fee_ledger_reserved": False,
                    "execution_authorized": False,
                    "send_lease_granted": False,
                    "model_calls_created": 0,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def test_expired_owner_cannot_read_or_heartbeat_after_fence_advance(wire, monkeypatch):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch, lease_seconds=1)
    first = claim(w, args)
    old_refs = refs(first)
    deadline = datetime.fromisoformat(
        first.metadata["document"]["lease_until"].replace("Z", "+00:00")
    )
    time.sleep(max(0, (deadline - datetime.now(timezone.utc)).total_seconds()) + 0.02)
    assert not inspect(w, first).metadata["current"]["preparation_lease_current"]
    second = claim(w, args | {"command_id": str(uuid4())})
    assert second.metadata["document"]["fence"] == first.metadata["document"]["fence"] + 1
    assert claim(w, args) == first
    assert not inspect(w, first).metadata["current"]["preparation_lease_current"]
    with pytest.raises(leases.PreparationError, match="LEASE_NOT_CURRENT"):
        leases.owned_context(w["database"]["preparation_worker"], **old_refs)
    with pytest.raises(leases.PreparationError, match="LEASE_NOT_CURRENT"):
        leases.heartbeat(w["database"]["preparation_worker"], **old_refs, command_id=str(uuid4()))
    assert inspect(w, second).metadata["current"]["preparation_lease_current"]


def test_active_claim_cannot_be_replaced_by_new_nonce(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    record = claim(w, args)
    with pytest.raises(leases.PreparationError, match="ALREADY_OWNED"):
        claim(w, args | {"command_id": str(uuid4())})
    assert inspect(w, record).metadata["current"]["preparation_lease_current"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("preparation_sql_method_digest", "e" * 64),
        ("job_profile_digest", "e" * 64),
        ("worker_login_oid", 1),
        ("database_oid", 1),
        ("database_name", "wrong_database"),
        ("origin", "current_prebid"),
        ("valid_until", datetime(2020, 1, 1, tzinfo=timezone.utc)),
    ],
)
def test_profile_epoch_method_database_or_realm_rejects(wire, monkeypatch, field, value):
    w, _, _ = wire
    changes = {field: value}
    if field == "valid_until":
        changes["valid_from"] = datetime(2019, 1, 1, tzinfo=timezone.utc)
    *_, args = ready(wire, monkeypatch, **changes)
    with pytest.raises(leases.PreparationError, match="CURRENT_STATE_UNAVAILABLE"):
        claim(w, args)


def test_other_purposes_and_other_worker_cannot_read_owned_bytes(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    record = claim(w, args)
    for key in (
        "owner",
        "job_submitter",
        "input_renewer",
        "cost_quoter",
        "verification_program",
        "other_preparation_worker",
    ):
        with pytest.raises(leases.PreparationError):
            claim(w, args, w["database"][key])
        with pytest.raises(leases.PreparationError):
            leases.owned_context(w["database"][key], **refs(record))


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE material_preparation.profile_heads SET enabled=false,revision=revision+1",
        "UPDATE material_judgment_job.profile_heads SET revision=revision+1",
        "UPDATE material_input_renewal.profile_heads SET revision=revision+1",
        "UPDATE material_input_authority.policy_heads SET revision=revision+1",
        "UPDATE design.bid_profiles SET phase='closed'",
    ],
)
def test_revocation_preserves_claim_and_blocks_heartbeat_and_owned_material(
    wire, monkeypatch, mutation
):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    record = claim(w, args)
    w["database"]["owner"].execute(mutation)
    assert (
        inspect(w, record).record == record
        and not inspect(w, record).metadata["current"]["preparation_lease_current"]
    )
    assert claim(w, args) == record
    with pytest.raises(leases.PreparationError, match="LEASE_NOT_CURRENT"):
        leases.heartbeat(
            w["database"]["preparation_worker"], **refs(record), command_id=str(uuid4())
        )
    with pytest.raises(leases.PreparationError, match="LEASE_NOT_CURRENT"):
        leases.owned_context(w["database"]["preparation_worker"], **refs(record))


def test_four_connections_one_native_claim_and_conflicting_references(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)

    def run(_):
        with w["database"]["preparation_worker_factory"]() as c:
            return claim(w, args, c)

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(run, range(4)))
    assert all(record == records[0] for record in records)
    with pytest.raises(leases.PreparationError, match="COMMAND_CONFLICT"):
        claim(w, args | {"expected_profile_digest": "d" * 64})


def test_bad_returned_method_rolls_back_claim_and_mutable_state(wire, monkeypatch):
    w, _, _ = wire
    _, job, args = ready(wire, monkeypatch, preparation_method_digest="e" * 64)
    with pytest.raises(leases.PreparationError, match="NATIVE_RESULT_INVALID"):
        claim(w, args)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_preparation.states WHERE job_id=%s",
            (job.metadata["document"]["job_id"],),
        )
        .fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize(
    "change,restore",
    [
        (
            "GRANT SELECT ON material_preparation.states TO PUBLIC",
            "REVOKE SELECT ON material_preparation.states FROM PUBLIC",
        ),
        (
            "GRANT EXECUTE ON FUNCTION material_preparation.lease_context(uuid,text) TO tender_material_preparation_worker",
            "REVOKE EXECUTE ON FUNCTION material_preparation.lease_context(uuid,text) FROM tender_material_preparation_worker",
        ),
        (
            "ALTER FUNCTION material_judgment_job.current_context(uuid,uuid) SET TimeZone='Asia/Shanghai'",
            "ALTER FUNCTION material_judgment_job.current_context(uuid,uuid) SET TimeZone='UTC'",
        ),
    ],
)
def test_overgrant_or_dependency_method_drift_rejects(wire, monkeypatch, change, restore):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    owner.execute(change)
    try:
        with pytest.raises(leases.PreparationError):
            claim(w, args)
    finally:
        owner.execute(restore)
