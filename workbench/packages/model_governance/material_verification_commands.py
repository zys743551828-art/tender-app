"""Durable pending verification commands, separate from program/input authority."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_native_evidence_issuers as issuers
from packages.model_governance import package_scope_review_issuers as policy_source
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

GROUP = "tender_material_verification_commands"
RPCS = (
    "material_verification.begin_command(uuid,uuid,text)",
    "material_verification.read_command(uuid,uuid,text)",
)
SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-verification-commands.sql"
UUID_FIELDS = frozenset(
    {
        "record_id",
        "case_id",
        "profile_id",
        "command_id",
        "bid_id",
        "scope_id",
        "registration_id",
        "review_attestation_id",
    }
)
SHA_FIELDS = frozenset(
    {
        "case_digest",
        "profile_digest",
        "scope_digest",
        "context_digest",
        "registration_digest",
        "review_attestation_digest",
        "controller_method_digest",
        "authority_policy_digest",
    }
)
FALSE_FIELDS = frozenset(
    {
        "controlled_program_executed",
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
    }
)
KNOWN_ERRORS = frozenset(
    "VERIFICATION_COMMAND_" + s
    for s in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "REFERENCE_INVALID",
        "CONFLICT",
        "CASE_UNAVAILABLE",
        "PROFILE_UNAVAILABLE",
        "REVIEW_UNAVAILABLE",
        "NOT_CURRENT_PREBID",
        "NOT_FOUND",
    )
)


class VerificationCommandError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise VerificationCommandError("VERIFICATION_COMMAND_" + code)


@dataclass(frozen=True, repr=False)
class NativeVerificationCommand:
    metadata: dict


@dataclass(frozen=True, repr=False)
class VerificationCommandObservation:
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "material-verification-command-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "issuer_method": issuers.method_digest(),
            "policy_sql_source": sha(policy_source.SQL_FILE.read_bytes()),
            "purpose_audit_source": sha(Path(read_purpose.__file__).read_bytes()),
            "authority_granted": False,
        }
    )


def _uuid(value):
    valid = False
    try:
        valid = type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        pass
    if not valid:
        fail("ID_INVALID")


def _time(value):
    valid = False
    try:
        valid = (
            type(value) is str
            and len(value) <= 40
            and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
        )
    except (ValueError, TypeError):
        pass
    if not valid:
        fail("NATIVE_RESULT_INVALID")


def _revision(value):
    return type(value) is int and 1 <= value <= 9007199254740991


def _audit(c):
    read_purpose.require_read_purpose(
        c, read_purpose.ReadPurpose(groups=frozenset({GROUP}), definer_calls=RPCS)
    )
    owner = c.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass('material_verification.commands')"
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
        RPCS, ("verification_command_begin", "verification_command_read"), strict=True
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
        error_code = "VERIFICATION_COMMAND_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "VERIFICATION_COMMAND_UNAVAILABLE"
        )
    if error_code:
        raise VerificationCommandError(error_code)
    return result


def _record(value):
    if type(value) is not dict or set(value) != {"document", "digest"}:
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
            "target_login",
            "target_login_oid",
            "origin",
            "profile_head_revision",
            "case_head_revision",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
            "status",
        }
        or len(canonical(value)) > 16384
        or d["version"] != "material-verification-command/1"
        or d["status"] != "pending_controlled_verification"
        or any(d[k] is not False for k in FALSE_FIELDS)
        or not is_digest(value["digest"])
        or value["digest"] != digest(d)
        or any(not is_digest(d[k]) for k in SHA_FIELDS)
        or type(d["origin"]) is not str
        or d["origin"] not in {"synthetic_mechanism", "current_prebid"}
        or any(
            type(d[k]) is not str or not 1 <= len(d[k]) <= 63
            for k in ("target_login", "recorded_by")
        )
        or type(d["target_login_oid"]) is not int
        or not 1 <= d["target_login_oid"] <= 4294967295
        or type(d["recorded_by_oid"]) is not int
        or not 1 <= d["recorded_by_oid"] <= 4294967295
        or any(not _revision(d[k]) for k in ("profile_head_revision", "case_head_revision"))
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in UUID_FIELDS:
        _uuid(d[k])
    _time(d["recorded_at"])
    return NativeVerificationCommand(deepcopy(value) | {"native_command_identity_verified": True})


def begin(connection, *, case_id, command_id, expected_case_digest, expected_method_digest):
    _uuid(case_id)
    _uuid(command_id)
    if not is_digest(expected_case_digest):
        fail("DIGEST_INVALID")

    def validate(value):
        result = _record(value)
        d = result.metadata["document"]
        if (
            d["case_id"] != case_id
            or d["command_id"] != command_id
            or d["case_digest"] != expected_case_digest
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_verification.begin_command(%s,%s,%s) AS value",
        (case_id, command_id, expected_case_digest),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(
    connection,
    *,
    case_id,
    command_id,
    expected_case_digest,
    expected_method_digest,
    expected_record_digest=None,
):
    _uuid(case_id)
    _uuid(command_id)
    if not is_digest(expected_case_digest) or (
        expected_record_digest is not None and not is_digest(expected_record_digest)
    ):
        fail("DIGEST_INVALID")

    def validate(value):
        if type(value) is not dict or set(value) != {"record", "current"}:
            fail("NATIVE_RESULT_INVALID")
        record = _record(value["record"])
        d = record.metadata["document"]
        if (
            d["case_id"] != case_id
            or d["command_id"] != command_id
            or d["case_digest"] != expected_case_digest
            or (
                expected_record_digest is not None
                and record.metadata["digest"] != expected_record_digest
            )
        ):
            fail("NATIVE_RESULT_INVALID")
        state = value["current"]
        fields = {
            "observed_at",
            "program_configuration_active",
            "case_active",
            "profile_head_revision",
            "case_head_revision",
            "program_runtime_authenticated",
        } | FALSE_FIELDS
        if (
            type(state) is not dict
            or set(state) != fields
            or any(
                type(state[k]) is not bool for k in ("program_configuration_active", "case_active")
            )
            or any(state[k] is not False for k in FALSE_FIELDS | {"program_runtime_authenticated"})
        ):
            fail("NATIVE_RESULT_INVALID")
        _time(state["observed_at"])
        for key, active in (
            ("profile_head_revision", "program_configuration_active"),
            ("case_head_revision", "case_active"),
        ):
            if (state[key] is None and state[active]) or (
                state[key] is not None and not _revision(state[key])
            ):
                fail("NATIVE_RESULT_INVALID")
        metadata = {
            "version": "material-verification-command-observation/1",
            "method_digest": method_digest(),
            **deepcopy(value),
        }
        return VerificationCommandObservation(metadata | {"digest": digest(metadata)})

    return _execute(
        connection,
        "SELECT material_verification.read_command(%s,%s,%s) AS value",
        (case_id, command_id, expected_case_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
