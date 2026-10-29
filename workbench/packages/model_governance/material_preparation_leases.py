"""Owned preparation and byte reads; these never grant provider execution."""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_judgment_jobs as jobs
from packages.model_governance import material_verification_commands as commands
from packages.model_governance import material_verification_program as program
from packages.model_governance import native_rpc_audit as audit
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_technical_material as material
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-preparation-leases.sql"
GROUP = "tender_material_preparation_worker"
RPCS = (
    "material_preparation.claim(uuid,text,uuid,text,uuid)",
    "material_preparation.heartbeat(uuid,text,uuid)",
    "material_preparation.inspect(uuid,text)",
    "material_preparation.owned_context(uuid,text)",
    "material_preparation.owned_asset(uuid,text,text)",
    "material_preparation.owned_assets(uuid,text)",
)
UUID_FIELDS = frozenset({"lease_id", "command_id", "job_id", "profile_id"})
SHA_FIELDS = frozenset(
    {
        "job_digest",
        "profile_digest",
        "material_input_digest",
        "quote_digest",
        "context_digest",
        "preparation_method_digest",
        "native_sql_method_digest",
    }
)
TRUE_FIELDS = frozenset({"preparation_lease_created", "native_binding_verified"})
FALSE_FIELDS = jobs.FALSE_FIELDS
DETAIL_FIELDS = frozenset(
    {
        "version",
        "profile_head_revision",
        "generation",
        "fence",
        "lease_seconds",
        "lease_until",
        "origin",
        "recorded_by",
        "recorded_by_oid",
        "recorded_at",
    }
)
BLOCKED_CURRENT = frozenset(
    {
        "fee_ledger_reserved",
        "execution_authorized",
        "send_lease_granted",
        "atomic_snapshot_verified",
    }
)
KNOWN_ERRORS = frozenset(
    "PREPARATION_" + v
    for v in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "REFERENCE_INVALID",
        "NOT_FOUND",
        "COMMAND_CONFLICT",
        "REFERENCE_MISMATCH",
        "CURRENT_STATE_UNAVAILABLE",
        "ALREADY_OWNED",
        "FENCE_OVERFLOW",
        "LEASE_NOT_CURRENT",
        "OBJECT_INVALID",
        "ASSET_NOT_OWNED",
    )
)


class PreparationError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise PreparationError("PREPARATION_" + code)


@dataclass(frozen=True, repr=False)
class NativePreparationLease:
    metadata: dict


@dataclass(frozen=True, repr=False)
class NativePreparationHeartbeat:
    metadata: dict


@dataclass(frozen=True, repr=False)
class PreparationObservation:
    record: NativePreparationLease
    metadata: dict


@dataclass(frozen=True, repr=False)
class OwnedMaterialProjection:
    metadata: dict


@dataclass(frozen=True, repr=False)
class OwnedMaterialAsset:
    lease_id: str
    object_digest: str
    data: bytes


@dataclass(frozen=True, repr=False)
class OwnedMaterialBatch:
    lease_id: str
    objects: dict[str, bytes]


def method_digest():
    return digest(
        {
            "version": "material-preparation-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "job_method": jobs.method_digest(),
            "audit_source": sha(Path(audit.__file__).read_bytes()),
        }
    )


def _uuid(value):
    try:
        commands._uuid(value)
    except commands.VerificationCommandError:
        fail("ID_INVALID")


def _time(value):
    try:
        commands._time(value)
    except commands.VerificationCommandError:
        fail("NATIVE_RESULT_INVALID")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _functions():
    own = (
        ("claim", "uuid, text, uuid, text, uuid", "preparation_claim", True, "v", "jsonb", True),
        ("heartbeat", "uuid, text, uuid", "preparation_heartbeat", True, "v", "jsonb", True),
        ("inspect", "uuid, text", "preparation_inspect", True, "v", "jsonb", True),
        ("owned_context", "uuid, text", "preparation_owned_context", True, "v", "jsonb", True),
        ("owned_asset", "uuid, text, text", "preparation_owned_asset", True, "v", "bytea", True),
        ("owned_assets", "uuid, text", "preparation_owned_assets", True, "v", "bytea[]", True),
        ("native_method_digest", "", "preparation_method", False, "s", "text", False),
        ("current_context", "uuid, uuid", "preparation_context", False, "v", "jsonb", False),
        ("lease_context", "uuid, text", "preparation_lease_context", False, "v", "jsonb", False),
        ("lock_inputs", "uuid, uuid", "preparation_locks", False, "v", "void", False),
    )
    return tuple(audit.FunctionSpec(SQL_FILE, "material_preparation", *s) for s in own) + tuple(
        replace(s, caller_execute=False) for s in jobs._functions()
    )


