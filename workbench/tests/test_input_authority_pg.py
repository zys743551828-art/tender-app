"""Independent native qualification; all fixtures are explicitly synthetic."""
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
import test_native_material_store as synthetic_store
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_package_current_original_set_pg import wire
from test_verification_program_pg import (
    ADMIN_DSN,
    api,
    exact,
    observation,
    pdf_data,
    record,
    requirements,
    saved,
    staged,
    world,
)
from test_verification_program_pg import (
    database as program_database,
)

from deploy import fusion_context_derivation as derivation
from deploy import fusion_verification_program as entry
from deploy import fusion_verified_material as controller
from packages.domain.review_identity import digest
from packages.model_governance import material_input_authority as authority
from packages.model_governance import material_verification_program as program
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_native_current_review as current_review
from packages.model_governance import package_technical_material as material

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_INPUT_AUTHORITY_PG") != "1",
    reason="explicit native authority fixture required",
)
VERIFIER = "fusion_input_authority"
OTHER = "fusion_other_input_authority"


@pytest.fixture(scope="module")
def database():
    base = program_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    installed = False
    try:
        owner.execute(authority.SQL_FILE.read_text(encoding="utf-8"))
        installed = True
        factories = {}
        for role in (VERIFIER, OTHER):
            assert not owner.execute("SELECT FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            created.append(role)
            owner.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(authority.GROUP), sql.Identifier(role)
                )
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=role, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[role] = factory
        with factories[VERIFIER]() as c, factories[OTHER]() as other:
            yield value | {
                "input_verifier": c,
                "input_verifier_factory": factories[VERIFIER],
                "other_input_verifier": other,
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
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(authority.GROUP))
                    )


def approve(w, result, *, image="sha256:" + "a" * 64, source="b" * 64, changes=None):
    """Owner publishes known local code and preselected renderer pins, not result claims."""
    owner = w["database"]["owner"]
    profile = result.metadata["document"]["profile_id"]
    identifier = str(uuid4())
    now = datetime.now(timezone.utc)
    values = {
        "id": identifier,
        "verifier_login": VERIFIER,
        "verifier_login_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (VERIFIER,)
        ).fetchone()["oid"],
        "program_profile_id": profile,
        "origin": "synthetic_mechanism",
        "verifier_method_digest": authority.method_digest(),
        "verifier_sql_method_digest": owner.execute(
            "SELECT material_input_authority.native_method_digest() AS v"
        ).fetchone()["v"],
        "program_port_method_digest": program.method_digest(),
        "program_method_digest": entry.method_digest(),
        "program_policy_digest": program.policy_digest(),
        "controller_method_digest": controller.method_digest(),
        "current_review_method_digest": current_review.method_digest(),
        "context_derivation_method_digest": derivation.method_digest(),
        "context_method_digest": material.context_method_digest(),
        "findings_method_digest": findings.method_digest(),
        "renderer_image_id": image,
        "renderer_source_digest": source,
        "review_issuer_kind": "human",
        "database_oid": owner.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()["oid"],
        "database_name": owner.info.dbname,
        "max_program_age_seconds": 120,
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(hours=1),
    } | (changes or {})
    owner.execute(
        sql.SQL("INSERT INTO material_input_authority.policies ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    owner.execute(
        "INSERT INTO material_input_authority.policy_heads VALUES(%s,%s,1,true)",
        (profile, identifier),
    )
    policy_digest = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)), 'UTF8')),'hex') AS v FROM material_input_authority.policies p WHERE id=%s",
        (identifier,),
    ).fetchone()["v"]
    return {
        "program_result_id": result.metadata["document"]["result_id"],
        "expected_program_result_digest": result.metadata["digest"],
        "policy_id": identifier,
        "expected_policy_digest": policy_digest,
        "command_id": str(uuid4()),
        "expected_method_digest": authority.method_digest(),
    }


def complete(wire, monkeypatch):
    w, _, _ = wire
    p = staged(wire)
    return record(w, p, observation(wire, p, monkeypatch))


def qualify(w, args, connection=None):
    return authority.qualify(
        w["database"]["input_verifier"] if connection is None else connection, **args
    )


def reread(w, record):
    with w["database"]["input_verifier_factory"]() as c:
        return authority.read(
            c,
            verification_id=record.metadata["document"]["verification_id"],
            expected_verification_digest=record.metadata["digest"],
            expected_method_digest=authority.method_digest(),
        )


