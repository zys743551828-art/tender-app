"""Optional exact-package historical admission and feature-free research commands."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb

from apps.api.auth import auth
from packages.contracts.package_historical_research_api import (
    PackageHistoryAdmissionRequest,
    PackageHistoryCohortRequest,
    PackageHistoryJobControl,
    PackageHistoryJobRequest,
    PackageHistoryProtocolRequest,
)
from packages.domain.runtime import Command, DomainError, connection
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance import package_history_repository as repository

SCOPE = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}"
BASE = "/api/v1/package-historical-research"
router = APIRouter(tags=["package-historical-research"])


def exact_query(request, allowed=()):
    keys = [key for key, _ in request.query_params.multi_items()]
    if len(keys) != len(set(keys)) or set(keys) - set(allowed):
        raise DomainError(
            "PACKAGE_HISTORY_QUERY_INVALID", "历史研究查询参数不得重复或包含未知字段", 422
        )


def reply(value, tag, *, status=200, replay=False):
    headers = {"ETag": tag, "Cache-Control": "private, no-store"}
    if replay:
        headers["Idempotency-Replayed"] = "true"
    return JSONResponse(value, status_code=status, headers=headers)


def command(c, request, actor, kind, target, body):
    return Command(
        c,
        actor["member_id"],
        kind,
        target,
        request.headers.get("idempotency-key"),
        body,
        request.headers.get("if-match"),
    )


def applied(cmd, value, kind, identity, *, status=201):
    tag = repository.tag(kind, identity, value)
    receipt = cmd.finish(value, status, {"ETag": tag})
    return reply(receipt["body"], tag, status=status)


def replay(cmd):
    if cmd.replay:
        return reply(
            cmd.replay["body"],
            cmd.replay["headers"]["ETag"],
            status=cmd.replay["status"],
            replay=True,
        )
    return None


@router.get(SCOPE + "/historical-admission-context")
def admission_context(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    request: Request,
    submission_id: UUID = Query(...),
    outcome_id: UUID = Query(...),
):
    auth(request)
    exact_query(request, ("submission_id", "outcome_id"))
    with repository.errors(), connection() as c:
        value, tag = repository.context(
            c, (bid_id, package_id, revision_id), scope_id, submission_id, outcome_id
        )
        return reply(value, tag)


@router.post(SCOPE + "/historical-admissions")
def admit(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    request: Request,
    body: PackageHistoryAdmissionRequest,
):
    actor = auth(request, True)
    value = body.model_dump(mode="json")
    with repository.errors(), connection() as c:
        repository.require(c)
        cmd = command(c, request, actor, "package-history-admission", scope_id, value)
        old = replay(cmd)
        if old is not None:
            return old
        context, tag = repository.context(
            c, (bid_id, package_id, revision_id), scope_id, body.submission_id, body.outcome_id
        )
        repository.match(request.headers.get("if-match"), tag)
        if context["context_digest"] != body.context_digest or str(body.proof_id) not in {
            r["id"] for r in context["proofs"]
        }:
            raise DomainError(
                "PACKAGE_HISTORY_EXACT_PROOF_REQUIRED",
                "请选择同一范围、实交、官方结果及当前证据回执",
                409,
            )
        result = c.execute(
            "SELECT package_historical_research.admit(%s,%s,%s) AS value",
            (body.proof_id, actor["member_id"], cmd.id),
        ).fetchone()["value"]
        return applied(cmd, result, "admission", result["id"])


@router.get(BASE + "/admissions/{admission_id}")
def admission(admission_id: UUID, request: Request):
    auth(request)
    exact_query(request)
    with repository.errors(), connection() as c:
        repository.require(c)
        value = c.execute(
            "SELECT package_historical_research.admission_view(%s) AS value", (admission_id,)
        ).fetchone()["value"]
        return reply(value, repository.tag("admission-view", admission_id, value))


@router.get(BASE + "/cpu-protocol-template")
def template(request: Request):
    auth(request)
    exact_query(request)
    with connection() as c:
        configured = repository.configured(c, research=True)
    document = cpu.protocol()
    value = {
        "schema_configured": configured,
        "document": document,
        "method_digest": document["method"]["digest"],
        "signed_proof_public_upload": False,
        "feature_calibration_available": False,
        "research_only": True,
        "formal_eligibility": "unavailable",
    }
    return reply(value, repository.tag("protocol-template", UUID(int=0), value))


@router.post(BASE + "/protocols")
def create_protocol(request: Request, body: PackageHistoryProtocolRequest):
    actor = auth(request, True)
    document = cpu.protocol(seed=body.seed, bootstrap_iterations=body.bootstrap_iterations)
    if document["method"]["digest"] != body.method_digest:
        raise DomainError(
            "PACKAGE_HISTORY_METHOD_CHANGED", "CPU 方法已变化，请读取当前方法再冻结", 409
        )
    with repository.errors(), connection() as c:
        repository.require(c, research=True)
        cmd = command(
            c,
            request,
            actor,
            "package-history-protocol",
            actor["member_id"],
            body.model_dump(mode="json"),
        )
        old = replay(cmd)
        if old is not None:
            return old
        result = c.execute(
            "SELECT package_historical_research.register_protocol(%s,%s,%s) AS value",
            (Jsonb(document), actor["member_id"], cmd.id),
        ).fetchone()["value"]
        return applied(cmd, result, "protocol", result["id"])


@router.post(BASE + "/cohorts")
def create_cohort(request: Request, body: PackageHistoryCohortRequest):
    actor = auth(request, True)
    value = body.model_dump(mode="json")
    with repository.errors(), connection() as c:
        repository.require(c, research=True)
        cmd = command(c, request, actor, "package-history-cohort", body.protocol_id, value)
        old = replay(cmd)
        if old is not None:
            return old
        result = c.execute(
            "SELECT package_historical_research.freeze_cohort(%s,%s,%s,%s,%s,%s) AS value",
            (
                body.protocol_id,
                body.submission_split_at,
                body.label_available_as_of,
                Jsonb(value["selections"]),
                actor["member_id"],
                cmd.id,
            ),
        ).fetchone()["value"]
        return applied(cmd, result, "cohort", result["id"])


@router.get(BASE + "/cohorts/{cohort_id}")
def cohort(cohort_id: UUID, request: Request):
    auth(request)
    exact_query(request)
    with repository.errors(), connection() as c:
        repository.require(c, research=True)
        value = c.execute(
            "SELECT package_historical_research.cohort_view(%s) AS value", (cohort_id,)
        ).fetchone()["value"]
        return reply(value, repository.tag("cohort-view", cohort_id, value))


@router.post(BASE + "/cohorts/{cohort_id}/jobs")
def start_job(cohort_id: UUID, request: Request, body: PackageHistoryJobRequest):
    actor = auth(request, True)
    with repository.errors(), connection() as c:
        repository.require(c, research=True)
        cmd = command(
            c, request, actor, "package-history-job", cohort_id, body.model_dump(mode="json")
        )
        old = replay(cmd)
        if old is not None:
            return old
        current = c.execute(
            "SELECT package_historical_research.cohort_view(%s) AS value", (cohort_id,)
        ).fetchone()["value"]
        repository.match(
            request.headers.get("if-match"), repository.tag("cohort-view", cohort_id, current)
        )
        if not current["current"]:
            raise DomainError(
                "PACKAGE_HISTORY_COHORT_STALE", "原件、成绩或相关分组已变化，不能启动新任务", 409
            )
        result = c.execute(
            "SELECT package_historical_research.start_job(%s,%s,%s,%s) AS value",
            (cohort_id, body.kind, actor["member_id"], cmd.id),
        ).fetchone()["value"]
        return applied(cmd, result, "job", result["job_id"])


@router.get(BASE + "/jobs/{job_id}")
def job(job_id: UUID, request: Request):
    auth(request)
    exact_query(request)
    with repository.errors(), connection() as c:
        repository.require(c, research=True)
        value = c.execute(
            "SELECT package_historical_research.job_view(%s) AS value", (job_id,)
        ).fetchone()["value"]
        return reply(value, repository.tag("job-view", job_id, value))


@router.post(BASE + "/jobs/{job_id}/control")
def control(job_id: UUID, request: Request, body: PackageHistoryJobControl):
    actor = auth(request, True)
    with repository.errors(), connection() as c:
        repository.require(c, research=True)
        cmd = command(
            c, request, actor, "package-history-job-control", job_id, body.model_dump(mode="json")
        )
        old = replay(cmd)
        if old is not None:
            return old
        current = c.execute(
            "SELECT package_historical_research.job_view(%s) AS value", (job_id,)
        ).fetchone()["value"]
        repository.match(
            request.headers.get("if-match"), repository.tag("job-view", job_id, current)
        )
        result = c.execute(
            "SELECT package_historical_research.control_job(%s,%s,%s,%s,%s) AS value",
            (job_id, body.generation, body.action, actor["member_id"], cmd.id),
        ).fetchone()["value"]
        return applied(cmd, result, "job", result["job_id"], status=200)
