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
    row = c.execute(
        "SELECT current_user=session_user AS direct,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=session_user"
    ).fetchone()
    if (
        row is None
        or not row["direct"]
        or not row["rolcanlogin"]
        or any(
            row[k]
            for k in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")
        )
    ):
        fail("INDEPENDENT_LOGIN_REQUIRED")
    membership = c.execute(
        "WITH RECURSIVE memberships(id) AS (SELECT roleid FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=session_user) UNION SELECT m.roleid FROM pg_auth_members m JOIN memberships p ON m.member=p.id) SELECT r.rolname FROM memberships m JOIN pg_roles r ON r.oid=m.id"
    ).fetchall()
    if {row["rolname"] for row in membership} != {GROUP}:
        fail("INDEPENDENT_MEMBERSHIP_REQUIRED")
    if c.execute(
        "SELECT has_database_privilege(current_user,current_database(),'CREATE') OR EXISTS(SELECT FROM pg_namespace n WHERE left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' AND has_schema_privilege(current_user,n.oid,'CREATE')) AS bad"
    ).fetchone()["bad"]:
        fail("CREATE_PRIVILEGE")
    if c.execute(
        "SELECT EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace WHERE t.relkind IN ('r','p','v','m','f') AND left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' AND (has_table_privilege(current_user,t.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_any_column_privilege(current_user,t.oid,'SELECT,INSERT,UPDATE,REFERENCES'))) AS bad"
    ).fetchone()["bad"]:
        fail("DIRECT_TABLE_PRIVILEGE")
    if c.execute(
        "SELECT EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.prosecdef AND left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' AND has_schema_privilege(current_user,n.oid,'USAGE') AND has_function_privilege(current_user,p.oid,'EXECUTE') AND p.oid<>coalesce(to_regprocedure(%s)::oid,0)) AS bad",
        (RPC,),
    ).fetchone()["bad"]:
        fail("EXCESS_DEFINER_PRIVILEGE")


def _native_method(c):
    row = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,l.lanname,p.prorettype::regtype::text AS returns,p.proowner=(SELECT oid FROM pg_roles WHERE rolname=session_user) AS caller_owner FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",
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
