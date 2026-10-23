"""Read exact selected records in one caller-owned snapshot; never choose a latest result."""

from uuid import UUID

from packages.contracts import package_retrospectives_api as contract
from packages.domain import bid_package_repository as packages
from packages.domain import bid_package_review_decision_repository as decisions
from packages.domain import bid_package_review_run_repository as runs
from packages.domain import bid_package_submission_repository as submissions
from packages.domain import package_review_comparison
from packages.domain.bid_package_service import view as package_view
from packages.domain.runtime import DomainError, clean, fetch, now, sha
from packages.metrics import results
from packages.rag.indexing import original_source_id, parse_source_id
from packages.research import outcomes, package_outcomes
from packages.retrospectives.policy import FLAGS, fail, packet, selection


def _gap(code, message):
    return {"code": code, "message": message}


def _members(selected, versions, roots):
    if selected is None:
        return
    for member in selected["manifest"]["members"]:
        identity = member["document_version_id"]
        versions.add(identity)
        roots.add(str(original_source_id(UUID(identity))))
        if member["parse"]["status"] == "frozen":
            roots.add(str(parse_source_id(UUID(member["parse"]["parse_run_id"]))))


def _outcome(c, bid, submission, identity, versions, roots):
    if identity is None:
        return None
    row = fetch(c, "SELECT * FROM design.outcomes WHERE bid_id=%s AND id=%s", (bid, identity))
    if str(row["submission_id"]) != submission["id"]:
        fail("OUTCOME_SUBMISSION_MISMATCH", "所选官方成绩不属于这条确切实交记录")
    value = outcomes.outcome_view(c, row)
    decision = c.execute(
        "SELECT h.decision_id FROM design.decision_heads h WHERE h.bid_id=%s AND h.object_kind='outcome' AND h.object_id=%s",
        (bid, identity),
    ).fetchone()
    head = c.execute(
        "SELECT outcome_id FROM design.outcome_heads WHERE bid_id=%s AND submission_id=%s",
        (bid, submission["id"]),
    ).fetchone()
    details = value["verification_details"]
    request = details.get("request", {}) if isinstance(details, dict) else {}
    refs = request.get("evidence_refs", [])
    versions.add(value["source_version_id"])
    roots.add(str(original_source_id(UUID(value["source_version_id"]))))
    _reference_roots(c, bid, refs, roots)
    native = fetch(c, "SELECT * FROM design.submission_records WHERE id=%s", (submission["id"],))
    reasons = package_outcomes.current_reasons(c, native, row, details)
    return {
        **{
            key: value[key]
            for key in (
                "id",
                "submission_id",
                "score_kind",
                "value",
                "maximum",
                "source_version_id",
                "known_at",
                "supersedes_id",
                "verification",
                "verification_revision",
            )
        },
        "verification_id": str(decision["decision_id"]) if decision else None,
        "verification_details_digest": sha(details) if details else None,
        "aggregation": request.get("aggregation"),
        "published_at": request.get("published_at"),
        "evidence_refs": refs,
        "current": bool(head and str(head["outcome_id"]) == identity),
        "association_reasons": reasons,
    }


def _reference_roots(c, bid, refs, roots):
    for ref in refs:
        row = results._reference(c, bid, ref)
        roots.add(str(parse_source_id(UUID(str(row["parse_id"])))))


def _business(c, bid, submission, identity, versions, roots):
    if identity is None:
        return None
    value = results.get(c, identity)
    if value["bid_id"] != bid or value["submission_id"] != submission["id"]:
        fail("RESULT_SUBMISSION_MISMATCH", "所选入围或中标结果不属于这条确切实交记录")
    if value["source_version_id"]:
        versions.add(value["source_version_id"])
        roots.add(str(original_source_id(UUID(value["source_version_id"]))))
    refs = value["evidence_refs"]
    if value["verification_details"]:
        refs = [*refs, *value["verification_details"].get("evidence_refs", [])]
    _reference_roots(c, bid, refs, roots)
    return {key: item for key, item in value.items() if key not in {"usable", "unusable_reasons"}}


