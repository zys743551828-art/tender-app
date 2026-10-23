"""Synthetic exact packages using the real scope-result and inventory-proof producers."""

from copy import deepcopy
from types import SimpleNamespace

from package_rule_correction_cases import chain, extraction_receipt, fixture, uid, view

from packages.contracts import bid_package_requirements_api as requirements
from packages.contracts import package_review_runs_api as runs
from packages.domain import package_inventory_proof as proofs
from packages.domain import package_review_decisions as opinions
from packages.domain import package_scope_review as review
from packages.domain.bid_package_requirements import assess_records, coverage_record
from packages.domain.review_identity import digest

TIME = "2026-10-21T14:00:00.000000Z"


def case():
    original = fixture()
    scope = original["target"].manifest()["scope"]
    identity = {
        "bidder_id": scope["bidder_id"],
        "bidder_name": "合成测试投标主体",
        "round_id": scope["round_id"],
        "engineering_project_id": scope["engineering_project_id"],
        "engineering_title": "合成测试工程",
        "region": None,
        "engineering_type": None,
        "lot": "合成标段",
        "lot_id": scope["lot_id"],
        "round_no": 1,
        "binding_status": "confirmed",
        "authority_id": uid(105),
        "digest": "d" * 64,
        "identity_version": "bid-identity/2",
    }
    target = view(original["target"].manifest()) | {
        "identity": deepcopy(identity),
        "storage_eligible": True,
        "review_ready": False,
    }
    authority = deepcopy(original["authority"]) | {
        "identity": deepcopy(identity),
        "storage_eligible": True,
        "review_ready": False,
    }
    receipt = extraction_receipt(authority, original["documents"])
    source = {
        "source_id": uid(42),
        "ancestor_id": uid(42),
        "document_version_id": uid(40),
        "policy_class": "prebid_content",
        "known_at": "2026-10-20T00:00:00Z",
        "revision": 1,
        "status": "published",
        "valid_from": "2026-10-20T00:00:00Z",
        "valid_until": None,
    }
    im = deepcopy(original["base"]["manifest"])
    im.update(
        source_snapshot=[source],
        extraction_input_digest=receipt["run"]["input_digest"],
        extraction_result_digest=receipt["run"]["result_digest"],
    )
    selection = {
        "version": "bid-package-review-input/1",
        "kind": "preview",
        "bid_id": uid(1),
        "target": target,
        "authority": authority,
        "inventory": view(im),
        "coverage": None,
    }
    assert requirements.valid("PackageReviewInputManifest", selection)
    current = {
        "current": {
            "identity": deepcopy(identity),
            "current_rule_set_id": im["rule_set_id"],
            "phase": "preparing",
            "archived_at": None,
        },
        "lifecycle": {"bid_id": uid(1), "phase": "preparing", "archived_at": None, "revision": 1},
        "package_heads": {uid(2): uid(3), uid(60): uid(61)},
        "inventory_head": {"id": im["id"]},
        "sources": [deepcopy(source)],
        "generated_outputs": [],
    }
    return {"selection": selection, "current": current, "source": original, "receipt": receipt}


def proof(case):
    selection = case["selection"]
    scope = (uid(1), uid(2), uid(3), selection["inventory"]["manifest"]["id"])
    fm = {
        "id": uid(5),
        **dict(zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)),
        "input_digest": digest(selection),
    }
    root = {"selection": selection, "documents": case["source"]["documents"]}
    original = SimpleNamespace(digest=digest(fm), view=lambda: view(fm), evidence=lambda: root)
    prepared = SimpleNamespace(
        scope=scope,
        frozen_id=uid(5),
        input_id=uid(6),
        digest="e" * 64,
        view=lambda: {
            "manifest": {
                "identity": {
                    "binding": {
                        "frozen_input_id": uid(5),
                        "frozen_digest": original.digest,
                        "input_digest": digest(selection),
                    }
                }
            }
        },
    )
    return proofs.assess(original, prepared, case["receipt"]).view()


