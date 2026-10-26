"""Purpose-only delivery leases for the original material judgment outbox.

Receipts carry private lease capabilities. Kafka messages carry only immutable
event/job identifiers and a generation; they cannot supply model or reader data.
Delivery qualification never grants live execution or retries a paid attempt.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.domain.providers.json_protocol import decode
from packages.domain.review_identity import digest
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_judgment_jobs as jobs
from packages.model_governance import native_rpc_audit as audit
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-execution-dispatch.sql"
GROUPS = {"relay": "tender_material_dispatch_relay", "worker": "tender_material_dispatch_worker"}
RPCS = {
    "relay": (
        "material_dispatch.claim_publication(uuid,text,uuid)",
        "material_dispatch.ack_publication(uuid,uuid)",
    ),
    "worker": (
        "material_dispatch.claim_delivery(uuid,jsonb,uuid)",
        "material_dispatch.heartbeat(uuid,uuid)",
        "material_dispatch.owned_job(uuid,uuid)",
        "material_dispatch.finish(uuid,uuid,text)",
        "material_dispatch.read(uuid)",
    ),
}
BLOCKERS = (
    "LIVE_ACCOUNT_PRICE_UNCONFIRMED",
    "MODEL_CONTEXT_FIT_UNPROVEN",
    "VISUAL_READABILITY_UNVERIFIED",
    "LIVE_SENDER_UNQUALIFIED",
)
FALSE_FIELDS = frozenset(
    {"production_send_authorized", "formal_prediction_eligible", "automatic_model_retry"}
)
TERMINAL = frozenset({"blocked", "mechanism_completed", "billing_unresolved"})
FAILURES = frozenset(
    {
        "NONE",
        "LIVE_QUALIFICATION_UNAVAILABLE",
        "PREPARATION_FAILED",
        "EXECUTION_FAILED",
        "CONFIGURATION_UNAVAILABLE",
    }
)
KNOWN_ERRORS = frozenset(
    "MATERIAL_DISPATCH_" + suffix
    for suffix in (
        "TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "PURPOSE_INVALID",
        "NOT_FOUND",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "PROFILE_UNAVAILABLE",
        "ALREADY_OWNED",
        "FENCE_OVERFLOW",
        "LEASE_NOT_CURRENT",
        "MESSAGE_MISMATCH",
        "FAILURE_CODE_INVALID",
    )
)
LEASE_FIELDS = (
    frozenset(
        {
            "version",
            "lease_id",
            "command_id",
            "event_id",
            "job_id",
            "job_digest",
            "generation",
            "fence",
            "profile_id",
            "profile_digest",
            "profile_head_revision",
            "purpose",
            "mode",
            "origin",
            "token",
            "lease_until",
            "message",
            "dispatch_method_digest",
            "native_sql_method_digest",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
        }
    )
    | FALSE_FIELDS
)
RESULT_FIELDS = (
    frozenset(
        {
            "version",
            "event_id",
            "job_id",
            "generation",
            "job_digest",
            "profile_id",
            "profile_digest",
            "dispatch_method_digest",
            "state",
            "mode",
            "source_current",
            "financial_state",
            "held_minor",
            "estimated_minor",
            "observed_send_grants",
            "failure_code",
            "preparation_fenced",
            "blockers",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
        }
    )
    | FALSE_FIELDS
)


class MaterialDispatchError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise MaterialDispatchError("MATERIAL_DISPATCH_" + code)


@dataclass(frozen=True, repr=False)
class DispatchObservation:
    """Private lease and immutable completion receipt, never a log payload."""

    metadata: dict


@dataclass(frozen=True, repr=False)
class OwnedJob:
    metadata: dict


def method_digest():
    root = Path(__file__).parents[2]
    return digest(
        {
            "version": "material-dispatch-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "runtime_source": sha(
                Path(__file__).with_name("material_execution_runtime.py").read_bytes()
            ),
            "launcher_source": sha((root / "deploy/material_execution_worker.py").read_bytes()),
            "execution_method": execution.method_digest(),
            "audit_source": sha(Path(audit.__file__).read_bytes()),
            "production_send_authorized": False,
        }
    )


def _uuid(value):
    try:
        jobs._uuid(value)
    except jobs.JudgmentJobError:
        fail("ID_INVALID")


def _time(value):
    try:
        jobs._time(value)
    except jobs.JudgmentJobError:
        fail("NATIVE_RESULT_INVALID")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 9007199254740991


def message(value):
    """Closed ID-only native/Kafka envelope; rejects floats, extras and duplicates."""
    if type(value) is bytes:
        if not 1 <= len(value) <= 1024:
            fail("MESSAGE_INVALID")
        try:
            value = decode(value)
        except (ValueError, UnicodeError, RecursionError):
            fail("MESSAGE_INVALID")
    if (
        type(value) is not dict
        or set(value) != {"version", "event_id", "job_id", "generation"}
        or value["version"] != "material-judgment-task/1"
        or type(value["generation"]) is not int
        or value["generation"] != 1
    ):
        fail("MESSAGE_INVALID")
    for key in ("event_id", "job_id"):
        _uuid(value[key])
    return deepcopy(value)


def _functions(purpose):
    if purpose not in GROUPS:
        fail("PURPOSE_INVALID")
    own = (
        ("native_method_digest", "", "dispatch_method", False, "s", "text", False),
        ("require_purpose", "text, boolean", "dispatch_purpose", False, "v", "void", False),
        ("profile_context", "uuid, text", "dispatch_profile", False, "v", "jsonb", False),
        ("envelope", "uuid", "dispatch_envelope", False, "s", "jsonb", False),
        ("observation", "uuid, boolean", "dispatch_observation", False, "v", "jsonb", False),
        ("claim", "uuid, uuid, text, uuid", "dispatch_claim", False, "v", "jsonb", False),
        (
            "claim_publication",
            "uuid, text, uuid",
            "dispatch_claim_publication",
            True,
            "v",
            "jsonb",
            purpose == "relay",
        ),
        (
            "ack_publication",
            "uuid, uuid",
            "dispatch_ack_publication",
            True,
            "v",
            "jsonb",
            purpose == "relay",
        ),
        (
            "claim_delivery",
            "uuid, jsonb, uuid",
            "dispatch_claim_delivery",
            True,
            "v",
            "jsonb",
            purpose == "worker",
        ),
        ("heartbeat", "uuid, uuid", "dispatch_heartbeat", True, "v", "jsonb", purpose == "worker"),
        ("owned_job", "uuid, uuid", "dispatch_owned_job", True, "v", "jsonb", purpose == "worker"),
        ("finish", "uuid, uuid, text", "dispatch_finish", True, "v", "jsonb", purpose == "worker"),
        ("read", "uuid", "dispatch_read", True, "v", "jsonb", purpose == "worker"),
    )
    return tuple(audit.FunctionSpec(SQL_FILE, "material_dispatch", *s) for s in own) + tuple(
        replace(s, caller_execute=False) for s in execution._functions()
    )


def _audit(cursor, purpose):
    try:
        audit.audit(
            cursor,
            group=GROUPS[purpose],
            rpcs=RPCS[purpose],
            schema="material_dispatch",
            tables=("profiles", "profile_heads", "leases", "states", "results"),
            functions=_functions(purpose),
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
        set(d) != LEASE_FIELDS
        or d["version"] != "material-dispatch-lease/1"
        or d["purpose"] not in GROUPS
        or type(d["generation"]) is not int
        or d["generation"] != 1
        or d["mode"] not in {"production_admission", "synthetic_mechanism"}
        or d["origin"] not in {"current_prebid", "synthetic_mechanism"}
        or (d["mode"] == "synthetic_mechanism" and d["origin"] != "synthetic_mechanism")
        or any(d[k] is not False for k in FALSE_FIELDS)
        or any(not _integer(d[k], 1) for k in ("fence", "profile_head_revision", "recorded_by_oid"))
        or d["dispatch_method_digest"] != method_digest()
        or not jobs._login(d["recorded_by"])
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in ("lease_id", "command_id", "event_id", "job_id", "profile_id", "token"):
        _uuid(d[k])
    if any(
        not is_digest(d[k]) for k in ("job_digest", "profile_digest", "native_sql_method_digest")
    ):
        fail("NATIVE_RESULT_INVALID")
    if _time(d["lease_until"]) <= _time(d["recorded_at"]):
        fail("NATIVE_RESULT_INVALID")
    m = message(d["message"])
    if any(m[k] != d[k] for k in ("event_id", "job_id", "generation")):
        fail("NATIVE_RESULT_INVALID")
    return d


def _result(value, lease):
    d = _envelope(value)
    if (
        set(d) != RESULT_FIELDS
        or d["version"] != "material-dispatch-result/1"
        or any(
            d[k] != lease[k]
            for k in (
                "event_id",
                "job_id",
                "job_digest",
                "profile_id",
                "profile_digest",
                "dispatch_method_digest",
                "mode",
                "generation",
            )
        )
        or d["state"] not in TERMINAL
        or any(d[k] is not False for k in FALSE_FIELDS)
        or type(d["source_current"]) is not bool
        or type(d["preparation_fenced"]) is not bool
        or d["financial_state"] not in execution.STATES | {None}
        or any(
            not _integer(d[k]) for k in ("held_minor", "estimated_minor", "observed_send_grants")
        )
        or d["failure_code"] not in FAILURES
        or d["blockers"] != (list(BLOCKERS) if d["mode"] == "production_admission" else [])
        or d["recorded_by"] != lease["recorded_by"]
        or d["recorded_by_oid"] != lease["recorded_by_oid"]
    ):
        fail("NATIVE_RESULT_INVALID")
    if (d["state"] == "billing_unresolved") != (d["financial_state"] in {"unknown", "in_flight"}):
        fail("NATIVE_RESULT_INVALID")
    if d["state"] == "mechanism_completed" and (
        d["mode"] != "synthetic_mechanism"
        or d["financial_state"] != "completed"
        or not d["source_current"]
    ):
        fail("NATIVE_RESULT_INVALID")
    _time(d["recorded_at"])
    return d


def _observation(value, purpose):
    if type(value) is not dict or set(value) != {
        "lease",
        "new_claim",
        "state",
        "lease_current",
        "lease_until",
        "result",
    }:
        fail("NATIVE_RESULT_INVALID")
    d = _lease(value["lease"])
    if (
        d["purpose"] != purpose
        or type(value["new_claim"]) is not bool
        or type(value["lease_current"]) is not bool
        or value["state"]
        not in ({"running", "published"} if purpose == "relay" else TERMINAL | {"running"})
        or (value["lease_current"] and value["state"] != "running")
    ):
        fail("NATIVE_RESULT_INVALID")
    _time(value["lease_until"])
    if value["result"] is not None:
        _result(value["result"], d)
        if purpose == "worker" and value["result"]["document"]["state"] != value["state"]:
            fail("NATIVE_RESULT_INVALID")
    elif value["state"] in TERMINAL:
        fail("NATIVE_RESULT_INVALID")
    return DispatchObservation(deepcopy(value))


def _execute(connection, query, args, *, purpose, write, expected_method_digest, validate):
    if expected_method_digest != method_digest():
        fail("METHOD_MISMATCH")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        fail("IDLE_CONNECTION_REQUIRED")
    result = None
    code = None
    try:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE"
                    if write
                    else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                c.execute("SET LOCAL statement_timeout='5s'")
                _audit(c, purpose)
                result = validate(c.execute(query, args).fetchone()["value"])
                if expected_method_digest != method_digest():
                    fail("METHOD_CHANGED")
    except read_purpose.ReadPurposeError as error:
        code = "MATERIAL_DISPATCH_" + error.code
    except psycopg.Error as error:
        code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "MATERIAL_DISPATCH_UNAVAILABLE"
        )
    if code:
        raise MaterialDispatchError(code)
    return result


def claim_publication(
    connection, *, profile_id, expected_profile_digest, command_id, expected_method_digest
):
    _uuid(profile_id)
    _uuid(command_id)
    if not is_digest(expected_profile_digest):
        fail("REFERENCE_INVALID")

    def validate(value):
        if value is None:
            return None
        result = _observation(value, "relay")
        d = result.metadata["lease"]["document"]
        if d["profile_id"] != profile_id or d["profile_digest"] != expected_profile_digest:
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_dispatch.claim_publication(%s,%s,%s) AS value",
        (profile_id, expected_profile_digest, command_id),
        purpose="relay",
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def claim_delivery(connection, value, *, command_id, expected_method_digest):
    m = message(value)
    _uuid(command_id)

    def validate(value):
        result = _observation(value, "worker")
        if result.metadata["lease"]["document"]["message"] != m:
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_dispatch.claim_delivery(%s,%s,%s) AS value",
        (m["event_id"], Jsonb(m), command_id),
        purpose="worker",
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def _leased(connection, observed, *, operation, expected_method_digest, failure=None):
    purpose = "relay" if operation == "ack_publication" else "worker"
    if type(observed) is not DispatchObservation:
        fail("OBSERVATION_REQUIRED")
    d = _observation(observed.metadata, purpose).metadata["lease"]["document"]
    args: tuple = (d["lease_id"], d["token"])
    queries = {
        "ack_publication": "SELECT material_dispatch.ack_publication(%s,%s) AS value",
        "heartbeat": "SELECT material_dispatch.heartbeat(%s,%s) AS value",
        "owned_job": "SELECT material_dispatch.owned_job(%s,%s) AS value",
        "finish": "SELECT material_dispatch.finish(%s,%s,%s) AS value",
    }
    if operation == "finish":
        if failure not in FAILURES:
            fail("FAILURE_CODE_INVALID")
        args += (failure,)

    def validate(value):
        if operation == "owned_job":
            if type(value) is not dict or set(value) != {
                "version",
                "lease",
                "job",
                "source_current",
                "preparation_profile_id",
                "preparation_profile_digest",
                "execution_profile_id",
                "execution_profile_digest",
                "store_command_id",
                "packet_digest",
                "storage_record_digest",
                "financial_state",
                "mode",
                "production_send_authorized",
                "blockers",
            }:
                fail("NATIVE_RESULT_INVALID")
            job = jobs._record(value["job"]).metadata["document"]
            if (
                value["version"] != "material-dispatch-owned-job/1"
                or value["lease"] != observed.metadata["lease"]
                or job["job_id"] != d["job_id"]
                or value["job"]["digest"] != d["job_digest"]
                or type(value["source_current"]) is not bool
                or value["mode"] != d["mode"]
                or value["production_send_authorized"] is not False
                or value["financial_state"] not in execution.STATES | {None}
                or value["blockers"] != list(BLOCKERS)
            ):
                fail("NATIVE_RESULT_INVALID")
            for key in ("preparation_profile_id", "store_command_id"):
                _uuid(value[key])
            for key in ("preparation_profile_digest", "packet_digest", "storage_record_digest"):
                if not is_digest(value[key]):
                    fail("NATIVE_RESULT_INVALID")
            if value["execution_profile_id"] is not None:
                _uuid(value["execution_profile_id"])
                if not is_digest(value["execution_profile_digest"]):
                    fail("NATIVE_RESULT_INVALID")
            elif (
                value["execution_profile_digest"] is not None or d["mode"] == "synthetic_mechanism"
            ):
                fail("NATIVE_RESULT_INVALID")
            return OwnedJob(deepcopy(value))
        result = _observation(value, purpose)
        if result.metadata["lease"] != observed.metadata["lease"]:
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        queries[operation],
        args,
        purpose=purpose,
        write=operation != "owned_job",
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def ack_publication(connection, observed, *, expected_method_digest):
    return _leased(
        connection,
        observed,
        operation="ack_publication",
        expected_method_digest=expected_method_digest,
    )


def heartbeat(connection, observed, *, expected_method_digest):
    return _leased(
        connection, observed, operation="heartbeat", expected_method_digest=expected_method_digest
    )


def owned_job(connection, observed, *, expected_method_digest):
    return _leased(
        connection, observed, operation="owned_job", expected_method_digest=expected_method_digest
    )


def finish(connection, observed, *, failure, expected_method_digest):
    return _leased(
        connection,
        observed,
        operation="finish",
        failure=failure,
        expected_method_digest=expected_method_digest,
    )


def read(connection, *, event_id, expected_method_digest):
    _uuid(event_id)

    def validate(value):
        result = _observation(value, "worker")
        if result.metadata["lease"]["document"]["event_id"] != event_id:
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_dispatch.read(%s) AS value",
        (event_id,),
        purpose="worker",
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
