"""Pending native-evidence registration v2; no fabricated v1 CAS references."""

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
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_native_material_recovery as recovery
from packages.model_governance import package_native_material_store as store
from packages.model_governance import package_scope_review_issuers as policy_source
from packages.model_governance import package_technical_material as material
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

GROUP = "tender_native_material_registration"
RPCS = (
    "material_registration.record_native(uuid,uuid,text,uuid,jsonb,jsonb)",
    "material_registration.read_native(uuid,uuid,text)",
)
SQL_FILE = Path(__file__).parents[2] / "deploy/sql/package-native-evidence-registration.sql"
ROOTS = frozenset(
    {
        "context_digest",
        "context_method_digest",
        "storage_record_digest",
        "storage_packet_digest",
        "native_recovery_method_digest",
        "native_recovery_observation_digest",
        "source_observation_digest",
        "material_digest",
        "findings_digest",
        "derivation_observation_digest",
        "registration_method_digest",
    }
)
FALSE_FIELDS = frozenset(
    {
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
    }
)
OBS_ROOTS = frozenset(
    {
        "method_digest",
        "storage_record_digest",
        "store_packet_digest",
        "context_digest",
        "original_source_observation_digest",
        "stored_findings_digest",
        "stored_derivation_observation_digest",
        "fresh_initial_parse_digest",
        "fresh_final_parse_digest",
        "fresh_final_scope_digest",
        "fresh_original_set_digest",
        "digest",
    }
)
OBS_TRUE = frozenset(
    {
        "native_evidence_bytes_reloaded",
        "exact_frozen_context_recovered",
        "current_native_parse_and_originals_rechecked",
        "stored_scope_findings_revalidated",
        "stored_derivation_claim_consistent",
    }
)
OBS_FALSE = FALSE_FIELDS | {
    "historical_existence_verified",
    "page_assets_rerendered",
    "trusted_derivation_freshly_verified",
    "actual_human_reading_verified",
    "atomic_snapshot_verified",
    "send_lease_granted",
}
OBS_BOOLS = frozenset({"all_findings_claimed_confirmed", "scope_changes_requested"})
KNOWN_ERRORS = frozenset(
    "NATIVE_REGISTRATION_" + s
    for s in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "PACKET_INVALID",
        "OBSERVATION_INVALID",
        "COMMAND_CONFLICT",
        "SCOPE_MISMATCH",
        "STORAGE_MISMATCH",
        "NOT_FOUND",
    )
)


class NativeEvidenceRegistrationError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise NativeEvidenceRegistrationError("NATIVE_REGISTRATION_" + code)


@dataclass(frozen=True, repr=False)
class NativeEvidenceRegistration:
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "package-native-evidence-registration-method/2",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "recovery_method": recovery.method_digest(),
            "store_method": store.method_digest(),
            "policy_sql_source": sha(policy_source.SQL_FILE.read_bytes()),
            "purpose_audit_source": sha(Path(read_purpose.__file__).read_bytes()),
            "qualification_granted": False,
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


def _packet(value):
    if (
        type(value) is not dict
        or set(value) != ROOTS | {"version", "storage_record_id"}
        or value["version"] != "package-native-material-registration-packet/2"
        or any(not is_digest(value[k]) for k in ROOTS)
    ):
        fail("PACKET_INVALID")
    _uuid(value["storage_record_id"])


