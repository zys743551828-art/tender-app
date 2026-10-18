"""评分预测处理器：大模型照评委的做法逐项判断评分条款，再由用官方成绩训练出的打分模型折算成技术分。

一次预测的步骤：

1. **条款对应章节**：目录分批映射，父章包含全部子节；无法映射时使用整份已解析正文。
2. **组织上下文**：完整保留相关章节；超长按证据顺序分节读取并保留逐块清单，再综合原文引用做逐项判断。
   读取失败或综合输入超限时该次判断失败，不静默截断。文字以外的表格结构、图页仍属于解析缺口。
3. **逐项判断**：每条款独立判断 ``prediction_repeats`` 次（第 1 次温度 0，其余 ``REPEAT_TEMPERATURE``）：先定档、再档内给分，
   逐条判断得分要点，评估正文针对性。要点判为写到（covered／partial）却没有引用所给正文的，落地校验时降为没写（missing）。
   全部判断都不可用的条款按失败处理：估计取满分一半，区间 0 到满分。
4. **汇总**：估计取各次得分的均值，区间取各次得分与所定档次区间的并集；比较式锚定（``ai.anchors``，有生效的锚点包时）；
   特征（``ai.features``，定义 ``pf-1``）。
5. **打分模型**（``services.scoring_models``）：业务环境有生效且适用的模型时，预测取校准后的分数与约 80% 区间、满分取招标文件
   写明的技术标满分；否则如实给出未校准的逐项评估合计。影子环境的模型结果只写进明细供对照。
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Connection

from bidwb import checks, db
from bidwb.ai import anchors, features, prompts
from bidwb.ai.anchors import AnchorSource
from bidwb.ai.grounding import EvidenceText, quote_supported
from bidwb.ai.handlers import _evidence_rows, _load_evidence_by_ids, diagnosis_coverage
from bidwb.ai.llm import IncompleteGeneration, LlmClient, Usage, call_validated
from bidwb.ai.sections import Section, build_sections
from bidwb.errors import Conflict, Unprocessable
from bidwb.services import anchor_packs, model_registry, scoring_models
from bidwb.services import rules as rules_service
from bidwb.services.model_registry import TARGET_SCORING
from bidwb.services.rules import QUALIFICATION_KINDS
from bidwb.util import decimal_text, new_id, utcnow
from bidwb.workers.handlers import Handler, HandlerFailure, HandlerOutput, JobContext

PART_CHARS = 24000
MAX_READING_PARTS = 128
SYNTHESIS_CHARS = 60000
MAPPING_BATCH = 60
PREDICTION_METHOD = "complete-chapters-1"
REPEAT_TEMPERATURE = 0.7
MAX_ITEM_EVIDENCE = 5
_PLACES = Decimal("0.01")
_CALIBRATED_PLACES = Decimal("0.1")
_STATUS_VALUE = {"covered": 1.0, "partial": 0.5, "missing": 0.0}
UNCALIBRATED_REASON = "基于招标文件评分条款与正文的逐项评估，尚未用官方成绩校准；只用于排出可能的失分点，不是对结果的承诺。"


def _q(value: Decimal) -> Decimal:
    return value.quantize(_PLACES, ROUND_HALF_UP)


# ------------------------------------------------------------------ 上下文
def item_context(
    statement: str, sections: Sequence[Section], body: Sequence[EvidenceText], position: dict[str, int]
) -> tuple[list[EvidenceText], bool]:
    """完整相关章节，映射缺失时提供整份正文；返回值第二项表示是否需要分节读取。"""
    indices = (
        sorted({position[e] for section in sections for e in section.evidence_ids if e in position}) if sections else list(range(len(body)))
    )
    context = [body[i] for i in indices]
    return context, sum(len(b.quote) for b in context) > PART_CHARS


def context_parts(context: Sequence[EvidenceText]) -> list[list[EvidenceText]]:
    """按原顺序分批，不丢字符；超长证据块保留原证据身份并分段读取。"""
    parts: list[list[EvidenceText]] = []
    used = PART_CHARS
    for block in context:
        for start in range(0, len(block.quote), PART_CHARS):
            piece = EvidenceText(block.evidence_id, block.quote[start : start + PART_CHARS])
            if used + len(piece.quote) > PART_CHARS:
                parts.append([])
                used = 0
            parts[-1].append(piece)
            used += len(piece.quote)
    return parts


def _read_context(
    llm: LlmClient,
    context: list[EvidenceText],
    rule: str,
    usage: Usage,
    ctx: JobContext,
    temperature: float,
) -> tuple[str | None, list[dict[str, Any]]]:
    parts = context_parts(context)
    ledger: list[dict[str, Any]] = []
    readings: list[dict[str, Any]] = []
    for n, part in enumerate(parts, 1):
        ctx.checkpoint()
        entry: dict[str, Any] = {
            "part": n,
            "evidence_ids": [b.evidence_id for b in part],
            "chars": sum(len(b.quote) for b in part),
            "state": "unread",
        }
        ledger.append(entry)
        if len(parts) > MAX_READING_PARTS:
            entry["reason"] = "reading_parts_limit"
            continue
        try:
            out = call_validated(
                llm,
                prompts.SectionReading,
                system=prompts.SECTION_READING_SYSTEM,
                user=f"评分条款：{rule}\n正文第 {n}/{len(parts)} 部分：\n{prompts.render_evidence(part)}",
                usage=usage,
                temperature=temperature,
            )
            offered = {b.evidence_id: b for b in part}
            if any(
                any(e not in offered for e in o.evidence_ids) or not quote_supported(o.quote, offered, o.evidence_ids)
                for o in out.observations
            ):
                raise IncompleteGeneration("分节引用无法落地")
        except IncompleteGeneration:
            entry.update(state="failed", reason="invalid_reading")
            continue
        entry["state"] = "read"
        readings.append({"part": n, **out.model_dump()})
    if any(e["state"] != "read" for e in ledger):
        return None, ledger
    summary = json.dumps(readings, ensure_ascii=False)
    if len(summary) > SYNTHESIS_CHARS:
        return None, [*ledger, {"state": "failed", "reason": "synthesis_context_limit"}]
    return summary, ledger


# ------------------------------------------------------------------ 逐项判断
@dataclass(frozen=True)
class Judged:
    """一次判断经落地校验之后的结果。"""

    score: Decimal
    grades: list[dict[str, str]]
    grade: int | None
    interval: tuple[Decimal, Decimal] | None  # 所定档次的分值区间（截到 0～满分）
    grade_position: float | None
    key_points: list[dict[str, Any]]
    coverage: float
    downgraded: int
    specificity: float
    specificity_note: str
    effectiveness: dict[str, Any]
    consistency: dict[str, Any]
    assessment: str
    limitations: str


def ground(out: prompts.ItemJudgement, offered: set[str], points: Decimal) -> Judged:
    """引用只保留本次提供过的正文；写到（covered／partial）却没有可核对引用的要点降为没写（missing）。"""
    key_points: list[dict[str, Any]] = []
    downgraded = 0
    for kp in out.key_points:
        evidence = [e for e in kp.evidence_ids if e in offered][:3]
        status = kp.status
        if status != "missing" and not evidence:
            status, downgraded = "missing", downgraded + 1
        key_points.append({"point": kp.point, "status": status, "evidence_ids": evidence if status != "missing" else []})

    def dimension(value: prompts.QualityDimension) -> dict[str, Any]:
        ids = list(dict.fromkeys(e for e in value.evidence_ids if e in offered))
        required = 2 if value.status == "contradicted" else 1
        if value.status != "unclear" and len(ids) < required:
            return {"status": "unclear", "note": "判断缺少可核对的正文引用", "evidence_ids": []}
        return {**value.model_dump(), "evidence_ids": ids}

    interval = position = None
    if out.grade is not None:
        chosen = out.grades[out.grade]
        interval = (min(max(_q(Decimal(chosen.low)), Decimal(0)), points), min(max(_q(Decimal(chosen.high)), Decimal(0)), points))
        position = 1.0 if len(out.grades) == 1 else 1 - out.grade / (len(out.grades) - 1)
    return Judged(
        score=min(_q(Decimal(out.score)), points),
        grades=[g.model_dump() for g in out.grades],
        grade=out.grade,
        interval=interval,
        grade_position=position,
        key_points=key_points,
        coverage=statistics.fmean(_STATUS_VALUE[k["status"]] for k in key_points),
        downgraded=downgraded,
        specificity=out.specificity,
        specificity_note=out.specificity_note,
        effectiveness=dimension(out.effectiveness),
        consistency=dimension(out.consistency),
        assessment=out.assessment,
        limitations=out.limitations,
    )


def aggregate(rule: db.Row, points: Decimal, judged: Sequence[Judged], *, mapped: bool, sections: list[str], rubric: str) -> dict[str, Any]:
    """一条评分条款的汇总（分数为该条款的分值）。``judged`` 为空表示全部判断都不可用。

    ``item_id`` 是稳定的条款标识（规则 ID，同一规则包内不变）；``rubric`` 是提取规则时引用的评分标准原文。
    """
    base = {
        "item_id": rule["id"],
        "rule_id": rule["id"],
        "rubric": rubric,
        "statement": rule["statement"],
        "max_points": decimal_text(points),
        "rule_basis": rule["basis"],
        "mapped": mapped,
        "sections": sections,
        "repeats_valid": len(judged),
    }
    if not judged:
        return {
            **base,
            "failed": True,
            "estimate": _q(points / 2),
            "low": Decimal(0),
            "high": points,
            "scores": [],
            "evidence_ids": [],
            "assessment": "该项评估失败，按 0 到满分全幅计入区间。",
            "limitations": "模型输出不可用",
            "grades": [],
            "grade": None,
            "grade_label": None,
            "grade_position": None,
            "coverage": None,
            "specificity": None,
            "specificity_note": "",
            "effectiveness": {"status": "unclear", "note": "评估失败", "evidence_ids": []},
            "consistency": {"status": "unclear", "note": "评估失败", "evidence_ids": []},
            "repeat_spread": None,
            "key_points": [],
            "missing_points": [],
            "downgraded": 0,
        }
    scores = [j.score for j in judged]
    bounds = [*scores, *(b for j in judged if j.interval for b in j.interval)]
    positions = [j.grade_position for j in judged if j.grade_position is not None]
    first = judged[0]
    evidence = list(
        dict.fromkeys(
            [
                *first.consistency["evidence_ids"],
                *first.effectiveness["evidence_ids"],
                *(e for k in first.key_points for e in k["evidence_ids"]),
            ]
        )
    )[:MAX_ITEM_EVIDENCE]
    return {
        **base,
        "failed": False,
        "estimate": _q(sum(scores, Decimal(0)) / len(scores)),
        "low": min(bounds),
        "high": max(bounds),
        "scores": [decimal_text(s) for s in scores],
        "evidence_ids": evidence,
        "assessment": first.assessment,
        "limitations": first.limitations,
        "grades": first.grades,
        "grade": first.grade,
        "grade_label": first.grades[first.grade]["label"] if first.grade is not None else None,
        "grade_position": round(statistics.fmean(positions), 4) if positions else None,
        "coverage": round(statistics.fmean(j.coverage for j in judged), 4),
        "specificity": round(statistics.fmean(j.specificity for j in judged), 4),
        "specificity_note": first.specificity_note,
        "effectiveness": first.effectiveness,
        "consistency": first.consistency,
        "repeat_spread": round(float((max(scores) - min(scores)) / points), 4),
        "key_points": first.key_points,
        "missing_points": [k["point"] for k in first.key_points if k["status"] == "missing"],
        "downgraded": sum(j.downgraded for j in judged),
    }


def item_facts(item: dict[str, Any]) -> features.ItemFacts:
    return features.ItemFacts(
        max_points=float(item["max_points"]),
        estimate=float(item["estimate"]),
        low=float(item["low"]),
        high=float(item["high"]),
        failed=item["failed"],
        mapped=item["mapped"],
        grade_position=item["grade_position"],
        coverage=item["coverage"],
        specificity=item["specificity"],
        repeat_spread=item["repeat_spread"],
    )


# ------------------------------------------------------------------ 输入
@dataclass(frozen=True)
class Inputs:
    scoring: list[db.Row]
    rule_evidence: dict[str, EvidenceText]
    body: list[checks.Passage]
    body_sha256: str
    body_pages: int | None
    engineering_type: str | None
    region: str | None
    technical_full_score: Decimal | None
    qualification: tuple[int, int]  # （违反, 无法判断）
    findings: tuple[int, int]  # （前后矛盾, 范围残留）
    models: dict[model_registry.Environment, db.Row]  # 环境 → 生效的打分模型发布


def _load(conn: Connection, project_id: str, snapshot_id: str) -> Inputs | None:
    snap = db.one(
        conn, "SELECT body_version_id,rule_set_id FROM input_snapshots WHERE id=:s AND project_id=:p", {"s": snapshot_id, "p": project_id}
    )
    if snap is None:
        return None
    scoring = [
        r
        for r in rules_service.effective_rules(conn, project_id, snap["rule_set_id"])
        if r["kind"] == "scoring" and r["max_points"] is not None
    ]
    rule_evidence = {
        e.evidence_id: e for e in _load_evidence_by_ids(conn, project_id, sorted({e for r in scoring for e in r["evidence_ids_json"]}))
    }
    body = [
        checks.Passage(r["id"], r["physical_page"], r["quote"])
        for r in _evidence_rows(conn, project_id, [snap["body_version_id"]], snapshot_id)
    ]
    version = db.one(
        conn,
        """SELECT a.sha256, (s.parse_inputs_json->fv.id->>'page_count')::integer AS pages
           FROM file_versions fv JOIN artifacts a ON a.id=fv.artifact_id JOIN input_snapshots s ON s.id=:s AND s.project_id=fv.project_id WHERE fv.id=:v""",
        {"v": snap["body_version_id"], "s": snapshot_id},
    )
    project = db.one(conn, "SELECT region, engineering_type FROM projects WHERE id=:p", {"p": project_id})
    assert version is not None
    assert project is not None
    term = rules_service.terms_of_package(conn, snap["rule_set_id"]).get("technical_full_score")
    verdicts = db.one(
        conn,
        """SELECT count(*) FILTER (WHERE v.verdict='violated') AS violated, count(*) FILTER (WHERE v.verdict='unclear') AS unclear
           FROM rule_verdicts v JOIN rule_items i ON i.id=v.rule_id
           WHERE v.run_id=(SELECT id FROM jobs WHERE project_id=:p AND snapshot_id=:s AND kind='diagnosis' AND state='succeeded'
                           ORDER BY finished_at DESC, id DESC LIMIT 1) AND i.kind = ANY(:k)""",
        {"p": project_id, "s": snapshot_id, "k": sorted(QUALIFICATION_KINDS)},
    )
    found = db.one(
        conn,
        """SELECT count(*) FILTER (WHERE category='consistency') AS consistency, count(*) FILTER (WHERE category='scope') AS scope
           FROM findings WHERE project_id=:p AND snapshot_id=:s""",
        {"p": project_id, "s": snapshot_id},
    )
    assert verdicts is not None
    assert found is not None
    environments: tuple[model_registry.Environment, ...] = ("business", "shadow")
    models = {env: row for env in environments if (row := model_registry.routed(conn, TARGET_SCORING, env)) is not None}
    return Inputs(
        scoring=scoring,
        rule_evidence=rule_evidence,
        body=body,
        body_sha256=version["sha256"],
        body_pages=version["pages"],
        engineering_type=project["engineering_type"],
        region=project["region"],
        technical_full_score=Decimal(term["value"]) if term else None,
        qualification=(verdicts["violated"], verdicts["unclear"]),
        findings=(found["consistency"], found["scope"]),
        models=models,
    )


# ------------------------------------------------------------------ 打分模型
def _apply_model(row: db.Row, feats: features.Features, inputs: Inputs, maximum: Decimal) -> dict[str, Any]:
    """一个环境的打分模型结果（写进明细）。``state``：applied 适用并已计算，out_of_scope 不适用。"""
    base = {"bundle_id": row["bundle_id"], "validation_id": row["validation_id"], "release_id": row["release_id"]}
    try:
        model = scoring_models.parse_model(row["components_json"])
    except Unprocessable as exc:
        return {**base, "model_id": row["components_json"].get("model_id"), "state": "out_of_scope", "reason": exc.message}
    base["model_id"] = model.model_id
    if (
        model.input_method != PREDICTION_METHOD
        or model.evaluation.acceptance is None
        or model.evaluation.acceptance.status != "passed"
        or model.evaluation.mode != "holdout"
    ):
        return {**base, "state": "out_of_scope", "reason": "校准模型的章节读取方法或独立验收条件不适用于本轮，需要重新评测"}
    reason = scoring_models.out_of_scope_reason(model, feats, engineering_type=inputs.engineering_type, region=inputs.region)
    if reason is not None:
        return {**base, "state": "out_of_scope", "reason": reason, "scope": scoring_models.scope_text(model)}
    applied = scoring_models.apply(model, feats)

    def points(pct: float) -> Decimal:
        # 校准分数的误差以分计，保留一位小数，不给出超出模型精度的位数
        value = (Decimal(str(pct)) / 100 * maximum).quantize(_CALIBRATED_PLACES, ROUND_HALF_UP)
        return min(max(value, Decimal(0)), maximum)

    return {
        **base,
        "state": "applied",
        "reason": scoring_models.calibrated_reason(model),
        "scope": scoring_models.scope_text(model),
        "pairs": model.evaluation.n,
        "mae_pct": model.evaluation.mae_pct,
        "pct": round(applied.pct, 4),
        "interval_pct": {
            "0.8": [round(applied.low80, 4), round(applied.high80, 4)],
            "0.9": [round(applied.low90, 4), round(applied.high90, 4)],
        },
        "maximum": maximum,
        "estimate": points(applied.pct),
        "low": points(applied.low80),
        "high": points(applied.high80),
    }


def _text(value: Any) -> Any:
    """明细里的数值一律写成十进制字符串。"""
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, dict):
        return {k: _text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_text(v) for v in value]
    return value


# ------------------------------------------------------------------ 处理器
def _map_sections(llm: LlmClient, scoring: Sequence[db.Row], sections: Sequence[Section], usage: Usage) -> dict[str, list[Section]] | None:
    """规则 ID → 对应章节（按模型给出的相关程度）；输出不合格时为 ``None``（整份正文回退）。"""
    by_id = {section.id: section for section in sections}
    selected: dict[str, list[Section]] = {rule["id"]: [] for rule in scoring}
    for item_start in range(0, len(scoring), MAPPING_BATCH):
        refs = {f"R{n}": rule for n, rule in enumerate(scoring[item_start : item_start + MAPPING_BATCH], 1)}
        for start in range(0, len(sections), MAPPING_BATCH):
            batch = list(sections[start : start + MAPPING_BATCH])
            try:
                out = call_validated(
                    llm,
                    prompts.mapping_output(list(refs), [section.id for section in batch]),
                    system=prompts.MAPPING_SYSTEM,
                    user=prompts.mapping_user(
                        batch, [(ref, decimal_text(r["max_points"]) or "0", r["statement"]) for ref, r in refs.items()]
                    ),
                    usage=usage,
                )
            except IncompleteGeneration:
                return None
            for item in out.mapping:
                selected[refs[item.item]["id"]].extend(by_id[sid] for sid in dict.fromkeys(item.sections))
    return selected


def _judge_item(
    llm: LlmClient,
    rule: db.Row,
    mapped: list[Section],
    body: list[EvidenceText],
    position: dict[str, int],
    inputs: Inputs,
    repeats: int,
    usage: Usage,
    ctx: JobContext,
) -> tuple[dict[str, Any], list[EvidenceText], int]:
    """一条评分条款：组织上下文、重复判断、汇总。返回（汇总, 上下文, 不可用的判断次数）。"""
    points = Decimal(str(rule["max_points"]))
    context, partitioned = item_context(rule["statement"], mapped, body, position)
    labels = [s.label for s in mapped]
    rule_evidence = _rule_evidence(rule, inputs)
    user = prompts.judgement_user(
        rule["statement"], rule_evidence, decimal_text(points) or "0", context if not partitioned else [], sections=labels, truncated=False
    )
    offered = {b.evidence_id for b in context}
    judged: list[Judged] = []
    invalid = 0
    readings: list[dict[str, Any]] = []
    for repeat in range(repeats):
        ctx.checkpoint()
        temperature = 0.0 if repeat == 0 else REPEAT_TEMPERATURE
        prompt = user
        repeat_offered = offered
        if partitioned:
            notes, ledger = _read_context(llm, context, rule["statement"], usage, ctx, temperature)
            readings.append({"repeat": repeat + 1, "parts": ledger, "state": "read" if notes is not None else "failed"})
            if notes is None:
                invalid += 1
                continue
            repeat_offered = {
                eid for part in json.loads(notes) for observation in part["observations"] for eid in observation["evidence_ids"]
            }
            prompt = prompt.replace("（没有找到相关正文）", "（原文已分节读取，见以下记录）")
            prompt += (
                "\n以下是完整相关正文分节读取所得的带原页引用记录（不是整章原文）：\n"
                + notes
                + "\n请跨节综合判断并检查相互矛盾的数字、条件和措施；只引用记录提供的原证据 ID。"
                "单节未发现不等于整章未响应。不要平均各节分数，也不要把摘要视为无损全文。"
            )
        try:
            out = call_validated(
                llm,
                prompts.item_judgement(points),
                system=prompts.JUDGEMENT_SYSTEM,
                user=prompt,
                usage=usage,
                temperature=temperature,
            )
        except IncompleteGeneration:
            invalid += 1
            continue
        judged.append(ground(out, repeat_offered, points))
    rubric = "\n".join(e.quote for e in rule_evidence)
    item = aggregate(rule, points, judged, mapped=bool(mapped), sections=labels, rubric=rubric)
    item["context_coverage"] = {
        "mode": "section_readings" if partitioned else "full_text",
        "source": "mapped_sections" if mapped else "whole_document_fallback",
        "evidence_ids": list(dict.fromkeys(b.evidence_id for b in context)),
        "chars": sum(len(b.quote) for b in context),
        "readings": readings,
        "valid_judgements": len(judged),
    }
    item["limitations"] = "；".join(
        filter(
            None,
            [item["limitations"], "仅含已解析文字，表格结构与图页未读取", "分节记录综合存在信息损失，质量未验证" if partitioned else ""],
        )
    )
    return item, context, invalid


def _rule_evidence(rule: db.Row, inputs: Inputs) -> list[EvidenceText]:
    return [inputs.rule_evidence[e] for e in rule["evidence_ids_json"] if e in inputs.rule_evidence]


def _round_facts(inputs: Inputs, anchor: anchors.AnchorResult | None) -> features.RoundFacts:
    return features.RoundFacts(
        technical_full_score=float(inputs.technical_full_score) if inputs.technical_full_score else None,
        body_pages=inputs.body_pages,
        body_chars=sum(len(p.text) for p in inputs.body),
        qualification_violated=inputs.qualification[0],
        qualification_unclear=inputs.qualification[1],
        findings_consistency=inputs.findings[0],
        findings_scope=inputs.findings[1],
        anchor_pct=anchor.pct if anchor else None,
        anchor_agree=anchor.agree if anchor else None,
        anchor_n=anchor.n if anchor else None,
    )


def make_prediction_handler(llm: LlmClient | None, anchor_source: AnchorSource | None = None) -> Handler:
    """``anchor_source`` 给出本项目可用的锚点包；为 ``None`` 时用当前路由生效的锚点包。"""
    source = anchor_source or anchor_packs.routed_pack

    def handler(ctx: JobContext) -> HandlerOutput | HandlerFailure:
        if llm is None:
            return HandlerFailure("llm_not_configured")
        snapshot_id, project_id = ctx.claim.snapshot_id, ctx.claim.project_id
        if snapshot_id is None:
            return HandlerFailure("invalid_job_input")
        settings = ctx.settings
        with ctx.engine.connect() as conn:
            try:
                loaded = _load(conn, project_id, snapshot_id)
            except Conflict as exc:
                return HandlerFailure(exc.code, exc.message)
            pack = source(conn, ctx.store, project_id) if loaded is not None and settings.prediction_anchors > 0 else None
        if loaded is None:
            return HandlerFailure("snapshot_not_found")
        if not loaded.body:
            return HandlerFailure("body_has_no_evidence")
        usage = Usage()
        sections = build_sections(loaded.body)
        body = [EvidenceText(p.evidence_id, p.text) for p in loaded.body]
        position = {b.evidence_id: i for i, b in enumerate(body)}
        mapping = _map_sections(llm, loaded.scoring, sections, usage) if loaded.scoring else None
        items: list[dict[str, Any]] = []
        contexts: list[list[EvidenceText]] = []
        failed: list[str] = []
        invalid_outputs = 0
        for rule in loaded.scoring:
            ctx.checkpoint()
            item, context, invalid = _judge_item(
                llm, rule, (mapping or {}).get(rule["id"], []), body, position, loaded, settings.prediction_repeats, usage, ctx
            )
            if item["failed"]:
                failed.append(rule["id"])
            items.append(item)
            contexts.append(context)
            invalid_outputs += invalid
        anchor = None
        if pack is not None and items:
            anchor = anchors.compare(
                llm,
                pack,
                [
                    anchors.ItemForComparison(
                        i["rule_id"],
                        i["statement"],
                        float(i["max_points"]),
                        _rule_evidence(rule, loaded),
                        c,
                    )
                    for i, c, rule in zip(items, contexts, loaded.scoring, strict=True)
                ],
                m=settings.prediction_anchors,
                tau=settings.prediction_anchor_tau,
                body_sha256=loaded.body_sha256,
                engineering_type=loaded.engineering_type,
                usage=usage,
                checkpoint=ctx.checkpoint,
            )
        feats = features.compute([item_facts(i) for i in items], _round_facts(loaded, anchor))
        summary = _summary(items)
        maximum = loaded.technical_full_score or (summary["maximum"] if summary else None)
        results = {env: _apply_model(row, feats, loaded, maximum) for env, row in loaded.models.items()} if summary and maximum else {}
        coverage = diagnosis_coverage(len(loaded.scoring), failed, [{"reason": "invalid_output"} for _ in failed])
        artifact = json.dumps(
            _text(
                {
                    "prompt_version": prompts.PROMPT_VERSION,
                    "input_method": PREDICTION_METHOD,
                    "model": llm.model,
                    "repeats": settings.prediction_repeats,
                    "usage": usage.__dict__,
                    "coverage": {**coverage, "failed_rule_ids": failed, "invalid_outputs": invalid_outputs},
                    "mapping": {
                        "status": "none" if not loaded.scoring else "model" if mapping is not None else "fallback",
                        "sections": [
                            {
                                "id": s.id,
                                "title": s.label,
                                "level": s.level,
                                "parent_id": s.parent_id,
                                "chars": s.chars,
                                "first_page": s.first_page,
                            }
                            for s in sections
                        ],
                        "items": {i["rule_id"]: i["sections"] for i in items},
                    },
                    "items": items,
                    "summary": summary,
                    "anchors": anchor.summary() if anchor else None,
                    "feature_spec": features.FEATURE_SPEC,
                    "features": feats,
                    "calibrated": results.get("business"),
                    "shadow": results.get("shadow"),
                }
            ),
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        row = _prediction_row(summary, results.get("business"))

        def finalize(conn: Connection, artifact_id: str) -> None:
            db.run(
                conn,
                """INSERT INTO predictions(id,project_id,snapshot_id,bundle_id,run_id,target,status,purpose,estimated_decimal,low_decimal,high_decimal,
                                           maximum_decimal,validation_status,validation_id,reason,detail_artifact_id,created_at)
                   VALUES (:i,:p,:s,:b,:r,'technical_total',:st,:pu,:e,:lo,:hi,:mx,:vs,:vid,:why,:a,:now)""",
                {**row, "i": new_id("prd"), "p": project_id, "s": snapshot_id, "r": ctx.claim.job_id, "a": artifact_id, "now": utcnow()},
            )

        return HandlerOutput(artifact, "application/json", "prediction-v1", finalize, coverage)

    return handler


def _prediction_row(summary: dict[str, Decimal] | None, business: dict[str, Any] | None) -> dict[str, Any]:
    """预测记录：业务环境的打分模型适用时取校准值，否则取逐项评估合计并如实标注未校准或超出适用范围。"""
    if summary is None:
        return {
            "b": None,
            "st": "abstained",
            "pu": "research",
            "e": None,
            "lo": None,
            "hi": None,
            "mx": None,
            "vs": "not_validated",
            "vid": None,
            "why": "招标文件的评分条款没有提取到分值，无法估计得分。",
        }
    if business is not None and business["state"] == "applied":
        return {
            "b": business["bundle_id"],
            "st": "candidate",
            "pu": "business",
            "e": business["estimate"],
            "lo": business["low"],
            "hi": business["high"],
            "mx": business["maximum"],
            "vs": "validated_in_scope",
            "vid": business["validation_id"],
            "why": business["reason"],
        }
    out_of_scope = business is not None
    return {
        "b": None,
        "st": "candidate",
        "pu": "research",
        "e": summary["estimate"],
        "lo": summary["low"],
        "hi": summary["high"],
        "mx": summary["maximum"],
        "vs": "out_of_scope" if out_of_scope else "not_validated",
        "vid": None,
        "why": f"{business['reason']}，校准模型不适用；以下是未经校准的逐项评估合计，只用于排出可能的失分点。"
        if business is not None
        else UNCALIBRATED_REASON,
    }


def _summary(items: list[dict[str, Any]]) -> dict[str, Decimal] | None:
    if not items:
        return None

    def total(key: str) -> Decimal:
        return _q(sum((Decimal(i[key]) for i in items), Decimal(0)))

    return {"estimate": total("estimate"), "low": total("low"), "high": total("high"), "maximum": total("max_points")}
