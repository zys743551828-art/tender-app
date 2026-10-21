"""Read-only orchestration: one RR snapshot from native resolution to projection."""

from contextlib import contextmanager
from uuid import UUID

import psycopg

from packages.contracts import work_context_api as contract
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, connection
from packages.work_contexts import observations, permissions, policy, repository


def request_ids(*values):
    try:
        valid = all(isinstance(value, str) and str(UUID(value)) == value for value in values)
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        policy.fail("REQUEST_INVALID", "请提供明确的规范项目和记录标识", 422)


@contextmanager
def snapshot(kind):
    try:
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            c.execute("SET LOCAL statement_timeout='20s'")
            permissions.require(c, kind)
            yield c
    except PackageError as error:
        raise DomainError(
            "WORK_CONTEXT_CORRUPT", "明确选择的关联包、清单或冻结输入不能核验", 500
        ) from error
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise DomainError(
            "WORK_CONTEXT_CORRUPT", "只读工作上下文的原生关系或证明不完整", 500
        ) from error
    except (
        psycopg.errors.InsufficientPrivilege,
        psycopg.errors.UndefinedTable,
        psycopg.errors.UndefinedFunction,
    ) as error:
        raise DomainError(
            "WORK_CONTEXT_UNAVAILABLE", "工作上下文所需只读存储或权限不可用", 503
        ) from error
    except psycopg.errors.QueryCanceled as error:
        raise DomainError(
            "WORK_CONTEXT_READ_TIMEOUT",
            "完整只读观察超过本次预算，未返回部分摘要",
            503,
            retryable=True,
        ) from error


def expected(value, selected_digest):
    if selected_digest is not None:
        if not contract.valid("WorkContextSelection", value["selection"]):
            policy.fail("CORRUPT", "工作上下文身份不能核验", 500)
        if selected_digest != value["selection_digest"]:
            policy.fail(
                "SELECTION_CHANGED",
                "返回身份与明确固定的选择摘要不一致，请保留原选择后重新核对",
                412,
            )
    return value


def resolve_run(bid, run_id, *, expected_selection_digest=None):
    request_ids(bid, run_id)
    with snapshot("run") as c:
        loaded = repository.exact_run(c, bid, run_id)
        run, selected = loaded["run"], loaded["selected"]
        selection = policy.run_selection(run, selected)
        at = repository.at(c)
        current = observations.observe(
            c,
            bid,
            selected,
            loaded["prepared"].snapshot()["context"]["manifest"]["sources"],
            at,
            loaded=loaded,
        )
        value = policy.context(
            selection,
            selected["target"]["identity"],
            {
                "kind": "package_review_run",
                "operation_id": run["operation"]["id"],
                "operation_state": run["operation"]["state"],
                "result_available": run["result"] is not None,
            },
            current,
            policy.summary(
                loaded["summary"],
                changed=any(item["status"] == "changed" for item in current.values()),
            ),
            {
                "package_revision": policy.package_target(selected["target"]),
                "authority_revision": policy.package_target(selected["authority"]),
                "package_review_run": policy.run_target(selection),
                "package_submission": None,
            },
            at,
        )
        return expected(value, expected_selection_digest)


def resolve_submission(bid, submission_id, *, expected_selection_digest=None):
    request_ids(bid, submission_id)
    with snapshot("submission") as c:
        loaded = repository.exact_submission(c, bid, submission_id)
        record, m, selected = loaded["record"], loaded["manifest"], loaded["selected"]
        run = loaded["run"]
        bound_run = policy.run_selection(m["review_run"], selected) if run else None
        selection = {
            **policy.package_target(selected["target"]),
            "kind": "package_submission",
            "submission_id": submission_id,
            "package_binding_digest": record["package_binding"]["digest"],
            "inventory": m["selection_request"]["inventory"],
            "review_run": bound_run,
        }
        at = repository.at(c)
        current = observations.observe(
            c, bid, selected, m["context"]["current"]["sources"], at, loaded=run, submission=loaded
        )
        bound_missing = run is not None and m["review_run"]["result"] is None
        summary = policy.submission_review(m["review_run"], run["summary"] if run else None)
        value = policy.context(
            selection,
            selected["target"]["identity"],
            {
                "kind": "package_submission",
                "registration_kind": record["kind"],
                "submitted_at": record["submitted_at"],
                "recorded_at": record["recorded_at"],
                "supersedes_id": record["supersedes_id"],
                "gate_checked_at_registration": record["gate_checked"],
                "platform_submission_verified": False,
                "pre_submission_system_check_verified": False,
            },
            current,
            policy.summary(
                summary,
                submission=True,
                bound_missing=bound_missing,
                changed=any(item["status"] == "changed" for item in current.values()),
            ),
            {
                "package_revision": policy.package_target(selected["target"]),
                "authority_revision": policy.package_target(selected["authority"])
                if selected["authority"]
                else None,
                "package_review_run": policy.run_target(bound_run) if bound_run else None,
                "package_submission": {
                    "kind": "package_submission",
                    "bid_id": bid,
                    "submission_id": submission_id,
                    "package_binding_digest": record["package_binding"]["digest"],
                },
            },
            at,
        )
        return expected(value, expected_selection_digest)


def build_relations(bid, build_id, *, limit=20, cursor=None):
    from packages.work_contexts import relations

    request_ids(bid, build_id)
    if type(limit) is not int or not 1 <= limit <= 50:
        policy.fail("REQUEST_INVALID", "关联目录每页数量须为 1 至 50", 422)
    with snapshot("relations") as c:
        return relations.page(c, bid, build_id, limit=limit, cursor=cursor)
