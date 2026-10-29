"""Pure explicit dependency declarations; synthetic packets, no DB or execution claim."""

import json
from copy import deepcopy

import pytest
from test_package_fact_usage import packet as prepared_packet
from test_package_fact_usage import uid

from packages.domain.package_execution_input import PreparedExecutionInput
from packages.domain.package_fact_usage import select
from packages.domain.package_input_dependencies import assess, verify
from packages.domain.package_review_frozen_input import FrozenPackageReviewInput
from packages.domain.review_identity import digest


@pytest.fixture
def case():
    prepared = prepared_packet()
    rule = {
        "id": uid(20),
        "statement": "按原文核对工期，不通过名称猜测事实依赖",
        "evidence_ids": [uid(30)],
        "conditions": [],
        "exceptions": [],
    }
    requirement = {"requirement_id": uid(20), "applicability": "applicable"}
    row = {
        "rule_id": uid(20),
        "rule_snapshot": rule,
        "rule_digest": digest(rule),
        "requirement": requirement,
        "requirement_digest": digest(requirement),
        "source_bound": True,
    }
    inv = {
        "id": prepared.scope[3],
        "requirements": [row],
        "extraction_binding": "exact_frozen_input_result",
    }
    selection = {"inventory": {"manifest": inv, "digest": digest(inv)}, "coverage": None}
    manifest = dict(
        zip(("bid_id", "package_id", "revision_id", "inventory_id"), prepared.scope, strict=True)
    ) | {"id": prepared.frozen_id, "input_digest": digest(selection)}
    root = {
        "selection": selection,
        "documents": [
            {"package_role": "authority", "blocks": [{"id": uid(30)}]},
            {"package_role": "target", "blocks": [{"id": uid(31)}]},
        ],
    }
    frozen = FrozenPackageReviewInput(json.dumps(manifest), json.dumps(root), digest(manifest))
    public = prepared.view()
    public["manifest"]["identity"]["binding"].update(
        frozen_digest=frozen.digest, input_digest=manifest["input_digest"]
    )
    prepared = PreparedExecutionInput(
        prepared.scope,
        prepared.frozen_id,
        prepared.input_id,
        digest(public),
        json.dumps(public),
        json.dumps(prepared.snapshot()),
    )
    return {"frozen": frozen, "prepared": prepared, "root": root, "row": row}


def declaration(case, state="required", facts=None):
    return {
        "requirement_id": uid(20),
        "requirement_digest": case["row"]["requirement_digest"],
        "state": state,
        "fact_ids": [uid(10)] if facts is None else facts,
        "evidence_ids": [uid(30)],
        "reason": "人工逐条核对原规则的本次依赖",
    }


def run(case, dependencies=None, selected=(uid(10),)):
    usage = select(case["prepared"], {"purpose": "prebid_compliance", "fact_ids": list(selected)})
    request = {
        "purpose": "prebid_compliance",
        "usage_digest": usage.digest,
        "dependencies": [] if dependencies is None else dependencies,
    }
    return assess(case["frozen"], case["prepared"], usage, request), usage, request


def rebind(case):
    root = case["root"]
    selection = root["selection"]
    selection["inventory"]["digest"] = digest(selection["inventory"]["manifest"])
    if selection["coverage"]:
        selection["coverage"]["manifest"]["inventory_digest"] = selection["inventory"]["digest"]
        selection["coverage"]["digest"] = digest(selection["coverage"]["manifest"])
    manifest = case["frozen"].view()["manifest"] | {"input_digest": digest(selection)}
    case["frozen"] = FrozenPackageReviewInput(
        json.dumps(manifest), json.dumps(root), digest(manifest)
    )
    p = case["prepared"]
    v = p.view()
    v["manifest"]["identity"]["binding"].update(
        frozen_digest=case["frozen"].digest, input_digest=manifest["input_digest"]
    )
    case["prepared"] = PreparedExecutionInput(
        p.scope, p.frozen_id, p.input_id, digest(v), json.dumps(v), json.dumps(p.snapshot())
    )


