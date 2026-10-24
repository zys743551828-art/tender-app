"""Owned durable verifier intent before external IO; no program qualification."""
# ruff: noqa: F401,F811

import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from test_native_evidence_issuers_pg import (
    ADMIN_DSN,
    api,
    attest,
    exact,
    pdf_data,
    requirements,
    saved,
    setup,
    world,
)
from test_native_evidence_issuers_pg import database as issuer_database
from test_package_current_original_set_pg import wire

from deploy.fusion_verified_material import method_digest as controller_method
from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_verification_commands as commands

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_VERIFICATION_COMMANDS_PG") != "1",
    reason="explicit grouped verification command checks required",
)
REQUESTER = "fusion_verification_commands"
TARGET = "fusion_verification_program"


@pytest.fixture(scope="module")
def database():
    base = issuer_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    try:
        assert not owner.execute(
            "SELECT FROM pg_roles WHERE rolname=ANY(%s)", ([REQUESTER, TARGET, commands.GROUP],)
        ).fetchone()
        owner.execute(commands.SQL_FILE.read_text(encoding="utf-8"))
        created.append(commands.GROUP)
        passwords = {}
        for name in (REQUESTER, TARGET):
            passwords[name] = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(name), sql.Literal(passwords[name]))
            )
            created.append(name)
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(commands.GROUP), sql.Identifier(REQUESTER)
            )
        )
        dsn = make_conninfo(
            ADMIN_DSN, dbname=owner.info.dbname, user=REQUESTER, password=passwords[REQUESTER]
        )

        def factory():
            return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

        with factory() as c:
            yield value | {"verification_requester": c, "verification_requester_factory": factory}
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


def configure(
    w,
    pending,
    attested,
    *,
    profile_changes=None,
    case_changes=None,
    profile_enabled=True,
    case_enabled=True,
):
    owner = w["database"]["owner"]
    native = owner.execute(
        "SELECT clock_timestamp() AS at,(SELECT oid FROM pg_database WHERE datname=current_database()) AS db_oid,(SELECT oid FROM pg_roles WHERE rolname=%s) AS role_oid",
        (TARGET,),
    ).fetchone()
    profile_id, case_id = str(uuid4()), str(uuid4())
    at = native["at"]
    p = {
        "login": TARGET,
        "oid": native["role_oid"],
        "origin": "synthetic_mechanism",
        "controller": controller_method(),
        "policy": digest("synthetic controlled verifier policy"),
        "db_oid": native["db_oid"],
        "database": owner.info.dbname,
        "start": at - timedelta(minutes=1),
        "end": at + timedelta(hours=1),
    } | (profile_changes or {})
    owner.execute(
        "INSERT INTO material_verification.profiles VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            profile_id,
            p["login"],
            p["oid"],
            p["origin"],
            p["controller"],
            p["policy"],
            p["db_oid"],
            p["database"],
            p["start"],
            p["end"],
        ),
    )
    owner.execute(
        "INSERT INTO material_verification.profile_heads VALUES(%s,%s,1,%s) ON CONFLICT(target_login) DO UPDATE SET profile_id=EXCLUDED.profile_id,revision=material_verification.profile_heads.revision+1,enabled=EXCLUDED.enabled",
        (p["login"], profile_id, profile_enabled),
    )
    c = {
        "requester": REQUESTER,
        "requester_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (REQUESTER,)
        ).fetchone()["oid"],
        "registration_id": pending.metadata["document"]["registration_id"],
        "registration_digest": pending.metadata["digest"],
        "review_id": attested.metadata["document"]["attestation_id"],
        "review_digest": attested.metadata["digest"],
        "start": at - timedelta(minutes=1),
        "end": at + timedelta(hours=1),
    } | (case_changes or {})
    owner.execute(
        "INSERT INTO material_verification.cases VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            case_id,
            profile_id,
            c["requester"],
            c["requester_oid"],
            c["registration_id"],
            c["registration_digest"],
            c["review_id"],
            c["review_digest"],
            c["start"],
            c["end"],
        ),
    )
    owner.execute(
        "INSERT INTO material_verification.case_heads VALUES(%s,1,%s)", (case_id, case_enabled)
    )
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(c)),'UTF8')),'hex') AS digest FROM material_verification.cases c WHERE id=%s",
        (case_id,),
    ).fetchone()["digest"]
    return profile_id, case_id, checksum


