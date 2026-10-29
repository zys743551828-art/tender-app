"""Pure exact authority evidence and native-row replay; no DB, originals or model calls."""

from copy import deepcopy

import pytest
from package_rule_correction_cases import addition, apply, chain, fixture, request, uid, view

from packages.contracts import package_rule_corrections_api as contract
from packages.domain import package_rule_corrections as core
from packages.domain.bid_package_requirements import project_requirement
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import DomainError, sha


def prepare(c, body=None):
    return core.prepare(c["base"], c["authority"], c["evidence"], body or request(c["base"]))


def verify(c):
    return core.verify_derivation(c["result"], c["derivation"], c["authority"], c["evidence"])


def reseal(c):
    """Recompute public hashes, without access to replacement native source facts."""
    step = c["derivation"]["steps"][-1]
    step["digest"] = digest(step["manifest"])
    c["result"]["manifest"]["human_derivation"]["head_digest"] = step["digest"]
    c["result"]["digest"] = digest(c["result"]["manifest"])


def test_complete_add_replace_withdraw_preserves_root_native_rows_and_human_limits():
    c = fixture()
    original = deepcopy(c)
    result = apply(c)
    assert c == original
    pm = result["preview"]["manifest"]
    assert pm["request_digest"] == sha(request(c["base"]))
    assert pm["counts"] == {
        "before": 4,
        "after": 5,
        "carried": 2,
        "added": 1,
        "replaced": 1,
        "withdrawn": 1,
        "active_after": 3,
    }
    assert pm["changes"][0]["after"]["max_points"] == "10.50"
    assert pm["changes"][0]["after"]["conditions"] == ["含安装"]
    assert pm["changes"][0]["after"]["exceptions"] == ["已有授权"]
    assert pm["changes"][0]["after"]["bands"][0]["points"] == "10.50"
    assert pm["changes"][1]["before"]["statement"] == pm["changes"][1]["after"]["statement"]
    assert pm["changes"][1]["after"]["provenance_status"] == "superseded"
    assert pm["inventory_complete"] is pm["review_ready"] is pm["original_bytes_verified"] is False
    assert "HUMAN_INTERPRETATION_NOT_AUTHORITY_AMENDMENT" in pm["limitations"]
    c.update(result, derivation={"root_inventory": c["base"], "steps": [result["step"]]})
    assert verify(c)["counts"] == {
        "total": 5,
        "active": 3,
        "inactive": 2,
        "needs_revalidation": 0,
        "human_withdrawn": 1,
        "inherited_superseded": 1,
    }
    assert result["record"]["manifest"]["extraction_basis"]["rule_set_id"] == uid(70)
    assert result["record"]["manifest"]["result"]["rule_set_id"] != uid(70)
    assert "inventory_digest" not in result["record"]["manifest"]["result"]


