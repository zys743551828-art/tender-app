"""Pure bounded human rule derivations over an exact frozen authority package.

This module never reads a database, original bytes, current material or a provider.
The coordinator proves those current identities separately. A human interpretation
cannot replace the original model receipt or certify semantic completeness.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import UUID

from packages.contracts import package_rule_corrections_api as contract
from packages.domain.review_identity import canonical, digest
from packages.domain.rule_sets import validate_addition
from packages.domain.runtime import ROOT, DomainError, clean, sha

V2 = "bid-package-requirements/2"
V3 = "bid-package-requirements/3"
BINDING = "frozen_extraction_plus_human_derivation"
SEMANTIC_KEYS = tuple(contract.SEMANTIC["properties"])
RULE_KEYS = set(SEMANTIC_KEYS) | {
    "id",
    "bid_id",
    "rule_set_id",
    "origin_kind",
    "manual_origin_rule_id",
}
POLICY_FILES = (
    "packages/domain/package_rule_corrections.py",
    "packages/domain/package_rule_correction_proof.py",
    "packages/contracts/package_rule_corrections_api.py",
    "packages/contracts/bid_package_requirements_api.py",
    "packages/contracts/schemas/protocol.schema.json",
    "packages/domain/rule_sets.py",
    "packages/domain/review_identity.py",
)


def require(condition, code, message, status=409):
    if not condition:
        raise DomainError("PACKAGE_RULE_CORRECTION_" + code, message, status)


def bounded(value, limit, label):
    try:
        raw = canonical(value)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as error:
        raise DomainError(
            "PACKAGE_RULE_CORRECTION_INVALID", "更正数据必须使用有界的规范JSON值", 422
        ) from error
    require(len(raw) <= limit, "CAPACITY_EXCEEDED", f"{label}超过本功能公开容量，未截断内容", 422)
    return raw


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def policy_identity():
    value = {
        "version": "package-rule-correction-policy/1",
        "limits": deepcopy(contract.LIMITS),
        "sources": {name: sha((ROOT / name).read_bytes()) for name in POLICY_FILES},
    }
    return {**value, "digest": digest(value)}


def semantic(rule):
    return {key: deepcopy(rule[key]) for key in SEMANTIC_KEYS}


def rule_state(rule):
    return {
        "effective": "active",
        "superseded": "inactive",
        "needs_revalidation": "needs_revalidation",
    }[rule["provenance_status"]]


def rule_counts(rules):
    return {
        "total": len(rules),
        **{
            state: sum(rule_state(rule) == state for rule in rules)
            for state in ("active", "inactive", "needs_revalidation")
        },
    }


def _rule(rule, bid, rule_set):
    require(
        type(rule) is dict
        and set(rule) == RULE_KEYS
        and _uuid(rule["id"])
        and rule["bid_id"] == bid
        and rule["rule_set_id"] == rule_set
        and contract.valid("PackageRuleCorrectionSemantic", semantic(rule)),
        "RULE_CORRUPT",
        "原规则快照的字段、类型或项目身份无法核验",
        500,
    )
    maximum = rule["max_points"]
    if maximum is not None:
        try:
            positive = Decimal(maximum).is_finite() and Decimal(maximum) > 0
        except (ValueError, TypeError, InvalidOperation):
            positive = False
        require(positive, "RULE_CORRUPT", "原规则分值不是精确正十进制值", 500)
    origin, manual = rule["origin_kind"], rule["manual_origin_rule_id"]
    require(
        origin == "model_extracted"
        and manual is None
        or origin == "human_added"
        and manual == rule["id"]
        or origin == "carried_human"
        and _uuid(manual),
        "RULE_CORRUPT",
        "原规则的模型或人工来源身份不一致",
        500,
    )


def verify_inventory_header(inventory):
    from packages.contracts.bid_package_requirements_api import valid

    require(
        type(inventory) is dict
        and set(inventory) == {"manifest", "digest"}
        and valid("PackageRequirementInventoryView", inventory)
        and digest(inventory["manifest"]) == inventory["digest"],
        "INVENTORY_CORRUPT",
        "原要求清单的不可变身份无法核验",
        500,
    )
    m = inventory["manifest"]
    require(
        m["version"] in {V2, V3},
        "EXACT_EXTRACTION_REQUIRED",
        "这份清单没有原整包抽取回执，请先完成准确范围的抽取",
        409,
    )
    require(
        len(m["requirements"]) <= contract.MAX_RULES,
        "CAPACITY_EXCEEDED",
        "要求条数超过人工派生支持容量",
        422,
    )
    ids = set()
    for row in m["requirements"]:
        r = row["rule_snapshot"]
        _rule(r, m["bid_id"], m["rule_set_id"])
        require(
            r["id"] == row["rule_id"] == row["requirement"]["requirement_id"]
            and row["rule_id"] not in ids
            and row["rule_digest"] == digest(r)
            and row["requirement_digest"] == digest(row["requirement"])
            and row["decision_id"]
            == (row["decision_snapshot"]["id"] if row["decision_snapshot"] else None),
            "INVENTORY_CORRUPT",
            "要求清单存在重复、漏绑或不一致规则快照",
            500,
        )
        ids.add(row["rule_id"])
    if m["version"] == V3:
        basis, head = m["extraction_basis"], m["human_derivation"]
        require(
            m["extraction_binding"] == BINDING
            and basis["inventory_id"] != m["id"]
            and basis["rule_set_id"] != m["rule_set_id"]
            and head["length"] <= contract.MAX_CHAIN,
            "INVENTORY_CORRUPT",
            "人工派生清单不得覆盖或冒充原模型抽取清单",
            500,
        )


def extraction_basis(inventory):
    verify_inventory_header(inventory)
    m = inventory["manifest"]
    if m["version"] == V3:
        return deepcopy(m["extraction_basis"])
    return {
        "inventory_id": m["id"],
        "inventory_digest": inventory["digest"],
        **{
            key: deepcopy(m[key])
            for key in contract.EXTRACTION_BASIS["properties"]
            if key not in {"inventory_id", "inventory_digest"}
        },
    }


def _authority(inventory, authority):
    m, am = inventory["manifest"], authority["manifest"]
    require(
        digest(am) == authority["digest"] == m["authority_digest"]
        and am["kind"] == "authority"
        and am["revision_id"] == m["authority_revision_id"]
        and am["scope"]["bid_id"] == m["bid_id"]
        and all(row["requirement"]["scope"] == am["scope"] for row in m["requirements"])
        and authority["identity"]["digest"] == m["identity_digest"],
        "AUTHORITY_CHANGED",
        "人工更正必须使用原清单的精确权威包、身份和解析范围",
    )
    return {
        "revision_id": am["revision_id"],
        "digest": authority["digest"],
        "identity_digest": authority["identity"]["digest"],
    }


def evidence_rows(authority, documents):
    """Project declared member-part blocks, matching the repository quote catalogue.

    The frozen documents retain the full parse. Blocks outside the explicit parts
    remain in that archive and never become selectable correction evidence.
    """
    members = {m["member_id"]: m for m in authority["manifest"]["members"]}
    rows = []
    for doc in documents:
        if doc.get("package_role", "authority") != "authority":
            continue
        member = members.get(doc["member_id"])
        if member is None:
            raise DomainError(
                "PACKAGE_RULE_CORRECTION_EVIDENCE_OUTSIDE_AUTHORITY",
                "证据文档不属于冻结权威包",
                422,
            )
        for block in doc["blocks"]:
            if not any(
                part["first_page"] <= block["physical_page"] <= part["last_page"]
                for part in member["parts"]
            ):
                continue
            rows.append(
                {
                    "evidence_id": block["id"],
                    "member_id": doc["member_id"],
                    "document_version_id": doc["document_version_id"],
                    "parse_run_id": doc["parse_id"],
                    "physical_page": block["physical_page"],
                    "text_content": block["text_content"],
                    "evidence_digest": block["digest"],
                }
            )
    return rows


def _catalog(authority, rows):
    members = {m["member_id"]: m for m in authority["manifest"]["members"]}
    require(
        len(members) == len(authority["manifest"]["members"]),
        "AUTHORITY_CHANGED",
        "权威成员身份重复",
    )
    result = {}
    keys = {
        "evidence_id",
        "member_id",
        "document_version_id",
        "parse_run_id",
        "physical_page",
        "text_content",
        "evidence_digest",
    }
    for row in rows:
        require(
            type(row) is dict and set(row) == keys, "EVIDENCE_INVALID", "证据目录字段无法核验", 422
        )
        member = members.get(row["member_id"])
        require(
            member is not None
            and member["parse"]["status"] == "frozen"
            and row["document_version_id"] == member["document_version_id"]
            and row["parse_run_id"] == member["parse"]["parse_run_id"]
            and type(row["physical_page"]) is int
            and 1 <= row["physical_page"] <= member["page_count"]
            and type(row["text_content"]) is str
            and _uuid(row["evidence_id"])
            and row["evidence_id"] not in result
            and sha(row["text_content"].encode("utf-8")) == row["evidence_digest"],
            "EVIDENCE_OUTSIDE_AUTHORITY",
            "更正依据不是原权威包的准确文件、解析或原页证据",
            422,
        )
        # The guard above rejects missing members; narrow the local value explicitly.
        if member is None:
            raise DomainError("PACKAGE_RULE_CORRECTION_EVIDENCE_INVALID", "原权威成员缺失", 422)
        parts = sorted(
            p["part_id"]
            for p in member["parts"]
            if p["first_page"] <= row["physical_page"] <= p["last_page"]
        )
        require(bool(parts), "EVIDENCE_OUTSIDE_AUTHORITY", "更正依据位于原权威包声明页段之外", 422)
        result[row["evidence_id"]] = deepcopy(row) | {"part_ids": parts}
    return result


def _quotes(values, catalog):
    output = []
    for value in values:
        row = catalog.get(value["evidence_id"])
        require(
            row is not None
            and bool(value["quote"].strip())
            and value["quote"] in row["text_content"],
            "QUOTE_INVALID",
            "人工依据必须逐字对应原权威包的准确证据，不可编造或改写引用",
            422,
        )
        output.append(
            {key: deepcopy(item) for key, item in row.items() if key != "text_content"}
            | {"quote": value["quote"]}
        )
    return output


def _duplicate_key(rule):
    return digest(
        {
            key: deepcopy(rule[key])
            for key in SEMANTIC_KEYS
            if key not in {"provenance_status", "evidence_ids"}
        }
        | {"evidence_ids": sorted(rule["evidence_ids"])}
    )


def _prepare(inventory, authority, rows, request, policy_digest):
    bounded(request, contract.LIMITS["request_bytes"], "更正请求")
    contract.validate("PackageRuleCorrectionRequest", request)
    verify_inventory_header(inventory)
    m = inventory["manifest"]
    require(
        request["reason"] == request["reason"].strip() and bool(request["reason"]),
        "REASON_REQUIRED",
        "请填写明确且无首尾空白的人工更正理由",
        422,
    )
    require(
        request["base_inventory_digest"] == inventory["digest"]
        and request["base_rule_set_digest"] == m["rule_set_digest"],
        "BASE_CHANGED",
        "更正基线已变化，请重新读取清单并预览",
        412,
    )
    authority_binding = _authority(inventory, authority)
    catalog = _catalog(authority, rows)
    old = {row["rule_id"]: row for row in m["requirements"]}
    changes, seen = [], set()
    resulting = {rid: semantic(row["rule_snapshot"]) for rid, row in old.items()}
    for index, change in enumerate(request["changes"]):
        op, rid = change["op"], change.get("rule_id")
        before = None
        if op != "add":
            require(
                rid in old and rid not in seen,
                "RULE_CHANGED",
                "每个有效原条款在同一笔更正中只能修改一次",
                422,
            )
            require(
                change["rule_digest"] == old[rid]["rule_digest"],
                "RULE_CHANGED",
                "待更正条款摘要已变化",
                412,
            )
            before = semantic(old[rid]["rule_snapshot"])
            require(
                before["provenance_status"] == "effective",
                "RULE_NOT_EFFECTIVE",
                "仅能替换或不采用当前有效解释；历史不再生效条款不可隐式恢复",
                422,
            )
            seen.add(rid)
        values = (
            change["evidence_quotes"] if op == "withdraw" else change["rule"]["evidence_quotes"]
        )
        quotes = _quotes(values, catalog)
        if op == "withdraw":
            if before is None:
                raise DomainError("PACKAGE_RULE_CORRECTION_RULE_CHANGED", "原条款缺失", 422)
            after = deepcopy(before) | {"provenance_status": "superseded"}
        else:
            rule = change["rule"]
            require(
                bool(rule["statement"].strip()) and bool(rule["scope"]["description"].strip()),
                "INVALID",
                "条款解释及适用范围不可为空白",
                422,
            )
            blocks = [
                {"id": q["evidence_id"], "text_content": catalog[q["evidence_id"]]["text_content"]}
                for q in quotes
            ]
            after = semantic(clean(validate_addition(rule, m["bid_id"], blocks)))
            if before is not None:
                require(
                    _duplicate_key(after) != _duplicate_key(before),
                    "NO_CHANGE",
                    "替换内容及依据与原条款相同，无需创建新解释",
                    422,
                )
        resulting[rid if rid is not None else f"add:{index}"] = after
        changes.append(
            {
                "index": index,
                "op": op,
                "rule_id": rid,
                "rule_digest": change.get("rule_digest"),
                "before": before,
                "after": after,
                "quotes": quotes,
            }
        )
    active = [
        _duplicate_key(rule)
        for rule in resulting.values()
        if rule["provenance_status"] == "effective"
    ]
    require(
        len(set(active)) == len(active),
        "DUPLICATE_RULE",
        "更正后的有效解释与依据重复，请合并明确条款",
        422,
    )
    require(
        len(resulting) <= contract.MAX_RULES,
        "CAPACITY_EXCEEDED",
        "新清单超过10000条容量，未截断任何条款",
        422,
    )
    previous = m.get("human_derivation")
    sequence = previous["length"] + 1 if previous else 1
    require(
        sequence <= contract.MAX_CHAIN,
        "CAPACITY_EXCEEDED",
        "人工派生链已达公开深度上限，请使用新完整抽取根",
        422,
    )
    basis = extraction_basis(inventory)
    counts = {
        "before": len(old),
        "after": len(resulting),
        "carried": len(old) - len(seen),
        **{
            name: sum(c["op"] == op for c in changes)
            for name, op in (("added", "add"), ("replaced", "replace"), ("withdrawn", "withdraw"))
        },
        "active_after": len(active),
    }
    limitations = [
        "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
        "HUMAN_INTERPRETATION_NOT_AUTHORITY_AMENDMENT",
        "ORIGINAL_BYTES_NOT_VERIFIED_BY_PREVIEW",
    ]
    if basis["extraction_coverage"] != "complete":
        limitations.append("ROOT_EXTRACTION_" + basis["extraction_coverage"].upper())
    value = {
        "version": "package-rule-correction-preview/1",
        "scope": {
            "bid_id": m["bid_id"],
            "package_id": m["package_id"],
            "revision_id": m["target_revision_id"],
            "inventory_id": m["id"],
        },
        "base": {
            "inventory_digest": inventory["digest"],
            "rule_set_id": m["rule_set_id"],
            "rule_set_digest": m["rule_set_digest"],
        },
        "authority": authority_binding,
        "extraction_basis": basis,
        "previous": {"id": previous["head_id"], "digest": previous["head_digest"]}
        if previous
        else None,
        "sequence_no": sequence,
        "policy_digest": policy_digest,
        "request": deepcopy(request),
        "request_digest": sha(request),
        "source_snapshot_digest": digest(m["source_snapshot"]),
        "changes": changes,
        "counts": counts,
        "limitations": limitations,
        "inventory_complete": False,
        "review_ready": False,
        "original_bytes_verified": False,
    }
    bounded(value, contract.LIMITS["preview_bytes"], "更正预览")
    result = {"manifest": value, "digest": digest(value)}
    contract.validate("PackageRuleCorrectionPreviewView", result)
    return result


def prepare(base_inventory_view, authority_view, evidence_rows, request):
    return _prepare(
        base_inventory_view, authority_view, evidence_rows, request, policy_identity()["digest"]
    )


def _mapping(binding, new_id):
    if not binding["annotation"]["mapped"]:
        return None
    requirement = binding["requirement"]
    return {
        "rule_id": new_id,
        **{
            key: deepcopy(requirement[key])
            for key in (
                "categories",
                "target_part_ids",
                "minimum_count",
                "applicability",
                "valid_at",
                "checks",
            )
        },
        "applicability_evidence_ids": [
            value.removeprefix("evidence:") for value in requirement["applicability_evidence"]
        ],
        "reason": binding["annotation"]["reason"],
        "basis_evidence_ids": deepcopy(binding["annotation"]["basis_evidence_ids"]),
    }


def materialize(base_inventory_view, preview_view, *, rule_set_id, rule_ids):
    """Use server-generated IDs; every old row survives as carry, replace or withdrawal."""
    verify_inventory_header(base_inventory_view)
    contract.validate("PackageRuleCorrectionPreviewView", preview_view)
    pm, base = preview_view["manifest"], base_inventory_view["manifest"]
    require(
        digest(pm) == preview_view["digest"]
        and pm["base"]["inventory_digest"] == base_inventory_view["digest"]
        and pm["request_digest"] == sha(pm["request"]),
        "PREVIEW_CHANGED",
        "更正预览与准确原清单或请求不一致",
    )
    old = {r["rule_id"]: r for r in base["requirements"]}
    added = {str(c["index"]): c for c in pm["changes"] if c["op"] == "add"}
    require(
        type(rule_ids) is dict
        and set(rule_ids) == {"existing", "added"}
        and set(rule_ids["existing"]) == set(old)
        and set(rule_ids["added"]) == set(added),
        "IDS_INVALID",
        "服务端规则身份必须完整覆盖所有原行和新增行",
        500,
    )
    ids = list(rule_ids["existing"].values()) + list(rule_ids["added"].values())
    require(
        _uuid(rule_set_id)
        and rule_set_id != base["rule_set_id"]
        and len(set(ids)) == len(ids)
        and all(_uuid(v) for v in ids)
        and not set(ids) & set(old),
        "IDS_INVALID",
        "新规则身份必须由服务端独立生成且不可复用原行",
        500,
    )
    changed = {c["rule_id"]: c for c in pm["changes"] if c["op"] != "add"}
    rules, mappings, additions, decisions, carryovers, annotations = [], [], [], [], [], []
    for rid, binding in old.items():
        new_id, change = rule_ids["existing"][rid], changed.get(rid)
        original = binding["rule_snapshot"]
        value = deepcopy(original) | {"id": new_id, "rule_set_id": rule_set_id}
        if original["origin_kind"] != "model_extracted":
            value["origin_kind"] = "carried_human"
        if change:
            value.update(deepcopy(change["after"]))
            if change["op"] == "replace":
                value.update(origin_kind="human_added", manual_origin_rule_id=new_id)
            decisions.append(_decision(value, change, pm, preview_view["digest"]))
        elif binding["decision_id"] is not None:
            carryovers.append(
                {
                    "bid_id": base["bid_id"],
                    "new_rule_id": new_id,
                    "from_rule_id": rid,
                    "from_decision_id": binding["decision_id"],
                    "equivalence_digest": digest(
                        {
                            "version": "package-rule-carryover/1",
                            "from_rule_id": rid,
                            "from_rule_digest": binding["rule_digest"],
                            "to_rule_id": new_id,
                            "to_rule_digest": digest(value),
                            "decision_id": binding["decision_id"],
                            "authority_digest": pm["authority"]["digest"],
                            "source_snapshot_digest": pm["source_snapshot_digest"],
                        }
                    ),
                }
            )
        rules.append(value)
        mappings.append(
            {
                "from_rule_id": rid,
                "from_rule_digest": binding["rule_digest"],
                "to_rule_id": new_id,
                "to_rule_digest": digest(value),
                "op": change["op"] if change else "carry",
                "change_index": change["index"] if change else None,
            }
        )
        if not change or change["op"] == "withdraw":
            annotation = _mapping(binding, new_id)
            if annotation:
                annotations.append(annotation)
    for index, change in added.items():
        new_id = rule_ids["added"][index]
        value = deepcopy(change["after"]) | {
            "id": new_id,
            "bid_id": base["bid_id"],
            "rule_set_id": rule_set_id,
            "origin_kind": "human_added",
            "manual_origin_rule_id": new_id,
        }
        rules.append(value)
        additions.append(
            {"change_index": int(index), "to_rule_id": new_id, "to_rule_digest": digest(value)}
        )
        decisions.append(_decision(value, change, pm, preview_view["digest"]))
    rules.sort(key=lambda r: (r["kind"], r["id"]))
    mappings.sort(key=lambda r: r["from_rule_id"])
    additions.sort(key=lambda r: r["change_index"])
    decisions.sort(key=lambda r: r["change_index"])
    carryovers.sort(key=lambda r: r["new_rule_id"])
    annotations.sort(key=lambda r: r["rule_id"])
    rules_digest = digest(rules)
    return {
        "rules": rules,
        "mappings": mappings,
        "additions": additions,
        "rules_digest": rules_digest,
        "rule_set_id": rule_set_id,
        "rule_set_digest": digest(
            {
                "version": "package-human-rule-set/1",
                "base": pm["base"],
                "authority": pm["authority"],
                "preview_digest": preview_view["digest"],
                "rule_set_id": rule_set_id,
                "rules_digest": rules_digest,
            }
        ),
        "decisions": decisions,
        "carryovers": carryovers,
        "inventory_mappings": annotations,
    }


def _decision(rule, change, preview, preview_digest):
    return {
        "rule_id": rule["id"],
        "decision": "rejected" if change["op"] == "withdraw" else "confirmed",
        "reason": preview["request"]["reason"],
        "evidence_ids": list(dict.fromkeys(q["evidence_id"] for q in change["quotes"])),
        "change_index": change["index"],
        "basis": {
            "package_rule_correction_preview_digest": preview_digest,
            "authority": deepcopy(preview["authority"]),
            "rule_digest": digest(rule),
            "change_index": change["index"],
            "operation": change["op"],
        },
    }


def make_record(
    preview_view,
    materialized,
    *,
    record_id,
    result_inventory_id,
    actor_id,
    command_id,
    created_at,
    decision_bindings,
):
    contract.validate("PackageRuleCorrectionPreviewView", preview_view)
    pm = preview_view["manifest"]
    require(digest(pm) == preview_view["digest"], "PREVIEW_CHANGED", "预览摘要无法核验")
    value = {
        "version": "package-rule-correction/1",
        "id": record_id,
        **{key: deepcopy(pm[key]) for key in contract.COMMON},
        "preview_digest": preview_view["digest"],
        "actor_id": actor_id,
        "command_id": command_id,
        "created_at": created_at,
        "result": {
            "inventory_id": result_inventory_id,
            "rule_set_id": materialized["rule_set_id"],
            "rule_set_digest": materialized["rule_set_digest"],
            "rule_count": len(materialized["rules"]),
            "rules_digest": materialized["rules_digest"],
        },
        "mappings": deepcopy(materialized["mappings"]),
        "additions": deepcopy(materialized["additions"]),
        "decision_bindings": sorted(deepcopy(decision_bindings), key=lambda r: r["rule_id"]),
    }
    result = {"manifest": value, "digest": digest(value)}
    contract.validate("PackageRuleCorrectionView", result)
    return result


def verify_derivation(inventory_view, derivation, authority_view, evidence_rows):
    from packages.domain.package_rule_correction_proof import verify

    try:
        return verify(inventory_view, derivation, authority_view, evidence_rows)
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
    ) as error:
        raise DomainError(
            "PACKAGE_RULE_CORRECTION_DERIVATION_CORRUPT", "人工更正链包含无法核验的结构或内容", 500
        ) from error
