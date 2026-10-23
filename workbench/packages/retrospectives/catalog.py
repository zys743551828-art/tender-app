"""Bounded, explicitly paged discovery. No option is chosen on the user's behalf."""

from packages.domain.runtime import clean, fetch
from packages.metrics import records
from packages.retrospectives.policy import fail


def choices(c, bid, kind, submission_id, limit, offset):
    fetch(c, "SELECT id FROM design.bids WHERE id=%s", (bid,))
    if kind not in {"submissions", "outcomes", "business_results", "runs"}:
        fail("CHOICE_KIND_INVALID", "请选择实交、官方成绩、业务结果或核查目录", 422)
    if kind != "submissions":
        if submission_id is None:
            fail("SUBMISSION_REQUIRED", "请先明确选择整包实际提交记录", 422)
        fetch(
            c,
            "SELECT id FROM design.submission_records WHERE bid_id=%s AND id=%s AND subject_kind='bid_package'",
            (bid, submission_id),
        )
    if kind == "submissions":
        rows = c.execute(
            "SELECT s.id,s.submitted_at,s.kind,b.package_id,b.revision_id,(h.submission_id=s.id) AS current FROM design.submission_records s JOIN design.bid_package_submission_bindings b ON b.submission_id=s.id AND b.bid_id=s.bid_id LEFT JOIN design.submission_heads h ON h.bid_id=s.bid_id WHERE s.bid_id=%s ORDER BY s.created_at DESC,s.id DESC LIMIT %s OFFSET %s",
            (bid, limit + 1, offset),
        ).fetchall()
        items = [
            {
                "id": r["id"],
                "label": f"{'补录' if r['kind'] == 'offline_fact' else '标准'}实交 · {r['submitted_at'].isoformat()} · 包修订 {r['revision_id']}",
                "current": bool(r["current"]),
                "package_id": r["package_id"],
                "revision_id": r["revision_id"],
            }
            for r in rows
        ]
    elif kind == "outcomes":
        rows = c.execute(
            "SELECT o.id,o.score_kind,o.value,o.maximum,d.original_name,(h.outcome_id=o.id) AS current FROM design.outcomes o JOIN design.document_versions d ON d.id=o.source_version_id LEFT JOIN design.outcome_heads h ON h.bid_id=o.bid_id AND h.submission_id=o.submission_id WHERE o.bid_id=%s AND o.submission_id=%s ORDER BY o.known_at DESC,o.id DESC LIMIT %s OFFSET %s",
            (bid, submission_id, limit + 1, offset),
        ).fetchall()
        labels = {
            "technical_total": "技术总分",
            "overall_total": "综合总分",
            "unknown": "成绩口径未知",
        }
        items = [
            {
                "id": r["id"],
                "label": f"{labels[r['score_kind']]} {r['value'] if r['value'] is not None else '未知'} / {r['maximum'] if r['maximum'] is not None else '未知'} · {r['original_name']} · {r['id']}",
                "current": bool(r["current"]),
                "package_id": None,
                "revision_id": None,
            }
            for r in rows
        ]
    elif kind == "business_results":
        head = records.result_head(c, bid, submission_id)
        rows = c.execute(
            "SELECT a.id,a.payload,a.created_at FROM design.audit_entries a WHERE a.bid_id=%s AND a.event_type=%s AND a.payload->>'submission_id'=%s ORDER BY a.created_at DESC,a.id DESC LIMIT %s OFFSET %s",
            (bid, records.RESULT, submission_id, limit + 1, offset),
        ).fetchall()
        labels = {
            "pending": "阶段待定",
            "technical_shortlisted": "技术入围",
            "not_shortlisted": "未入围",
            "rejected": "否决",
            "candidate": "中标候选",
            "awarded": "中标",
            "not_awarded": "未中标",
            "cancelled": "取消",
            "failed_tender": "流标",
        }
        items = [
            {
                "id": r["id"],
                "label": f"{labels.get(r['payload']['stage'], r['payload']['stage'])} · {r['created_at'].isoformat()} · {r['id']}",
                "current": str(r["id"]) == head["result_id"],
                "package_id": None,
                "revision_id": None,
            }
            for r in rows
        ]
    else:
        rows = c.execute(
            "SELECT r.id,r.input_manifest,r.created_at FROM design.bid_package_review_runs r JOIN design.operations o ON o.id=r.operation_id JOIN design.bid_package_review_results x ON x.run_id=r.id WHERE r.bid_id=%s AND o.state='succeeded' ORDER BY r.created_at DESC,r.id DESC LIMIT %s OFFSET %s",
            (bid, limit + 1, offset),
        ).fetchall()
        items = [
            {
                "id": r["id"],
                "label": f"已完成核查 · {r['created_at'].isoformat()} · 包修订 {r['input_manifest']['scope']['revision_id']} · {r['id']}",
                "current": None,
                "package_id": r["input_manifest"]["scope"]["package_id"],
                "revision_id": r["input_manifest"]["scope"]["revision_id"],
            }
            for r in rows
        ]
    return clean(
        {
            "bid_id": bid,
            "kind": kind,
            "submission_id": submission_id,
            "items": items[:limit],
            "next_offset": offset + limit if len(items) > limit else None,
        }
    )
