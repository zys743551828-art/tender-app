"""Native input sealing; explicitly synthetic program and review fixtures."""
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
from test_input_authority_pg import (
    ADMIN_DSN,
    api,
    approve,
    exact,
    pdf_data,
    qualify,
    requirements,
    saved,
    world,
)
from test_input_authority_pg import (
    database as authority_database,
)
from test_package_current_original_set_pg import wire
from test_verification_program_pg import observation, record, staged

from packages.domain.review_identity import digest
from packages.model_governance import material_input_seals as seals
from packages.model_governance import package_native_material_store as store
from packages.model_governance import package_technical_material as material

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_INPUT_SEALS_PG") != "1",
    reason="explicit native input seal fixture required",
)
SEALER = "fusion_input_sealer"
OTHER = "fusion_other_input_sealer"


@pytest.fixture(scope="module")
def database():
    base = authority_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    installed = False
    created = []
    try:
        owner.execute(seals.SQL_FILE.read_text(encoding="utf-8"))
        installed = True
        factories = {}
        for role in (SEALER, OTHER):
            assert not owner.execute("SELECT FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            created.append(role)
            owner.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(seals.GROUP), sql.Identifier(role))
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=role, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[role] = factory
        with factories[SEALER]() as c, factories[OTHER]() as other:
            yield value | {
                "input_sealer": c,
                "input_sealer_factory": factories[SEALER],
                "other_input_sealer": other,
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
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(seals.GROUP))
                    )


def publish(w, verified, **changes):
    """Fresh initializer pins known existing method implementations and assigned account."""
    owner = w["database"]["owner"]
    q = verified.metadata["document"]
    now = datetime.now(timezone.utc)
    values = {
        "id": str(uuid4()),
        "sealer_login": SEALER,
        "sealer_login_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (SEALER,)
        ).fetchone()["oid"],
        "authority_policy_id": q["policy_id"],
        "authority_policy_digest": q["policy_digest"],
        "origin": "synthetic_mechanism",
        "seal_method_digest": seals.method_digest(),
        "seal_sql_method_digest": owner.execute(
            "SELECT material_input_seal.native_method_digest() AS v"
        ).fetchone()["v"],
        "input_method_digest": material.method_digest(),
        "context_method_digest": material.context_method_digest(),
        "store_method_digest": store.method_digest(),
        "database_oid": owner.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()["oid"],
        "database_name": owner.info.dbname,
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(hours=1),
    } | changes
    owner.execute(
        sql.SQL("INSERT INTO material_input_seal.profiles ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    owner.execute(
        "INSERT INTO material_input_seal.profile_heads VALUES(%s,%s,1,true) ON CONFLICT(sealer_login) DO UPDATE SET profile_id=excluded.profile_id,revision=excluded.revision,enabled=true",
        (values["sealer_login"], values["id"]),
    )
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') AS v FROM material_input_seal.profiles p WHERE id=%s",
        (values["id"],),
    ).fetchone()["v"]
    return {
        "verification_id": q["verification_id"],
        "expected_verification_digest": verified.metadata["digest"],
        "profile_id": values["id"],
        "expected_profile_digest": checksum,
        "command_id": str(uuid4()),
        "expected_method_digest": seals.method_digest(),
    }


def ready(wire, monkeypatch, *, authority_changes=None, **profile_changes):
    w, _, _ = wire
    p = staged(wire)
    completed = record(w, p, observation(wire, p, monkeypatch))
    verified = qualify(w, approve(w, completed, changes=authority_changes))
    return verified, p[0][1].context, publish(w, verified, **profile_changes)


def seal(w, args, connection=None):
    return seals.seal(w["database"]["input_sealer"] if connection is None else connection, **args)


def reread(w, record):
    with w["database"]["input_sealer_factory"]() as c:
        return seals.read(
            c,
            seal_id=record.metadata["document"]["seal_id"],
            expected_seal_digest=record.metadata["digest"],
            expected_method_digest=seals.method_digest(),
        )


