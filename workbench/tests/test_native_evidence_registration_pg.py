"""Native stored evidence/recovery roots registered through a separate LOGIN."""
# ruff: noqa: F401,F811

import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_native_material_recovery_pg import artifact, restore
from test_native_material_store_pg import (
    ADMIN_DSN,
    api,
    exact,
    pdf_data,
    requirements,
    saved,
    world,
)
from test_native_material_store_pg import database as store_database
from test_package_current_original_set_pg import wire
from test_scope_review_issuers_pg import assign

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_registration as legacy
from packages.model_governance import package_native_evidence_registration as registration

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_NATIVE_EVIDENCE_REGISTRATION_PG") != "1",
    reason="explicit grouped v2 native evidence registration required",
)
LOGIN = "fusion_native_evidence_registration"


@pytest.fixture(scope="module")
def database():
    base = store_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    try:
        assert not owner.execute(
            "SELECT FROM pg_roles WHERE rolname=ANY(%s)", ([LOGIN, registration.GROUP],)
        ).fetchone()
        owner.execute(registration.SQL_FILE.read_text(encoding="utf-8"))
        created.append(registration.GROUP)
        password = secrets.token_urlsafe(36)
        owner.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(LOGIN), sql.Literal(password))
        )
        created.append(LOGIN)
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(registration.GROUP), sql.Identifier(LOGIN)
            )
        )
        dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=LOGIN, password=password)

        def factory():
            return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

        with factory() as c:
            yield value | {"native_registrar": c, "native_registrar_factory": factory}
    finally:
        if owner.info.transaction_status != TransactionStatus.IDLE:
            owner.rollback()
        try:
            next(base)
        except StopIteration:
            pass
        finally:
            with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
                for name in reversed(created):
                    admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def recovered(wire):
    a = artifact(wire)
    return restore(wire, a)


def record(w, r, command, connection=None):
    return registration.record(
        w["database"]["native_registrar"] if connection is None else connection,
        r,
        command_id=command,
        expected_context_digest=r.context.metadata["digest"],
        expected_storage_record_digest=r.stored_record.metadata["digest"],
        expected_recovery_observation_digest=r.metadata["digest"],
        expected_method_digest=registration.method_digest(),
    )


def packet_for(r):
    return registration.packet_for(
        r,
        expected_context_digest=r.context.metadata["digest"],
        expected_storage_record_digest=r.stored_record.metadata["digest"],
        expected_recovery_observation_digest=r.metadata["digest"],
    )


def read(w, r, command, expected=None, connection=None):
    return registration.read(
        w["database"]["native_registrar"] if connection is None else connection,
        bid_id=r.context.metadata["bid_id"],
        command_id=command,
        expected_packet_digest=digest(packet_for(r)),
        expected_method_digest=registration.method_digest(),
        expected_record_digest=expected,
    )


def raw_record(w, r, command, *, packet=None, observation=None):
    m = r.context.metadata
    return (
        w["database"]["native_registrar"]
        .execute(
            "SELECT material_registration.record_native(%s,%s,%s,%s,%s,%s)",
            (
                m["bid_id"],
                m["scope_id"],
                m["scope_digest"],
                command,
                Jsonb(packet_for(r) if packet is None else packet),
                Jsonb(r.metadata if observation is None else observation),
            ),
        )
        .fetchone()
    )


