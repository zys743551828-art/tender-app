"""Configured synthetic issuers and independent readers in the dedicated check DB."""
# ruff: noqa: F401,F811

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
from test_package_current_material_pg import (
    ADMIN_DSN,
    api,
    exact,
    pdf_data,
    requirements,
    saved,
    world,
)
from test_package_current_original_set_pg import wire
from test_package_material_recovery_pg import restore
from test_package_material_recovery_pg import setup as recovery_setup
from test_package_material_registration_pg import database as registration_database
from test_package_material_registration_pg import staged as staged_registration
from test_package_material_registration_pg import write as write_registration
from test_package_material_scope_findings import checked, draft_for

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_registration as registration
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_scope_findings_store as findings_store
from packages.model_governance import package_scope_review_issuers as issuers
from packages.storage.private_cas import PrivateContentStore

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_SCOPE_REVIEW_ISSUERS_PG") != "1",
    reason="explicit grouped synthetic issuer checks required",
)
SIGNER = "fusion_scope_review_issuer"
READER = "fusion_scope_review_verify"


@pytest.fixture(scope="module")
def database():
    base = registration_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    try:
        names = [SIGNER, READER, issuers.ISSUER_GROUP, issuers.VERIFY_GROUP]
        assert not owner.execute("SELECT FROM pg_roles WHERE rolname=ANY(%s)", (names,)).fetchone()
        owner.execute(issuers.SQL_FILE.read_text(encoding="utf-8"))
        created.extend([issuers.ISSUER_GROUP, issuers.VERIFY_GROUP])
        factories = {}
        for name, group in ((SIGNER, issuers.ISSUER_GROUP), (READER, issuers.VERIFY_GROUP)):
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
                "issuer": signer,
                "issuer_reader": reader,
                "issuer_factory": factories[SIGNER],
                "reader_factory": factories[READER],
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


def assign(
    w,
    pending,
    review_digest,
    *,
    profile_changes=None,
    case_changes=None,
    profile_enabled=True,
    case_enabled=True,
):
    owner = w["database"]["owner"]
    native = owner.execute(
        "SELECT clock_timestamp() AS at,(SELECT oid FROM pg_database WHERE datname=current_database()) AS database_oid"
    ).fetchone()
    at = native["at"]
    profile_id = str(uuid4())
    case_id = str(uuid4())
    d = pending.metadata["document"]
    p = {
        "login_name": SIGNER,
        "subject_id": str(uuid4()),
        "issuer_kind": "human",
        "origin": "synthetic_mechanism",
        "policy": digest("synthetic reviewer authorization policy"),
        "findings": findings.method_digest(),
        "store": findings_store.method_digest(),
        "database_oid": native["database_oid"],
        "database_name": owner.info.dbname,
        "start": at - timedelta(minutes=1),
        "end": at + timedelta(hours=1),
    } | (profile_changes or {})
    owner.execute(
        "INSERT INTO scope_review_issuer.profiles(id,login_name,subject_id,issuer_kind,origin,authority_policy_digest,findings_method_digest,store_method_digest,database_oid,database_name,valid_from,valid_until) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            profile_id,
            p["login_name"],
            p["subject_id"],
            p["issuer_kind"],
            p["origin"],
            p["policy"],
            p["findings"],
            p["store"],
            p["database_oid"],
            p["database_name"],
            p["start"],
            p["end"],
        ),
    )
    owner.execute(
        "INSERT INTO scope_review_issuer.profile_heads(login_name,profile_id,revision,enabled) VALUES(%s,%s,1,%s) ON CONFLICT(login_name) DO UPDATE SET profile_id=EXCLUDED.profile_id,revision=scope_review_issuer.profile_heads.revision+1,enabled=EXCLUDED.enabled",
        (p["login_name"], profile_id, profile_enabled),
    )
    c = {
        "context": d["packet"]["context_digest"],
        "review": review_digest,
        "registration_id": d["registration_id"],
        "registration_digest": pending.metadata["digest"],
        "start": at - timedelta(minutes=1),
        "end": at + timedelta(hours=1),
    } | (case_changes or {})
    owner.execute(
        "INSERT INTO scope_review_issuer.cases(id,profile_id,registration_id,registration_digest,context_digest,review_digest,valid_from,valid_until) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            case_id,
            profile_id,
            c["registration_id"],
            c["registration_digest"],
            c["context"],
            c["review"],
            c["start"],
            c["end"],
        ),
    )
    owner.execute(
        "INSERT INTO scope_review_issuer.case_heads(case_id,revision,enabled) VALUES(%s,1,%s)",
        (case_id, case_enabled),
    )
    return profile_id, case_id