def _audit(cursor):
    try:
        audit.audit(
            cursor,
            group=GROUP,
            rpcs=RPCS,
            schema="material_preparation",
            tables=("profiles", "profile_heads", "leases", "heartbeats", "states"),
            functions=_functions(),
        )
    except audit.NativeMethodMismatch:
        fail("NATIVE_METHOD_MISMATCH")


def _envelope(value):
    if (
        type(value) is not dict
        or set(value) != {"document", "digest"}
        or type(value["document"]) is not dict
        or not is_digest(value["digest"])
        or digest(value["document"]) != value["digest"]
    ):
        fail("NATIVE_RESULT_INVALID")
    return value["document"]


def _lease(value):
    d = _envelope(value)
    if (
        set(d) != UUID_FIELDS | SHA_FIELDS | TRUE_FIELDS | FALSE_FIELDS | DETAIL_FIELDS
        or d["version"] != "material-preparation-lease/1"
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in UUID_FIELDS:
        _uuid(d[k])
    if (
        any(not is_digest(d[k]) for k in SHA_FIELDS)
        or any(d[k] is not True for k in TRUE_FIELDS)
        or any(d[k] is not False for k in FALSE_FIELDS)
    ):
        fail("NATIVE_RESULT_INVALID")
    if (
        not commands._revision(d["profile_head_revision"])
        or not commands._revision(d["fence"])
        or type(d["generation"]) is not int
        or d["generation"] != 1
        or not cost._integer(d["lease_seconds"], minimum=1, maximum=120)
        or not program._oid(d["recorded_by_oid"])
        or not jobs._login(d["recorded_by"])
        or type(d["origin"]) is not str
        or d["origin"] not in {"synthetic_mechanism", "current_prebid"}
    ):
        fail("NATIVE_RESULT_INVALID")
    if (_time(d["lease_until"]) - _time(d["recorded_at"])).total_seconds() != d["lease_seconds"]:
        fail("NATIVE_RESULT_INVALID")
    return NativePreparationLease(deepcopy(value))


def _heartbeat(value):
    d = _envelope(value)
    ids = {"heartbeat_id", "command_id", "lease_id", "job_id"}
    if (
        set(d)
        != ids
        | {
            "version",
            "lease_digest",
            "generation",
            "fence",
            "previous_lease_until",
            "lease_until",
            "recorded_at",
            "recorded_by",
            "recorded_by_oid",
        }
        | BLOCKED_CURRENT
        or d["version"] != "material-preparation-heartbeat/1"
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in ids:
        _uuid(d[k])
    if (
        not is_digest(d["lease_digest"])
        or not commands._revision(d["fence"])
        or type(d["generation"]) is not int
        or d["generation"] != 1
        or not program._oid(d["recorded_by_oid"])
        or not jobs._login(d["recorded_by"])
        or any(d[k] is not False for k in BLOCKED_CURRENT)
    ):
        fail("NATIVE_RESULT_INVALID")
    if _time(d["lease_until"]) < _time(d["previous_lease_until"]) or _time(
        d["lease_until"]
    ) <= _time(d["recorded_at"]):
        fail("NATIVE_RESULT_INVALID")
    return NativePreparationHeartbeat(deepcopy(value))


def _execute(connection, query, args, *, write, expected_method_digest, validate):
    method = method_digest()
    if method != expected_method_digest:
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
        error_code = "PREPARATION_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "PREPARATION_UNAVAILABLE"
        )
    if error_code:
        raise PreparationError(error_code)
    return result


def _references(*, uuids, digests):
    for identity in uuids:
        _uuid(identity)
    if any(not is_digest(v) for v in digests):
        fail("DIGEST_INVALID")


def claim(
    connection,
    *,
    job_id,
    expected_job_digest,
    profile_id,
    expected_profile_digest,
    command_id,
    expected_method_digest,
):
    _references(
        uuids=(job_id, profile_id, command_id),
        digests=(expected_job_digest, expected_profile_digest),
    )

    def validate(value):
        record = _lease(value)
        d = record.metadata["document"]
        if (
            d["job_id"] != job_id
            or d["job_digest"] != expected_job_digest
            or d["profile_id"] != profile_id
            or d["profile_digest"] != expected_profile_digest
            or d["command_id"] != command_id
            or d["preparation_method_digest"] != expected_method_digest
        ):
            fail("NATIVE_RESULT_INVALID")
        return record

    return _execute(
        connection,
        "SELECT material_preparation.claim(%s,%s,%s,%s,%s) AS value",
        (job_id, expected_job_digest, profile_id, expected_profile_digest, command_id),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def heartbeat(connection, *, lease_id, expected_lease_digest, command_id, expected_method_digest):
    _references(uuids=(lease_id, command_id), digests=(expected_lease_digest,))

    def validate(value):
        record = _heartbeat(value)
        d = record.metadata["document"]
        if (
            d["lease_id"] != lease_id
            or d["lease_digest"] != expected_lease_digest
            or d["command_id"] != command_id
        ):
            fail("NATIVE_RESULT_INVALID")
        return record

    return _execute(
        connection,
        "SELECT material_preparation.heartbeat(%s,%s,%s) AS value",
        (lease_id, expected_lease_digest, command_id),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def inspect(connection, *, lease_id, expected_lease_digest, expected_method_digest):
    _references(uuids=(lease_id,), digests=(expected_lease_digest,))

    def validate(value):
        if type(value) is not dict or set(value) != {"record", "current"}:
            fail("NATIVE_RESULT_INVALID")
        record = _lease(value["record"])
        d = record.metadata["document"]
        cur = value["current"]
        flags = {"profile_current", "job_current", "preparation_lease_current"}
        if (
            d["lease_id"] != lease_id
            or record.metadata["digest"] != expected_lease_digest
            or type(cur) is not dict
            or set(cur)
            != flags
            | BLOCKED_CURRENT
            | {"observed_at", "generation", "fence", "lease_until", "profile_head_revision"}
            or any(type(cur[k]) is not bool for k in flags)
            or any(cur[k] is not False for k in BLOCKED_CURRENT)
            or type(cur["generation"]) is not int
            or cur["generation"] != 1
            or not commands._revision(cur["fence"])
            or (
                cur["profile_head_revision"] is not None
                and not commands._revision(cur["profile_head_revision"])
            )
        ):
            fail("NATIVE_RESULT_INVALID")
        observed_at = _time(cur["observed_at"])
        lease_until = _time(cur["lease_until"])
        eligible = (
            cur["profile_current"]
            and cur["job_current"]
            and cur["fence"] == d["fence"]
            and cur["generation"] == d["generation"]
            and cur["profile_head_revision"] == d["profile_head_revision"]
            and observed_at < lease_until
        )
        if cur["preparation_lease_current"] is not eligible:
            fail("NATIVE_RESULT_INVALID")
        metadata = {
            "version": "material-preparation-observation/1",
            "method_digest": method_digest(),
            **deepcopy(value),
        }
        return PreparationObservation(record, metadata | {"digest": digest(metadata)})

    return _execute(
        connection,
        "SELECT material_preparation.inspect(%s,%s) AS value",
        (lease_id, expected_lease_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def owned_context(connection, *, lease_id, expected_lease_digest, expected_method_digest):
    _references(uuids=(lease_id,), digests=(expected_lease_digest,))

    def validate(value):
        if type(value) is not dict or set(value) != {
            "lease",
            "lease_id",
            "job_id",
            "generation",
            "fence",
            "evidence_revision",
            "context",
            "context_object_digest",
            "material_input",
        }:
            fail("OWNED_PROJECTION_INVALID")
        lease = _lease(value["lease"])
        d = lease.metadata["document"]
        ctx = value["context"]
        bound = value["material_input"]
        if (
            lease.metadata["digest"] != expected_lease_digest
            or value["lease_id"] != lease_id
            or d["lease_id"] != lease_id
            or value["job_id"] != d["job_id"]
            or type(value["generation"]) is not int
            or value["generation"] != d["generation"]
            or type(value["fence"]) is not int
            or value["fence"] != d["fence"]
            or not commands._revision(value["evidence_revision"])
            or type(ctx) is not dict
            or type(bound) is not dict
            or not is_digest(value["context_object_digest"])
            or sha(canonical(ctx)) != value["context_object_digest"]
        ):
            fail("OWNED_PROJECTION_INVALID")
        input_fields = {
            "version",
            "context_digest",
            "input_method_digest",
            "binding_reference",
            "binding_reference_digest",
            "native_binding_verified",
            "input_authority_granted",
            "execution_authorized",
            "digest",
        }
        if (
            ctx.get("digest") != d["context_digest"]
            or digest({k: v for k, v in ctx.items() if k != "digest"}) != d["context_digest"]
            or ctx.get("context_method_digest") != material.context_method_digest()
            or set(bound) != input_fields
            or bound["version"] != "package-technical-material-input/3"
            or bound["digest"] != d["material_input_digest"]
            or digest({k: v for k, v in bound.items() if k != "digest"}) != bound["digest"]
            or bound["context_digest"] != d["context_digest"]
            or bound["input_method_digest"] != material.method_digest()
            or digest(bound["binding_reference"]) != bound["binding_reference_digest"]
            or any(
                bound[k] is not False
                for k in {
                    "native_binding_verified",
                    "input_authority_granted",
                    "execution_authorized",
                }
            )
        ):
            fail("OWNED_PROJECTION_INVALID")
        return OwnedMaterialProjection(deepcopy(value))

    return _execute(
        connection,
        "SELECT material_preparation.owned_context(%s,%s) AS value",
        (lease_id, expected_lease_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def owned_asset(
    connection, *, lease_id, expected_lease_digest, object_digest, expected_method_digest
):
    _references(uuids=(lease_id,), digests=(expected_lease_digest, object_digest))

    def validate(value):
        if (
            type(value) is not bytes
            or not 1 <= len(value) <= 33554432
            or sha(value) != object_digest
        ):
            fail("OWNED_ASSET_INVALID")
        return OwnedMaterialAsset(lease_id, object_digest, value)

    return _execute(
        connection,
        "SELECT material_preparation.owned_asset(%s,%s,%s) AS value",
        (lease_id, expected_lease_digest, object_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def _batch(value, expected_object_digests, lease_id):
    keys = expected_object_digests
    if (
        type(keys) is not list
        or not 1 <= len(keys) <= 384
        or any(not is_digest(key) for key in keys)
        or keys != sorted(set(keys))
        or type(value) is not list
        or len(value) != len(keys)
        or any(type(raw) is not bytes or not 1 <= len(raw) <= 33554432 for raw in value)
        or sum(len(raw) for raw in value) > 67108864
        or [sha(raw) for raw in value] != keys
    ):
        fail("OWNED_BATCH_INVALID")
    return OwnedMaterialBatch(lease_id, dict(zip(keys, value, strict=True)))


def owned_assets(
    connection, *, lease_id, expected_lease_digest, expected_object_digests, expected_method_digest
):
    _references(uuids=(lease_id,), digests=(expected_lease_digest,))
    keys = deepcopy(expected_object_digests)
    if (
        type(keys) is not list
        or not 1 <= len(keys) <= 384
        or any(not is_digest(key) for key in keys)
        or keys != sorted(set(keys))
    ):
        fail("OWNED_BATCH_INVALID")
    return _execute(
        connection,
        "SELECT material_preparation.owned_assets(%s,%s) AS value",
        (lease_id, expected_lease_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=lambda value: _batch(value, keys, lease_id),
    )