def _observation(value, packet):
    if (
        type(value) is not dict
        or set(value)
        != OBS_ROOTS
        | OBS_TRUE
        | OBS_FALSE
        | OBS_BOOLS
        | {"version", "storage_record_id", "store_command_id", "observed_at"}
        or any(not is_digest(value[k]) for k in OBS_ROOTS)
        or any(type(value[k]) is not bool for k in OBS_BOOLS)
        or len(canonical(value)) > 8192
        or value.get("version") != "package-native-material-evidence-recovery/1"
        or value.get("digest") != packet["native_recovery_observation_digest"]
        or digest({k: v for k, v in value.items() if k != "digest"}) != value.get("digest")
    ):
        fail("OBSERVATION_INVALID")
    _uuid(value["store_command_id"])
    _uuid(value["storage_record_id"])
    valid_time = False
    try:
        at = value["observed_at"]
        valid_time = (
            type(at) is str
            and len(at) <= 40
            and datetime.fromisoformat(at.replace("Z", "+00:00")).tzinfo is not None
        )
    except (ValueError, TypeError):
        pass
    if not valid_time:
        fail("OBSERVATION_INVALID")
    equal = {
        "method_digest": "native_recovery_method_digest",
        "storage_record_id": "storage_record_id",
        "storage_record_digest": "storage_record_digest",
        "store_packet_digest": "storage_packet_digest",
        "context_digest": "context_digest",
        "original_source_observation_digest": "source_observation_digest",
        "stored_findings_digest": "findings_digest",
        "stored_derivation_observation_digest": "derivation_observation_digest",
    }
    if any(value.get(k) != packet[v] for k, v in equal.items()):
        fail("OBSERVATION_INVALID")
    if any(
        value.get(k) is not True
        for k in (
            "native_evidence_bytes_reloaded",
            "exact_frozen_context_recovered",
            "current_native_parse_and_originals_rechecked",
            "stored_scope_findings_revalidated",
            "stored_derivation_claim_consistent",
        )
    ):
        fail("OBSERVATION_INVALID")
    if any(
        value.get(k) is not False
        for k in FALSE_FIELDS
        | {
            "historical_existence_verified",
            "page_assets_rerendered",
            "trusted_derivation_freshly_verified",
            "actual_human_reading_verified",
            "atomic_snapshot_verified",
            "send_lease_granted",
        }
    ):
        fail("OBSERVATION_INVALID")
    return deepcopy(value)


def packet_for(
    recovered,
    *,
    expected_context_digest,
    expected_storage_record_digest,
    expected_recovery_observation_digest,
):
    if type(recovered) is not recovery.RecoveredNativeEvidence:
        fail("CURRENT_RECOVERY_REQUIRED")
    context = material.verify_context(recovered.context, expected_context_digest)
    checked = findings.verify(
        recovered.findings, expected_digest=recovered.findings.metadata["digest"]
    )
    record = store._record({k: recovered.stored_record.metadata[k] for k in ("document", "digest")})
    m = deepcopy(recovered.metadata)
    d = record.metadata["document"]
    p = d["packet"]
    if (
        record.metadata["digest"] != expected_storage_record_digest
        or checked.metadata["context_digest"] != expected_context_digest
        or checked.metadata["digest"] != p["findings_digest"]
        or d["scope_digest"] != context.metadata["scope_digest"]
        or any(d[k] != context.metadata[k] for k in ("bid_id", "scope_id"))
        or m.get("digest") != expected_recovery_observation_digest
        or m.get("method_digest") != recovery.method_digest()
        or m.get("all_findings_claimed_confirmed")
        is not checked.metadata["all_findings_claimed_confirmed"]
        or m.get("scope_changes_requested") is not checked.metadata["scope_changes_requested"]
    ):
        fail("RECOVERY_BINDING_MISMATCH")
    packet = {
        "version": "package-native-material-registration-packet/2",
        "context_digest": expected_context_digest,
        "context_method_digest": material.context_method_digest(),
        "storage_record_id": d["record_id"],
        "storage_record_digest": expected_storage_record_digest,
        "storage_packet_digest": d["packet_digest"],
        "native_recovery_method_digest": recovery.method_digest(),
        "native_recovery_observation_digest": expected_recovery_observation_digest,
        "source_observation_digest": context.metadata["source_observation_digest"],
        "material_digest": context.metadata["source_material_digest"],
        "findings_digest": checked.metadata["digest"],
        "derivation_observation_digest": p["derivation_observation_digest"],
        "registration_method_digest": method_digest(),
    }
    _packet(packet)
    _observation(m, packet)
    return packet