def test_no_annotations_and_no_selection_never_mean_no_required_facts(case):
    result, _, _ = run(case, selected=())
    m = result.view()["manifest"]
    assert (
        m["required_facts_assessment"] == "unknown"
        and m["dependency_review_status"] == "incomplete"
    )
    assert m["requirements"][0]["declaration"] is None


@pytest.mark.parametrize("selected", [(), (uid(11),)])
def test_known_dependency_not_selected_is_missing_even_when_an_unrelated_fact_is_selected(
    case, selected
):
    result, _, _ = run(case, [declaration(case)], selected)
    m = result.view()["manifest"]
    assert m["required_facts_assessment"] == "missing"
    assert m["requirements"][0]["unselected_fact_ids"] == [uid(10)]


def test_explicit_needed_fact_without_any_matching_value_reports_missing(case):
    result, _, _ = run(case, [declaration(case, facts=[])], selected=())
    assert result.view()["manifest"]["required_facts_assessment"] == "missing"


def test_selected_dependency_remains_unvalidated_not_confirmed_or_qualified(case):
    result, usage, _ = run(case, [declaration(case)])
    m = result.view()["manifest"]
    assert (
        m["required_facts_assessment"] == "selected_unvalidated"
        and m["dependency_review_status"] == "declared"
    )
    assert m["usage_digest"] == usage.digest
    assert not any(
        m[k]
        for k in (
            "inventory_complete",
            "facts_qualified",
            "review_ready",
            "launch_available",
            "publication_authorized",
            "original_bytes_verified",
        )
    )
    assert "selected-private" not in json.dumps(m) and "unused-private" not in repr(result)


def test_explicit_no_fact_dependency_is_a_human_annotation_not_inventory_certification(case):
    result, _, _ = run(case, [declaration(case, "not_needed", [])], selected=())
    m = result.view()["manifest"]
    assert m["required_facts_assessment"] == "not_used"
    assert m["declaration_kind"] == "human_dependency_annotation"
    assert (
        m["inventory_status"] == "range_submitted_quality_unmeasured"
        and not m["inventory_complete"]
    )


@pytest.mark.parametrize("state", ["unknown", "not_needed"])
def test_unknown_and_not_needed_must_not_smuggle_selected_facts(case, state):
    with pytest.raises(ValueError, match="nonrequired_facts"):
        run(case, [declaration(case, state)])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(requirement_id=uid(99)),
        lambda d: d.update(requirement_digest="f" * 64),
        lambda d: d.update(fact_ids=[uid(99)]),
        lambda d: d.update(evidence_ids=[uid(31)]),
        lambda d: d.update(evidence_ids=[uid(99)]),
        lambda d: d.update(evidence_ids=[]),
        lambda d: d.update(reason="  "),
        lambda d: d.update(reason=" padded "),
        lambda d: d.update(state="satisfied"),
        lambda d: d.update(facts_qualified=True),
    ],
)
def test_rejects_foreign_or_stale_requirements_facts_evidence_and_implied_grants(case, mutate):
    d = declaration(case)
    mutate(d)
    with pytest.raises(ValueError):
        run(case, [d])


def test_duplicate_requirements_or_declarations_rejected(case):
    d = declaration(case)
    with pytest.raises(ValueError, match="requirement_scope"):
        run(case, [d, d])
    case["root"]["selection"]["inventory"]["manifest"]["requirements"].append(deepcopy(case["row"]))
    rebind(case)
    with pytest.raises(ValueError, match="duplicate_requirement"):
        run(case)


def test_unproven_rule_source_never_proves_dependencies_even_after_annotation(case):
    case["row"]["source_bound"] = False
    rebind(case)
    result, _, _ = run(case, [declaration(case, "not_needed", [])])
    assert result.view()["manifest"]["required_facts_assessment"] == "unknown"


def test_empty_inventory_is_unknown_not_vacuously_complete(case):
    case["root"]["selection"]["inventory"]["manifest"]["requirements"] = []
    rebind(case)
    result, _, _ = run(case, selected=())
    assert result.view()["manifest"]["required_facts_assessment"] == "unknown"
    assert result.view()["manifest"]["dependency_review_status"] == "incomplete"