def test_independent_native_qualification_reopen_and_opaque_binding(wire, monkeypatch):
    w, state, _ = wire
    completed = complete(wire, monkeypatch)
    args = approve(w, completed)
    verified = qualify(w, args)
    assert verified.metadata["document"]["recorded_by"] == VERIFIER
    assert verified.metadata["document"]["native_binding_verified"]
    assert not any(
        verified.metadata["document"][k] for k in authority.ORIGIN_FIELDS | authority.FALSE_FIELDS
    )
    assert qualify(w, args).metadata == verified.metadata
    reopened = reread(w, verified)
    assert reopened.record == verified and reopened.metadata["current"]["software_input_current"]
    assert not reopened.metadata["current"]["current_input_verified"] and state["attempts"] == 8
    directory = os.environ.get("FUSION_INPUT_AUTHORITY_EVIDENCE")
    if directory:
        (Path(directory) / "input-authority-proof.json").write_text(
            json.dumps(
                {
                    "method_digest": authority.method_digest(),
                    "record": verified.metadata,
                    "binding": verified.binding,
                    "reopened": reopened.metadata,
                    "independent_nonowner_login_and_oid": True,
                    "approved_methods_and_runtime_pins_enforced": True,
                    "native_sql_fingerprint_enforced": True,
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
    "key", ["owner", "verification_program", "verification_requester", "other_input_verifier"]
)
def test_only_policy_assigned_independent_verifier_can_qualify(wire, monkeypatch, key):
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch))
    with pytest.raises(authority.InputAuthorityError):
        qualify(w, args, w["database"][key])


@pytest.mark.parametrize(
    "field",
    [
        "verifier_sql_method_digest",
        "program_port_method_digest",
        "program_method_digest",
        "program_policy_digest",
        "controller_method_digest",
        "current_review_method_digest",
        "context_derivation_method_digest",
        "context_method_digest",
        "findings_method_digest",
        "renderer_image_id",
        "renderer_source_digest",
        "review_issuer_kind",
        "origin",
    ],
)
def test_unapproved_method_or_renderer_or_origin_never_qualifies(wire, monkeypatch, field):
    w, _, _ = wire
    wrong = "e" * 64
    if field == "renderer_image_id":
        wrong = "sha256:" + wrong
    if field == "review_issuer_kind":
        wrong = "external_receipt"
    if field == "origin":
        wrong = "current_prebid"
    args = approve(w, complete(wire, monkeypatch), changes={field: wrong})
    with pytest.raises(authority.InputAuthorityError, match="APPROVED_METHOD_MISMATCH"):
        qualify(w, args)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE material_input_authority.policy_heads SET enabled=false,revision=revision+1",
        "UPDATE material_verification.profile_heads SET enabled=false,revision=revision+1",
        "UPDATE scope_review_issuer.case_heads SET enabled=false,revision=revision+1",
        "UPDATE design.bid_profiles SET phase='closed'",
    ],
)
def test_native_current_state_required_and_old_fact_remains_after_revocation(
    wire, monkeypatch, mutation
):
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch))
    verified = qualify(w, args)
    w["database"]["owner"].execute(mutation)
    observed = reread(w, verified)
    assert (
        observed.record == verified and not observed.metadata["current"]["software_input_current"]
    )
    assert qualify(w, args) == verified
    with pytest.raises(authority.InputAuthorityError, match="CURRENT_STATE_UNAVAILABLE"):
        qualify(w, args | {"command_id": str(uuid4())})


def test_policy_revision_requires_new_verification_without_rewriting_old_receipt(wire, monkeypatch):
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch))
    first = qualify(w, args)
    w["database"]["owner"].execute(
        "UPDATE material_input_authority.policy_heads SET revision=revision+1"
    )
    assert not reread(w, first).metadata["current"]["software_input_current"]
    second = qualify(w, args | {"command_id": str(uuid4())})
    assert second.metadata["document"]["policy_head_revision"] == 2
    assert second.metadata["digest"] != first.metadata["digest"]
    assert (
        reread(w, first).record == first
        and reread(w, second).metadata["current"]["software_input_current"]
    )


def test_four_connections_one_command_and_conflicting_command_rejected(wire, monkeypatch):
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch))

    def run(_):
        with w["database"]["input_verifier_factory"]() as c:
            return qualify(w, args, c)

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, range(4)))
    assert all(row == rows[0] for row in rows)
    with pytest.raises(authority.InputAuthorityError, match="ALREADY_VERIFIED"):
        qualify(w, args | {"command_id": str(uuid4())})
    with pytest.raises(authority.InputAuthorityError, match="COMMAND_CONFLICT"):
        qualify(w, args | {"expected_program_result_digest": "f" * 64})


