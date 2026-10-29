"""Isolated pending registry; native identity is distinct from input authority."""
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
from test_package_current_material_pg import database as material_database
from test_package_current_original_set_pg import wire
from test_package_material_recovery_pg import restore, setup

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_registration as registration
from packages.storage.private_cas import PrivateContentStore

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_REGISTRATION_PG") != "1",
    reason="explicit grouped pending registration required",
)
LOGIN = "fusion_material_registration"


@pytest.fixture(scope="module")
def database():
    base = material_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    password = secrets.token_urlsafe(36)
    try:
        owner.execute(registration.SQL_FILE.read_text(encoding="utf-8"))
        owner.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(LOGIN), sql.Literal(password))
        )
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(registration.GROUP), sql.Identifier(LOGIN)
            )
        )
        dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=LOGIN, password=password)

        def connect():
            return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

        with connect() as verifier:
            yield value | {"registration_verifier": verifier, "registration_connection": connect}
    finally:
        try:
            next(base)
        except StopIteration:
            pass
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(LOGIN)))
            admin.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(registration.GROUP))
            )


def synthetic_packet():
    # References only. This fixture never asserts that native recovery occurred.
    return {"version": "package-native-material-registration-packet/1"} | {
        key: "a" * 64 for key in registration.PACKET_FIELDS
    }


def staged(w, tmp_path, *, command_id=None, packet=None):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    p = synthetic_packet() if packet is None else deepcopy(packet)
    p["registration_method_digest"] = registration.method_digest()
    command = {
        "version": "package-material-registration-command/1",
        "method_digest": registration.method_digest(),
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "scope_digest": w["saved_scope"]["digest"],
        "command_id": str(uuid4()) if command_id is None else command_id,
        "packet": p,
    }
    with PrivateContentStore(root) as store:
        key = store.publish(canonical(command))
    return root, key, command


def write(w, root, key, connection=None):
    with PrivateContentStore(root) as store:
        return registration.record(
            w["database"]["registration_verifier"] if connection is None else connection,
            store,
            command_commit_digest=key,
            expected_method_digest=registration.method_digest(),
        )


def read(w, command, **changes):
    args = {
        "bid_id": command["bid_id"],
        "command_id": command["command_id"],
        "expected_packet_digest": digest(command["packet"]),
        "expected_method_digest": registration.method_digest(),
    } | changes
    return registration.read(w["database"]["registration_verifier"], **args)


def test_actual_recovery_stages_durable_command_then_native_lookup_and_replay(wire, tmp_path):
    w, state, url = wire
    root, recovery_key, bundle = setup(wire, tmp_path)
    recovered = restore(root, recovery_key, bundle, wire)
    with PrivateContentStore(root) as store:
        command_key = registration.stage_command(
            store,
            recovered,
            command_id=str(uuid4()),
            expected_context_digest=bundle.metadata["context_digest"],
            expected_recovery_commit_digest=recovery_key,
            expected_method_digest=registration.method_digest(),
        )
        command = registration._command(store, command_key)
    registered = write(w, root, command_key)
    # The result can be lost after commit: resolve using only the previously saved command.
    with w["database"]["registration_connection"]() as reopened:
        looked = registration.read(
            reopened,
            bid_id=command["bid_id"],
            command_id=command["command_id"],
            expected_packet_digest=digest(command["packet"]),
            expected_method_digest=registration.method_digest(),
        )
        replayed = write(w, root, command_key, connection=reopened)
    assert looked.metadata == registered.metadata == replayed.metadata
    assert state["attempts"] == 4
    doc = registered.metadata["document"]
    assert doc["recorded_by"] == LOGIN and doc["status"] == "awaiting_independent_verification"
    assert doc["packet"]["context_digest"] == bundle.context.metadata["digest"]
    assert all(
        doc[k] is False
        for k in (
            "native_binding_verified",
            "necessary_scope_verified",
            "input_authority_granted",
            "execution_authorized",
        )
    )
    directory = os.environ.get("FUSION_MATERIAL_REGISTRATION_EVIDENCE")
    if directory:
        (Path(directory) / "material-registration-native-proof.json").write_text(
            json.dumps(
                {
                    "record": registered.metadata,
                    "command_commit_digest": command_key,
                    "synthetic_content": True,
                    "actual_recovery_loopback_gets": 4,
                    "durable_command_reopened": True,
                    "unknown_result_lookup_same_record": True,
                    "replay_same_record": True,
                    "provider_attempts": 0,
                    "input_authority_granted": False,
                    "native_binding_registered": False,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def test_pending_record_is_immutable_and_remains_readable_after_scope_close(saved, tmp_path):
    w = saved
    root, key, command = staged(w, tmp_path)
    result = write(w, root, key)
    assert read(w, command).metadata == result.metadata
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable_record"):
        w["database"]["owner"].execute(
            "UPDATE material_registration.records SET document=document WHERE command_id=%s",
            (command["command_id"],),
        )
    w["database"]["owner"].execute(
        "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (command["bid_id"],)
    )
    assert write(w, root, key).metadata == result.metadata == read(w, command).metadata


def test_changed_packet_same_command_conflicts(saved, tmp_path):
    w = saved
    root, key, command = staged(w, tmp_path)
    write(w, root, key)
    changed = deepcopy(command)
    changed["packet"]["context_digest"] = "b" * 64
    with PrivateContentStore(root) as store:
        other = store.publish(canonical(changed))
    with pytest.raises(registration.MaterialRegistrationError, match="COMMAND_CONFLICT") as caught:
        write(w, root, other)
    assert caught.value.__context__ is None
    assert read(w, command).metadata["document"]["packet"] == command["packet"]


def test_other_actor_cannot_lookup_or_replay_private_command(saved, tmp_path):
    w = saved
    root, key, command = staged(w, tmp_path)
    write(w, root, key)
    owner = w["database"]["owner"]
    other = "fusion_material_registration_other"
    secret = secrets.token_urlsafe(36)
    owner.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(sql.Identifier(other), sql.Literal(secret))
    )
    try:
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(registration.GROUP), sql.Identifier(other)
            )
        )
        dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=other, password=secret)
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as c:
            with pytest.raises(registration.MaterialRegistrationError, match="NOT_FOUND"):
                registration.read(
                    c,
                    bid_id=command["bid_id"],
                    command_id=command["command_id"],
                    expected_packet_digest=digest(command["packet"]),
                    expected_method_digest=registration.method_digest(),
                )
            with pytest.raises(registration.MaterialRegistrationError, match="COMMAND_CONFLICT"):
                write(w, root, key, connection=c)
    finally:
        owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(other)))


