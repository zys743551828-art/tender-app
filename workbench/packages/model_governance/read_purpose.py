"""Audit native effective grants for fixed read-only technical verification ports.

Policies are implementation constants, never request fields. No connection,
environment loading, grants, role switching or permission repair occurs here.
"""

from dataclasses import dataclass


class ReadPurposeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ReadPurpose:
    groups: frozenset[str]
    tables: frozenset[str] = frozenset()
    columns: tuple[tuple[str, frozenset[str]], ...] = ()
    definer_calls: tuple[str, ...] = ()

    def __post_init__(self):
        if (
            not self.groups
            or len(dict(self.columns)) != len(self.columns)
            or any(table not in self.tables for table, _ in self.columns)
        ):
            raise ValueError("READ_PURPOSE_POLICY_INVALID")


def fail(code):
    raise ReadPurposeError(code)


def require_read_purpose(c, policy):
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
    memberships = c.execute(
        "WITH RECURSIVE memberships(id) AS (SELECT roleid FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=session_user) UNION SELECT m.roleid FROM pg_auth_members m JOIN memberships p ON m.member=p.id) SELECT r.rolname FROM memberships m JOIN pg_roles r ON r.oid=m.id"
    ).fetchall()
    if {row["rolname"] for row in memberships} != policy.groups:
        fail("INDEPENDENT_MEMBERSHIP_REQUIRED")
    if c.execute(
        "SELECT has_database_privilege(current_user,current_database(),'CREATE') AS bad"
    ).fetchone()["bad"]:
        fail("DATABASE_CREATE_PRIVILEGE")
    if c.execute(
        "SELECT EXISTS(SELECT FROM pg_namespace n WHERE left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' AND has_schema_privilege(current_user,n.oid,'CREATE')) AS bad"
    ).fetchone()["bad"]:
        fail("SCHEMA_WRITE_PRIVILEGE")
    if c.execute(
        "SELECT EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.prosecdef AND left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' AND has_schema_privilege(current_user,n.oid,'USAGE') AND has_function_privilege(current_user,p.oid,'EXECUTE') AND p.oid<>ALL(ARRAY(SELECT to_regprocedure(name)::oid FROM unnest(%s::text[]) AS allowed(name) WHERE to_regprocedure(name) IS NOT NULL))) AS bad",
        (list(policy.definer_calls),),
    ).fetchone()["bad"]:
        fail("DEFINER_EXECUTE_PRIVILEGE")
    if c.execute(
        "SELECT EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace WHERE t.relkind IN ('r','p','v','m','f') AND left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' AND (has_table_privilege(current_user,t.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_any_column_privilege(current_user,t.oid,'INSERT,UPDATE,REFERENCES') OR ((has_table_privilege(current_user,t.oid,'SELECT') OR has_any_column_privilege(current_user,t.oid,'SELECT')) AND n.nspname||'.'||t.relname<>ALL(%s::text[])))) AS bad",
        (sorted(policy.tables),),
    ).fetchone()["bad"]:
        fail("EXCESS_TABLE_PRIVILEGE")
    if not policy.columns:
        return
    allowed_columns = dict(policy.columns)
    columns = c.execute(
        "SELECT n.nspname||'.'||t.relname AS relation,a.attname FROM pg_attribute a JOIN pg_class t ON t.oid=a.attrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE a.attnum>0 AND NOT a.attisdropped AND n.nspname||'.'||t.relname=ANY(%s::text[]) AND has_column_privilege(current_user,t.oid,a.attnum,'SELECT')",
        (sorted(allowed_columns),),
    ).fetchall()
    if any(row["attname"] not in allowed_columns[row["relation"]] for row in columns):
        fail("EXCESS_METADATA_COLUMN_PRIVILEGE")
