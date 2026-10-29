"""Explicit B1–B5 fresh-install plan and actual API/Worker permission checks.

The plan fixes BASE_SQL and the eight optional authoring inputs. The existing
bootstrap verifies their frozen bytes before its first connection.
No consumer, model credential, tariff, budget or business record is created here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.rows import dict_row

from deploy import bootstrap_fresh as fresh
from deploy.initialize_database import file_configuration
from packages.authoring import exact_builds, exact_sources, exact_text_edits
from packages.authoring import package_input_repository as inputs

VERSION = "authoring-fresh-candidate/1"
OPTIONAL_SQL = (
    "packages/contracts/sql/authoring-package-inputs.sql",
    "packages/assistant/sql/assistant.sql",
    "packages/assistant/sql/live-facts.sql",
    "packages/assistant/sql/intent-budget.sql",
    "packages/contracts/sql/authoring-package-jobs.sql",
    "packages/contracts/sql/authoring-exact-revisions.sql",
    "packages/contracts/sql/authoring-exact-builds.sql",
    "packages/contracts/sql/authoring-exact-text-edits.sql",
)
TABLES = (
    "authoring_package_inputs",
    "authoring_package_fact_scopes",
    "authoring_package_job_bindings",
    "authoring_package_action_bindings",
    "authoring_exact_revisions",
    "authoring_exact_manual_revisions",
    "authoring_exact_revision_records",
)
PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
)
WORKER_RPCS = (
    "design.authoring_package_assert_job(uuid)",
    "design.authoring_exact_snapshot_proof(uuid)",
    "design.authoring_exact_build_packet(uuid)",
    "design.authoring_exact_assert_build(uuid)",
)
API_RPCS = (
    *WORKER_RPCS,
    "design.authoring_package_digest(jsonb)",
    "design.authoring_exact_check_revision(uuid)",
    "design.authoring_exact_assert_revision(uuid)",
)


def fail(suffix: str) -> NoReturn:
    raise fresh.BootstrapError("AUTHORING_CANDIDATE_" + suffix)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def plan():
    if set(OPTIONAL_SQL) & set(fresh.BASE_SQL):
        fail("EXTENSIONS_MUST_REMAIN_OPTIONAL")
    entries = [fresh.reviewed_sql(fresh.ROOT / name) for name in OPTIONAL_SQL]
    base = [fresh.reviewed_sql(fresh.ROOT / name) for name in fresh.BASE_SQL]
    document = {
        "version": VERSION,
        "base_sql": [{"path": item.path, "sha256": item.sha256} for item in base],
        "optional_sql": [{"path": item.path, "sha256": item.sha256} for item in entries],
    }
    return document | {"digest": digest(document)}


def checked(document):
    """Reject missing, reordered, extra or changed inputs before any mutation."""
    if (
        type(document) is not dict
        or set(document) != {"version", "base_sql", "optional_sql", "digest"}
        or document["version"] != VERSION
        or type(document["base_sql"]) is not list
        or len(document["base_sql"]) != len(fresh.BASE_SQL)
        or type(document["optional_sql"]) is not list
        or len(document["optional_sql"]) != len(OPTIONAL_SQL)
        or document["digest"] != digest({k: v for k, v in document.items() if k != "digest"})
        or set(OPTIONAL_SQL) & set(fresh.BASE_SQL)
    ):
        fail("PLAN_INVALID")
    ordered = [*document["base_sql"], *document["optional_sql"]]
    for entry, expected in zip(ordered, (*fresh.BASE_SQL, *OPTIONAL_SQL), strict=True):
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or entry["path"] != expected
            or type(entry["sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
        ):
            fail("PLAN_INVALID")
    return tuple(
        fresh.reviewed_sql(fresh.ROOT / entry["path"], entry["sha256"]) for entry in ordered
    )


def load(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
        fail("PLAN_FILE_INVALID")

    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                fail("PLAN_INVALID")
            value[key] = item
        return value

    try:
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        fail("PLAN_INVALID")
    checked(document)
    return document


def function_names(entries):
    names = {"authoring_exact_check_candidate_revision"}
    for entry in entries:
        names.update(
            re.findall(
                r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:design\.)?"
                r"(authoring_(?:exact|package)_[a-z_]+)\s*\(",
                entry.content.decode("utf-8"),
            )
        )
    return names


def inspect_acl(cursor, role, expected_functions):
    """Read effective permissions as the actual LOGIN; never grant or repair."""
    if role not in {"api", "worker"}:
        fail("ROLE_INVALID")
    row = cursor.execute(
        "SELECT current_user=session_user AS direct,rolcanlogin,rolsuper,rolcreatedb,"
        "rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=session_user"
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
    memberships = cursor.execute(
        "WITH RECURSIVE memberships(id,admin) AS ("
        "SELECT roleid,admin_option FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=session_user) "
        "UNION SELECT m.roleid,m.admin_option FROM pg_auth_members m JOIN memberships p ON m.member=p.id) "
        "SELECT r.rolname,m.admin,r.rolcanlogin,r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls "
        "FROM memberships m JOIN pg_roles r ON r.oid=m.id"
    ).fetchall()
    if (
        len(memberships) != 1
        or memberships[0]["rolname"] != "tender_" + role
        or any(value for key, value in memberships[0].items() if key != "rolname")
    ):
        fail("MEMBERSHIP_NOT_EXACT")
    forbidden = cursor.execute(
        "SELECT has_database_privilege(current_user,current_database(),'CREATE') OR "
        "EXISTS(SELECT FROM pg_namespace n WHERE left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' "
        "AND (has_schema_privilege(current_user,n.oid,'CREATE') OR pg_has_role(session_user,n.nspowner,'MEMBER'))) OR "
        "EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' AND pg_has_role(session_user,t.relowner,'MEMBER')) AS bad"
    ).fetchone()
    if forbidden["bad"]:
        fail("OWNER_OR_CREATE_PRIVILEGE")
    rows = cursor.execute(
        "SELECT t.relname,p.privilege,has_table_privilege(current_user,t.oid,p.privilege) AS allowed,"
        "CASE WHEN p.privilege IN('SELECT','INSERT','UPDATE','REFERENCES') "
        "THEN has_any_column_privilege(current_user,t.oid,p.privilege) ELSE false END AS column_allowed "
        "FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace "
        "CROSS JOIN unnest(%s::text[]) p(privilege) "
        "WHERE n.nspname='design' AND t.relname=ANY(%s::text[]) AND t.relkind IN('r','v')",
        (list(PRIVILEGES), list(TABLES)),
    ).fetchall()
    if len(rows) != len(TABLES) * len(PRIVILEGES):
        fail("RELATIONS_MISSING")
    table_grants: dict[str, list[str]] = {name: [] for name in TABLES}
    for row in rows:
        expected = role == "api" and (
            row["privilege"] == "SELECT"
            or row["privilege"] == "INSERT"
            and row["relname"] != "authoring_exact_revision_records"
        )
        if row["allowed"] is not expected or not expected and row["column_allowed"]:
            fail("TABLE_PRIVILEGE_MISMATCH")
        if row["allowed"]:
            table_grants[row["relname"]].append(row["privilege"])
    rpcs = API_RPCS if role == "api" else WORKER_RPCS
    functions = cursor.execute(
        "SELECT p.proname,has_function_privilege(current_user,p.oid,'EXECUTE') AS allowed,"
        "p.oid=ANY(ARRAY(SELECT to_regprocedure(signature)::oid FROM unnest(%s::text[]) s(signature))) AS expected,"
        "p.proowner=n.nspowner AND NOT pg_has_role(session_user,p.proowner,'MEMBER') AS owner_safe "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='design' AND (p.proname LIKE 'authoring_exact_%%' OR p.proname LIKE 'authoring_package_%%')",
        (list(rpcs),),
    ).fetchall()
    if (
        len(functions) != len(expected_functions)
        or {row["proname"] for row in functions} != expected_functions
        or sum(row["allowed"] for row in functions) != len(rpcs)
        or any(not row["owner_safe"] or row["allowed"] is not row["expected"] for row in functions)
    ):
        fail("FUNCTION_PRIVILEGE_MISMATCH")
    capabilities = {
        "fixed_input_storage": inputs.available(cursor),
        "exact_adoption_permissions": exact_sources.apply_available(cursor),
        "exact_build_permissions": exact_builds.available(cursor),
        "manual_text_edit_permissions": exact_text_edits.available(cursor),
    }
    if capabilities != {
        "fixed_input_storage": role == "api",
        "exact_adoption_permissions": role == "api",
        "exact_build_permissions": True,
        "manual_text_edit_permissions": role == "api",
    }:
        fail("CAPABILITIES_UNAVAILABLE")
    return {
        "login": cursor.execute("SELECT session_user AS login").fetchone()["login"],
        "membership": "tender_" + role,
        "table_privileges": {name: sorted(values) for name, values in table_grants.items()},
        "executable_functions": list(rpcs),
        "schema_capabilities": capabilities,
    }


def verify(result, entries):
    business = fresh.ROOT / result["profiles"]["business"]
    if (
        business.is_symlink()
        or not business.is_file()
        or stat.S_IMODE(business.stat().st_mode) != 0o600
    ):
        fail("PRIVATE_BUSINESS_PROFILE_REQUIRED")
    values = file_configuration(business)
    checks = {}
    for role in ("api", "worker"):
        with psycopg.connect(values[role.upper() + "_DATABASE_DSN"], autocommit=True) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                fresh.verify_connection(
                    connection,
                    database=result["database"],
                    user=result["logins"][role],
                    restricted=True,
                )
                with connection.cursor(row_factory=dict_row) as cursor:
                    checks[role] = inspect_acl(cursor, role, function_names(entries))
    if checks["api"]["login"] == checks["worker"]["login"]:
        fail("INDEPENDENT_LOGIN_REQUIRED")
    return checks


def create(document, **kwargs):
    entries = checked(document)
    if (
        "extensions" in kwargs
        or "expected_sql_plan" in kwargs
        or kwargs.get("model_purposes")
        or kwargs.get("model_score_purpose")
        or kwargs.get("assistant_budget_admin")
    ):
        fail("EXCLUSIVE_PLAN_REQUIRED")
    result = fresh.bootstrap(
        extensions=[
            (fresh.ROOT / entry.path, entry.sha256) for entry in entries[len(fresh.BASE_SQL) :]
        ],
        expected_sql_plan=tuple((entry.path, entry.sha256) for entry in entries),
        **kwargs,
    )
    try:
        if result["ordered_sql"] != [*document["base_sql"], *document["optional_sql"]]:
            fail("INSTALLED_PLAN_MISMATCH")
        permissions = verify(result, entries)
    except Exception:
        # This invocation just created it. Preserve the private init/recovery
        # profile, but do not expose a business profile whose B1–B5 audit failed.
        (fresh.ROOT / result["profiles"]["business"]).unlink(missing_ok=True)
        raise
    return result | {
        "authoring_candidate": {
            "version": VERSION,
            "plan_digest": document["digest"],
            "optional_sql": document["optional_sql"],
            "actual_login_checks": permissions,
            "schema_permissions_verified": True,
            "business_workflow_executed": False,
        }
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-plan", type=Path)
    args = parser.parse_args(argv)
    document = plan()
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.write_plan:
        with args.write_plan.open("x", encoding="utf-8") as output:
            output.write(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