def report(case, *, verdict="satisfied", number=800):
    selection = case["selection"]
    inventory = selection["inventory"]["manifest"]
    rows = inventory["requirements"]
    scope = {
        "bid_id": selection["bid_id"],
        "package_id": inventory["package_id"],
        "revision_id": inventory["target_revision_id"],
        "inventory_id": inventory["id"],
    }
    frozen_proof = proof(case)
    manifest = {
        "scope": scope,
        "frozen_input": {"id": uid(5), "digest": frozen_proof["manifest"]["frozen_digest"]},
        "execution_input": {
            "id": uid(6),
            "digest": "e" * 64,
            "identity": {"execution_digest": "f" * 64},
        },
        "dependency_plan": {"id": uid(7), "digest": "a" * 64},
        "executor_method": {"digest": "b" * 64},
    }
    documents = []
    for role in ("target", "authority"):
        for member in selection[role]["manifest"]["members"]:
            documents.append(
                {
                    "package_role": role,
                    **{
                        key: deepcopy(member[key])
                        for key in (
                            "member_id",
                            "document_version_id",
                            "file_digest",
                            "page_count",
                            "parts",
                        )
                    },
                    "parse_run_id": member["parse"]["parse_run_id"],
                    "blocks": [],
                    "pages": [],
                }
            )
    matrix = [
        {
            "requirement_id": row["rule_id"],
            "requirement_digest": row["requirement_digest"],
            "rule_digest": row["rule_digest"],
            "rule_kind": row["rule_snapshot"]["kind"],
            "requirement_statement": row["rule_snapshot"]["statement"],
            "applicability": row["requirement"]["applicability"],
            "target_part_ids": row["requirement"]["target_part_ids"],
            "inspected_ranges": [],
            "verdict": verdict,
            "statement": "合成精确范围核查结论，不代表实际模型质量已测。",
            "target_quotes": [],
            "authority_quotes": [],
            "used_fact_ids": [],
            "limitations": [],
            "human_review_state": "unreviewed",
        }
        for row in rows
    ]
    payload = {
        "requirements": [{"requirement_id": row["rule_id"]} for row in rows],
        "documents": documents,
    }
    result = review.result_manifest(uid(number), manifest, payload, matrix)
    output = {
        "kind": "package_review_run",
        "id": uid(number),
        "actor_id": uid(91),
        "created_at": TIME,
        "scope": scope,
        "frozen_input_id": uid(5),
        "frozen_input_digest": manifest["frozen_input"]["digest"],
        "execution_input_id": uid(6),
        "execution_input_digest": "e" * 64,
        "execution_digest": "f" * 64,
        "dependency_plan_id": uid(7),
        "dependency_plan_digest": "a" * 64,
        "input_digest": digest(manifest),
        "method_digest": "b" * 64,
        "operation": {
            "id": uid(number + 1),
            "kind": "package-scope-review",
            "state": "succeeded",
            "input_digest": digest(manifest),
            "handler_version": "package-review/1",
            "error_code": None,
            "created_at": TIME,
            "finished_at": TIME,
        },
        "result": view(result),
    }
    assert runs.valid("PackageReviewRunView", output)
    return output


def confirmation_rows(case):
    return [
        {
            "rule_id": row["rule_id"],
            "rule_digest": row["rule_digest"],
            "decision": deepcopy(row["decision_snapshot"]),
        }
        for row in case["selection"]["inventory"]["manifest"]["requirements"]
    ]


def derived(case):
    """Use the actual F04 native carryover/replace/withdraw/add derivation producer."""
    source = deepcopy(case["source"])
    source.update(
        base=case["selection"]["inventory"],
        authority=case["selection"]["authority"],
        receipt=case["receipt"],
    )
    derived = chain(source)
    output = deepcopy(case)
    output["selection"]["inventory"] = derived["result"]
    output["receipt"] = derived["receipt"] | {"derivation": derived["derivation"]}
    output["current"]["inventory_head"]["id"] = derived["result"]["manifest"]["id"]
    output["current"]["current"]["current_rule_set_id"] = derived["result"]["manifest"][
        "rule_set_id"
    ]
    return output


def history(*reports, complete=True, human=(), legacy=()):
    return {
        "complete": complete,
        "package_runs": list(reports),
        "human_decisions": list(human),
        "legacy_findings": list(legacy),
    }


def opinion(run, *, state="rejected", number=900):
    row = run["result"]["manifest"]["matrix"][0]
    return opinions.make(
        run,
        row["requirement_id"],
        {
            "result_digest": run["result"]["digest"],
            "row_digest": digest(row),
            "expected_head": None,
            "state": state,
            "reason": "合成人工意见，不表示已经复检解决。",
            "selected_quotes": [],
        },
        decision_id=uid(number),
        actor_id=uid(91),
        created_at=TIME,
        sequence_no=1,
    )


def legacy(*, lifecycle="open", number=950):
    return {
        "id": uid(number),
        "bid_id": uid(1),
        "origin_id": uid(number + 1),
        "review_id": uid(number + 2),
        "rule_id": None,
        "rule_kind": None,
        "severity": "critical",
        "category": "consistency",
        "verdict": "violated",
        "lifecycle": lifecycle,
        "statement": "合成旧单正文关键问题；未取得真实复检解决记录。",
    }


def declared_coverage(case):
    selection = case["selection"]
    bindings = selection["inventory"]["manifest"]["requirements"]
    records = [
        coverage_record(
            case["source"]["target"],
            row,
            {
                "requirement_digest": row["requirement_digest"],
                "state": "verified",
                "inspected": [{"part_id": "body", "first_page": 1, "last_page": 2}],
                "evidence_ids": [uid(30)],
                "reason": "人工声明已逐页查看已知项",
                "basis_type": "human_scope_declaration",
            },
        )
        for row in bindings
    ]
    manifest = {
        "version": "bid-package-coverage/1",
        "id": uid(11),
        "bid_id": uid(1),
        "inventory_id": selection["inventory"]["manifest"]["id"],
        "inventory_digest": selection["inventory"]["digest"],
        "package_digest": selection["target"]["digest"],
        "actor_id": uid(91),
        "results": records,
        "assessment": assess_records(case["source"]["target"], bindings, records),
        "review_ready": False,
    }
    result = view(manifest)
    assert requirements.valid("PackageCoverageAttemptView", result)
    return result
