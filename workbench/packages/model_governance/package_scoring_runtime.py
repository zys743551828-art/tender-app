"""Purpose-only package Worker RPCs, separate from API, old score and raw storage."""

import os
import re
import threading
from contextlib import contextmanager
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from packages.domain.runtime import DomainError
from packages.model_governance.package_scoring_producer import execute
from packages.model_governance.scoring_runtime import ScoreAuthority

ALLOWED_ENV = {
    "PACKAGE_SCORE_DATABASE_DSN",
    "WORKBENCH_ENV_FILE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
}


@contextmanager
def package_score_connection():
    if set(os.environ) - ALLOWED_ENV or os.environ.get("WORKBENCH_ENV_FILE") != "/dev/null":
        raise DomainError(
            "PACKAGE_SCORE_ENVIRONMENT_NOT_ISOLATED",
            "整包评分Worker不能继承API、桶或供应商凭据",
            503,
        )
    dsn = os.environ.get("PACKAGE_SCORE_DATABASE_DSN")
    if not dsn:
        raise DomainError("PACKAGE_SCORE_RUNTIME_NOT_CONFIGURED", "整包专用用途连接未配置", 503)
    with psycopg.connect(
        dsn,
        row_factory=dict_row,
        options="-c search_path=package_score_execution,pg_catalog -c statement_timeout=15000 -c lock_timeout=10000 -c idle_in_transaction_session_timeout=15000",
        application_name="tender-package-score-purpose",
    ) as c:
        role = c.execute(
            "SELECT r.rolsuper,r.rolbypassrls,has_schema_privilege(current_user,'design','USAGE') AS raw_access,pg_has_role(current_user,'tender_package_score_test_worker','MEMBER') AS worker,pg_has_role(current_user,'tender_api','MEMBER') OR pg_has_role(current_user,'tender_worker','MEMBER') OR pg_has_role(current_user,'tender_model_score','MEMBER') AS mixed FROM pg_roles r WHERE r.rolname=current_user"
        ).fetchone()
        if (
            role is None
            or role["rolsuper"]
            or role["rolbypassrls"]
            or role["raw_access"]
            or role["mixed"]
            or not role["worker"]
            or not re.fullmatch(r"fusion_package_score_mechanism_[a-z0-9]{8}", c.info.dbname)
        ):
            raise DomainError(
                "PACKAGE_SCORE_ROLE_INVALID", "此机制Worker须使用隔离数据库和独立受限用途LOGIN", 503
            )
        yield c


class PackageScoreAuthority(ScoreAuthority):
    """Reuse the existing typed ledger adapter; route only its fixed RPC names."""

    @staticmethod
    def _call(query, values):
        if not query.startswith("SELECT score_execution.") or query.count("score_execution.") != 1:
            raise DomainError("PACKAGE_SCORE_RPC_INVALID", "整包Worker只允许固定owned RPC", 503)
        query = query.replace("score_execution.", "package_score_execution.", 1)
        try:
            with package_score_connection() as c:
                return c.execute(query, values).fetchone()["value"]
        except psycopg.Error as error:
            if error.sqlstate in {"42883", "3F000", "42501"}:
                raise DomainError(
                    "PACKAGE_SCORE_AUTHORITY_UNAVAILABLE", "独立整包执行权威或用途权限未配置", 503
                ) from None
            if error.sqlstate in {"55000", "22023", "23514", "23505", "P0002", "40001"}:
                raise DomainError(
                    "PACKAGE_SCORE_EXECUTION_REJECTED",
                    "原范围、租约、预算或调用回执不再允许此执行",
                    409,
                ) from None
            raise


def execute_job(identity: UUID, generation: int, *, transport=None):
    if transport is None:
        raise DomainError(
            "PACKAGE_SCORE_PROVIDER_UNQUALIFIED",
            "完整图文资格与真实模型运行尚未配置，未领取任务或发送模型请求",
            503,
        )
    authority = PackageScoreAuthority()
    lease = authority.claim(identity, generation)
    stop = threading.Event()
    failures: list[bool] = []

    def beat():
        while not stop.wait(20):
            try:
                authority.heartbeat(lease)
            except Exception:
                failures.append(True)
                return

    thread = threading.Thread(target=beat, name="package-score-heartbeat", daemon=True)
    thread.start()
    try:
        result = execute(authority, lease, transport=transport)
        if failures:
            raise DomainError(
                "PACKAGE_SCORE_HEARTBEAT_INTERRUPTED", "租约维护中断，请核对原已持久化任务回执", 409
            )
        return result
    except Exception:
        try:
            authority.pause_failed(lease)
        except Exception:
            # A lost fence, cancellation or unknown fee already changed the state.
            # Never overwrite a newer owner while reporting the original failure.
            failures.append(True)
        raise
    finally:
        stop.set()
        thread.join(timeout=1)
