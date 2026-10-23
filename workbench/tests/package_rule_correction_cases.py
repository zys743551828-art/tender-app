"""Synthetic immutable native rows for the package human derivation protocol tests."""

from copy import deepcopy

from packages.domain import package_rule_corrections as core
from packages.domain.bid_package_requirements import project_requirement
from packages.domain.bid_packages import (
    BidScope,
    DocumentPart,
    PackageKind,
    PackageMember,
    PackageRevision,
    ParseIdentity,
)
from packages.domain.review_identity import digest
from packages.domain.runtime import sha

TIME = "2026-10-21T12:34:56.123456Z"


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def view(manifest):
    return {"manifest": manifest, "digest": digest(manifest)}


def native_decision(rule_id, decision_id, *, decision="confirmed", reason="已核对原页", actor=91):
    return {
        "id": uid(decision_id),
        "bid_id": uid(1),
        "object_kind": "rule",
        "object_id": rule_id,
        "object_revision": 1,
        "decision": decision,
        "reason": reason,
        "evidence_ids": [uid(30)],
        "actor_id": uid(actor),
        "created_at": TIME,
    }


def package(scope, *, authority=False):
    role = "authority" if authority else "target"
    member = PackageMember(
        role,
        uid(40 if authority else 50),
        "c" * 64 if authority else "d" * 64,
        "authority" if authority else "own",
        uid(42 if authority else 52),
        scope,
        ("technical",),
        2,
        ParseIdentity("frozen", uid(41 if authority else 51), "e" * 64, "f" * 64, "a" * 64),
        (DocumentPart("main" if authority else "body", "technical", 1, 2),),
    )
    return PackageRevision(
        uid(60 if authority else 2),
        uid(61 if authority else 3),
        1,
        PackageKind.AUTHORITY if authority else PackageKind.BID,
        scope,
        (member,),
    )


def native_rule(n):
    return {
        "id": uid(n),
        "bid_id": uid(1),
        "rule_set_id": uid(70),
        "kind": "mandatory",
        "statement": {20: "工期为 30 天", 21: "原评分解释", 22: "须提供纸质样本", 23: "旧解释"}[n],
        "conditions": [],
        "exceptions": [],
        "max_points": None,
        "evidence_ids": [uid(30 if n in (20, 21) else 32)],
        "bands": [],
        "applicability_scope": {"bid_id": uid(1), "description": "当前标段"},
        "origin_kind": "model_extracted",
        "manual_origin_rule_id": None,
        "provenance_status": "superseded" if n == 23 else "effective",
    }


def mapping():
    return {
        "categories": ["technical"],
        "target_part_ids": ["body"],
        "minimum_count": None,
        "applicability": "applicable",
        "applicability_evidence_ids": [],
        "valid_at": None,
        "checks": [],
        "reason": "人工检查计划绑定精确正文页段",
        "basis_evidence_ids": [uid(30)],
    }


def extraction_receipt(authority, documents):
    am = authority["manifest"]
    member = am["members"][0]
    method = {"engine": "synthetic-test-only"}
    im = {
        "identity_version": "package-rule-extraction-input/1",
        "bid_id": uid(1),
        "scope": am["scope"],
        "authority_package": {
            "package_id": am["package_id"],
            "revision_id": am["revision_id"],
            "digest": authority["digest"],
            "manifest": am,
            "identity_digest": authority["identity"]["digest"],
            "identity_snapshot": authority["identity"],
        },
        "members": [
            {
                **{
                    k: member[k]
                    for k in (
                        "member_id",
                        "document_version_id",
                        "file_digest",
                        "page_count",
                        "parts",
                    )
                },
                **{
                    k: member["parse"][k]
                    for k in ("parse_run_id", "parser_digest", "config_digest", "evidence_digest")
                },
            }
        ],
        "extraction_scope": {
            "policy": "all_declared_package_parts",
            "coverage": "all_physical_pages",
            "parts": [
                {
                    "member_id": member["member_id"],
                    "document_version_id": member["document_version_id"],
                    "parse_run_id": member["parse"]["parse_run_id"],
                    **{
                        k: p[k] for k in ("part_id", "first_page", "last_page", "shared_attachment")
                    },
                }
                for p in member["parts"]
            ],
        },
        "method_profile": method,
        "method_digest": digest(method),
    }
    result = {
        "input_digest": digest(im),
        "rule_set_id": uid(70),
        "authority_revision_id": am["revision_id"],
        "authority_digest": authority["digest"],
        "method_digest": digest(method),
        "range_status": "all_frozen_evidence_submitted",
        "read_evidence_ids_digest": digest(sorted(b["id"] for d in documents for b in d["blocks"])),
        "extraction_coverage": "complete",
        "quality_status": "not_measured",
    }
    run = {
        "id": uid(71),
        "bid_id": uid(1),
        "authority_revision_id": am["revision_id"],
        "authority_digest": authority["digest"],
        "input_digest": digest(im),
        "input_manifest": im,
        "operation_id": uid(72),
        "operation_input_digest": "b" * 64,
        "rule_set_id": uid(70),
        "result_digest": digest(result),
        "result": result,
    }
    return {
        "run": run,
        "operation": {
            "id": uid(72),
            "bid_id": uid(1),
            "input_digest": "b" * 64,
            "handler_version": "prepare/1",
            "state": "succeeded",
        },
        "effect": {
            "result_ref": uid(70),
            "method_digest": digest(method),
            "extraction_input_digest": digest(im),
        },
    }


