"""Independent configured issuer attestations; identity is not input authority.

Initializer-owned profiles/case grants are never created or repaired here. The
issuer cannot verify its own attestation through the independent verifier port.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_archive as archive
from packages.model_governance import package_material_registration as registration
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_scope_findings_store as findings_store
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

ISSUER_GROUP = "tender_scope_review_issuer"
VERIFY_GROUP = "tender_scope_review_verify"
ISSUE_RPC = "scope_review_issuer.attest(uuid,uuid,jsonb)"
READ_RPC = "scope_review_issuer.read(uuid,uuid,text)"
POLICY_RPC = "scope_review_issuer.role_policy(name,text,text[])"
SQL_FILE = Path(__file__).parents[2] / "deploy/sql/package-scope-review-issuers.sql"
REF_FIELDS = frozenset(
    {
        "context_digest",
        "review_digest",
        "findings_digest",
        "findings_commit_digest",
        "findings_method_digest",
        "findings_store_method_digest",
    }
)
KNOWN_ERRORS = frozenset(
    "SCOPE_ISSUER_" + code
    for code in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "PROFILE_UNAVAILABLE",
        "CASE_UNAVAILABLE",
        "CASE_REFERENCE_MISMATCH",
        "NOT_FOUND",
        "REFERENCE_STATE_INVALID",
    )
)


class ScopeIssuerError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise ScopeIssuerError("SCOPE_ISSUER_" + code)


@dataclass(frozen=True, repr=False)
class NativeIssuerRecord:
    metadata: dict


@dataclass(frozen=True, repr=False)
class NativeIssuerObservation:
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "package-scope-review-issuers-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "purpose_audit_source": sha(Path(read_purpose.__file__).read_bytes()),
            "registration_method": registration.method_digest(),
            "findings_method": findings.method_digest(),
            "findings_store_method": findings_store.method_digest(),
            "authority_grants": False,
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


def _reference(value):
    if (
        type(value) is not dict
        or set(value) != REF_FIELDS | {"version"}
        or value["version"] != "package-scope-review-attestation-reference/1"
        or any(not is_digest(value[k]) for k in REF_FIELDS)
    ):
        fail("REFERENCE_INVALID")


def stage_command(
    store,
    packet,
    *,
    case_id,
    command_id,
    findings_commit_digest,
    expected_findings_digest,
    expected_method_digest,
):
    if expected_method_digest != method_digest():
        fail("METHOD_MISMATCH")
    _uuid(case_id)
    _uuid(command_id)
    checked = findings_store.load(
        store,
        packet,
        commit_digest=findings_commit_digest,
        expected_findings_digest=expected_findings_digest,
        expected_method_digest=findings_store.method_digest(),
    )
    reference = {
        "version": "package-scope-review-attestation-reference/1",
        "context_digest": checked.metadata["context_digest"],
        "review_digest": checked.metadata["review_digest"],
        "findings_digest": expected_findings_digest,
        "findings_commit_digest": findings_commit_digest,
        "findings_method_digest": findings.method_digest(),
        "findings_store_method_digest": findings_store.method_digest(),
    }
    _reference(reference)
    command = {
        "version": "package-scope-review-attestation-command/1",
        "method_digest": expected_method_digest,
        "case_id": case_id,
        "command_id": command_id,
        "bid_id": packet.context.metadata["bid_id"],
        "scope_id": packet.context.metadata["scope_id"],
        "reference": reference,
    }
    return store.publish(canonical(command))


def _command(store, key):
    raw = store.get_commit(key)
    if len(raw) > 8192:
        fail("COMMAND_INVALID")
    command = archive._decode(raw)
    if (
        set(command)
        != {"version", "method_digest", "case_id", "command_id", "bid_id", "scope_id", "reference"}
        or command["version"] != "package-scope-review-attestation-command/1"
        or command["method_digest"] != method_digest()
    ):
        fail("COMMAND_INVALID")
    _uuid(command["case_id"])
    _uuid(command["command_id"])
    _uuid(command["bid_id"])
    _uuid(command["scope_id"])
    _reference(command["reference"])
    if (
        command["reference"]["findings_method_digest"] != findings.method_digest()
        or command["reference"]["findings_store_method_digest"] != findings_store.method_digest()
    ):
        fail("COMMAND_INVALID")
    return command


def _audit(c, group, rpc):
    read_purpose.require_read_purpose(
        c, read_purpose.ReadPurpose(groups=frozenset({group}), definer_calls=(rpc,))
    )
    sql = SQL_FILE.read_text(encoding="utf-8")
    owner = c.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass('scope_review_issuer.profiles')"
    ).fetchone()
    if owner is None or owner["relowner"] != owner["nspowner"]:
        fail("NATIVE_METHOD_MISMATCH")
    for name, tag, definer, volatility, returns in (
        (POLICY_RPC, "scope_issuer_policy", False, "s", "boolean"),
        (ISSUE_RPC, "scope_issuer_attest", True, "v", "jsonb"),
        (READ_RPC, "scope_issuer_read", True, "v", "jsonb"),
    ):
        parts = sql.split("$" + tag + "$")
        row = c.execute(
            "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns,pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",
            (name,),
        ).fetchone()
        config = ["search_path=pg_catalog, scope_review_issuer, design, pg_temp"] + (
            ["TimeZone=UTC"] if definer else []
        )
        if (
            len(parts) != 3
            or row is None
            or row["prosrc"] != parts[1]
            or row["prosecdef"] is not definer
            or row["provolatile"] != volatility
            or row["lanname"] != "plpgsql"
            or row["returns"] != returns
            or row["caller_owner"]
            or row["proowner"] != owner["relowner"]
            or row["proconfig"] != config
        ):
            fail("NATIVE_METHOD_MISMATCH")


def _record(value):
    if type(value) is not dict or set(value) != {"document", "digest"}:
        fail("NATIVE_RESULT_INVALID")
    d = value["document"]
    fields = {
        "version",
        "attestation_id",
        "case_id",
        "command_id",
        "profile_id",
        "subject_id",
        "issuer_kind",
        "issuer_origin",
        "authority_policy_digest",
        "profile_digest",
        "case_digest",
        "registration_id",
        "registration_digest",
        "bid_id",
        "scope_id",
        "recorded_by",
        "recorded_at",
        "reference",
        "status",
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
    }
    if (
        type(d) is not dict
        or set(d) != fields
        or len(canonical(value)) > 16384
        or d["version"] != "package-native-scope-review-attestation/1"
        or d["status"] != "issuer_attestation_recorded"
        or not is_digest(value["digest"])
        or digest(d) != value["digest"]
    ):
        fail("NATIVE_RESULT_INVALID")
    for name in (
        "attestation_id",
        "case_id",
        "command_id",
        "profile_id",
        "subject_id",
        "registration_id",
        "bid_id",
        "scope_id",
    ):
        _uuid(d[name])
    for name in ("authority_policy_digest", "profile_digest", "case_digest", "registration_digest"):
        if not is_digest(d[name]):
            fail("NATIVE_RESULT_INVALID")
    if (
        type(d["issuer_kind"]) is not str
        or d["issuer_kind"] not in {"human", "controlled_program", "external_receipt"}
        or type(d["issuer_origin"]) is not str
        or d["issuer_origin"] not in {"synthetic_mechanism", "current_prebid"}
        or type(d["recorded_by"]) is not str
        or not 1 <= len(d["recorded_by"]) <= 63
        or any(
            d[name] is not False
            for name in (
                "necessary_scope_verified",
                "native_binding_verified",
                "input_authority_granted",
                "execution_authorized",
            )
        )
    ):
        fail("NATIVE_RESULT_INVALID")
    valid = False
    try:
        valid = (
            type(d["recorded_at"]) is str
            and len(d["recorded_at"]) <= 40
            and datetime.fromisoformat(d["recorded_at"].replace("Z", "+00:00")).tzinfo is not None
        )
    except (ValueError, TypeError):
        pass
    if not valid:
        fail("NATIVE_RESULT_INVALID")
    _reference(d["reference"])
    return value


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
                _audit(c, ISSUER_GROUP if write else VERIFY_GROUP, ISSUE_RPC if write else READ_RPC)
                value = c.execute(query, args).fetchone()["value"]
                checked = validate(value)
                if method_digest() != method:
                    fail("METHOD_CHANGED")
    except read_purpose.ReadPurposeError as error:
        error_code = "SCOPE_ISSUER_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "SCOPE_ISSUER_NATIVE_UNAVAILABLE"
        )
    if error_code:
        raise ScopeIssuerError(error_code)
    return checked


def attest(connection, store, *, command_commit_digest, expected_method_digest):
    command = _command(store, command_commit_digest)

    def validate(value):
        checked = _record(value)
        d = checked["document"]
        if (
            d["case_id"] != command["case_id"]
            or d["command_id"] != command["command_id"]
            or d["bid_id"] != command["bid_id"]
            or d["scope_id"] != command["scope_id"]
            or canonical(d["reference"]) != canonical(command["reference"])
        ):
            fail("NATIVE_RESULT_INVALID")
        return NativeIssuerRecord(
            deepcopy(checked) | {"native_issuer_record_identity_verified": True}
        )

    return _execute(
        connection,
        "SELECT scope_review_issuer.attest(%s,%s,%s) AS value",
        (command["case_id"], command["command_id"], Jsonb(command["reference"])),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(
    connection,
    *,
    bid_id,
    command_id,
    expected_reference_digest,
    expected_method_digest,
    expected_record_digest=None,
):
    _uuid(bid_id)
    _uuid(command_id)
    if not is_digest(expected_reference_digest) or (
        expected_record_digest is not None and not is_digest(expected_record_digest)
    ):
        fail("DIGEST_INVALID")

    def validate(value):
        if type(value) is not dict or set(value) != {"record", "current"}:
            fail("NATIVE_RESULT_INVALID")
        record = _record(value["record"])
        d = record["document"]
        if (
            d["bid_id"] != bid_id
            or d["command_id"] != command_id
            or digest(d["reference"]) != expected_reference_digest
            or (expected_record_digest is not None and record["digest"] != expected_record_digest)
        ):
            fail("NATIVE_RESULT_INVALID")
        state = value["current"]
        fields = {
            "observed_at",
            "issuer_active",
            "case_active",
            "profile_head_revision",
            "case_head_revision",
            "configured_issuer_identity_verified",
            "current_business_sources_rechecked",
            "necessary_scope_verified",
            "native_binding_verified",
            "input_authority_granted",
            "execution_authorized",
        }
        if (
            type(state) is not dict
            or set(state) != fields
            or any(type(state[k]) is not bool for k in ("issuer_active", "case_active"))
            or state["configured_issuer_identity_verified"] is not True
            or any(
                state[k] is not False
                for k in (
                    "current_business_sources_rechecked",
                    "necessary_scope_verified",
                    "native_binding_verified",
                    "input_authority_granted",
                    "execution_authorized",
                )
            )
        ):
            fail("NATIVE_RESULT_INVALID")
        valid_time = False
        try:
            at = state["observed_at"]
            valid_time = (
                type(at) is str
                and len(at) <= 40
                and datetime.fromisoformat(at.replace("Z", "+00:00")).tzinfo is not None
            )
        except (ValueError, TypeError):
            pass
        if not valid_time:
            fail("NATIVE_RESULT_INVALID")
        for key, active in (
            ("profile_head_revision", "issuer_active"),
            ("case_head_revision", "case_active"),
        ):
            revision = state[key]
            if (revision is None and state[active] is True) or (
                revision is not None
                and (type(revision) is not int or not 1 <= revision <= 9_007_199_254_740_991)
            ):
                fail("NATIVE_RESULT_INVALID")
        metadata = {
            "version": "package-native-scope-review-issuer-observation/1",
            "method_digest": method_digest(),
            **deepcopy(value),
        }
        return NativeIssuerObservation(metadata | {"digest": digest(metadata)})

    return _execute(
        connection,
        "SELECT scope_review_issuer.read(%s,%s,%s) AS value",
        (bid_id, command_id, expected_reference_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