def test_changed_semantics_do_not_reuse_old_plan_but_carries_keep_exact_old_decisions():
    c = chain()
    materialized = c["materialized"]
    mappings = {r["from_rule_id"]: r for r in materialized["mappings"]}
    plans = {r["rule_id"]: r for r in materialized["inventory_mappings"]}
    bindings = {r["rule_id"]: r for r in c["result"]["manifest"]["requirements"]}
    carry = mappings[uid(20)]["to_rule_id"]
    replaced = mappings[uid(21)]["to_rule_id"]
    withdrawn = mappings[uid(22)]["to_rule_id"]
    added = materialized["additions"][0]["to_rule_id"]
    assert set(plans) == {carry, withdrawn, mappings[uid(23)]["to_rule_id"]}
    assert (
        bindings[carry]["decision_snapshot"]
        == c["base"]["manifest"]["requirements"][0]["decision_snapshot"]
    )
    assert bindings[carry]["decision_snapshot"]["object_id"] == uid(20)
    for rid in (replaced, added):
        assert bindings[rid]["annotation"]["mapped"] is False
        assert bindings[rid]["requirement"]["applicability"] == "unknown"
        assert bindings[rid]["requirement"]["target_part_ids"] == []
        assert bindings[rid]["rule_snapshot"]["origin_kind"] == "human_added"
        assert bindings[rid]["rule_snapshot"]["manual_origin_rule_id"] == rid
        assert bindings[rid]["decision_snapshot"]["decision"] == "confirmed"
    assert bindings[withdrawn]["decision_snapshot"]["decision"] == "rejected"
    assert bindings[withdrawn]["rule_snapshot"]["statement"] == "须提供纸质样本"
    assert bindings[withdrawn]["requirement"]["target_part_ids"] == ["body"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(base_inventory_digest="0" * 64),
        lambda b: b.update(base_rule_set_digest="0" * 64),
        lambda b: b.update(reason="  "),
        lambda b: b.update(reason=" padded "),
        lambda b: b.update(rule_set_id=uid(999)),
        lambda b: b["changes"][0].update(rule_digest="0" * 64),
        lambda b: b["changes"][0].update(rule_id=uid(999)),
        lambda b: b["changes"].append(deepcopy(b["changes"][0])),
        lambda b: b["changes"][0]["rule"].update(id=uid(999)),
        lambda b: b["changes"][0]["rule"].update(origin_kind="model_extracted"),
        lambda b: b["changes"][0]["rule"].update(maximum=10.5),
        lambda b: b["changes"][0]["rule"].update(maximum="10.500"),
        lambda b: b["changes"][0]["rule"].update(conditions=["推测条件"]),
        lambda b: b["changes"][0]["rule"].update(exceptions=["推测例外"]),
        lambda b: b["changes"][0]["rule"]["scope"].update(bid_id=uid(999)),
        lambda b: b["changes"][0]["rule"]["bands"][0].update(points="11.50"),
        lambda b: b["changes"][0]["rule"]["bands"][0].update(evidence_ids=[uid(32)]),
        lambda b: b["changes"][0]["rule"]["evidence_quotes"][0].update(quote="伪造原文"),
        lambda b: b["changes"][1]["evidence_quotes"][0].update(quote=" "),
        lambda b: b["changes"][1]["evidence_quotes"][0].update(evidence_id=uid(999)),
        lambda b: b["changes"].append(deepcopy(b["changes"][2])),
    ],
)
def test_request_cannot_forge_scope_identity_quotes_or_exact_scoring(mutate):
    c = fixture()
    body = request(c["base"])
    mutate(body)
    with pytest.raises(DomainError):
        prepare(c, body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("member_id", "target"),
        ("document_version_id", uid(999)),
        ("parse_run_id", uid(999)),
        ("physical_page", 3),
        ("physical_page", True),
        ("evidence_digest", "f" * 64),
        ("text_content", "替换原文"),
    ],
)
def test_exact_authority_catalog_rejects_other_member_parse_page_and_changed_text(field, value):
    c = fixture()
    c["evidence"][0][field] = value
    with pytest.raises(DomainError):
        prepare(c)


def test_quotes_must_stay_inside_explicit_parts_even_when_file_page_exists():
    c = fixture()
    c["authority"]["manifest"]["members"][0]["parts"][0]["last_page"] = 1
    c["authority"]["digest"] = digest(c["authority"]["manifest"])
    c["base"]["manifest"]["authority_digest"] = c["authority"]["digest"]
    c["base"]["digest"] = digest(c["base"]["manifest"])
    with pytest.raises(DomainError, match="EVIDENCE_OUTSIDE_AUTHORITY"):
        prepare(c)


def test_frozen_document_quote_projection_matches_declared_parts_without_rewriting_archive():
    c = fixture()
    original = deepcopy(c["documents"])
    c["authority"]["manifest"]["members"][0]["parts"][0]["last_page"] = 1
    catalog = core.evidence_rows(c["authority"], c["documents"])
    assert [row["evidence_id"] for row in catalog] == [uid(30)]
    assert c["documents"] == original and len(c["documents"][0]["blocks"]) == 2


def test_cross_lot_requirement_cannot_piggyback_same_bid_or_resealed_inventory():
    c = fixture()
    row = c["base"]["manifest"]["requirements"][0]
    row["requirement"]["scope"]["lot_id"] = uid(999)
    row["requirement_digest"] = digest(row["requirement"])
    c["base"]["digest"] = digest(c["base"]["manifest"])
    with pytest.raises(DomainError, match="AUTHORITY_CHANGED"):
        prepare(c)


def test_superseded_interpretations_cannot_be_silently_reactivated():
    c = fixture()
    row = c["base"]["manifest"]["requirements"][-1]
    body = request(
        c["base"],
        [
            {
                "op": "replace",
                "rule_id": row["rule_id"],
                "rule_digest": row["rule_digest"],
                "rule": addition(),
            }
        ],
    )
    with pytest.raises(DomainError, match="RULE_NOT_EFFECTIVE"):
        prepare(c, body)


@pytest.mark.parametrize("field", ["inventory_complete", "review_ready"])
def test_resealed_inventory_cannot_promote_human_declaration_to_completeness(field):
    c = fixture()
    c["base"]["manifest"][field] = True
    c["base"]["digest"] = digest(c["base"]["manifest"])
    with pytest.raises(DomainError, match="INVENTORY_CORRUPT"):
        prepare(c)


