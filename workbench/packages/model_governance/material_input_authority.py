"""Independent native qualification of fixed program facts under an approved policy."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_verification_commands as commands
from packages.model_governance import material_verification_program as program
from packages.model_governance import package_scope_review_issuers as policy_source
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-input-authority.sql"
GROUP = "tender_material_input_verify"
RPCS = (
    "material_input_authority.qualify(uuid,text,uuid,text,uuid)",
    "material_input_authority.read(uuid,text)",
)
UUID_FIELDS = frozenset(
    {
        "verification_id",
        "command_id",
        "program_result_id",
        "policy_id",
        "bid_id",
        "scope_id",
        "program_profile_id",
        "program_case_id",
        "program_command_row_id",
        "registration_id",
        "review_attestation_id",
    }
)
SHA_FIELDS = frozenset(
    {
        "program_result_digest",
        "policy_digest",
        "scope_digest",
        "context_digest",
        "context_method_digest",
        "findings_digest",
        "program_command_digest",
        "registration_digest",
        "review_attestation_digest",
        "verifier_method_digest",
        "native_sql_method_digest",
    }
)
TRUE_FIELDS = frozenset(
    {
        "software_input_verified",
        "necessary_scope_policy_accepted",
        "native_binding_verified",
    }
)
ORIGIN_FIELDS = frozenset({"necessary_scope_verified", "input_verified", "input_authority_granted"})
FALSE_FIELDS = frozenset(
    {
        "execution_authorized",
        "raw_judgment_executable",
        "uncalibrated_numeric_eligible",
        "formal_prediction_eligible",
        "historical_sample_eligible",
        "actual_human_reading_verified",
        "historical_existence_verified",
        "atomic_snapshot_verified",
        "send_lease_granted",
    }
)
CURRENT_FLAGS = frozenset(
    {
        "policy_current",
        "program_current",
        "review_current",
        "source_current",
        "fingerprints_match",
        "complete_findings_confirmed",
        "software_input_current",
        "current_input_verified",
    }
)
KNOWN_ERRORS = frozenset(
    "INPUT_AUTHORITY_" + s
    for s in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "PROGRAM_RESULT_NOT_FOUND",
        "POLICY_MISMATCH",
        "VERIFIER_IDENTITY_MISMATCH",
        "CURRENT_STATE_UNAVAILABLE",
        "APPROVED_METHOD_MISMATCH",
        "REVIEW_INCOMPLETE",
        "ALREADY_VERIFIED",
        "NOT_FOUND",
    )
)


class InputAuthorityError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise InputAuthorityError("INPUT_AUTHORITY_" + code)


@dataclass(frozen=True, repr=False)
class NativeInputVerification:
    metadata: dict
    binding: dict


@dataclass(frozen=True, repr=False)
class InputVerificationObservation:
    record: NativeInputVerification
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "material-input-authority-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "program_port_method": program.method_digest(),
            "policy_sql_source": sha(policy_source.SQL_FILE.read_bytes()),
            "purpose_source": sha(Path(read_purpose.__file__).read_bytes()),
            "synthetic_origin_grants_input": False,
        }
    )


def _audit(c):
    read_purpose.require_read_purpose(
        c, read_purpose.ReadPurpose(groups=frozenset({GROUP}), definer_calls=RPCS)
    )
    owners = c.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='material_input_authority' AND c.relname IN('policies','policy_heads','verifications')"
    ).fetchall()
    if (
        len(owners) != 3
        or len({r["relowner"] for r in owners}) != 1
        or any(r["relowner"] != r["nspowner"] for r in owners)
    ):
        fail("NATIVE_METHOD_MISMATCH")
    owner = owners[0]["relowner"]
    policy = policy_source.SQL_FILE.read_text(encoding="utf-8").split("$scope_issuer_policy$")
    shared = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang "
        "WHERE n.nspname='scope_review_issuer' AND p.proname='role_policy' AND oidvectortypes(p.proargtypes)='name, text, text[]'"
    ).fetchall()
    if len(policy) != 3 or len(shared) != 1:
        fail("NATIVE_METHOD_MISMATCH")
    r = shared[0]
    if (
        r["prosrc"] != policy[1]
        or r["prosecdef"] is not False
        or r["provolatile"] != "s"
        or r["proowner"] != owner
        or r["lanname"] != "plpgsql"
        or r["returns"] != "boolean"
        or r["proconfig"] != ["search_path=pg_catalog, scope_review_issuer, design, pg_temp"]
    ):
        fail("NATIVE_METHOD_MISMATCH")
    source = SQL_FILE.read_text(encoding="utf-8")
    specs = (
        (RPCS[0], "qualify", True, "v", "jsonb"),
        (RPCS[1], "read", True, "v", "jsonb"),
        ("material_input_authority.native_method_digest()", "method", False, "s", "text"),
        (
            "material_input_authority.source_current(uuid,uuid,text)",
            "source",
            False,
            "s",
            "boolean",
        ),
        ("material_input_authority.policy_context(uuid,uuid)", "context", False, "v", "jsonb"),
    )
    for signature, tag, definer, volatility, returns in specs:
        parts = source.split("$input_authority_" + tag + "$")
        row = c.execute(
            "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns,"
            "pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner,has_function_privilege(session_user,p.oid,'EXECUTE') AS caller_execute "
            "FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",
            (signature,),
        ).fetchone()
        if (
            len(parts) != 3
            or row is None
            or row["prosrc"] != parts[1]
            or row["prosecdef"] is not definer
            or row["provolatile"] != volatility
            or row["proowner"] != owner
            or row["caller_owner"]
            or row["lanname"] != "plpgsql"
            or row["returns"] != returns
            or row["caller_execute"] is not definer
            or row["proconfig"]
            != ["search_path=pg_catalog, material_input_authority, design, pg_temp", "TimeZone=UTC"]
        ):
            fail("NATIVE_METHOD_MISMATCH")


def _record(value):
    if type(value) is not dict or set(value) != {"document", "digest"}:
        fail("NATIVE_RESULT_INVALID")
    d = value["document"]
    if (
        type(d) is not dict
        or set(d)
        != UUID_FIELDS
        | SHA_FIELDS
        | TRUE_FIELDS
        | ORIGIN_FIELDS
        | FALSE_FIELDS
        | {
            "version",
            "origin",
            "policy_head_revision",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
            "status",
        }
        or len(canonical(value)) > 16384
        or d["version"] != "material-input-verification/1"
        or not is_digest(value["digest"])
        or value["digest"] != digest(d)
        or any(not is_digest(d[k]) for k in SHA_FIELDS)
        or type(d["origin"]) is not str
        or d["origin"] not in {"synthetic_mechanism", "current_prebid"}
        or any(d[k] is not True for k in TRUE_FIELDS)
        or any(d[k] is not False for k in FALSE_FIELDS)
        or not commands._revision(d["policy_head_revision"])
        or not program._oid(d["recorded_by_oid"])
        or type(d["recorded_by"]) is not str
        or not 1 <= len(d["recorded_by"]) <= 63
    ):
        fail("NATIVE_RESULT_INVALID")
    real = d["origin"] == "current_prebid"
    if any(d[k] is not real for k in ORIGIN_FIELDS) or d["status"] != (
        "current_input_verified" if real else "mechanism_input_verified"
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in UUID_FIELDS:
        commands._uuid(d[k])
    commands._time(d["recorded_at"])
    binding = {
        "version": "package-technical-verification-binding/3",
        "verification_id": d["verification_id"],
        "verification_receipt_digest": value["digest"],
        "context_digest": d["context_digest"],
        "context_method_digest": d["context_method_digest"],
    }
    return NativeInputVerification(deepcopy(value), binding)


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
        error_code = "INPUT_AUTHORITY_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "INPUT_AUTHORITY_UNAVAILABLE"
        )
    if error_code:
        raise InputAuthorityError(error_code)
    return result


def qualify(
    connection,
    *,
    program_result_id,
    expected_program_result_digest,
    policy_id,
    expected_policy_digest,
    command_id,
    expected_method_digest,
):
    for identifier in (program_result_id, policy_id, command_id):
        commands._uuid(identifier)
    if not is_digest(expected_program_result_digest) or not is_digest(expected_policy_digest):
        fail("DIGEST_INVALID")

    def validate(value):
        record = _record(value)
        d = record.metadata["document"]
        if (
            d["program_result_id"] != program_result_id
            or d["program_result_digest"] != expected_program_result_digest
            or d["policy_id"] != policy_id
            or d["policy_digest"] != expected_policy_digest
            or d["command_id"] != command_id
            or d["verifier_method_digest"] != expected_method_digest
        ):
            fail("NATIVE_RESULT_INVALID")
        return record

    return _execute(
        connection,
        "SELECT material_input_authority.qualify(%s,%s,%s,%s,%s) AS value",
        (
            program_result_id,
            expected_program_result_digest,
            policy_id,
            expected_policy_digest,
            command_id,
        ),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(connection, *, verification_id, expected_verification_digest, expected_method_digest):
    commands._uuid(verification_id)
    if not is_digest(expected_verification_digest):
        fail("DIGEST_INVALID")

    def validate(value):
        if type(value) is not dict or set(value) != {"record", "current"}:
            fail("NATIVE_RESULT_INVALID")
        record = _record(value["record"])
        if (
            record.metadata["digest"] != expected_verification_digest
            or record.metadata["document"]["verification_id"] != verification_id
        ):
            fail("NATIVE_RESULT_INVALID")
        current = value["current"]
        blocked = {"execution_authorized", "send_lease_granted", "atomic_snapshot_verified"}
        if (
            type(current) is not dict
            or set(current) != CURRENT_FLAGS | blocked | {"observed_at", "policy_head_revision"}
            or any(type(current[k]) is not bool for k in CURRENT_FLAGS)
            or any(current[k] is not False for k in blocked)
            or (
                current["policy_head_revision"] is not None
                and not commands._revision(current["policy_head_revision"])
            )
        ):
            fail("NATIVE_RESULT_INVALID")
        commands._time(current["observed_at"])
        eligible = all(
            current[k] for k in CURRENT_FLAGS - {"software_input_current", "current_input_verified"}
        ) and (
            current["policy_head_revision"] == record.metadata["document"]["policy_head_revision"]
        )
        if current["software_input_current"] is not eligible or current[
            "current_input_verified"
        ] is not (eligible and record.metadata["document"]["origin"] == "current_prebid"):
            fail("NATIVE_RESULT_INVALID")
        metadata = {
            "version": "material-input-verification-observation/1",
            "method_digest": method_digest(),
            **deepcopy(value),
        }
        return InputVerificationObservation(record, metadata | {"digest": digest(metadata)})

    return _execute(
        connection,
        "SELECT material_input_authority.read(%s,%s) AS value",
        (verification_id, expected_verification_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
