"""Synthetic policy cases; no model, original storage or database authority implied."""

from copy import deepcopy

import pytest
from package_rule_correction_cases import uid
from test_package_technical_scope import synthetic_scope

from packages.contracts import package_technical_eligibility_api as contract
from packages.domain import package_technical_eligibility as policy
from packages.domain import package_technical_scope as scopes
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha

FROZEN = "2026-01-02T00:00:00+00:00"
SUBMITTED = "2026-01-03T00:00:00+00:00"
KNOWN = "2026-01-04T00:00:00+00:00"
OBSERVED = "2026-01-05T00:00:00+00:00"
DECLARATION = "技术总分满分为60分，量尺为未加权原始分。"


def case():
    snapshot, request = synthetic_scope()
    document = next(row for row in snapshot["documents"] if row["package_role"] == "authority")
    block = document["blocks"][0]
    block.update(text_content=DECLARATION, digest=sha(DECLARATION.encode()))
    preview = scopes.prepare(snapshot, request)
    saved = scopes.freeze(
        preview,
        identity=uid(901),
        actor=uid(902),
        command=uid(903),
        frozen_at=FROZEN,
        verified_at=FROZEN,
        originals=snapshot["originals"],
    )
    source = next(
        row
        for row in snapshot["source_snapshot"]
        if row["source_id"] == row["ancestor_id"]
        and row["document_version_id"] == document["document_version_id"]
        and row["source_id"]
        != next(
            row["ancestor_id"]
            for row in snapshot["source_snapshot"]
            if row["source_id"] != row["ancestor_id"]
            and row["document_version_id"] == document["document_version_id"]
        )
    )
    scale = {
        "id": uid(904),
        "bid_id": preview["manifest"]["scope"]["bid_id"],
        "purpose": "current_prebid",
        "submission_id": None,
        "identity": deepcopy(snapshot["target"]["identity"]),
        "technical_maximum": "60.00",
        "scale_description": "未加权原始分",
        "aggregation": {"status": "unknown", "description": "合成场景无可执行聚合规则"},
        "maximum_usable": True,
        "current_applicability": True,
        "is_current_head": True,
        "state": "confirmed",
        "decision": {"state": "confirmed"},
        "evidence_refs": [
            {
                "id": uid(905),
                "document_version_id": document["document_version_id"],
                "blob_digest": document["file_digest"],
                "parse_id": document["parse"]["parse_run_id"],
                "evidence_id": block["id"],
                "physical_page": block["physical_page"],
                "evidence_digest": block["digest"],
                "source_id": source["source_id"],
                "source_revision": source["revision"],
                "quote": DECLARATION,
                "supported_fields": ["technical_maximum", "scale_description"],
            }
        ],
    }
    return snapshot, saved, scale


def codes(value):
    return {row["code"] for row in value["blockers"]}


def current(saved, snapshot, maximum=None):
    return policy.scoring_context(
        saved, snapshot, maximum or policy.missing_scale("current_prebid"), observed_at=OBSERVED
    )


