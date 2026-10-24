"""Configured native-evidence issuer identity and independent revocation reads."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_native_evidence_registration_pg import (
    ADMIN_DSN,
    api,
    exact,
    pdf_data,
    recovered,
    requirements,
    saved,
    world,
)
from test_native_evidence_registration_pg import database as registration_database
from test_native_evidence_registration_pg import (
    record as register,
)
from test_package_current_original_set_pg import wire
from test_scope_review_issuers_pg import assign

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_native_evidence_issuers as issuer
from packages.model_governance import package_native_material_recovery as recovery
from packages.model_governance import package_native_material_store as store
from packages.model_governance import package_scope_review_issuers as legacy

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_NATIVE_EVIDENCE_ISSUERS_PG") != "1",
    reason="explicit grouped native-evidence issuer verification required",
)
SIGNER = "fusion_native_evidence_issuer"
READER = "fusion_native_evidence_verify"


@pytest.fixture(scope="module")
def database():
    base = registration_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    try:
        names = [SIGNER, READER, issuer.ISSUER_GROUP, issuer.VERIFY_GROUP]
        assert not owner.execute("SELECT FROM pg_roles WHERE rolname=ANY(%s)", (names,)).fetchone()
        owner.execute(issuer.SQL_FILE.read_text(encoding="utf-8"))
        created.extend([issuer.ISSUER_GROUP, issuer.VERIFY_GROUP])
        factories = {}
        for name, group in ((SIGNER, issuer.ISSUER_GROUP), (READER, issuer.VERIFY_GROUP)):
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(name), sql.Literal(password))
            )
            created.append(name)
            owner.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(name))
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=name, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[name] = factory
        with factories[SIGNER]() as signer, factories[READER]() as reader:
            yield value | {
                "native_issuer": signer,
                "native_issuer_reader": reader,
                "native_issuer_factory": factories[SIGNER],
                "native_issuer_reader_factory": factories[READER],
            }
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


def setup(wire, **options):
    w, _, _ = wire
    r = recovered(wire)
    pending = register(w, r, str(uuid4()))
    profile = {"login_name": SIGNER, "store": store.method_digest()} | options.pop(
        "profile_changes", {}
    )
    profile_id, case_id = assign(
        w, pending, r.findings.metadata["review_digest"], profile_changes=profile, **options
    )
    return pending, r, profile_id, case_id


def attest(w, data, command, connection=None):
    pending, recovered, _, case_id = data
    return issuer.attest(
        w["database"]["native_issuer"] if connection is None else connection,
        pending,
        recovered,
        case_id=case_id,
        command_id=command,
        expected_registration_digest=pending.metadata["digest"],
        expected_findings_digest=recovered.findings.metadata["digest"],
        expected_method_digest=issuer.method_digest(),
    )


def reference(data):
    p, r, _, _ = data
    return issuer.reference_for(
        p,
        r,
        expected_registration_digest=p.metadata["digest"],
        expected_findings_digest=r.findings.metadata["digest"],
    )


def read(w, data, command, record=None, connection=None):
    return issuer.read(
        w["database"]["native_issuer_reader"] if connection is None else connection,
        bid_id=data[1].context.metadata["bid_id"],
        command_id=command,
        expected_reference_digest=digest(reference(data)),
        expected_record_digest=None if record is None else record.metadata["digest"],
        expected_method_digest=issuer.method_digest(),
    )


def raw(w, data, command, ref=None):
    return (
        w["database"]["native_issuer"]
        .execute(
            "SELECT scope_review_issuer.attest_native(%s,%s,%s)",
            (data[3], command, Jsonb(reference(data) if ref is None else ref)),
        )
        .fetchone()
    )


def test_configured_native_issuer_exact_registration_report_reopen_and_pending_status(wire):
    w, state, _ = wire
    data = setup(wire)
    command = str(uuid4())
    result = attest(w, data, command)
    doc = result.metadata["document"]
    assert doc["version"] == "package-native-evidence-attestation/2"
    assert doc["recorded_by"] == SIGNER and doc["issuer_origin"] == "synthetic_mechanism"
    assert doc["reference"] == reference(data) and not any("commit" in k for k in doc["reference"])
    assert doc["registration_digest"] == data[0].metadata["digest"]
    assert not any(
        doc[k]
        for k in (
            "necessary_scope_verified",
            "native_binding_verified",
            "input_authority_granted",
            "execution_authorized",
        )
    )
    assert attest(w, data, command).metadata == result.metadata
    with w["database"]["native_issuer_reader_factory"]() as reopened:
        observation = read(w, data, command, connection=reopened)
    assert observation.metadata["record"] == {k: result.metadata[k] for k in ("document", "digest")}
    current = observation.metadata["current"]
    assert (
        current["issuer_active"]
        and current["case_active"]
        and current["configured_issuer_identity_verified"]
    )
    assert current["input_authority_granted"] is False and state["attempts"] == 4
    directory = os.environ.get("FUSION_NATIVE_EVIDENCE_ISSUERS_EVIDENCE")
    if directory:
        (Path(directory) / "native-evidence-issuers-proof.json").write_text(
            json.dumps(
                {
                    "issuer_method_digest": issuer.method_digest(),
                    "record": result.metadata,
                    "observation": observation.metadata,
                    "actual_loopback_gets": 4,
                    "independent_issuer_and_reader_logins": True,
                    "exact_native_registration_store_report_and_review_bound": True,
                    "unknown_result_lookup_after_reader_reopen": True,
                    "same_command_same_immutable_fact": True,
                    "old_cas_commit_fields_fabricated": False,
                    "synthetic_material_and_issuer_configuration": True,
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
        "issuer",
        "issuer_reader",
        "native_issuer_reader",
        "native_registrar",
        "material_writer",
        "material_reader",
        "scope_verifier",
    ],
)
def test_other_purposes_cannot_sign_native_evidence(wire, role):
    w, _, _ = wire
    data = setup(wire)
    with pytest.raises(issuer.NativeEvidenceIssuerError):
        attest(w, data, str(uuid4()), connection=w["database"][role])


def test_signer_cannot_read_own_attestation_or_directly_read_private_tables(wire):
    w, _, _ = wire
    data = setup(wire)
    command = str(uuid4())
    attest(w, data, command)
    with pytest.raises(issuer.NativeEvidenceIssuerError):
        read(w, data, command, connection=w["database"]["native_issuer"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        w["database"]["native_issuer"].execute("SELECT * FROM scope_review_issuer.profiles")
    for role in ("native_issuer", "native_issuer_reader"):
        row = (
            w["database"][role]
            .execute(
                "SELECT has_schema_privilege(session_user,'technical_material_store','USAGE') OR has_schema_privilege(session_user,'material_registration','USAGE') AS excess"
            )
            .fetchone()
        )
        assert row["excess"] is False


@pytest.mark.parametrize(
    "change",
    [
        "disabled_profile",
        "disabled_case",
        "expired_profile",
        "wrong_database",
        "wrong_store_method",
        "wrong_review",
    ],
)
def test_unconfigured_expired_or_mismatched_authority_cannot_sign(wire, change):
    w, _, _ = wire
    now = w["database"]["owner"].execute("SELECT clock_timestamp() AS t").fetchone()["t"]
    options = {}
    if change == "disabled_profile":
        options["profile_enabled"] = False
    elif change == "disabled_case":
        options["case_enabled"] = False
    elif change == "expired_profile":
        options["profile_changes"] = {
            "start": now - timedelta(hours=2),
            "end": now - timedelta(hours=1),
        }
    elif change == "wrong_database":
        options["profile_changes"] = {"database_name": "wrong_synthetic_database"}
    elif change == "wrong_store_method":
        options["profile_changes"] = {"store": "a" * 64}
    else:
        options["case_changes"] = {"review": "a" * 64}
    data = setup(wire, **options)
    with pytest.raises(issuer.NativeEvidenceIssuerError):
        attest(w, data, str(uuid4()))


@pytest.mark.parametrize(
    "field",
    [
        "storage_record_id",
        "storage_record_digest",
        "findings_digest",
        "registration_digest",
        "review_digest",
        "native_store_method_digest",
    ],
)
def test_sql_checks_native_storage_registration_and_full_report_roots(wire, field):
    w, _, _ = wire
    data = setup(wire)
    ref = reference(data)
    ref[field] = str(uuid4()) if field.endswith("_id") else "a" * 64
    with pytest.raises(
        psycopg.errors.RaiseException, match="NATIVE_EVIDENCE_ISSUER_CASE_REFERENCE_MISMATCH"
    ):
        raw(w, data, str(uuid4()), ref)


def test_revocation_reactivation_and_profile_replacement_preserve_old_fact(wire):
    w, _, _ = wire
    data = setup(wire)
    command = str(uuid4())
    result = attest(w, data, command)
    owner = w["database"]["owner"]
    for enabled, revision in ((False, 2), (True, 3)):
        owner.execute(
            "UPDATE scope_review_issuer.profile_heads SET enabled=%s,revision=%s WHERE login_name=%s",
            (enabled, revision, SIGNER),
        )
        observation = read(w, data, command, result)
        assert observation.metadata["record"]["digest"] == result.metadata["digest"]
        assert observation.metadata["current"]["issuer_active"] is enabled
        assert observation.metadata["current"]["profile_head_revision"] == revision
        assert attest(w, data, command).metadata == result.metadata
        if not enabled:
            with pytest.raises(issuer.NativeEvidenceIssuerError, match="PROFILE_UNAVAILABLE"):
                attest(w, data, str(uuid4()))
    assign(
        w,
        data[0],
        data[1].findings.metadata["review_digest"],
        profile_changes={"login_name": SIGNER, "store": store.method_digest()},
    )
    observation = read(w, data, command, result)
    assert observation.metadata["current"]["issuer_active"] is False
    assert observation.metadata["record"]["digest"] == result.metadata["digest"]
    assert attest(w, data, command).metadata == result.metadata


def test_case_revocation_does_not_change_immutable_attestation(wire):
    w, _, _ = wire
    data = setup(wire)
    command = str(uuid4())
    result = attest(w, data, command)
    w["database"]["owner"].execute(
        "UPDATE scope_review_issuer.case_heads SET enabled=false,revision=revision+1 WHERE case_id=%s",
        (data[3],),
    )
    observed = read(w, data, command, result)
    assert (
        observed.metadata["current"]["case_active"] is False
        and observed.metadata["current"]["case_head_revision"] == 2
    )
    assert attest(w, data, command).metadata == result.metadata
    with pytest.raises(issuer.NativeEvidenceIssuerError, match="CASE_UNAVAILABLE"):
        attest(w, data, str(uuid4()))


def test_same_command_four_actual_connections_returns_one_fact(wire):
    w, _, _ = wire
    data = setup(wire)
    command = str(uuid4())

    def run(_):
        with w["database"]["native_issuer_factory"]() as c:
            return attest(w, data, command, c).metadata

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, range(4)))
    assert all(row == rows[0] for row in rows)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM scope_review_issuer.attestations WHERE command_id=%s",
            (command,),
        )
        .fetchone()["n"]
        == 1
    )


def test_new_current_recovery_observation_does_not_rewrite_registration(wire):
    w, _, _ = wire
    data = setup(wire)
    p, r, profile, case = data
    d = r.stored_record.metadata["document"]
    refreshed = asyncio.run(
        recovery.restore(
            w["database"]["material_reader"],
            *(w["database"][k] for k in ("scope_verifier", "original_verifier", "parse_verifier")),
            store_command_id=d["command_id"],
            expected_packet_digest=d["packet_digest"],
            expected_storage_record_digest=r.stored_record.metadata["digest"],
            expected_context_digest=r.context.metadata["digest"],
            expected_method_digest=recovery.method_digest(),
            bid_id=r.context.metadata["bid_id"],
            scope_id=r.context.metadata["scope_id"],
            expected_scope_digest=r.context.metadata["scope_digest"],
            profile="development_s3",
            url_for_locator=wire[2],
        )
    )
    assert refreshed.metadata["digest"] != r.metadata["digest"]
    assert reference((p, refreshed, profile, case)) == reference(data)
    before = canonical(p.metadata)
    attest(w, (p, refreshed, profile, case), str(uuid4()))
    assert canonical(p.metadata) == before


def test_public_privilege_drift_is_rejected_by_native_policy(wire):
    w, _, _ = wire
    data = setup(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT SELECT ON scope_review_issuer.attestations TO PUBLIC")
    try:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege, match="INDEPENDENT_LOGIN_REQUIRED"
        ):
            raw(w, data, str(uuid4()))
    finally:
        owner.execute("REVOKE SELECT ON scope_review_issuer.attestations FROM PUBLIC")


def test_invalid_result_rolls_back_attestation(wire, monkeypatch):
    w, _, _ = wire
    data = setup(wire)
    command = str(uuid4())

    def invalid(value):
        raise issuer.NativeEvidenceIssuerError("synthetic invalid result")

    monkeypatch.setattr(issuer, "_record", invalid)
    with pytest.raises(issuer.NativeEvidenceIssuerError, match="synthetic invalid result"):
        attest(w, data, command)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM scope_review_issuer.attestations WHERE command_id=%s",
            (command,),
        )
        .fetchone()["n"]
        == 0
    )


def test_new_native_fact_is_rejected_by_legacy_codec_and_cross_registration(wire):
    w, _, _ = wire
    data = setup(wire)
    result = attest(w, data, str(uuid4()))
    value = {k: result.metadata[k] for k in ("document", "digest")}
    with pytest.raises(legacy.ScopeIssuerError):
        legacy._record(value)
    wrong = deepcopy(value)
    wrong["document"]["reference"]["registration_id"] = str(uuid4())
    wrong["digest"] = digest(wrong["document"])
    with pytest.raises(issuer.NativeEvidenceIssuerError, match="NATIVE_RESULT_INVALID"):
        issuer._record(wrong)


def test_native_issuer_function_owner_drift_rejects_without_repair(wire):
    w, _, _ = wire
    data = setup(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT CREATE ON SCHEMA scope_review_issuer TO tender_api")
    owner.execute(
        "ALTER FUNCTION scope_review_issuer.read_native(uuid,uuid,text) OWNER TO tender_api"
    )
    owner.execute("REVOKE CREATE ON SCHEMA scope_review_issuer FROM tender_api")
    try:
        with pytest.raises(issuer.NativeEvidenceIssuerError, match="NATIVE_METHOD_MISMATCH"):
            attest(w, data, str(uuid4()))
    finally:
        owner.execute(
            sql.SQL(
                "ALTER FUNCTION scope_review_issuer.read_native(uuid,uuid,text) OWNER TO {}"
            ).format(sql.Identifier(owner.info.user))
        )
