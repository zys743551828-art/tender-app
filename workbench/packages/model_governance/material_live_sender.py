"""Explicit process-owned /2 sender, disabled by default; never reads secrets itself."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

import httpx
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.errors import DomainError
from packages.domain.providers.deepseek_complete_vision import DeepSeekCompleteVisionClient
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_qualification_guard as guard
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import package_technical_complete_vision as vision


@dataclass(frozen=True, repr=False)
class Sender:
    account_id: str
    profile_id: str
    profile_digest: str
    credential: Callable[[str], str] = field(repr=False)
    enabled: bool = False
    transport: httpx.MockTransport | None = field(default=None, repr=False)


def validate(sender, profile_id, profile_digest):
    if type(sender) is not Sender or sender.enabled is not True:
        execution.fail("LIVE_QUALIFICATION_UNAVAILABLE")
    if (
        sender.profile_id != profile_id
        or sender.profile_digest != profile_digest
        or not callable(sender.credential)
        or sender.transport is not None
        and type(sender.transport) is not httpx.MockTransport
    ):
        execution.fail("LIVE_CONFIGURATION_MISMATCH")
    execution._uuid(sender.account_id)


def audit(connection):
    if connection.info.transaction_status != TransactionStatus.IDLE:
        execution.fail("IDLE_CONNECTION_REQUIRED")
    try:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SET LOCAL statement_timeout='5s'")
                guard.audit(cursor)
    except DomainError:
        execution.fail("QUALIFICATION_GUARD_UNAVAILABLE")


async def execute(
    preparation_connection,
    execution_connection,
    bundle,
    checked,
    *,
    sender,
    rule_id,
    slot_id,
    profile_id,
    expected_profile_digest,
    command_id,
    expected_preflight_digest,
    expected_method_digest,
):
    validate(sender, profile_id, expected_profile_digest)
    if preparation_connection is execution_connection:
        execution.fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    if expected_method_digest != execution.method_digest():
        execution.fail("METHOD_MISMATCH")
    audit(execution_connection)
    request = preflight.prepare_rule_request(
        preparation_connection,
        bundle,
        checked,
        rule_id,
        expected_preflight_digest=expected_preflight_digest,
        expected_method_digest=preflight.method_digest(),
    )
    granted = execution.begin_attempt(
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
        return granted  # No credential resolution or HTTP on replay/unknown/in-flight.
    d = granted.metadata["attempt"]["document"]
    try:
        if (
            d["version"] != "material-execution-attempt/2"
            or d["execution_mode"] != "qualified_live"
            or granted.metadata["reservation"]["document"]["account_id"] != sender.account_id
            or d["request"] != request.receipt
            or d["rule_id"] != rule_id
        ):
            execution.fail("LIVE_GRANT_MISMATCH")
        # The only credential interface is the existing client constructor.
        # The trusted host supplies this callback; it is never request data.
        key = sender.credential(sender.account_id)
        current = execution.read(
            execution_connection,
            attempt_id=d["attempt_id"],
            expected_method_digest=expected_method_digest,
        )
        if (
            current.metadata["attempt"] != granted.metadata["attempt"]
            or current.metadata.get("send_current") is not True
            or current.metadata["outcome"] is not None
            or datetime.now(timezone.utc) >= execution._time(d["send_until"])
        ):
            execution.fail("LIVE_GRANT_NOT_CURRENT")
        client = DeepSeekCompleteVisionClient(
            api_key=key, total_timeout=30, transport=sender.transport
        )
        generated = await client.generate_async(
            request,
            expected_request_digest=d["request"]["request_digest"],
            expected_profile_digest=vision.profile_digest(),
        )
    except Exception as error:
        submitted = execution._received(granted, bundle, request, error=error)
    else:
        submitted = execution._received(granted, bundle, request, generated=generated)
    # Never gate settlement on qualification. Failures before HTTP conservatively
    # retain an unresolved hold; client claims cannot manufacture a zero invoice.
    return execution.settle(
        execution_connection,
        granted,
        submitted,
        command_id=str(uuid4()),
        expected_method_digest=expected_method_digest,
    )
