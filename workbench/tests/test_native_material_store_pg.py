"""Actual independent native byte storage; derivation claims remain synthetic."""
# ruff: noqa: F401,F811

import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_native_material_store import prepared
from test_package_current_material_pg import (
    ADMIN_DSN,
    api,
    exact,
    pdf_data,
    requirements,
    saved,
    world,
)
from test_package_current_material_pg import collect as native_collect
from test_package_current_original_set_pg import wire
from test_package_technical_material import context
from test_scope_review_issuers_pg import database as issuer_database

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_native_material_store as store
from packages.storage.private_cas import sha

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_NATIVE_MATERIAL_STORE_PG") != "1",
    reason="explicit grouped private native material store required",
)
WRITER = "fusion_material_store_writer"
READER = "fusion_material_store_reader"


@pytest.fixture(scope="module")
def database():
    base = issuer_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    try:
        names = [WRITER, READER, store.WRITE_GROUP, store.READ_GROUP]
        assert not owner.execute("SELECT FROM pg_roles WHERE rolname=ANY(%s)", (names,)).fetchone()
        owner.execute(store.SQL_FILE.read_text(encoding="utf-8"))
        created.extend([store.WRITE_GROUP, store.READ_GROUP])
        factories = {}
        for login, group in ((WRITER, store.WRITE_GROUP), (READER, store.READ_GROUP)):
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(login), sql.Literal(password))
            )
            created.append(login)
            owner.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(login))
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=login, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[login] = factory
        with factories[WRITER]() as writer, factories[READER]() as reader:
            yield value | {
                "material_writer": writer,
                "material_reader": reader,
                "material_writer_factory": factories[WRITER],
                "material_reader_factory": factories[READER],
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


def ready(wire, reason_suffix=""):
    w, state, url = wire
    return prepared(context(native_collect(w, url)), reason_suffix)


def put(w, p, command, connection=None):
    return store.put(
        w["database"]["material_writer"] if connection is None else connection,
        p,
        command_id=command,
        expected_packet_digest=digest(p.packet),
        expected_method_digest=store.method_digest(),
    )


def args(w, p, command, record=None):
    return {
        "bid_id": w["technical_scope"][0],
        "command_id": command,
        "expected_packet_digest": digest(p.packet),
        "expected_method_digest": store.method_digest(),
        "expected_record_digest": None if record is None else record.metadata["digest"],
    }


def raw_put(w, p, command, *, packet=None, keys=None, values=None, scope_digest=None):
    keys = sorted(p.objects) if keys is None else keys
    values = [p.objects[k] for k in keys] if values is None else values
    m = p.live.context.metadata
    return (
        w["database"]["material_writer"]
        .execute(
            "SELECT technical_material_store.put(%s,%s,%s,%s,%s,%s,%s)",
            (
                m["bid_id"],
                m["scope_id"],
                m["scope_digest"] if scope_digest is None else scope_digest,
                command,
                Jsonb(p.packet if packet is None else packet),
                keys,
                values,
            ),
        )
        .fetchone()
    )


def test_actual_native_private_write_independent_reopen_and_full_byte_recovery(wire):
    w, state, url = wire
    p = ready(wire)
    command = str(uuid4())
    record = put(w, p, command)
    reader = w["database"]["material_reader"]
    loaded = store.load(reader, **args(w, p, command, record))
    assert canonical(loaded.context_metadata) == canonical(p.live.context.metadata)
    assert canonical(loaded.source_observation) == canonical(p.live.context.origin.metadata)
    assert canonical(loaded.derivation_observation) == canonical(p.live.metadata)
    assert canonical(loaded.findings_metadata) == canonical(p.findings.metadata)
    expected_images = {r["asset_id"]: p.objects[r["sha256"]] for r in p.packet["image_objects"]}
    assert loaded.image_blobs == expected_images
    assert not any(record.metadata["document"][k] for k in store.FLAGS)
    with w["database"]["material_reader_factory"]() as reopened:
        recovered = store.read(reopened, **args(w, p, command))
    assert recovered.metadata == record.metadata and put(w, p, command).metadata == record.metadata
    assert state["attempts"] == state["idle_checks"] == 2
    assert record.metadata["document"]["recorded_by"] == WRITER
    directory = os.environ.get("FUSION_NATIVE_MATERIAL_STORE_EVIDENCE")
    if directory:
        (Path(directory) / "native-material-store-proof.json").write_text(
            json.dumps(
                {
                    "store_method_digest": store.method_digest(),
                    "record": record.metadata,
                    "object_count": len(p.objects),
                    "asset_count": len(p.packet["image_objects"]),
                    "physical_pages": 4,
                    "actual_loopback_gets": 2,
                    "exact_context_source_derivation_report_and_png_bytes_recovered": True,
                    "independent_writer_and_reader_logins": True,
                    "reader_closed_and_reopened": True,
                    "unknown_result_lookup_by_fixed_command": True,
                    "same_command_replay_same_record": True,
                    "synthetic_material": True,
                    "synthetic_derivation_claims": True,
                    "actual_renderer_used_in_this_store_test": False,
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


def test_object_must_belong_to_exact_record_not_just_exist_in_store(wire):
    w, _, _ = wire
    p = ready(wire)
    first = str(uuid4())
    r = put(w, p, first)
    other = prepared(p.live.context, " different synthetic reason")
    second = str(uuid4())
    put(w, other, second)
    foreign = other.packet["findings_object"]["sha256"]
    assert foreign not in p.objects
    with pytest.raises(store.NativeMaterialStoreError, match="OBJECT_NOT_IN_RECORD"):
        store.read(w["database"]["material_reader"], **args(w, p, first, r), object_digest=foreign)


@pytest.mark.parametrize("relation", ["objects", "records", "record_objects"])
def test_neither_runtime_role_has_direct_private_table_access(saved, relation):
    for role in ("material_writer", "material_reader"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            saved["database"][role].execute(
                sql.SQL("SELECT * FROM technical_material_store.{}").format(
                    sql.Identifier(relation)
                )
            )


@pytest.mark.parametrize(
    "role",
    [
        "owner",
        "registration_verifier",
        "scope_verifier",
        "original_verifier",
        "parse_verifier",
        "issuer",
        "issuer_reader",
        "material_reader",
    ],
)
def test_other_purposes_cannot_write_private_evidence(wire, role):
    w, _, _ = wire
    p = ready(wire)
    with pytest.raises(store.NativeMaterialStoreError):
        put(w, p, str(uuid4()), connection=w["database"][role])


def test_writer_cannot_use_independent_reader_port(wire):
    w, _, _ = wire
    p = ready(wire)
    command = str(uuid4())
    put(w, p, command)
    with pytest.raises(store.NativeMaterialStoreError):
        store.read(w["database"]["material_writer"], **args(w, p, command))


def test_native_role_policy_rejects_public_table_overgrant_without_python(wire):
    w, _, _ = wire
    p = ready(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT SELECT ON technical_material_store.objects TO PUBLIC")
    try:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege, match="MATERIAL_STORE_INDEPENDENT_LOGIN_REQUIRED"
        ):
            raw_put(w, p, str(uuid4()))
    finally:
        owner.execute("REVOKE SELECT ON technical_material_store.objects FROM PUBLIC")


@pytest.mark.parametrize("mutation", ["missing", "corrupt", "duplicate_asset"])
def test_raw_native_object_closure_and_hash_checks_reject_without_partial_rows(wire, mutation):
    w, _, _ = wire
    p = ready(wire)
    owner = w["database"]["owner"]
    command = str(uuid4())
    before = owner.execute("SELECT count(*) AS n FROM technical_material_store.objects").fetchone()[
        "n"
    ]
    keys = sorted(p.objects)
    values = [p.objects[k] for k in keys]
    packet = p.packet
    if mutation == "missing":
        keys = keys[:-1]
        values = values[:-1]
    elif mutation == "corrupt":
        values[0] = b"corrupt synthetic object"
    else:
        packet = json.loads(canonical(p.packet))
        packet["image_objects"].append(packet["image_objects"][0])
    with pytest.raises(psycopg.Error, match="MATERIAL_STORE_"):
        raw_put(w, p, command, packet=packet, keys=keys, values=values)
    assert (
        owner.execute("SELECT count(*) AS n FROM technical_material_store.objects").fetchone()["n"]
        == before
    )
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM technical_material_store.records WHERE command_id=%s",
            (command,),
        ).fetchone()["n"]
        == 0
    )


def test_invalid_native_result_rolls_back_objects_links_and_record(wire, monkeypatch):
    w, _, _ = wire
    p = ready(wire)
    command = str(uuid4())
    owner = w["database"]["owner"]
    before = owner.execute("SELECT count(*) AS n FROM technical_material_store.objects").fetchone()[
        "n"
    ]

    def invalid(value):
        raise store.NativeMaterialStoreError("synthetic result fault")

    monkeypatch.setattr(store, "_record", invalid)
    with pytest.raises(store.NativeMaterialStoreError, match="synthetic result fault"):
        put(w, p, command)
    assert (
        owner.execute("SELECT count(*) AS n FROM technical_material_store.objects").fetchone()["n"]
        == before
    )
    assert (
        owner.execute(
            "SELECT count(*) AS n FROM technical_material_store.records WHERE command_id=%s",
            (command,),
        ).fetchone()["n"]
        == 0
    )


def test_same_command_concurrent_writers_publish_one_record(wire):
    w, _, _ = wire
    p = ready(wire)
    command = str(uuid4())

    def writing(index):
        with w["database"]["material_writer_factory"]() as c:
            return put(w, p, command, connection=c).metadata

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(writing, range(4)))
    assert all(r == results[0] for r in results)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM technical_material_store.records WHERE command_id=%s",
            (command,),
        )
        .fetchone()["n"]
        == 1
    )


