"""中标导向的度量：入围率与中标率、废标／否决风险的闭环、预测校准，以及每个项目逐轮的变化。

只统计与中标有关的结果，不统计用了多少时间或人力。各项目只算调用者有权查看的。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor
from bidwb.schemas import Metrics, OutcomeMetrics, QualificationMetrics, RoundPoint, RoundTrend
from bidwb.services import predictions
from bidwb.services.findings import OPEN_STATES
from bidwb.util import decimal_text

_SHORTLISTED = ("technical_shortlisted", "candidate", "awarded", "not_awarded")
_RATE_PLACES = Decimal("0.0001")
_MAX_TRENDS = 20

# 每个提交取最新、未被取代、未冲突的一条结果
_LATEST_OUTCOME = """
SELECT DISTINCT ON (s.id) s.id AS submission_id, s.project_id, s.snapshot_id, o.stage_result, o.target, o.value_decimal, o.maximum_decimal
FROM submissions s JOIN outcomes o ON o.submission_id=s.id AND o.project_id=s.project_id
WHERE s.project_id = ANY(:ids) AND o.verification_status <> 'conflict' AND NOT EXISTS (SELECT 1 FROM outcomes x WHERE x.supersedes=o.id)
AND NOT EXISTS (SELECT 1 FROM submissions newer WHERE newer.supersedes=s.id)
ORDER BY s.id, o.known_at DESC, o.id DESC
"""


def _rate(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return decimal_text((Decimal(numerator) / Decimal(denominator)).quantize(_RATE_PLACES, ROUND_HALF_UP))


def _outcomes(conn: Connection, ids: list[str]) -> tuple[OutcomeMetrics, list[db.Row]]:
    rows = db.all_(conn, _LATEST_OUTCOME, {"ids": ids})
    submissions = db.scalar(
        conn,
        "SELECT count(*) FROM submissions s WHERE s.project_id = ANY(:ids) AND NOT EXISTS (SELECT 1 FROM submissions x WHERE x.supersedes=s.id)",
        {"ids": ids},
    )
    count = {k: sum(1 for r in rows if r["stage_result"] == k) for k in ("not_shortlisted", "rejected", "awarded", "not_awarded")}
    shortlisted = sum(1 for r in rows if r["stage_result"] in _SHORTLISTED)
    decided = shortlisted + count["not_shortlisted"] + count["rejected"]
    final = count["awarded"] + count["not_awarded"] + count["not_shortlisted"] + count["rejected"]
    return (
        OutcomeMetrics(
            submissions=int(submissions or 0),
            decided=decided,
            shortlisted=shortlisted,
            not_shortlisted=count["not_shortlisted"],
            rejected=count["rejected"],
            awarded=count["awarded"],
            not_awarded=count["not_awarded"],
            shortlist_rate=_rate(shortlisted, decided),
            award_rate=_rate(count["awarded"], final),
        ),
        rows,
    )


def _qualification(conn: Connection, ids: list[str], outcome_rows: list[db.Row]) -> QualificationMetrics:
    latest = db.all_(
        conn,
        """SELECT DISTINCT ON (s.project_id) s.id FROM input_snapshots s
           WHERE s.project_id = ANY(:ids) AND EXISTS (SELECT 1 FROM jobs d WHERE d.snapshot_id=s.id AND d.kind='diagnosis' AND d.state='succeeded')
           ORDER BY s.project_id, s.as_of DESC, s.id DESC""",
        {"ids": ids},
    )
    states = db.all_(
        conn,
        """SELECT st.state FROM findings f JOIN finding_states st ON st.finding_id=f.id
           WHERE f.snapshot_id = ANY(:snaps) AND f.category IN ('disqualification','response')""",
        {"snaps": [r["id"] for r in latest]},
    )
    open_at_submission = db.scalar(
        conn,
        """SELECT count(*) FROM findings f JOIN finding_states st ON st.finding_id=f.id
           WHERE f.category IN ('disqualification','response') AND st.state = ANY(:open)
             AND f.snapshot_id IN (SELECT snapshot_id FROM submissions WHERE project_id = ANY(:ids))""",
        {"ids": ids, "open": list(OPEN_STATES)},
    )
    return QualificationMetrics(
        identified=len(states),
        resolved_or_dismissed=sum(1 for s in states if s["state"] in ("resolved", "rejected")),
        open_at_submission=int(open_at_submission or 0),
        rejected_by_buyer=sum(1 for r in outcome_rows if r["stage_result"] == "rejected"),
    )


def _trends(conn: Connection, ids: list[str], outcome_rows: list[db.Row]) -> list[RoundTrend]:
    actual = {r["project_id"]: r for r in outcome_rows if r["target"] == "technical_total" and r["value_decimal"] is not None}
    trends: list[RoundTrend] = []
    projects = db.all_(
        conn,
        """SELECT p.id,p.title FROM projects p
           WHERE p.id = ANY(:ids) AND EXISTS (SELECT 1 FROM jobs j WHERE j.project_id=p.id AND j.kind='diagnosis' AND j.state='succeeded')
           ORDER BY p.created_at DESC, p.id LIMIT :n""",
        {"ids": ids, "n": _MAX_TRENDS},
    )
    for project in projects:
        snaps = db.all_(
            conn,
            """SELECT s.id, s.as_of FROM input_snapshots s
               WHERE s.project_id=:p AND EXISTS (SELECT 1 FROM jobs d WHERE d.snapshot_id=s.id AND d.kind='diagnosis' AND d.state='succeeded')
               ORDER BY s.as_of, s.id""",
            {"p": project["id"]},
        )
        rounds: list[RoundPoint] = []
        maximum = None
        for number, snap in enumerate(snaps, start=1):
            pred = db.one(
                conn,
                "SELECT estimated_decimal,maximum_decimal FROM predictions WHERE snapshot_id=:s AND status='candidate' ORDER BY created_at DESC, id DESC LIMIT 1",
                {"s": snap["id"]},
            )
            counts = db.one(
                conn,
                """SELECT count(*) FILTER (WHERE st.state = ANY(:open)) AS open,
                          count(*) FILTER (WHERE st.state IN ('resolved','rejected')) AS resolved,
                          count(*) FILTER (WHERE st.state = ANY(:open) AND f.category IN ('disqualification','response')) AS qual
                   FROM findings f JOIN finding_states st ON st.finding_id=f.id WHERE f.snapshot_id=:s""",
                {"s": snap["id"], "open": list(OPEN_STATES)},
            )
            assert counts is not None
            maximum = decimal_text(pred["maximum_decimal"]) if pred else maximum
            rounds.append(
                RoundPoint(
                    round_no=number,
                    snapshot_id=snap["id"],
                    estimated_value=decimal_text(pred["estimated_decimal"]) if pred else None,
                    open_findings=counts["open"],
                    resolved_findings=counts["resolved"],
                    open_qualification=counts["qual"],
                )
            )
        outcome = actual.get(project["id"])
        trends.append(
            RoundTrend(
                project_id=project["id"],
                title=project["title"],
                maximum=maximum or (decimal_text(outcome["maximum_decimal"]) if outcome else None),
                actual_value=decimal_text(outcome["value_decimal"]) if outcome else None,
                rounds=rounds,
            )
        )
    return trends


def get_metrics(conn: Connection, actor: Actor) -> Metrics:
    del actor
    ids = [r["id"] for r in db.all_(conn, "SELECT id FROM projects ORDER BY created_at")]
    outcomes, rows = _outcomes(conn, ids)
    return Metrics(
        outcomes=outcomes,
        qualification=_qualification(conn, ids, rows),
        calibration=predictions.calibration(conn),
        trends=_trends(conn, ids, rows),
    )
