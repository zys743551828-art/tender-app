"""评分预测的读取与在线对照。

预测本身由 ``prediction`` 任务产生并追加保存；这里把它连同明细（逐条评分条款的评估）读出来。
校准有两层：预测时由登记的打分模型校准（``validation_status`` 与 ``scoring_model``，见 ``ai.predict``）；
这里的在线对照用已登记的官方成绩持续衡量预测准不准，作为监控信息。样本不足时不给误差，如实标注“样本不足”。
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor, require_project
from bidwb.schemas import Calibration, Prediction, PredictionBrief, PredictionTopic, ScoringModelRef
from bidwb.services import evidence
from bidwb.services import rules as rules_service
from bidwb.storage import ObjectStore
from bidwb.util import decimal_text

NEEDED_PAIRS = 20
TOPICS_SHOWN = 10
_PLACES = Decimal("0.01")

# 每个有效提交（未被更新的提交取代）只配一组：它最新的一条带技术分的结果，对它提交快照上的最新预测
_PAIRS_SQL = """
SELECT p.estimated_decimal AS est, p.maximum_decimal AS pmax, o.value_decimal AS actual, o.maximum_decimal AS omax
FROM submissions s
JOIN LATERAL (SELECT value_decimal, maximum_decimal FROM outcomes x
              WHERE x.submission_id=s.id AND x.project_id=s.project_id AND x.target='technical_total'
                AND x.value_decimal IS NOT NULL AND x.maximum_decimal > 0 AND x.verification_status <> 'conflict'
                AND NOT EXISTS (SELECT 1 FROM outcomes y WHERE y.supersedes=x.id)
              ORDER BY x.known_at DESC, x.id DESC LIMIT 1) o ON true
JOIN LATERAL (SELECT estimated_decimal, maximum_decimal FROM predictions
              WHERE snapshot_id=s.snapshot_id AND status='candidate' ORDER BY created_at DESC, id DESC LIMIT 1) p ON p.maximum_decimal > 0
