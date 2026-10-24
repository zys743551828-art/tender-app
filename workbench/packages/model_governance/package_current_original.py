"""Native private locator observation, separate from byte and input authority.

No business configuration, connection factory, signer or permission repair.
Only the controlled reader consumes the private locator; receipts contain its hash.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain import review_identity
from packages.domain.review_identity import digest
from packages.model_governance import package_current_scope as scope
from packages.model_governance import read_purpose
from packages.model_governance.technical_png import digest_bytes

GROUP = "tender_current_original_verify"
RPC = "current_technical_original.locate(uuid,uuid,text,uuid,text)"
SQL_FILE = Path(__file__).parents[2] / "deploy/sql/package-current-original-runtime.sql"
MAX_LOCATOR_BYTES = 4096
MAX_ORIGINAL_BYTES = 32 * 1024 * 1024
KNOWN_ERRORS = scope.KNOWN_ERRORS | {
    "CURRENT_ORIGINAL_" + code
    for code in (
        "INDEPENDENT_LOGIN_REQUIRED",
        "FILE_SET_INVALID",
        "NOT_IN_SCOPE",
        "SOURCE_SET_INVALID",
        "SOURCE_LIMIT",
        "SOURCE_CLOSURE_CHANGED",
        "SOURCES_CHANGED",
        "BINDING_INVALID",
    )
}


class CurrentOriginalError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise CurrentOriginalError("CURRENT_ORIGINAL_" + code)


@dataclass(frozen=True, repr=False)
class OriginalLocatorObservation:
    metadata: dict
    locator: str


def method_digest():
    return digest(
        {
            "version": "package-current-original-method/1",
            "source_digest": digest_bytes(Path(__file__).read_bytes()),
            "sql_digest": digest_bytes(SQL_FILE.read_bytes()),
            "scope_method_digest": scope.method_digest(),
            "canonical_source_digest": digest_bytes(Path(review_identity.__file__).read_bytes()),
            "maximum_locator_bytes": MAX_LOCATOR_BYTES,
            "maximum_original_bytes": MAX_ORIGINAL_BYTES,
            "authority_grants": False,
        }
    )


def _native_method(c):
    parts = SQL_FILE.read_text(encoding="utf-8").split("$current_original$")
    if len(parts) != 3:
        fail("METHOD_UNAVAILABLE")
    row = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,l.lanname,p.prorettype::regtype::text AS returns,pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",
        (RPC,),
    ).fetchone()
    if (
        row is None
        or row["prosrc"] != parts[1]
        or not row["prosecdef"]
        or row["provolatile"] != "v"
        or row["lanname"] != "plpgsql"
        or row["returns"] != "jsonb"
        or row["caller_owner"]
        or row["proconfig"] != ["search_path=pg_catalog, design, pg_temp"]
    ):
        fail("NATIVE_METHOD_MISMATCH")
    return digest_bytes(row["prosrc"].encode())


def observe(
    connection,
    *,
    bid_id,
    scope_id,
    expected_scope_digest,
    document_version_id,
    expected_original_digest,
    expected_method_digest,
):
    valid = False
    try:
        valid = all(str(UUID(v)) == v for v in (bid_id, scope_id, document_version_id))
    except (ValueError, TypeError, AttributeError):
        pass
    if not valid:
        fail("INVALID_ID")
    for value in (expected_scope_digest, expected_original_digest):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            fail("INVALID_DIGEST")
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        fail("IDLE_CONNECTION_REQUIRED")
    failure = None
    try:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as c:
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                c.execute("SET LOCAL statement_timeout='5s'")
                read_purpose.require_read_purpose(
                    c,
                    read_purpose.ReadPurpose(
                        groups=frozenset({GROUP, scope.GROUP}), definer_calls=(RPC, scope.RPC)
                    ),
                )
                scope_body = scope._native_method(c)
                native_body = _native_method(c)
                value = c.execute(
                    "SELECT current_technical_original.locate(%s,%s,%s,%s,%s) AS value",
                    (
                        bid_id,
                        scope_id,
                        expected_scope_digest,
                        document_version_id,
                        expected_original_digest,
                    ),
                ).fetchone()["value"]
                if method_digest() != method:
                    fail("METHOD_CHANGED")
    except read_purpose.ReadPurposeError as error:
        failure = "CURRENT_ORIGINAL_" + error.code
    except scope.CurrentScopeError:
        failure = "CURRENT_ORIGINAL_SCOPE_NATIVE_METHOD_MISMATCH"
    except psycopg.Error as error:
        code = error.diag.message_primary
        failure = code if code in KNOWN_ERRORS else "CURRENT_ORIGINAL_NATIVE_UNAVAILABLE"
    # Discard native exception context; it may carry private query/result values.
    if failure:
        raise CurrentOriginalError(failure)
    expected = {
        "version": "package-current-original-locator/1",
        "bid_id": bid_id,
        "scope_id": scope_id,
        "scope_digest": expected_scope_digest,
        "document_version_id": document_version_id,
        "source_digest": expected_original_digest,
        "native_current_original_locator_checked": True,
        "original_bytes_reverified": False,
        "necessary_scope_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    if not isinstance(value, dict) or any(
        type(value.get(k)) is not type(v) or value[k] != v for k, v in expected.items()
    ):
        fail("NATIVE_RESULT_INVALID")
    locator = value.get("locator")
    if (
        not isinstance(locator, str)
        or not 1 <= len(locator.encode()) <= MAX_LOCATOR_BYTES
        or any(ord(c) < 32 or ord(c) == 127 for c in locator)
        or type(value.get("source_byte_size")) is not int
        or not 1 <= value["source_byte_size"] <= MAX_ORIGINAL_BYTES
    ):
        fail("NATIVE_RESULT_INVALID")
    public = {k: v for k, v in value.items() if k != "locator"}
    public.update(
        method_digest=method,
        native_body_digest=native_body,
        scope_native_body_digest=scope_body,
        locator_digest=digest_bytes(locator.encode()),
    )
    return OriginalLocatorObservation(public | {"digest": digest(public)}, locator)