def reference_only(w, tmp_path, **changes):
    # Tests of native credential/case boundaries, without an assertion of content review.
    root, key, registration_command = staged_registration(w, tmp_path)
    pending = write_registration(w, root, key)
    ref = {
        "version": "package-scope-review-attestation-reference/1",
        "context_digest": registration_command["packet"]["context_digest"],
        "review_digest": "b" * 64,
        "findings_digest": "c" * 64,
        "findings_commit_digest": "d" * 64,
        "findings_method_digest": findings.method_digest(),
        "findings_store_method_digest": findings_store.method_digest(),
    }
    profile_id, case_id = assign(w, pending, ref["review_digest"], **changes)
    command = {
        "version": "package-scope-review-attestation-command/1",
        "method_digest": issuers.method_digest(),
        "case_id": case_id,
        "command_id": str(uuid4()),
        "bid_id": registration_command["bid_id"],
        "scope_id": registration_command["scope_id"],
        "reference": ref,
    }
    with PrivateContentStore(root) as store:
        command_key = store.publish(canonical(command))
    return root, command_key, command, profile_id


def attest(w, root, key, connection=None):
    with PrivateContentStore(root) as store:
        return issuers.attest(
            w["database"]["issuer"] if connection is None else connection,
            store,
            command_commit_digest=key,
            expected_method_digest=issuers.method_digest(),
        )


def read(w, command, **changes):
    args = {
        "bid_id": command["bid_id"],
        "command_id": command["command_id"],
        "expected_reference_digest": digest(command["reference"]),
        "expected_method_digest": issuers.method_digest(),
    } | changes
    return issuers.read(w["database"]["issuer_reader"], **args)


def test_actual_native_material_private_findings_and_configured_issuer_identity(wire, tmp_path):
    w, state, url = wire
    root, recovery_key, bundle = recovery_setup(wire, tmp_path)
    recovered = restore(root, recovery_key, bundle, wire)
    with PrivateContentStore(root) as store:
        pending_key = registration.stage_command(
            store,
            recovered,
            command_id=str(uuid4()),
            expected_context_digest=bundle.context.metadata["digest"],
            expected_recovery_commit_digest=recovery_key,
            expected_method_digest=registration.method_digest(),
        )
        pending = registration.record(
            w["database"]["registration_verifier"],
            store,
            command_commit_digest=pending_key,
            expected_method_digest=registration.method_digest(),
        )
        packet = review.build(
            recovered.context,
            expected_context_digest=bundle.context.metadata["digest"],
            expected_method_digest=review.method_digest(),
        )
        report = checked(packet, draft_for(packet))
        sealed = findings_store.save(
            store,
            report,
            expected_findings_digest=report.metadata["digest"],
            expected_method_digest=findings_store.method_digest(),
        )
        profile_id, case_id = assign(w, pending, packet.metadata["digest"])
        key = issuers.stage_command(
            store,
            packet,
            case_id=case_id,
            command_id=str(uuid4()),
            findings_commit_digest=sealed,
            expected_findings_digest=report.metadata["digest"],
            expected_method_digest=issuers.method_digest(),
        )
        command = issuers._command(store, key)
    w["database"]["issuer"].execute("SET TIME ZONE 'Asia/Shanghai'")
    w["database"]["issuer_reader"].execute("SET TIME ZONE 'America/New_York'")
    record = attest(w, root, key)
    observed = read(w, command, expected_record_digest=record.metadata["digest"])
    assert observed.metadata["record"] == {k: record.metadata[k] for k in ("document", "digest")}
    assert observed.metadata["current"]["configured_issuer_identity_verified"] is True
    assert (
        observed.metadata["current"]["issuer_active"]
        and observed.metadata["current"]["case_active"]
    )
    assert (
        record.metadata["document"]["profile_id"] == profile_id
        and record.metadata["document"]["recorded_by"] == SIGNER
    )
    assert record.metadata["document"]["issuer_origin"] == "synthetic_mechanism"
    assert (
        record.metadata["document"]["input_authority_granted"] is False and state["attempts"] == 4
    )
    with w["database"]["reader_factory"]() as reopened:
        recovered_record = issuers.read(
            reopened,
            bid_id=command["bid_id"],
            command_id=command["command_id"],
            expected_reference_digest=digest(command["reference"]),
            expected_method_digest=issuers.method_digest(),
        )
    assert recovered_record.metadata["record"] == observed.metadata["record"]
    assert attest(w, root, key).metadata == record.metadata
    directory = os.environ.get("FUSION_SCOPE_REVIEW_ISSUERS_EVIDENCE")
    if directory:
        (Path(directory) / "scope-review-issuers-native-proof.json").write_text(
            json.dumps(
                {
                    "issuer_method_digest": issuers.method_digest(),
                    "command_commit_digest": key,
                    "record": record.metadata,
                    "observation": observed.metadata,
                    "actual_loopback_gets": 4,
                    "independent_issuer_and_reader_logins": True,
                    "durable_command_replay_same_record": True,
                    "lost_result_lookup_by_command": True,
                    "session_timezones_differ": True,
                    "synthetic_review_claims": True,
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
    "mutation",
    [
        "profile_disabled",
        "case_disabled",
        "profile_expired",
        "case_expired",
        "database",
        "method",
        "context",
        "review",
    ],
)
def test_unconfigured_expired_or_wrong_case_cannot_attest(saved, tmp_path, mutation):
    owner = saved["database"]["owner"]
    now = owner.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
    changes = {}
    if mutation == "profile_disabled":
        changes["profile_enabled"] = False
    elif mutation == "case_disabled":
        changes["case_enabled"] = False
    elif mutation == "profile_expired":
        changes["profile_changes"] = {
            "start": now - timedelta(hours=2),
            "end": now - timedelta(hours=1),
        }
    elif mutation == "case_expired":
        changes["case_changes"] = {
            "start": now - timedelta(hours=2),
            "end": now - timedelta(hours=1),
        }
    elif mutation == "database":
        changes["profile_changes"] = {"database_name": "not_this_database"}
    elif mutation == "method":
        changes["profile_changes"] = {"findings": "a" * 64}
    elif mutation == "context":
        changes["case_changes"] = {"context": "e" * 64}
    elif mutation == "review":
        changes["case_changes"] = {"review": "e" * 64}
    root, key, command, profile = reference_only(saved, tmp_path, **changes)
    with pytest.raises(issuers.ScopeIssuerError):
        attest(saved, root, key)
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM scope_review_issuer.attestations WHERE command_id=%s",
            (command["command_id"],),
        ).fetchone()["n"]
        == 0
    )


