"""快照、规则、事实、问题复核、证据检索，以及提交与结果。"""

from __future__ import annotations

from typing import Annotated, TypeVar

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import Connection

from bidwb.api.deps import Body, Ctr, CurrentSession, IdemKey, mutate
from bidwb.schemas import (
    ConfirmRulesRequest,
    ConfirmRulesResult,
    EvidenceRef,
    FactList,
    FactRequest,
    FactSetResult,
    FactWithdrawRequest,
    Finding,
    InputSnapshot,
    Outcome,
    OutcomeRequest,
    OutcomeVerifyRequest,
    ResolveTermRequest,
    Review,
    ReviewRequest,
    RuleSet,
    SearchRequest,
    SearchResult,
    SnapshotRequest,
    Submission,
    SubmissionRequest,
)
from bidwb.services import evidence, findings, outcomes, pipeline, rules, snapshots

router = APIRouter(tags=["review"])

R = TypeVar("R", bound=BaseModel)


def _settled(conn: Connection, project_id: str, result: R) -> R:
    """规则更正、事实变化、问题复核之后对齐项目状态：输入已经变了的项目不能停在“可登记提交”。"""
    pipeline.settle(conn, project_id)
    return result


def _review_settled(conn: Connection, review: Review) -> Review:
    return _settled(conn, review.project_id, review)


class FindingPage(BaseModel):
    items: list[Finding]
    next_cursor: str | None


# ---- 快照
@router.post("/projects/{project_id}/snapshots", response_model=InputSnapshot, operation_id="freezeInput")
def freeze_input(project_id: str, body: SnapshotRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/snapshots",
        body,
        lambda c: snapshots.freeze(c, ctr.store, session.actor, project_id, body, session.request_id),
    )


@router.get("/projects/{project_id}/snapshots", response_model=list[InputSnapshot], operation_id="listSnapshots")
def list_snapshots(project_id: str, session: CurrentSession, ctr: Ctr) -> list[InputSnapshot]:
    with ctr.engine.connect() as conn:
        return snapshots.list_snapshots(conn, session.actor, project_id)


@router.get("/snapshots/{snapshot_id}", response_model=InputSnapshot, operation_id="getSnapshot")
def get_snapshot(snapshot_id: str, session: CurrentSession, ctr: Ctr) -> InputSnapshot:
    with ctr.engine.connect() as conn:
        return snapshots.get_snapshot(conn, session.actor, snapshot_id)


# ---- 规则与事实
@router.post("/projects/{project_id}/rules/terms:resolve", response_model=RuleSet, operation_id="resolveRuleTerm")
def resolve_rule_term(project_id: str, body: ResolveTermRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/rules/terms:resolve",
        body,
        lambda c: _settled(c, project_id, rules.resolve_term(c, session.actor, project_id, body, session.request_id)),
    )


@router.get("/projects/{project_id}/rules", response_model=RuleSet, operation_id="getRules")
def get_rules(project_id: str, session: CurrentSession, ctr: Ctr) -> RuleSet:
    with ctr.engine.connect() as conn:
        return rules.get_rules(conn, session.actor, project_id)


@router.post("/projects/{project_id}/rules:confirm", response_model=ConfirmRulesResult, operation_id="confirmPendingRules")
def confirm_pending_rules(project_id: str, body: ConfirmRulesRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    """一次确认多条未审核的规则（按原文接受）。"""
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/rules:confirm",
        body,
        lambda c: _settled(c, project_id, rules.confirm_pending(c, session.actor, project_id, body, session.request_id)),
    )


@router.post("/rules/{rule_id}/reviews", response_model=Review, operation_id="reviewRule")
def review_rule(rule_id: str, body: ReviewRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /rules/{rule_id}/reviews",
        body,
        lambda c: _review_settled(c, rules.review_rule(c, session.actor, rule_id, body, session.request_id)),
    )


@router.get("/projects/{project_id}/facts", response_model=FactList, operation_id="listFacts")
def list_facts(project_id: str, session: CurrentSession, ctr: Ctr) -> FactList:
    with ctr.engine.connect() as conn:
        return rules.list_facts(conn, session.actor, project_id)


