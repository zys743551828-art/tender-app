"""Explicit package observations and immutable facts; originals are read off-transaction."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from apps.api.auth import auth
from apps.api.identity_routes import saved
from apps.api.views import bid_etag
from packages.contracts.package_submissions_api import validate
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, clean, connection, fetch

BASE = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"
router = APIRouter(tags=["bid-package-submissions"])


def service():
    from packages.domain import bid_package_submissions

    return bid_package_submissions


@contextmanager
def submission_errors():
    try:
        yield
    except PackageError as error:
        status = 404 if error.code.endswith("NOT_FOUND") else 409
        if error.code.endswith("CORRUPT"):
            status = 500
        raise DomainError(
            error.code, "所选完整投标包与精确提交依据无法核对，请重新读取原记录", status
        ) from error
    except (psycopg.IntegrityError, psycopg.DataError) as error:
        raise DomainError(
            "PACKAGE_SUBMISSION_STORAGE_REJECTED",
            "实际提交记录、完整包绑定或原命令未满足一致性约束，整次登记已回滚",
            409,
        ) from error


@router.post(BASE + "/submission-preview")
def preview(bid_id: UUID, package_id: UUID, revision_id: UUID, r: Request, body: dict = Body(...)):
    auth(r, True)
    with submission_errors():
        validate("PackageSubmissionSelection", body)
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            result = service().prepare(
                c, tuple(map(str, (bid_id, package_id, revision_id))), body, bid_etag_fn=bid_etag
            )
            return JSONResponse(clean(result), headers={"Cache-Control": "private, no-store"})


async def record(r, actor, scope, body, *, supersedes=None):
    with submission_errors():
        validate("PackageSubmissionRequest", body)
        result, replay = await run_in_threadpool(
            service().register,
            scope,
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
            supersedes=supersedes,
            bid_etag_fn=bid_etag,
            final_auth=lambda: auth(r, True)["member_id"],
        )
        return saved(result, replay)


@router.post(BASE + "/submissions", status_code=201)
async def register(
    bid_id: UUID, package_id: UUID, revision_id: UUID, r: Request, body: dict = Body(...)
):
    actor = await run_in_threadpool(auth, r, True)
    return await record(r, actor, tuple(map(str, (bid_id, package_id, revision_id))), body)


def correction_scope(submission_id, body):
    validate("PackageSubmissionRequest", body)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        previous = fetch(c, "SELECT bid_id FROM submission_records WHERE id=%s", (submission_id,))
    selection = body["selection"]
    return str(previous["bid_id"]), selection["package_id"], selection["revision_id"]


@router.post("/api/v1/submissions/{submission_id}/package-corrections", status_code=201)
async def correct(submission_id: UUID, r: Request, body: dict = Body(...)):
    actor = await run_in_threadpool(auth, r, True)
    with submission_errors():
        scope = await run_in_threadpool(correction_scope, submission_id, body)
        return await record(r, actor, scope, body, supersedes=str(submission_id))