def test_server_constructs_exact_old_input_and_binds_full_native_evidence(wire, monkeypatch):
    w, state, _ = wire
    verified, context, args = ready(wire, monkeypatch)
    sealed = seal(w, args)
    bound = material.bind_input(
        context,
        verified.binding,
        expected_context_digest=context.metadata["digest"],
        expected_binding_digest=digest(verified.binding),
        expected_method_digest=material.method_digest(),
    )
    d = sealed.metadata["document"]
    assert d["material_input"] == bound.metadata and d["recorded_by"] == SEALER
    assert d["software_input_sealed"] and d["native_binding_verified"]
    assert not any(d[k] for k in seals.ORIGIN_FIELDS | seals.FALSE_FIELDS)
    assert seal(w, args) == sealed
    observed = reread(w, sealed)
    assert observed.record == sealed and observed.metadata["current"]["software_input_current"]
    assert not observed.metadata["current"]["current_input_verified"] and state["attempts"] == 8
    directory = os.environ.get("FUSION_INPUT_SEALS_EVIDENCE")
    if directory:
        (Path(directory) / "input-seals-proof.json").write_text(
            json.dumps(
                {
                    "method_digest": seals.method_digest(),
                    "record": sealed.metadata,
                    "reopened": observed.metadata,
                    "independent_sealer_login_and_oid": True,
                    "exact_old_input_metadata_matches": True,
                    "complete_native_object_set_rehashed": True,
                    "qualification_or_sealing_additional_gets": 0,
                    "synthetic_renderer_stub": True,
                    "actual_renderer_used": False,
                    "synthetic_material_and_configuration": True,
                    "input_authority_granted": False,
                    "actual_human_review": False,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "key",
    [
        "owner",
        "verification_program",
        "verification_requester",
        "input_verifier",
        "other_input_sealer",
    ],
)
def test_only_assigned_separate_sealer_can_consume_verification(wire, monkeypatch, key):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch)
    with pytest.raises(seals.InputSealError):
        seal(w, args, w["database"][key])


@pytest.mark.parametrize(
    "field,value",
    [
        ("seal_sql_method_digest", "e" * 64),
        ("context_method_digest", "e" * 64),
        ("store_method_digest", "e" * 64),
        ("authority_policy_digest", "e" * 64),
        ("origin", "current_prebid"),
        ("database_oid", 1),
        ("database_name", "wrong_database"),
        ("sealer_login_oid", 1),
    ],
)
def test_unapproved_policy_method_store_or_identity_cannot_seal(wire, monkeypatch, field, value):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch, **{field: value})
    with pytest.raises(seals.InputSealError, match="CURRENT_STATE_UNAVAILABLE"):
        seal(w, args)


@pytest.mark.parametrize("field", ["seal_method_digest", "input_method_digest"])
def test_python_return_validation_rolls_back_incompatible_input_method(wire, monkeypatch, field):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch, **{field: "d" * 64})
    with pytest.raises(seals.InputSealError, match="NATIVE_RESULT_INVALID"):
        seal(w, args)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_input_seal.records WHERE command_id=%s",
            (args["command_id"],),
        )
        .fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE material_input_seal.profile_heads SET enabled=false,revision=revision+1",
        "UPDATE material_input_authority.policy_heads SET enabled=false,revision=revision+1",
        "UPDATE material_input_authority.policy_heads SET revision=revision+1",
        "UPDATE material_verification.profile_heads SET enabled=false,revision=revision+1",
        "UPDATE scope_review_issuer.case_heads SET enabled=false,revision=revision+1",
        "UPDATE design.bid_profiles SET phase='closed'",
    ],
)
def test_revocation_and_current_source_changes_preserve_fact_but_block_current_input(
    wire, monkeypatch, change
):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch)
    sealed = seal(w, args)
    w["database"]["owner"].execute(change)
    observed = reread(w, sealed)
    assert observed.record == sealed and not observed.metadata["current"]["software_input_current"]
    assert seal(w, args) == sealed
    with pytest.raises(seals.InputSealError, match="CURRENT_STATE_UNAVAILABLE"):
        seal(w, args | {"command_id": str(uuid4())})