def test_old_program_fact_cannot_be_newly_qualified_after_policy_age_limit(wire, monkeypatch):
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch), changes={"max_program_age_seconds": 1})
    time.sleep(1.05)
    with pytest.raises(authority.InputAuthorityError, match="CURRENT_STATE_UNAVAILABLE"):
        qualify(w, args)


def test_result_validation_rolls_back_unapproved_python_method(wire, monkeypatch):
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch), changes={"verifier_method_digest": "d" * 64})
    with pytest.raises(authority.InputAuthorityError, match="NATIVE_RESULT_INVALID"):
        qualify(w, args)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_input_authority.verifications WHERE command_id=%s",
            (args["command_id"],),
        )
        .fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize("outcome", ["unable_to_verify", "change_required"])
def test_full_report_with_unresolved_findings_cannot_be_promoted(wire, monkeypatch, outcome):
    original = synthetic_store.draft_for

    def draft(packet):
        value = original(packet)
        value["findings"][0]["outcome"] = outcome
        return value

    monkeypatch.setattr(synthetic_store, "draft_for", draft)
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch))
    with pytest.raises(authority.InputAuthorityError, match="REVIEW_INCOMPLETE"):
        qualify(w, args)


@pytest.mark.parametrize("kind", ["withdraw", "revision", "review_reenabled"])
def test_source_changes_and_reenabled_review_do_not_reuse_old_program_completion(
    wire, monkeypatch, kind
):
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch))
    owner = w["database"]["owner"]
    if kind == "review_reenabled":
        owner.execute(
            "UPDATE scope_review_issuer.profile_heads SET enabled=false,revision=revision+1"
        )
        owner.execute(
            "UPDATE scope_review_issuer.profile_heads SET enabled=true,revision=revision+1"
        )
    else:
        source = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0][
            "source_id"
        ]
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status=CASE WHEN %s='withdraw' THEN 'withdrawn' ELSE status END WHERE source_id=%s",
            (kind, source),
        )
    with pytest.raises(authority.InputAuthorityError, match="CURRENT_STATE_UNAVAILABLE"):
        qualify(w, args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_oid", 1),
        ("database_name", "wrong_database"),
        ("verifier_login_oid", 1),
        ("valid_until", datetime(2020, 1, 1, tzinfo=timezone.utc)),
    ],
)
def test_policy_database_account_epoch_and_expiration_are_native(wire, monkeypatch, field, value):
    w, _, _ = wire
    changes = {field: value}
    if field == "valid_until":
        changes["valid_from"] = datetime(2019, 1, 1, tzinfo=timezone.utc)
    args = approve(w, complete(wire, monkeypatch), changes=changes)
    with pytest.raises(
        authority.InputAuthorityError, match="CURRENT_STATE_UNAVAILABLE|VERIFIER_IDENTITY_MISMATCH"
    ):
        qualify(w, args)


@pytest.mark.parametrize(
    "change",
    [
        "GRANT SELECT ON material_input_authority.verifications TO PUBLIC",
        "GRANT EXECUTE ON FUNCTION material_input_authority.policy_context(uuid,uuid) TO tender_material_input_verify",
        "ALTER FUNCTION material_input_authority.source_current(uuid,uuid,text) SET TimeZone='Asia/Shanghai'",
    ],
)
def test_permission_or_private_helper_drift_is_rejected(wire, monkeypatch, change):
    w, _, _ = wire
    args = approve(w, complete(wire, monkeypatch))
    owner = w["database"]["owner"]
    restore = {
        "GRANT SELECT ON material_input_authority.verifications TO PUBLIC": "REVOKE SELECT ON material_input_authority.verifications FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION material_input_authority.policy_context(uuid,uuid) TO tender_material_input_verify": "REVOKE EXECUTE ON FUNCTION material_input_authority.policy_context(uuid,uuid) FROM tender_material_input_verify",
        "ALTER FUNCTION material_input_authority.source_current(uuid,uuid,text) SET TimeZone='Asia/Shanghai'": "ALTER FUNCTION material_input_authority.source_current(uuid,uuid,text) SET TimeZone='UTC'",
    }[change]
    owner.execute(change)
    try:
        with pytest.raises(authority.InputAuthorityError):
            qualify(w, args)
    finally:
        owner.execute(restore)
