"""Public history commands require the complete reviewed exposure guard.

The metadata directory has its own read-only contract and does not use this
dependency. Native standalone mechanism databases remain independently testable.
"""

import psycopg
from fastapi import Request
from psycopg import sql

from apps.api.auth import auth
from packages.domain.runtime import DomainError, connection

READINESS_BODY_SHA256 = "2e34c9cce5297cd7c8c32e9e27464eb821579c4f62b152c9eebbd3e2d7de2d66"
CATALOG = """
 SELECT p.oid,
  encode(sha256(convert_to(p.prosrc,'UTF8')),'hex') AS body_digest,
  p.proowner=n.nspowner AND p.proowner=d.nspowner AND p.prosecdef
  AND p.prokind='f' AND p.provolatile='s' AND NOT p.proretset
  AND p.prorettype='jsonb'::regtype AND p.pronargs=0
  AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')
  AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[]
  AS signature_matches
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 JOIN pg_namespace d ON d.nspname='design'
 WHERE n.nspname='package_history_exposure_bridge' AND p.proname='readiness'
 AND p.pronargs=0
"""
STATES = {"manifest_invalid", "installed_guard_changed", "entry_identity_changed"}


def unavailable(reason):
    return DomainError(
        "PACKAGE_HISTORY_PUBLIC_GUARD_UNAVAILABLE",
        "整包历史研究的共同暴露守卫尚未完整装配或已发生变化，核心入口暂不可用。",
        503,
        {
            "configured": False,
            "reason": reason,
            "required_guard": "package-history-public-guard/1",
            "qualification_granted": False,
            "command_started": False,
        },
    )


def require_history_public_guard(request: Request) -> None:
    """Mount once on the core router via Depends; never infer readiness from tables."""
    auth(request)
    try:
        with connection() as c:
            c.execute("SET TRANSACTION READ ONLY")
            c.execute("SET LOCAL statement_timeout='2s'")
            identity = c.execute(CATALOG).fetchone()
            if identity is None:
                raise unavailable("installation_missing")
            if (
                identity["body_digest"] != READINESS_BODY_SHA256
                or identity["signature_matches"] is not True
            ):
                raise unavailable("readiness_identity_changed")
            # Recheck the identity and the immutable installation manifest in
            # one statement snapshot. A concurrent removal also fails closed.
            row = c.execute(
                sql.SQL(
                    "WITH identity AS MATERIALIZED ({}) "
                    "SELECT CASE WHEN signature_matches AND body_digest=%s "
                    "THEN package_history_exposure_bridge.readiness() END AS value FROM identity"
                ).format(sql.SQL(CATALOG)),
                (READINESS_BODY_SHA256,),
            ).fetchone()
    except psycopg.Error as error:
        raise unavailable("guard_check_unavailable") from error
    value = row["value"] if row else None
    if not isinstance(value, dict) or value != {
        "schema": "package-history-public-guard/1",
        "configured": True,
        "state": "ready",
        "contract_count": 76,
        "checked_function_count": 58,
        "checked_trigger_count": 11,
        "public_metadata_only": True,
        "qualification_granted": False,
    }:
        reason = value.get("state") if isinstance(value, dict) else None
        raise unavailable(reason if reason in STATES else "guard_receipt_invalid")
