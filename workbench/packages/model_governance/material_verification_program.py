"""Authenticated target-program facts, distinct from independent input authority."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_verification_commands as commands
from packages.model_governance import package_scope_review_issuers as policy_source
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

ROOT = Path(__file__).parents[2]
SQL_FILE = ROOT / "deploy/sql/material-verification-program.sql"
ENTRY = ROOT / "deploy/fusion_verification_program.py"
CONTROLLER = ROOT / "deploy/fusion_verified_material.py"
GROUP = "tender_material_verification_program"
RPCS = (
    "material_verification.program_context(uuid,text)",
    "material_verification.record_program_result(uuid,text,jsonb)",
)
MAX_OBSERVATION_BYTES = 8 * 1024 * 1024
CAPSULE_FIELDS = frozenset(
    {
        "version",
        "method_digest",
        "context_digest",
        "findings_digest",
        "initial_current_review",
        "live_derivation",
        "final_current_review",
        "status",
        "actual_current_derivation_and_review_combined",
        "trusted_derivation_bound",
        "issuer_state_unchanged_across_all_stages",
        "exact_frozen_context_and_report_preserved",
        "actual_human_reading_verified",
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
        "atomic_snapshot_verified",
        "send_lease_granted",
        "digest",
    }
)
UUID_FIELDS = frozenset(
    {
        "result_id",
        "command_row_id",
        "command_id",
        "profile_id",
        "case_id",
        "bid_id",
        "scope_id",
        "registration_id",
        "review_attestation_id",
    }
)
SHA_FIELDS = frozenset(
    {
        "command_digest",
        "scope_digest",
        "context_digest",
        "findings_digest",
        "registration_digest",
        "review_attestation_digest",
        "observation_digest",
        "program_method_digest",
        "port_method_digest",
        "controller_method_digest",
        "policy_digest",
    }
)
FALSE_FIELDS = frozenset(
    {
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
        "actual_human_reading_verified",
        "historical_existence_verified",
        "atomic_snapshot_verified",
        "send_lease_granted",
    }
)
OBS_ROOTS = frozenset(
    {
        "command_digest",
        "program_method_digest",
        "port_method_digest",
        "policy_digest",
        "controller_method_digest",
        "digest",
    }
)
REVIEW_FIELDS = frozenset(
    {
        "registration_command_id",
        "expected_registration_packet_digest",
        "expected_registration_digest",
        "issuer_command_id",
        "expected_issuer_reference_digest",
        "expected_issuer_digest",
        "expected_context_digest",
        "bid_id",
        "scope_id",
        "expected_scope_digest",
    }
)
KNOWN_ERRORS = frozenset(
    "VERIFICATION_PROGRAM_" + s
    for s in (
        "OWNED_READ_TRANSACTION_REQUIRED",
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "NOT_FOUND",
        "TARGET_IDENTITY_MISMATCH",
        "OBSERVATION_INVALID",
        "COMMAND_CONFLICT",
        "CONFIGURATION_UNAVAILABLE",
        "POLICY_MISMATCH",
        "MATERIAL_MISMATCH",
        "REVIEW_STATE_CHANGED",
        "CURRENT_SOURCE_CHANGED",
        "OBSERVATION_STALE",
    )
)


class VerificationProgramError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise VerificationProgramError("VERIFICATION_PROGRAM_" + code)


@dataclass(frozen=True, repr=False)
class NativeProgramResult:
    metadata: dict


@dataclass(frozen=True, repr=False)
class NativeProgramContext:
    command: commands.NativeVerificationCommand
    prior_result: NativeProgramResult | None
    metadata: dict


def policy_digest():
    return digest(
        {
            "version": "material-verification-program-policy/1",
            "port_source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "entry_source": sha(ENTRY.read_bytes()),
            "controller_source": sha(CONTROLLER.read_bytes()),
            "transport_profiles": {
                "synthetic_mechanism": "development_s3",
                "current_prebid": "oss_hangzhou",
            },
            "grants_input_authority": False,
        }
    )


def method_digest():
    return digest(
        {
            "version": "material-verification-program-port/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "command_method": commands.method_digest(),
            "policy_digest": policy_digest(),
            "purpose_audit_source": sha(Path(read_purpose.__file__).read_bytes()),
            "private_policy_sql_source": sha(policy_source.SQL_FILE.read_bytes()),
            "maximum_observation_bytes": MAX_OBSERVATION_BYTES,
        }
    )


def _time(value):
    commands._time(value)


def _oid(value):
    return type(value) is int and 1 <= value <= 4294967295


def _observation(value):
    if (
        type(value) is not dict
        or set(value) != OBS_ROOTS | {"version", "command_id", "byte_profile", "verified_material"}
        or value["version"] != "material-verification-execution/1"
        or len(canonical(value)) > MAX_OBSERVATION_BYTES
        or any(not is_digest(value[k]) for k in OBS_ROOTS)
        or digest({k: v for k, v in value.items() if k != "digest"}) != value["digest"]
        or type(value["byte_profile"]) is not str
        or value["byte_profile"] not in {"development_s3", "oss_hangzhou"}
    ):
        fail("OBSERVATION_INVALID")
    commands._uuid(value["command_id"])
    capsule = value["verified_material"]
    if (
        type(capsule) is not dict
        or set(capsule) != CAPSULE_FIELDS
        or capsule.get("version") != "fusion-live-verified-material/1"
        or capsule.get("method_digest") != value["controller_method_digest"]
        or digest({k: v for k, v in capsule.items() if k != "digest"}) != capsule.get("digest")
        or any(capsule.get(k) is not False for k in FALSE_FIELDS)
        or any(
            capsule.get(k) is not True
            for k in (
                "actual_current_derivation_and_review_combined",
                "trusted_derivation_bound",
                "issuer_state_unchanged_across_all_stages",
                "exact_frozen_context_and_report_preserved",
            )
        )
    ):
        fail("OBSERVATION_INVALID")
    return deepcopy(value)


def _audit(c):
    read_purpose.require_read_purpose(
        c, read_purpose.ReadPurpose(groups=frozenset({GROUP}), definer_calls=RPCS)
    )
    owner = c.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass('material_verification.program_results')"
    ).fetchone()
    if owner is None or owner["relowner"] != owner["nspowner"]:
        fail("NATIVE_METHOD_MISMATCH")
    policy = policy_source.SQL_FILE.read_text(encoding="utf-8").split("$scope_issuer_policy$")
    rows = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname='scope_review_issuer' AND p.proname='role_policy' AND oidvectortypes(p.proargtypes)='name, text, text[]'"
    ).fetchall()
    if len(policy) != 3 or len(rows) != 1:
        fail("NATIVE_METHOD_MISMATCH")
    r = rows[0]
    if (
        r["prosrc"] != policy[1]
        or r["prosecdef"] is not False
        or r["provolatile"] != "s"
        or r["proowner"] != owner["relowner"]
        or r["lanname"] != "plpgsql"
        or r["returns"] != "boolean"
        or r["proconfig"] != ["search_path=pg_catalog, scope_review_issuer, design, pg_temp"]
    ):
        fail("NATIVE_METHOD_MISMATCH")
    sql = SQL_FILE.read_text(encoding="utf-8")
    for rpc, tag in zip(
        RPCS, ("verification_program_context", "verification_program_record"), strict=True
    ):
        parts = sql.split("$" + tag + "$")
        r = c.execute(
            "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns,pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",
            (rpc,),
        ).fetchone()
        if (
            len(parts) != 3
            or r is None
            or r["prosrc"] != parts[1]
            or r["prosecdef"] is not True
            or r["provolatile"] != "v"
            or r["proowner"] != owner["relowner"]
            or r["caller_owner"]
            or r["lanname"] != "plpgsql"
            or r["returns"] != "jsonb"
            or r["proconfig"]
            != ["search_path=pg_catalog, material_verification, design, pg_temp", "TimeZone=UTC"]
        ):
            fail("NATIVE_METHOD_MISMATCH")
    parts = sql.split("$verification_program_state$")
    helper = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns,has_function_privilege(session_user,p.oid,'EXECUTE') AS caller_exec FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('material_verification.program_state(uuid,text)')"
    ).fetchone()
    if (
        len(parts) != 3
        or helper is None
        or helper["prosrc"] != parts[1]
        or helper["prosecdef"] is not False
        or helper["provolatile"] != "v"
        or helper["proowner"] != owner["relowner"]
        or helper["lanname"] != "plpgsql"
        or helper["returns"] != "jsonb"
        or helper["caller_exec"]
        or helper["proconfig"]
        != ["search_path=pg_catalog, material_verification, design, pg_temp", "TimeZone=UTC"]
    ):
        fail("NATIVE_METHOD_MISMATCH")


def _execute(connection, query, args, *, write, expected_method_digest, validate):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        fail("IDLE_CONNECTION_REQUIRED")
    error_code = None
    try:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE"
                    if write
                    else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                c.execute("SET LOCAL statement_timeout='5s'")
                _audit(c)
                result = validate(c.execute(query, args).fetchone()["value"])
                if method_digest() != method:
                    fail("METHOD_CHANGED")
    except read_purpose.ReadPurposeError as error:
        error_code = "VERIFICATION_PROGRAM_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "VERIFICATION_PROGRAM_UNAVAILABLE"
        )
    if error_code:
        raise VerificationProgramError(error_code)
    return result


def _record(value):
    if type(value) is not dict or set(value) != {"document", "digest", "observation"}:
        fail("NATIVE_RESULT_INVALID")
    d = value["document"]
    if (
        type(d) is not dict
        or set(d)
        != UUID_FIELDS
        | SHA_FIELDS
        | FALSE_FIELDS
        | {
            "version",
            "origin",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
            "status",
            "review_status",
            "program_runtime_authenticated",
        }
        or d["version"] != "material-verification-program-result/1"
        or d["status"] != "program_verification_recorded"
        or d["program_runtime_authenticated"] is not True
        or any(d[k] is not False for k in FALSE_FIELDS)
        or not is_digest(value["digest"])
        or digest(d) != value["digest"]
        or len(canonical(d)) > 16384
        or any(not is_digest(d[k]) for k in SHA_FIELDS)
        or not _oid(d["recorded_by_oid"])
        or type(d["recorded_by"]) is not str
        or not 1 <= len(d["recorded_by"]) <= 63
        or type(d["origin"]) is not str
        or d["origin"] not in {"synthetic_mechanism", "current_prebid"}
        or type(d["review_status"]) is not str
        or d["review_status"]
        not in {
            "synthetic_review_only",
            "configured_review_confirmed",
            "review_incomplete",
            "scope_changes_requested",
        }
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in UUID_FIELDS:
        commands._uuid(d[k])
    _time(d["recorded_at"])
    obs = _observation(value["observation"])
    capsule = obs["verified_material"]
    if (
        d["observation_digest"] != obs["digest"]
        or d["command_id"] != obs["command_id"]
        or any(
            d[k] != obs[k]
            for k in (
                "command_digest",
                "program_method_digest",
                "port_method_digest",
                "controller_method_digest",
                "policy_digest",
            )
        )
        or d["context_digest"] != capsule.get("context_digest")
        or d["findings_digest"] != capsule.get("findings_digest")
        or d["review_status"] != capsule.get("status")
    ):
        fail("NATIVE_RESULT_INVALID")
    return NativeProgramResult(deepcopy(value) | {"native_program_identity_verified": True})


def _context(value):
    if type(value) is not dict or set(value) != {
        "command",
        "configuration",
        "review_arguments",
        "current",
        "result",
    }:
        fail("NATIVE_CONTEXT_INVALID")
    command = commands._record(value["command"])
    d = command.metadata["document"]
    cfg = value["configuration"]
    cfg_fields = {
        "profile_id",
        "case_id",
        "target_login",
        "target_login_oid",
        "origin",
        "controller_method_digest",
        "authority_policy_digest",
    }
    if type(cfg) is not dict or set(cfg) != cfg_fields or any(cfg[k] != d[k] for k in cfg_fields):
        fail("NATIVE_CONTEXT_INVALID")
    args = value["review_arguments"]
    if type(args) is not dict or set(args) != REVIEW_FIELDS:
        fail("NATIVE_CONTEXT_INVALID")
    for k in ("registration_command_id", "issuer_command_id", "bid_id", "scope_id"):
        commands._uuid(args[k])
    if any(
        not is_digest(args[k])
        for k in REVIEW_FIELDS
        - {"registration_command_id", "issuer_command_id", "bid_id", "scope_id"}
    ):
        fail("NATIVE_CONTEXT_INVALID")
    for key, target in (
        ("expected_registration_digest", "registration_digest"),
        ("expected_issuer_digest", "review_attestation_digest"),
        ("expected_context_digest", "context_digest"),
        ("expected_scope_digest", "scope_digest"),
        ("bid_id", "bid_id"),
        ("scope_id", "scope_id"),
    ):
        if args[key] != d[target]:
            fail("NATIVE_CONTEXT_INVALID")
    state = value["current"]
    bools = {
        "target_identity_matches",
        "program_configuration_current",
        "case_current",
        "review_current",
        "program_runtime_authenticated",
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
    }
    revisions = {
        "profile_head_revision",
        "case_head_revision",
        "review_profile_head_revision",
        "review_case_head_revision",
    }
    if (
        type(state) is not dict
        or set(state) != bools | revisions | {"observed_at"}
        or any(type(state[k]) is not bool for k in bools)
        or state["target_identity_matches"] is not True
        or state["program_runtime_authenticated"] is not True
        or any(
            state[k] is not False
            for k in (
                "necessary_scope_verified",
                "native_binding_verified",
                "input_authority_granted",
                "execution_authorized",
            )
        )
        or any(state[k] is not None and not commands._revision(state[k]) for k in revisions)
    ):
        fail("NATIVE_CONTEXT_INVALID")
    _time(state["observed_at"])
    prior = None if value["result"] is None else _record(value["result"])
    if prior is not None:
        r = prior.metadata["document"]
        if (
            r["command_row_id"] != d["record_id"]
            or r["command_digest"] != command.metadata["digest"]
            or any(
                r[k] != d[k]
                for k in (
                    "command_id",
                    "profile_id",
                    "case_id",
                    "bid_id",
                    "scope_id",
                    "scope_digest",
                    "context_digest",
                    "registration_id",
                    "registration_digest",
                    "review_attestation_id",
                    "review_attestation_digest",
                )
            )
            or r["recorded_by"] != cfg["target_login"]
            or r["recorded_by_oid"] != cfg["target_login_oid"]
        ):
            fail("NATIVE_CONTEXT_INVALID")
    metadata = {
        "version": "material-verification-program-context/1",
        "method_digest": method_digest(),
        **deepcopy(value),
    }
    return NativeProgramContext(command, prior, metadata | {"digest": digest(metadata)})


def context(connection, *, command_id, expected_command_digest, expected_method_digest):
    commands._uuid(command_id)
    if not is_digest(expected_command_digest):
        fail("DIGEST_INVALID")

    def validate(value):
        result = _context(value)
        d = result.command.metadata["document"]
        if (
            d["command_id"] != command_id
            or result.command.metadata["digest"] != expected_command_digest
        ):
            fail("NATIVE_CONTEXT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_verification.program_context(%s,%s) AS value",
        (command_id, expected_command_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def record_result(
    connection,
    *,
    command_id,
    expected_command_digest,
    observation,
    expected_observation_digest,
    expected_method_digest,
):
    commands._uuid(command_id)
    obs = _observation(observation)
    if (
        not is_digest(expected_command_digest)
        or obs["command_id"] != command_id
        or obs["command_digest"] != expected_command_digest
        or obs["digest"] != expected_observation_digest
        or obs["port_method_digest"] != method_digest()
        or obs["policy_digest"] != policy_digest()
    ):
        fail("OBSERVATION_BINDING_MISMATCH")

    def validate(value):
        result = _record(value)
        if result.metadata["observation"] != obs:
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_verification.record_program_result(%s,%s,%s) AS value",
        (command_id, expected_command_digest, Jsonb(obs)),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