@router.post("/projects/{project_id}/facts", response_model=FactSetResult, operation_id="confirmFact")
def confirm_fact(project_id: str, body: FactRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/facts",
        body,
        lambda c: _settled(c, project_id, rules.add_fact(c, ctr.store, session.actor, project_id, body, session.request_id)),
    )


@router.post("/projects/{project_id}/facts/{fact_id}/withdraw", response_model=FactSetResult, operation_id="withdrawFact")
def withdraw_fact(project_id: str, fact_id: str, body: FactWithdrawRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/facts/{fact_id}/withdraw",
        body,
        lambda c: _settled(c, project_id, rules.withdraw_fact(c, ctr.store, session.actor, project_id, fact_id, body, session.request_id)),
    )


# ---- 问题
@router.get("/projects/{project_id}/findings", response_model=FindingPage, operation_id="listFindings")
def list_findings(
    project_id: str,
    session: CurrentSession,
    ctr: Ctr,
    snapshot_id: str | None = None,
    status: str | None = None,
    category: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> FindingPage:
    with ctr.engine.connect() as conn:
        items, next_cursor = findings.list_findings(
            conn, session.actor, project_id, snapshot_id=snapshot_id, status=status, category=category, cursor=cursor, limit=limit
        )
    return FindingPage(items=items, next_cursor=next_cursor)


@router.get("/findings/{finding_id}", response_model=Finding, operation_id="getFinding")
def get_finding(finding_id: str, session: CurrentSession, ctr: Ctr) -> Finding:
    with ctr.engine.connect() as conn:
        return findings.get_finding(conn, session.actor, finding_id)


@router.post("/findings/{finding_id}/reviews", response_model=Review, operation_id="reviewFinding")
def review_finding(finding_id: str, body: ReviewRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /findings/{finding_id}/reviews",
        body,
        lambda c: _review_settled(c, findings.review_finding(c, session.actor, finding_id, body, session.request_id)),
    )


# ---- 证据
@router.post("/projects/{project_id}/search", response_model=SearchResult, operation_id="searchEvidence")
def search_evidence(project_id: str, body: SearchRequest, session: CurrentSession, ctr: Ctr) -> SearchResult:
    # 只读检索：POST 仅为承载请求体，无副作用，因此不要求幂等键。
    with ctr.engine.connect() as conn:
        return evidence.search(conn, session.actor, project_id, body, ctr.settings)


@router.get("/evidence/{evidence_id}", response_model=EvidenceRef, operation_id="getEvidence")
def get_evidence(evidence_id: str, session: CurrentSession, ctr: Ctr) -> EvidenceRef:
    with ctr.engine.connect() as conn:
        return evidence.get_evidence(conn, session.actor, evidence_id)


# ---- 提交与结果
@router.post("/projects/{project_id}/submissions", response_model=Submission, operation_id="freezeSubmission")
def freeze_submission(project_id: str, body: SubmissionRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/submissions",
        body,
        lambda c: outcomes.freeze_submission(c, session.actor, project_id, body, session.request_id),
    )


@router.get("/projects/{project_id}/submissions", response_model=list[Submission], operation_id="listSubmissions")
def list_submissions(project_id: str, session: CurrentSession, ctr: Ctr) -> list[Submission]:
    with ctr.engine.connect() as conn:
        return outcomes.list_submissions(conn, session.actor, project_id)


@router.post("/projects/{project_id}/outcomes", response_model=Outcome, operation_id="recordOutcome")
def record_outcome(project_id: str, body: OutcomeRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /projects/{project_id}/outcomes",
        body,
        lambda c: outcomes.record_outcome(c, session.actor, project_id, body, session.request_id),
    )


@router.get("/projects/{project_id}/outcomes", response_model=list[Outcome], operation_id="listOutcomes")
def list_outcomes(project_id: str, session: CurrentSession, ctr: Ctr) -> list[Outcome]:
    with ctr.engine.connect() as conn:
        return outcomes.list_outcomes(conn, session.actor, project_id)


@router.post("/outcomes/{outcome_id}/verify", response_model=Outcome, operation_id="verifyOutcome")
def verify_outcome(outcome_id: str, body: OutcomeVerifyRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /outcomes/{outcome_id}/verify",
        body,
        lambda c: outcomes.verify_outcome(c, session.actor, outcome_id, body, session.request_id),
    )
