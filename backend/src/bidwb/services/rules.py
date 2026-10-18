"""规则包、规则条款的人工确认，以及事实集。

规则包与条款追加保存、不可改。“是否已确认”不是包上的字段，而是由人工审核记录推导：
包不是冲突状态，每条规则的最新审核都是“确认”或“驳回”（没有待定或未审核），且至少有一条被确认时，规则包才算生效确认。
评审不等规则确认：没人看过的规则按“未确认依据”照常参与评审，被驳回或暂缓的不参与。
规则包一旦被某一轮评审引用就不再改动；之后的更正落在复制出的新规则包上。
一次审核就是一行追加记录，没有“先改包再写日志”的两处不一致。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection

from bidwb import db, source_effectivity, term_conflicts
from bidwb.access import Actor, require_project
from bidwb.errors import Conflict, NotFound, PreconditionFailed, Unprocessable
from bidwb.schemas import (
    BidTerms,
    ConfirmRulesRequest,
    ConfirmRulesResult,
    Fact,
    FactList,
    FactRequest,
    FactSetResult,
    FactWithdrawRequest,
    FullScoreTerm,
    PriceRuleTerm,
    ResolveTermRequest,
    Review,
    ReviewRequest,
    Rule,
    RuleSet,
    TermAlternative,
    TermConflict,
)
from bidwb.services import action_context, audit, current_materials, evidence, parse_identity
from bidwb.services.files import CONTRACT_VERSION
from bidwb.storage import ObjectStore, artifact_key
from bidwb.util import canonical_json, decimal_text, new_id, sha256_hex, utcnow

RULE_KIND = "rule"
_FINAL_DECISIONS = frozenset({"confirm", "reject"})
CARRIED_REASON_PREFIX = "沿用自上一版规则集："
QUALIFICATION_KINDS = frozenset({"disqualification", "mandatory"})  # 违反即可能被否决的规则：提交前必须由人确认或驳回


def _latest_reviews(conn: Connection, project_id: str, rule_ids: list[str]) -> dict[str, db.Row]:
    if not rule_ids:
        return {}
    rows = db.all_(
        conn,
        """SELECT DISTINCT ON (object_id) object_id, id, decision, reason, object_version, reviewed_at, actor_id
           FROM reviews WHERE project_id=:p AND object_kind=:k AND object_id = ANY(:ids) ORDER BY object_id, reviewed_at DESC, id DESC""",
        {"p": project_id, "k": RULE_KIND, "ids": rule_ids},
    )
    return {r["object_id"]: r for r in rows}


def _effective_status(package_status: str, items: list[db.Row], reviews: dict[str, db.Row]) -> str:
    if package_status == "conflict":
        return "conflict"
    decisions = [(r["decision"] if (r := reviews.get(i["id"])) is not None else None) for i in items]
    if decisions and all(d in _FINAL_DECISIONS for d in decisions) and "confirm" in decisions:
        return "confirmed"
    return "candidate"


def current_tender_version_ids(conn: Connection, project_id: str) -> list[str]:
    """项目当前的招标文件与补遗：每个文件的最新版本，按 ID 排序。"""
    return sorted(r["id"] for r in current_materials.heads(conn, project_id) if r["role"] in {"tender", "supplement"})


def latest_package(conn: Connection, project_id: str, package_id: str | None = None) -> db.Row | None:
    if package_id:
        return db.one(conn, "SELECT * FROM rule_packages WHERE id=:i AND project_id=:p", {"i": package_id, "p": project_id})
    return db.one(
        conn, "SELECT * FROM rule_packages WHERE project_id=:p ORDER BY revision DESC, created_at DESC LIMIT 1", {"p": project_id}
    )


def sources_current(conn: Connection, project_id: str, package: db.Row) -> bool:
    if package["parse_inputs_json"] is None:
        return False
    versions = current_tender_version_ids(conn, project_id)
    current, _ = parse_identity.capture(conn, project_id, versions)
    return bool(sorted(package["source_versions_json"]) == versions and current == package["parse_inputs_json"])


def require_current_sources(conn: Connection, project_id: str, package: db.Row) -> None:
    if package["parse_inputs_json"] is None:
        raise Conflict("rule_parse_identity_unknown", "该历史规则包未冻结解析来源，请重新提取规则后继续")
    if not sources_current(conn, project_id, package):
        raise Conflict("rules_parse_stale", "招标资料或识别依据已变化，请重新提取规则后继续")


def get_rules(conn: Connection, actor: Actor, project_id: str) -> RuleSet:
    require_project(conn, actor, project_id)
    package = latest_package(conn, project_id)
    if package is None:
        raise NotFound("rules_not_extracted", "该项目尚未提取规则")
    items = db.all_(
        conn, "SELECT * FROM rule_items WHERE package_id=:p AND project_id=:pr ORDER BY id", {"p": package["id"], "pr": project_id}
    )
    reviews = _latest_reviews(conn, project_id, [i["id"] for i in items])
    rules: list[Rule] = []
    for item in items:
        review = reviews.get(item["id"])
        confirmation = {"confirm": "confirmed", "reject": "rejected"}.get(review["decision"] if review else "", "pending")
        rules.append(
            Rule(
                rule_id=item["id"],
                kind=item["kind"],
                statement=item["statement"],
                conditions=item["conditions_json"],
                exceptions=item["exceptions_json"],
                evidence=evidence.evidence_for_ids(conn, project_id, item["evidence_ids_json"], annotate=False),
                confirmation=confirmation,
                carried_from_rule_id=item["carried_from_rule_id"],
                max_points=decimal_text(item["max_points"]),
                source_status=source_effectivity.state(package["effectivity_json"], item),
            )
        )
    return RuleSet(
        source_parse_state="legacy_unfrozen"
        if package["parse_inputs_json"] is None
        else ("current" if sources_current(conn, project_id, package) else "stale"),
        rule_set_id=package["id"],
        project_id=project_id,
        source_version_ids=list(package["source_versions_json"]),
        status="conflict"
        if term_conflicts.pending(package["terms_json"]) or source_effectivity.pending_count(package["effectivity_json"], items)
        else _effective_status(
            package["status"], [item for item in items if source_effectivity.state(package["effectivity_json"], item) == "active"], reviews
        ),
        revision=package["revision"],
        rules=rules,
        terms=bid_terms(conn, project_id, package["terms_json"]),
        effectivity_decisions=package["effectivity_json"].get("decisions", []),
    )


def bid_terms(conn: Connection, project_id: str, terms: dict[str, Any]) -> BidTerms:
    def ev(term: dict[str, Any]) -> dict[str, Any]:
        rest = {k: v for k, v in term.items() if k != "evidence_ids"}
        return {**rest, "evidence": evidence.evidence_for_ids(conn, project_id, term["evidence_ids"])}

    active = term_conflicts.effective(terms)
    full, price = active.get("technical_full_score"), active.get("price_rule")
    return BidTerms(
        technical_full_score=FullScoreTerm.model_validate(ev(full)) if full else None,
        price_rule=PriceRuleTerm.model_validate(ev(price)) if price else None,
        conflicts=[
            TermConflict(
                term=key,
                alternatives=[
                    TermAlternative(
                        option_id=term_conflicts.option_id(candidate),
                        values=term_conflicts.values(candidate),
                        quote=candidate["quote"],
                        evidence=evidence.evidence_for_ids(conn, project_id, candidate["evidence_ids"]),
                    )
                    for candidate in candidates
                ],
            )
            for key, candidates in term_conflicts.pending(terms).items()
        ],
    )


def terms_of_package(conn: Connection, package_id: str) -> dict[str, Any]:
    row = db.one(conn, "SELECT terms_json FROM rule_packages WHERE id=:k", {"k": package_id})
    return term_conflicts.effective(dict(row["terms_json"])) if row else {}


def effective_rules(conn: Connection, project_id: str, package_id: str) -> list[db.Row]:
    """评审实际使用的规则：人工确认的，以及还没有人看过的（标为未确认依据）；被驳回或暂缓的不用。

    每行在规则条目的列之外多一个 ``basis``（``confirmed`` 或 ``unconfirmed``）。
    """
    items = db.all_(
        conn, "SELECT * FROM rule_items WHERE package_id=:p AND project_id=:pr ORDER BY id", {"p": package_id, "pr": project_id}
    )
    reviews = _latest_reviews(conn, project_id, [i["id"] for i in items])
    effectivity = (
        db.scalar(conn, "SELECT effectivity_json FROM rule_packages WHERE id=:k AND project_id=:p", {"k": package_id, "p": project_id})
        or {}
    )
    out: list[db.Row] = []
    for item in items:
        if source_effectivity.state(effectivity, item) != "active":
            continue
        decision = reviews[item["id"]]["decision"] if item["id"] in reviews else None
        if decision in ("reject", "defer"):
            continue
        out.append({**item, "basis": "confirmed" if decision == "confirm" else "unconfirmed"})  # type: ignore[arg-type]
    return out


def unconfirmed_qualification_count(conn: Connection, project_id: str, package_id: str) -> int:
    """废标／否决／强制类规则里还没有人确认或驳回的条数。"""
    return sum(1 for r in effective_rules(conn, project_id, package_id) if r["kind"] in QUALIFICATION_KINDS and r["basis"] == "unconfirmed")


def _is_frozen(conn: Connection, package_id: str) -> bool:
    return db.one(conn, "SELECT 1 AS x FROM input_snapshots WHERE rule_set_id=:k LIMIT 1", {"k": package_id}) is not None


def _clone_package(
    conn: Connection, project_id: str, package: db.Row, *, terms: dict[str, Any] | None = None, effectivity: dict[str, Any] | None = None
) -> tuple[str, dict[str, str]]:
    """规则包已被某一轮评审引用而不可改：复制出新规则包（条款相同、决定沿用），之后的更正落在新包上。

    返回（新规则包 ID, 旧规则 ID → 新规则 ID）。调用方须已锁项目行。
    """
    new_package = new_id("rpk")
    revision = int(db.scalar(conn, "SELECT MAX(revision) FROM rule_packages WHERE project_id=:p", {"p": project_id})) + 1
    now = utcnow()
    db.run(
        conn,
        """INSERT INTO rule_packages(id,project_id,revision,status,artifact_id,source_versions_json,terms_json,effectivity_json,parse_inputs_json,created_at)
           VALUES (:i,:p,:r,'candidate',:a,CAST(:s AS jsonb),CAST(:t AS jsonb),CAST(:ef AS jsonb),CAST(:inputs AS jsonb),:now)""",
        {
            "i": new_package,
            "p": project_id,
            "r": revision,
            "a": package["artifact_id"],
            "s": json.dumps(package["source_versions_json"]),
            "t": json.dumps(package["terms_json"] if terms is None else terms, ensure_ascii=False),
            "ef": json.dumps(package["effectivity_json"] if effectivity is None else effectivity, ensure_ascii=False),
            "inputs": json.dumps(package["parse_inputs_json"]) if package["parse_inputs_json"] is not None else None,
            "now": now,
        },
    )
    items = db.all_(
        conn, "SELECT * FROM rule_items WHERE package_id=:p AND project_id=:pr ORDER BY id", {"p": package["id"], "pr": project_id}
    )
    reviews = _latest_reviews(conn, project_id, [i["id"] for i in items])
    mapping: dict[str, str] = {}
    for item in items:
        new_rule = new_id("rul")
        mapping[item["id"]] = new_rule
        db.run(
            conn,
            """INSERT INTO rule_items(id,project_id,package_id,kind,statement,conditions_json,exceptions_json,evidence_ids_json,max_points,carried_from_rule_id)
               VALUES (:i,:p,:pk,:k,:s,CAST(:c AS jsonb),CAST(:e AS jsonb),CAST(:ev AS jsonb),:mp,:cf)""",
            {
                "i": new_rule,
                "p": project_id,
                "pk": new_package,
                "k": item["kind"],
                "s": item["statement"],
                "c": json.dumps(item["conditions_json"], ensure_ascii=False),
                "e": json.dumps(item["exceptions_json"], ensure_ascii=False),
                "ev": json.dumps(item["evidence_ids_json"]),
                "mp": item["max_points"],
                "cf": item["id"],
            },
        )
        old = reviews.get(item["id"])
        if old is not None:
            reason = old["reason"]
            db.run(
                conn,
                """INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
                   VALUES (:i,:p,:k,:o,:v,:d,:r,:a,:now)""",
                {
                    "i": new_id("rev"),
                    "p": project_id,
                    "k": RULE_KIND,
                    "o": new_rule,
                    "v": str(revision),
                    "d": old["decision"],
                    "r": reason if reason.startswith(CARRIED_REASON_PREFIX) else CARRIED_REASON_PREFIX + reason,
                    "a": old["actor_id"],
                    "now": now,
                },
            )
    return new_package, mapping


def resolve_term(conn: Connection, actor: Actor, project_id: str, req: ResolveTermRequest, request_id: str) -> RuleSet:
    require_project(conn, actor, project_id)
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})
    package = latest_package(conn, project_id)
    if package is None:
        raise NotFound("rules_not_extracted")
    if req.object_version != str(package["revision"]):
        raise PreconditionFailed("stale_version", "规则包已有更新，请刷新后重新核实", current_version=str(package["revision"]))
    if sorted(package["source_versions_json"]) != current_tender_version_ids(conn, project_id):
        raise PreconditionFailed("stale_inputs", "招标文件或补遗已有更新，请等待规则重新提取后核实")
    require_current_sources(conn, project_id, package)
    terms = dict(package["terms_json"])
    alternatives = term_conflicts.pending(terms).get(req.term, [])
    candidate = next((item for item in alternatives if term_conflicts.option_id(item) == req.option_id), None)
    if candidate is None:
        raise Unprocessable("term_option_not_found", "该候选不属于当前待核实条件，请刷新后重试")
    terms[req.term] = candidate
    terms["_resolved"] = {**terms.get("_resolved", {}), req.term: req.option_id}
    new_package, _ = _clone_package(conn, project_id, package, terms=terms)
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="rule_term.resolve",
        object_kind="rule_package",
        object_id=new_package,
        request_id=request_id,
        details={"from_package": package["id"], "term": req.term, "option_id": req.option_id, "reason": req.reason},
    )
    return get_rules(conn, actor, project_id)


def review_rule(conn: Connection, actor: Actor, rule_id: str, req: ReviewRequest, request_id: str) -> Review:
    item = db.one(
        conn,
        "SELECT i.id,i.project_id,i.package_id,p.revision FROM rule_items i JOIN rule_packages p ON p.id=i.package_id WHERE i.id=:i",
        {"i": rule_id},
    )
    if item is None:
        raise NotFound("rule_not_found")
    project_id = item["project_id"]
    require_project(conn, actor, project_id)
    if req.decision not in {"confirm", "reject", "defer"}:
        raise Unprocessable("decision_not_allowed", "规则只能确认、驳回或暂缓")
    if req.object_version != str(item["revision"]):
        raise PreconditionFailed("stale_version", "规则包已有新版本，请刷新后重新审核", current_version=str(item["revision"]))
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})  # 克隆规则包与追加审核要串行
    latest_pkg = latest_package(conn, project_id)
    if latest_pkg is not None and latest_pkg["id"] != item["package_id"]:
        raise PreconditionFailed("stale_version", "该规则属于旧版规则包", current_version=str(latest_pkg["revision"]))
    if latest_pkg is not None:
        require_current_sources(conn, project_id, latest_pkg)
    current_rule = db.one(conn, "SELECT * FROM rule_items WHERE id=:i AND project_id=:p", {"i": rule_id, "p": project_id})
    if (
        latest_pkg is not None
        and current_rule is not None
        and source_effectivity.state(latest_pkg["effectivity_json"], current_rule) != "active"
    ):
        raise Conflict("rule_effectivity_review_required", "这条要求的生效关系已有更正，请在补遗影响中核实，不能用普通规则确认覆盖效力决定")
    version = req.object_version
    previous = _latest_reviews(conn, project_id, [rule_id]).get(rule_id)
    was_effective = previous is None or previous["decision"] == "confirm"
    if _is_frozen(conn, item["package_id"]) and was_effective != (req.decision == "confirm"):
        # 这次决定改变了参与评审的规则集合，而评审引用着这版规则包：保持它不变（旧一轮结果仍可复现），
        # 更正落在复制出的新规则包上，下一轮评审使用它。只是把“未确认”确认下来不改变规则集合，直接追加审核。
        package = latest_package(conn, project_id, item["package_id"])
        assert package is not None
        new_package, mapping = _clone_package(conn, project_id, package)
        rule_id = mapping[rule_id]
        version = str(db.scalar(conn, "SELECT revision FROM rule_packages WHERE id=:i", {"i": new_package}))
    review_id = new_id("rev")
    now = utcnow()
    db.run(
        conn,
        """INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
           VALUES (:i,:p,:k,:o,:v,:d,:r,:a,:now)""",
        {
            "i": review_id,
            "p": project_id,
            "k": RULE_KIND,
            "o": rule_id,
            "v": version,
            "d": req.decision,
            "r": req.reason,
            "a": actor.member_id,
            "now": now,
        },
    )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="rule.review",
        object_kind="rule",
        object_id=rule_id,
        request_id=request_id,
        details={"decision": req.decision},
    )
    return Review(
        review_id=review_id,
        project_id=project_id,
        object_id=rule_id,
        object_version=version,
        decision=req.decision,
        reason=req.reason,
        actor_id=actor.member_id,
        reviewed_at=now,
    )


def confirm_pending(conn: Connection, actor: Actor, project_id: str, req: ConfirmRulesRequest, request_id: str) -> ConfirmRulesResult:
    """批量确认未审核的规则。未审核的规则本来就参与评审，确认不改变评审所用的规则集合，所以不必复制规则包。"""
    require_project(conn, actor, project_id)
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})
    action_context.require_current(conn, project_id, req.expected_context)
    package = latest_package(conn, project_id)
    if package is None:
        raise NotFound("rules_not_extracted", "该项目尚未提取规则")
    if req.object_version != str(package["revision"]):
        raise PreconditionFailed("stale_version", "规则包已有新版本，请刷新后重新确认", current_version=str(package["revision"]))
    require_current_sources(conn, project_id, package)
    ids = list(dict.fromkeys(req.rule_ids))
    known = {
        r["id"]
        for r in db.all_(
            conn,
            "SELECT id FROM rule_items WHERE package_id=:k AND project_id=:p AND id = ANY(:ids)",
            {"k": package["id"], "p": project_id, "ids": ids},
        )
    }
    if len(known) != len(ids):
        raise NotFound("rule_not_found", "部分规则不属于当前规则包，请刷新后重试")
    reviewed = _latest_reviews(conn, project_id, ids)
    rows = db.all_(conn, "SELECT * FROM rule_items WHERE package_id=:k AND project_id=:p", {"k": package["id"], "p": project_id})
    active = {row["id"] for row in rows if source_effectivity.state(package["effectivity_json"], row) == "active"}
    pending = [i for i in ids if i not in reviewed and i in active]
    now = utcnow()
    for rule_id in pending:
        db.run(
            conn,
            """INSERT INTO reviews(id,project_id,object_kind,object_id,object_version,decision,reason,actor_id,reviewed_at)
               VALUES (:i,:p,:k,:o,:v,'confirm','',:a,:now)""",
            {"i": new_id("rev"), "p": project_id, "k": RULE_KIND, "o": rule_id, "v": req.object_version, "a": actor.member_id, "now": now},
        )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="rule.confirm_pending",
        object_kind="rule_package",
        object_id=package["id"],
        request_id=request_id,
        details={"confirmed": len(pending), "skipped": len(ids) - len(pending)},
    )
    return ConfirmRulesResult(confirmed=len(pending), skipped=len(ids) - len(pending))


# ------------------------------------------------------------------ 事实集
def list_facts(conn: Connection, actor: Actor, project_id: str) -> FactList:
    require_project(conn, actor, project_id)
    current = db.one(conn, "SELECT id FROM fact_sets WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    if current is None:
        return FactList(fact_set_id=None, items=[])
    rows = db.all_(conn, "SELECT * FROM fact_items WHERE fact_set_id=:f ORDER BY id", {"f": current["id"]})
    items = [
        Fact(
            fact_id=r["id"],
            name=r["name"],
            subject=r["subject"],
            scope=r["scope"],
            value_decimal=None if r["value_decimal"] is None else str(r["value_decimal"]),
            unit=r["unit"],
            statement=r["statement"],
            confirmation=r["confirmation"],
            evidence_ids=r["evidence_ids_json"],
        )
        for r in rows
    ]
    return FactList(fact_set_id=current["id"], items=items)


def add_fact(conn: Connection, store: ObjectStore, actor: Actor, project_id: str, req: FactRequest, request_id: str) -> FactSetResult:
    """追加一条经人工录入的事实：生成新的事实集（带上之前的全部条目），旧事实集保持不变。"""
    require_project(conn, actor, project_id)
    found = evidence.evidence_for_ids(conn, project_id, req.evidence_ids)
    if len(found) != len(set(req.evidence_ids)):
        raise Unprocessable("evidence_not_in_project", "引用了不属于本项目的证据")
    # 锁项目行：事实集是“读最新 → 带上旧条目 → 写新集”，并发录入不串行就会互相覆盖、丢事实
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})
    previous = db.one(conn, "SELECT id FROM fact_sets WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    carried = db.all_(conn, "SELECT * FROM fact_items WHERE fact_set_id=:f", {"f": previous["id"]}) if previous else []
    set_id = _new_fact_set(conn, store, project_id, previous["id"] if previous else None, carried, {"added": req.model_dump()})
    fact_id = new_id("fai")
    db.run(
        conn,
        """INSERT INTO fact_items(id,project_id,fact_set_id,name,value_decimal,unit,subject,scope,confirmation,evidence_ids_json,statement)
           VALUES (:i,:p,:f,:n,CAST(:v AS numeric),:u,:s,:sc,'confirmed',CAST(:e AS jsonb),:st)""",
        {
            "i": fact_id,
            "p": project_id,
            "f": set_id,
            "n": req.name,
            "v": req.value_decimal,
            "u": req.unit,
            "s": req.subject,
            "sc": req.scope,
            "e": json.dumps(list(dict.fromkeys(req.evidence_ids))),
            "st": req.statement,
        },
    )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="fact.add",
        object_kind="fact",
        object_id=fact_id,
        request_id=request_id,
        details={"fact_set_id": set_id},
    )
    return FactSetResult(fact_set_id=set_id, fact_id=fact_id, item_count=len(carried) + 1)


def _new_fact_set(
    conn: Connection, store: ObjectStore, project_id: str, previous_id: str | None, carried: list[db.Row], change: dict[str, object]
) -> str:
    """写入新的事实集（含产物）并带上 ``carried`` 条目（新 ID）；返回新事实集 ID。调用方须已锁项目行。"""
    set_id = new_id("fct")
    now = utcnow()
    payload = canonical_json({"fact_set_id": set_id, "project_id": project_id, "previous": previous_id, **change}).encode()
    art_id = new_id("art")
    store.put(artifact_key(art_id), payload, "application/json")
    db.run(
        conn,
        """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
                    VALUES (:i,:sha,:k,:n,'application/json',:cv,:now,'committed')""",
        {"i": art_id, "sha": sha256_hex(payload), "k": artifact_key(art_id), "n": len(payload), "cv": CONTRACT_VERSION, "now": now},
    )
    db.run(
        conn,
        "INSERT INTO fact_sets(id,project_id,artifact_id,created_at) VALUES (:i,:p,:a,:now)",
        {"i": set_id, "p": project_id, "a": art_id, "now": now},
    )
    for item in carried:
        db.run(
            conn,
            """INSERT INTO fact_items(id,project_id,fact_set_id,name,value_decimal,unit,subject,scope,confirmation,evidence_ids_json,statement)
               VALUES (:i,:p,:f,:n,:v,:u,:s,:sc,:c,CAST(:e AS jsonb),:st)""",
            {
                "i": new_id("fai"),
                "p": project_id,
                "f": set_id,
                "n": item["name"],
                "v": item["value_decimal"],
                "u": item["unit"],
                "s": item["subject"],
                "sc": item["scope"],
                "c": item["confirmation"],
                "e": json.dumps(item["evidence_ids_json"]),
                "st": item["statement"],
            },
        )
    return set_id


def withdraw_fact(
    conn: Connection, store: ObjectStore, actor: Actor, project_id: str, fact_id: str, req: FactWithdrawRequest, request_id: str
) -> FactSetResult:
    """撤回最新事实集中的一条事实：生成不含它的新事实集（旧集不变）；理由与被撤回的事实内容写入审计与新集产物。"""
    require_project(conn, actor, project_id)
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})
    previous = db.one(conn, "SELECT id FROM fact_sets WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    target = db.one(conn, "SELECT * FROM fact_items WHERE id=:i AND project_id=:p", {"i": fact_id, "p": project_id})
    if target is None:
        raise NotFound("fact_not_found", "事实不存在")
    if previous is None or target["fact_set_id"] != previous["id"]:
        raise Conflict("fact_not_current", "该事实不在最新事实集中（可能已被撤回，或事实集已有新版本），请刷新后重试", fact_id=fact_id)
    items = db.all_(conn, "SELECT * FROM fact_items WHERE fact_set_id=:f ORDER BY id", {"f": previous["id"]})
    carried = [i for i in items if i["id"] != fact_id]
    withdrawn = {
        "fact_id": fact_id,
        "name": target["name"],
        "subject": target["subject"],
        "scope": target["scope"],
        "value_decimal": None if target["value_decimal"] is None else str(target["value_decimal"]),
        "unit": target["unit"],
        "statement": target["statement"],
        "evidence_ids": target["evidence_ids_json"],
    }
    set_id = _new_fact_set(conn, store, project_id, previous["id"], carried, {"withdrawn": withdrawn, "reason": req.reason})
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="fact.withdraw",
        object_kind="fact",
        object_id=fact_id,
        request_id=request_id,
        details={"fact_set_id": set_id, "previous_fact_set_id": previous["id"], "reason": req.reason, "statement": target["statement"]},
    )
    return FactSetResult(fact_set_id=set_id, fact_id=fact_id, item_count=len(carried))