def test_closed_project_can_keep_exact_private_evidence_without_qualification(wire):
    w, _, _ = wire
    p = ready(wire)
    w["database"]["owner"].execute(
        "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (w["technical_scope"][0],)
    )
    record = put(w, p, str(uuid4()))
    assert record.metadata["document"]["status"] == "private_evidence_stored"
    assert not any(record.metadata["document"][k] for k in store.FLAGS)


def test_raw_nested_document_cannot_self_grant_input_authority(wire):
    w, _, _ = wire
    p = ready(wire)
    packet = json.loads(canonical(p.packet))
    objects = dict(p.objects)
    old = packet["derivation_object"]["sha256"]
    body = json.loads(objects.pop(old))
    body["input_authority_granted"] = True
    body["digest"] = digest({k: v for k, v in body.items() if k != "digest"})
    raw = canonical(body)
    key = sha(raw)
    objects[key] = raw
    packet["derivation_observation_digest"] = body["digest"]
    packet["derivation_object"] = {"sha256": key, "byte_size": len(raw)}
    keys = sorted(objects)
    with pytest.raises(psycopg.Error, match="MATERIAL_STORE_DOCUMENT_INVALID"):
        raw_put(w, p, str(uuid4()), packet=packet, keys=keys, values=[objects[k] for k in keys])


