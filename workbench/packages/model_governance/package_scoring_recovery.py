"""Apply already registered isolated receipts with a separate purpose principal.

No response body, model credentials, qualification switch or direct ledger update
is accepted. SQL owns receipt identity, immutable prior state and accounting.
"""

import os
import re
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from packages.domain.runtime import DomainError

ALLOWED_ENV = {
    "PACKAGE_SCORE_RECONCILIATION_DSN",
    "WORKBENCH_ENV_FILE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
}


@contextmanager
def reconciliation_connection():
    if set(os.environ) - ALLOWED_ENV or os.environ.get("WORKBENCH_ENV_FILE") != "/dev/null":
        raise DomainError(
            "PACKAGE_SCORE_RECONCILIATION_ENVIRONMENT_INVALID", "对账进程必须使用独立用途环境", 503
        )
    dsn = os.environ.get("PACKAGE_SCORE_RECONCILIATION_DSN")
    if not dsn:
        raise DomainError(
            "PACKAGE_SCORE_RECONCILIATION_NOT_CONFIGURED", "独立整包对账连接未配置", 503
        )
    with psycopg.connect(
        dsn,
        row_factory=dict_row,
        options="-c search_path=package_score_execution,pg_catalog -c statement_timeout=15000 -c lock_timeout=10000 -c idle_in_transaction_session_timeout=15000",
        application_name="tender-package-score-reconciliation",
    ) as c:
        role = c.execute(
            "SELECT r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole,r.rolreplication,has_schema_privilege(current_user,'design','USAGE') AS raw_access,pg_has_role(current_user,'tender_package_score_test_reconciler','MEMBER') AS reconciler,pg_has_role(current_user,'tender_api','MEMBER') OR pg_has_role(current_user,'tender_worker','MEMBER') OR pg_has_role(current_user,'tender_research_worker','MEMBER') OR pg_has_role(current_user,'tender_model_score','MEMBER') OR pg_has_role(current_user,'tender_package_score_test_api','MEMBER') OR pg_has_role(current_user,'tender_package_score_test_worker','MEMBER') AS mixed FROM pg_roles r WHERE r.rolname=current_user"
        ).fetchone()
        if (
            role is None
            or any(
                role[key]
                for key in (
                    "rolsuper",
                    "rolbypassrls",
                    "rolcreatedb",
                    "rolcreaterole",
                    "rolreplication",
                    "raw_access",
                    "mixed",
                )
            )
            or not role["reconciler"]
            or not re.fullmatch(r"fusion_package_score_mechanism_[a-z0-9]{8}", c.info.dbname)
        ):
            raise DomainError(
                "PACKAGE_SCORE_RECONCILIATION_ROLE_INVALID",
                "必须使用独立临时机制库和受限对账LOGIN",
                503,
            )
        yield c


def reconcile(receipt_id, command_key, reason):
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 4000:
        raise DomainError("PACKAGE_SCORE_RECONCILIATION_REASON_REQUIRED", "请记录具体对账理由", 422)
    try:
        with reconciliation_connection() as c:
            result = c.execute(
                "SELECT package_score_execution.reconcile_call(%s,%s,%s) AS value",
                (receipt_id, command_key, reason),
            ).fetchone()["value"]
    except psycopg.Error as error:
        if error.sqlstate in {"42883", "3F000", "42501"}:
            raise DomainError(
                "PACKAGE_SCORE_RECONCILIATION_AUTHORITY_UNAVAILABLE",
                "独立对账权威或用途权限尚未配置",
                503,
            ) from None
        if error.sqlstate in {
            "55000",
            "22023",
            "22P02",
            "22003",
            "23514",
            "23505",
            "23502",
            "P0002",
            "40001",
        }:
            raise DomainError(
                "PACKAGE_SCORE_RECONCILIATION_REJECTED",
                "原调用、可信回执、幂等条件或账目未通过核验，未改变费用",
                409,
            ) from None
        raise
    return result
