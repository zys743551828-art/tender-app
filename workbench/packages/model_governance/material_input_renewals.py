"""Fresh native evidence for unchanged sealed input and quote, never a send lease."""

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_cost_quotes as quotes
from packages.model_governance import material_verification_commands as commands
from packages.model_governance import material_verification_program as program
from packages.model_governance import native_rpc_audit as audit
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-input-renewals.sql"
GROUP = "tender_material_input_renew"
RPCS = (
    "material_input_renewal.record(uuid,text,uuid,text,uuid,text,uuid,text,uuid)",
    "material_input_renewal.read(uuid,text)",
)
UUID_FIELDS = frozenset(
    {
        "renewal_id",
        "command_id",
        "profile_id",
        "seal_id",
        "quote_id",
        "admission_verification_id",
        "current_verification_id",
        "quote_policy_id",
        "bid_id",
        "scope_id",
    }
)
SHA_FIELDS = frozenset(
    {
        "profile_digest",
        "seal_digest",
        "quote_digest",
        "admission_verification_digest",
        "current_verification_digest",
        "material_input_digest",
        "context_digest",
        "context_method_digest",
        "findings_digest",
        "quote_policy_digest",
        "scope_digest",
        "renew_method_digest",
        "native_sql_method_digest",
    }
)
TRUE_FIELDS = frozenset(
    {
        "software_current_evidence_verified",
        "frozen_input_preserved",
        "frozen_quote_preserved",
        "native_binding_verified",
    }
)
FALSE_FIELDS = frozenset(
    {
        "fee_ledger_reserved",
        "automatic_retry",
        "input_authority_granted",
        "execution_authorized",
        "send_lease_granted",
        "atomic_snapshot_verified",
        "actual_human_reading_verified",
        "model_context_fit_proven",
        "request_body_limit_verified",
        "account_price_confirmed",
    }
)
KNOWN_ERRORS = frozenset(
    "INPUT_RENEWAL_" + s
    for s in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "NOT_FOUND",
        "PROGRAM_COMMAND_MISMATCH",
        "PROFILE_MISMATCH",
        "CURRENT_STATE_UNAVAILABLE",
    )
)


class InputRenewalError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise InputRenewalError("INPUT_RENEWAL_" + code)


@dataclass(frozen=True, repr=False)
class NativeInputRenewal:
    metadata: dict


@dataclass(frozen=True, repr=False)
class InputRenewalObservation:
    record: NativeInputRenewal
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "material-input-renewal-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "quote_method": quotes.method_digest(),
            "frozen_input_and_quote_unchanged": True,
            "logical_command_from_native_program": True,
            "grants_execution": False,
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


def _audit(cursor):
    own = (
        (
            "record",
            "uuid, text, uuid, text, uuid, text, uuid, text, uuid",
            "input_renewal_write",
            True,
            "v",
            "jsonb",
            True,
        ),
        ("read", "uuid, text", "input_renewal_read", True, "v", "jsonb", True),
        ("native_method_digest", "", "input_renewal_method", False, "s", "text", False),
        (
            "current_context",
            "uuid, uuid, uuid, uuid",
            "input_renewal_context",
            False,
            "v",
            "jsonb",
            False,
        ),
    )
    functions = tuple(audit.FunctionSpec(SQL_FILE, "material_input_renewal", *spec) for spec in own)
    functions += tuple(replace(spec, caller_execute=False) for spec in quotes._functions())
    try:
        audit.audit(
            cursor,
            group=GROUP,
            rpcs=RPCS,
            schema="material_input_renewal",
            tables=("profiles", "profile_heads", "records"),
            functions=functions,
        )
    except audit.NativeMethodMismatch:
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
        | FALSE_FIELDS
        | {
            "version",
            "profile_head_revision",
            "origin",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
            "status",
            "budget_sufficient_under_policy",
        }
        or len(canonical(value)) > 32768
        or d["version"] != "material-input-renewal/1"
        or not is_digest(value["digest"])
        or digest(d) != value["digest"]
        or any(not is_digest(d[k]) for k in SHA_FIELDS)
        or any(d[k] is not True for k in TRUE_FIELDS)
        or any(d[k] is not False for k in FALSE_FIELDS)
        or type(d["origin"]) is not str
        or d["origin"] not in {"synthetic_mechanism", "current_prebid"}
        or not commands._revision(d["profile_head_revision"])
        or not program._oid(d["recorded_by_oid"])
        or type(d["recorded_by"]) is not str
        or not 1 <= len(d["recorded_by"]) <= 63
        or type(d["budget_sufficient_under_policy"]) is not bool
        or d["admission_verification_id"] == d["current_verification_id"]
        or d["admission_verification_digest"] == d["current_verification_digest"]
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in UUID_FIELDS:
        _uuid(d[k])
    _time(d["recorded_at"])
    if d["status"] != (
        "current_evidence_registered"
        if d["origin"] == "current_prebid"
        else "synthetic_current_evidence_registered"
    ):
        fail("NATIVE_RESULT_INVALID")
    return NativeInputRenewal(deepcopy(value))


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
        error_code = "INPUT_RENEWAL_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "INPUT_RENEWAL_UNAVAILABLE"
        )
    if error_code:
        raise InputRenewalError(error_code)
    return result