def test_revocation_changes_current_state_without_rewriting_old_record(saved, tmp_path):
    w = saved
    root, key, command, profile = reference_only(w, tmp_path)
    record = attest(w, root, key)
    w["database"]["owner"].execute(
        "UPDATE scope_review_issuer.profile_heads SET enabled=false,revision=revision+1 WHERE login_name=%s",
        (SIGNER,),
    )
    observed = read(w, command)
    assert (
        observed.metadata["record"]["digest"] == record.metadata["digest"]
        and observed.metadata["current"]["issuer_active"] is False
    )
    assert attest(w, root, key).metadata == record.metadata
    changed = deepcopy(command)
    changed["command_id"] = str(uuid4())
    with PrivateContentStore(root) as store:
        other = store.publish(canonical(changed))
    with pytest.raises(issuers.ScopeIssuerError, match="PROFILE_UNAVAILABLE"):
        attest(w, root, other)


@pytest.mark.parametrize(
    "role",
    [
        "owner",
        "registration_verifier",
        "scope_verifier",
        "original_verifier",
        "parse_verifier",
        "issuer_reader",
    ],
)
def test_issuer_is_a_separate_purpose(saved, tmp_path, role):
    root, key, command, profile = reference_only(saved, tmp_path)
    with pytest.raises(issuers.ScopeIssuerError):
        attest(saved, root, key, connection=saved["database"][role])


