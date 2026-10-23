"""Three independent discovery operations in one native RR READ ONLY snapshot each."""

from contextlib import contextmanager

import psycopg

from packages.authoring_input_catalog import facts, nodes, permissions, policy
from packages.contracts import authoring_input_catalog_api as contract
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, connection


@contextmanager
def snapshot(kind):
    try:
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            c.execute("SET LOCAL statement_timeout='20s'")
            permissions.require(c, kind)
            yield c
    except DomainError as error:
        if error.code.startswith("AUTHORING_INPUT_CATALOG_"):
            raise
        if error.status == 404:
            policy.fail("NOT_FOUND", "所选原生记录不属于这个项目或不存在", 404)
        raise DomainError(
            "AUTHORING_INPUT_CATALOG_CORRUPT", "所选原生正文或来源绑定不能完整核验", 500
        ) from error
    except PackageError as error:
        if error.code.endswith("NOT_FOUND"):
            policy.fail("NOT_FOUND", "所选资料包原修订不存在于这个项目", 404)
        raise DomainError(
            "AUTHORING_INPUT_CATALOG_CORRUPT", "所选资料包的冻结身份不能核验", 500
        ) from error
    except (TypeError, KeyError, ValueError, RecursionError, AttributeError) as error:
        raise DomainError(
            "AUTHORING_INPUT_CATALOG_CORRUPT", "采集目录的原生数据不能完整核验", 500
        ) from error
    except (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable) as error:
        raise DomainError(
            "AUTHORING_INPUT_CATALOG_UNAVAILABLE", "采集目录所需只读权限或存储不可用", 503
        ) from error
    except psycopg.errors.QueryCanceled as error:
        raise DomainError(
            "AUTHORING_INPUT_CATALOG_READ_TIMEOUT",
            "完整目录读取超时，未返回局部观察",
            503,
            retryable=True,
        ) from error


def at(c):
    return c.execute("SELECT transaction_timestamp() AS at").fetchone()["at"].isoformat()


def stable_nodes(
    bid, snapshot_id, section_id, *, expected_snapshot_digest, expected_section_digest
):
    policy.request_ids(bid, snapshot_id, section_id)
    policy.request_digest(expected_snapshot_digest)
    policy.request_digest(expected_section_digest)
    with snapshot("nodes") as c:
        stamp = at(c)
        value = nodes.catalog(
            c, bid, snapshot_id, section_id, expected_snapshot_digest, expected_section_digest
        )
        return contract.checked("PackageAuthoringNodeCatalog", policy.marker(value, stamp))


def fact_sets(bid, *, limit=20, cursor=None):
    policy.request_ids(bid)
    with snapshot("sets") as c:
        stamp = at(c)
        value, items = facts.sets(c, bid)
        page = policy.page(
            value,
            items,
            identity="fact_set_id",
            scope={"kind": "fact_sets", "bid_id": bid},
            limit=limit,
            cursor=cursor,
            at=stamp,
        )
        return contract.checked("PackageAuthoringFactSetPage", page)


def exact_facts(
    bid,
    fact_set_id,
    *,
    expected_fact_set_digest,
    fact_head_revision,
    target,
    authority,
    limit=20,
    cursor=None,
):
    policy.request_ids(bid, fact_set_id)
    policy.request_digest(expected_fact_set_digest)
    for package in (target, authority):
        if not isinstance(package, dict) or set(package) != {
            "package_id",
            "revision_id",
            "manifest_digest",
        }:
            policy.fail("REQUEST_INVALID", "请选择完整且明确的两个资料包原修订", 422)
        policy.request_ids(package["package_id"], package["revision_id"])
        policy.request_digest(package["manifest_digest"])
    if type(fact_head_revision) is not int or not 1 <= fact_head_revision <= 9007199254740991:
        policy.fail("REQUEST_INVALID", "请选择目录中明确观察到的事实头修订", 422)
    selection = {
        "fact_set_id": fact_set_id,
        "fact_set_digest": expected_fact_set_digest,
        "fact_head_revision": fact_head_revision,
        "target": target,
        "authority": authority,
    }
    with snapshot("facts") as c:
        stamp = at(c)
        value, items = facts.catalog(c, bid, selection, stamp)
        page = policy.page(
            value,
            items,
            identity="fact_id",
            scope={"kind": "facts", "bid_id": bid, **selection},
            limit=limit,
            cursor=cursor,
            at=stamp,
        )
        return contract.checked("PackageAuthoringFactCatalog", page)
