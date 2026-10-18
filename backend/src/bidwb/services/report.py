"""评审报告：一轮评审的结论与下一步。

报告是项目的落地页，只汇总已有的事实——响应矩阵、问题分类计数、评分预测、报价模拟——不产生新的判断。
“下一步”按对中标的影响排序：先是可能被否决的问题，再是依据未确认的关键规则，然后才是得分与报价。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor, require_project
from bidwb.errors import NotFound
from bidwb.schemas import (
    CategoryCount,
    Compliance,
    NextAction,
    PipelineStatus,
    PricePlanWithSimulation,
    PriceSummary,
    ProjectSettings,
    ProjectSummary,
    Report,
    ReportBasis,
)
from bidwb.services import compliance, pipeline, predictions, price
from bidwb.services import projects as projects_service
from bidwb.services import rules as rules_service
from bidwb.services.findings import OPEN_STATES
from bidwb.storage import ObjectStore

_CATEGORIES = ("disqualification", "response", "consistency", "scope", "improvement")
_CLOSED_STATES = ("resolved", "rejected")


def _rank(actions: list[NextAction]) -> list[NextAction]:
    priorities = {
        "verify_sources": 1,
        "upload_materials": 1,
        "retry_analysis": 2,
        "reanalyze": 2,
        "start_analysis": 2,
        "wait_analysis": 2,
        "handle_disqualification": 3,
        "handle_critical": 3,
        "review_unclear": 4,
        "verify_facts": 4,
        "confirm_rules": 4,
        "handle_findings": 5,
        "improve_score": 5,
    }
    ranked = [a.model_copy(update={"priority": priorities.get(a.key, 6)}) for a in actions]
    # 同级优先登记已满足闸门的提交，再看非阻断建议和报价；报价不构成放行前提。
    return sorted(ranked, key=lambda a: (a.priority, 0 if a.key in {"submit", "record_outcome"} else 1))


def _category_counts(conn: Connection, project_id: str, snapshot_id: str) -> list[CategoryCount]:
    rows = db.all_(
        conn,
        """SELECT f.category, count(*) AS total,
                  count(*) FILTER (WHERE s.state = ANY(:open)) AS open,
                  count(*) FILTER (WHERE s.state = ANY(:closed)) AS resolved
           FROM findings f JOIN finding_states s ON s.finding_id=f.id
           WHERE f.project_id=:p AND f.snapshot_id=:s GROUP BY f.category""",
        {"p": project_id, "s": snapshot_id, "open": list(OPEN_STATES), "closed": list(_CLOSED_STATES)},
    )
    by = {r["category"]: r for r in rows}
    return [
        CategoryCount(category=c, total=by[c]["total"], open=by[c]["open"], resolved=by[c]["resolved"])
        if c in by
        else CategoryCount(category=c, total=0, open=0, resolved=0)
        for c in _CATEGORIES
    ]


def _next_actions(
    status_: PipelineStatus,
    matrix: Compliance,
    categories: list[CategoryCount],
    unconfirmed_qualification: int,
    has_price: bool,
    submitted: bool,
    has_outcome: bool,
    project_state: str,
    settings: ProjectSettings,
    critical_open: int = 0,
    facts_open: int = 0,
    technical_open: int | None = None,
    suggestions_open: int | None = None,
    scoring_gap: bool = False,
) -> list[NextAction]:
    """按项目开关裁剪：关闭的模块不出现在“下一步”里，规则按原文接受时不催确认。"""
    if status_.word_pdf_required or status_.input_verification_required or status_.stage != "done":
        return _rank(_actions_before_report(status_))
    if status_.stale_reasons:
        return _rank(
            [
                NextAction(
                    key="reanalyze",
                    title="资料、规则或事实有更新，重新评审",
                    detail="当前报告基于更早的输入，旧风险保留在历史报告中。",
                    target="report",
                    count=None,
                )
            ]
        )
    actions: list[NextAction] = []
    open_by = {c.category: c.open for c in categories}
    qualification_open = open_by["disqualification"] + open_by["response"]
    incomplete = matrix.coverage is None or matrix.coverage.status != "complete" or matrix.qualification.failed > 0
    if incomplete:
        actions.append(
            NextAction(
                key="retry_analysis",
                title="关键核对覆盖未完成，重新评审",
                detail="存在检查失败或未覆盖的要求，不能用不完整结论登记提交。",
                target="report",
                count=None,
            )
        )
    if qualification_open:
        actions.append(
            NextAction(
                key="handle_disqualification",
                title=f"处理 {qualification_open} 个可能被否决或不满足强制要求的问题",
                detail="这类问题处理完之前不能登记提交。",
                target="findings",
                count=qualification_open,
            )
        )
    actions.extend(
        [
            NextAction(
                key="handle_critical",
                title=f"处理 {critical_open} 个其他关键风险",
                detail="存在被标为关键的未处理问题，先核对原文并处理。",
                target="findings",
                count=critical_open,
            )
        ]
        if critical_open
        else []
    )
    unclear = matrix.qualification.unclear + matrix.qualification.failed
    if unclear:
        actions.append(
            NextAction(
                key="review_unclear",
                title=f"核对 {unclear} 条正文没有明确响应的废标／强制类条款",
                detail="模型在正文里找不到明确依据（或检查失败）。“无法判断”不等于“满足”，需要人确认确实响应了。",
                target="report",
                count=unclear,
            )
        )
    if unconfirmed_qualification and not settings.accept_rules_as_written:
        actions.append(
            NextAction(
                key="confirm_rules",
                title=f"确认 {unconfirmed_qualification} 条废标／否决／强制类规则",
                detail="这些规则决定能否入围，评审暂按模型提取的原文判断，确认后结论才算数。",
                target="rules",
                count=unconfirmed_qualification,
            )
        )
    actions.extend(
        [
            NextAction(
                key="verify_facts",
                title=f"核实 {facts_open} 个问题需要的事实",
                detail="只录入有原件依据的事实；录入后重新评审，不把模型建议当成事实。",
                target="rules",
                count=facts_open,
            )
        ]
        if facts_open
        else []
    )
    other_open = technical_open if technical_open is not None else open_by["consistency"] + open_by["scope"]
    if other_open:
        actions.append(
            NextAction(
                key="handle_findings",
                title=f"处理 {other_open} 个影响得分或一致性的问题",
                detail="按失分影响从大到小处理。",
                target="findings",
                count=other_open,
            )
        )
    if scoring_gap or matrix.scoring.failed or matrix.scoring.unclear:
        actions.append(
            NextAction(
                key="improve_score",
                title="核对评分覆盖与失分点",
                detail="评分检查有失败或缺少明确响应，先查看具体缺口；预测不完整本身不替代提交闸门。",
                target="report",
                count=None,
            )
        )
    suggestions = suggestions_open if suggestions_open is not None else open_by["improvement"]
    if suggestions:
        actions.append(
            NextAction(
                key="handle_suggestions",
                title=f"查看 {suggestions} 个其他建议",
                detail="这些建议不属于关键风险，是否登记提交仍以正式检查为准。",
                target="findings",
                count=suggestions,
            )
        )
    if settings.price and not has_price:
        actions.append(
            NextAction(
                key="set_price",
                title="填写评标价规则，模拟报价得分",
                detail="价格分与技术分合在一起才决定排名。",
                target="price",
                count=None,
            )
        )
    if (
        project_state == "ready_to_submit"
        and not incomplete
        and not qualification_open
        and not critical_open
        and (not unconfirmed_qualification or settings.accept_rules_as_written)
    ):
        actions.append(NextAction(key="submit", title="登记提交", detail="关键问题与强制性要求已处理完。", target="submit", count=None))
    if settings.outcome_tracking and submitted and not has_outcome:
        actions.append(
            NextAction(
                key="record_outcome", title="登记开标结果", detail="结果用来校准预测，让下一次评审更准。", target="outcomes", count=None
            )
        )
    return _rank(actions)


@dataclass(frozen=True)
class _Round:
    """一轮已完成评审的汇总输入，报告与项目摘要共用。"""

    status: PipelineStatus
    snapshot_id: str
    as_of: datetime
    effective: list[db.Row]
    matrix: Compliance
    categories: list[CategoryCount]
    plan: PricePlanWithSimulation | None
    actions: list[NextAction]


def _round(conn: Connection, actor: Actor, project_id: str, status_: PipelineStatus, snapshot_id: str) -> _Round:
    snapshot = db.one(conn, "SELECT rule_set_id,as_of FROM input_snapshots WHERE id=:s", {"s": snapshot_id})
    assert snapshot is not None
    effective = rules_service.effective_rules(conn, project_id, snapshot["rule_set_id"])
    matrix = compliance.for_snapshot(conn, project_id, snapshot_id)
    categories = _category_counts(conn, project_id, snapshot_id)
    groups = db.all_(
        conn,
        """SELECT CASE
        WHEN f.category IN ('disqualification','response') THEN 'qualification'
        WHEN f.severity='critical' THEN 'critical'
        WHEN f.nature='needs_confirmation' AND jsonb_array_length(f.required_facts_json)>0 THEN 'facts'
        WHEN f.category IN ('consistency','scope') OR (f.impact='technical' AND f.severity!='improvement') THEN 'technical'
        ELSE 'suggestions' END AS kind,count(*) AS n
        FROM findings f JOIN finding_states s ON s.finding_id=f.id
        WHERE f.project_id=:p AND f.snapshot_id=:s AND s.state=ANY(:open) GROUP BY 1""",
        {"p": project_id, "s": snapshot_id, "open": list(OPEN_STATES)},
    )
    counts = {r["kind"]: int(r["n"]) for r in groups}
    prediction_state = db.scalar(
        conn,
        "SELECT status FROM predictions WHERE project_id=:p AND snapshot_id=:s ORDER BY created_at DESC,id DESC LIMIT 1",
        {"p": project_id, "s": snapshot_id},
    )
    settings = projects_service.settings_of(conn, project_id)
    plan = price.get_plan(conn, actor, project_id) if settings.price else None
    submission = db.one(
        conn,
        "SELECT s.id FROM submissions s WHERE s.project_id=:p AND NOT EXISTS(SELECT 1 FROM submissions n WHERE n.supersedes=s.id) ORDER BY s.submitted_at DESC,s.id DESC LIMIT 1",
        {"p": project_id},
    )
    outcome = (
        db.one(conn, "SELECT 1 AS x FROM outcomes WHERE submission_id=:i LIMIT 1", {"i": submission["id"]})
        if submission is not None
        else None
    )
    project = db.one(conn, "SELECT state FROM projects WHERE id=:p", {"p": project_id})
    assert project is not None
    actions = _next_actions(
        status_,
        matrix,
        categories,
        sum(1 for r in effective if r["kind"] in rules_service.QUALIFICATION_KINDS and r["basis"] == "unconfirmed"),
        plan is not None,
        submission is not None,
        outcome is not None,
        project["state"],
        settings,
        critical_open=counts.get("critical", 0),
        facts_open=counts.get("facts", 0),
        technical_open=counts.get("technical", 0),
        suggestions_open=counts.get("suggestions", 0),
        scoring_gap=prediction_state == "failed" or any(step.key == "prediction" and step.state == "failed" for step in status_.steps),
    )
    return _Round(status_, snapshot_id, snapshot["as_of"], effective, matrix, categories, plan, actions)


def _actions_before_report(status_: PipelineStatus) -> list[NextAction]:
    """还没有完成的评审：下一步只取决于流水线走到哪里。"""
    if status_.word_pdf_required:
        return [
            NextAction(
                key="upload_materials",
                title="核对或补交此稿的 PDF",
                detail="在对应 Word 原稿处处理，无需重传其他资料。",
                target="materials",
                count=None,
            )
        ]
    if status_.input_verification_required:
        return [
            NextAction(
                key="verify_sources",
                title="先核实补遗或投标条件",
                detail="原文的生效关系尚未核实，处理后再重新评审。",
                target="rules",
                count=None,
            )
        ]
    if status_.stage == "waiting_materials":
        missing = "、".join({"tender": "招标文件", "body": "施组正文"}[m] for m in status_.missing)
        return [
            NextAction(
                key="upload_materials",
                title=f"上传{missing or '资料'}",
                detail="招标文件和施组正文都到齐后自动开始评审。",
                target="materials",
                count=None,
            )
        ]
    if status_.stage == "waiting_start":
        return [
            NextAction(key="start_analysis", title="开始评审", detail="资料已齐，本项目设置为手动开始评审。", target="report", count=None)
        ]
    if status_.stage == "failed":
        return [NextAction(key="retry_analysis", title="评审中断，重新评审", detail="已完成的环节不会重做。", target="report", count=None)]
    return [NextAction(key="wait_analysis", title="正在评审", detail="完成后报告会自动生成。", target="report", count=None)]


def summary(conn: Connection, actor: Actor, project_id: str) -> ProjectSummary:
    status_ = pipeline.status(conn, actor, project_id)
    last = pipeline.last_reviewed(conn, project_id)
    if last is None:
        actions = _rank(_actions_before_report(status_))
        return ProjectSummary(reviewed=False, qualification_open=0, prediction=None, next_action=actions[0] if actions else None)
    r = _round(conn, actor, project_id, status_, last["id"])
    open_by = {c.category: c.open for c in r.categories}
    return ProjectSummary(
        reviewed=True,
        qualification_open=open_by["disqualification"] + open_by["response"],
        prediction=predictions.brief(conn, project_id, r.snapshot_id),
        next_action=r.actions[0] if r.actions else None,
    )


def get_report(conn: Connection, store: ObjectStore, actor: Actor, project_id: str) -> Report:
    require_project(conn, actor, project_id)
    status_ = pipeline.status(conn, actor, project_id)
    last = pipeline.last_reviewed(conn, project_id)
    if last is None:
        raise NotFound("report_not_ready", "还没有完成的评审")
    r = _round(conn, actor, project_id, status_, last["id"])
    unconfirmed = sum(1 for e in r.effective if e["basis"] == "unconfirmed")
    plan = r.plan
    return Report(
        project_id=project_id,
        snapshot_id=r.snapshot_id,
        round_no=status_.round_no or 1,
        basis=ReportBasis(
            rules_total=len(r.effective),
            rules_confirmed=len(r.effective) - unconfirmed,
            rules_unconfirmed=unconfirmed,
            coverage=r.matrix.coverage,
            generated_from_snapshot_at=r.as_of,
        ),
        qualification=r.matrix,
        categories=r.categories,
        prediction=predictions.for_snapshot(conn, store, project_id, r.snapshot_id),
        price=(
            PriceSummary(
                plan_id=plan.plan.plan_id,
                exchange_rate=plan.simulation.exchange_rate,
                best=plan.simulation.best,
                candidates=plan.simulation.candidates,
                created_at=plan.plan.created_at,
            )
            if plan
            else None
        ),
        next_actions=r.actions,
        pipeline=status_,
    )
