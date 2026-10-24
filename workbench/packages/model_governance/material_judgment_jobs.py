"""Native complete-rule job registration; funding and execution are separate."""

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.review_identity import digest
from packages.model_governance import material_cost_quotes as quotes
from packages.model_governance import material_input_renewals as renewals
from packages.model_governance import material_verification_commands as commands
from packages.model_governance import material_verification_program as program
from packages.model_governance import native_rpc_audit as audit
from packages.model_governance import package_material_cost as cost
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-judgment-jobs.sql"
GROUP = "tender_material_judgment_submit"
RPCS = (
    "material_judgment_job.start(uuid,text,uuid,text,uuid)",
    "material_judgment_job.read(uuid,text)",
    "material_judgment_job.refresh(uuid,text,uuid,text,bigint,uuid)",
)
UUID_FIELDS = frozenset(
    {
        "job_id",
        "command_id",
        "intent_command_id",
        "profile_id",
        "bid_id",
        "scope_id",
        "seal_id",
        "quote_id",
        "initial_renewal_id",
        "initial_evidence_id",
    }
)
SHA_FIELDS = frozenset(
    {
        "intent_command_digest",
        "profile_digest",
        "scope_digest",
        "seal_digest",
        "quote_digest",
        "material_input_digest",
        "context_digest",
        "context_method_digest",
        "findings_digest",
        "initial_renewal_digest",
        "job_method_digest",
        "native_sql_method_digest",
    }
)
TRUE_FIELDS = frozenset({"software_job_registered", "native_binding_verified"})
FALSE_FIELDS = renewals.FALSE_FIELDS
DETAIL_FIELDS = frozenset(
    {
        "version",
        "profile_head_revision",
        "rule_ids",
        "slots",
        "required_valid_slots",
        "max_attempts_per_slot",
        "maximum_external_calls",
        "currency",
        "required_reservation_minor",
        "budget_ceiling_minor",
        "origin",
        "generation",
        "status",
        "recorded_by",
        "recorded_by_oid",
        "request_login",
        "request_login_oid",
        "recorded_at",
    }
)
KNOWN_ERRORS = frozenset(
    "JUDGMENT_JOB_" + s
    for s in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "NOT_FOUND",
        "REFERENCE_MISMATCH",
        "CURRENT_STATE_UNAVAILABLE",
        "BUDGET_INSUFFICIENT",
        "INTENT_ALREADY_REGISTERED",
        "REVISION_CONFLICT",
        "NEW_EVIDENCE_REQUIRED",
    )
)


class JudgmentJobError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise JudgmentJobError("JUDGMENT_JOB_" + code)


@dataclass(frozen=True, repr=False)
class NativeJudgmentJob:
    metadata: dict


@dataclass(frozen=True, repr=False)
class NativeJobEvidence:
    metadata: dict


@dataclass(frozen=True, repr=False)
class JudgmentJobObservation:
    record: NativeJudgmentJob
    evidence: NativeJobEvidence
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "material-judgment-job-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "renewal_method": renewals.method_digest(),
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