def test_actual_v2_roots_native_record_reopen_and_legacy_case_fk(wire):
    w, state, url = wire
    r = recovered(wire)
    command = str(uuid4())
    before = canonical(r.context.metadata)
    result = record(w, r, command)
    d = result.metadata["document"]
    assert d["version"] == "package-native-material-registration/2" and d["recorded_by"] == LOGIN
    assert d["packet"] == packet_for(r) and d["recovery_observation"] == r.metadata
    assert not any("commit" in k for k in d["packet"]) and not any(
        d[k] for k in registration.FALSE_FIELDS
    )
    assert record(w, r, command).metadata == result.metadata
    with w["database"]["native_registrar_factory"]() as reopened:
        again = read(w, r, command, connection=reopened)
    assert again.metadata == result.metadata
    _, case_id = assign(w, result, r.findings.review_packet.metadata["digest"])
    case = (
        w["database"]["owner"]
        .execute(
            "SELECT registration_id::text,registration_digest::text FROM scope_review_issuer.cases WHERE id=%s",
            (case_id,),
        )
        .fetchone()
    )
    assert (
        case["registration_id"] == d["registration_id"]
        and case["registration_digest"] == result.metadata["digest"]
    )
    assert canonical(r.context.metadata) == before and state["attempts"] == 4
    directory = os.environ.get("FUSION_NATIVE_EVIDENCE_REGISTRATION_EVIDENCE")
    if directory:
        (Path(directory) / "native-evidence-registration-proof.json").write_text(
            json.dumps(
                {
                    "registration_method_digest": registration.method_digest(),
                    "record": result.metadata,
                    "actual_loopback_gets": 4,
                    "native_storage_and_current_recovery_roots_bound": True,
                    "old_cas_commit_fields_fabricated": False,
                    "unknown_result_lookup_by_command": True,
                    "same_command_replay_same_record": True,
                    "reader_closed_and_reopened": True,
                    "legacy_case_registration_fk_accepts_v2_identity": True,
                    "legacy_methods_and_records_not_rewritten": True,
                    "context_bytes_preserved": True,
                    "synthetic_material_and_claims": True,
                    "actual_human_review": False,
                    "input_authority_granted": False,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "role",
    [
        "owner",
        "registration_verifier",
        "material_writer",
        "material_reader",
        "scope_verifier",
        "original_verifier",
        "parse_verifier",
        "issuer",
        "issuer_reader",
    ],
)
def test_only_dedicated_v2_purpose_can_register_native_roots(wire, role):
    w, _, _ = wire
    r = recovered(wire)
    with pytest.raises(registration.NativeEvidenceRegistrationError):
        record(w, r, str(uuid4()), connection=w["database"][role])


def test_new_purpose_has_no_tables_or_other_schema_usage(saved):
    c = saved["database"]["native_registrar"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("SELECT * FROM material_registration.records")
    for schema in ("technical_material_store", "scope_review_issuer"):
        assert (
            c.execute(
                "SELECT has_schema_privilege(%s,%s) AS allowed", (schema, "USAGE")
            ).fetchone()["allowed"]
            is False
        )


@pytest.mark.parametrize(
    "mutation", ["storage", "old_commit", "qualification", "incomplete_as_confirmed"]
)
def test_raw_sql_cannot_replace_storage_or_self_qualify(wire, mutation):
    w, _, _ = wire
    r = recovered(wire)
    p = packet_for(r)
    obs = deepcopy(r.metadata)
    if mutation == "storage":
        p["storage_record_digest"] = "e" * 64
        obs["storage_record_digest"] = "e" * 64
    elif mutation == "old_commit":
        p["recovery_commit_digest"] = "e" * 64
    elif mutation == "qualification":
        obs["input_authority_granted"] = True
    else:
        obs["all_findings_claimed_confirmed"] = not obs["all_findings_claimed_confirmed"]
    obs["digest"] = digest({k: v for k, v in obs.items() if k != "digest"})
    p["native_recovery_observation_digest"] = obs["digest"]
    with pytest.raises(psycopg.Error, match="NATIVE_REGISTRATION_"):
        raw_record(w, r, str(uuid4()), packet=p, observation=obs)


def test_four_concurrent_same_command_only_one_v2_record(wire):
    w, _, _ = wire
    r = recovered(wire)
    command = str(uuid4())

    def writing(index):
        with w["database"]["native_registrar_factory"]() as c:
            return record(w, r, command, connection=c).metadata

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(writing, range(4)))
    assert all(d == results[0] for d in results)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_registration.records WHERE command_id=%s",
            (command,),
        )
        .fetchone()["n"]
        == 1
    )


