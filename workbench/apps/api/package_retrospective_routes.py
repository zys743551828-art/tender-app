"""Exact-package retrospective observations, immutable drafts and explicit knowledge candidates."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from apps.api.identity_routes import saved
from packages.contracts.package_retrospectives_api import BASE
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, connection
from packages.retrospectives import catalog, observations, repository

router = APIRouter(tags=["package-retrospectives"])


@contextmanager
def errors():
    try:
        yield
    except PackageError as error:
        raise DomainError(error.code, "所选包或核查身份无法还原，请核对确切记录", 409) from error
    except (psycopg.IntegrityError, psycopg.DataError) as error:
        raise DomainError(
            "PACKAGE_RETROSPECTIVE_STORAGE_REJECTED",
            "复盘与原始实交、结果或知识来源约束不一致，整次操作已回滚",
            409,
        ) from error


@router.get(BASE + "/choices")
def choices(
    bid_id: UUID,
    r: Request,
    kind: str = "submissions",
    submission_id: UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return catalog.choices(
            c, str(bid_id), kind, str(submission_id) if submission_id else None, limit, offset
        )


@router.post(BASE + "/preview")
def preview(bid_id: UUID, r: Request, body: dict = Body(...)):
    auth(r, True)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        value = observations.observe(c, str(bid_id), body)
        return JSONResponse(
            value,
            headers={
                "ETag": repository.preview_tag(bid_id, value["digest"]),
                "Cache-Control": "private, no-store",
            },
        )


@router.post(BASE, status_code=201)
def freeze(bid_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    with errors(), connection() as c:
        result, replay = repository.freeze(
            c,
            str(bid_id),
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
        )
        return saved(result, replay)


@router.get(BASE)
def history(
    bid_id: UUID,
    r: Request,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return repository.directory(c, str(bid_id), limit, offset)


@router.get(BASE + "/{retrospective_id}")
def get(bid_id: UUID, retrospective_id: UUID, r: Request):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        value = repository.detail(c, str(bid_id), str(retrospective_id))
        return JSONResponse(
            value,
            headers={
                "ETag": repository.saved_tag(value["retrospective"]),
                "Cache-Control": "private, no-store",
            },
        )


@router.post(BASE + "/{retrospective_id}/knowledge-candidate", status_code=201)
def candidate(bid_id: UUID, retrospective_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    with errors(), connection() as c:
        result, replay = repository.handoff(
            c,
            str(bid_id),
            str(retrospective_id),
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
        )
        return saved(result, replay)