def fixture():
    scope = BidScope(uid(101), uid(102), uid(103), uid(1), uid(104))
    target, ap = package(scope), package(scope, authority=True)
    authority = view(ap.manifest()) | {"identity": {"digest": "d" * 64}}
    texts = [
        "工期为 30 天。适用条件为含安装；除非已有授权。满分 10.50 分，完整方案得 10.50 分。",
        "仅提交电子文件，不要求纸质样本。新增要求：须提供服务响应说明。",
    ]
    blocks = [
        {"id": uid(n), "physical_page": p, "text_content": text, "digest": sha(text.encode())}
        for n, p, text in zip((30, 32), (1, 2), texts, strict=True)
    ]
    documents = [
        {
            "package_role": "authority",
            "member_id": "authority",
            "document_version_id": uid(40),
            "parse_id": uid(41),
            "digest": "c" * 64,
            "parser_digest": "e" * 64,
            "config_digest": "f" * 64,
            "page_count": 2,
            "blocks": blocks,
        }
    ]
    receipt = extraction_receipt(authority, documents)
    rules = [native_rule(n) for n in range(20, 24)]
    bindings = [
        project_requirement(
            target,
            r,
            native_decision(r["id"], 80 + i, decision="rejected" if i == 3 else "confirmed"),
            mapping(),
            source_bound=True,
        )
        for i, r in enumerate(rules)
    ]
    run = receipt["run"]
    manifest = {
        "version": core.V2,
        "id": uid(4),
        "bid_id": uid(1),
        "package_id": uid(2),
        "target_revision_id": uid(3),
        "package_digest": target.manifest_digest,
        "authority_revision_id": uid(61),
        "authority_digest": authority["digest"],
        "rule_set_id": uid(70),
        "rule_set_digest": digest(rules),
        "revision": 1,
        "predecessor_digest": None,
        "identity_digest": authority["identity"]["digest"],
        "source_snapshot": [{"id": uid(42), "document_version_id": uid(40), "status": "effective"}],
        "requirements": bindings,
        "inventory_complete": False,
        "extraction_binding": "exact_frozen_input_result",
        "review_ready": False,
        "actor_id": uid(91),
        "extraction_result_id": run["id"],
        "extraction_input_digest": run["input_digest"],
        "extraction_result_digest": run["result_digest"],
        "extraction_range_status": "all_frozen_evidence_submitted",
        "extraction_coverage": "complete",
        "extraction_quality_status": "not_measured",
    }
    return {
        "base": view(manifest),
        "target": target,
        "authority": authority,
        "documents": documents,
        "evidence": core.evidence_rows(authority, documents),
        "receipt": receipt,
    }


def addition(*, scoring=False):
    return {
        "kind": "scoring" if scoring else "mandatory",
        "statement": "完整方案按原文评 10.50 分" if scoring else "须提供服务响应说明",
        "conditions": ["含安装"] if scoring else [],
        "exceptions": ["已有授权"] if scoring else [],
        "scope": {"bid_id": uid(1), "description": "当前标段"},
        "maximum": "10.50" if scoring else None,
        "bands": [
            {
                "label": "完整",
                "description": "完整方案得 10.50 分",
                "points": "10.50",
                "evidence_ids": [uid(30)],
            }
        ]
        if scoring
        else [],
        "evidence_quotes": [
            {
                "evidence_id": uid(30 if scoring else 32),
                "quote": "适用条件为含安装；除非已有授权。满分 10.50 分，完整方案得 10.50 分。"
                if scoring
                else "新增要求：须提供服务响应说明。",
            }
        ],
    }