def test_legacy_without_exact_extraction_is_not_repaired_by_human_description():
    c = fixture()
    m = c["base"]["manifest"]
    for key in tuple(m):
        if key.startswith("extraction_"):
            m.pop(key)
    m.update(version="bid-package-requirements/1", extraction_binding="unproven_legacy_rule_set")
    c["base"]["digest"] = digest(m)
    with pytest.raises(DomainError, match="EXACT_EXTRACTION_REQUIRED"):
        prepare(c)


@pytest.mark.parametrize("coverage", ["partial", "conflict"])
def test_manual_changes_preserve_incomplete_root_range_quality_without_false_upgrade(coverage):
    c = fixture()
    c["base"]["manifest"]["extraction_coverage"] = coverage
    c["base"]["digest"] = digest(c["base"]["manifest"])
    result = prepare(c)["manifest"]
    assert result["extraction_basis"]["extraction_coverage"] == coverage
    assert "ROOT_EXTRACTION_" + coverage.upper() in result["limitations"]
    assert result["inventory_complete"] is result["review_ready"] is False


@pytest.mark.parametrize(
    "tamper",
    [
        "request",
        "source_snapshot",
        "mapping_omission",
        "mapping_duplicate",
        "additions",
        "rules",
        "result_digest",
        "decision_actor",
        "decision_reason",
        "decision_digest",
        "carryover",
        "carried_decision",
        "missing_decision",
        "extra_step",
        "new_rule_reused",
        "fake_root_result",
    ],
)
def test_resealed_public_hashes_do_not_hide_broken_native_derivation(tamper):
    c = chain()
    step = c["derivation"]["steps"][0]
    m = step["manifest"]
    if tamper == "request":
        m["request"]["reason"] = "另一理由"
        m["request_digest"] = sha(m["request"])
    elif tamper == "source_snapshot":
        m["source_snapshot_digest"] = "f" * 64
    elif tamper == "mapping_omission":
        m["mappings"].pop()
    elif tamper == "mapping_duplicate":
        m["mappings"][1] = deepcopy(m["mappings"][0])
    elif tamper == "additions":
        m["additions"].clear()
    elif tamper == "rules":
        step["result_rules"][0]["statement"] = "替换真实条款"
    elif tamper == "result_digest":
        m["result"]["rule_set_digest"] = "f" * 64
    elif tamper in {"decision_actor", "decision_reason", "carried_decision"}:
        d = step["decisions"][-1] if tamper == "carried_decision" else step["decisions"][0]
        d["actor_id" if tamper == "decision_actor" else "reason"] = (
            uid(999) if tamper == "decision_actor" else "替换真实决定"
        )
        for b in m["decision_bindings"]:
            if b["decision_id"] == d["id"]:
                b["decision_digest"] = digest(d)
    elif tamper == "decision_digest":
        m["decision_bindings"][0]["decision_digest"] = "f" * 64
    elif tamper == "carryover":
        step["carryovers"][0]["from_decision_id"] = uid(999)
    elif tamper == "missing_decision":
        step["decisions"].pop()
    elif tamper == "extra_step":
        c["derivation"]["steps"].append(deepcopy(step))
    elif tamper == "new_rule_reused":
        m["mappings"][0]["to_rule_id"] = m["mappings"][0]["from_rule_id"]
    else:
        c["result"]["manifest"]["extraction_basis"]["rule_set_id"] = m["result"]["rule_set_id"]
    reseal(c)
    with pytest.raises(DomainError):
        verify(c)


def test_reprojection_and_chained_carries_preserve_explicit_human_withdrawal_history():
    c = chain()
    first = deepcopy(c["result"])
    selected = deepcopy(first["manifest"])
    selected.update(id=uid(950), revision=3, predecessor_digest=first["digest"])
    selected["requirements"][0]["annotation"]["reason"] = "重新保存的检查计划"
    c["result"] = view(selected)
    assert verify(c)["counts"]["human_withdrawn"] == 1
    extra = addition()
    extra["statement"] = "服务响应说明须覆盖本次标段"
    second = apply(
        c, base=c["result"], body=request(c["result"], [{"op": "add", "rule": extra}]), number=2
    )
    c["derivation"]["steps"].append(second["step"])
    c["result"] = second["result"]
    checked = verify(c)
    assert checked["length"] == 2 and checked["counts"]["total"] == 6
    assert checked["counts"]["human_withdrawn"] == checked["counts"]["inherited_superseded"] == 1
    added_first = c["materialized"]["additions"][0]["to_rule_id"]
    original_id = next(
        r["manual_origin_rule_id"]
        for r in second["materialized"]["rules"]
        if r["manual_origin_rule_id"] == added_first
    )
    assert original_id == added_first
    assert any(r["origin_kind"] == "carried_human" for r in second["materialized"]["rules"])
    assert first["manifest"]["id"] != second["step"]["base_inventory"]["manifest"]["id"]


