"""Authenticated discovery of existing native records; no command or qualification writes."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from apps.api.package_historical_research import exact_query
from packages.contracts.package_history_directory_api import BASE
from packages.model_governance import package_history_directory as directory

router = APIRouter(tags=["package-historical-research-directories"])


def reply(value):
    return JSONResponse(value, headers={"Cache-Control": "private, no-store", "Vary": "Cookie"})


@router.get(BASE + "/admissions")
def admissions(
    request: Request,
    bid_id: UUID | None = Query(default=None),
    scope_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=4096),
):
    auth(request)
    exact_query(request, ("bid_id", "scope_id", "limit", "cursor"))
    return reply(
        directory.read(
            "admissions",
            bid=str(bid_id) if bid_id else None,
            scope=str(scope_id) if scope_id else None,
            limit=limit,
            cursor=cursor,
        )
    )


@router.get(BASE + "/protocols")
def protocols(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=4096),
):
    auth(request)
    exact_query(request, ("limit", "cursor"))
    return reply(directory.read("protocols", limit=limit, cursor=cursor))


@router.get(BASE + "/cohorts")
def cohorts(
    request: Request,
    protocol_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=4096),
):
    auth(request)
    exact_query(request, ("protocol_id", "limit", "cursor"))
    return reply(
        directory.read(
            "cohorts",
            protocol=str(protocol_id) if protocol_id else None,
            limit=limit,
            cursor=cursor,
        )
    )


@router.get(BASE + "/cohorts/{cohort_id}/jobs")
def jobs(
    cohort_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=4096),
):
    auth(request)
    exact_query(request, ("limit", "cursor"))
    return reply(directory.read("jobs", cohort=str(cohort_id), limit=limit, cursor=cursor))
