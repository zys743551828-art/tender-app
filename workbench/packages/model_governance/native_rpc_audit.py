"""Catalog-only audit for explicitly declared native RPC and helper methods."""

from dataclasses import dataclass
from pathlib import Path

from packages.model_governance import package_scope_review_issuers as policy_source
from packages.model_governance import read_purpose


class NativeMethodMismatch(ValueError):
    pass


@dataclass(frozen=True)
class FunctionSpec:
    source: Path
    schema: str
    name: str
    argument_types: str
    tag: str
    definer: bool
    volatility: str
    returns: str
    caller_execute: bool
    utc: bool = True


def audit(cursor, *, group, rpcs, schema, tables, functions):
    """Trusted code supplies fixed declarations; never accepts request SQL or paths."""
    read_purpose.require_read_purpose(
        cursor, read_purpose.ReadPurpose(groups=frozenset({group}), definer_calls=rpcs)
    )
    owners = cursor.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relname=ANY(%s) AND c.relkind='r'",
        (schema, list(tables)),
    ).fetchall()
    if (
        len(owners) != len(tables)
        or len({r["relowner"] for r in owners}) != 1
        or any(r["relowner"] != r["nspowner"] for r in owners)
    ):
        raise NativeMethodMismatch("NATIVE_METHOD_MISMATCH")
    owner = owners[0]["relowner"]
    specs = (
        FunctionSpec(
            policy_source.SQL_FILE,
            "scope_review_issuer",
            "role_policy",
            "name, text, text[]",
            "scope_issuer_policy",
            False,
            "s",
            "boolean",
            False,
            False,
        ),
        *functions,
    )
    sources = {path: path.read_text(encoding="utf-8") for path in {spec.source for spec in specs}}
    for spec in specs:
        pieces = sources[spec.source].split("$" + spec.tag + "$")
        rows = cursor.execute(
            "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,"
            "p.prorettype::regtype::text AS returns,pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner,"
            "has_function_privilege(session_user,p.oid,'EXECUTE') AS caller_execute "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang "
            "WHERE n.nspname=%s AND p.proname=%s AND oidvectortypes(p.proargtypes)=%s",
            (spec.schema, spec.name, spec.argument_types),
        ).fetchall()
        if len(pieces) != 3 or len(rows) != 1:
            raise NativeMethodMismatch("NATIVE_METHOD_MISMATCH")
        row = rows[0]
        settings = [f"search_path=pg_catalog, {spec.schema}, design, pg_temp"]
        if spec.utc:
            settings.append("TimeZone=UTC")
        if (
            row["prosrc"] != pieces[1]
            or row["prosecdef"] is not spec.definer
            or row["provolatile"] != spec.volatility
            or row["proowner"] != owner
            or row["caller_owner"]
            or row["lanname"] != "plpgsql"
            or row["returns"] != spec.returns
            or row["caller_execute"] is not spec.caller_execute
            or row["proconfig"] != settings
        ):
            raise NativeMethodMismatch("NATIVE_METHOD_MISMATCH")