def record(
    connection,
    *,
    seal_id,
    expected_seal_digest,
    quote_id,
    expected_quote_digest,
    verification_id,
    expected_verification_digest,
    profile_id,
    expected_profile_digest,
    command_id,
    expected_method_digest,
):
    for identity in (seal_id, quote_id, verification_id, profile_id, command_id):
        _uuid(identity)
    if any(
        not is_digest(v)
        for v in (
            expected_seal_digest,
            expected_quote_digest,
            expected_verification_digest,
            expected_profile_digest,
        )
    ):
        fail("DIGEST_INVALID")

    def validate(value):
        result = _record(value)
        d = result.metadata["document"]
        if (
            d["seal_id"] != seal_id
            or d["seal_digest"] != expected_seal_digest
            or d["quote_id"] != quote_id
            or d["quote_digest"] != expected_quote_digest
            or d["current_verification_id"] != verification_id
            or d["current_verification_digest"] != expected_verification_digest
            or d["profile_id"] != profile_id
            or d["profile_digest"] != expected_profile_digest
            or d["command_id"] != command_id
            or d["renew_method_digest"] != expected_method_digest
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_input_renewal.record(%s,%s,%s,%s,%s,%s,%s,%s,%s) AS value",
        (
            seal_id,
            expected_seal_digest,
            quote_id,
            expected_quote_digest,
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


def read(connection, *, renewal_id, expected_renewal_digest, expected_method_digest):
    _uuid(renewal_id)
    if not is_digest(expected_renewal_digest):
        fail("DIGEST_INVALID")

    def validate(value):
        if type(value) is not dict or set(value) != {"record", "current"}:
            fail("NATIVE_RESULT_INVALID")
        result = _record(value["record"])
        d = result.metadata["document"]
        current = value["current"]
        flags = {
            "profile_current",
            "seal_current",
            "quote_current",
            "verification_current",
            "software_evidence_current",
            "software_budget_sufficient",
        }
        blocked = {
            "fee_ledger_reserved",
            "execution_authorized",
            "send_lease_granted",
            "atomic_snapshot_verified",
        }
        if (
            d["renewal_id"] != renewal_id
            or result.metadata["digest"] != expected_renewal_digest
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
        _time(current["observed_at"])
        eligible = (
            all(
                current[k]
                for k in {
                    "profile_current",
                    "seal_current",
                    "quote_current",
                    "verification_current",
                }
            )
            and current["profile_head_revision"] == d["profile_head_revision"]
        )
        if current["software_evidence_current"] is not eligible or current[
            "software_budget_sufficient"
        ] is not (eligible and d["budget_sufficient_under_policy"]):
            fail("NATIVE_RESULT_INVALID")
        metadata = {
            "version": "material-input-renewal-observation/1",
            "method_digest": method_digest(),
            **deepcopy(value),
        }
        return InputRenewalObservation(result, metadata | {"digest": digest(metadata)})

    return _execute(
        connection,
        "SELECT material_input_renewal.read(%s,%s) AS value",
        (renewal_id, expected_renewal_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
