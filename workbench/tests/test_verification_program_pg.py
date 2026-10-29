"""Real native program identity with explicitly mocked renderer claims only."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_native_evidence_issuers_pg import (
    api,
    attest,
    exact,
    pdf_data,
    requirements,
    saved,
    setup,
    world,
)
from test_native_material_store import claims_for
from test_package_current_original_set_pg import wire
from test_verification_commands_pg import ADMIN_DSN, TARGET, begin, configure
from test_verification_commands_pg import database as command_database

from deploy import fusion_context_derivation as derivation
from deploy import fusion_verification_program as program
from deploy import fusion_verified_material as controller
from deploy.fusion_asset_runtime import FusionAssetRuntime
from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_verification_program as port

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_VERIFICATION_PROGRAM_PG") != "1",
    reason="explicit native verification program fixture required",
)
KEYS = (
    "native_registrar",
    "material_reader",
    "scope_verifier",
    "original_verifier",
    "parse_verifier",
    "native_issuer_reader",
)
OTHER = "fusion_other_verification_program"


@pytest.fixture(scope="module")
def database():
    base = command_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    installed = False
    other_created = False
    try:
        owner.execute(port.SQL_FILE.read_text(encoding="utf-8"))
        installed = True
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(sql.Identifier(port.GROUP), sql.Identifier(TARGET))
        )
        password = secrets.token_urlsafe(36)
        owner.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(TARGET), sql.Literal(password)
            )
        )
        dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=TARGET, password=password)

        def factory():
            return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

        assert not owner.execute("SELECT FROM pg_roles WHERE rolname=%s", (OTHER,)).fetchone()
        other_password = secrets.token_urlsafe(36)
        owner.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(OTHER), sql.Literal(other_password))
        )
        other_created = True
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(sql.Identifier(port.GROUP), sql.Identifier(OTHER))
        )
        other_dsn = make_conninfo(
            ADMIN_DSN, dbname=owner.info.dbname, user=OTHER, password=other_password
        )
        with (
            factory() as c,
            psycopg.connect(other_dsn, autocommit=True, row_factory=dict_row) as other,
        ):
            yield value | {
                "verification_program": c,
                "verification_program_factory": factory,
                "other_verification_program": other,
            }
    finally:
        try:
            next(base)
        except StopIteration:
            pass
        finally:
            if installed:
                with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
                    if other_created:
                        admin.execute(
                            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(OTHER))
                        )
                    admin.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(port.GROUP))
                    )


def staged(wire, **changes):
    w, _, _ = wire
    data = setup(wire)
    signed = attest(w, data, str(uuid4()))
    p = configure(w, data[0], signed, profile_changes={"policy": port.policy_digest()} | changes)
    command = str(uuid4())
    ticket = begin(w, p, command)
    return data, ticket


def args(staged):
    return {
        "command_id": staged[1].metadata["document"]["command_id"],
        "expected_command_digest": staged[1].metadata["digest"],
        "expected_method_digest": port.method_digest(),
    }


def context(w, staged, connection=None):
    return port.context(
        w["database"]["verification_program"] if connection is None else connection, **args(staged)
    )


def stub_renderer(monkeypatch):
    async def mocked(ctx, *args, **kwargs):
        return claims_for(ctx)

    monkeypatch.setattr(derivation, "collect", mocked)
    return FusionAssetRuntime(
        expected_image_id="sha256:" + "a" * 64, expected_source_digest="b" * 64
    )


def observation(wire, staged, monkeypatch):
    w, _, url = wire
    owned = context(w, staged)
    review_args = dict(owned.metadata["review_arguments"]) | {
        "profile": "development_s3",
        "url_for_locator": url,
    }
    live = asyncio.run(
        controller.collect(
            *(w["database"][k] for k in KEYS),
            runtime=stub_renderer(monkeypatch),
            review_arguments=review_args,
            expected_method_digest=controller.method_digest(),
        )
    )
    obs = {
        "version": "material-verification-execution/1",
        "command_id": args(staged)["command_id"],
        "command_digest": args(staged)["expected_command_digest"],
        "program_method_digest": program.method_digest(),
        "port_method_digest": port.method_digest(),
        "policy_digest": port.policy_digest(),
        "controller_method_digest": controller.method_digest(),
        "byte_profile": "development_s3",
        "verified_material": live.metadata,
    }
    obs["digest"] = digest(obs)
    return obs


def record(w, staged, obs):
    return port.record_result(
        w["database"]["verification_program"],
        **args(staged),
        observation=obs,
        expected_observation_digest=obs["digest"],
    )


def raw_record(w, staged, obs):
    return (
        w["database"]["verification_program"]
        .execute(
            "SELECT material_verification.record_program_result(%s,%s,%s)",
            (args(staged)["command_id"], args(staged)["expected_command_digest"], Jsonb(obs)),
        )
        .fetchone()
    )


def test_native_program_context_record_and_reopen_without_reexecution(wire, monkeypatch):
    w, state, _ = wire
    p = staged(wire)
    before = context(w, p)
    assert (
        before.prior_result is None and before.metadata["current"]["program_runtime_authenticated"]
    )
    obs = observation(wire, p, monkeypatch)
    result = record(w, p, obs)
    assert result.metadata["document"]["recorded_by"] == TARGET
    assert not any(result.metadata["document"][k] for k in port.FALSE_FIELDS)
    assert record(w, p, obs).metadata == result.metadata
    with w["database"]["verification_program_factory"]() as c:
        after = context(w, p, c)
    assert after.prior_result.metadata == result.metadata and state["attempts"] == 8
    directory = os.environ.get("FUSION_VERIFICATION_PROGRAM_EVIDENCE")
    if directory:
        (Path(directory) / "verification-program-proof.json").write_text(
            json.dumps(
                {
                    "port_method_digest": port.method_digest(),
                    "record": result.metadata,
                    "real_native_program_login_and_oid_authenticated": True,
                    "native_command_and_program_result_bound": True,
                    "reader_closed_and_reopened": True,
                    "unknown_result_recovered_without_io": True,
                    "actual_loopback_gets": 8,
                    "synthetic_renderer_stub": True,
                    "actual_renderer_used": False,
                    "synthetic_material_and_configuration": True,
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
        "verification_requester",
        "native_registrar",
        "material_reader",
        "material_writer",
        "native_issuer",
        "native_issuer_reader",
    ],
)
def test_other_purposes_cannot_consume_target_program_work(wire, role):
    w, _, _ = wire
    p = staged(wire)
    with pytest.raises(ValueError):
        context(w, p, w["database"][role])


def test_entrypoint_uses_native_context_and_resumes_without_gets(wire, monkeypatch):
    w, state, url = wire
    p = staged(wire)
    runtime = stub_renderer(monkeypatch)

    def execute():
        return asyncio.run(
            program.execute(
                w["database"]["verification_program"],
                *(w["database"][k] for k in KEYS),
                runtime=runtime,
                command_id=args(p)["command_id"],
                expected_command_digest=args(p)["expected_command_digest"],
                expected_method_digest=program.method_digest(),
                profile="development_s3",
                url_for_locator=url,
            )
        )

    first = execute()
    assert state["attempts"] == 8 and not first.metadata["resumed_completed_native_result"]
    again = execute()
    assert state["attempts"] == 8 and again.metadata["resumed_completed_native_result"]
    assert first.result.metadata == again.result.metadata


@pytest.mark.parametrize(
    "mutation",
    ["command", "controller", "policy", "profile", "capsule", "grant", "context", "findings"],
)
def test_native_complete_rejects_wrong_or_rehashed_observation(wire, monkeypatch, mutation):
    w, _, _ = wire
    p = staged(wire)
    obs = deepcopy(observation(wire, p, monkeypatch))
    if mutation == "command":
        obs["command_digest"] = "a" * 64
    elif mutation == "controller":
        obs["controller_method_digest"] = "a" * 64
    elif mutation == "policy":
        obs["policy_digest"] = "a" * 64
    elif mutation == "profile":
        obs["byte_profile"] = "oss_hangzhou"
    elif mutation == "capsule":
        obs["verified_material"]["status"] = "configured_review_confirmed"
    elif mutation == "grant":
        obs["verified_material"]["input_authority_granted"] = True
    elif mutation == "context":
        obs["verified_material"]["context_digest"] = "a" * 64
    else:
        obs["verified_material"]["findings_digest"] = "a" * 64
    capsule = obs["verified_material"]
    capsule["digest"] = digest({k: v for k, v in capsule.items() if k != "digest"})
    obs["digest"] = digest({k: v for k, v in obs.items() if k != "digest"})
    with pytest.raises(psycopg.errors.RaiseException):
        raw_record(w, p, obs)


@pytest.mark.parametrize("mutation", ["program", "case", "review", "closed", "source"])
def test_late_native_configuration_or_source_change_rejects_result(wire, monkeypatch, mutation):
    w, _, _ = wire
    p = staged(wire)
    obs = observation(wire, p, monkeypatch)
    owner = w["database"]["owner"]
    d = p[1].metadata["document"]
    if mutation == "program":
        owner.execute(
            "UPDATE material_verification.profile_heads SET enabled=false,revision=revision+1"
        )
    elif mutation == "case":
        owner.execute(
            "UPDATE material_verification.case_heads SET enabled=false,revision=revision+1 WHERE case_id=%s",
            (d["case_id"],),
        )
    elif mutation == "review":
        owner.execute(
            "UPDATE scope_review_issuer.profile_heads SET enabled=false,revision=revision+1"
        )
    elif mutation == "closed":
        owner.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (d["bid_id"],)
        )
    else:
        root = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0][
            "source_id"
        ]
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1 WHERE source_id=%s", (root,)
        )
    with pytest.raises(ValueError):
        record(w, p, obs)


def test_invalid_result_rolls_back_program_completion(wire, monkeypatch):
    w, _, _ = wire
    p = staged(wire)
    obs = observation(wire, p, monkeypatch)

    def invalid(value):
        raise port.VerificationProgramError("synthetic result fault")

    monkeypatch.setattr(port, "_record", invalid)
    with pytest.raises(port.VerificationProgramError, match="synthetic result fault"):
        record(w, p, obs)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_verification.program_results WHERE command_row_id=%s",
            (p[1].metadata["document"]["record_id"],),
        )
        .fetchone()["n"]
        == 0
    )


def test_same_purpose_different_account_cannot_read_another_program_task(wire):
    w, _, _ = wire
    p = staged(wire)
    with pytest.raises(port.VerificationProgramError, match="TARGET_IDENTITY_MISMATCH"):
        context(w, p, w["database"]["other_verification_program"])


@pytest.mark.parametrize("offset", [-121, 10])
def test_rehashed_expired_or_future_last_source_observation_rejects(wire, monkeypatch, offset):
    w, _, _ = wire
    p = staged(wire)
    obs = observation(wire, p, monkeypatch)
    capsule = obs["verified_material"]
    final = capsule["final_current_review"]
    recovery = final["current_recovery"]
    recovery["observed_at"] = (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()
    for value in (recovery, final, capsule, obs):
        value["digest"] = digest({k: v for k, v in value.items() if k != "digest"})
    with pytest.raises(psycopg.errors.RaiseException, match="OBSERVATION_STALE"):
        raw_record(w, p, obs)


def test_private_state_helper_not_exposed_and_accidental_grant_rejected(wire):
    w, _, _ = wire
    p = staged(wire)
    db = w["database"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db["verification_program"].execute(
            "SELECT material_verification.program_state(%s,%s)",
            (args(p)["command_id"], args(p)["expected_command_digest"]),
        )
    db["owner"].execute(
        sql.SQL(
            "GRANT EXECUTE ON FUNCTION material_verification.program_state(uuid,text) TO {}"
        ).format(sql.Identifier(port.GROUP))
    )
    try:
        with pytest.raises(port.VerificationProgramError, match="NATIVE_METHOD_MISMATCH"):
            context(w, p)
    finally:
        db["owner"].execute(
            sql.SQL(
                "REVOKE EXECUTE ON FUNCTION material_verification.program_state(uuid,text) FROM {}"
            ).format(sql.Identifier(port.GROUP))
        )


def test_private_helper_owner_drift_rejects_without_repair(wire):
    w, _, _ = wire
    p = staged(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT CREATE ON SCHEMA material_verification TO tender_api")
    owner.execute(
        "ALTER FUNCTION material_verification.program_state(uuid,text) OWNER TO tender_api"
    )
    owner.execute("REVOKE CREATE ON SCHEMA material_verification FROM tender_api")
    try:
        with pytest.raises(port.VerificationProgramError, match="NATIVE_METHOD_MISMATCH"):
            context(w, p)
    finally:
        owner.execute(
            sql.SQL(
                "ALTER FUNCTION material_verification.program_state(uuid,text) OWNER TO {}"
            ).format(sql.Identifier(owner.info.user))
        )


def test_native_program_policy_rejects_public_table_overgrant(wire):
    w, _, _ = wire
    p = staged(wire)
    owner = w["database"]["owner"]
    owner.execute("GRANT SELECT ON material_verification.program_results TO PUBLIC")
    try:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege, match="INDEPENDENT_LOGIN_REQUIRED"
        ):
            with w["database"]["verification_program"].transaction():
                w["database"]["verification_program"].execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                w["database"]["verification_program"].execute(
                    "SELECT material_verification.program_context(%s,%s)",
                    (args(p)["command_id"], args(p)["expected_command_digest"]),
                )
    finally:
        owner.execute("REVOKE SELECT ON material_verification.program_results FROM PUBLIC")


def test_four_program_connections_record_one_completion(wire, monkeypatch):
    w, _, _ = wire
    p = staged(wire)
    obs = observation(wire, p, monkeypatch)

    def run(_):
        with w["database"]["verification_program_factory"]() as c:
            return port.record_result(
                c, **args(p), observation=obs, expected_observation_digest=obs["digest"]
            ).metadata

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, range(4)))
    assert all(r == rows[0] for r in rows)
    assert (
        w["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM material_verification.program_results WHERE command_row_id=%s",
            (p[1].metadata["document"]["record_id"],),
        )
        .fetchone()["n"]
        == 1
    )


def test_wrong_published_policy_rejects_entry_before_new_get(wire):
    w, state, url = wire
    p = staged(wire, policy="a" * 64)
    with pytest.raises(port.VerificationProgramError, match="PROGRAM_POLICY_MISMATCH"):
        asyncio.run(
            program.execute(
                w["database"]["verification_program"],
                *(w["database"][k] for k in KEYS),
                runtime=object(),
                command_id=args(p)["command_id"],
                expected_command_digest=args(p)["expected_command_digest"],
                expected_method_digest=program.method_digest(),
                profile="development_s3",
                url_for_locator=url,
            )
        )
    assert state["attempts"] == 4


def test_completed_result_can_be_recovered_after_configuration_revoked(wire, monkeypatch):
    w, state, _ = wire
    p = staged(wire)
    obs = observation(wire, p, monkeypatch)
    recorded = record(w, p, obs)
    w["database"]["owner"].execute(
        "UPDATE material_verification.profile_heads SET enabled=false,revision=revision+1"
    )
    owned = context(w, p)
    assert owned.metadata["current"]["program_configuration_current"] is False
    assert owned.prior_result.metadata == recorded.metadata and state["attempts"] == 8