def prepared(wire, **changes):
    w, _, _ = wire
    data = setup(wire)
    attested = attest(w, data, str(uuid4()))
    return configure(w, data[0], attested, **changes)


def begin(w, p, command, connection=None):
    return commands.begin(
        w["database"]["verification_requester"] if connection is None else connection,
        case_id=p[1],
        command_id=command,
        expected_case_digest=p[2],
        expected_method_digest=commands.method_digest(),
    )


def read(w, p, command, record=None, connection=None):
    return commands.read(
        w["database"]["verification_requester"] if connection is None else connection,
        case_id=p[1],
        command_id=command,
        expected_case_digest=p[2],
        expected_record_digest=None if record is None else record.metadata["digest"],
        expected_method_digest=commands.method_digest(),
    )


def test_native_command_before_new_io_replay_and_unknown_result_reopen(wire):
    w, state, _ = wire
    p = prepared(wire)
    command = str(uuid4())
    result = begin(w, p, command)
    d = result.metadata["document"]
    assert (
        d["recorded_by"] == REQUESTER
        and d["target_login"] == TARGET
        and d["status"] == "pending_controlled_verification"
    )
    assert not any(d[k] for k in commands.FALSE_FIELDS)
    assert state["attempts"] == 4 and begin(w, p, command).metadata == result.metadata
    with w["database"]["verification_requester_factory"]() as c:
        observed = read(w, p, command, connection=c)
    assert observed.metadata["record"] == {k: result.metadata[k] for k in ("document", "digest")}
    assert (
        observed.metadata["current"]["program_configuration_active"]
        and observed.metadata["current"]["case_active"]
    )
    assert observed.metadata["current"]["program_runtime_authenticated"] is False
    directory = os.environ.get("FUSION_VERIFICATION_COMMANDS_EVIDENCE")
    if directory:
        (Path(directory) / "verification-commands-proof.json").write_text(
            json.dumps(
                {
                    "command_method_digest": commands.method_digest(),
                    "record": result.metadata,
                    "observation": observed.metadata,
                    "prior_loopback_gets": 4,
                    "new_loopback_gets_during_command": 0,
                    "new_render_sessions_during_command": 0,
                    "logical_command_durable_before_next_external_io": True,
                    "unknown_result_recovered_after_reopen": True,
                    "target_login_name_and_native_oid_bound": True,
                    "requester_native_oid_bound": True,
                    "synthetic_material_and_configuration": True,
                    "program_runtime_authenticated": False,
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
        "native_registrar",
        "native_issuer",
        "native_issuer_reader",
        "material_writer",
        "material_reader",
        "scope_verifier",
    ],
)
def test_other_purposes_cannot_stage_verification_work(wire, role):
    w, _, _ = wire
    p = prepared(wire)
    with pytest.raises(commands.VerificationCommandError):
        begin(w, p, str(uuid4()), w["database"][role])


@pytest.mark.parametrize(
    "change",
    [
        "disabled_profile",
        "disabled_case",
        "expired",
        "database",
        "oid",
        "requester",
        "requester_oid",
        "registration",
        "review",
    ],
)
def test_case_program_identity_and_review_must_match(wire, change):
    w, _, _ = wire
    options = {}
    if change == "disabled_profile":
        options["profile_enabled"] = False
    elif change == "disabled_case":
        options["case_enabled"] = False
    elif change == "expired":
        now = w["database"]["owner"].execute("SELECT clock_timestamp() AS at").fetchone()["at"]
        options["profile_changes"] = {
            "start": now - timedelta(hours=2),
            "end": now - timedelta(hours=1),
        }
    elif change == "database":
        options["profile_changes"] = {"database": "synthetic_wrong_database"}
    elif change == "oid":
        options["profile_changes"] = {"oid": 1}
    elif change == "requester":
        options["case_changes"] = {"requester": "synthetic_other_requester"}
    elif change == "requester_oid":
        options["case_changes"] = {"requester_oid": 1}
    elif change == "registration":
        options["case_changes"] = {"registration_digest": "a" * 64}
    else:
        options["case_changes"] = {"review_digest": "a" * 64}
    p = prepared(wire, **options)
    with pytest.raises(commands.VerificationCommandError):
        begin(w, p, str(uuid4()))


def test_revocation_preserves_command_but_blocks_new_intent(wire):
    w, _, _ = wire
    p = prepared(wire)
    command = str(uuid4())
    record = begin(w, p, command)
    w["database"]["owner"].execute(
        "UPDATE material_verification.profile_heads SET enabled=false,revision=revision+1 WHERE target_login=%s",
        (TARGET,),
    )
    assert begin(w, p, command).metadata == record.metadata
    observed = read(w, p, command, record)
    assert observed.metadata["current"]["program_configuration_active"] is False
    assert observed.metadata["record"]["digest"] == record.metadata["digest"]
    with pytest.raises(commands.VerificationCommandError, match="PROFILE_UNAVAILABLE"):
        begin(w, p, str(uuid4()))


def test_target_login_drop_recreate_does_not_inherit_old_oid_configuration(wire):
    w, _, _ = wire
    p = prepared(wire)
    command = str(uuid4())
    record = begin(w, p, command)
    owner = w["database"]["owner"]
    owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(TARGET)))
    owner.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        ).format(sql.Identifier(TARGET))
    )
    assert read(w, p, command, record).metadata["current"]["program_configuration_active"] is False
    with pytest.raises(commands.VerificationCommandError, match="PROFILE_UNAVAILABLE"):
        begin(w, p, str(uuid4()))


