"""Native full-input reservation quotes; never money reservations or send grants."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_input_authority as authority
from packages.model_governance import material_input_seals as seals
from packages.model_governance import material_verification_commands as commands
from packages.model_governance import material_verification_program as program
from packages.model_governance import native_rpc_audit as audit
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

SQL_FILE = Path(__file__).parents[2] / "deploy/sql/material-cost-quotes.sql"
GROUP = "tender_material_cost_quote"
RPCS = (
    "material_cost_quote.quote(uuid,text,uuid,text,uuid,integer,text,bigint)",
    "material_cost_quote.read(uuid,text)",
)
UUID_FIELDS = frozenset({"quote_id", "command_id", "seal_id", "policy_id", "bid_id", "scope_id"})
SHA_FIELDS = frozenset(
    {
        "seal_digest",
        "material_input_digest",
        "policy_digest",
        "context_digest",
        "context_method_digest",
        "scope_digest",
        "price_policy_digest",
        "cost_method_digest",
        "provider_profile_digest",
        "serializer_digest",
        "judgment_method_digest",
        "quote_method_digest",
        "native_sql_method_digest",
        "quote_digest",
    }
)
TRUE_FIELDS = frozenset(
    {"software_quote_verified", "price_policy_native_verified", "native_binding_verified"}
)
FALSE_FIELDS = frozenset(
    {
        "account_price_confirmed",
        "model_context_fit_proven",
        "request_body_limit_verified",
        "fee_ledger_reserved",
        "automatic_retry",
        "input_authority_granted",
        "execution_authorized",
        "send_lease_granted",
        "atomic_snapshot_verified",
    }
)
KNOWN_ERRORS = frozenset(
    "COST_QUOTE_" + s
    for s in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "SEAL_NOT_FOUND",
        "POLICY_MISMATCH",
        "CURRENT_STATE_UNAVAILABLE",
        "BUDGET_INVALID",
        "RULE_SOURCE_INCOMPLETE",
        "RULES_INVALID",
        "AMOUNT_OVERFLOW",
        "NOT_FOUND",
    )
)


class CostQuoteError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise CostQuoteError("COST_QUOTE_" + code)


@dataclass(frozen=True, repr=False)
class NativeCostQuote:
    metadata: dict


@dataclass(frozen=True, repr=False)
class CostQuoteObservation:
    record: NativeCostQuote
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "material-cost-quote-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "seal_method": seals.method_digest(),
            "audit_source": sha(Path(audit.__file__).read_bytes()),
            "cost_source": sha(Path(cost.__file__).read_bytes()),
            "vision_source": sha(Path(vision.__file__).read_bytes()),
            "price_is_not_account_contract": True,
            "quote_is_not_reservation": True,
        }
    )


def _functions():
    declarations = (
        (
            SQL_FILE,
            "material_cost_quote",
            (
                (
                    "quote",
                    "uuid, text, uuid, text, uuid, integer, text, bigint",
                    "cost_quote_write",
                    True,
                    "v",
                    "jsonb",
                    True,
                ),
                ("read", "uuid, text", "cost_quote_read", True, "v", "jsonb", True),
                ("native_method_digest", "", "cost_quote_method", False, "s", "text", False),
                ("current_context", "uuid, uuid", "cost_quote_context", False, "v", "jsonb", False),
            ),
        ),
        (
            seals.SQL_FILE,
            "material_input_seal",
            (
                (
                    "seal",
                    "uuid, text, uuid, text, uuid",
                    "input_seal_write",
                    True,
                    "v",
                    "jsonb",
                    False,
                ),
                ("read", "uuid, text", "input_seal_read", True, "v", "jsonb", False),
                ("native_method_digest", "", "input_seal_method", False, "s", "text", False),
                ("current_context", "uuid, uuid", "input_seal_context", False, "v", "jsonb", False),
            ),
        ),
        (
            authority.SQL_FILE,
            "material_input_authority",
            (
                (
                    "qualify",
                    "uuid, text, uuid, text, uuid",
                    "input_authority_qualify",
                    True,
                    "v",
                    "jsonb",
                    False,
                ),
                ("read", "uuid, text", "input_authority_read", True, "v", "jsonb", False),
                ("native_method_digest", "", "input_authority_method", False, "s", "text", False),
                (
                    "source_current",
                    "uuid, uuid, text",
                    "input_authority_source",
                    False,
                    "s",
                    "boolean",
                    False,
                ),
                (
                    "policy_context",
                    "uuid, uuid",
                    "input_authority_context",
                    False,
                    "v",
                    "jsonb",
                    False,
                ),
            ),
        ),
    )
    return tuple(
        audit.FunctionSpec(source, schema, *spec)
        for source, schema, items in declarations
        for spec in items
    )


def _audit(cursor):
    try:
        audit.audit(
            cursor,
            group=GROUP,
            rpcs=RPCS,
            schema="material_cost_quote",
            tables=("policies", "policy_heads", "quotes"),
            functions=_functions(),
        )
    except audit.NativeMethodMismatch:
        fail("NATIVE_METHOD_MISMATCH")


def _trial(document):
    """Rebuild arithmetic at the recorded time, without asserting rule closure from JSON."""
    d = document
    try:
        p = cost.bind_policy(d["price_policy"], expected_policy_digest=d["price_policy_digest"])
        q = d["quote"]
        if type(q) is not dict:
            fail("NATIVE_RESULT_INVALID")
        rules = q.get("rule_ids")
        if type(rules) is not list or not 1 <= len(rules) <= 400 or len(set(rules)) != len(rules):
            fail("NATIVE_RESULT_INVALID")
        for identity in rules:
            commands._uuid(identity)
        attempts = q.get("max_attempts_per_slot")
        budget = q.get("budget_ceiling_minor")
        if (
            not isinstance(attempts, int)
            or not cost._integer(attempts, minimum=1, maximum=5)
            or not cost._integer(budget)
            or q.get("currency") != p.metadata["currency"]
            or p.metadata["policy_id"] != d["policy_id"]
            or p.metadata["profile_digest"] != d["provider_profile_digest"]
        ):
            fail("NATIVE_RESULT_INVALID")
        cost._policy(p, d["price_policy_digest"], d["recorded_at"])
        per_call = cost.ceiling_charge(
            p.metadata["context_token_capacity"],
            4096,
            p.metadata["input_per_million_minor"],
            p.metadata["output_per_million_minor"],
        )
        required = per_call * len(rules) * 3 * attempts
        if required > cost.SAFE_INTEGER:
            fail("NATIVE_RESULT_INVALID")
        expected = {
            "version": "package-material-reservation-quote/1",
            "method_digest": d["cost_method_digest"],
            "context_digest": d["context_digest"],
            "policy_digest": d["price_policy_digest"],
            "profile_digest": d["provider_profile_digest"],
            "serializer_digest": d["serializer_digest"],
            "as_of": d["recorded_at"],
            "currency": p.metadata["currency"],
            "minor_per_unit": 1000000,
            "rule_ids": rules,
            "required_valid_slots": len(rules) * 3,
            "max_attempts_per_slot": attempts,
            "maximum_external_calls": len(rules) * 3 * attempts,
            "reserved_input_tokens_per_call": p.metadata["context_token_capacity"],
            "reserved_output_tokens_per_call": 4096,
            "per_call_ceiling_minor": per_call,
            "required_reservation_minor": required,
            "budget_ceiling_minor": budget,
            "budget_sufficient_under_policy": budget >= required,
            "all_declared_included_rules_retained": True,
            "reservation_is_not_invoice_cap": True,
            "price_policy_native_verified": False,
            "model_context_fit_proven": False,
            "request_body_limit_verified": False,
            "fee_ledger_reserved": False,
            "automatic_retry": False,
            "native_binding_verified": False,
            "execution_authorized": False,
        }
        expected |= {"digest": digest(expected)}
        if canonical(expected) != canonical(q) or q["digest"] != d["quote_digest"]:
            fail("NATIVE_RESULT_INVALID")
        return q
    except (cost.MaterialCostError, commands.VerificationCommandError, TypeError, KeyError):
        fail("NATIVE_RESULT_INVALID")


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
            "policy_head_revision",
            "origin",
            "price_policy",
            "quote",
            "recorded_by",
            "recorded_by_oid",
            "recorded_at",
            "status",
        }
        or len(canonical(value)) > 65536
        or d["version"] != "material-cost-quote/1"
        or not is_digest(value["digest"])
        or digest(d) != value["digest"]
        or any(not is_digest(d[k]) for k in SHA_FIELDS)
        or any(d[k] is not True for k in TRUE_FIELDS)
        or any(d[k] is not False for k in FALSE_FIELDS)
        or type(d["origin"]) is not str
        or d["origin"] not in {"synthetic_mechanism", "current_prebid"}
        or not commands._revision(d["policy_head_revision"])
        or not program._oid(d["recorded_by_oid"])
        or type(d["recorded_by"]) is not str
        or not 1 <= len(d["recorded_by"]) <= 63
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in UUID_FIELDS:
        commands._uuid(d[k])
    commands._time(d["recorded_at"])
    q = _trial(d)
    if d["status"] != (
        "quoted_sufficient" if q["budget_sufficient_under_policy"] else "quoted_insufficient"
    ):
        fail("NATIVE_RESULT_INVALID")
    return NativeCostQuote(deepcopy(value))


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
        error_code = "COST_QUOTE_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "COST_QUOTE_UNAVAILABLE"
        )
    if error_code:
        raise CostQuoteError(error_code)
    return result


def quote(
    connection,
    *,
    seal_id,
    expected_seal_digest,
    policy_id,
    expected_policy_digest,
    command_id,
    max_attempts_per_slot,
    budget_currency,
    budget_ceiling_minor,
    expected_method_digest,
):
    for identifier in (seal_id, policy_id, command_id):
        commands._uuid(identifier)
    if (
        not is_digest(expected_seal_digest)
        or not is_digest(expected_policy_digest)
        or not cost._integer(max_attempts_per_slot, minimum=1, maximum=5)
        or not cost._integer(budget_ceiling_minor)
        or type(budget_currency) is not str
        or budget_currency not in {"USD", "CNY"}
    ):
        fail("REFERENCE_INVALID")

    def validate(value):
        record = _record(value)
        d = record.metadata["document"]
        q = d["quote"]
        if (
            d["seal_id"] != seal_id
            or d["seal_digest"] != expected_seal_digest
            or d["policy_id"] != policy_id
            or d["policy_digest"] != expected_policy_digest
            or d["command_id"] != command_id
            or d["quote_method_digest"] != expected_method_digest
            or d["cost_method_digest"] != cost.method_digest()
            or d["serializer_digest"] != vision.serializer_digest()
            or d["provider_profile_digest"] != vision.profile_digest()
            or d["judgment_method_digest"] != vision.judgment_method_digest()
            or q["max_attempts_per_slot"] != max_attempts_per_slot
            or q["currency"] != budget_currency
            or q["budget_ceiling_minor"] != budget_ceiling_minor
        ):
            fail("NATIVE_RESULT_INVALID")
        return record

    return _execute(
        connection,
        "SELECT material_cost_quote.quote(%s,%s,%s,%s,%s,%s,%s,%s) AS value",
        (
            seal_id,
            expected_seal_digest,
            policy_id,
            expected_policy_digest,
            command_id,
            max_attempts_per_slot,
            budget_currency,
            budget_ceiling_minor,
        ),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(connection, *, quote_id, expected_quote_digest, expected_method_digest):
    commands._uuid(quote_id)
    if not is_digest(expected_quote_digest):
        fail("DIGEST_INVALID")

    def validate(value):
        if type(value) is not dict or set(value) != {"record", "current"}:
            fail("NATIVE_RESULT_INVALID")
        record = _record(value["record"])
        d = record.metadata["document"]
        current = value["current"]
        flags = {
            "configuration_current",
            "input_current",
            "price_effective",
            "software_quote_current",
            "software_budget_sufficient",
        }
        blocked = {
            "fee_ledger_reserved",
            "execution_authorized",
            "send_lease_granted",
            "atomic_snapshot_verified",
        }
        if (
            d["quote_id"] != quote_id
            or record.metadata["digest"] != expected_quote_digest
            or type(current) is not dict
            or set(current) != flags | blocked | {"observed_at", "policy_head_revision"}
            or any(type(current[k]) is not bool for k in flags)
            or any(current[k] is not False for k in blocked)
            or (
                current["policy_head_revision"] is not None
                and not commands._revision(current["policy_head_revision"])
            )
        ):
            fail("NATIVE_RESULT_INVALID")
        commands._time(current["observed_at"])
        eligible = (
            all(current[k] for k in {"configuration_current", "input_current", "price_effective"})
            and current["policy_head_revision"] == d["policy_head_revision"]
        )
        if current["software_quote_current"] is not eligible or current[
            "software_budget_sufficient"
        ] is not (eligible and d["quote"]["budget_sufficient_under_policy"]):
            fail("NATIVE_RESULT_INVALID")
        metadata = {
            "version": "material-cost-quote-observation/1",
            "method_digest": method_digest(),
            **deepcopy(value),
        }
        return CostQuoteObservation(record, metadata | {"digest": digest(metadata)})

    return _execute(
        connection,
        "SELECT material_cost_quote.read(%s,%s) AS value",
        (quote_id, expected_quote_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )
