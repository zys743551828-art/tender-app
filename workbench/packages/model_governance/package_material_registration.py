"""Native immutable pending-reference registry; never an input verification grant."""

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
from packages.model_governance import package_material_recovery as recovery
from packages.model_governance import package_technical_material as material
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

GROUP = "tender_material_registration"
RPCS = (
    "material_registration.record(uuid,uuid,text,uuid,jsonb)",
    "material_registration.read(uuid,uuid,text)",
)
SQL_FILE = Path(__file__).parents[2] / "deploy/sql/package-material-registration.sql"
PACKET_FIELDS = frozenset(
    {
        "context_digest",
        "context_method_digest",
        "recovery_commit_digest",
        "recovery_method_digest",
        "recovery_observation_digest",
        "source_observation_digest",
        "material_digest",
        "registration_method_digest",
    }
)
KNOWN_ERRORS = frozenset(
    "MATERIAL_REGISTRATION_" + code
    for code in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "PACKET_INVALID",
        "COMMAND_CONFLICT",
        "SCOPE_MISMATCH",
        "NOT_FOUND",
    )
)


class MaterialRegistrationError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise MaterialRegistrationError("MATERIAL_REGISTRATION_" + code)


@dataclass(frozen=True, repr=False)
class PendingMaterialRegistration:
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "package-material-registration-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "purpose_audit_source": sha(Path(read_purpose.__file__).read_bytes()),
            "recovery_method": recovery.method_digest(),
            "context_method": material.context_method_digest(),
            "status": "awaiting_independent_verification",
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


def packet_for(recovered, *, expected_context_digest, expected_recovery_commit_digest):
    if type(recovered) is not recovery.RecoveredContext:
        fail("RECOVERY_REQUIRED")
    context = material.verify_context(recovered.context, expected_context_digest)
    m = deepcopy(recovered.metadata)
    if (
        m.get("version") != "package-native-material-recovery-observation/1"
        or m.get("method_digest") != recovery.method_digest()
        or m.get("context_digest") != expected_context_digest
        or not is_digest(expected_recovery_commit_digest)
        or m.get("recovery_commit_digest") != expected_recovery_commit_digest
        or m.get("original_source_observation_digest")
        != context.metadata["source_observation_digest"]
        or m.get("digest") != digest({k: v for k, v in m.items() if k != "digest"})
        or m.get("exact_frozen_context_recovered") is not True
        or m.get("current_native_parse_and_originals_rechecked") is not True
        or any(
            m.get(k) is not False
            for k in (
                "native_binding_verified",
                "necessary_scope_verified",
                "input_authority_granted",
                "execution_authorized",
                "historical_existence_verified",
            )
        )
    ):
        fail("RECOVERY_REFERENCE_MISMATCH")
    result = {
        "version": "package-native-material-registration-packet/1",
        "context_digest": expected_context_digest,
        "context_method_digest": context.metadata["context_method_digest"],
        "recovery_commit_digest": expected_recovery_commit_digest,
        "recovery_method_digest": recovery.method_digest(),
        "recovery_observation_digest": m["digest"],
        "source_observation_digest": context.metadata["source_observation_digest"],
        "material_digest": context.metadata["source_material_digest"],
        "registration_method_digest": method_digest(),
    }
    _packet(result)
    return result


def _packet(value):
    if (
        type(value) is not dict
        or set(value) != PACKET_FIELDS | {"version"}
        or value["version"] != "package-native-material-registration-packet/1"
        or any(not is_digest(value[k]) for k in PACKET_FIELDS)
        or len(canonical(value)) > 4096
    ):
        fail("PACKET_INVALID")


def _audit(c):
    # Reuse only the effective-grant auditor. This registry intentionally owns
    # one fixed mutating RPC, with no direct table DML or request-defined policy.
    read_purpose.require_read_purpose(
        c, read_purpose.ReadPurpose(groups=frozenset({GROUP}), definer_calls=RPCS)
    )
    text = SQL_FILE.read_text(encoding="utf-8")
    for rpc, tag in zip(RPCS, ("material_record", "material_read"), strict=True):
        expected = text.split("$" + tag + "$")
        row = c.execute(
            "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,l.lanname,p.prorettype::regtype::text AS returns,pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",
            (rpc,),
        ).fetchone()
        if (
            len(expected) != 3
            or row is None
            or row["prosrc"] != expected[1]
            or not row["prosecdef"]
            or row["provolatile"] != "v"
            or row["lanname"] != "plpgsql"
            or row["returns"] != "jsonb"
            or row["caller_owner"]
            or row["proconfig"]
            != ["search_path=pg_catalog, material_registration, design, pg_temp"]
        ):
            fail("NATIVE_METHOD_MISMATCH")


