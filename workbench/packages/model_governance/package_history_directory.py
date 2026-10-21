"""One read-only snapshot and signed continuation; never invoke qualification RPCs."""

import base64
import hmac
import json
import re
from datetime import datetime, timezone
from uuid import UUID

import psycopg

from packages.contracts import package_history_directory_api as contract
from packages.domain.runtime import DomainError, connection, secret_hash, sha

SIGNATURES = {
    "admissions": "package_historical_research.list_admissions(uuid,uuid,integer,uuid,design.sha256)",
    "protocols": "package_historical_research.list_protocols(integer,uuid,design.sha256)",
    "cohorts": "package_historical_research.list_cohorts(uuid,integer,uuid,design.sha256)",
    "jobs": "package_historical_research.list_jobs(uuid,integer,uuid,design.sha256)",
}
SQL = {
    "admissions": "SELECT package_historical_research.list_admissions(%s,%s,%s,%s,%s) AS value",
    "protocols": "SELECT package_historical_research.list_protocols(%s,%s,%s) AS value",
    "cohorts": "SELECT package_historical_research.list_cohorts(%s,%s,%s,%s) AS value",
    "jobs": "SELECT package_historical_research.list_jobs(%s,%s,%s,%s) AS value",
}
SHA = re.compile(r"^[a-f0-9]{64}$")


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def encode_cursor(kind, filters, observation, after):
    raw = json.dumps(
        {
            "version": 1,
            "scope": sha({"kind": kind, "filters": filters}),
            "observation": observation,
            "after": after,
        },
        separators=(",", ":"),
    ).encode()
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return token + "." + secret_hash("package-history-directory/1:" + token)


def decode_cursor(cursor, kind, filters):
    if cursor is None:
        return None, None
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096:
            raise ValueError("invalid length")
        token, signature = cursor.split(".")
        if not hmac.compare_digest(secret_hash("package-history-directory/1:" + token), signature):
            raise ValueError("invalid signature")
        value = json.loads(
            base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True),
            object_pairs_hook=_pairs,
        )
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "scope", "observation", "after"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["scope"] != sha({"kind": kind, "filters": filters})
            or not isinstance(value["observation"], str)
            or not SHA.fullmatch(value["observation"])
            or not isinstance(value["after"], str)
            or str(UUID(value["after"])) != value["after"]
        ):
            raise ValueError("invalid identity")
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, AttributeError):
        raise DomainError(
            "PACKAGE_HISTORY_DIRECTORY_CURSOR_INVALID",
            "目录游标与所选筛选不符，请从首页重新读取",
            422,
        ) from None
    return value["after"], value["observation"]


def unavailable(kind, filters):
    return {
        "version": "package-history-directory/1",
        "kind": kind,
        "filters": filters,
        "status": "unavailable",
        "schema_configured": False,
        "items": [],
        "total": None,
        "observation_digest": None,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "complete_observation": False,
        "has_more": None,
        "next_cursor": None,
        "currentness_rechecked": False,
        "research_only": True,
        "formal_eligibility": "unavailable",
        "qualification_granted": False,
    }


def read(kind, *, bid=None, scope=None, protocol=None, cohort=None, limit=20, cursor=None):
    filters = {"bid_id": bid, "scope_id": scope, "protocol_id": protocol, "cohort_id": cohort}
    if (
        kind not in SIGNATURES
        or type(limit) is not int
        or not 1 <= limit <= 50
        or kind == "admissions"
        and (protocol is not None or cohort is not None or scope is not None and bid is None)
        or kind == "protocols"
        and any(value is not None for value in filters.values())
        or kind == "cohorts"
        and any(value is not None for value in (bid, scope, cohort))
        or kind == "jobs"
        and (cohort is None or any(value is not None for value in (bid, scope, protocol)))
    ):
        raise DomainError(
            "PACKAGE_HISTORY_DIRECTORY_FILTERS_INVALID", "请明确选择有效的目录筛选", 422
        )
    try:
        if any(
            value is not None and (not isinstance(value, str) or str(UUID(value)) != value)
            for value in filters.values()
        ):
            raise ValueError("invalid identity")
    except (ValueError, TypeError, AttributeError):
        raise DomainError(
            "PACKAGE_HISTORY_DIRECTORY_FILTERS_INVALID", "目录身份必须为明确的有效标识", 422
        ) from None
    after, observation = decode_cursor(cursor, kind, filters)
    try:
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            c.execute("SET LOCAL statement_timeout='20s'")
            present = c.execute(
                "SELECT bool_and(to_regprocedure(signature) IS NOT NULL) AS value FROM unnest(%s::text[]) signature",
                (list(SIGNATURES.values()),),
            ).fetchone()["value"]
            if not present:
                return contract.validate(kind, unavailable(kind, filters))
            prefixes = {
                "admissions": [bid, scope],
                "protocols": [],
                "cohorts": [protocol],
                "jobs": [cohort],
            }
            value = c.execute(SQL[kind], (*prefixes[kind], limit, after, observation)).fetchone()[
                "value"
            ]
            if value["kind"] != kind or value["filters"] != filters:
                raise DomainError(
                    "PACKAGE_HISTORY_DIRECTORY_INVALID", "目录返回了不同的筛选身份", 500
                )
            next_id = value.pop("after_id")
            value.update(
                version="package-history-directory/1",
                status="observed",
                schema_configured=True,
                complete_observation=True,
                next_cursor=encode_cursor(kind, filters, value["observation_digest"], next_id)
                if next_id is not None
                else None,
                currentness_rechecked=False,
                research_only=True,
                formal_eligibility="unavailable",
                qualification_granted=False,
            )
            return contract.validate(kind, value)
    except psycopg.errors.ProgramLimitExceeded:
        raise DomainError(
            "PACKAGE_HISTORY_DIRECTORY_BUDGET_EXCEEDED",
            "目录超过完整观察预算，请缩小筛选后重新读取",
            503,
        ) from None
    except psycopg.errors.QueryCanceled:
        raise DomainError(
            "PACKAGE_HISTORY_DIRECTORY_TIMEOUT", "目录尚未完整读取，请稍后重试", 503, retryable=True
        ) from None
    except psycopg.Error as error:
        code = error.diag.message_primary or ""
        if code.startswith("package_history_directory_"):
            status = (
                403
                if error.sqlstate == "42501"
                else 404
                if error.sqlstate == "P0002"
                else 422
                if error.sqlstate == "23514"
                else 409
            )
            message = (
                "目录在分页期间已变化，请保留原选择并从首页重新读取"
                if code == "package_history_directory_observation_changed"
                else "历史研究目录的身份、筛选或只读权限不满足要求"
            )
            raise DomainError(code.upper(), message, status) from error
        if isinstance(
            error,
            (
                psycopg.errors.UndefinedFunction,
                psycopg.errors.UndefinedTable,
                psycopg.errors.InsufficientPrivilege,
            ),
        ):
            raise DomainError(
                "PACKAGE_HISTORY_DIRECTORY_UNAVAILABLE", "历史研究目录所需只读能力或权限不可用", 503
            ) from error
        raise