def test_exact_denominator_does_not_grant_aggregation_judgments_or_score():
    snapshot, saved, scale = case()
    original = deepcopy((snapshot, saved, scale))
    maximum = policy.scale_assessment(saved, snapshot, scale, purpose="current_prebid")
    value = current(saved, snapshot, maximum)
    assert maximum["technical_maximum"] == "60.00" and maximum["maximum_usable"]
    assert maximum["aggregation_usable"] is False
    assert value["current_input"]["state"] == "matched"
    assert value["judgments"]["required_valid_independent"] == 3
    assert value["judgments"]["recorded_valid_independent"] == 0
    assert value["numeric_prediction"] is None
    assert all(value[key] is False for key in scopes.FLAGS)
    assert {
        "TECHNICAL_AGGREGATION_NOT_EXECUTABLE",
        "VISUAL_COMPLETENESS_UNPROVEN",
        "REQUIRED_RANGE_UNPROVEN",
        "THREE_VALID_INDEPENDENT_JUDGMENTS_REQUIRED",
    } <= codes(value)
    assert (snapshot, saved, scale) == original


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(bid_id=uid(800)),
        lambda s: s.update(purpose="historical_backtest", submission_id=uid(801)),
        lambda s: s["identity"].update(lot_id=uid(802)),
        lambda s: s["identity"].update(round_id=uid(803)),
        lambda s: s["identity"].update(bidder_id=uid(804)),
        lambda s: s.update(is_current_head=False),
        lambda s: s.update(maximum_usable=False, technical_maximum=None),
        lambda s: s["decision"].update(state="withdrawn"),
        lambda s: s.update(technical_maximum="80"),
        lambda s: s.update(scale_description="已加权技术总分"),
        lambda s: s["evidence_refs"][0].update(parse_id=uid(805)),
        lambda s: s["evidence_refs"][0].update(document_version_id=uid(806)),
        lambda s: s["evidence_refs"][0].update(physical_page=2),
        lambda s: s["evidence_refs"][0].update(quote="60"),
        lambda s: s["evidence_refs"][0].update(source_revision=2),
        lambda s: s["evidence_refs"][0].update(source_id=uid(807)),
        lambda s: s["evidence_refs"].clear(),
    ],
)
def test_maximum_cannot_be_borrowed_from_other_scope_or_fragment(change):
    snapshot, saved, scale = case()
    change(scale)
    value = policy.scale_assessment(saved, snapshot, scale, purpose="current_prebid")
    assert value["state"] == "mismatched" and value["maximum_usable"] is False
    assert value["technical_maximum"] is None and value["aggregation_usable"] is False


def test_uninstalled_authority_does_not_infer_maximum_from_scoring_clause_sum():
    snapshot, saved, _ = case()
    maximum = policy.missing_scale("current_prebid", uid(904), configured=False)
    value = current(saved, snapshot, maximum)
    assert maximum["state"] == "not_configured" and maximum["technical_maximum"] is None
    assert "TECHNICAL_SCALE_AUTHORITY_NOT_CONFIGURED" in codes(value)
    assert value["numeric_prediction"] is None


def test_current_source_change_preserves_historical_record_and_blocks_new_use():
    snapshot, saved, _ = case()
    original = deepcopy(saved)
    snapshot["source_snapshot"][0]["revision"] += 1
    snapshot["blocking_reasons"].append(policy.reason("SOURCE_UNAVAILABLE", "synthetic withdrawal"))
    value = current(saved, snapshot)
    assert value["current_input"]["state"] == "changed"
    assert {"TECHNICAL_INPUT_CHANGED", "SOURCE_UNAVAILABLE"} <= codes(value)
    assert saved == original


def test_unknown_current_input_returns_explicit_unavailable_not_empty_complete():
    _, saved, _ = case()
    value = current(saved, None)
    assert value["current_input"]["state"] == "unavailable"
    assert value["current_input"]["current_context_digest"] is None
    assert value["coverage"]["state"] != "complete"


def historical_case():
    snapshot, saved, _ = case()
    preview = saved["manifest"]["preview"]["manifest"]
    submission = {
        "id": uid(920),
        "subject_kind": "bid_package",
        "submitted_at": SUBMITTED,
        "created_at": SUBMITTED,
    }
    manifest = {
        "subject": {
            "kind": "bid_package",
            "bid_id": preview["scope"]["bid_id"],
            "package_id": preview["scope"]["package_id"],
            "revision_id": preview["scope"]["revision_id"],
            "package_digest": preview["basis"]["package_digest"],
        },
        "selection": {key: snapshot[key] for key in ("target", "authority", "inventory")},
        "package_identity": deepcopy(snapshot["target"]["identity"]),
    }
    binding = {"manifest": manifest, "digest": digest(manifest)}
    official = {
        "outcome_id": uid(921),
        "score_kind": "technical_total",
        "technical_value": "0",
        "reported_maximum": "60",
        "label_known_at": KNOWN,
        "current_association": True,
        "reasons": [],
    }
    return {
        "saved": saved,
        "snapshot": snapshot,
        "submission": submission,
        "binding": binding,
        "official": official,
        "denominator": policy.missing_scale("historical_backtest"),
        "observed_at": OBSERVED,
        "submission_current": True,
    }