def test_wrong_native_scope_digest_rejects_private_storage(wire):
    w, _, _ = wire
    p = ready(wire)
    with pytest.raises(psycopg.Error, match="MATERIAL_STORE_SCOPE_MISMATCH"):
        raw_put(w, p, str(uuid4()), scope_digest="e" * 64)


def test_record_lookup_is_bound_to_exact_project(wire):
    w, _, _ = wire
    p = ready(wire)
    command = str(uuid4())
    r = put(w, p, command)
    values = args(w, p, command, r)
    values["bid_id"] = str(uuid4())
    with pytest.raises(store.NativeMaterialStoreError, match="NOT_FOUND"):
        store.read(w["database"]["material_reader"], **values)


def test_same_command_cannot_publish_different_private_report(wire):
    w, _, _ = wire
    p = ready(wire)
    command = str(uuid4())
    put(w, p, command)
    other = prepared(p.live.context, " conflicting report")
    with pytest.raises(store.NativeMaterialStoreError, match="COMMAND_CONFLICT"):
        put(w, other, command)


def test_native_function_owner_drift_rejects_without_runtime_repair(wire):
    w, _, _ = wire
    p = ready(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT CREATE ON SCHEMA technical_material_store TO tender_api")
    owner.execute(
        "ALTER FUNCTION technical_material_store.read(uuid,uuid,text,text) OWNER TO tender_api"
    )
    owner.execute("REVOKE CREATE ON SCHEMA technical_material_store FROM tender_api")
    try:
        with pytest.raises(store.NativeMaterialStoreError, match="NATIVE_METHOD_MISMATCH"):
            put(w, p, str(uuid4()))
    finally:
        owner.execute(
            sql.SQL(
                "ALTER FUNCTION technical_material_store.read(uuid,uuid,text,text) OWNER TO {}"
            ).format(sql.Identifier(owner.info.user))
        )


def test_shared_policy_audit_does_not_grant_other_purpose_schema_usage(saved):
    for role in ("material_writer", "material_reader"):
        row = (
            saved["database"][role]
            .execute("SELECT has_schema_privilege('scope_review_issuer','USAGE') AS allowed")
            .fetchone()
        )
        assert row["allowed"] is False