def test_same_command_four_connections_create_one_record(wire):
    w, _, _ = wire
    p = prepared(wire)
    command = str(uuid4())

    def run(_):
        with w["database"]["verification_requester_factory"]() as c:
            return begin(w, p, command, c).metadata

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, range(4)))
    assert all(r == rows[0] for r in rows)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_verification.commands WHERE command_id=%s",
            (command,),
        )
        .fetchone()["n"]
        == 1
    )


def test_invalid_result_rolls_back_command(wire, monkeypatch):
    w, _, _ = wire
    p = prepared(wire)
    command = str(uuid4())

    def invalid(value):
        raise commands.VerificationCommandError("synthetic result fault")

    monkeypatch.setattr(commands, "_record", invalid)
    with pytest.raises(commands.VerificationCommandError, match="synthetic result fault"):
        begin(w, p, command)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_verification.commands WHERE command_id=%s",
            (command,),
        )
        .fetchone()["n"]
        == 0
    )


def test_revoked_independent_reviewer_rejects_new_verification_command(wire):
    w, state, _ = wire
    p = prepared(wire)
    w["database"]["owner"].execute(
        "UPDATE scope_review_issuer.profile_heads SET enabled=false,revision=revision+1"
    )
    with pytest.raises(commands.VerificationCommandError, match="REVIEW_UNAVAILABLE"):
        begin(w, p, str(uuid4()))
    assert state["attempts"] == 4


def test_reused_command_cannot_target_another_case_or_rewrite_old_record(wire):
    w, _, _ = wire
    first = prepared(wire)
    logical = str(uuid4())
    record = begin(w, first, logical)
    second = prepared(wire)
    with pytest.raises(commands.VerificationCommandError, match="CONFLICT"):
        begin(w, second, logical)
    assert read(w, first, logical, record).metadata["record"]["digest"] == record.metadata["digest"]


def test_native_policy_rejects_public_table_overgrant(wire):
    w, _, _ = wire
    p = prepared(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT SELECT ON material_verification.commands TO PUBLIC")
    try:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege, match="INDEPENDENT_LOGIN_REQUIRED"
        ):
            w["database"]["verification_requester"].execute(
                "SELECT material_verification.begin_command(%s,%s,%s)", (p[1], str(uuid4()), p[2])
            )
    finally:
        owner.execute("REVOKE SELECT ON material_verification.commands FROM PUBLIC")


def test_command_function_owner_drift_rejects_without_repair(wire):
    w, _, _ = wire
    p = prepared(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT CREATE ON SCHEMA material_verification TO tender_api")
    owner.execute(
        "ALTER FUNCTION material_verification.read_command(uuid,uuid,text) OWNER TO tender_api"
    )
    owner.execute("REVOKE CREATE ON SCHEMA material_verification FROM tender_api")
    try:
        with pytest.raises(commands.VerificationCommandError, match="NATIVE_METHOD_MISMATCH"):
            begin(w, p, str(uuid4()))
    finally:
        owner.execute(
            sql.SQL(
                "ALTER FUNCTION material_verification.read_command(uuid,uuid,text) OWNER TO {}"
            ).format(sql.Identifier(owner.info.user))
        )