def _functions():
    own = (
        ("start", "uuid, text, uuid, text, uuid", "judgment_job_start", True, "v", "jsonb", True),
        ("read", "uuid, text", "judgment_job_read", True, "v", "jsonb", True),
        (
            "refresh",
            "uuid, text, uuid, text, bigint, uuid",
            "judgment_job_refresh",
            True,
            "v",
            "jsonb",
            True,
        ),
        ("native_method_digest", "", "judgment_job_method", False, "s", "text", False),
        ("current_context", "uuid, uuid", "judgment_job_context", False, "v", "jsonb", False),
        ("lock_inputs", "uuid", "judgment_job_locks", False, "v", "void", False),
    )
    older = (
        (
            "record",
            "uuid, text, uuid, text, uuid, text, uuid, text, uuid",
            "input_renewal_write",
            True,
            "v",
            "jsonb",
            False,
        ),
        ("read", "uuid, text", "input_renewal_read", True, "v", "jsonb", False),
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
    return (
        tuple(audit.FunctionSpec(SQL_FILE, "material_judgment_job", *spec) for spec in own)
        + tuple(
            audit.FunctionSpec(renewals.SQL_FILE, "material_input_renewal", *spec) for spec in older
        )
        + tuple(replace(spec, caller_execute=False) for spec in quotes._functions())
    )


def _audit(cursor):
    try:
        audit.audit(
            cursor,
            group=GROUP,
            rpcs=RPCS,
            schema="material_judgment_job",
            tables=(
                "profiles",
                "profile_heads",
                "jobs",
                "slots",
                "evidence_events",
                "evidence_heads",
                "outbox",
            ),
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


def _login(value):
    return type(value) is str and 1 <= len(value) <= 63


def _record(value):
    d = _envelope(value)
    if (
        set(d) != UUID_FIELDS | SHA_FIELDS | TRUE_FIELDS | FALSE_FIELDS | DETAIL_FIELDS
        or d["version"] != "material-judgment-job/1"
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
        or type(d["origin"]) is not str
        or d["origin"] not in {"synthetic_mechanism", "current_prebid"}
        or type(d["generation"]) is not int
        or d["generation"] != 1
        or d["status"] != "awaiting_budget_reservation"
        or type(d["currency"]) is not str
        or d["currency"] not in {"USD", "CNY"}
        or not cost._integer(d["required_reservation_minor"])
        or not cost._integer(d["budget_ceiling_minor"])
        or d["budget_ceiling_minor"] < d["required_reservation_minor"]
        or not cost._integer(d["max_attempts_per_slot"], minimum=1, maximum=5)
        or not program._oid(d["recorded_by_oid"])
        or not program._oid(d["request_login_oid"])
        or not _login(d["recorded_by"])
        or not _login(d["request_login"])
        or d["recorded_by"] == d["request_login"]
        or d["recorded_by_oid"] == d["request_login_oid"]
    ):
        fail("NATIVE_RESULT_INVALID")
    rules, slots = d["rule_ids"], d["slots"]
    if (
        type(rules) is not list
        or not 1 <= len(rules) <= 400
        or any(type(r) is not str for r in rules)
        or len(set(rules)) != len(rules)
        or type(slots) is not list
        or len(slots) != 3 * len(rules)
    ):
        fail("NATIVE_RESULT_INVALID")
    for rule in rules:
        _uuid(rule)
    identities = []
    for ordinal, rule in enumerate(rules, 1):
        for number in range(1, 4):
            item = slots[(ordinal - 1) * 3 + number - 1]
            if type(item) is not dict or set(item) != {
                "slot_id",
                "rule_id",
                "rule_ordinal",
                "slot_number",
                "max_attempts",
            }:
                fail("NATIVE_RESULT_INVALID")
            _uuid(item["slot_id"])
            if (
                item["rule_id"] != rule
                or type(item["rule_ordinal"]) is not int
                or item["rule_ordinal"] != ordinal
                or type(item["slot_number"]) is not int
                or item["slot_number"] != number
                or type(item["max_attempts"]) is not int
                or item["max_attempts"] != d["max_attempts_per_slot"]
            ):
                fail("NATIVE_RESULT_INVALID")
            identities.append(item["slot_id"])
    if (
        len(set(identities)) != len(identities)
        or type(d["required_valid_slots"]) is not int
        or d["required_valid_slots"] != len(slots)
        or type(d["maximum_external_calls"]) is not int
        or d["maximum_external_calls"] != len(slots) * d["max_attempts_per_slot"]
    ):
        fail("NATIVE_RESULT_INVALID")
    _time(d["recorded_at"])
    return NativeJudgmentJob(deepcopy(value))


def _event(value):
    d = _envelope(value)
    ids = {"event_id", "job_id", "command_id", "renewal_id"}
    fields = ids | {
        "version",
        "job_digest",
        "revision",
        "previous_revision",
        "renewal_digest",
        "recorded_at",
        "recorded_by",
        "recorded_by_oid",
    }
    if set(d) != fields or d["version"] != "material-judgment-evidence/1":
        fail("NATIVE_RESULT_INVALID")
    for k in ids:
        _uuid(d[k])
    if (
        not is_digest(d["job_digest"])
        or not is_digest(d["renewal_digest"])
        or not commands._revision(d["revision"])
        or type(d["previous_revision"]) is not int
        or d["previous_revision"] != d["revision"] - 1
        or not _login(d["recorded_by"])
        or not program._oid(d["recorded_by_oid"])
    ):
        fail("NATIVE_RESULT_INVALID")
    _time(d["recorded_at"])
    return NativeJobEvidence(deepcopy(value))


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
        error_code = "JUDGMENT_JOB_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "JUDGMENT_JOB_UNAVAILABLE"
        )
    if error_code:
        raise JudgmentJobError(error_code)
    return result


def _references(*, uuids, digests):
    for identity in uuids:
        _uuid(identity)
    if any(not is_digest(v) for v in digests):
        fail("DIGEST_INVALID")


def start(
    connection,
    *,
    renewal_id,
    expected_renewal_digest,
    profile_id,
    expected_profile_digest,
    command_id,
    expected_method_digest,
):
    _references(
        uuids=(renewal_id, profile_id, command_id),
        digests=(expected_renewal_digest, expected_profile_digest),
    )

    def validate(value):
        result = _record(value)
        d = result.metadata["document"]
        if (
            d["initial_renewal_id"] != renewal_id
            or d["initial_renewal_digest"] != expected_renewal_digest
            or d["profile_id"] != profile_id
            or d["profile_digest"] != expected_profile_digest
            or d["command_id"] != command_id
            or d["job_method_digest"] != expected_method_digest
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_judgment_job.start(%s,%s,%s,%s,%s) AS value",
        (renewal_id, expected_renewal_digest, profile_id, expected_profile_digest, command_id),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def refresh(
    connection,
    *,
    job_id,
    expected_job_digest,
    renewal_id,
    expected_renewal_digest,
    expected_revision,
    command_id,
    expected_method_digest,
):
    _references(
        uuids=(job_id, renewal_id, command_id),
        digests=(expected_job_digest, expected_renewal_digest),
    )
    if not commands._revision(expected_revision):
        fail("REVISION_INVALID")

    def validate(value):
        result = _event(value)
        d = result.metadata["document"]
        if (
            d["job_id"] != job_id
            or d["job_digest"] != expected_job_digest
            or d["renewal_id"] != renewal_id
            or d["renewal_digest"] != expected_renewal_digest
            or d["command_id"] != command_id
            or d["previous_revision"] != expected_revision
        ):
            fail("NATIVE_RESULT_INVALID")
        return result

    return _execute(
        connection,
        "SELECT material_judgment_job.refresh(%s,%s,%s,%s,%s,%s) AS value",
        (
            job_id,
            expected_job_digest,
            renewal_id,
            expected_renewal_digest,
            expected_revision,
            command_id,
        ),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(connection, *, job_id, expected_job_digest, expected_method_digest):
    _references(uuids=(job_id,), digests=(expected_job_digest,))

    def validate(value):
        if type(value) is not dict or set(value) != {"record", "evidence", "current"}:
            fail("NATIVE_RESULT_INVALID")
        result = _record(value["record"])
        evidence = _event(value["evidence"])
        d = result.metadata["document"]
        e = evidence.metadata["document"]
        current = value["current"]
        flags = {
            "profile_current",
            "renewal_current",
            "request_current",
            "slots_intact",
            "software_preparation_current",
            "software_budget_sufficient",
        }
        blocked = {
            "fee_ledger_reserved",
            "execution_authorized",
            "send_lease_granted",
            "atomic_snapshot_verified",
        }
        if (
            d["job_id"] != job_id
            or result.metadata["digest"] != expected_job_digest
            or e["job_id"] != job_id
            or e["job_digest"] != expected_job_digest
            or e["recorded_by"] != d["recorded_by"]
            or e["recorded_by_oid"] != d["recorded_by_oid"]
            or type(current) is not dict
            or set(current) != flags | blocked | {"observed_at", "evidence_revision"}
            or any(type(current[k]) is not bool for k in flags)
            or any(current[k] is not False for k in blocked)
            or current["evidence_revision"] != e["revision"]
            or type(current["evidence_revision"]) is not int
        ):
            fail("NATIVE_RESULT_INVALID")
        if current["software_preparation_current"] and not all(
            current[k]
            for k in {"profile_current", "renewal_current", "request_current", "slots_intact"}
        ):
            fail("NATIVE_RESULT_INVALID")
        if current["software_budget_sufficient"] and not current["software_preparation_current"]:
            fail("NATIVE_RESULT_INVALID")
        _time(current["observed_at"])
        metadata = {
            "version": "material-judgment-job-observation/1",
            "method_digest": method_digest(),
            **deepcopy(value),
        }
        return JudgmentJobObservation(result, evidence, metadata | {"digest": digest(metadata)})

    return _execute(
        connection,
        "SELECT material_judgment_job.read(%s,%s) AS value",
        (job_id, expected_job_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
