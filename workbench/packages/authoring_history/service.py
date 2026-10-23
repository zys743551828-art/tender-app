"""Single RR READ ONLY coordinator for explicit historical chapter reads."""

import re
from contextlib import contextmanager
from uuid import UUID

import psycopg

from packages.authoring_history import permissions, repository
from packages.contracts import authoring_history_api as contract
from packages.domain.runtime import DomainError, connection


@contextmanager
def snapshot():
    try:
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            c.execute("SET LOCAL statement_timeout='20s'")
            permissions.require(c)
            yield c
    except DomainError as error:
        if error.code.startswith("AUTHORING_HISTORY_"):
            raise
        raise DomainError(
            "AUTHORING_HISTORY_CORRUPT", "所选历史章节的原生正文或保存格式不能核验", 500
        ) from error
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise DomainError(
            "AUTHORING_HISTORY_CORRUPT", "所选历史章节的原生身份或图片绑定不完整", 500
        ) from error
    except (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable) as error:
        raise DomainError(
            "AUTHORING_HISTORY_UNAVAILABLE", "历史章节所需只读存储或权限不可用", 503
        ) from error
    except psycopg.errors.QueryCanceled as error:
        raise DomainError(
            "AUTHORING_HISTORY_READ_TIMEOUT",
            "完整历史读取超过本次预算，未返回部分正文",
            503,
            retryable=True,
        ) from error


def resolve(bid, draft, section_id, revision, *, expected_digest):
    try:
        valid = all(
            isinstance(value, str) and str(UUID(value)) == value
            for value in (bid, draft, section_id)
        )
    except (TypeError, ValueError, AttributeError):
        valid = False
    if (
        not valid
        or type(revision) is not int
        or not 1 <= revision <= 2**63 - 1
        or not isinstance(expected_digest, str)
        or re.fullmatch(r"[a-f0-9]{64}", expected_digest) is None
    ):
        raise DomainError(
            "AUTHORING_HISTORY_INVALID_REQUEST", "请选择明确的项目、草稿、章节原修订与正文摘要", 422
        )
    with snapshot() as c:
        return contract.checked(
            repository.section(c, bid, draft, section_id, revision, expected_digest)
        )
