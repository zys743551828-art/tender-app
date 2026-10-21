"""HTTP-facing native history commands; no proof import or issuer configuration."""

from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg

from packages.domain import bid_package_technical_scope_repository as scopes
from packages.domain.runtime import DomainError, etag, sha


def configured(c, *, research=False):
    relation = (
        "package_historical_research.cohorts"
        if research
        else "package_historical_research.admissions"
    )
    return c.execute("SELECT to_regclass(%s) AS value", (relation,)).fetchone()["value"] is not None


def require(c, *, research=False):
    if not configured(c, research=research):
        raise DomainError("PACKAGE_HISTORY_NOT_CONFIGURED", "独立整包历史研究能力未安装", 503)


@contextmanager
def errors():
    try:
        yield
    except psycopg.Error as error:
        code = error.diag.message_primary or ""
        if not code.startswith("package_history_"):
            raise
        status = (
            403
            if error.sqlstate == "42501"
            else 404
            if error.sqlstate == "P0002"
            else 422
            if error.sqlstate == "23514"
            else 409
        )
        raise DomainError(
            code.upper(), "整包历史证据、用途、时间或当前版本不满足本次操作条件", status
        ) from error


def tag(kind, identity, value):
    return etag(
        "package-history-" + kind,
        str(identity),
        sha({k: v for k, v in value.items() if k != "observed_at"}),
    )


def match(condition, expected):
    if not condition:
        raise DomainError("IF_MATCH_REQUIRED", "请先读取当前历史研究状态", 428)
    if condition != expected:
        raise DomainError("PRECONDITION_FAILED", "历史研究上下文已经变化，请重新核对", 412)


def context(c, scope, scope_id, submission_id, outcome_id):
    saved = scopes.load(c, tuple(map(str, scope)), str(scope_id))
    if configured(c):
        result = c.execute(
            "SELECT package_historical_research.admission_context(%s,%s,%s) AS value",
            (scope_id, submission_id, outcome_id),
        ).fetchone()["value"] | {"schema_configured": True}
    else:
        # No optional table is queried on a BASE-only deployment.
        result = {
            "schema": "package-historical-admission-context/1",
            "schema_configured": False,
            "scope_id": str(scope_id),
            "submission_id": str(submission_id),
            "outcome_id": str(outcome_id),
            "context_digest": None,
            "official_technical_value": None,
            "official_maximum": None,
            "historical_as_of": None,
            "scope_frozen_at": saved["manifest"]["frozen_at"],
            "label_known_at": None,
            "proofs": [],
            "blockers": [
                {
                    "code": "PACKAGE_HISTORY_NOT_CONFIGURED",
                    "message": "独立历史证据与样本准入能力未安装；当前范围不授历史资格。",
                }
            ],
            "research_only": True,
            "formal_eligibility": "unavailable",
            "strict_prebid_eligible": False,
            "online_metrics_eligible": False,
            "formal_sample_created": False,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
    return result, tag("context", scope_id, result)
