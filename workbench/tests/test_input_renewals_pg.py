"""Fresh native evidence for identical input; no model or execution grant."""
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
from test_cost_quotes_pg import (
    ADMIN_DSN,
    api,
    exact,
    pdf_data,
    quote,
    requirements,
    saved,
    world,
)
from test_cost_quotes_pg import (
    database as quote_database,
)
from test_cost_quotes_pg import (
    publish as publish_prices,
)
from test_cost_quotes_pg import (
    reread as read_quote,
)
from test_input_seals_pg import ready as seal_ready
from test_input_seals_pg import reread as read_seal
from test_input_seals_pg import seal
from test_package_current_original_set_pg import wire
from test_verification_commands_pg import begin
from test_verification_program_pg import observation
from test_verification_program_pg import record as finish_program

from packages.domain.review_identity import digest
from packages.model_governance import material_input_authority as authority
from packages.model_governance import material_input_renewals as renewals
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import sha

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_INPUT_RENEWALS_PG") != "1",
    reason="explicit native renewal fixture required",
)
RENEWER = "fusion_material_input_renewer"
OTHER = "fusion_other_material_input_renewer"


@pytest.fixture(scope="module")
def database():
    base = quote_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    created = []
    installed = False
    try:
        owner.execute(renewals.SQL_FILE.read_text(encoding="utf-8"))
        installed = True
        factories = {}
        for role in (RENEWER, OTHER):
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
                    sql.Identifier(renewals.GROUP), sql.Identifier(role)
                )
            )
            dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=role, password=password)

            def factory(dsn=dsn):
                return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

            factories[role] = factory
        with factories[RENEWER]() as c, factories[OTHER]() as other:
            yield value | {
                "input_renewer": c,
                "input_renewer_factory": factories[RENEWER],
                "other_input_renewer": other,
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
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(renewals.GROUP))
                    )


def publish(w, quoted, **changes):
    owner = w["database"]["owner"]
    now = datetime.now(timezone.utc)
    values = {
        "id": str(uuid4()),
        "renew_login": RENEWER,
        "renew_login_oid": owner.execute(
            "SELECT oid FROM pg_roles WHERE rolname=%s", (RENEWER,)
        ).fetchone()["oid"],
        "quote_policy_id": quoted.metadata["document"]["policy_id"],
        "quote_policy_digest": quoted.metadata["document"]["policy_digest"],
        "origin": "synthetic_mechanism",
        "renew_method_digest": renewals.method_digest(),
        "renew_sql_method_digest": owner.execute(
            "SELECT material_input_renewal.native_method_digest() AS v"
        ).fetchone()["v"],
        "database_oid": owner.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()["oid"],
        "database_name": owner.info.dbname,
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(hours=1),
    } | changes
    owner.execute(
        sql.SQL("INSERT INTO material_input_renewal.profiles ({}) VALUES ({})").format(
            sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values),
        ),
        list(values.values()),
    )
    owner.execute(
        "INSERT INTO material_input_renewal.profile_heads VALUES(%s,%s,1,true) ON CONFLICT(renew_login) DO UPDATE SET profile_id=excluded.profile_id,revision=excluded.revision,enabled=true",
        (values["renew_login"], values["id"]),
    )
    checksum = owner.execute(
        "SELECT encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') AS v FROM material_input_renewal.profiles p WHERE id=%s",
        (values["id"],),
    ).fetchone()["v"]
    return values["id"], checksum


def fresh_program(wire, admission, monkeypatch):
    w, _, _ = wire
    old = admission.metadata["document"]
    owner = w["database"]["owner"]
    original_command = owner.execute(
        "SELECT document FROM material_verification.commands WHERE id=%s",
        (old["program_command_row_id"],),
    ).fetchone()["document"]
    case = (old["program_profile_id"], old["program_case_id"], original_command["case_digest"])
    logical = str(uuid4())
    ticket = begin(w, case, logical)
    staged = (None, ticket)
    completed = finish_program(w, staged, observation(wire, staged, monkeypatch))
    current = authority.qualify(
        w["database"]["input_verifier"],
        program_result_id=completed.metadata["document"]["result_id"],
        expected_program_result_digest=completed.metadata["digest"],
        policy_id=old["policy_id"],
        expected_policy_digest=old["policy_digest"],
        command_id=logical,
        expected_method_digest=authority.method_digest(),
    )
    return current, logical


