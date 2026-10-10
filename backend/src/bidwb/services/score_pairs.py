"""评分配对集导出：产品里已提交且登记了官方技术分的投标，写成研究侧的交接格式。

* 格式 A（``score-pairs/1``，``评分配对集.json``）：每个有效提交（未被更新的提交取代）一份样本，标签取该提交最新一条、
  未被取代且不冲突的技术分结果；招标文件与补遗取该轮评审冻结的版本（按入库先后），正文取提交登记的版本。
  文件按内容导出到 ``files/<sha256>.pdf``，样本里的路径相对于 ``files``。同一正文出现在多份提交里时，后出现的标为
  ``duplicate_body``（不是独立样本）。模板组暂取项目 ID（产品里没有招标文件模板的信息）。
* 格式 B（``system-prediction/1``，``predictions/<sample_id>.json``）：该轮评审的预测与明细产物，键与
  ``tools/batch/predict_dataset.py`` 的输出一致（逐项明细、特征、规则与响应矩阵计数、正文页数与字数）。
  提交的正文与该轮评审所用正文不同时，预测不是针对被打分的那份正文，格式 B 标为失败并写明原因。

数据量增长后，这就是打分模型与锚点包的训练数据来源。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from bidwb import db
from bidwb.services import compliance
from bidwb.services import rules as rules_service
from bidwb.storage import ObjectStore
from bidwb.util import decimal_text

SCHEMA_A = "score-pairs/1"
SCHEMA_B = "system-prediction/1"
ITEM_KEYS = ("statement", "max_points", "estimate", "low", "high", "evidence_count", "rule_basis", "failed")
FINDING_CATEGORIES = ("disqualification", "response", "consistency", "scope", "improvement")

_PAIRS_SQL = """
SELECT s.id AS submission_id, s.project_id, s.snapshot_id, s.body_version_id, s.submitted_at,
       p.title, p.tender_number, p.lot, p.region, p.engineering_type,
       o.value_decimal, o.maximum_decimal, o.verification_status
FROM submissions s JOIN projects p ON p.id=s.project_id
JOIN LATERAL (SELECT value_decimal, maximum_decimal, verification_status FROM outcomes x
              WHERE x.submission_id=s.id AND x.project_id=s.project_id AND x.target='technical_total'
                AND x.value_decimal IS NOT NULL AND x.maximum_decimal > 0 AND x.verification_status <> 'conflict'
                AND NOT EXISTS (SELECT 1 FROM outcomes y WHERE y.supersedes=x.id)
              ORDER BY x.known_at DESC, x.id DESC LIMIT 1) o ON true
