"""Opt-in B1 discovery only. Explicit capture keeps the existing command path."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from packages.authoring_input_catalog import policy, service
from packages.contracts.authoring_input_catalog_api import FACTS_PATH, NODES_PATH, SETS_PATH

router = APIRouter(tags=["authoring-input-catalog"])


def query(r, allowed):
    keys = [key for key, _ in r.query_params.multi_items()]
    if len(set(keys)) != len(keys) or set(keys) - set(allowed):
        policy.fail("REQUEST_INVALID", "采集目录参数不能重复或包含未知字段", 422)


def response(value):
    return JSONResponse(value, headers={"Cache-Control": "private, no-store", "Vary": "Cookie"})


@router.get(NODES_PATH)
def stable_nodes(
    bid_id: UUID,
    snapshot_id: UUID,
    section_id: UUID,
    r: Request,
    expected_snapshot_digest: str = Query(..., pattern="^[a-f0-9]{64}$"),
    expected_section_digest: str = Query(..., pattern="^[a-f0-9]{64}$"),
):
    auth(r)
    query(r, ("expected_snapshot_digest", "expected_section_digest"))
    return response(
        service.stable_nodes(
            str(bid_id),
            str(snapshot_id),
            str(section_id),
            expected_snapshot_digest=expected_snapshot_digest,
            expected_section_digest=expected_section_digest,
        )
    )


@router.get(SETS_PATH)
def fact_sets(
    bid_id: UUID,
    r: Request,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=4096),
):
    auth(r)
    query(r, ("limit", "cursor"))
    return response(service.fact_sets(str(bid_id), limit=limit, cursor=cursor))


@router.get(FACTS_PATH)
def exact_facts(
    bid_id: UUID,
    fact_set_id: UUID,
    r: Request,
    expected_fact_set_digest: str = Query(..., pattern="^[a-f0-9]{64}$"),
    fact_head_revision: int = Query(..., ge=1, le=9007199254740991),
    target_package_id: UUID = Query(...),
    target_revision_id: UUID = Query(...),
    target_manifest_digest: str = Query(..., pattern="^[a-f0-9]{64}$"),
    authority_package_id: UUID = Query(...),
    authority_revision_id: UUID = Query(...),
    authority_manifest_digest: str = Query(..., pattern="^[a-f0-9]{64}$"),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=4096),
):
    auth(r)
    query(
        r,
        (
            "expected_fact_set_digest",
            "fact_head_revision",
            "target_package_id",
            "target_revision_id",
            "target_manifest_digest",
            "authority_package_id",
            "authority_revision_id",
            "authority_manifest_digest",
            "limit",
            "cursor",
        ),
    )
    return response(
        service.exact_facts(
            str(bid_id),
            str(fact_set_id),
            expected_fact_set_digest=expected_fact_set_digest,
            fact_head_revision=fact_head_revision,
            target={
                "package_id": str(target_package_id),
                "revision_id": str(target_revision_id),
                "manifest_digest": target_manifest_digest,
            },
            authority={
                "package_id": str(authority_package_id),
                "revision_id": str(authority_revision_id),
                "manifest_digest": authority_manifest_digest,
            },
            limit=limit,
            cursor=cursor,
        )
    )