def ready(wire, monkeypatch, *, age=120, expire_original=False, **profile_changes):
    w, _, _ = wire
    admission, ctx, seal_args = seal_ready(
        wire, monkeypatch, authority_changes={"max_program_age_seconds": age}
    )
    sealed = seal(w, seal_args)
    price_args, _ = publish_prices(w, sealed)
    quoted = quote(w, price_args)
    profile_id, profile_digest = publish(w, quoted, **profile_changes)
    if expire_original:
        recorded = (
            w["database"]["owner"]
            .execute(
                "SELECT document FROM material_verification.program_results WHERE id=%s",
                (admission.metadata["document"]["program_result_id"],),
            )
            .fetchone()["document"]["recorded_at"]
        )
        deadline = datetime.fromisoformat(recorded.replace("Z", "+00:00")) + timedelta(seconds=age)
        time.sleep(max(0, (deadline - datetime.now(timezone.utc)).total_seconds()) + 0.05)
        assert not read_seal(w, sealed).metadata["current"]["software_input_current"]
        assert not read_quote(w, quoted).metadata["current"]["software_quote_current"]
    current, logical = fresh_program(wire, admission, monkeypatch)
    args = {
        "seal_id": sealed.metadata["document"]["seal_id"],
        "expected_seal_digest": sealed.metadata["digest"],
        "quote_id": quoted.metadata["document"]["quote_id"],
        "expected_quote_digest": quoted.metadata["digest"],
        "verification_id": current.metadata["document"]["verification_id"],
        "expected_verification_digest": current.metadata["digest"],
        "profile_id": profile_id,
        "expected_profile_digest": profile_digest,
        "command_id": logical,
        "expected_method_digest": renewals.method_digest(),
    }
    return admission, ctx, sealed, quoted, current, args


def record(w, args, connection=None):
    return renewals.record(
        w["database"]["input_renewer"] if connection is None else connection, **args
    )


def reread(w, result):
    with w["database"]["input_renewer_factory"]() as c:
        return renewals.read(
            c,
            renewal_id=result.metadata["document"]["renewal_id"],
            expected_renewal_digest=result.metadata["digest"],
            expected_method_digest=renewals.method_digest(),
        )


def wire_digests(ctx, binding):
    bundle = material.bind_input(
        ctx,
        binding,
        expected_context_digest=ctx.metadata["digest"],
        expected_binding_digest=digest(binding),
        expected_method_digest=material.method_digest(),
    )
    result = []
    for rule in ctx.metadata["rules"]:
        if rule["selection"] != "include":
            continue
        request = vision.prepare_request(
            bundle,
            rule["rule_id"],
            expected_input_digest=bundle.metadata["digest"],
            expected_serializer_digest=vision.serializer_digest(),
        )
        result.append(
            {
                "rule_id": rule["rule_id"],
                "request_digest": sha(request.body),
                "semantic_input_digest": request.receipt["semantic_input_digest"],
            }
        )
    return bundle.metadata["digest"], result