def test_manual_coverage_and_not_applicable_do_not_skip_fact_dependency_review(case):
    cm = {
        "inventory_digest": case["root"]["selection"]["inventory"]["digest"],
        "assessment": {"requirement_states": {uid(20): "not_applicable"}},
    }
    case["root"]["selection"]["coverage"] = {"manifest": cm, "digest": digest(cm)}
    rebind(case)
    result, _, _ = run(case, selected=())
    m = result.view()["manifest"]
    assert (
        m["requirements"][0]["coverage_state"] == "not_applicable"
        and m["required_facts_assessment"] == "unknown"
    )


def test_result_owns_its_data_and_verification_rejects_resealed_wrong_assessment(case):
    d = declaration(case)
    result, usage, _ = run(case, [d])
    old = result.view()
    d["fact_ids"].clear()
    v = result.view()
    v["manifest"]["requirements"].clear()
    assert result.view() == old
    assert verify(old, case["frozen"], case["prepared"], usage).view() == old
    bad = deepcopy(old)
    bad["manifest"]["required_facts_assessment"] = "not_used"
    bad["digest"] = digest(bad["manifest"])
    with pytest.raises(ValueError, match="record_changed"):
        verify(bad, case["frozen"], case["prepared"], usage)


def test_wrong_usage_or_frozen_identity_is_rejected(case):
    result, usage, request = run(case)
    request["usage_digest"] = "a" * 64
    with pytest.raises(ValueError, match="usage_changed"):
        assess(case["frozen"], case["prepared"], usage, request)
    request["usage_digest"] = usage.digest
    f = case["frozen"]
    case["frozen"] = FrozenPackageReviewInput(f._manifest_text, f._evidence_text, "a" * 64)
    with pytest.raises(ValueError, match="frozen_binding"):
        assess(case["frozen"], case["prepared"], usage, request)
    assert result.view()["manifest"]["inventory_complete"] is False


def test_same_text_with_a_different_rule_identity_cannot_reuse_old_annotation(case):
    d = declaration(case)
    case["row"]["rule_snapshot"]["id"] = uid(80)
    case["row"]["rule_digest"] = digest(case["row"]["rule_snapshot"])
    rebind(case)
    with pytest.raises(ValueError, match="projection_corrupt"):
        run(case, [d])


def test_fact_and_evidence_set_order_does_not_change_assessment_identity(case):
    case["row"]["rule_snapshot"]["evidence_ids"].append(uid(32))
    case["row"]["rule_digest"] = digest(case["row"]["rule_snapshot"])
    case["root"]["documents"][0]["blocks"].append({"id": uid(32)})
    rebind(case)
    a = declaration(case, facts=[uid(11), uid(10)])
    a["evidence_ids"] = [uid(32), uid(30)]
    b = deepcopy(a)
    b["fact_ids"].reverse()
    b["evidence_ids"].reverse()
    first, _, _ = run(case, [a], selected=(uid(10), uid(11)))
    second, _, _ = run(case, [b], selected=(uid(11), uid(10)))
    assert first.view() == second.view()


def test_omitted_requirement_stays_unknown_even_when_another_rule_is_declared(case):
    other = deepcopy(case["row"])
    other["rule_id"] = other["rule_snapshot"]["id"] = other["requirement"]["requirement_id"] = uid(
        21
    )
    other["rule_digest"] = digest(other["rule_snapshot"])
    other["requirement_digest"] = digest(other["requirement"])
    case["root"]["selection"]["inventory"]["manifest"]["requirements"].append(other)
    rebind(case)
    result, _, _ = run(case, [declaration(case, "not_needed", [])], selected=())
    m = result.view()["manifest"]
    assert m["requirement_count"] == 2 and m["required_facts_assessment"] == "unknown"
    assert m["dependency_review_status"] == "incomplete"
    assert [r["fact_status"] for r in m["requirements"]] == ["not_used", "unknown"]