def test_four_connections_one_immutable_seal_and_different_commands_conflict(wire, monkeypatch):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch)

    def run(_):
        with w["database"]["input_sealer_factory"]() as c:
            return seal(w, args, c)

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, range(4)))
    assert all(row == rows[0] for row in rows)
    with pytest.raises(seals.InputSealError, match="ALREADY_SEALED"):
        seal(w, args | {"command_id": str(uuid4())})
    with pytest.raises(seals.InputSealError, match="COMMAND_CONFLICT"):
        seal(w, args | {"expected_verification_digest": "d" * 64})


def test_new_profile_revision_requires_a_new_seal_and_preserves_old_record(wire, monkeypatch):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch)
    first = seal(w, args)
    w["database"]["owner"].execute(
        "UPDATE material_input_seal.profile_heads SET revision=revision+1"
    )
    assert not reread(w, first).metadata["current"]["software_input_current"]
    second = seal(w, args | {"command_id": str(uuid4())})
    assert second.metadata["document"]["profile_head_revision"] == 2
    assert (
        reread(w, first).record == first
        and reread(w, second).metadata["current"]["software_input_current"]
    )


def test_program_fact_age_limit_also_expires_current_seal_observation(wire, monkeypatch):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch, authority_changes={"max_program_age_seconds": 1})
    sealed = seal(w, args)
    time.sleep(1.05)
    observed = reread(w, sealed)
    assert observed.record == sealed and not observed.metadata["current"]["verification_current"]
    assert not observed.metadata["current"]["software_input_current"] and seal(w, args) == sealed
    with pytest.raises(seals.InputSealError, match="CURRENT_STATE_UNAVAILABLE"):
        seal(w, args | {"command_id": str(uuid4())})


def test_expired_sealer_configuration_cannot_be_used(wire, monkeypatch):
    w, _, _ = wire
    _, _, args = ready(
        wire,
        monkeypatch,
        valid_from=datetime(2019, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(seals.InputSealError, match="CURRENT_STATE_UNAVAILABLE"):
        seal(w, args)


def test_missing_native_object_link_blocks_sealing(wire, monkeypatch):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    row = owner.execute(
        "SELECT l.record_id,l.object_sha FROM material_input_authority.verifications q JOIN material_registration.records r ON r.id=(q.document->>'registration_id')::uuid JOIN technical_material_store.record_objects l ON l.record_id=(r.document#>>'{packet,storage_record_id}')::uuid WHERE q.id=%s LIMIT 1",
        (args["verification_id"],),
    ).fetchone()
    # Fault injection is confined to the fresh fixture; restore exact link immediately.
    owner.execute(
        "ALTER TABLE technical_material_store.record_objects DISABLE TRIGGER immutable_material_store_link"
    )
    try:
        owner.execute(
            "DELETE FROM technical_material_store.record_objects WHERE record_id=%s AND object_sha=%s",
            (row["record_id"], row["object_sha"]),
        )
        with pytest.raises(seals.InputSealError, match="CURRENT_STATE_UNAVAILABLE"):
            seal(w, args)
    finally:
        owner.execute(
            "INSERT INTO technical_material_store.record_objects VALUES(%s,%s)",
            (row["record_id"], row["object_sha"]),
        )
        owner.execute(
            "ALTER TABLE technical_material_store.record_objects ENABLE TRIGGER immutable_material_store_link"
        )


@pytest.mark.parametrize(
    "change,restore",
    [
        (
            "GRANT SELECT ON material_input_seal.records TO PUBLIC",
            "REVOKE SELECT ON material_input_seal.records FROM PUBLIC",
        ),
        (
            "GRANT EXECUTE ON FUNCTION material_input_seal.current_context(uuid,uuid) TO tender_material_input_seal",
            "REVOKE EXECUTE ON FUNCTION material_input_seal.current_context(uuid,uuid) FROM tender_material_input_seal",
        ),
        (
            "ALTER FUNCTION material_input_authority.source_current(uuid,uuid,text) SET TimeZone='Asia/Shanghai'",
            "ALTER FUNCTION material_input_authority.source_current(uuid,uuid,text) SET TimeZone='UTC'",
        ),
    ],
)
def test_private_permission_or_approved_authority_code_drift_is_rejected(
    wire, monkeypatch, change, restore
):
    w, _, _ = wire
    _, _, args = ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    owner.execute(change)
    try:
        with pytest.raises(seals.InputSealError):
            seal(w, args)
    finally:
        owner.execute(restore)