def test_issuer_cannot_verify_itself_and_reader_cannot_issue(saved, tmp_path):
    w = saved
    root, key, command, profile = reference_only(w, tmp_path)
    attest(w, root, key)
    with pytest.raises(issuers.ScopeIssuerError):
        issuers.read(
            w["database"]["issuer"],
            bid_id=command["bid_id"],
            command_id=command["command_id"],
            expected_reference_digest=digest(command["reference"]),
            expected_method_digest=issuers.method_digest(),
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        w["database"]["issuer_reader"].execute(
            "SELECT scope_review_issuer.attest(%s,%s,%s)",
            (command["case_id"], str(uuid4()), Jsonb(command["reference"])),
        )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM scope_review_issuer.profiles",
        "SELECT * FROM scope_review_issuer.cases",
        "SELECT * FROM scope_review_issuer.attestations",
        "SELECT * FROM design.outcomes",
        "SELECT scope_review_issuer.role_policy(current_user,'tender_scope_review_issuer',ARRAY['scope_review_issuer.attest(uuid,uuid,jsonb)'])",
    ],
)
def test_no_direct_tables_labels_or_private_policy_helper(saved, query):
    for role in ("issuer", "issuer_reader"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            saved["database"][role].execute(query)


def test_native_policy_rejects_public_overgrant_even_without_python_port(saved, tmp_path):
    w = saved
    root, key, command, profile = reference_only(w, tmp_path)
    owner = w["database"]["owner"]
    owner.execute("GRANT SELECT ON scope_review_issuer.profiles TO PUBLIC")
    try:
        with pytest.raises(psycopg.Error, match="SCOPE_ISSUER_INDEPENDENT_LOGIN_REQUIRED"):
            w["database"]["issuer"].execute(
                "SELECT scope_review_issuer.attest(%s,%s,%s)",
                (command["case_id"], command["command_id"], Jsonb(command["reference"])),
            )
    finally:
        owner.execute("REVOKE SELECT ON scope_review_issuer.profiles FROM PUBLIC")


def test_changed_role_membership_invalidates_current_authority(saved, tmp_path):
    w = saved
    root, key, command, profile = reference_only(w, tmp_path)
    record = attest(w, root, key)
    owner = w["database"]["owner"]
    owner.execute(sql.SQL("GRANT tender_api TO {}").format(sql.Identifier(SIGNER)))
    try:
        observed = read(w, command)
        assert (
            observed.metadata["record"]["digest"] == record.metadata["digest"]
            and not observed.metadata["current"]["issuer_active"]
        )
    finally:
        owner.execute(sql.SQL("REVOKE tender_api FROM {}").format(sql.Identifier(SIGNER)))


def test_native_method_ownership_drift_is_rejected_without_runtime_repair(saved, tmp_path):
    w = saved
    root, key, command, profile = reference_only(w, tmp_path)
    owner = w["database"]["owner"]
    owner.execute("GRANT CREATE ON SCHEMA scope_review_issuer TO tender_api")
    owner.execute("ALTER FUNCTION scope_review_issuer.read(uuid,uuid,text) OWNER TO tender_api")
    owner.execute("REVOKE CREATE ON SCHEMA scope_review_issuer FROM tender_api")
    try:
        with pytest.raises(issuers.ScopeIssuerError, match="NATIVE_METHOD_MISMATCH"):
            attest(w, root, key)
    finally:
        owner.execute(
            sql.SQL("ALTER FUNCTION scope_review_issuer.read(uuid,uuid,text) OWNER TO {}").format(
                sql.Identifier(owner.info.user)
            )
        )


def test_concurrent_same_command_has_one_issuer_record(saved, tmp_path):
    w = saved
    root, key, command, profile = reference_only(w, tmp_path)

    def attempt(index):
        with w["database"]["issuer_factory"]() as c:
            return attest(w, root, key, connection=c).metadata

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert all(r == results[0] for r in results)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM scope_review_issuer.attestations WHERE command_id=%s",
            (command["command_id"],),
        )
        .fetchone()["n"]
        == 1
    )


def test_invalid_native_result_rolls_back_new_attestation(saved, tmp_path, monkeypatch):
    w = saved
    root, key, command, profile = reference_only(w, tmp_path)

    def invalid(value):
        raise issuers.ScopeIssuerError("synthetic record fault")

    monkeypatch.setattr(issuers, "_record", invalid)
    with pytest.raises(issuers.ScopeIssuerError, match="synthetic record fault"):
        attest(w, root, key)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM scope_review_issuer.attestations WHERE command_id=%s",
            (command["command_id"],),
        )
        .fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize(
    "field", ["bid_id", "command_id", "expected_reference_digest", "expected_record_digest"]
)
def test_reader_binding_is_exact(saved, tmp_path, field):
    w = saved
    root, key, command, profile = reference_only(w, tmp_path)
    attest(w, root, key)
    bad = str(uuid4()) if field.endswith("_id") else "e" * 64
    with pytest.raises(issuers.ScopeIssuerError):
        read(w, command, **{field: bad})