WHERE NOT EXISTS (SELECT 1 FROM submissions t WHERE t.supersedes=s.id)
"""


def calibration(conn: Connection) -> Calibration:
    """预测与官方成绩的对照：按满分折算为百分制比较。样本达到 ``NEEDED_PAIRS`` 才给平均绝对误差与偏差。"""
    rows = db.all_(conn, _PAIRS_SQL)
    errors = [(r["est"] / r["pmax"] - r["actual"] / r["omax"]) * 100 for r in rows]
    if not errors:
        return Calibration(state="uncalibrated", pairs=0, needed_pairs=NEEDED_PAIRS, mae=None, bias=None)
    if len(errors) < NEEDED_PAIRS:
        return Calibration(state="insufficient", pairs=len(errors), needed_pairs=NEEDED_PAIRS, mae=None, bias=None)
    mae = sum((abs(e) for e in errors), Decimal(0)) / len(errors)
    bias = sum(errors, Decimal(0)) / len(errors)
    return Calibration(
        state="calibrated",
        pairs=len(errors),
        needed_pairs=NEEDED_PAIRS,
        mae=decimal_text(mae.quantize(_PLACES, ROUND_HALF_UP)),
        bias=decimal_text(bias.quantize(_PLACES, ROUND_HALF_UP)),
    )


MISSING_SHOWN = 4


def topic_text(item: dict[str, Any]) -> str:
    """失分点标题：条款、满分、所定档次与没写到的得分要点，如“施工进度计划（满分 8 分，判为“良”档；缺：关键线路说明、劳动力计划）”。"""
    parts = [f"满分 {item['max_points']} 分"]
    if item.get("grade_label"):
        parts[0] += f"，判为“{item['grade_label']}”档"
    missing = item.get("missing_points") or []
    if missing:
        more = f"等 {len(missing)} 项" if len(missing) > MISSING_SHOWN else ""
        parts.append(f"缺：{'、'.join(missing[:MISSING_SHOWN])}{more}")
    return f"{item['statement']}（{'；'.join(parts)}）"


def _scoring_model(conn: Connection, bundle_id: str | None) -> ScoringModelRef | None:
    if bundle_id is None:
        return None
    components = db.scalar(conn, "SELECT components_json FROM model_bundles WHERE id=:b", {"b": bundle_id})
    if not components:
        return None
    evaluation = components.get("evaluation") or {}
    scope = components.get("scope") or {}
    mae = Decimal(str(evaluation.get("mae_pct", 0))).quantize(_PLACES, ROUND_HALF_UP)
    return ScoringModelRef(
        model_id=components.get("model_id", ""),
        pairs=int(evaluation.get("n", 0)),
        mae=decimal_text(mae) or "0",
        scope=f"工程类型：{'、'.join(scope.get('engineering_types') or []) or '不限'}；地区：{'、'.join(scope.get('regions') or []) or '不限'}",
    )


def _topics(conn: Connection, store: ObjectStore, row: db.Row) -> list[PredictionTopic]:
    if row["artifact_key"] is None:
        return []
    detail = json.loads(store.get(row["artifact_key"]))
    items = sorted(detail.get("items", []), key=lambda i: Decimal(i["max_points"]) - Decimal(i["estimate"]), reverse=True)
    topics: list[PredictionTopic] = []
    for item in items[:TOPICS_SHOWN]:
        lost = Decimal(item["max_points"]) - Decimal(item["estimate"])
        topics.append(
            PredictionTopic(
                topic=topic_text(item),
                points_lost=decimal_text(lost.quantize(_PLACES, ROUND_HALF_UP)) or "0",
                assessment=item["assessment"],
                evidence=evidence.evidence_for_ids(conn, row["project_id"], item["evidence_ids"]),
                limitations=item["limitations"] or ("依据未确认的评分条款" if item["rule_basis"] == "unconfirmed" else ""),
            )
        )
    return topics


def _prediction(conn: Connection, store: ObjectStore, row: db.Row, calib: Calibration) -> Prediction:
    return Prediction(
        prediction_id=row["id"],
        project_id=row["project_id"],
        snapshot_id=row["snapshot_id"],
        run_id=row["run_id"],
        target=row["target"],
        status=row["status"],
        purpose=row["purpose"],
        estimated_value=decimal_text(row["estimated_decimal"]),
        low=decimal_text(row["low_decimal"]),
        high=decimal_text(row["high_decimal"]),
        maximum=decimal_text(row["maximum_decimal"]),
        technical_full_score=_full_score(conn, row["snapshot_id"]),
        validation_status=row["validation_status"],
        reason=row["reason"],
        scoring_model=_scoring_model(conn, row["bundle_id"]) if row["validation_status"] == "validated_in_scope" else None,
        topics=_topics(conn, store, row),
        created_at=row["created_at"],
        calibration=calib,
    )


def _full_score(conn: Connection, snapshot_id: str) -> str | None:
    """该轮评审所用规则包里，评标办法写明的技术标满分。"""
    rule_set = db.scalar(conn, "SELECT rule_set_id FROM input_snapshots WHERE id=:s", {"s": snapshot_id})
    term = rules_service.terms_of_package(conn, rule_set).get("technical_full_score") if rule_set else None
    return decimal_text(Decimal(term["value"])) if term else None


_SELECT = """SELECT p.*, a.object_key AS artifact_key FROM predictions p LEFT JOIN artifacts a ON a.id=p.detail_artifact_id """


def for_snapshot(conn: Connection, store: ObjectStore, project_id: str, snapshot_id: str) -> Prediction | None:
    row = db.one(
        conn,
        _SELECT + "WHERE p.project_id=:p AND p.snapshot_id=:s ORDER BY p.created_at DESC, p.id DESC LIMIT 1",
        {"p": project_id, "s": snapshot_id},
    )
    return _prediction(conn, store, row, calibration(conn)) if row else None


def brief(conn: Connection, project_id: str, snapshot_id: str) -> PredictionBrief | None:
    """项目总览用的预测摘要：不读明细产物。"""
    row = db.one(
        conn,
        "SELECT * FROM predictions WHERE project_id=:p AND snapshot_id=:s ORDER BY created_at DESC, id DESC LIMIT 1",
        {"p": project_id, "s": snapshot_id},
    )
    if row is None:
        return None
    return PredictionBrief(
        status=row["status"],
        estimated_value=decimal_text(row["estimated_decimal"]),
        low=decimal_text(row["low_decimal"]),
        high=decimal_text(row["high_decimal"]),
        maximum=decimal_text(row["maximum_decimal"]),
        technical_full_score=_full_score(conn, snapshot_id),
        validation_status=row["validation_status"],
        reason=row["reason"],
    )


def latest(conn: Connection, store: ObjectStore, actor: Actor, project_id: str, snapshot_id: str | None = None) -> Prediction | None:
    """项目最近一轮评审的预测；指定 ``snapshot_id`` 时取该轮的。"""
    require_project(conn, actor, project_id)
    if snapshot_id is None:
        row = db.one(
            conn,
            _SELECT + "WHERE p.project_id=:p ORDER BY p.created_at DESC, p.id DESC LIMIT 1",
            {"p": project_id},
        )
        return _prediction(conn, store, row, calibration(conn)) if row else None
    return for_snapshot(conn, store, project_id, snapshot_id)
