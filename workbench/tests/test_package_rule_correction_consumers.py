"""Derived inventories through original receipts, dependency checks and saved plans."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from package_rule_correction_cases import chain, fixture, uid
from test_package_fact_usage import packet

from packages.contracts import bid_package_requirements_api as contracts
from packages.domain import package_dependency_plan as plans
from packages.domain import package_fact_usage as facts
from packages.domain import package_input_dependencies as dependencies
from packages.domain import package_inventory_proof as proof
from packages.domain.package_execution_input import PreparedExecutionInput
from packages.domain.package_review_frozen_input import FrozenPackageReviewInput
from packages.domain.review_identity import digest


def execution(c):
    inventory = c["result"]
    selection = {
        "bid_id": uid(1),
        "inventory": inventory,
        "authority": c["authority"],
        "coverage": None,
    }
    root = {"selection": selection, "documents": c["documents"]}
    scope = (uid(1), uid(2), uid(3), inventory["manifest"]["id"])
    fm = {
        "id": uid(5),
        **dict(zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)),
        "input_digest": digest(selection),
    }
    frozen = FrozenPackageReviewInput(json.dumps(fm), json.dumps(root), digest(fm))
    prepared = packet()
    public, snapshot = prepared.view(), prepared.snapshot()
    public["manifest"]["identity"]["binding"].update(
        {
            **dict(
                zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
            ),
            "frozen_digest": frozen.digest,
            "input_digest": fm["input_digest"],
        }
    )
    result = PreparedExecutionInput(
        scope,
        prepared.frozen_id,
        prepared.input_id,
        digest({"public": public, "snapshot": snapshot}),
        json.dumps(public),
        json.dumps(snapshot),
    )
    return frozen, result


def check(c, *, declarations=None):
    frozen, prepared = execution(c)
    usage = facts.select(prepared, {"purpose": "prebid_compliance", "fact_ids": []})
    assessment = dependencies.assess(
        frozen,
        prepared,
        usage,
        {
            "purpose": "prebid_compliance",
            "usage_digest": usage.digest,
            "dependencies": declarations or [],
        },
    )
    return frozen, prepared, usage, assessment


def test_original_extraction_and_native_derivation_have_distinct_verified_identifiers():
    c = chain()
    frozen, prepared = execution(c)
    receipt = c["receipt"] | {"derivation": c["derivation"]}
    result = proof.assess(frozen, prepared, receipt).view()
    m = result["manifest"]
    assert m["version"] == "package-inventory-proof/2"
    assert m["extraction_receipt_state"] == "matched" and m["extraction_range_proven"] is True
    assert m["human_derivation"]["state"] == "verified"
    assert m["human_derivation"]["root_rule_set_id"] == receipt["run"]["rule_set_id"] == uid(70)
    assert c["result"]["manifest"]["rule_set_id"] != receipt["run"]["rule_set_id"]
    assert m["human_derivation"]["counts"]["human_withdrawn"] == 1
    assert m["human_derivation"]["counts"]["inherited_superseded"] == 1
    assert m["quality_status"] == "not_measured"
    assert m["blockers"] == ["INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"]
    assert all(
        m[key] is False
        for key in (
            "inventory_complete",
            "facts_qualified",
            "review_ready",
            "launch_available",
            "original_bytes_verified",
            "publication_authorized",
        )
    )
    assert result["digest"] == digest(m)
    assert Draft202012Validator(proof.SCHEMA).is_valid(result)


def test_no_archive_does_not_guess_human_withdrawal_or_treat_header_as_full_chain():
    c = chain()
    frozen, prepared = execution(c)
    m = proof.assess(frozen, prepared).view()["manifest"]
    assert m["human_derivation"]["state"] == "archive_missing"
    assert m["human_derivation"]["counts"]["inactive"] == 2
    assert m["human_derivation"]["counts"]["human_withdrawn"] is None
    assert m["human_derivation"]["counts"]["inherited_superseded"] is None
    assert not m["extraction_range_proven"] and not m["inventory_complete"]


@pytest.mark.parametrize(
    "tamper", ["missing", "new_rule_set", "new_result_id", "altered_native_decision", "wrong_head"]
)
def test_proof_rejects_missing_or_fabricated_new_model_receipt_for_human_rules(tamper):
    c = chain()
    receipt = deepcopy(c["receipt"] | {"derivation": c["derivation"]})
    if tamper == "missing":
        receipt.pop("derivation")
    elif tamper == "new_rule_set":
        receipt["run"]["rule_set_id"] = c["result"]["manifest"]["rule_set_id"]
    elif tamper == "new_result_id":
        receipt["run"]["id"] = uid(999)
    elif tamper == "altered_native_decision":
        receipt["derivation"]["steps"][0]["decisions"][0]["decision"] = "rejected"
    else:
        c["result"]["manifest"]["human_derivation"]["head_digest"] = "f" * 64
        c["result"]["digest"] = digest(c["result"]["manifest"])
    frozen, prepared = execution(c)
    with pytest.raises(ValueError):
        proof.assess(frozen, prepared, receipt)


@pytest.mark.parametrize("coverage", ["partial", "conflict"])
def test_manual_derivation_does_not_remove_original_extraction_blocker(coverage):
    c = fixture()
    run = c["receipt"]["run"]
    run["result"]["extraction_coverage"] = coverage
    run["result_digest"] = digest(run["result"])
    c["base"]["manifest"].update(
        extraction_coverage=coverage, extraction_result_digest=run["result_digest"]
    )
    c["base"]["digest"] = digest(c["base"]["manifest"])
    c = chain(c)
    frozen, prepared = execution(c)
    m = proof.assess(frozen, prepared, c["receipt"] | {"derivation": c["derivation"]}).view()[
        "manifest"
    ]
    assert m["extraction_range_proven"] is True
    assert "INVENTORY_EXTRACTION_" + coverage.upper() in m["blockers"]
    assert m["inventory_complete"] is False


def test_dependencies_keep_every_inactive_row_and_never_turn_withdrawal_into_pass():
    c = chain()
    frozen, prepared, usage, assessment = check(c)
    m = assessment.view()["manifest"]
    assert m["version"] == "package-input-dependencies/2"
    assert m["inventory_status"] == "human_derivation_range_quality_unmeasured"
    assert m["requirement_count"] == len(m["requirements"]) == 5
    assert m["rule_state_counts"] == {
        "total": 5,
        "active": 3,
        "inactive": 2,
        "needs_revalidation": 0,
    }
    assert sum(r["rule_status"] == "inactive" for r in m["requirements"]) == 2
    assert all(
        r["fact_status"] == "unknown" and r["coverage_state"] == "not_provided"
        for r in m["requirements"]
    )
    assert m["required_facts_assessment"] == "unknown"
    assert m["inventory_complete"] is m["review_ready"] is m["facts_qualified"] is False
    assert (
        dependencies.verify(assessment.view(), frozen, prepared, usage).view() == assessment.view()
    )
    assert contracts.valid("PackageInputDependencyAssessment", assessment.view())


def test_all_not_needed_declarations_are_only_dependency_choices_even_for_inactive_rows():
    c = chain()
    declarations = [
        {
            "requirement_id": r["rule_id"],
            "requirement_digest": r["requirement_digest"],
            "state": "not_needed",
            "fact_ids": [],
            "evidence_ids": r["rule_snapshot"]["evidence_ids"],
            "reason": "已核对本次不使用企业事实",
        }
        for r in c["result"]["manifest"]["requirements"]
    ]
    frozen, prepared, usage, assessment = check(c, declarations=declarations)
    m = assessment.view()["manifest"]
    assert m["required_facts_assessment"] == "not_used"
    assert m["dependency_review_status"] == "declared"
    assert len(m["requirements"]) == 5 and m["rule_state_counts"]["inactive"] == 2
    assert all(r["coverage_state"] == "not_provided" for r in m["requirements"])
    assert m["inventory_complete"] is m["review_ready"] is False
    saved = plans.build(
        frozen,
        prepared,
        usage,
        assessment,
        record_id=uid(900),
        actor_id=uid(91),
        command_id=uid(901),
        saved_at="2026-10-21T13:00:00Z",
        body={
            "execution_input_digest": prepared.digest,
            "purpose": "prebid_compliance",
            "fact_ids": [],
            "dependencies": declarations,
            "assessment_digest": assessment.digest,
            "reason": "保存这次完整人工依赖声明",
        },
    )
    assert contracts.valid("PackageDependencyPlanView", saved.view())
    assert plans.read(saved.view(), frozen, prepared).view() == saved.view()
    assert saved.view()["manifest"]["assessment"] == assessment.view()


@pytest.mark.parametrize(
    "tamper", ["drop_inactive", "active_count", "label_inactive", "mark_complete"]
)
def test_resealed_assessment_cannot_hide_inactive_rows_or_promote_them_to_active(tamper):
    c = chain()
    frozen, prepared, usage, assessment = check(c)
    bad = assessment.view()
    m = bad["manifest"]
    if tamper == "drop_inactive":
        m["requirements"] = [r for r in m["requirements"] if r["rule_status"] != "inactive"]
        m["requirement_count"] = len(m["requirements"])
    elif tamper == "active_count":
        m["rule_state_counts"]["active"] = 5
        m["rule_state_counts"]["inactive"] = 0
    elif tamper == "label_inactive":
        for r in m["requirements"]:
            r["rule_status"] = "active"
    else:
        m["inventory_complete"] = True
    bad["digest"] = digest(m)
    with pytest.raises(ValueError):
        dependencies.verify(bad, frozen, prepared, usage)


def test_dependency_plan_embedded_assessment_keeps_exact_live_v1_v2_contract_union():
    # The saved-plan API must accept both actual assessment generations. Frozen
    # old /1 fixtures remain old /1; no fixture rewrite can fix a missing DTO union.
    for name, value in dependencies.SCHEMA["$defs"].items():
        rewritten = json.loads(json.dumps(value).replace("#/$defs/", "#/$defs/Assessment_"))
        assert plans.SCHEMA["$defs"]["Assessment_" + name] == rewritten
    expected = {
        "oneOf": [
            {"$ref": "#/components/schemas/PackageDependencyPlan_Assessment_ManifestV1"},
            {"$ref": "#/components/schemas/PackageDependencyPlan_Assessment_ManifestV2"},
        ]
    }
    assert contracts.SCHEMAS["PackageDependencyPlan_Assessment_Manifest"] == expected
