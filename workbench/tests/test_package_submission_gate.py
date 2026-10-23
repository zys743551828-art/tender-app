"""Four real observations retain unknowns and historical obligations; zero provider IO."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from package_submission_gate_cases import (
    TIME,
    case,
    confirmation_rows,
    declared_coverage,
    derived,
    history,
    legacy,
    opinion,
    proof,
    report,
    uid,
)

from packages.domain import package_submission_gate as gate
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


def observe(c, **kwargs):
    return gate.assess(c["selection"], observed_at=TIME, **kwargs)["manifest"]


def resign(value):
    value["digest"] = digest(value["manifest"])


def test_full_physical_extraction_and_confirmed_known_rules_do_not_invent_formal_completeness():
    c = case()
    run = report(c)
    old = deepcopy(c)
    output = gate.assess(
        c["selection"],
        observed_at=TIME,
        current=c["current"],
        run=run,
        inventory_proof=proof(c),
        rule_decisions=confirmation_rows(c),
        risk_history=history(run),
    )
    m = output["manifest"]
    assert gate.validate_view(output) == output
    assert output["digest"] == digest(m)
    assert c == old
    assert m["subject"]["kind"] == "bid_package"
    assert m["subject"]["package_digest"] == c["selection"]["target"]["digest"]
    cards = m["gates"]
    assert cards["current_input"]["state"] == "unknown"
    assert "ORIGINAL_BYTES_NOT_CHECKED" in cards["current_input"]["codes"]
    assert cards["core_coverage"]["state"] == "unknown"
    assert cards["core_coverage"]["extraction_range_proven"] is True
    assert cards["core_coverage"]["active_core_count"] == 3
    assert cards["core_coverage"]["judged_core_count"] == 3
    assert cards["mandatory_confirmation"]["state"] == "pass"
    assert cards["mandatory_confirmation"]["inactive_rule_ids"] == [uid(23)]
    assert cards["known_blocking_risks"]["state"] == "pass"
    for key in (
        "allowed",
        "submission_eligible",
        "formal_scoring_eligible",
        "inventory_complete",
        "publication_authorized",
        "platform_submission_verified",
    ):
        assert m[key] is False
    assert m["quality_status"] == "not_measured"


def test_offline_actual_package_may_have_no_authority_inventory_or_review():
    c = case()
    selection = {
        "target": c["selection"]["target"],
        "authority": None,
        "inventory": None,
        "coverage": None,
    }
    value = gate.assess(selection, observed_at=TIME)
    m = value["manifest"]
    assert m["subject"]["revision_id"] == uid(3)
    assert (
        m["selection"]["authority_revision_id"]
        is m["selection"]["inventory_id"]
        is m["selection"]["run_id"]
        is None
    )
    assert all(card["state"] == "unknown" for card in m["gates"].values())
    assert not m["allowed"]


@pytest.mark.parametrize(
    "history_value",
    [None, {"complete": False, "package_runs": [], "human_decisions": [], "legacy_findings": []}],
)
def test_missing_or_incomplete_history_never_means_no_known_risks(history_value):
    card = observe(case(), risk_history=history_value)["gates"]["known_blocking_risks"]
    assert card["state"] == "unknown" and not card["history_complete"]
    assert card["blocked_count"] == 0
    assert "RISK_HISTORY_INCOMPLETE" in card["codes"]


def test_explicit_complete_empty_whole_bid_history_can_pass_only_known_risk_card():
    m = observe(case(), risk_history=history())
    assert m["gates"]["known_blocking_risks"]["state"] == "pass"
    assert m["gates"]["core_coverage"]["state"] == "unknown"
    assert not m["allowed"]


@pytest.mark.parametrize("verdict", ["violated", "not_found", "unable_to_judge"])
def test_selected_run_missing_from_claimed_complete_history_keeps_its_actual_rows(verdict):
    c = case()
    run = report(c, verdict=verdict)
    card = observe(c, run=run, risk_history=history())["gates"]["known_blocking_risks"]
    assert card["state"] == ("unknown" if verdict == "unable_to_judge" else "blocked")
    assert not card["history_complete"]
    assert card["runs_read"] == 1 and len(card["risks"]) == 4
    assert "SELECTED_RUN_MISSING_FROM_HISTORY" in card["codes"]


@pytest.mark.parametrize("state", ["confirmed", "rejected", "needs_review"])
def test_all_human_machine_opinions_preserve_original_blocking_risk(state):
    c = case()
    run = report(c, verdict="violated")
    decision = opinion(run, state=state)
    card = observe(c, risk_history=history(run, human=[decision]))["gates"]["known_blocking_risks"]
    assert card["state"] == "blocked" and card["blocked_count"] == 4
    first = card["risks"][0]
    assert first["human_decision"]["state"] == state
    assert first["row_digest"] == digest(run["result"]["manifest"]["matrix"][0])
    assert first["resolution"] == "no_verified_package_recheck_resolution"


def test_changed_package_and_later_satisfied_report_do_not_erase_prior_violations():
    c = case()
    old = report(c, verdict="not_found", number=800)
    old["scope"]["package_id"] = uid(777)
    old["scope"]["revision_id"] = uid(778)
    old["result"]["manifest"]["scope"] = deepcopy(old["scope"])
    resign(old["result"])
    current = report(c, number=810)
    card = observe(c, run=current, risk_history=history(old, current))["gates"][
        "known_blocking_risks"
    ]
    assert card["state"] == "blocked" and card["blocked_count"] == 4
    assert {r["run_id"] for r in card["risks"]} == {old["id"]}
    assert all(r["scope"]["package_id"] == uid(777) for r in card["risks"])


@pytest.mark.parametrize("lifecycle", ["open", "deferred", "dismissed"])
def test_native_legacy_dismissal_is_not_a_verified_package_recheck(lifecycle):
    card = observe(case(), risk_history=history(legacy=[legacy(lifecycle=lifecycle)]))["gates"][
        "known_blocking_risks"
    ]
    assert card["state"] == "blocked" and card["blocked_count"] == 1
    item = card["risks"][0]
    assert item["kind"] == "legacy_finding"
    assert item["finding"]["lifecycle"] == lifecycle
    assert "run_id" not in item


@pytest.mark.parametrize("state", ["queued", "running", "failed", "cancelled", "cancel_requested"])
def test_unfinished_or_failed_historical_runs_leave_unknown_not_all_clear(state):
    c = case()
    run = report(c)
    run["operation"]["state"] = state
    run["operation"]["error_code"] = "SYNTHETIC_FAILURE" if state == "failed" else None
    run["result"] = None
    card = observe(c, risk_history=history(run))["gates"]["known_blocking_risks"]
    assert card["state"] == "unknown"
    assert card["unknown_run_ids"] == [run["id"]]


@pytest.mark.parametrize(
    "change",
    [
        "bid",
        "run_id",
        "input_digest",
        "execution_digest",
        "counts",
        "duplicate_rows",
        "result_digest",
        "terminal_state",
    ],
)
def test_historical_report_binding_corruption_is_rejected(change):
    c = case()
    run = report(c)
    m = run["result"]["manifest"]
    if change == "bid":
        run["scope"]["bid_id"] = uid(999)
        m["scope"] = deepcopy(run["scope"])
        m["bid_id"] = uid(999)
    elif change == "run_id":
        m["run_id"] = uid(999)
    elif change in {"input_digest", "execution_digest"}:
        m[change] = "0" * 64
    elif change == "counts":
        m["counts"]["satisfied"] += 1
    elif change == "duplicate_rows":
        m["matrix"][1] = deepcopy(m["matrix"][0])
    elif change == "terminal_state":
        run["operation"]["state"] = "failed"
    resign(run["result"])
    if change == "result_digest":
        run["result"]["digest"] = "0" * 64
    with pytest.raises(DomainError):
        observe(c, risk_history=history(run))


@pytest.mark.parametrize("field", ["package_id", "revision_id", "inventory_id"])
def test_selected_report_must_bind_selected_exact_package_and_inventory(field):
    c = case()
    run = report(c)
    run["scope"][field] = uid(999)
    run["result"]["manifest"]["scope"] = deepcopy(run["scope"])
    resign(run["result"])
    with pytest.raises(DomainError):
        observe(c, run=run)


@pytest.mark.parametrize(
    "field", ["file_digest", "document_version_id", "parse_run_id", "page_count"]
)
def test_selected_report_cannot_substitute_different_original_document_identity(field):
    c = case()
    run = report(c)
    run["result"]["manifest"]["submitted_documents"][0][field] = (
        3 if field == "page_count" else "0" * 64 if field == "file_digest" else uid(999)
    )
    resign(run["result"])
    with pytest.raises(DomainError):
        observe(c, run=run)


@pytest.mark.parametrize(
    "field", ["requirement_digest", "rule_digest", "rule_kind", "requirement_statement"]
)
def test_selected_report_cannot_substitute_other_rule_content(field):
    c = case()
    run = report(c)
    run["result"]["manifest"]["matrix"][0][field] = (
        "advisory"
        if field == "rule_kind"
        else "不同规则正文"
        if field == "requirement_statement"
        else "0" * 64
    )
    resign(run["result"])
    with pytest.raises(DomainError):
        observe(c, run=run)


@pytest.mark.parametrize(
    "change",
    ["cross_run", "wrong_row", "duplicate_opinion", "duplicate_run", "conflicting_selected_run"],
)
def test_human_history_cannot_cross_or_ambiguously_replace_original_run_rows(change):
    c = case()
    run = report(c, verdict="violated")
    decision = opinion(run)
    h = history(run, human=[decision])
    selected = None
    if change == "cross_run":
        decision["manifest"]["run_id"] = uid(999)
        resign(decision)
    elif change == "wrong_row":
        decision["manifest"]["row_digest"] = "0" * 64
        resign(decision)
    elif change == "duplicate_opinion":
        h["human_decisions"].append(deepcopy(decision))
    elif change == "duplicate_run":
        h["package_runs"].append(deepcopy(run))
    else:
        selected = deepcopy(run)
        selected["actor_id"] = uid(998)
    with pytest.raises(DomainError):
        observe(c, risk_history=h, run=selected)


def test_absent_current_native_decisions_do_not_fall_back_to_frozen_confirmations():
    c = case()
    card = observe(c)["gates"]["mandatory_confirmation"]
    assert card["state"] == "unknown"
    assert card["confirmed_count"] == 0 and len(card["pending_rule_ids"]) == 3


@pytest.mark.parametrize(
    "decision", ["rejected", "needs_review", "dismiss", "accept_rules_as_written"]
)
def test_known_nonconfirmation_cannot_pass_mandatory_rule_gate(decision):
    c = case()
    rows = confirmation_rows(c)
    rows[0]["decision"]["decision"] = decision
    card = observe(c, rule_decisions=rows)["gates"]["mandatory_confirmation"]
    assert card["state"] == "blocked"
    assert card["confirmed_count"] == 2


@pytest.mark.parametrize("change", ["bid", "rule", "digest", "duplicate", "extra_field"])
def test_native_rule_confirmation_must_bind_current_rule_or_exact_validated_carryover(change):
    c = case()
    rows = confirmation_rows(c)
    if change == "bid":
        rows[0]["decision"]["bid_id"] = uid(999)
    elif change == "rule":
        rows[0]["decision"]["object_id"] = uid(999)
    elif change == "digest":
        rows[0]["rule_digest"] = "0" * 64
    elif change == "duplicate":
        rows.append(deepcopy(rows[0]))
    else:
        rows[0]["decision"]["decision_revision"] = 1
    with pytest.raises(DomainError):
        observe(c, rule_decisions=rows)


def test_exact_frozen_carryover_can_confirm_a_new_rule_without_fabricating_decision_identity():
    c = case()
    row = c["selection"]["inventory"]["manifest"]["requirements"][0]
    row["decision_snapshot"]["object_id"] = uid(666)
    resign(c["selection"]["inventory"])
    decisions = confirmation_rows(c)
    card = observe(c, rule_decisions=decisions)["gates"]["mandatory_confirmation"]
    assert card["state"] == "pass"
    decisions[0]["decision"]["reason"] = "改过的旧决定不能视为同一个carryover"
    with pytest.raises(DomainError):
        observe(c, rule_decisions=decisions)


@pytest.mark.parametrize(
    "change,code",
    [
        ("package_head", "PACKAGE_REVISION_STALE"),
        ("inventory_head", "PACKAGE_INVENTORY_STALE"),
        ("identity", "PACKAGE_IDENTITY_STALE"),
        ("rule_set", "PACKAGE_RULE_SET_STALE"),
        ("source_status", "PACKAGE_SOURCE_NOT_EFFECTIVE"),
        ("source_known", "PACKAGE_SOURCE_NOT_EFFECTIVE"),
        ("source_expired", "PACKAGE_SOURCE_NOT_EFFECTIVE"),
        ("archived", "PROJECT_WORK_CLOSED"),
        ("generated", "PACKAGE_GENERATED_OUTPUT_UNPROVEN"),
    ],
)
def test_real_current_mismatches_are_explicitly_blocked(change, code):
    c = case()
    current = c["current"]
    if change == "package_head":
        current["package_heads"][uid(2)] = uid(999)
    elif change == "inventory_head":
        current["inventory_head"] = None
    elif change == "identity":
        current["current"]["identity"]["digest"] = "0" * 64
    elif change == "rule_set":
        current["current"]["current_rule_set_id"] = uid(999)
    elif change == "source_status":
        current["sources"][0]["status"] = "withdrawn"
    elif change == "source_known":
        current["sources"][0]["known_at"] = "2026-10-22T00:00:00Z"
    elif change == "source_expired":
        current["sources"][0]["valid_until"] = TIME
    elif change == "archived":
        current["lifecycle"]["archived_at"] = TIME
    else:
        current["generated_outputs"] = [
            {
                "package_role": "target",
                "member_id": "target",
                "document_version_id": uid(50),
                "admission": {"state": "blocked"},
            }
        ]
    card = observe(c, current=current)["gates"]["current_input"]
    assert card["state"] == "blocked" and code in card["codes"]


def test_all_known_human_coverage_declarations_cannot_establish_system_completeness():
    c = case()
    c["selection"]["coverage"] = declared_coverage(c)
    run = report(c)
    m = observe(
        c,
        run=run,
        inventory_proof=proof(c),
        rule_decisions=confirmation_rows(c),
        risk_history=history(run),
    )
    card = m["gates"]["core_coverage"]
    assert card["human_declared_count"] == 4
    assert card["state"] == "unknown" and card["inventory_complete"] is False
    assert not m["allowed"]


@pytest.mark.parametrize(
    "change", ["inventory", "authority", "frozen", "execution", "document", "range_boolean"]
)
def test_range_receipt_cannot_be_rebound_to_other_package_run_or_fake_full_range(change):
    c = case()
    run = report(c)
    value = proof(c)
    m = value["manifest"]
    if change == "inventory":
        m["inventory_digest"] = "0" * 64
    elif change == "authority":
        m["authority_digest"] = "0" * 64
    elif change == "frozen":
        m["frozen_digest"] = "0" * 64
    elif change == "execution":
        m["prepared"]["execution_input_id"] = uid(999)
    elif change == "document":
        m["documents"][0]["document_version_id"] = uid(999)
    else:
        m["extraction_range_proven"] = False
    resign(value)
    with pytest.raises(DomainError):
        observe(c, run=run, inventory_proof=value)


@pytest.mark.parametrize(
    "claim", [True, "verified", "verified_at_observation", "all_originals_verified"]
)
def test_bare_original_success_claim_never_creates_io_evidence(claim):
    with pytest.raises(DomainError):
        observe(case(), original_verification=claim)


def test_actual_reported_original_verification_failure_blocks_current_input():
    card = observe(case(), original_verification="failed")["gates"]["current_input"]
    assert card["state"] == "blocked"
    assert "ORIGINAL_BYTES_VERIFICATION_FAILED" in card["codes"]


def test_history_below_partial_read_limit_keeps_known_blockers_and_unknown_remainder():
    c = case()
    run = report(c, verdict="violated")
    card = observe(c, risk_history=history(run, complete=False))["gates"]["known_blocking_risks"]
    assert card["state"] == "blocked" and card["blocked_count"] == 4
    assert not card["history_complete"] and "RISK_HISTORY_INCOMPLETE" in card["codes"]


@pytest.mark.parametrize("limit", ["history_runs", "history_rows", "rule_decisions", "input_bytes"])
def test_capacity_overflow_rejects_whole_observation_without_silent_truncation(monkeypatch, limit):
    c = case()
    run = report(c)
    monkeypatch.setitem(gate.LIMITS, limit, 0)
    with pytest.raises(DomainError) as error:
        observe(c, risk_history=history(run), rule_decisions=confirmation_rows(c))
    assert error.value.code == "PACKAGE_SUBMISSION_GATE_LIMIT_EXCEEDED"


def test_recorded_observation_is_read_under_its_policy_without_rewriting_history(monkeypatch):
    c = case()
    recorded = gate.assess(c["selection"], observed_at=TIME)
    previous = recorded["manifest"]["policy_digest"]
    monkeypatch.setattr(gate, "policy_identity", lambda: {"digest": "0" * 64})
    assert gate.validate_view(recorded)["manifest"]["policy_digest"] == previous
    assert observe(c)["policy_digest"] == "0" * 64


def test_actual_f04_derived_inventory_and_withdrawal_keep_prior_machine_obligations():
    c = case()
    old = report(c, verdict="violated")
    next_case = derived(c)
    current = report(next_case, number=810)
    inventory_proof = proof(next_case)
    assert inventory_proof["manifest"]["human_derivation"]["state"] == "verified"
    m = observe(
        next_case,
        run=current,
        current=next_case["current"],
        inventory_proof=inventory_proof,
        rule_decisions=confirmation_rows(next_case),
        risk_history=history(old, current),
    )
    assert m["gates"]["mandatory_confirmation"]["state"] == "pass"
    assert len(m["gates"]["mandatory_confirmation"]["inactive_rule_ids"]) == 2
    assert m["gates"]["known_blocking_risks"]["blocked_count"] == 4
    assert m["gates"]["core_coverage"]["extraction_range_proven"] is True
    assert not m["inventory_complete"] and not m["allowed"]


def test_derived_inventory_proof_must_bind_the_actual_manual_chain_head():
    c = derived(case())
    value = proof(c)
    value["manifest"]["human_derivation"]["head_digest"] = "0" * 64
    resign(value)
    with pytest.raises(DomainError):
        observe(c, inventory_proof=value)


@pytest.mark.parametrize("change", ["count", "receipt", "read_set", "declared_pages"])
def test_extraction_proof_cannot_claim_frozen_evidence_or_range_with_inconsistent_facts(change):
    c = case()
    value = proof(c)
    m = value["manifest"]
    if change == "count":
        m["frozen_evidence_count"] += 1
    elif change == "receipt":
        m["receipt_digest"] = None
    elif change == "read_set":
        m["recorded_read_evidence_ids_digest"] = "0" * 64
    else:
        m["documents"][0]["declared_page_count"] = 1
        m["documents"][0]["all_pages_declared"] = False
        m["all_declared_pages_bound"] = m["extraction_range_proven"] = False
    resign(value)
    with pytest.raises(DomainError):
        observe(c, inventory_proof=value)


def test_frozen_physical_gap_is_visible_even_without_live_metadata_or_a_run():
    c = case()
    target = c["selection"]["target"]
    target["manifest"]["members"][0]["parts"][0]["first_page"] = 2
    resign(target)
    c["selection"]["inventory"]["manifest"]["package_digest"] = target["digest"]
    resign(c["selection"]["inventory"])
    card = observe(c)["gates"]["current_input"]
    assert card["state"] == "blocked"
    assert card["physical_page_gaps"] == [
        {"role": "target", "member_id": "target", "first_page": 1, "last_page": 1}
    ]


@pytest.mark.parametrize(
    "change", ["duplicate_document", "source_kind", "scope", "storage_eligible"]
)
def test_manifest_shape_and_digest_cannot_bypass_pure_package_invariants(change):
    c = case()
    target = c["selection"]["target"]
    if change == "duplicate_document":
        other = deepcopy(target["manifest"]["members"][0])
        other["member_id"] = "duplicate-document"
        other["parts"][0]["part_id"] = "another-part"
        target["manifest"]["members"].append(other)
    elif change == "source_kind":
        target["manifest"]["members"][0]["source_kind"] = "authority"
    elif change == "scope":
        target["manifest"]["members"][0]["scope"]["bid_id"] = uid(999)
    else:
        target["storage_eligible"] = False
    resign(target)
    c["selection"]["inventory"]["manifest"]["package_digest"] = target["digest"]
    resign(c["selection"]["inventory"])
    with pytest.raises(DomainError):
        observe(c)


@pytest.mark.parametrize(
    "field,value",
    [
        ("rule_decisions", None),
        ("risk_history", []),
        (
            "risk_history",
            {
                "complete": True,
                "package_runs": [],
                "human_decisions": [],
                "legacy_findings": [None],
            },
        ),
        ("current", {}),
        ("inventory_proof", {}),
        ("run", {}),
    ],
)
def test_malformed_observation_is_a_domain_error_not_an_implicit_empty_history(field, value):
    with pytest.raises(DomainError):
        observe(case(), **{field: value})


def test_openapi_export_resolves_self_contained_output_schema():
    value = gate.assess(case()["selection"], observed_at=TIME)
    Draft202012Validator.check_schema(gate.SCHEMA)
    schema = {
        "components": {"schemas": gate.SCHEMAS},
        "$ref": "#/components/schemas/PackageSubmissionGateView",
    }
    assert Draft202012Validator(schema).is_valid(value)