def test_invalid_native_result_rolls_back_v2_registration(wire, monkeypatch):
    w, _, _ = wire
    r = recovered(wire)
    command = str(uuid4())

    def invalid(value):
        raise registration.NativeEvidenceRegistrationError("synthetic record fault")

    monkeypatch.setattr(registration, "_record", invalid)
    with pytest.raises(
        registration.NativeEvidenceRegistrationError, match="synthetic record fault"
    ):
        record(w, r, command)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_registration.records WHERE command_id=%s",
            (command,),
        )
        .fetchone()["n"]
        == 0
    )


def test_v1_codec_does_not_interpret_v2_record_as_file_commit_protocol(wire):
    w, _, _ = wire
    r = recovered(wire)
    result = record(w, r, str(uuid4()))
    with pytest.raises(legacy.MaterialRegistrationError):
        legacy._validate_record(
            {k: result.metadata[k] for k in ("document", "digest")},
            bid_id=r.context.metadata["bid_id"],
        )


def test_v1_and_v2_share_command_conflicts_without_rewriting_v1(wire, tmp_path):
    from test_package_material_registration_pg import staged, write

    w, _, _ = wire
    r = recovered(wire)
    root, key, old_command = staged(w, tmp_path)
    old = write(w, root, key)
    with pytest.raises(registration.NativeEvidenceRegistrationError, match="COMMAND_CONFLICT"):
        record(w, r, old_command["command_id"])
    unchanged = legacy.read(
        w["database"]["registration_verifier"],
        bid_id=r.context.metadata["bid_id"],
        command_id=old_command["command_id"],
        expected_packet_digest=digest(old_command["packet"]),
        expected_record_digest=old.metadata["digest"],
        expected_method_digest=legacy.method_digest(),
    )
    assert unchanged.metadata == old.metadata


def test_closed_after_observation_keeps_pending_fact_without_current_qualification(wire):
    w, _, _ = wire
    r = recovered(wire)
    w["database"]["owner"].execute(
        "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
        (r.context.metadata["bid_id"],),
    )
    result = record(w, r, str(uuid4()))
    assert result.metadata["document"]["status"] == "awaiting_independent_verification"
    assert not any(result.metadata["document"][k] for k in registration.FALSE_FIELDS)


def test_native_role_policy_rejects_public_overgrant_without_python(wire):
    w, _, _ = wire
    r = recovered(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT SELECT ON material_registration.records TO PUBLIC")
    try:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege,
            match="NATIVE_REGISTRATION_INDEPENDENT_LOGIN_REQUIRED",
        ):
            raw_record(w, r, str(uuid4()))
    finally:
        owner.execute("REVOKE SELECT ON material_registration.records FROM PUBLIC")


def test_native_function_owner_drift_rejects_without_repair(wire):
    w, _, _ = wire
    r = recovered(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT CREATE ON SCHEMA material_registration TO tender_api")
    owner.execute(
        "ALTER FUNCTION material_registration.read_native(uuid,uuid,text) OWNER TO tender_api"
    )
    owner.execute("REVOKE CREATE ON SCHEMA material_registration FROM tender_api")
    try:
        with pytest.raises(
            registration.NativeEvidenceRegistrationError, match="NATIVE_METHOD_MISMATCH"
        ):
            record(w, r, str(uuid4()))
    finally:
        owner.execute(
            sql.SQL(
                "ALTER FUNCTION material_registration.read_native(uuid,uuid,text) OWNER TO {}"
            ).format(sql.Identifier(owner.info.user))
        )


def test_native_recovery_observation_cannot_name_another_store_command(wire):
    w, _, _ = wire
    r = recovered(wire)
    observation = deepcopy(r.metadata)
    observation["store_command_id"] = str(uuid4())
    observation["digest"] = digest({k: v for k, v in observation.items() if k != "digest"})
    packet = packet_for(r)
    packet["native_recovery_observation_digest"] = observation["digest"]
    with pytest.raises(psycopg.errors.RaiseException, match="NATIVE_REGISTRATION_STORAGE_MISMATCH"):
        raw_record(w, r, str(uuid4()), packet=packet, observation=observation)