def _audit(c):
    read_purpose.require_read_purpose(
        c, read_purpose.ReadPurpose(groups=frozenset({GROUP}), definer_calls=RPCS)
    )
    owner = c.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass('material_registration.records')"
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
        RPCS, ("native_evidence_registration", "native_evidence_registration_read"), strict=True
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
            != ["search_path=pg_catalog, material_registration, design, pg_temp", "TimeZone=UTC"]
        ):
            fail("NATIVE_METHOD_MISMATCH")


def _record(value):
    if type(value) is not dict or set(value) != {"document", "digest"}:
        fail("NATIVE_RESULT_INVALID")
    d = value["document"]
    if (
        type(d) is not dict
        or set(d)
        != FALSE_FIELDS
        | {
            "version",
            "registration_id",
            "bid_id",
            "scope_id",
            "scope_digest",
            "command_id",
            "recorded_by",
            "recorded_at",
            "packet",
            "packet_digest",
            "recovery_observation",
            "status",
        }
        or d["version"] != "package-native-material-registration/2"
        or d["status"] != "awaiting_independent_verification"
        or any(d[k] is not False for k in FALSE_FIELDS)
        or not is_digest(value["digest"])
        or digest(d) != value["digest"]
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in ("registration_id", "bid_id", "scope_id", "command_id"):
        _uuid(d[k])
    if (
        not is_digest(d["scope_digest"])
        or not is_digest(d["packet_digest"])
        or digest(d["packet"]) != d["packet_digest"]
        or type(d["recorded_by"]) is not str
        or not 1 <= len(d["recorded_by"]) <= 63
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
    _packet(d["packet"])
    _observation(d["recovery_observation"], d["packet"])
    return NativeEvidenceRegistration(deepcopy(value) | {"native_record_identity_verified": True})


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
        error_code = "NATIVE_REGISTRATION_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "NATIVE_REGISTRATION_UNAVAILABLE"
        )
    if error_code:
        raise NativeEvidenceRegistrationError(error_code)
    return result


def record(
    connection,
    recovered,
    *,
    command_id,
    expected_context_digest,
    expected_storage_record_digest,
    expected_recovery_observation_digest,
    expected_method_digest,
):
    _uuid(command_id)
    if expected_method_digest != method_digest():
        fail("METHOD_MISMATCH")
    packet = packet_for(
        recovered,
        expected_context_digest=expected_context_digest,
        expected_storage_record_digest=expected_storage_record_digest,
        expected_recovery_observation_digest=expected_recovery_observation_digest,
    )
    observation = deepcopy(recovered.metadata)
    context = recovered.context.metadata

    def validate(value):
        result = _record(value)
        d = result.metadata["document"]
        if (
            d["packet"] != packet
            or d["recovery_observation"] != observation
            or d["command_id"] != command_id
            or any(d[k] != context[k] for k in ("bid_id", "scope_id", "scope_digest"))
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_registration.record_native(%s,%s,%s,%s,%s,%s) AS value",
        (
            context["bid_id"],
            context["scope_id"],
            context["scope_digest"],
            command_id,
            Jsonb(packet),
            Jsonb(observation),
        ),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(
    connection,
    *,
    bid_id,
    command_id,
    expected_packet_digest,
    expected_method_digest,
    expected_record_digest=None,
):
    _uuid(bid_id)
    _uuid(command_id)
    if not is_digest(expected_packet_digest) or (
        expected_record_digest is not None and not is_digest(expected_record_digest)
    ):
        fail("DIGEST_INVALID")

    def validate(value):
        result = _record(value)
        d = result.metadata["document"]
        if (
            d["bid_id"] != bid_id
            or d["command_id"] != command_id
            or d["packet_digest"] != expected_packet_digest
            or (
                expected_record_digest is not None
                and result.metadata["digest"] != expected_record_digest
            )
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_registration.read_native(%s,%s,%s) AS value",
        (bid_id, command_id, expected_packet_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