def _side(c, bid, identity, saved_identity, versions, roots):
    row = fetch(c, runs.SELECT + " WHERE r.bid_id=%s AND r.id=%s", (bid, identity))
    run = runs.view(row)
    if run["operation"]["state"] != "succeeded" or run["result"] is None:
        fail("RUN_UNFINISHED", "请选择已完成并发布原结果的核查运行")
    revision = packages.load_revision(c, bid, run["scope"]["revision_id"])
    selected = package_view(c, revision)
    if selected["identity"] != saved_identity:
        fail("RUN_IDENTITY_MISMATCH", "两轮核查必须与实交包的原项目、标段、轮次和投标主体身份一致")
    _members(selected, versions, roots)
    inventory = fetch(
        c,
        "SELECT authority_revision_id FROM design.bid_package_requirement_inventories WHERE bid_id=%s AND id=%s",
        (bid, run["scope"]["inventory_id"]),
    )
    authority = package_view(
        c, packages.load_revision(c, bid, str(inventory["authority_revision_id"]))
    )
    _members(authority, versions, roots)
    return {
        "run": run,
        "input": {"manifest": row["input_manifest"], "digest": row["input_digest"]},
        "human": decisions.current(c, run),
    }


def _comparison(c, bid, chosen, submission, versions, roots):
    if chosen["baseline_run_id"] is None:
        return None
    left = _side(c, bid, chosen["baseline_run_id"], submission["identity"], versions, roots)
    right = _side(c, bid, chosen["submitted_run_id"], submission["identity"], versions, roots)
    target = submission["package_binding"]["manifest"]["subject"]
    if any(right["run"]["scope"][key] != target[key] for key in ("package_id", "revision_id")):
        fail("RUN_SUBMISSION_MISMATCH", "实交侧核查必须属于所选实际提交包的确切修订")
    return package_review_comparison.compare(bid, left, right)


def _sources(c, bid, versions, roots):
    if len(versions) > contract.LIMITS["documents"]:
        fail("CAPACITY_EXCEEDED", "复盘原件超过容量，未省略来源", 413)
    docs = clean(
        c.execute(
            "SELECT d.id,d.original_name,b.digest,b.byte_size FROM design.document_versions d JOIN design.blobs b ON b.id=d.blob_id WHERE d.bid_id=%s AND d.id=ANY(%s::uuid[]) ORDER BY d.id",
            (bid, sorted(versions)),
        ).fetchall()
    )
    if len(docs) != len(versions):
        fail("SOURCE_MISMATCH", "复盘来源原件缺失或属于其他项目")
    rows = clean(
        c.execute(
            "SELECT a.source_id,a.ancestor_id,n.document_version_id,d.bid_id AS document_bid_id,n.kind,n.policy_class,n.known_at,n.digest,h.revision,h.status,h.valid_from,h.valid_until "
            "FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id LEFT JOIN design.document_versions d ON d.id=n.document_version_id "
            "WHERE a.source_id=ANY(%s::uuid[]) ORDER BY a.source_id,a.ancestor_id LIMIT %s",
            (sorted(roots), contract.LIMITS["source_rows"] + 1),
        ).fetchall()
    )
    if len(rows) > contract.LIMITS["source_rows"]:
        fail("CAPACITY_EXCEEDED", "复盘来源祖先超过容量，未截断来源", 413)
    issues = []
    if {r["source_id"] for r in rows if r["source_id"] == r["ancestor_id"]} != roots:
        issues.append(
            _gap("source_closure_missing", "部分原件或确切解析没有完整来源图，知识候选暂不能建立。")
        )
    from packages.knowledge.content import instant

    at = now()
    if any(
        r["status"] != "published"
        or r["valid_from"] is None
        or instant(r["valid_from"]) > at
        or instant(r["known_at"]) > at
        or r["valid_until"] is not None
        and instant(r["valid_until"]) <= at
        for r in rows
    ):
        issues.append(
            _gap(
                "source_unavailable", "部分来源未生效、到期或撤回；历史依据保留，不能新建知识候选。"
            )
        )
    if any(r["document_bid_id"] not in (None, bid) for r in rows):
        issues.append(_gap("foreign_source", "来源祖先涉及其他项目，需核对后重新建立复盘。"))
    hashes = {d["id"]: d["digest"] for d in docs}
    if any(
        r["source_id"] == r["ancestor_id"]
        and r["document_version_id"] in hashes
        and r["digest"] != hashes[r["document_version_id"]]
        for r in rows
    ):
        fail("SOURCE_CORRUPT", "原件来源摘要与确切文件不一致", 500)
    return docs, rows, issues


