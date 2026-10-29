"""Freeze an explicit package technical range without claiming scoring completeness.

This version records exact text/table/visual evidence that was actually stored. No
reader here can prove exhaustive visual understanding, or that the user selected
all applicable technical requirements. Those gaps remain visible and immutable.
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from packages.contracts import package_technical_scope_api as contract
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import DomainError, sha
from packages.rag.indexing import original_source_id, parse_source_id

VERSION = "package-technical-scope-policy/1"
LIMITS = contract.LIMITS
FLAGS = dict.fromkeys(contract.FLAGS, False)
TIMING = {
    "purpose": "current_prebid",
    "historical_as_of": None,
    "submitted_at": None,
    "label_known_at": None,
    "training_frozen_at": None,
    "submission_split_at": None,
    "label_available_as_of": None,
    "historical_qualification": "not_established",
}
ROOT = Path(__file__).resolve().parents[2]
SOURCES = contract.METHOD_SOURCES


def failure(code, message, status=409):
    raise DomainError("PACKAGE_TECHNICAL_SCOPE_" + code, message, status)


def bounded(value, limit):
    try:
        pending, count = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if depth > 80 or count > 2000000:
                failure("TOO_LARGE", "技术范围超过完整冻结容量，未截断内容", 413)
            if isinstance(item, str):
                if "\x00" in item:
                    raise ValueError
            elif isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError
                pending.extend((child, depth + 1) for child in [*item.keys(), *item.values()])
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
            elif item is not None and type(item) not in {int, bool}:
                raise ValueError
        raw = canonical(value)
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        failure("INVALID", "技术范围必须是有界、有限、准确的JSON记录", 422)
    if len(raw) > limit:
        failure("TOO_LARGE", "技术范围超过完整冻结容量，未截断内容", 413)
    return raw


def policy_identity():
    value = {
        "version": VERSION,
        "limits": dict(LIMITS),
        "sources": {name: sha((ROOT / name).read_bytes()) for name in SOURCES},
    }
    return value | {"digest": digest(value)}


def gap(code, subject, message):
    value = {"code": code, "subject": subject, "message": message}
    return {"id": digest(value), **value}


def _check_view(value, name):
    contract.validate(name, value)
    if digest(value["manifest"]) != value["digest"]:
        failure("BINDING_INVALID", "冻结对象内容与其准确摘要不一致")


def check_snapshot(snapshot):
    """Pure identity/geometry validation of an untruncated server observation."""
    bounded(snapshot, LIMITS["snapshot_bytes"])
    target, authority, inventory = (snapshot[key] for key in ("target", "authority", "inventory"))
    _check_view(target, "BidPackageStoredView")
    _check_view(authority, "BidPackageStoredView")
    _check_view(inventory, "PackageRequirementInventoryView")
    tm, am, im = (value["manifest"] for value in (target, authority, inventory))
    if (
        tm["kind"] != "bid"
        or am["kind"] != "authority"
        or tm["scope"] != am["scope"]
        or target["identity"] != authority["identity"]
        or im["bid_id"] != tm["scope"]["bid_id"]
        or im["package_id"] != tm["package_id"]
        or im["target_revision_id"] != tm["revision_id"]
        or im["package_digest"] != target["digest"]
        or im["authority_revision_id"] != am["revision_id"]
        or im["authority_digest"] != authority["digest"]
        or im["identity_digest"] != target["identity"]["digest"]
    ):
        failure("BINDING_INVALID", "本方包、权威包、清单或项目身份不一致")
    if any(len(value["manifest"]["members"]) > LIMITS["members"] for value in (target, authority)):
        failure("TOO_LARGE", "成员超过完整技术范围容量", 413)
    members = {
        (role, member["member_id"]): member
        for role, value in (("target", target), ("authority", authority))
        for member in value["manifest"]["members"]
    }
    documents = snapshot["documents"]
    if len(documents) != len(members) or {
        (d["package_role"], d["member_id"]) for d in documents
    } != set(members):
        failure("DOCUMENT_SET_INVALID", "技术范围必须保留确切包的全部成员，不能省略未选分册")
    total, page_total = 0, 0
    for document in documents:
        contract_schema = {
            "components": {
                "schemas": {
                    **contract.PACKAGE_SCHEMAS,
                    **contract.INVENTORY_SCHEMAS,
                    **contract.SCHEMAS,
                }
            },
            **contract.DOCUMENT,
        }
        from jsonschema import Draft202012Validator, FormatChecker

        if not Draft202012Validator(contract_schema, format_checker=FormatChecker()).is_valid(
            document
        ):
            failure("DOCUMENT_INVALID", "原页证据未满足准确文档协议")
        member = members[(document["package_role"], document["member_id"])]
        if any(
            document[key] != member[key]
            for key in ("document_version_id", "file_digest", "parse", "page_count")
        ):
            failure("DOCUMENT_INVALID", "证据必须属于所选成员的原件和冻结解析")
        if member["parse"]["status"] == "not_frozen":
            if document["pages"] or document["blocks"]:
                failure("DOCUMENT_INVALID", "未冻结解析不能借用最新解析或其他文件证据")
            continue
        page_numbers = [page["physical_page"] for page in document["pages"]]
        page_total += len(page_numbers)
        if len(page_numbers) != member["page_count"] or any(
            page != index for index, page in enumerate(page_numbers, 1)
        ):
            failure("PAGE_SET_INVALID", "冻结解析必须包含全部准确物理页，不能跳页")
        seen, ordinals = set(), set()
        for block in document["blocks"]:
            if (
                block["id"] in seen
                or (block["physical_page"], block["ordinal"]) in ordinals
                or block["physical_page"] not in page_numbers
                or sha(block["text_content"].encode()) != block["digest"]
            ):
                failure("EVIDENCE_INVALID", "原文证据ID、物理页、顺序或字节摘要不一致")
            seen.add(block["id"])
            ordinals.add((block["physical_page"], block["ordinal"]))
        total += len(document["blocks"])
    if (
        total > LIMITS["blocks"]
        or page_total > LIMITS["pages"]
        or len(snapshot["source_snapshot"]) > LIMITS["source_rows"]
    ):
        failure("TOO_LARGE", "证据或来源超过完整冻结容量，未截断", 413)
    parts = [part for member in tm["members"] for part in member["parts"]]
    scoring = [row for row in im["requirements"] if row["rule_snapshot"]["kind"] == "scoring"]
    if len(parts) > LIMITS["parts"] or len(scoring) > LIMITS["rules"]:
        failure("TOO_LARGE", "完整章节或评分项超过支持容量，不能以分页缺行构造分母", 413)
    if len({p["part_id"] for p in parts}) != len(parts) or len(
        {r["rule_id"] for r in scoring}
    ) != len(scoring):
        failure("BINDING_INVALID", "章节或评分项身份重复")
    for row in scoring:
        if (
            digest(row["rule_snapshot"]) != row["rule_digest"]
            or digest(row["requirement"]) != row["requirement_digest"]
        ):
            failure("BINDING_INVALID", "清单内原规则或范围摘要不一致")
    return scoring


def context_digest(snapshot):
    return digest(snapshot)


def required_roots(documents):
    """Canonical original and exact-parse identities, never latest parse metadata."""
    result = {}
    for document in documents:
        identity = (document["document_version_id"], document["file_digest"])
        result[str(original_source_id(UUID(identity[0])))] = identity
        if document["parse"]["status"] == "frozen":
            result[str(parse_source_id(UUID(document["parse"]["parse_run_id"])))] = identity
    return result


def prepare(snapshot, request, *, method=None):
    bounded(request, LIMITS["request_bytes"])
    contract.validate("PackageTechnicalScopeRequest", request)
    scoring = check_snapshot(snapshot)
    current_method = policy_identity()
    if method is not None and method != current_method:
        failure("METHOD_CHANGED", "方法声明不等于当前实际实现，请重新取得预览")
    observed = snapshot["observation"]
    if (
        observed.get("current_submission_head") is not None
        or (observed.get("profile") or {}).get("phase") == "submitted"
    ):
        failure("AFTER_SUBMISSION", "已有实际提交的项目不能登记为当前事前范围")
    target, authority, inventory = (snapshot[key] for key in ("target", "authority", "inventory"))
    tm, am, im = (value["manifest"] for value in (target, authority, inventory))
    if any(
        request[key] != expected
        for key, expected in {
            "package_digest": target["digest"],
            "authority_revision_id": am["revision_id"],
            "authority_digest": authority["digest"],
            "inventory_id": im["id"],
            "inventory_digest": inventory["digest"],
        }.items()
    ):
        failure("BASIS_CHANGED", "请求引用的准确包、权威版本或清单已变化")
    selected = set(request["technical_part_ids"])
    all_parts = {part["part_id"] for member in tm["members"] for part in member["parts"]}
    if not selected <= all_parts:
        failure("PART_NOT_FOUND", "技术章节必须来自所选确切包，不能引用其他修订")
    supplied = {row["rule_id"]: row for row in request["rule_scopes"]}
    if len(supplied) != len(request["rule_scopes"]) or set(supplied) != {
        row["rule_id"] for row in scoring
    }:
        failure("RULE_SET_INCOMPLETE", "请逐项保留全部已识别评分条款的纳入、排除或待分类状态")
    reasons = [
        gap(
            "INVENTORY_COMPLETENESS_UNPROVEN",
            im["id"],
            "当前规则清单没有完整性实测权威；技术范围选择不会消除漏提风险。",
        ),
        gap(
            "VISUAL_COMPLETENESS_UNPROVEN",
            None,
            "当前证据只记录实际解析内容，没有全图表完整阅读的资格证明。",
        ),
        gap(
            "REQUIRED_RANGE_UNPROVEN",
            None,
            "用户声明的适用章节不能独立证明已覆盖全部必要技术范围。",
        ),
        gap(
            "MODEL_EXECUTION_NOT_OPEN",
            None,
            "本记录仅冻结范围，不创建评分任务、三次判断或训练样本。",
        ),
    ]
    parts = []
    by_member = {
        (document["package_role"], document["member_id"]): document
        for document in snapshot["documents"]
    }
    for member in tm["members"]:
        document = by_member[("target", member["member_id"])]
        if not member["parts"]:
            reasons.append(
                gap(
                    "MEMBER_RANGE_UNDECLARED",
                    member["member_id"],
                    "该包成员没有明确章节范围，仍保留在范围缺口中。",
                )
            )
        for part in member["parts"]:
            key = part["part_id"]
            pages = [
                p["physical_page"]
                for p in document["pages"]
                if part["first_page"] <= p["physical_page"] <= part["last_page"]
            ]
            blocks = [
                b
                for b in document["blocks"]
                if part["first_page"] <= b["physical_page"] <= part["last_page"]
            ]
            parts.append(
                {
                    "member_id": member["member_id"],
                    "document_version_id": member["document_version_id"],
                    "file_digest": member["file_digest"],
                    "part": deepcopy(part),
                    "selected": key in selected,
                    "read_physical_pages": pages,
                    "block_ids": [b["id"] for b in blocks],
                    "text_evidence_present": any(
                        b["kind"] == "text" and b["text_content"].strip() for b in blocks
                    ),
                    "visual_coverage": "unproven",
                }
            )
            if key not in selected:
                reasons.append(
                    gap(
                        "PACKAGE_PART_NOT_SELECTED",
                        key,
                        "该包章节未纳入技术范围；是否适用仍需独立有据核实，未从包中删除。",
                    )
                )
            elif len(pages) != part["last_page"] - part["first_page"] + 1:
                reasons.append(
                    gap(
                        "EXACT_PARSE_UNAVAILABLE",
                        key,
                        "所选章节尚无全部准确物理页的冻结解析，不能借用其他解析。",
                    )
                )
            elif not blocks:
                reasons.append(
                    gap(
                        "EMPTY_EVIDENCE_RANGE",
                        key,
                        "已声明物理页没有可核对的实际内容证据，不能当作无需阅读。",
                    )
                )
            if any(
                p["quality"] != "usable" or p["gaps"]
                for p in document["pages"]
                if p["physical_page"] in pages
            ):
                reasons.append(
                    gap("PARSE_PAGE_GAP", key, "该章节原解析含不可用或部分读取页，缺口保持原状态。")
                )
    rule_rows = []
    for binding in scoring:
        choice = supplied[binding["rule_id"]]
        if choice["rule_digest"] != binding["rule_digest"]:
            failure("RULE_CHANGED", "评分条款与所选清单的原版本不一致")
        included = choice["selection"] == "include"
        if (included and (not choice["part_ids"] or not set(choice["part_ids"]) <= selected)) or (
            not included and choice["part_ids"]
        ):
            failure(
                "RULE_RANGE_INVALID", "纳入项须选择完整技术章节；排除或待分类项不能附带执行范围"
            )
        if included and binding["rule_snapshot"]["provenance_status"] != "effective":
            failure("RULE_INACTIVE", "人工不采用或待重新核验的规则不能被恢复为有效评分项")
        evidence = []
        for member in am["members"]:
            document = by_member[("authority", member["member_id"])]
            for block in document["blocks"]:
                if block["id"] not in binding["rule_snapshot"]["evidence_ids"]:
                    continue
                part_ids = [
                    part["part_id"]
                    for part in member["parts"]
                    if part["first_page"] <= block["physical_page"] <= part["last_page"]
                ]
                if part_ids:
                    evidence.append(
                        {
                            "member_id": member["member_id"],
                            "document_version_id": member["document_version_id"],
                            "file_digest": member["file_digest"],
                            "parse_run_id": member["parse"]["parse_run_id"],
                            "physical_page": block["physical_page"],
                            "evidence_id": block["id"],
                            "evidence_digest": block["digest"],
                            "text_content": block["text_content"],
                            "part_ids": part_ids,
                        }
                    )
        source_complete = bool(binding["rule_snapshot"]["evidence_ids"]) and {
            e["evidence_id"] for e in evidence
        } == set(binding["rule_snapshot"]["evidence_ids"])
        if not source_complete:
            if choice["selection"] in {"include", "exclude"}:
                failure(
                    "RULE_SOURCE_UNPROVEN",
                    "没有确切权威原页依据的评分条款只能保留待分类，不能有据纳入或排除",
                )
            reasons.append(
                gap(
                    "RULE_SOURCE_UNPROVEN",
                    binding["rule_id"],
                    "评分条款缺少所选权威版本完整逐字原页依据。",
                )
            )
        declared = binding["requirement"]["target_part_ids"]
        if included and not set(declared) <= set(choice["part_ids"]):
            reasons.append(
                gap(
                    "DECLARED_RULE_RANGE_OMITTED",
                    binding["rule_id"],
                    "该条款既有检查计划声明了更多章节，本次遗漏的范围仍是缺口。",
                )
            )
        if choice["selection"] != "include":
            reasons.append(
                gap(
                    "RULE_EXCLUDED_BY_DECLARATION"
                    if choice["selection"] == "exclude"
                    else "RULE_NOT_CLASSIFIED",
                    binding["rule_id"],
                    "本条款未进入技术判断范围；人工选择与理由保留，不会删除潜在适用义务。",
                )
            )
        rule_rows.append(
            {
                **deepcopy(choice),
                "rule_snapshot": deepcopy(binding["rule_snapshot"]),
                "requirement_digest": binding["requirement_digest"],
                "declared_target_part_ids": list(declared),
                "source_evidence": evidence,
            }
        )
    if not scoring:
        reasons.append(
            gap(
                "SCORING_RULES_UNKNOWN",
                im["id"],
                "未识别评分项不等于不存在评分要求，评分分母未知。",
            )
        )
    reasons.extend(deepcopy(snapshot["blocking_reasons"]))
    manifest = {
        "version": "package-technical-scope-preview/1",
        "scope": {
            "bid_id": im["bid_id"],
            "package_id": tm["package_id"],
            "revision_id": tm["revision_id"],
            "inventory_id": im["id"],
        },
        "basis": {
            "package_digest": target["digest"],
            "authority_revision_id": am["revision_id"],
            "authority_digest": authority["digest"],
            "inventory_digest": inventory["digest"],
            "rule_set_id": im["rule_set_id"],
            "rule_set_digest": im["rule_set_digest"],
            "identity_digest": im["identity_digest"],
        },
        "method": deepcopy(current_method),
        "request": deepcopy(request),
        "request_digest": digest(request),
        "context_digest": context_digest(snapshot),
        "parts": parts,
        "rules": rule_rows,
        "documents": deepcopy(snapshot["documents"]),
        "source_snapshot": deepcopy(snapshot["source_snapshot"]),
        "coverage": {
            "state": "partial"
            if any(p["selected"] and p["block_ids"] for p in parts)
            else "unknown",
            "all_part_count": len(parts),
            "selected_part_count": len(selected),
            "all_scoring_rule_count": len(scoring),
            "included_rule_count": sum(r["selection"] == "include" for r in rule_rows),
            "frozen_parse_member_count": sum(
                d["parse"]["status"] == "frozen"
                for d in snapshot["documents"]
                if d["package_role"] == "target"
            ),
            "gaps": list({r["id"]: r for r in reasons}.values()),
            "visual_coverage": "unproven",
            "required_range_completeness": "unproven",
        },
        "timing": dict(TIMING),
        "original_bytes_verified": False,
        **FLAGS,
    }
    bounded(manifest, LIMITS["snapshot_bytes"])
    result = {"manifest": manifest, "digest": digest(manifest)}
    contract.validate("PackageTechnicalScopePreview", result)
    return result


def freeze(preview, *, identity, actor, command, frozen_at, verified_at, originals):
    contract.validate("PackageTechnicalScopePreview", preview)
    if digest(preview["manifest"]) != preview["digest"] or not originals:
        failure("PREVIEW_CHANGED", "预览摘要或实际原件核验记录缺失")
    frozen, verified = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (frozen_at, verified_at)
    )
    if (
        frozen.tzinfo is None
        or verified.tzinfo is None
        or verified > frozen
        or frozen > datetime.now(timezone.utc)
    ):
        failure("TIME_INVALID", "登记与实际核验时间关系不成立")
    files = sorted(
        (
            {key: row[key] for key in ("document_version_id", "digest", "byte_size")}
            for row in originals
        ),
        key=lambda row: row["document_version_id"],
    )
    if len({row["document_version_id"] for row in files}) != len(files):
        failure("ORIGINAL_SET_INVALID", "原件核验集合不能重复")
    by_id = {row["document_version_id"]: row for row in files}
    sources = preview["manifest"]["source_snapshot"]
    roots = required_roots(preview["manifest"]["documents"])
    self_rows = {row["source_id"]: row for row in sources if row["source_id"] == row["ancestor_id"]}
    if {row["source_id"] for row in sources} != set(roots) or set(self_rows) != set(roots):
        failure("SOURCE_CLOSURE_UNPROVEN", "原件和确切解析必须都有独立规范来源根及自身闭包边")
    for key, expected in roots.items():
        if (self_rows[key]["document_version_id"], self_rows[key]["digest"]) != expected:
            failure("SOURCE_CLOSURE_UNPROVEN", "规范来源根被错误绑定到另一原件")
    source_versions = {row["document_version_id"] for row in sources}
    if set(by_id) != source_versions:
        failure("ORIGINAL_SET_INVALID", "实际原件核验必须覆盖全部直接来源和祖先原件，不能增减集合")
    if sum(row["byte_size"] for row in files) > LIMITS["original_bytes"]:
        failure("TOO_LARGE", "完整原件核验超过支持容量，未截断来源", 413)
    for source in sources:
        if (
            by_id[source["document_version_id"]]["digest"] != source["digest"]
            or source["digest"] != source["original_digest"]
        ):
            failure("ORIGINAL_SET_INVALID", "祖先原件摘要没有与实际核验原件完整绑定")
        if (
            source.get("document_bid") != preview["manifest"]["scope"]["bid_id"]
            or source.get("kind") != "document"
            or source.get("policy_class") != "prebid_content"
            or source.get("status") != "published"
        ):
            failure("SOURCE_UNAVAILABLE", "全部直接来源和祖先必须是本项目可用于事前内容的真实原件")
        try:
            dates = {
                name: datetime.fromisoformat(source[name].replace("Z", "+00:00"))
                if source[name] is not None
                else None
                for name in ("known_at", "valid_from", "valid_until")
            }
            if any(value is not None and value.tzinfo is None for value in dates.values()):
                raise ValueError
            if dates["known_at"] is None or dates["valid_from"] is None:
                raise ValueError
            if (
                dates["known_at"] > frozen
                or dates["valid_from"] > frozen
                or (dates["valid_until"] is not None and dates["valid_until"] <= frozen)
            ):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            failure("SOURCE_UNAVAILABLE", "来源取得时点或有效窗口不支持该实际登记时刻")
    for document in preview["manifest"]["documents"]:
        if by_id.get(document["document_version_id"]) != {
            "document_version_id": document["document_version_id"],
            "digest": document["file_digest"],
            "byte_size": document["byte_size"],
        }:
            failure("ORIGINAL_SET_INVALID", "每个确切包成员必须对应实际原字节核验")
    manifest = {
        "version": "package-technical-scope/1",
        "id": str(identity),
        "actor_id": str(actor),
        "command_id": str(command),
        "frozen_at": frozen_at,
        "preview": deepcopy(preview),
        "original_verification": {
            "state": "verified_at_recording",
            "verified_at": verified_at,
            "files": files,
        },
        **FLAGS,
    }
    bounded(manifest, LIMITS["snapshot_bytes"])
    result = {"manifest": manifest, "digest": digest(manifest)}
    contract.validate("PackageTechnicalScopeView", result)
    return result