def request(base, changes=None):
    rows = {r["rule_id"]: r for r in base["manifest"]["requirements"]}
    if changes is None:
        changes = [
            {
                "op": "replace",
                "rule_id": uid(21),
                "rule_digest": rows[uid(21)]["rule_digest"],
                "rule": addition(scoring=True),
            },
            {
                "op": "withdraw",
                "rule_id": uid(22),
                "rule_digest": rows[uid(22)]["rule_digest"],
                "evidence_quotes": [{"evidence_id": uid(32), "quote": "不要求纸质样本"}],
            },
            {"op": "add", "rule": addition()},
        ]
    return {
        "base_inventory_digest": base["digest"],
        "base_rule_set_digest": base["manifest"]["rule_set_digest"],
        "reason": "核对同一权威包原页后更正解释并补漏",
        "changes": changes,
    }


def apply(c, *, base=None, body=None, number=1):
    base = deepcopy(base if base is not None else c["base"])
    body = deepcopy(body if body is not None else request(base))
    preview = core.prepare(base, c["authority"], c["evidence"], body)
    n = number * 100000
    ids = {
        "existing": {
            r["rule_id"]: uid(n + i) for i, r in enumerate(base["manifest"]["requirements"])
        },
        "added": {
            str(i): uid(n + 10000 + i) for i, r in enumerate(body["changes"]) if r["op"] == "add"
        },
    }
    materialized = core.materialize(base, preview, rule_set_id=uid(n + 200), rule_ids=ids)
    decisions, bindings, by_rule = [], [], {}
    old = {r["rule_id"]: r for r in base["manifest"]["requirements"]}
    for i, row in enumerate(materialized["decisions"]):
        d = native_decision(
            row["rule_id"], n + 300 + i, decision=row["decision"], reason=row["reason"]
        )
        d["evidence_ids"] = row["evidence_ids"]
        by_rule[row["rule_id"]] = d
        decisions.append(d)
        bindings.append(
            {
                "rule_id": row["rule_id"],
                "decision_id": d["id"],
                "decision_digest": digest(d),
                "mode": row["decision"],
            }
        )
    for row in materialized["carryovers"]:
        d = deepcopy(old[row["from_rule_id"]]["decision_snapshot"])
        by_rule[row["new_rule_id"]] = d
        decisions.append(d)
        bindings.append(
            {
                "rule_id": row["new_rule_id"],
                "decision_id": d["id"],
                "decision_digest": digest(d),
                "mode": "carried",
            }
        )
    record = core.make_record(
        preview,
        materialized,
        record_id=uid(n + 400),
        result_inventory_id=uid(n + 500),
        actor_id=uid(91),
        command_id=uid(n + 600),
        created_at=TIME,
        decision_bindings=bindings,
    )
    m = {k: deepcopy(v) for k, v in base["manifest"].items() if not k.startswith("extraction_")}
    annotations = {r["rule_id"]: r for r in materialized["inventory_mappings"]}
    m.update(
        version=core.V3,
        id=uid(n + 500),
        rule_set_id=materialized["rule_set_id"],
        rule_set_digest=materialized["rule_set_digest"],
        revision=m["revision"] + 1,
        predecessor_digest=base["digest"],
        extraction_binding=core.BINDING,
        extraction_basis=core.extraction_basis(base),
        human_derivation={
            "version": "package-rule-derivation/1",
            "head_id": record["manifest"]["id"],
            "head_digest": record["digest"],
            "length": number,
        },
        requirements=[
            project_requirement(
                c["target"], r, by_rule.get(r["id"]), annotations.get(r["id"]), source_bound=True
            )
            for r in materialized["rules"]
        ],
    )
    step = {
        **record,
        "base_inventory": base,
        "result_rules": deepcopy(materialized["rules"]),
        "decisions": decisions,
        "carryovers": deepcopy(materialized["carryovers"]),
    }
    return {
        "preview": preview,
        "record": record,
        "result": view(m),
        "step": step,
        "materialized": materialized,
    }


def chain(c=None):
    c = fixture() if c is None else c
    result = apply(c)
    return (
        c
        | result
        | {"derivation": {"root_inventory": deepcopy(c["base"]), "steps": [result["step"]]}}
    )