def observe(c, bid, body):
    chosen = selection(body)
    saved = submissions.load(c, bid, chosen["submission_id"])
    frozen = saved["package_binding"]["manifest"]
    versions, roots = (
        {saved["evidence_ref"]},
        {str(original_source_id(UUID(saved["evidence_ref"])))},
    )
    for role in ("target", "authority"):
        _members(frozen["selection"][role], versions, roots)
    outcome = _outcome(c, bid, saved, chosen["outcome_id"], versions, roots)
    business = _business(c, bid, saved, chosen["business_result_id"], versions, roots)
    comparison = _comparison(c, bid, chosen, saved, versions, roots)
    documents, source_snapshot, gaps = _sources(c, bid, versions, roots)
    for kind, label in (("outcome", "官方成绩"), ("business_result", "业务阶段结果")):
        if chosen[kind + "_id"] is None:
            gaps.append(
                _gap(kind + "_missing", label + "待补：" + chosen[kind + "_missing_reason"])
            )
    if comparison is None:
        gaps.append(_gap("reviews_missing", "两轮核查待补：" + chosen["reviews_missing_reason"]))
    else:
        gaps.append(
            _gap(
                "risk_resolution_unproven",
                "两轮差异和人工整改意见不证明风险已解决；整包风险闭环资格仍待独立复检依据。",
            )
        )
    if outcome:
        gaps.append(
            _gap(
                "item_deductions_unavailable",
                "所选成绩没有逐项扣分数据，不能从技术总分或综合总分推断具体扣分原因。",
            )
        )
        if outcome["association_reasons"]:
            gaps.append(
                _gap(
                    "outcome_association_unproven",
                    "所选官方成绩的当前核验或实交关联尚未全部成立；原记录状态已保留。",
                )
            )
    if business and (
        not business["current"]
        or business["verification"] != "verified"
        or business["source_type"] != "official"
    ):
        gaps.append(
            _gap(
                "business_result_unverified",
                "所选业务阶段尚未取得完整有效核验，不能据此推断入围或中标。",
            )
        )
    if not saved["current"]:
        gaps.append(
            _gap("historical_submission", "所选为历史实交记录；复盘仍固定原包，不替换为当前提交。")
        )
    gaps.append(
        _gap(
            "formal_sample_unavailable",
            "复盘不会创建正式研究样本，也不授予模型或评分资格；需另走研究准入。",
        )
    )
    subject = frozen["subject"]
    summary = {
        **{
            key: saved[key]
            for key in ("id", "kind", "submitted_at", "recorded_at", "current", "identity")
        },
        **{key: subject[key] for key in ("package_id", "revision_id", "package_digest")},
        "binding_digest": saved["package_binding"]["digest"],
        "registration_risk_digest": sha(saved["open_risk_snapshot"]),
        "registration_assessed_at": frozen["assessed_at"],
        "risk_resolution_assessed": False,
    }
    return packet(
        {
            "version": "package-retrospective-preview/1",
            "bid_id": bid,
            "selection": chosen,
            "submission": summary,
            "outcome": outcome,
            "business_result": business,
            "comparison": comparison,
            "source_ids": sorted(roots),
            "source_snapshot": source_snapshot,
            "documents": documents,
            "gaps": gaps,
            "timing": "post_outcome_retrospective",
            **FLAGS,
        },
        "PackageRetrospectivePreview",
    )


def current(c, frozen):
    old = frozen["manifest"]["preview"]
    try:
        fresh = observe(c, frozen["manifest"]["bid_id"], old["manifest"]["selection"])
    except DomainError as error:
        if error.status >= 500:
            raise
        return {
            "unchanged": False,
            "issues": [_gap(error.code, "复盘所选的原始依据当前无法完整还原；历史记录仍保留。")],
        }
    issues = [
        g
        for g in fresh["manifest"]["gaps"]
        if g["code"] in {"source_closure_missing", "source_unavailable", "foreign_source"}
    ]
    if fresh["digest"] != old["digest"]:
        issues.insert(
            0,
            _gap(
                "selected_records_changed",
                "所选实交、官方核验、人工处置或来源状态已变化，请重新预览并建立新复盘。",
            ),
        )
    return {"unchanged": fresh["digest"] == old["digest"] and not issues, "issues": issues}