def test_policy_binds_all_actual_pure_sources_and_new_preview_tracks_changes(monkeypatch):
    c = chain()
    old = c["preview"]
    identity = core.policy_identity()
    assert set(identity["sources"]) == set(core.POLICY_FILES)
    assert identity["sources"]["packages/domain/package_rule_correction_proof.py"] == sha(
        (core.ROOT / "packages/domain/package_rule_correction_proof.py").read_bytes()
    )
    monkeypatch.setattr(core, "POLICY_FILES", (*core.POLICY_FILES, "packages/domain/runtime.py"))
    assert (
        core.prepare(c["base"], c["authority"], c["evidence"], old["manifest"]["request"])["digest"]
        != old["digest"]
    )
    # Archived protocol /1 replays its recorded method; the coordinator compares
    # the fresh prepare digest before every new write.
    assert verify(c)["state"] == "verified"


def test_capacity_rejects_whole_request_chain_or_output_without_truncation(monkeypatch):
    c = fixture()
    body = request(c["base"])
    body["changes"] = [{"op": "add", "rule": addition()}] * 101
    with pytest.raises(DomainError):
        prepare(c, body)
    body = request(c["base"])
    body["oversized"] = "x" * (contract.LIMITS["request_bytes"] + 1)
    with pytest.raises(DomainError, match="CAPACITY_EXCEEDED"):
        prepare(c, body)
    saved = chain()
    saved["result"]["manifest"]["human_derivation"]["length"] = contract.MAX_CHAIN
    saved["result"]["digest"] = digest(saved["result"]["manifest"])
    with pytest.raises(DomainError, match="CAPACITY_EXCEEDED"):
        core.prepare(
            saved["result"],
            saved["authority"],
            saved["evidence"],
            request(saved["result"], [{"op": "add", "rule": addition() | {"statement": "新要求"}}]),
        )
    monkeypatch.setattr(contract, "MAX_RULES", 4)
    with pytest.raises(DomainError, match="CAPACITY_EXCEEDED"):
        prepare(c)
    monkeypatch.setitem(
        contract.LIMITS, "derivation_bytes", len(canonical(saved["derivation"])) - 1
    )
    with pytest.raises(DomainError, match="CAPACITY_EXCEEDED"):
        verify(saved)


def test_existing_inventory_above_500_is_not_silently_clipped_to_form_page_size():
    c = fixture()
    original = c["base"]["manifest"]["requirements"][0]
    rows = []
    for n in range(501):
        rule = deepcopy(original["rule_snapshot"])
        rule.update(id=uid(10000 + n), statement=f"明确义务 {n}")
        rows.append(project_requirement(c["target"], rule, None, None, source_bound=True))
    c["base"]["manifest"]["requirements"] = rows
    c["base"]["digest"] = digest(c["base"]["manifest"])
    body = request(c["base"], [{"op": "add", "rule": addition()}])
    result = apply(c, body=body)
    assert len(result["materialized"]["rules"]) == 502
    assert len(result["materialized"]["mappings"]) == 501
    c.update(result, derivation={"root_inventory": c["base"], "steps": [result["step"]]})
    assert verify(c)["counts"]["total"] == 502


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(digest="f" * 64),
        lambda p: p["manifest"].update(
            base={**p["manifest"]["base"], "inventory_digest": "f" * 64}
        ),
    ],
)
def test_materialization_rejects_stale_or_tampered_preview_digest(mutate):
    c = chain()
    p = deepcopy(c["preview"])
    mutate(p)
    with pytest.raises(DomainError):
        core.materialize(c["base"], p, rule_set_id=uid(900), rule_ids={"existing": {}, "added": {}})


def test_invalid_json_values_fail_cleanly_instead_of_getting_hashed_or_truncated():
    c = fixture()
    for bad in (float("nan"), float("inf"), "\ud800", {"cycle": None}):
        body = request(c["base"])
        if isinstance(bad, dict):
            bad["cycle"] = bad
        body["bad"] = bad
        with pytest.raises(DomainError):
            prepare(c, body)
