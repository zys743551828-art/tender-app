"""规则提取与问题诊断处理器。

流水线是普通的顺序 Python：每个阶段的输入输出都是显式数据，便于测试与审计；
只有出现“暂停等待人、之后原地恢复”的需求时才值得引入 LangGraph（见 ADR 偏差记录）。
处理器只读数据库、调用模型、返回结果；所有领域写入都在 ``finalize`` 里、与租约校验同一事务。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import Connection, text

from bidwb import checks, db, retrieval, term_conflicts
from bidwb.ai import grounding, prompts
from bidwb.ai.grounding import EvidenceText
from bidwb.ai.llm import IncompleteGeneration, LlmClient, Usage, call_validated
from bidwb.checks import consistency, scope
from bidwb.logs import get_logger
from bidwb.services import findings as findings_service
from bidwb.services import projects as projects_service
from bidwb.services import rules as rules_service
from bidwb.util import new_id, utcnow
from bidwb.workers.handlers import Handler, HandlerFailure, HandlerOutput, JobContext

if TYPE_CHECKING:
    from bidwb.ai.anchors import AnchorSource

log = get_logger(__name__)
RULES_BATCH = 20  # 每次送给模型的片段数
BODY_TOP_K = 5
MAX_RULES_PER_PACKAGE = 200


# 文档顺序：资料按入库先后（招标文件在补遗之前），同一资料内按解析时的块顺序
EVIDENCE_IN_ORDER_SQL = """SELECT e.id,e.physical_page,e.quote,e.file_version_id FROM evidence e
   JOIN file_versions fv ON fv.id=e.file_version_id AND fv.project_id=e.project_id
   WHERE e.project_id=:p AND e.file_version_id = ANY(:v) AND (e.kind='text' OR e.semantic_review='supported')
   ORDER BY fv.obtained_at, fv.id, e.seq, e.id"""


def _evidence_rows(conn: Connection, project_id: str, version_ids: Sequence[str]) -> list[db.Row]:
    return db.all_(conn, EVIDENCE_IN_ORDER_SQL, {"p": project_id, "v": list(version_ids)})


def _load_evidence(conn: Connection, project_id: str, version_ids: Sequence[str]) -> list[EvidenceText]:
    return [EvidenceText(r["id"], r["quote"]) for r in _evidence_rows(conn, project_id, version_ids)]


CARRIED_REASON_PREFIX = rules_service.CARRIED_REASON_PREFIX


def _previous_decisions(conn: Connection, project_id: str, package_id: str) -> dict[tuple[str, str], db.Row]:
    """上一版规则包里已有人工决定（确认/驳回/暂缓）的规则，键为（性质，规范化后的条文）；同键取先出现的。"""
    rows = db.all_(
        conn,
        """SELECT i.id AS rule_id, i.kind, i.statement, r.decision, r.reason, r.actor_id
           FROM rule_items i JOIN LATERAL (
               SELECT decision, reason, actor_id FROM reviews
               WHERE project_id=i.project_id AND object_kind='rule' AND object_id=i.id ORDER BY reviewed_at DESC, id DESC LIMIT 1
           ) r ON true
           WHERE i.package_id=:pk AND i.project_id=:p ORDER BY i.id""",
        {"pk": package_id, "p": project_id},
    )
    out: dict[tuple[str, str], db.Row] = {}
    for row in rows:
        out.setdefault((row["kind"], grounding.squash(row["statement"])), row)
    return out


def _dump(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()


def _ground_terms(
    out: prompts.RulesOutput, allowed: dict[str, EvidenceText], terms: dict[str, dict[str, Any]], dropped: list[dict[str, Any]]
) -> None:
    """投标条件（技术分满分、评标价规则）：引文必须逐字出自所引片段，每个数值必须出现在引文里；
    不落地的数值单独丢弃，其余保留；不一致的候选交给人工核实，不能按抽取顺序取值。"""
    for key, model in (("technical_full_score", prompts.FullScoreTerm), ("price_rule", prompts.PriceRuleTerm)):
        raw = getattr(out, key)
        if raw is None:
            continue
        valid, bad = prompts.validate_items(model, [raw])
        dropped.extend({**b, "term": key} for b in bad)
        if not valid:
            continue
        term = valid[0]
        if grounding.unknown_ids(term.evidence_ids, allowed) or not grounding.quote_supported(term.quote, allowed, term.evidence_ids):
            dropped.append({"reason": "quote_not_found", "term": key})
            continue
        numbers = grounding.numeric_tokens(term.quote)
        values = term.model_dump(exclude={"evidence_ids", "quote"}, exclude_none=True)
        kept = {k: v for k, v in values.items() if k == "method" or v in numbers}
        dropped.extend({"reason": "invented_number", "term": key, "field": k} for k in sorted(set(values) - set(kept)))
        if kept and (key != "price_rule" or set(kept) - {"method"}):
            term_conflicts.add_candidate(terms, key, {**kept, "evidence_ids": term.evidence_ids, "quote": term.quote})


def _write_rule_package(
    conn: Connection,
    project_id: str,
    artifact_id: str,
    version_ids: Sequence[str],
    accepted: Sequence[prompts.RuleCandidate],
    terms: dict[str, dict[str, Any]],
) -> None:
    """新规则包入库，并沿用上一版规则包里同一条款（性质＋规范化条文相同）的人工决定。"""
    revision = (db.scalar(conn, "SELECT COALESCE(MAX(revision),0) FROM rule_packages WHERE project_id=:p", {"p": project_id}) or 0) + 1
    package_id = new_id("rpk")
    db.run(
        conn,
        """INSERT INTO rule_packages(id,project_id,revision,status,artifact_id,source_versions_json,terms_json,created_at)
                    VALUES (:i,:p,:r,'candidate',:a,CAST(:s AS jsonb),CAST(:t AS jsonb),:now)""",
        {
            "i": package_id,
            "p": project_id,
            "r": revision,
            "a": artifact_id,
            "s": json.dumps(sorted(version_ids)),
            "t": json.dumps(terms, ensure_ascii=False),
            "now": utcnow(),
        },
    )
    previous = db.one(
        conn,
        "SELECT id FROM rule_packages WHERE project_id=:p AND revision<:r ORDER BY revision DESC LIMIT 1",
        {"p": project_id, "r": revision},
    )
    carry = _previous_decisions(conn, project_id, previous["id"]) if previous else {}
    now = utcnow()
    rows: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for r in accepted:
        rule_id = new_id("rul")
        old = carry.get((r.kind, grounding.squash(r.statement)))
        rows.append(
            {
                "i": rule_id,
                "p": project_id,
                "pk": package_id,
                "k": r.kind,
                "s": r.statement,
                "c": json.dumps(r.conditions, ensure_ascii=False),
                "e": json.dumps(r.exceptions, ensure_ascii=False),
                "ev": json.dumps(r.evidence_ids),
                "cf": old["rule_id"] if old else None,
                "mp": r.max_points if r.kind == "scoring" else None,
            }
        )
        if old is not None:
            reason = old["reason"]
            reviews.append(
                {
                    "i": new_id("rev"),
                    "p": project_id,
                    "o": rule_id,
                    "v": str(revision),
                    "d": old["decision"],
                    "r": reason if reason.startswith(CARRIED_REASON_PREFIX) else CARRIED_REASON_PREFIX + reason,
                    "a": old["actor_id"],
                    "now": now,
                }
            )
    conn.execute(
        text("""INSERT INTO rule_items(id,project_id,package_id,kind,statement,conditions_json,exceptions_json,evidence_ids_json,max_points,carried_from_rule_id)
                         VALUES (:i,:p,:pk,:k,:s,CAST(:c AS jsonb),CAST(:e AS jsonb),CAST(:ev AS jsonb),:mp,:cf)"""),
        rows,
    )
    if reviews:
        conn.execute(
            text("""INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
                             VALUES (:i,:p,'rule',:o,:v,:d,:r,:a,:now)"""),
            reviews,
        )


# ------------------------------------------------------------------ 规则提取
def make_rules_handler(llm: LlmClient | None) -> Handler:
    def handler(ctx: JobContext) -> HandlerOutput | HandlerFailure:
        if llm is None:
            return HandlerFailure("llm_not_configured")
        version_ids = ctx.claim.input_json.get("file_version_ids")
        if not isinstance(version_ids, list) or not version_ids:
            return HandlerFailure("invalid_job_input")
        project_id = ctx.claim.project_id
        with ctx.engine.connect() as conn:
            evidence_rows = _evidence_rows(conn, project_id, version_ids)
            chunks = [EvidenceText(row["id"], row["quote"]) for row in evidence_rows]
        if not chunks:
            return HandlerFailure("no_evidence")
        by_id = {c.evidence_id: c for c in chunks}
        usage = Usage()
        dropped: list[dict[str, Any]] = []
        accepted: list[prompts.RuleCandidate] = []
        terms: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        # 每批只读同一文件版本，使招标文件与补遗的同类条件分别抽取，再比较候选。
        by_version: dict[str, list[EvidenceText]] = {}
        for row, chunk in zip(evidence_rows, chunks, strict=True):
            by_version.setdefault(row["file_version_id"], []).append(chunk)
        batches = [group[start : start + RULES_BATCH] for group in by_version.values() for start in range(0, len(group), RULES_BATCH)]
        for batch_number, batch in enumerate(batches):
            ctx.checkpoint()
            try:
                out = call_validated(llm, prompts.RulesOutput, system=prompts.RULES_SYSTEM, user=prompts.rules_user(batch), usage=usage)
            except IncompleteGeneration:
                dropped.append({"reason": "invalid_output", "batch_number": batch_number})
                continue
            allowed = {c.evidence_id: c for c in batch}
            _ground_terms(out, allowed, terms, dropped)
            candidates, bad = prompts.validate_items(prompts.RuleCandidate, out.rules)
            dropped.extend(bad)
            for rule in candidates:
                key = grounding.squash(rule.statement)
                if grounding.unknown_ids(rule.evidence_ids, allowed):
                    dropped.append({"reason": "unknown_evidence", "statement": rule.statement})
                elif not grounding.quote_supported(rule.quote, by_id, rule.evidence_ids):
                    dropped.append({"reason": "quote_not_found", "statement": rule.statement})
                elif key in seen:
                    dropped.append({"reason": "duplicate", "statement": rule.statement})
                else:
                    seen.add(key)
                    accepted.append(rule)
        accepted = accepted[:MAX_RULES_PER_PACKAGE]
        if not accepted:  # 不留下空的候选规则包：没有任何可确认的规则，后续流程无从继续
            return HandlerFailure(
                "no_rules_extracted",
                f"未能从招标文件中提取出任何可核对的规则（模型候选被丢弃 {len(dropped)} 条），请检查招标文件解析结果后重试",
            )
        artifact = _dump(
            {
                "prompt_version": prompts.PROMPT_VERSION,
                "extraction_policy": "per-file-terms-conflict-1",
                "model": llm.model,
                "usage": usage.__dict__,
                "rules": [r.model_dump() for r in accepted],
                "terms": terms,
                "dropped": dropped,
            }
        )

        def finalize(conn: Connection, artifact_id: str) -> None:
            # 提取期间又上传了招标文件或补遗：这批规则基于过时的资料，不作为规则包入库（产物仍保留可审计），
            # 流水线会针对最新资料重新提取。
            if rules_service.current_tender_version_ids(conn, project_id) == sorted(version_ids):
                _write_rule_package(conn, project_id, artifact_id, version_ids, accepted, terms)

        return HandlerOutput(artifact, "application/json", "rules-v1", finalize)

    return handler


# ------------------------------------------------------------------ 诊断
def _category(kind: str) -> tuple[str, str]:
    """规则性质 → （问题分类, 影响）：否决项与强制项关系到能否入围，其余只影响得分。"""
    if kind == "disqualification":
        return "disqualification", "qualification"
    if kind == "mandatory":
        return "response", "qualification"
    return "improvement", "technical"


def _passages(conn: Connection, project_id: str, version_ids: Sequence[str]) -> list[checks.Passage]:
    return [checks.Passage(r["id"], r["physical_page"], r["quote"]) for r in _evidence_rows(conn, project_id, version_ids)]


def _load_diagnosis_inputs(conn: Connection, project_id: str, snapshot_id: str) -> tuple[Any, ...] | None:
    snap = db.one(
        conn,
        "SELECT body_version_id,rule_set_id,fact_set_id FROM input_snapshots WHERE id=:s AND project_id=:p",
        {"s": snapshot_id, "p": project_id},
    )
    if snap is None:
        return None
    # 人工确认的规则与尚未人工看过的规则都参与核对（后者标为“未确认依据”）；驳回、暂缓的不用
    rules = rules_service.effective_rules(conn, project_id, snap["rule_set_id"])
    facts = (
        db.all_(
            conn,
            "SELECT id,name,statement,value_decimal,unit FROM fact_items WHERE fact_set_id=:f AND project_id=:p AND confirmation='confirmed' ORDER BY id",
            {"f": snap["fact_set_id"], "p": project_id},
        )
        if snap["fact_set_id"]
        else []
    )
    body = _load_evidence(conn, project_id, [snap["body_version_id"]])
    body_passages = _passages(conn, project_id, [snap["body_version_id"]])
    tender_versions = db.all_(
        conn,
        """SELECT sf.file_version_id AS id FROM snapshot_files sf
           JOIN file_versions fv ON fv.id=sf.file_version_id AND fv.project_id=sf.project_id
           JOIN files f ON f.id=fv.file_id AND f.project_id=fv.project_id
           WHERE sf.snapshot_id=:s AND sf.project_id=:p AND f.role IN ('tender','supplement')""",
        {"s": snapshot_id, "p": project_id},
    )
    tender_passages = _passages(conn, project_id, [v["id"] for v in tender_versions])
    rule_ev_ids = sorted({e for r in rules for e in r["evidence_ids_json"]})
    rule_ev = {e.evidence_id: e for e in _load_evidence_by_ids(conn, project_id, rule_ev_ids)}
    settings = projects_service.settings_of(conn, project_id)
    return rules, facts, body, body_passages, tender_passages, rule_ev, settings


def make_diagnosis_handler(llm: LlmClient | None) -> Handler:
    def handler(ctx: JobContext) -> HandlerOutput | HandlerFailure:
        if llm is None:
            return HandlerFailure("llm_not_configured")
        snapshot_id, project_id = ctx.claim.snapshot_id, ctx.claim.project_id
        if snapshot_id is None:
            return HandlerFailure("invalid_job_input")
        with ctx.engine.connect() as conn:
            loaded = _load_diagnosis_inputs(conn, project_id, snapshot_id)
        if loaded is None:
            return HandlerFailure("snapshot_not_found")
        rules, facts, body, body_passages, tender_passages, rule_ev, settings = loaded
        if not body:
            return HandlerFailure("body_has_no_evidence")
        if not rules:
            return HandlerFailure("no_rules", "快照引用的规则包里没有可用的规则，无法诊断")
        body_by_id = {b.evidence_id: b for b in body}
        usage = Usage()
        dropped: list[dict[str, Any]] = []
        accepted: list[tuple[db.Row, prompts.FindingCandidate]] = []
        verdicts: list[dict[str, Any]] = []
        failed_rules: list[str] = []
        for rule in rules:
            ctx.checkpoint()
            rule_evidence = [rule_ev[e] for e in rule["evidence_ids_json"] if e in rule_ev]
            ranked = retrieval.rank(rule["statement"], [b.quote for b in body], BODY_TOP_K)
            retrieved = [body[s.index] for s in ranked]
            try:
                out = call_validated(
                    llm,
                    prompts.DiagnosisOutput,
                    system=prompts.DIAGNOSIS_SYSTEM,
                    usage=usage,
                    user=prompts.diagnosis_user(
                        rule["statement"],
                        rule_evidence,
                        retrieved,
                        [(f["id"], _fact_text(f)) for f in facts],
                        kind=rule["kind"],
                        confirmed=rule["basis"] == "confirmed",
                    ),
                )
            except IncompleteGeneration:
                dropped.append({"rule_id": rule["id"], "reason": "invalid_output"})
                failed_rules.append(rule["id"])
                verdicts.append(
                    {
                        "rule_id": rule["id"],
                        "verdict": "failed",
                        "basis": rule["basis"],
                        "evidence_ids": [],
                        "note": "模型输出不可用，未能完成检查",
                    }
                )
                continue
            offered_body = {b.evidence_id: b for b in retrieved}
            offered_rule = {e.evidence_id: e for e in rule_evidence}
            candidates, bad = prompts.validate_items(prompts.FindingCandidate, out.findings)
            dropped.extend({**d, "rule_id": rule["id"]} for d in bad)
            kept = 0
            for cand in candidates:
                reason = _reject_reason(cand, offered_body, offered_rule, body_by_id)
                if reason is None and cand.nature == "needs_confirmation" and _facts_covered(cand.required_facts, facts):
                    reason = "facts_already_confirmed"  # 所需事实已在快照的已确认事实里，不再要求人工确认
                if reason:
                    dropped.append({"rule_id": rule["id"], "reason": reason, "statement": cand.statement})
                else:
                    accepted.append((rule, cand))
                    kept += 1
            verdicts.append(_verdict(rule, out, offered_body, kept))
        # 确定性检测按项目开关执行；关闭的检测不产生问题，产物里记下本次实际执行了哪些
        detected = [
            *(consistency.check(body_passages) if settings.consistency_check else []),
            *(scope.residual_scope(body_passages, tender_passages) if settings.scope_check else []),
        ]
        coverage = diagnosis_coverage(len(rules), failed_rules, dropped)
        artifact = _dump(
            {
                "prompt_version": prompts.PROMPT_VERSION,
                "model": llm.model,
                "usage": usage.__dict__,
                "coverage": {**coverage, "failed_rule_ids": failed_rules},
                "verdicts": verdicts,
                "findings": [{"rule_id": r["id"], **c.model_dump()} for r, c in accepted],
                "checks": {"consistency": settings.consistency_check, "scope": settings.scope_check},
                "detected": [d.__dict__ for d in detected],
                "dropped": dropped,
            }
        )

        def finalize(conn: Connection, _artifact_id: str) -> None:
            _write_diagnosis(conn, project_id, snapshot_id, ctx.claim.job_id, verdicts, accepted, detected)

        return HandlerOutput(artifact, "application/json", "diagnosis-v1", finalize, coverage, _coverage_message(coverage))

    return handler


def _write_diagnosis(
    conn: Connection,
    project_id: str,
    snapshot_id: str,
    job_id: str,
    verdicts: Sequence[dict[str, Any]],
    accepted: Sequence[tuple[db.Row, prompts.FindingCandidate]],
    detected: Sequence[checks.Candidate],
) -> None:
    now = utcnow()
    for v in verdicts:
        db.run(
            conn,
            """INSERT INTO rule_verdicts(id,project_id,snapshot_id,run_id,rule_id,verdict,rule_basis,body_evidence_ids_json,note,created_at)
               VALUES (:i,:p,:s,:r,:rule,:v,:b,CAST(:ev AS jsonb),:n,:now) ON CONFLICT (run_id,rule_id) DO NOTHING""",
            {
                "i": new_id("rvd"),
                "p": project_id,
                "s": snapshot_id,
                "r": job_id,
                "rule": v["rule_id"],
                "v": v["verdict"],
                "b": v["basis"],
                "ev": json.dumps(v["evidence_ids"]),
                "n": v["note"],
                "now": now,
            },
        )
    for rule, cand in accepted:
        category, impact = _category(rule["kind"])
        evidence_ids = cand.body_evidence_ids + cand.rule_evidence_ids
        _insert_finding(
            conn,
            {
                "p": project_id,
                "s": snapshot_id,
                "r": job_id,
                "rule": rule["id"],
                "src": "rule",
                "cat": category if cand.nature != "suggestion" else "improvement",
                "basis": rule["basis"],
                "dk": dedupe_key(rule["id"], cand.nature, evidence_ids),
                "n": cand.nature,
                "imp": impact if cand.nature != "suggestion" else "technical",
                "sev": cand.severity,
                "st": cand.statement,
                "ev": json.dumps(evidence_ids),
                "rf": json.dumps(cand.required_facts, ensure_ascii=False),
                "now": now,
            },
        )
    for d in detected:
        _insert_finding(
            conn,
            {
                "p": project_id,
                "s": snapshot_id,
                "r": job_id,
                "rule": None,
                "src": d.category,
                "cat": d.category,
                "basis": None,
                "dk": f"{d.category}|{d.key}",
                "n": d.nature,
                "imp": "technical",
                "sev": d.severity,
                "st": d.statement,
                "ev": json.dumps(list(d.evidence_ids)),
                "rf": json.dumps(list(d.required_facts), ensure_ascii=False),
                "now": now,
            },
        )
    findings_service.reconcile_project_state(conn, project_id)


def _verdict(rule: db.Row, out: prompts.DiagnosisOutput, offered_body: dict[str, EvidenceText], kept: int) -> dict[str, Any]:
    """规则判定。“满足”必须引用本次提供给模型的正文片段，否则降为无法判断；模型说满足却给出了问题，也按无法判断处理。"""
    evidence = [e for e in out.verdict_evidence_ids if e in offered_body]
    verdict = out.verdict
    note = out.verdict_note
    if verdict == "satisfied" and (not evidence or kept):
        verdict, note = "unclear", note or "模型未给出可核对的正文依据"
    if verdict == "violated" and not kept:
        verdict = "unclear"  # 判违反但没有一条通过落地校验的问题：不下违反结论，留给人看
        note = note or "模型判定违反，但未给出可核对的引文"
    return {
        "rule_id": rule["id"],
        "verdict": verdict,
        "basis": rule["basis"],
        "evidence_ids": evidence if verdict == "satisfied" else [],
        "note": note,
    }


def _insert_finding(conn: Connection, params: dict[str, Any]) -> None:
    fid = new_id("fnd")
    inserted = db.one(
        conn,
        """INSERT INTO findings(id,project_id,snapshot_id,run_id,rule_id,source,category,rule_basis,dedupe_key,nature,impact,severity,statement,
                                evidence_ids_json,required_facts_json,created_at)
                    VALUES (:i,:p,:s,:r,:rule,:src,:cat,:basis,:dk,:n,:imp,:sev,:st,CAST(:ev AS jsonb),CAST(:rf AS jsonb),:now)
                    ON CONFLICT (snapshot_id,dedupe_key) DO NOTHING RETURNING id""",
        {"i": fid, **params},
    )
    if inserted is not None:  # 同一快照里已有相同去重键的问题（重跑诊断）：保留原问题及其人工复核，不再新建
        db.run(conn, "INSERT INTO finding_states(finding_id,state,revision) VALUES (:f,'candidate',1)", {"f": fid})


def diagnosis_coverage(total: int, failed_rules: Sequence[str], dropped: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """诊断覆盖度。任何一条规则的模型调用整体失败（输出不可用）即 partial；一条规则都没检查成功即 empty。

    ``candidates_dropped`` 只数“候选被证据落地校验丢弃”的条数（不含整条规则失败），那是模型幻觉被拦截，不影响完整性。
    """
    checked = total - len(failed_rules)
    status = "empty" if checked <= 0 else "partial" if failed_rules else "complete"
    return {
        "status": status,
        "rules_total": total,
        "rules_checked": checked,
        "rules_failed": len(failed_rules),
        "candidates_dropped": len(dropped) - len(failed_rules),
    }


def _coverage_message(coverage: dict[str, Any]) -> str:
    if coverage["status"] == "complete":
        return ""
    if coverage["status"] == "empty":
        return "没有任何规则完成检查（模型输出均不可用），本次诊断不能作为结论，请重新诊断"
    return f"{coverage['rules_total']} 条规则中有 {coverage['rules_failed']} 条未能完成检查（模型输出不可用），诊断结论不完整，请重新诊断"


def dedupe_key(rule_id: str, nature: str, evidence_ids: Sequence[str]) -> str:
    """问题去重键：同一快照里，同一规则、同一性质、同一组证据视为同一个问题（与 statement 的措辞无关）。"""
    return f"{rule_id}|{nature}|{','.join(sorted(set(evidence_ids)))}"


def _fact_text(fact: Any) -> str:
    value = f" {fact['value_decimal']}{fact['unit'] or ''}" if fact["value_decimal"] is not None else ""
    return f"{fact['name']}：{fact['statement']}{value}"


def _facts_covered(required: Sequence[str], facts: Sequence[Any]) -> bool:
    """每一项所需事实都被某条已确认事实覆盖才算覆盖：事实 ID 相同，或所需描述与事实的名称/陈述互相包含（忽略空白，至少 2 个字）。"""
    if not required or not facts:
        return False
    for need in required:
        needle = grounding.squash(need)
        if len(needle) < 2:
            return False
        if not any(
            need.strip() == f["id"]
            or grounding.squash(f["name"]) in needle
            or needle in grounding.squash(f["name"])
            or needle in grounding.squash(f["statement"])
            for f in facts
            if len(grounding.squash(f["name"])) >= 2
        ):
            return False
    return True


def _load_evidence_by_ids(conn: Connection, project_id: str, ids: list[str]) -> list[EvidenceText]:
    if not ids:
        return []
    rows = db.all_(
        conn,
        "SELECT id,quote FROM evidence WHERE project_id=:p AND id = ANY(:i) AND (kind='text' OR semantic_review='supported')",
        {"p": project_id, "i": ids},
    )
    return [EvidenceText(r["id"], r["quote"]) for r in rows]


def _reject_reason(
    cand: prompts.FindingCandidate,
    offered_body: dict[str, EvidenceText],
    offered_rule: dict[str, EvidenceText],
    all_body: dict[str, EvidenceText],
) -> str | None:
    """候选只能引用本次提供过的证据；冲突类必须同时有正文与规则两侧的逐字引文。"""
    if grounding.unknown_ids(cand.rule_evidence_ids, offered_rule) or grounding.unknown_ids(cand.body_evidence_ids, offered_body):
        return "unknown_evidence"
    if not grounding.quote_supported(cand.rule_quote, offered_rule, cand.rule_evidence_ids):
        return "rule_quote_not_found"
    if cand.nature == "fact_conflict":
        if not cand.body_evidence_ids or not cand.body_quote:
            return "conflict_without_body_evidence"
        if not grounding.quote_supported(cand.body_quote, all_body, cand.body_evidence_ids):
            return "body_quote_not_found"
    if cand.nature == "needs_confirmation" and not cand.required_facts:
        return "confirmation_without_required_facts"
    return None


# ------------------------------------------------------------------ 改稿建议
EDITS_PER_FINDING_CONTEXT = 3


def make_revision_handler(llm: LlmClient | None) -> Handler:
    def handler(ctx: JobContext) -> HandlerOutput | HandlerFailure:
        if llm is None:
            return HandlerFailure("llm_not_configured")
        spec = ctx.claim.input_json
        project_id = ctx.claim.project_id
        try:
            base_version_id, finding_ids = str(spec["base_version_id"]), list(spec["finding_ids"])
            fact_ids, scope = list(spec["allowed_fact_ids"]), str(spec["scope"])
        except (KeyError, TypeError):
            return HandlerFailure("invalid_job_input")
        with ctx.engine.connect() as conn:
            findings = db.all_(
                conn,
                "SELECT id,statement,required_facts_json FROM findings WHERE project_id=:p AND id = ANY(:i) ORDER BY id",
                {"p": project_id, "i": finding_ids},
            )
            body = _load_evidence(conn, project_id, [base_version_id])
            facts = db.all_(
                conn,
                "SELECT id,statement,value_decimal,unit FROM fact_items WHERE project_id=:p AND confirmation='confirmed' AND id = ANY(:i) ORDER BY id",
                {"p": project_id, "i": fact_ids},
            )
        if not body:
            return HandlerFailure("body_has_no_evidence")
        fact_text = {f["id"]: f"{f['statement']} {f['value_decimal'] or ''}{f['unit'] or ''}".strip() for f in facts}
        usage = Usage()
        dropped: list[dict[str, Any]] = []
        accepted: list[prompts.Edit] = []
        for finding in findings:
            ctx.checkpoint()
            ranked = retrieval.rank(f"{scope} {finding['statement']}", [b.quote for b in body], EDITS_PER_FINDING_CONTEXT)
            offered = {body[s.index].evidence_id: body[s.index] for s in ranked}
            facts_block = "\n".join(f"- [{fid}] {t}" for fid, t in fact_text.items()) or "（无）"
            user = (
                f"待解决的问题 [{finding['id']}]：{finding['statement']}\n修改范围：{scope}\nallowed_facts：\n{facts_block}\n\n"
                f"正文片段：\n{prompts.render_evidence(list(offered.values()))}"
            )
            try:
                out = call_validated(llm, prompts.RevisionOutput, system=prompts.REVISION_SYSTEM, user=user, usage=usage)
            except IncompleteGeneration:
                dropped.append({"finding_id": finding["id"], "reason": "invalid_output"})
                continue
            edits, bad = prompts.validate_items(prompts.Edit, out.edits)
            dropped.extend({**d, "finding_id": finding["id"]} for d in bad)
            for edit in edits:
                reason = _edit_reject_reason(edit, finding["id"], offered, fact_text, finding["statement"])
                if reason:
                    dropped.append({"finding_id": finding["id"], "reason": reason, "original": edit.original[:80]})
                else:
                    accepted.append(edit)
        artifact = _dump(
            {
                "prompt_version": prompts.PROMPT_VERSION,
                "model": llm.model,
                "usage": usage.__dict__,
                "base_version_id": base_version_id,
                "edits": [e.model_dump() for e in accepted],
                "dropped": dropped,
            }
        )

        def finalize(conn: Connection, artifact_id: str) -> None:
            db.run(
                conn,
                """INSERT INTO revisions(id,project_id,base_version_id,target_version_id,finding_ids_json,allowed_fact_ids_json,diff_artifact_id,created_at)
                            VALUES (:i,:p,:b,NULL,CAST(:f AS jsonb),CAST(:a AS jsonb),:art,:now)""",
                {
                    "i": new_id("rvn"),
                    "p": project_id,
                    "b": base_version_id,
                    "f": json.dumps(sorted(finding_ids)),
                    "a": json.dumps(sorted(fact_ids)),
                    "art": artifact_id,
                    "now": utcnow(),
                },
            )

        return HandlerOutput(artifact, "application/json", "revision-v1", finalize)

    return handler


def _edit_reject_reason(
    edit: prompts.Edit, finding_id: str, offered: dict[str, EvidenceText], fact_text: dict[str, str], finding_statement: str
) -> str | None:
    if edit.finding_id != finding_id:
        return "finding_not_requested"
    source = offered.get(edit.evidence_id)
    if source is None:
        return "unknown_evidence"
    if grounding.squash(edit.original) not in grounding.squash(source.quote):
        return "original_not_verbatim"
    if any(f not in fact_text for f in edit.facts_used):
        return "fact_not_allowed"
    allowed_text = [source.quote, *(fact_text[f] for f in edit.facts_used)]
    if grounding.invented_numbers(edit.replacement, *allowed_text):
        return "invented_number"
    return None


def build_handlers(llm: LlmClient | None, *, anchor_source: AnchorSource | None = None) -> dict[str, Handler]:
    """worker 使用的全部处理器；未实现的任务种类由运行器以 ``kind_not_implemented`` 明确失败。

    ``anchor_source`` 只在批量预测时给出（直接读锚点包文件并排除同模板组的锚点）；产品里用路由生效的锚点包。
    """
    from bidwb.ai.predict import make_prediction_handler  # noqa: PLC0415  预测处理器复用本模块的取数函数
    from bidwb.workers.handlers import default_handlers  # noqa: PLC0415  延迟导入，避免与 workers 包循环依赖

    return {
        **default_handlers(),
        "rules": make_rules_handler(llm),
        "diagnosis": make_diagnosis_handler(llm),
        "revision": make_revision_handler(llm),
        "prediction": make_prediction_handler(llm, anchor_source),
    }