WHERE NOT EXISTS (SELECT 1 FROM submissions t WHERE t.supersedes=s.id)
ORDER BY s.submitted_at, s.id
"""

_VERSION_SQL = """SELECT fv.id, f.role, a.sha256, a.object_key, ps.page_count, ps.coverage, pa.object_key AS parse_key
FROM file_versions fv JOIN files f ON f.id=fv.file_id JOIN artifacts a ON a.id=fv.artifact_id
LEFT JOIN LATERAL (SELECT page_count, coverage, artifact_id FROM parses WHERE file_version_id=fv.id ORDER BY created_at DESC, id DESC LIMIT 1) ps ON true
LEFT JOIN artifacts pa ON pa.id=ps.artifact_id """


def jsonable(value: Any) -> Any:
    """十进制数写成字符串（分数、分值），浮点数（特征、比例）保持 JSON 数字。"""
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value


def format_b_items(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """预测明细产物的逐项结果原样透传（明细里的分数本就是十进制字符串），再补齐格式 B 约定的键。"""
    failed_ids = set((detail.get("coverage") or {}).get("failed_rule_ids") or [])
    out: list[dict[str, Any]] = []
    for raw in detail.get("items") or []:
        item = jsonable(dict(raw))
        if "evidence_count" not in item:
            ids = item.get("evidence_ids")
            item["evidence_count"] = len(ids) if isinstance(ids, list) else None
        if "failed" not in item:
            item["failed"] = item.get("rule_id") in failed_ids if "rule_id" in item else None
        for key in ITEM_KEYS:
            item.setdefault(key, None)
        out.append(item)
    return out


def _export_file(store: ObjectStore, files_dir: Path, version: db.Row) -> str:
    name = f"{version['sha256']}.pdf"
    target = files_dir / name
    if not target.exists():
        target.write_bytes(store.get(version["object_key"]))
    return name


def _body_stats(store: ObjectStore, version: db.Row) -> dict[str, Any]:
    chars = None
    if version["parse_key"]:
        chars = sum(json.loads(store.get(version["parse_key"])).get("page_text_chars") or [])
    return {"pages": version["page_count"], "chars": chars}


def _format_b(conn: Connection, store: ObjectStore, pair: db.Row, sample_id: str, tender: list[db.Row], body: db.Row) -> dict[str, Any]:
    snapshot = db.one(conn, "SELECT body_version_id, rule_set_id FROM input_snapshots WHERE id=:s", {"s": pair["snapshot_id"]})
    assert snapshot is not None
    record: dict[str, Any] = {
        "schema": SCHEMA_B,
        "sample_id": sample_id,
        "status": "failed",
        "error": None,
        "fingerprint": None,
        "model": None,
        "prompt_version": None,
        "code_sha256": None,
        "started_at": None,
        "finished_at": None,
        "inputs": {"tender_sha256": [v["sha256"] for v in tender], "body_sha256": body["sha256"]},
        "technical_full_score": None,
        "prediction": None,
        "items": [],
        "artifact_extra": None,
        "rules": None,
        "compliance": None,
        "findings": None,
        "body": _body_stats(store, body),
        "usage": None,
    }
    rules = rules_service.effective_rules(conn, pair["project_id"], snapshot["rule_set_id"])
    kinds = [r["kind"] for r in rules]
    record["rules"] = {
        "disqualification": kinds.count("disqualification"),
        "mandatory": kinds.count("mandatory"),
        "scoring": kinds.count("scoring"),
        "with_points": sum(1 for r in rules if r["kind"] == "scoring" and r["max_points"] is not None),
        "total": len(rules),
    }
    term = rules_service.terms_of_package(conn, snapshot["rule_set_id"]).get("technical_full_score")
    record["technical_full_score"] = decimal_text(Decimal(term["value"])) if term else None
    matrix = compliance.for_snapshot(conn, pair["project_id"], pair["snapshot_id"])
    q = matrix.qualification
    record["compliance"] = {
        "qualification_total": q.total,
        "satisfied": q.satisfied,
        "violated": q.violated,
        "unclear": q.unclear,
        "failed": q.failed,
        "coverage": matrix.coverage.status if matrix.coverage else None,
        "scoring": matrix.scoring.model_dump(),
    }
    counts = {
        r["category"]: r["n"]
        for r in db.all_(
            conn,
            "SELECT category, count(*) AS n FROM findings WHERE project_id=:p AND snapshot_id=:s GROUP BY category",
            {"p": pair["project_id"], "s": pair["snapshot_id"]},
        )
    }
    record["findings"] = {c: counts.get(c, 0) for c in FINDING_CATEGORIES}
    prediction = db.one(
        conn,
        """SELECT p.*, a.object_key AS artifact_key FROM predictions p LEFT JOIN artifacts a ON a.id=p.detail_artifact_id
           WHERE p.project_id=:p AND p.snapshot_id=:s ORDER BY p.created_at DESC, p.id DESC LIMIT 1""",
        {"p": pair["project_id"], "s": pair["snapshot_id"]},
    )
    if prediction is None:
        record["error"] = "prediction_missing: 该轮评审没有评分预测"
        return record
    record["prediction"] = {
        "status": prediction["status"],
        "estimate": decimal_text(prediction["estimated_decimal"]),
        "low": decimal_text(prediction["low_decimal"]),
        "high": decimal_text(prediction["high_decimal"]),
        "maximum": decimal_text(prediction["maximum_decimal"]),
    }
    record["started_at"] = record["finished_at"] = prediction["created_at"].isoformat()
    if prediction["artifact_key"]:
        detail = json.loads(store.get(prediction["artifact_key"]))
        record["model"], record["prompt_version"] = detail.get("model"), detail.get("prompt_version")
        record["usage"] = detail.get("usage")
        record["items"] = format_b_items(detail)
        record["artifact_extra"] = jsonable({k: v for k, v in detail.items() if k not in {"items", "usage"}})
    if snapshot["body_version_id"] != pair["body_version_id"]:
        record["error"] = "body_mismatch: 提交的正文与该轮评审所用的正文不同，预测不是针对被打分的那份正文"
    else:
        record["status"] = "succeeded"
    return record


def export(conn: Connection, store: ObjectStore, out: Path) -> dict[str, int]:
    """写出 ``评分配对集.json``、``files/``、``predictions/``，返回计数。"""
    files_dir, predictions_dir = out / "files", out / "predictions"
    files_dir.mkdir(parents=True, exist_ok=True)
    predictions_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    seen_bodies: set[str] = set()
    failed = 0
    for pair in db.all_(conn, _PAIRS_SQL):
        tender = db.all_(
            conn,
            _VERSION_SQL
            + """JOIN snapshot_files sf ON sf.file_version_id=fv.id AND sf.project_id=fv.project_id
                 WHERE sf.snapshot_id=:s AND f.role IN ('tender','supplement') ORDER BY fv.obtained_at, fv.id""",
            {"s": pair["snapshot_id"]},
        )
        body = db.one(conn, _VERSION_SQL + "WHERE fv.id=:v", {"v": pair["body_version_id"]})
        assert body is not None
        sample_id = pair["submission_id"]
        duplicate = body["sha256"] in seen_bodies
        seen_bodies.add(body["sha256"])
        samples.append(
            {
                "sample_id": sample_id,
                "project_key": f"{pair['tender_number'] or pair['project_id']}|{pair['lot'] or ''}",
                "template_group": pair["project_id"],
                "region": pair["region"],
                "engineering_type": pair["engineering_type"],
                "scoring_scheme": None,
                "bidder": None,
                "own_company": True,
                "submitted_at": pair["submitted_at"].date().isoformat(),
                "tender_files": [
                    {
                        "file_id": v["id"],
                        "path": _export_file(store, files_dir, v),
                        "sha256": v["sha256"],
                        "pages": v["page_count"],
                        "role": "tender" if v["role"] == "tender" else "addendum",
                    }
                    for v in tender
                ],
                "body_file": {
                    "file_id": body["id"],
                    "path": _export_file(store, files_dir, body),
                    "sha256": body["sha256"],
                    "pages": body["page_count"],
                    "text_layer": body["coverage"] in ("complete", "partial"),
                },
                "label": {
                    "target": "technical_total",
                    "value": float(pair["value_decimal"]),
                    "maximum": float(pair["maximum_decimal"]),
                    "verification_status": pair["verification_status"],
                },
                "eligible": not duplicate,
                "exclusion": "duplicate_body" if duplicate else None,
            }
        )
        record = _format_b(conn, store, pair, sample_id, tender, body)
        failed += record["status"] != "succeeded"
        (predictions_dir / f"{sample_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dataset = {"schema": SCHEMA_A, "datasets_root": "files", "samples": samples}
    (out / "评分配对集.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"samples": len(samples), "duplicates": sum(1 for s in samples if s["exclusion"]), "predictions_failed": failed}
