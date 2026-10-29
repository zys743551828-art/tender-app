"""Opt-in exact work-context reads. GET never chooses or writes a business head."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from packages.contracts.work_context_api import RELATIONS_PATH, RUN_PATH, SUBMISSION_PATH
from packages.domain.runtime import DomainError
from packages.work_contexts import service

router = APIRouter(tags=["package-work-contexts"])


def query(r, allowed):
    keys = [key for key, _ in r.query_params.multi_items()]
    if len(set(keys)) != len(keys) or set(keys) - set(allowed):
        raise DomainError(
            "WORK_CONTEXT_REQUEST_INVALID", "工作上下文参数不能重复或包含未知字段", 422
        )


def response(value):
    return JSONResponse(value, headers={"Cache-Control": "private, no-store", "Vary": "Cookie"})


@router.get(RUN_PATH)
def resolve_run(
    bid_id: UUID,
    run_id: UUID,
    r: Request,
    expected_selection_digest: str | None = Query(default=None, pattern="^[a-f0-9]{64}$"),
):
    auth(r)
    query(r, ("expected_selection_digest",))
    return response(
        service.resolve_run(
            str(bid_id), str(run_id), expected_selection_digest=expected_selection_digest
        )
    )


@router.get(SUBMISSION_PATH)
def resolve_submission(
    bid_id: UUID,
    submission_id: UUID,
    r: Request,
    expected_selection_digest: str | None = Query(default=None, pattern="^[a-f0-9]{64}$"),
):
    auth(r)
    query(r, ("expected_selection_digest",))
    return response(
        service.resolve_submission(
            str(bid_id), str(submission_id), expected_selection_digest=expected_selection_digest
        )
    )


@router.get(RELATIONS_PATH)
def build_relations(
    bid_id: UUID,
    build_id: UUID,
    r: Request,
    target: Literal["package_revision"] = Query(...),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=4096),
):
    auth(r)
    query(r, ("target", "limit", "cursor"))
    return response(service.build_relations(str(bid_id), str(build_id), limit=limit, cursor=cursor))