def _validate_record(value, *, bid_id, expected_digest=None):
    if type(value) is not dict or set(value) != {"document", "digest"}:
        fail("NATIVE_RESULT_INVALID")
    document = value["document"]
    fields = {
        "version",
        "registration_id",
        "bid_id",
        "scope_id",
        "scope_digest",
        "command_id",
        "recorded_by",
        "recorded_at",
        "packet",
        "status",
        "native_binding_verified",
        "necessary_scope_verified",
        "input_authority_granted",
        "execution_authorized",
    }
    if (
        type(document) is not dict
        or set(document) != fields
        or len(canonical(value)) > 16384
        or document["version"] != "package-native-material-registration/1"
        or document["bid_id"] != bid_id
        or document["status"] != "awaiting_independent_verification"
        or any(
            document[k] is not False
            for k in (
                "native_binding_verified",
                "necessary_scope_verified",
                "input_authority_granted",
                "execution_authorized",
            )
        )
        or not is_digest(value["digest"])
        or digest(document) != value["digest"]
        or (expected_digest is not None and value["digest"] != expected_digest)
    ):
        fail("NATIVE_RESULT_INVALID")
    for key in ("registration_id", "bid_id", "scope_id", "command_id"):
        _uuid(document[key])
    valid_time = False
    try:
        at = document["recorded_at"]
        valid_time = (
            type(at) is str
            and len(at) <= 40
            and datetime.fromisoformat(at.replace("Z", "+00:00")).tzinfo is not None
        )
    except (ValueError, TypeError):
        pass
    if (
        not valid_time
        or type(document["recorded_by"]) is not str
        or not 1 <= len(document["recorded_by"]) <= 63
        or not is_digest(document["scope_digest"])
    ):
        fail("NATIVE_RESULT_INVALID")
    _packet(document["packet"])
    return PendingMaterialRegistration(deepcopy(value) | {"native_record_identity_verified": True})


def stage_command(
    store,
    recovered,
    *,
    command_id,
    expected_context_digest,
    expected_recovery_commit_digest,
    expected_method_digest,
):
    if expected_method_digest != method_digest():
        fail("METHOD_MISMATCH")
    _uuid(command_id)
    packet = packet_for(
        recovered,
        expected_context_digest=expected_context_digest,
        expected_recovery_commit_digest=expected_recovery_commit_digest,
    )
    m = recovered.context.metadata
    command = {
        "version": "package-material-registration-command/1",
        "method_digest": expected_method_digest,
        "bid_id": m["bid_id"],
        "scope_id": m["scope_id"],
        "scope_digest": m["scope_digest"],
        "command_id": command_id,
        "packet": packet,
    }
    return store.publish(canonical(command))


def _command(store, command_commit_digest):
    raw = store.get_commit(command_commit_digest)
    if len(raw) > 16384:
        fail("COMMAND_INVALID")
    value = archive._decode(raw)
    if (
        set(value)
        != {
            "version",
            "method_digest",
            "bid_id",
            "scope_id",
            "scope_digest",
            "command_id",
            "packet",
        }
        or value["version"] != "package-material-registration-command/1"
        or value["method_digest"] != method_digest()
        or not is_digest(value["scope_digest"])
    ):
        fail("COMMAND_INVALID")
    for key in ("bid_id", "scope_id", "command_id"):
        _uuid(value[key])
    _packet(value["packet"])
    if value["packet"]["registration_method_digest"] != value["method_digest"]:
        fail("COMMAND_INVALID")
    return value


def _execute(connection, query, parameters, *, write, expected_method_digest, validate):
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
                value = c.execute(query, parameters).fetchone()["value"]
                checked = validate(value)
                if method_digest() != method:
                    fail("METHOD_CHANGED")
    except read_purpose.ReadPurposeError as error:
        error_code = "MATERIAL_REGISTRATION_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "MATERIAL_REGISTRATION_NATIVE_UNAVAILABLE"
        )
    if error_code:
        raise MaterialRegistrationError(error_code)
    return checked


def record(
    connection,
    store,
    *,
    command_commit_digest,
    expected_method_digest,
):
    command = _command(store, command_commit_digest)

    def check(value):
        checked = _validate_record(value, bid_id=command["bid_id"])
        document = checked.metadata["document"]
        if document["packet"] != command["packet"] or any(
            document[k] != command[k] for k in ("scope_id", "scope_digest", "command_id")
        ):
            fail("NATIVE_RESULT_INVALID")
        return checked

    return _execute(
        connection,
        "SELECT material_registration.record(%s,%s,%s,%s,%s) AS value",
        (
            command["bid_id"],
            command["scope_id"],
            command["scope_digest"],
            command["command_id"],
            Jsonb(command["packet"]),
        ),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=check,
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

    def check(value):
        checked = _validate_record(value, bid_id=bid_id, expected_digest=expected_record_digest)
        document = checked.metadata["document"]
        if (
            document["command_id"] != command_id
            or digest(document["packet"]) != expected_packet_digest
        ):
            fail("NATIVE_RESULT_INVALID")
        return checked

    return _execute(
        connection,
        "SELECT material_registration.read(%s,%s,%s) AS value",
        (bid_id, command_id, expected_packet_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=check,
    )
