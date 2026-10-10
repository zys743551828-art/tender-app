"""响应矩阵：一轮评审里每条规则的判定（满足／违反／无法判断／检查失败），废标、否决与强制类单独计数。"""

from __future__ import annotations

from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor, require_project
from bidwb.errors import NotFound
from bidwb.schemas import Compliance, RuleVerdict, TaskCoverage, VerdictCounts
from bidwb.services import evidence
from bidwb.services.rules import QUALIFICATION_KINDS

_VERDICTS = ("satisfied", "violated", "unclear", "failed")


def _counts(rows: list[RuleVerdict]) -> VerdictCounts:
    tally = {v: sum(1 for r in rows if r.verdict == v) for v in _VERDICTS}
    return VerdictCounts(total=len(rows), **tally)


def for_snapshot(conn: Connection, project_id: str, snapshot_id: str) -> Compliance:
    run = db.one(
        conn,
        """SELECT id,coverage_json FROM jobs WHERE project_id=:p AND snapshot_id=:s AND kind='diagnosis' AND state='succeeded'
           ORDER BY finished_at DESC, id DESC LIMIT 1""",
        {"p": project_id, "s": snapshot_id},
    )
    rows: list[RuleVerdict] = []
    if run is not None:
        verdicts = db.all_(
            conn,
            """SELECT v.rule_id,v.verdict,v.rule_basis,v.body_evidence_ids_json,v.note,i.kind,i.statement
               FROM rule_verdicts v JOIN rule_items i ON i.id=v.rule_id WHERE v.run_id=:r ORDER BY i.kind, v.rule_id""",
            {"r": run["id"]},
        )
        linked = db.all_(
            conn,
            "SELECT id,rule_id FROM findings WHERE project_id=:p AND snapshot_id=:s AND rule_id IS NOT NULL ORDER BY id",
            {"p": project_id, "s": snapshot_id},
        )
        by_rule: dict[str, list[str]] = {}
        for f in linked:
            by_rule.setdefault(f["rule_id"], []).append(f["id"])
        for v in verdicts:
            rows.append(
                RuleVerdict(
                    rule_id=v["rule_id"],
                    kind=v["kind"],
                    statement=v["statement"],
                    rule_basis=v["rule_basis"],
                    verdict=v["verdict"],
                    note=v["note"],
                    evidence=evidence.evidence_for_ids(conn, project_id, v["body_evidence_ids_json"]),
                    finding_ids=by_rule.get(v["rule_id"], []),
                )
            )
    return Compliance(
        snapshot_id=snapshot_id,
        run_id=run["id"] if run else None,
        coverage=TaskCoverage.model_validate(run["coverage_json"]) if run and run["coverage_json"] else None,
        qualification=_counts([r for r in rows if r.kind in QUALIFICATION_KINDS]),
        scoring=_counts([r for r in rows if r.kind == "scoring"]),
        rows=rows,
    )


def get_compliance(conn: Connection, actor: Actor, project_id: str, snapshot_id: str | None = None) -> Compliance:
    require_project(conn, actor, project_id)
    if snapshot_id is None:
        latest = db.one(
            conn,
            """SELECT s.id FROM input_snapshots s WHERE s.project_id=:p
               AND EXISTS (SELECT 1 FROM jobs d WHERE d.snapshot_id=s.id AND d.kind='diagnosis' AND d.state='succeeded')
               ORDER BY s.as_of DESC, s.id DESC LIMIT 1""",
            {"p": project_id},
        )
        if latest is None:
            raise NotFound("review_not_ready", "还没有完成的评审")
        snapshot_id = latest["id"]
    elif db.one(conn, "SELECT 1 AS x FROM input_snapshots WHERE id=:s AND project_id=:p", {"s": snapshot_id, "p": project_id}) is None:
        raise NotFound("snapshot_not_found")
    return for_snapshot(conn, project_id, snapshot_id)