def test_expired_admission_renewed_with_exact_input_quote_and_wire_content(wire, monkeypatch):
    w, state, _ = wire
    admission, ctx, sealed, quoted, current, args = ready(
        wire, monkeypatch, age=5, expire_original=True
    )
    old_input, old_wire = wire_digests(ctx, admission.binding)
    naive_input, naive_wire = wire_digests(ctx, current.binding)
    assert naive_input != old_input and naive_wire != old_wire
    result = record(w, args)
    observed = reread(w, result)
    d = result.metadata["document"]
    assert observed.record == result and observed.metadata["current"]["software_budget_sufficient"]
    assert d["admission_verification_id"] == admission.metadata["document"]["verification_id"]
    assert d["current_verification_id"] == current.metadata["document"]["verification_id"]
    assert (
        d["material_input_digest"]
        == old_input
        == sealed.metadata["document"]["material_input_digest"]
    )
    assert d["quote_digest"] == quoted.metadata["digest"] and wire_digests(
        ctx, admission.binding
    ) == (old_input, old_wire)
    assert record(w, args) == result and state["attempts"] == 12
    recorded = (
        w["database"]["owner"]
        .execute(
            "SELECT document FROM material_verification.program_results WHERE id=%s",
            (current.metadata["document"]["program_result_id"],),
        )
        .fetchone()["document"]["recorded_at"]
    )
    deadline = datetime.fromisoformat(recorded.replace("Z", "+00:00")) + timedelta(seconds=5)
    time.sleep(max(0, (deadline - datetime.now(timezone.utc)).total_seconds()) + 0.05)
    expired = reread(w, result)
    assert expired.record == result and not expired.metadata["current"]["software_evidence_current"]
    assert record(w, args) == result
    directory = os.environ.get("FUSION_INPUT_RENEWALS_EVIDENCE")
    if directory:
        (Path(directory) / "input-renewals-proof.json").write_text(
            json.dumps(
                {
                    "method_digest": renewals.method_digest(),
                    "record": result.metadata,
                    "reopened": observed.metadata,
                    "expired": expired.metadata,
                    "wire_digests": old_wire,
                    "naive_rebinding_changes_input_and_wire": True,
                    "old_admission_expired_without_rewriting_it": True,
                    "native_program_command_precedes_new_io": True,
                    "exact_input_and_quote_preserved": True,
                    "actual_loopback_gets": 12,
                    "synthetic_renderer_stub": True,
                    "actual_renderer_used": False,
                    "synthetic_material_and_configuration": True,
                    "actual_human_review": False,
                    "fee_ledger_reserved": False,
                    "execution_authorized": False,
                    "model_calls_created": 0,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def test_old_verification_and_arbitrary_nonce_cannot_claim_renewal(wire, monkeypatch):
    w, _, _ = wire
    admission, _, _, _, _, args = ready(wire, monkeypatch)
    with pytest.raises(renewals.InputRenewalError, match="PROGRAM_COMMAND_MISMATCH"):
        record(w, args | {"command_id": str(uuid4())})
    command = (
        w["database"]["owner"]
        .execute(
            "SELECT command_id FROM material_verification.commands WHERE id=%s",
            (admission.metadata["document"]["program_command_row_id"],),
        )
        .fetchone()["command_id"]
    )
    with pytest.raises(renewals.InputRenewalError, match="CURRENT_STATE_UNAVAILABLE"):
        record(
            w,
            args
            | {
                "verification_id": admission.metadata["document"]["verification_id"],
                "expected_verification_digest": admission.metadata["digest"],
                "command_id": str(command),
            },
        )


def test_all_other_purposes_and_other_assigned_login_reject(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    for key in (
        "owner",
        "verification_program",
        "input_verifier",
        "input_sealer",
        "cost_quoter",
        "other_input_renewer",
    ):
        with pytest.raises(renewals.InputRenewalError):
            record(w, args, w["database"][key])


@pytest.mark.parametrize(
    "field,value",
    [
        ("renew_sql_method_digest", "e" * 64),
        ("quote_policy_digest", "e" * 64),
        ("renew_login_oid", 1),
        ("database_oid", 1),
        ("database_name", "wrong_database"),
        ("origin", "current_prebid"),
    ],
)
def test_unapproved_method_realm_identity_or_quote_policy_rejects(wire, monkeypatch, field, value):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch, **{field: value})
    with pytest.raises(renewals.InputRenewalError, match="CURRENT_STATE_UNAVAILABLE"):
        record(w, args)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE material_input_renewal.profile_heads SET enabled=false,revision=revision+1",
        "UPDATE material_cost_quote.policy_heads SET enabled=false,revision=revision+1",
        "UPDATE material_input_seal.profile_heads SET revision=revision+1",
        "UPDATE material_input_authority.policy_heads SET revision=revision+1",
        "UPDATE design.bid_profiles SET phase='closed'",
    ],
)
def test_current_state_changes_preserve_record_and_reject_fresh_eligibility(
    wire, monkeypatch, mutation
):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    result = record(w, args)
    w["database"]["owner"].execute(mutation)
    observed = reread(w, result)
    assert (
        observed.record == result and not observed.metadata["current"]["software_evidence_current"]
    )
    assert record(w, args) == result


def test_four_connections_one_persisted_program_command_renewal(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)

    def run(_):
        with w["database"]["input_renewer_factory"]() as c:
            return record(w, args, c)

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, range(4)))
    assert all(row == rows[0] for row in rows)
    with pytest.raises(renewals.InputRenewalError, match="COMMAND_CONFLICT"):
        record(w, args | {"expected_quote_digest": "d" * 64})


def test_return_validation_rolls_back_wrong_approved_interface(wire, monkeypatch):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch, renew_method_digest="e" * 64)
    with pytest.raises(renewals.InputRenewalError, match="NATIVE_RESULT_INVALID"):
        record(w, args)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_input_renewal.records WHERE command_id=%s",
            (args["command_id"],),
        )
        .fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize(
    "change,restore",
    [
        (
            "GRANT SELECT ON material_input_renewal.records TO PUBLIC",
            "REVOKE SELECT ON material_input_renewal.records FROM PUBLIC",
        ),
        (
            "GRANT EXECUTE ON FUNCTION material_input_renewal.current_context(uuid,uuid,uuid,uuid) TO tender_material_input_renew",
            "REVOKE EXECUTE ON FUNCTION material_input_renewal.current_context(uuid,uuid,uuid,uuid) FROM tender_material_input_renew",
        ),
        (
            "ALTER FUNCTION material_cost_quote.current_context(uuid,uuid) SET TimeZone='Asia/Shanghai'",
            "ALTER FUNCTION material_cost_quote.current_context(uuid,uuid) SET TimeZone='UTC'",
        ),
    ],
)
def test_permission_or_private_method_drift_rejects(wire, monkeypatch, change, restore):
    w, _, _ = wire
    *_, args = ready(wire, monkeypatch)
    owner = w["database"]["owner"]
    owner.execute(change)
    try:
        with pytest.raises(renewals.InputRenewalError):
            record(w, args)
    finally:
        owner.execute(restore)
