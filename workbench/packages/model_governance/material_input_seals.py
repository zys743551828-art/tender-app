"""Native sealed input references, never a reconstructed live capability."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_input_authority as authority
from packages.model_governance import material_verification_commands as commands
from packages.model_governance import material_verification_program as program
from packages.model_governance import package_scope_review_issuers as policy_source
from packages.model_governance import package_technical_material as material
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-input-seals.sql"
GROUP = "tender_material_input_seal"
RPCS = ("material_input_seal.seal(uuid,text,uuid,text,uuid)", "material_input_seal.read(uuid,text)")
UUID_FIELDS = frozenset(
    {
        "seal_id",
        "command_id",
        "profile_id",
        "verification_id",
        "authority_policy_id",
        "program_result_id",
        "registration_id",
        "storage_record_id",
        "bid_id",
        "scope_id",
    }
)
SHA_FIELDS = frozenset(
    {
        "profile_digest",
        "verification_digest",
        "authority_policy_digest",
        "program_result_digest",
        "registration_digest",
        "storage_record_digest",
        "storage_packet_digest",
        "context_object_digest",
        "findings_object_digest",
        "context_digest",
        "context_method_digest",
        "findings_digest",
        "input_method_digest",
        "material_input_digest",
        "seal_method_digest",
        "native_sql_method_digest",
        "scope_digest",
    }
)
TRUE_FIELDS = frozenset({"software_input_sealed", "native_binding_verified"})
ORIGIN_FIELDS = frozenset({"input_verified", "input_authority_granted"})
FALSE_FIELDS = frozenset(
    {
        "execution_authorized",
        "raw_judgment_executable",
        "formal_prediction_eligible",
        "historical_sample_eligible",
        "actual_human_reading_verified",
        "atomic_snapshot_verified",
        "send_lease_granted",
    }
)
KNOWN_ERRORS = frozenset(
    "INPUT_SEAL_" + s
    for s in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "VERIFICATION_NOT_FOUND",
        "PROFILE_MISMATCH",
        "CURRENT_STATE_UNAVAILABLE",
        "ALREADY_SEALED",
        "NOT_FOUND",
    )
)


class InputSealError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise InputSealError("INPUT_SEAL_" + code)


@dataclass(frozen=True, repr=False)
class NativeInputSeal:
    metadata: dict


@dataclass(frozen=True, repr=False)
class InputSealObservation:
    record: NativeInputSeal
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "material-input-seal-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "authority_method": authority.method_digest(),
            "material_input_source": sha(Path(material.__file__).read_bytes()),
            "policy_sql_source": sha(policy_source.SQL_FILE.read_bytes()),
            "purpose_source": sha(Path(read_purpose.__file__).read_bytes()),
            "grants_execution": False,
            "synthetic_origin_grants_input": False,
        }
    )


def _audit(c):
    read_purpose.require_read_purpose(
        c, read_purpose.ReadPurpose(groups=frozenset({GROUP}), definer_calls=RPCS)
    )
    owners = c.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='material_input_seal' AND c.relname IN('profiles','profile_heads','records')"
    ).fetchall()
    if (
        len(owners) != 3
        or len({r["relowner"] for r in owners}) != 1
        or any(r["relowner"] != r["nspowner"] for r in owners)
    ):
        fail("NATIVE_METHOD_MISMATCH")
    owner = owners[0]["relowner"]
    shared = policy_source.SQL_FILE.read_text(encoding="utf-8").split("$scope_issuer_policy$")
    rows = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname='scope_review_issuer' AND p.proname='role_policy' AND oidvectortypes(p.proargtypes)='name, text, text[]'"
    ).fetchall()
    if len(shared) != 3 or len(rows) != 1:
        fail("NATIVE_METHOD_MISMATCH")
    r = rows[0]
    if (
        r["prosrc"] != shared[1]
        or r["prosecdef"] is not False
        or r["provolatile"] != "s"
        or r["proowner"] != owner
        or r["lanname"] != "plpgsql"
        or r["returns"] != "boolean"
        or r["proconfig"] != ["search_path=pg_catalog, scope_review_issuer, design, pg_temp"]
    ):
        fail("NATIVE_METHOD_MISMATCH")
    sources = {
        "material_input_seal": SQL_FILE.read_text(encoding="utf-8"),
        "material_input_authority": authority.SQL_FILE.read_text(encoding="utf-8"),
    }
    specs = (
        (
            "material_input_seal",
            "seal",
            "uuid, text, uuid, text, uuid",
            "input_seal_write",
            True,
            "v",
            "jsonb",
            True,
        ),
        ("material_input_seal", "read", "uuid, text", "input_seal_read", True, "v", "jsonb", True),
        (
            "material_input_seal",
            "native_method_digest",
            "",
            "input_seal_method",
            False,
            "s",
            "text",
            False,
        ),
        (
            "material_input_seal",
            "current_context",
            "uuid, uuid",
            "input_seal_context",
            False,
            "v",
            "jsonb",
            False,
        ),
        (
            "material_input_authority",
            "qualify",
            "uuid, text, uuid, text, uuid",
            "input_authority_qualify",
            True,
            "v",
            "jsonb",
            False,
        ),
        (
            "material_input_authority",
            "read",
            "uuid, text",
            "input_authority_read",
            True,
            "v",
            "jsonb",
            False,
        ),
        (
            "material_input_authority",
            "native_method_digest",
            "",
            "input_authority_method",
            False,
            "s",
            "text",
            False,
        ),
        (
            "material_input_authority",
            "source_current",
            "uuid, uuid, text",
            "input_authority_source",
            False,
            "s",
            "boolean",
            False,
        ),
        (
            "material_input_authority",
            "policy_context",
            "uuid, uuid",
            "input_authority_context",
            False,
            "v",
            "jsonb",
            False,
        ),
    )
    for schema, name, args, tag, definer, volatility, returns, executable in specs:
        parts = sources[schema].split("$" + tag + "$")
        rows = c.execute(
            "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns,pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner,has_function_privilege(session_user,p.oid,'EXECUTE') AS caller_execute "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname=%s AND p.proname=%s AND oidvectortypes(p.proargtypes)=%s",
            (schema, name, args),
        ).fetchall()
        if len(parts) != 3 or len(rows) != 1:
            fail("NATIVE_METHOD_MISMATCH")
        r = rows[0]
        if (
            r["prosrc"] != parts[1]
            or r["prosecdef"] is not definer
            or r["provolatile"] != volatility
            or r["proowner"] != owner
            or r["caller_owner"]
            or r["lanname"] != "plpgsql"
            or r["returns"] != returns
            or r["caller_execute"] is not executable
            or r["proconfig"]
            != [f"search_path=pg_catalog, {schema}, design, pg_temp", "TimeZone=UTC"]
        ):
            fail("NATIVE_METHOD_MISMATCH")


def _input_for(document):
    d = document
    binding = {
        "version": "package-technical-verification-binding/3",
        "verification_id": d["verification_id"],
        "verification_receipt_digest": d["verification_digest"],
        "context_digest": d["context_digest"],
        "context_method_digest": d["context_method_digest"],
    }
    metadata = {
        "version": "package-technical-material-input/3",
        "context_digest": d["context_digest"],
        "input_method_digest": d["input_method_digest"],
        "binding_reference": binding,
        "binding_reference_digest": digest(binding),
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
    }
    return metadata | {"digest": digest(metadata)}


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
            "profile_head_revision",
            "authority_policy_revision",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
            "origin",
            "status",
            "material_input",
        }
        or len(canonical(value)) > 32768
        or d["version"] != "material-input-seal/1"
        or not is_digest(value["digest"])
        or digest(d) != value["digest"]
        or any(not is_digest(d[k]) for k in SHA_FIELDS)
        or type(d["origin"]) is not str
        or d["origin"] not in {"synthetic_mechanism", "current_prebid"}
        or any(d[k] is not True for k in TRUE_FIELDS)
        or any(d[k] is not False for k in FALSE_FIELDS)
        or not commands._revision(d["profile_head_revision"])
        or not commands._revision(d["authority_policy_revision"])
        or not program._oid(d["recorded_by_oid"])
        or type(d["recorded_by"]) is not str
        or not 1 <= len(d["recorded_by"]) <= 63
    ):
        fail("NATIVE_RESULT_INVALID")
    real = d["origin"] == "current_prebid"
    if (
        any(d[k] is not real for k in ORIGIN_FIELDS)
        or d["status"] != ("current_input_sealed" if real else "mechanism_input_sealed")
        or canonical(d["material_input"]) != canonical(_input_for(d))
        or d["material_input_digest"] != d["material_input"]["digest"]
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in UUID_FIELDS:
        commands._uuid(d[k])
    commands._time(d["recorded_at"])
    return NativeInputSeal(deepcopy(value))


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
        error_code = "INPUT_SEAL_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "INPUT_SEAL_UNAVAILABLE"
        )
    if error_code:
        raise InputSealError(error_code)
    return result


def seal(
    connection,
    *,
    verification_id,
    expected_verification_digest,
    profile_id,
    expected_profile_digest,
    command_id,
    expected_method_digest,
):
    for identifier in (verification_id, profile_id, command_id):
        commands._uuid(identifier)
    if not is_digest(expected_verification_digest) or not is_digest(expected_profile_digest):
        fail("DIGEST_INVALID")

    def validate(value):
        record = _record(value)
        d = record.metadata["document"]
        if (
            d["verification_id"] != verification_id
            or d["verification_digest"] != expected_verification_digest
            or d["profile_id"] != profile_id
            or d["profile_digest"] != expected_profile_digest
            or d["command_id"] != command_id
            or d["seal_method_digest"] != expected_method_digest
            or d["input_method_digest"] != material.method_digest()
            or d["context_method_digest"] != material.context_method_digest()
        ):
            fail("NATIVE_RESULT_INVALID")
        return record

    return _execute(
        connection,
        "SELECT material_input_seal.seal(%s,%s,%s,%s,%s) AS value",
        (
            verification_id,
            expected_verification_digest,
            profile_id,
            expected_profile_digest,
            command_id,
        ),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(connection, *, seal_id, expected_seal_digest, expected_method_digest):
    commands._uuid(seal_id)
    if not is_digest(expected_seal_digest):
        fail("DIGEST_INVALID")

    def validate(value):
        if type(value) is not dict or set(value) != {"record", "current"}:
            fail("NATIVE_RESULT_INVALID")
        record = _record(value["record"])
        d = record.metadata["document"]
        current = value["current"]
        flags = {
            "profile_current",
            "verification_current",
            "storage_current",
            "software_input_current",
            "current_input_verified",
        }
        blocked = {"execution_authorized", "send_lease_granted", "atomic_snapshot_verified"}
        if (
            d["seal_id"] != seal_id
            or record.metadata["digest"] != expected_seal_digest
            or type(current) is not dict
            or set(current) != flags | blocked | {"observed_at", "profile_head_revision"}
            or any(type(current[k]) is not bool for k in flags)
            or any(current[k] is not False for k in blocked)
            or (
                current["profile_head_revision"] is not None
                and not commands._revision(current["profile_head_revision"])
            )
        ):
            fail("NATIVE_RESULT_INVALID")
        commands._time(current["observed_at"])
        eligible = (
            all(current[k] for k in {"profile_current", "verification_current", "storage_current"})
            and current["profile_head_revision"] == d["profile_head_revision"]
        )
        if current["software_input_current"] is not eligible or current[
            "current_input_verified"
        ] is not (eligible and d["origin"] == "current_prebid"):
            fail("NATIVE_RESULT_INVALID")
        metadata = {
            "version": "material-input-seal-observation/1",
            "method_digest": method_digest(),
            **deepcopy(value),
        }
        return InputSealObservation(record, metadata | {"digest": digest(metadata)})

    return _execute(
        connection,
        "SELECT material_input_seal.read(%s,%s) AS value",
        (seal_id, expected_seal_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
