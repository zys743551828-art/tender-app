"""Protected exact job RPC adapter. Mode strings only select this verifier."""

from uuid import UUID

import psycopg

from packages.domain.runtime import DomainError

MODE = "exact_package_authoring/1"


def available(c):
    return bool(
        c.execute(
            "SELECT to_regclass('design.authoring_package_job_bindings') IS NOT NULL "
            "AND to_regprocedure('design.authoring_package_assert_job(uuid)') IS NOT NULL "
            "AND to_regprocedure('design.assistant_reserve_budget(uuid)') IS NOT NULL AS ready"
        ).fetchone()["ready"]
    )


def require_schema(c):
    if not available(c):
        raise DomainError(
            "AUTHORING_PACKAGE_EXECUTOR_NOT_CONFIGURED", "固定整包编写执行器尚未配置", 503
        )


def assert_job(c, job_id):
    require_schema(c)
    try:
        with c.transaction():
            c.execute("SELECT design.authoring_package_assert_job(%s)", (job_id,))
    except psycopg.Error as error:
        code = error.diag.message_primary or ""
        if code.startswith("AUTHORING_PACKAGE_") or code.startswith("ASSISTANT_"):
            raise DomainError(
                code, "固定输入、原任务或当前使用资格已变化，未授权继续执行", 409
            ) from None
        raise


def assert_manifest(c, manifest):
    """A fake mode / job ID cannot replace the immutable manifest in the DB."""
    from packages.domain.runtime import sha

    try:
        identity = UUID(manifest["job_id"])
    except (ValueError, TypeError, KeyError):
        raise DomainError(
            "AUTHORING_PACKAGE_JOB_BINDING_INVALID", "固定编写任务身份缺失", 409
        ) from None
    row = c.execute(
        "SELECT input_digest FROM design.assistant_jobs WHERE id=%s", (identity,)
    ).fetchone()
    if row is None or row["input_digest"] != sha(manifest):
        raise DomainError("AUTHORING_PACKAGE_JOB_BINDING_INVALID", "固定编写任务内容身份不符", 409)
    from packages.authoring.package_generation import checked

    checked(manifest, live_policy=True)
    assert_job(c, identity)