def test_native_official_zero_is_separate_from_denominator_and_never_grants_sample():
    kwargs = historical_case()
    result = policy.sample_context(**kwargs)
    assert result["submission"]["matches_scope"]
    assert result["original_scope_precedes_submission"] and result["source_metadata_matches"]
    assert result["official_result"]["technical_value"] == "0"
    assert result["denominator"]["technical_maximum"] is None
    assert result["sample_state"] == "pending" and not result["sample_created"]
    assert result["timing"]["historical_as_of"] == SUBMITTED
    assert result["timing"]["label_known_at"] == KNOWN
    assert result["timing"]["training_frozen_at"] is None
    assert result["timing"]["submission_split_at"] is None
    assert result["timing"]["label_available_as_of"] is None
    assert result["training_eligible"] is False


@pytest.mark.parametrize("key", ["package_id", "revision_id", "package_digest"])
def test_historical_binding_must_match_original_exact_package(key):
    kwargs = historical_case()
    kwargs["binding"]["manifest"]["subject"][key] = "0" * 64 if key.endswith("digest") else uid(930)
    value = policy.sample_context(**kwargs)
    assert not value["submission"]["matches_scope"]
    assert "SAMPLE_EXACT_SCOPE_MISMATCH" in codes(value)


def test_late_freeze_and_future_ancestor_cannot_be_backdated_from_current_read():
    kwargs = historical_case()
    kwargs["submission"]["submitted_at"] = "2025-12-31T00:00:00+00:00"
    value = policy.sample_context(**kwargs)
    assert not value["original_scope_precedes_submission"]
    assert {
        "SAMPLE_SCOPE_FROZEN_AFTER_SUBMISSION",
        "SAMPLE_HISTORICAL_SOURCE_TIME_UNPROVEN",
    } <= codes(value)
    assert value["timing"]["scope_frozen_at"] == FROZEN


def test_history_does_not_mistake_new_package_head_for_original_input_but_keeps_source_check():
    kwargs = historical_case()
    kwargs["snapshot"]["blocking_reasons"] = [
        policy.reason("AFTER_SUBMISSION", "submitted"),
        policy.reason("PACKAGE_HEAD_CHANGED", "new current package"),
        policy.reason("SOURCE_UNAVAILABLE", "withdrawn original"),
    ]
    value = policy.sample_context(**kwargs)
    assert value["submission"]["matches_scope"]
    assert "AFTER_SUBMISSION" not in codes(value) and "PACKAGE_HEAD_CHANGED" not in codes(value)
    assert "SOURCE_UNAVAILABLE" in codes(value)


def test_old_current_scale_cannot_silently_be_repurposed_as_historical():
    snapshot, saved, scale = case()
    maximum = policy.scale_assessment(
        saved, snapshot, scale, purpose="historical_backtest", submission_id=uid(920)
    )
    assert not maximum["maximum_usable"]
    assert "TECHNICAL_SCALE_SCOPE_MISMATCH" in {r["code"] for r in maximum["reasons"]}


def test_response_contract_cannot_promote_flags_or_add_client_supplied_label_to_current():
    snapshot, saved, _ = case()
    value = current(saved, snapshot)
    for key in scopes.FLAGS:
        altered = deepcopy(value)
        altered[key] = True
        with pytest.raises(DomainError):
            contract.validate("PackageTechnicalScoringContext", altered)
    with pytest.raises(DomainError):
        contract.validate("PackageTechnicalScoringContext", value | {"official_label": "60"})


def test_optional_paths_publish_only_their_closed_reachable_contracts():
    empty = {"paths": {}}
    contract.extend_openapi(empty)
    assert empty == {"paths": {}}
    base = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}"
    actual = {"paths": {base + "/scoring-context": {"get": {}}}}
    contract.extend_openapi(actual)
    assert set(actual["components"]["schemas"]) == {"PackageTechnicalScoringContext"}
    before = deepcopy(actual)
    contract.extend_openapi(actual)
    assert actual == before
