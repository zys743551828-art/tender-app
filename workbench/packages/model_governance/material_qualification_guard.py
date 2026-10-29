"""Catalog verification for optional qualification triggers; no new RPC grants."""

from pathlib import Path

from packages.model_governance import material_qualification as policy
from packages.storage.private_cas import sha

SQL = Path(__file__).parents[2] / "deploy/sql/material-qualified-execution.sql"


def method_digest():
    """Pin the exact SQL enforcement body, independently of old job RPC hashes."""
    return sha(SQL.read_text().split("$qualification_enforce$")[1].encode())


def audit(c):
    row = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,"
        "p.prorettype::regtype::text AS returns,"
        "pg_has_role(current_user,p.proowner,'MEMBER') AS caller_owner,"
        "has_function_privilege(current_user,p.oid,'EXECUTE') AS caller_execute,"
        "(SELECT f.proowner FROM pg_proc f JOIN pg_namespace ns ON ns.oid=f.pronamespace WHERE ns.nspname='material_judgment_job' AND f.proname='start' AND oidvectortypes(f.proargtypes)='uuid, text, uuid, text, uuid') AS native_owner "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang "
        "WHERE n.nspname='material_qualification' AND p.proname='enforce' AND p.pronargs=0"
    ).fetchone()
    source = SQL.read_text().split("$qualification_enforce$")[1]
    if (
        row is None
        or row["prosrc"] != source
        or row["prosecdef"] is not True
        or row["provolatile"] != "v"
        or row["lanname"] != "plpgsql"
        or row["returns"] != "trigger"
        or row["proconfig"]
        != ["search_path=pg_catalog, material_qualification, design, pg_temp", "TimeZone=UTC"]
        or row["proowner"] != row["native_owner"]
        or row["caller_owner"]
        or row["caller_execute"]
    ):
        policy.fail("GUARD_UNAVAILABLE", "原生资格边界未安装或与固定实现不符", 503)
    owners = c.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='material_qualification' AND c.relname=ANY(%s) AND c.relkind='r'",
        (["records", "decisions", "heads", "intents", "acceptances"],),
    ).fetchall()
    if len(owners) != 5 or any(
        x["relowner"] != row["proowner"] or x["nspowner"] != row["proowner"] for x in owners
    ):
        policy.fail("GUARD_UNAVAILABLE", "原生资格持久化所有者不一致", 503)
    triggers = c.execute(
        "SELECT n.nspname,c.relname,t.tgname,t.tgtype,t.tgenabled,t.tgqual,t.tgnargs,c.relowner,p.proname,p.proowner "
        "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid "
        "JOIN pg_namespace fn ON fn.oid=p.pronamespace WHERE fn.nspname='material_qualification' AND p.proname='enforce' AND p.pronargs=0 AND NOT t.tgisinternal"
    ).fetchall()
    expected = {
        ("material_judgment_job", "jobs", "qualified_material_job", 5),
        ("material_execution", "attempts", "qualified_material_attempt", 7),
    }
    if (
        {(t["nspname"], t["relname"], t["tgname"], t["tgtype"]) for t in triggers} != expected
        or len(triggers) != 2
        or any(
            t["tgenabled"] != "O"
            or t["tgqual"] is not None
            or t["tgnargs"] != 0
            or t["relowner"] != row["proowner"]
            or t["proowner"] != row["proowner"]
            for t in triggers
        )
    ):
        policy.fail("GUARD_UNAVAILABLE", "原生资格触发器边界不完整", 503)
