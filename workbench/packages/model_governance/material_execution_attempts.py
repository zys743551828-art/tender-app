"""Native full-material reservation, one send and durable financial evidence.

The runnable lane is explicitly synthetic. Production admission is refused;
neither a preflight receipt nor an owner-published price estimate proves live
account prices, model token fit or visual readability. There is no retry port.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

import httpx
import psycopg
from jsonschema import Draft202012Validator, FormatChecker
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.contracts import package_technical_material as contract
from packages.domain.errors import DomainError
from packages.domain.providers import deepseek_complete_vision as provider
from packages.domain.providers.deepseek_vision import (
    MAX_RESPONSE_BYTES,
    VisionGeneration,
    VisionProviderError,
)
from packages.domain.providers.json_protocol import decode, identifier
from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_preparation_leases as leases
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import native_rpc_audit as audit
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-execution-attempts.sql"
GROUP = "tender_material_execution_worker"
RPCS = (
    "material_execution.begin_attempt(jsonb,uuid,text,uuid,uuid,uuid)",
    "material_execution.settle(uuid,uuid,jsonb,bytea,uuid)",
    "material_execution.read(uuid)",
    "material_execution.response(uuid,text)",
)
FALSE_FIELDS = frozenset(
    {
        "execution_authorized",
        "account_price_confirmed",
        "model_context_fit_proven",
        "visual_readability_verified",
        "automatic_retry",
        "atomic_snapshot_verified",
        "formal_prediction_eligible",
    }
)
ATTEMPT_FIELDS = (
    frozenset(
        {
            "version",
            "attempt_id",
            "command_id",
            "job_id",
            "slot_id",
            "rule_id",
            "slot_number",
            "attempt_number",
            "profile_id",
            "profile_digest",
            "profile_head_revision",
            "lease_id",
            "lease_digest",
            "generation",
            "fence",
            "preflight_digest",
            "send_token",
            "send_until",
            "request",
            "price_policy",
            "reserved_call_minor",
            "currency",
            "execution_method_digest",
            "native_sql_method_digest",
            "execution_mode",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
            "mechanism_send_once_granted",
        }
    )
    | FALSE_FIELDS
)
SUBMITTED_FIELDS = frozenset(
    {
        "version",
        "attempt_id",
        "request_digest",
        "raw_response_digest",
        "raw_complete",
        "billing_state",
        "usage",
        "response_id",
        "request_id",
        "valid_slot",
        "judgment_digest",
        "failure_code",
        "formal_prediction_eligible",
        "invoice_reconciled",
    }
)
OUTCOME_FIELDS = SUBMITTED_FIELDS | frozenset(
    {
        "command_id",
        "estimated_fee_minor",
        "fee_basis",
        "source_current_at_settlement",
        "duplicate_response",
        "over_reservation",
        "state",
        "execution_mode",
        "recorded_at",
    }
)
STATES = frozenset(
    {
        "ready",
        "in_flight",
        "unknown",
        "paused_invalid",
        "paused_stale",
        "paused_overrun",
        "completed",
    }
)
KNOWN_ERRORS = frozenset(
    "MATERIAL_EXECUTION_" + suffix
    for suffix in (
        "TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "PREFLIGHT_INVALID",
        "NOT_FOUND",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "CURRENT_STATE_UNAVAILABLE",
        "REFERENCE_MISMATCH",
        "ACCOUNT_UNAVAILABLE",
        "BUDGET_INSUFFICIENT",
        "RESERVATION_CONFLICT",
        "JOB_BLOCKED",
        "OUTCOME_INVALID",
        "SETTLEMENT_CONFLICT",
        "AMOUNT_OVERFLOW",
        "LEDGER_INVALID",
    )
)


class MaterialExecutionError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise MaterialExecutionError("MATERIAL_EXECUTION_" + code)


@dataclass(frozen=True, repr=False)
class AttemptObservation:
    """Private receipt; includes a one-use capability, never suitable for logging."""

    metadata: dict


@dataclass(frozen=True, repr=False)
class SubmittedOutcome:
    metadata: dict
    raw_response: bytes


def method_digest():
    return digest(
        {
            "version": "material-execution-attempt-method/1",
            "source_digest": sha(Path(__file__).read_bytes()),
            "sql_source_digest": sha(SQL_FILE.read_bytes()),
            "preflight_method_digest": preflight.method_digest(),
            "serializer_digest": vision.serializer_digest(),
            "provider_source_digest": sha(Path(provider.__file__).read_bytes()),
            "audit_source_digest": sha(Path(audit.__file__).read_bytes()),
            "execution_mode": "isolated_synthetic_mechanism",
            "formal_prediction_eligible": False,
        }
    )


def _functions():
    own = (
        (
            "begin_attempt",
            "jsonb, uuid, text, uuid, uuid, uuid",
            "execution_begin",
            True,
            "v",
            "jsonb",
            True,
        ),
        ("settle", "uuid, uuid, jsonb, bytea, uuid", "execution_settle", True, "v", "jsonb", True),
        ("read", "uuid", "execution_read", True, "v", "jsonb", True),
        ("response", "uuid, text", "execution_response", True, "v", "bytea", True),
        ("native_method_digest", "", "execution_method", False, "s", "text", False),
        ("require_worker", "boolean", "execution_worker", False, "v", "void", False),
        ("current_context", "jsonb, uuid", "execution_context", False, "v", "jsonb", False),
        ("observation", "uuid, boolean", "execution_observation", False, "v", "jsonb", False),
        ("judgment_valid", "uuid, jsonb, text", "execution_judgment", False, "v", "boolean", False),
    )
    return tuple(audit.FunctionSpec(SQL_FILE, "material_execution", *spec) for spec in own) + tuple(
        replace(spec, caller_execute=False) for spec in leases._functions()
    )


def _audit(cursor):
    try:
        audit.audit(
            cursor,
            group=GROUP,
            rpcs=RPCS,
            schema="material_execution",
            tables=(
                "accounts",
                "balances",
                "profiles",
                "profile_heads",
                "reservations",
                "job_balances",
                "attempts",
                "outcomes",
            ),
            functions=_functions(),
        )
    except audit.NativeMethodMismatch:
        fail("NATIVE_METHOD_MISMATCH")


def _uuid(value):
    try:
        leases._uuid(value)
    except leases.PreparationError:
        fail("REFERENCE_INVALID")


def _time(value):
    try:
        return leases._time(value)
    except (leases.PreparationError, ValueError, TypeError):
        fail("NATIVE_RESULT_INVALID")


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


def _observation(value):
    if (
        type(value) is not dict
        or set(value)
        != {"attempt", "outcome", "reservation", "job_balance", "account_balance", "new_send"}
        or type(value["new_send"]) is not bool
    ):
        fail("NATIVE_RESULT_INVALID")
    d = _envelope(value["attempt"])
    if (
        set(d) != ATTEMPT_FIELDS
        or d["version"] != "material-execution-attempt/1"
        or d["execution_mode"] != "isolated_synthetic_mechanism"
        or any(d[k] is not False for k in FALSE_FIELDS)
        or d["mechanism_send_once_granted"] is not True
        or type(d["attempt_number"]) is not int
        or d["attempt_number"] != 1
        or type(d["generation"]) is not int
        or d["generation"] != 1
        or not cost._integer(d["slot_number"], minimum=1, maximum=3)
        or not cost._integer(d["fence"], minimum=1)
        or not cost._integer(d["profile_head_revision"], minimum=1)
        or not cost._integer(d["reserved_call_minor"])
        or d["currency"] not in {"USD", "CNY"}
        or not cost._integer(d["recorded_by_oid"], minimum=1)
        or not leases.jobs._login(d["recorded_by"])
    ):
        fail("NATIVE_RESULT_INVALID")
    for key in (
        "attempt_id",
        "command_id",
        "job_id",
        "slot_id",
        "rule_id",
        "profile_id",
        "lease_id",
        "send_token",
    ):
        _uuid(d[key])
    if any(
        not is_digest(d[key])
        for key in (
            "profile_digest",
            "lease_digest",
            "preflight_digest",
            "execution_method_digest",
            "native_sql_method_digest",
        )
    ):
        fail("NATIVE_RESULT_INVALID")
    if _time(d["send_until"]) <= _time(d["recorded_at"]):
        fail("NATIVE_RESULT_INVALID")
    request = d["request"]
    if (
        type(request) is not dict
        or request.get("rule_id") != d["rule_id"]
        or request.get("serializer_digest") != vision.serializer_digest()
        or request.get("profile_digest") != vision.profile_digest()
        or request.get("judgment_method_digest") != vision.judgment_method_digest()
        or request.get("execution_authorized") is not False
    ):
        fail("NATIVE_RESULT_INVALID")
    if not Draft202012Validator(contract.REQUEST_RECEIPT, format_checker=FormatChecker()).is_valid(
        request
    ):
        fail("NATIVE_RESULT_INVALID")
    policy = cost.bind_policy(d["price_policy"], expected_policy_digest=digest(d["price_policy"]))
    if policy.metadata["currency"] != d["currency"]:
        fail("NATIVE_RESULT_INVALID")
    reservation = _envelope(value["reservation"])
    if (
        reservation.get("version") != "material-execution-reservation/1"
        or reservation.get("job_id") != d["job_id"]
        or reservation.get("profile_id") != d["profile_id"]
        or reservation.get("execution_mode") != "isolated_synthetic_mechanism"
        or reservation.get("mechanism_fee_ledger_reserved") is not True
        or reservation.get("account_price_confirmed") is not False
        or reservation.get("formal_prediction_eligible") is not False
        or reservation.get("invoice_reconciled") is not False
        or not cost._integer(reservation.get("reserved_minor"))
        or reservation.get("per_call_reserved_minor") != d["reserved_call_minor"]
    ):
        fail("NATIVE_RESULT_INVALID")
    job = value["job_balance"]
    account = value["account_balance"]
    if (
        type(job) is not dict
        or set(job) != {"job_id", "held_minor", "estimated_minor", "released_minor", "state"}
        or job["job_id"] != d["job_id"]
        or job["state"] not in STATES
        or any(
            not cost._integer(job[k]) for k in ("held_minor", "estimated_minor", "released_minor")
        )
        or type(account) is not dict
        or set(account) != {"account_id", "held_minor", "estimated_minor"}
        or account["account_id"] != reservation.get("account_id")
        or any(not cost._integer(account[k]) for k in ("held_minor", "estimated_minor"))
        or account["held_minor"] < job["held_minor"]
        or account["estimated_minor"] < job["estimated_minor"]
    ):
        fail("NATIVE_RESULT_INVALID")
    if value["outcome"] is not None:
        outcome = _envelope(value["outcome"])
        if (
            set(outcome) != OUTCOME_FIELDS
            or outcome["version"] != "material-execution-outcome/1"
            or outcome["attempt_id"] != d["attempt_id"]
            or outcome["request_digest"] != request.get("request_digest")
            or outcome["formal_prediction_eligible"] is not False
            or outcome["invoice_reconciled"] is not False
            or outcome["execution_mode"] != "isolated_synthetic_mechanism"
            or not is_digest(outcome["raw_response_digest"])
            or outcome["billing_state"] not in {"usage_reported", "unknown"}
            or any(
                type(outcome[key]) is not bool
                for key in (
                    "raw_complete",
                    "valid_slot",
                    "source_current_at_settlement",
                    "duplicate_response",
                    "over_reservation",
                )
            )
            or value["new_send"]
        ):
            fail("NATIVE_RESULT_INVALID")
        if outcome["billing_state"] == "unknown":
            if (
                outcome["estimated_fee_minor"] is not None
                or outcome["usage"] is not None
                or outcome["valid_slot"]
                or outcome["fee_basis"] != "unresolved"
            ):
                fail("NATIVE_RESULT_INVALID")
        elif (
            not cost._integer(outcome["estimated_fee_minor"])
            or outcome["fee_basis"] != "usage_price_estimate"
        ):
            fail("NATIVE_RESULT_INVALID")
    elif value["new_send"] and job["state"] != "in_flight":
        fail("NATIVE_RESULT_INVALID")
    return AttemptObservation(deepcopy(value))


def _execute(connection, query, args, *, write, expected_method_digest, validate):
    if expected_method_digest != method_digest():
        fail("METHOD_MISMATCH")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        fail("IDLE_CONNECTION_REQUIRED")
    error_code = None
    result = None
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
                if expected_method_digest != method_digest():
                    fail("METHOD_CHANGED")
    except read_purpose.ReadPurposeError as error:
        error_code = "MATERIAL_EXECUTION_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "MATERIAL_EXECUTION_UNAVAILABLE"
        )
    if error_code:
        raise MaterialExecutionError(error_code)
    return result


def begin_attempt(
    connection,
    checked,
    *,
    profile_id,
    expected_profile_digest,
    slot_id,
    rule_id,
    command_id,
    expected_method_digest,
):
    """Atomically reserve the whole job and grant one synthetic slot once.

    A committed grant with a lost acknowledgment remains in flight. Its replay
    is observation only, even under a new command or preparation lease.
    """
    for value in (profile_id, slot_id, rule_id, command_id):
        _uuid(value)
    if not is_digest(expected_profile_digest):
        fail("REFERENCE_INVALID")
    if (
        type(checked) is not preflight.MaterialRequestPreflight
        or type(checked.metadata) is not dict
        or set(checked.metadata) != preflight.RECEIPT_FIELDS
        or len(canonical(checked.metadata)) > 1_048_576
        or checked.metadata["method_digest"] != preflight.method_digest()
    ):
        fail("PREFLIGHT_INVALID")

    def validate(value):
        result = _observation(value)
        d = result.metadata["attempt"]["document"]
        if (
            d["job_id"] != checked.metadata["job_id"]
            or d["slot_id"] != slot_id
            or d["rule_id"] != rule_id
            or d["profile_id"] != profile_id
            or d["profile_digest"] != expected_profile_digest
            or d["execution_method_digest"] != expected_method_digest
            or d["request"] not in checked.metadata["requests"]
            or (result.metadata["new_send"] and d["command_id"] != command_id)
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_execution.begin_attempt(%s,%s,%s,%s,%s,%s) AS value",
        (
            Jsonb(deepcopy(checked.metadata)),
            profile_id,
            expected_profile_digest,
            slot_id,
            rule_id,
            command_id,
        ),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def settle(connection, granted, submitted, *, command_id, expected_method_digest):
    """Record bounded raw evidence once; an expired lease never erases its fee."""
    _uuid(command_id)
    if type(granted) is not AttemptObservation or type(submitted) is not SubmittedOutcome:
        fail("OUTCOME_INVALID")
    d = _observation(granted.metadata).metadata["attempt"]["document"]
    m = submitted.metadata
    if (
        type(m) is not dict
        or set(m) != SUBMITTED_FIELDS
        or type(submitted.raw_response) is not bytes
        or len(submitted.raw_response) > MAX_RESPONSE_BYTES
        or m["raw_response_digest"] != sha(submitted.raw_response)
        or m["attempt_id"] != d["attempt_id"]
        or m["request_digest"] != d["request"]["request_digest"]
        or m["formal_prediction_eligible"] is not False
        or m["invoice_reconciled"] is not False
    ):
        fail("OUTCOME_INVALID")

    def validate(value):
        result = _observation(value)
        if (
            result.metadata["attempt"] != granted.metadata["attempt"]
            or result.metadata["outcome"] is None
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_execution.settle(%s,%s,%s,%s,%s) AS value",
        (d["attempt_id"], d["send_token"], Jsonb(deepcopy(m)), submitted.raw_response, command_id),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(connection, *, attempt_id, expected_method_digest):
    _uuid(attempt_id)

    def validate(value):
        result = _observation(value)
        if (
            result.metadata["attempt"]["document"]["attempt_id"] != attempt_id
            or result.metadata["new_send"]
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_execution.read(%s) AS value",
        (attempt_id,),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def response(connection, observed, *, expected_method_digest):
    if type(observed) is not AttemptObservation:
        fail("REFERENCE_INVALID")
    m = _observation(observed.metadata).metadata
    if m["outcome"] is None:
        fail("NOT_FOUND")

    def validate(value):
        if (
            type(value) is not bytes
            or sha(value) != m["outcome"]["document"]["raw_response_digest"]
        ):
            fail("NATIVE_RESULT_INVALID")
        return value

    return _execute(
        connection,
        "SELECT material_execution.response(%s,%s) AS value",
        (m["attempt"]["document"]["attempt_id"], m["outcome"]["digest"]),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def _outcome(
    granted,
    *,
    raw=b"",
    complete=False,
    billing="unknown",
    usage=None,
    response_id=None,
    request_id=None,
    valid=False,
    judgment_digest=None,
    failure="UNRESOLVED",
):
    d = granted.metadata["attempt"]["document"]
    return SubmittedOutcome(
        {
            "version": "material-execution-submitted-outcome/1",
            "attempt_id": d["attempt_id"],
            "request_digest": d["request"]["request_digest"],
            "raw_response_digest": sha(raw),
            "raw_complete": complete,
            "billing_state": billing,
            "usage": usage,
            "response_id": response_id,
            "request_id": request_id,
            "valid_slot": valid,
            "judgment_digest": judgment_digest,
            "failure_code": failure,
            "formal_prediction_eligible": False,
            "invoice_reconciled": False,
        },
        bytes(raw),
    )


def _billing(raw, request_id, claimed_usage, price):
    """Re-derive usage from the original provider bytes, including invalid output."""
    value = decode(raw)
    usage = {
        key: value["usage"][key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    if (
        value.get("model") != vision.profile()["expected_response_model"]
        or not identifier(value.get("id"))
        or not identifier(request_id)
        or any(not cost._integer(v) for v in usage.values())
        or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]
        or type(claimed_usage) is not dict
        or any(claimed_usage.get(key) != usage[key] for key in usage)
    ):
        raise ValueError("usage")
    cost.ceiling_charge(
        usage["prompt_tokens"],
        usage["completion_tokens"],
        price["input_per_million_minor"],
        price["output_per_million_minor"],
    )
    return usage, value["id"]


def _received(granted, bundle, request, generated=None, error=None):
    raw, complete, request_id, claimed_usage = b"", False, None, None
    if type(generated) is VisionGeneration:
        raw, complete = generated.raw_response, True
        request_id, claimed_usage = generated.request_id, generated.usage
    elif isinstance(error, VisionProviderError):
        raw, complete = error.raw_response, error.raw_complete
        request_id = error.details.get("provider_request_id")
        if error.details.get("billing_state") == "usage_reported":
            claimed_usage = error.details.get("usage")
    raw = bytes(raw[:MAX_RESPONSE_BYTES])
    d = granted.metadata["attempt"]["document"]
    usage = None
    response_id = None
    if complete and claimed_usage is not None:
        try:
            usage, response_id = _billing(raw, request_id, claimed_usage, d["price_policy"])
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            pass
    if usage is None:
        return _outcome(
            granted,
            raw=raw,
            complete=complete,
            request_id=identifier(request_id),
            failure="BILLING_UNRESOLVED",
        )
    valid, judgment = False, None
    if generated is not None:
        try:
            result = vision.check_judgment(
                bundle,
                request,
                generated,
                expected_input_digest=d["request"]["input_digest"],
                expected_request_digest=d["request"]["request_digest"],
            )
            valid, judgment = result["valid_slot"], result["judgment_digest"]
        except (ValueError, DomainError):
            pass
    return _outcome(
        granted,
        raw=raw,
        complete=True,
        billing="usage_reported",
        usage=usage,
        response_id=response_id,
        request_id=request_id,
        valid=valid,
        judgment_digest=judgment,
        failure="NONE" if valid else "JUDGMENT_INVALID",
    )


def execute_attempt(*args, **kwargs):
    """Live execution cannot be enabled by passing client assertions or credentials."""
    fail("LIVE_QUALIFICATION_UNAVAILABLE")


async def execute_mechanism_attempt(
    preparation_connection,
    execution_connection,
    bundle,
    checked,
    *,
    rule_id,
    slot_id,
    profile_id,
    expected_profile_digest,
    command_id,
    expected_preflight_digest,
    expected_method_digest,
    transport,
):
    """A single original /3 request through an explicit synthetic HTTP transport.

    No database transaction spans I/O. Every caught transport failure is settled
    as unknown unless complete raw usage can be verified. Cancellation, process
    loss, and settlement failure leave the durable in-flight hold intact; none
    grants another send. The caller can explicitly retry only settlement/read.
    """
    if type(transport) is not httpx.MockTransport:
        fail("ISOLATED_TRANSPORT_REQUIRED")
    if preparation_connection is execution_connection:
        fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    if expected_method_digest != method_digest():
        fail("METHOD_MISMATCH")
    if any(
        c.info.transaction_status != TransactionStatus.IDLE
        for c in (preparation_connection, execution_connection)
    ):
        fail("IDLE_CONNECTION_REQUIRED")
    request = preflight.prepare_rule_request(
        preparation_connection,
        bundle,
        checked,
        rule_id,
        expected_preflight_digest=expected_preflight_digest,
        expected_method_digest=preflight.method_digest(),
    )
    granted = begin_attempt(
        execution_connection,
        checked,
        profile_id=profile_id,
        expected_profile_digest=expected_profile_digest,
        slot_id=slot_id,
        rule_id=rule_id,
        command_id=command_id,
        expected_method_digest=expected_method_digest,
    )
    if not granted.metadata["new_send"]:
        return granted
    d = granted.metadata["attempt"]["document"]
    if d["request"] != request.receipt or d["rule_id"] != rule_id:
        submitted = _outcome(granted, failure="REQUEST_MISMATCH_BEFORE_SEND")
    elif datetime.now(timezone.utc) >= _time(d["send_until"]):
        submitted = _outcome(granted, failure="LEASE_EXPIRED_BEFORE_SEND")
    else:
        client = provider.DeepSeekCompleteVisionClient(
            api_key="isolated-synthetic-fixture",
            total_timeout=30,
            transport=transport,
        )
        try:
            generation = await client.generate_async(
                request,
                expected_request_digest=d["request"]["request_digest"],
                expected_profile_digest=vision.profile_digest(),
            )
        except Exception as error:
            submitted = _received(granted, bundle, request, error=error)
        else:
            submitted = _received(granted, bundle, request, generated=generation)
    return settle(
        execution_connection,
        granted,
        submitted,
        command_id=str(uuid4()),
        expected_method_digest=expected_method_digest,
    )
