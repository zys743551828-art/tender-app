"""Owned current package facts through one audited, narrow native RPC.

The independent LOGIN cannot read any business table directly. This observation
retains declarations and gaps; it does not certify semantic necessary scope.
"""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain import review_identity
from packages.domain.review_identity import canonical, digest
from packages.model_governance import read_purpose
from packages.model_governance.technical_png import digest_bytes

GROUP = "tender_current_scope_verify"
RPC = "current_technical_scope.observe(uuid,uuid,text)"
MAX_BYTES = 8 * 1024 * 1024
SQL_FILE = Path(__file__).parents[2] / "deploy/sql/package-current-scope-runtime.sql"
KNOWN_ERRORS = {
    "CURRENT_SCOPE_OWNED_READ_ONLY_TRANSACTION_REQUIRED",
    "CURRENT_SCOPE_INDEPENDENT_LOGIN_REQUIRED",
    "CURRENT_SCOPE_NOT_FOUND",
    "CURRENT_SCOPE_TOO_LARGE",
    "CURRENT_SCOPE_CORRUPT",
    "CURRENT_SCOPE_NOT_CURRENT_PREBID",
    "CURRENT_SCOPE_IDENTITY_CHANGED",
    "CURRENT_SCOPE_TARGET_CHANGED",
    "CURRENT_SCOPE_INVENTORY_CHANGED",
    "CURRENT_SCOPE_RULES_CHANGED",
    "CURRENT_SCOPE_AUTHORITY_CHANGED",
}


class CurrentScopeError(ValueError):
    pass


def fail(code):
    raise CurrentScopeError("CURRENT_SCOPE_" + code)


@dataclass(frozen=True, repr=False)
class CurrentScopeObservation:
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "package-current-scope-method/1",
            "source_digest": digest_bytes(Path(__file__).read_bytes()),
            "sql_digest": digest_bytes(SQL_FILE.read_bytes()),
            "canonical_source_digest": digest_bytes(Path(review_identity.__file__).read_bytes()),
            "read_purpose_source_digest": digest_bytes(Path(read_purpose.__file__).read_bytes()),
            "maximum_bytes": MAX_BYTES,
            "authority_grants": False,
        }
    )


def _expected_native_body():
    parts = SQL_FILE.read_text(encoding="utf-8").split("$current_scope$")
    if len(parts) != 3:
        fail("METHOD_UNAVAILABLE")
    return parts[1]


def _role(c):
    policy = read_purpose.ReadPurpose(groups=frozenset({GROUP}), definer_calls=(RPC,))
    try:
        read_purpose.require_read_purpose(c, policy)
    except read_purpose.ReadPurposeError as error:
        aliases = {
            "EXCESS_TABLE_PRIVILEGE": "DIRECT_TABLE_PRIVILEGE",
            "DEFINER_EXECUTE_PRIVILEGE": "EXCESS_DEFINER_PRIVILEGE",
            "DATABASE_CREATE_PRIVILEGE": "CREATE_PRIVILEGE",
            "SCHEMA_WRITE_PRIVILEGE": "CREATE_PRIVILEGE",
        }
        fail(aliases.get(error.code, error.code))


def _native_method(c):
    row = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,l.lanname,p.prorettype::regtype::text AS returns,pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",
        (RPC,),
    ).fetchone()
    if (
        row is None
        or row["prosrc"] != _expected_native_body()
        or not row["prosecdef"]
        or row["provolatile"] != "v"
        or row["lanname"] != "plpgsql"
        or row["returns"] != "jsonb"
        or row["caller_owner"]
        or row["proconfig"] != ["search_path=pg_catalog, design, pg_temp"]
    ):
        fail("NATIVE_METHOD_MISMATCH")
    return digest_bytes(row["prosrc"].encode())


def observe(connection, *, bid_id, scope_id, expected_scope_digest, expected_method_digest):
    try:
        if any(str(UUID(value)) != value for value in (bid_id, scope_id)):
            fail("INVALID_ID")
    except (ValueError, TypeError, AttributeError):
        fail("INVALID_ID")
    if (
        not isinstance(expected_scope_digest, str)
        or len(expected_scope_digest) != 64
        or any(char not in "0123456789abcdef" for char in expected_scope_digest)
    ):
        fail("INVALID_DIGEST")
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        fail("IDLE_CONNECTION_REQUIRED")
    try:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as c:
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                c.execute("SET LOCAL statement_timeout='5s'")
                _role(c)
                native_digest = _native_method(c)
                value = c.execute(
                    "SELECT current_technical_scope.observe(%s,%s,%s) AS value",
                    (bid_id, scope_id, expected_scope_digest),
                ).fetchone()["value"]
                if method_digest() != method:
                    fail("METHOD_CHANGED")
    except psycopg.Error as error:
        code = error.diag.message_primary
        if code in KNOWN_ERRORS:
            raise CurrentScopeError(code) from None
        fail("NATIVE_UNAVAILABLE")
    if (
        not isinstance(value, dict)
        or value.get("version") != "package-current-scope-facts/1"
        or value.get("bid_id") != bid_id
        or value.get("scope", {}).get("digest") != expected_scope_digest
    ):
        fail("NATIVE_RESULT_INVALID")
    try:
        for key in ("scope", "target", "authority", "inventory"):
            if digest(value[key]["manifest"]) != value[key]["digest"]:
                fail("NATIVE_RESULT_INVALID")
        if len(canonical(value)) > MAX_BYTES:
            fail("TOO_LARGE")
    except CurrentScopeError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        fail("NATIVE_RESULT_INVALID")
    result = {**value, "method_digest": method, "native_body_digest": native_digest}
    return CurrentScopeObservation(result | {"digest": digest(result)})