@pytest.mark.parametrize(
    "field", ["bid_id", "command_id", "expected_packet_digest", "expected_record_digest"]
)
def test_cross_binding_lookup_rejected(saved, tmp_path, field):
    w = saved
    root, key, command = staged(w, tmp_path)
    write(w, root, key)
    value = str(uuid4()) if field.endswith("_id") else "b" * 64
    with pytest.raises(registration.MaterialRegistrationError):
        read(w, command, **{field: value})


@pytest.mark.parametrize("role", ["owner", "scope_verifier", "original_verifier", "parse_verifier"])
def test_other_purpose_connections_cannot_register(saved, tmp_path, role):
    w = saved
    root, key, command = staged(w, tmp_path)
    with pytest.raises(registration.MaterialRegistrationError):
        write(w, root, key, connection=w["database"][role])


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM material_registration.records",
        "SELECT object_key FROM design.blobs",
        "SELECT * FROM design.outcomes",
        "UPDATE material_registration.records SET document=document WHERE false",
        "DELETE FROM material_registration.records WHERE false",
    ],
)
def test_no_direct_registry_business_or_label_read(saved, query):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        saved["database"]["registration_verifier"].execute(query)


def test_extra_public_select_is_rejected_without_runtime_repair(saved, tmp_path):
    w = saved
    root, key, command = staged(w, tmp_path)
    owner = w["database"]["owner"]
    owner.execute("GRANT SELECT ON material_registration.records TO PUBLIC")
    try:
        with pytest.raises(registration.MaterialRegistrationError, match="EXCESS_TABLE_PRIVILEGE"):
            write(w, root, key)
        assert owner.execute(
            "SELECT has_table_privilege(%s,'material_registration.records','SELECT') AS allowed",
            (LOGIN,),
        ).fetchone()["allowed"]
    finally:
        owner.execute("REVOKE SELECT ON material_registration.records FROM PUBLIC")


def test_modified_native_function_is_rejected_without_runtime_repair(saved, tmp_path):
    w = saved
    root, key, command = staged(w, tmp_path)
    owner = w["database"]["owner"]
    source = registration.SQL_FILE.read_text(encoding="utf-8")
    start = source.index("CREATE FUNCTION material_registration.read(")
    end = source.index("$material_read$;", start) + len("$material_read$;")
    original = source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    modified = original.replace(" SELECT * INTO item", " PERFORM 1;\n SELECT * INTO item")
    assert modified != original
    owner.execute(modified)
    try:
        with pytest.raises(registration.MaterialRegistrationError, match="NATIVE_METHOD_MISMATCH"):
            write(w, root, key)
    finally:
        owner.execute(original)


def test_borrowed_transaction_rejected(saved, tmp_path):
    w = saved
    root, key, command = staged(w, tmp_path)
    with (
        w["database"]["registration_verifier"].transaction(),
        pytest.raises(registration.MaterialRegistrationError, match="IDLE_CONNECTION_REQUIRED"),
    ):
        write(w, root, key)


def test_concurrent_connections_same_command_create_one_record(saved, tmp_path):
    w = saved
    root, key, command = staged(w, tmp_path)

    def attempt(index):
        with w["database"]["registration_connection"]() as c:
            return write(w, root, key, connection=c).metadata

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert all(r == results[0] for r in results)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_registration.records WHERE command_id=%s",
            (command["command_id"],),
        )
        .fetchone()["n"]
        == 1
    )


def test_invalid_native_result_rolls_back_insert(saved, tmp_path, monkeypatch):
    w = saved
    root, key, command = staged(w, tmp_path)

    def invalid(*args, **kwargs):
        raise registration.MaterialRegistrationError("synthetic result fault")

    monkeypatch.setattr(registration, "_validate_record", invalid)
    with pytest.raises(registration.MaterialRegistrationError, match="synthetic result fault"):
        write(w, root, key)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_registration.records WHERE command_id=%s",
            (command["command_id"],),
        )
        .fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize("mutation", ["null_version", "extra", "boolean", "zero_digest"])
def test_native_rpc_rejects_packet_bypass(saved, mutation):
    packet = synthetic_packet()
    if mutation == "null_version":
        packet["version"] = None
    elif mutation == "extra":
        packet["verified"] = True
    elif mutation == "boolean":
        packet["context_digest"] = False
    else:
        packet["context_digest"] = "0" * 64
    with pytest.raises(psycopg.Error, match="MATERIAL_REGISTRATION_PACKET_INVALID"):
        saved["database"]["registration_verifier"].execute(
            "SELECT material_registration.record(%s,%s,%s,%s,%s)",
            (
                saved["technical_scope"][0],
                saved["saved_scope"]["manifest"]["id"],
                saved["saved_scope"]["digest"],
                str(uuid4()),
                Jsonb(packet),
            ),
        )
