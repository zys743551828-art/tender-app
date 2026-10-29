"""Authenticated read-only batch route; lifecycle and directory projections share one snapshot."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from apps.api.auth import auth
from packages.domain.project_summary_repository import read
from packages.domain.runtime import connection

router = APIRouter(tags=["project-work-summaries"])


@router.get("/api/v1/project-work-summaries")
def summaries(r: Request, bid_id: list[UUID] = Query(min_length=1, max_length=20)):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        c.execute("SET LOCAL statement_timeout='3s'")
        return read(c, bid_id)
