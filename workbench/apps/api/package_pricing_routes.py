"""Exact package formula entrypoints; reuse the immutable pricing execution path."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from packages.domain.runtime import connection
from packages.pricing import package_sources
from packages.pricing.package_models import RegisterPackageFormula

router = APIRouter(prefix="/api/v1", tags=["package-pricing"])


def selected(package_id, revision_id, authority_package_id, authority_revision_id):
    return {
        "package_id": str(package_id),
        "revision_id": str(revision_id),
        "authority_package_id": str(authority_package_id),
        "authority_revision_id": str(authority_revision_id),
    }


@router.get("/bids/{bid_id}/package-pricing-context")
def package_context(
    bid_id: UUID,
    request: Request,
    package_id: UUID,
    revision_id: UUID,
    authority_package_id: UUID,
    authority_revision_id: UUID,
):
    auth(request)
    binding = selected(package_id, revision_id, authority_package_id, authority_revision_id)
    with connection() as c:
        value, tag = package_sources.context(c, bid_id, binding)
    return JSONResponse(value, headers={"ETag": tag})


@router.get("/bids/{bid_id}/package-pricing-formula-sources")
def package_source_choices(
    bid_id: UUID,
    request: Request,
    package_id: UUID,
    revision_id: UUID,
    authority_package_id: UUID,
    authority_revision_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    cursor: UUID | None = None,
):
    auth(request)
    binding = selected(package_id, revision_id, authority_package_id, authority_revision_id)
    with connection() as c:
        return package_sources.source_choices(c, bid_id, binding, limit=limit, cursor=cursor)


@router.post("/bids/{bid_id}/package-pricing-formulas")
def register_package_formula(bid_id: UUID, request: Request, body: RegisterPackageFormula):
    from apps.api.pricing_routes import register_formula

    return register_formula(bid_id, request, body)
