"""Synthetic CPU projections, never provider/input authority or real scoring quality."""

import hashlib
import socket
from copy import deepcopy
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from packages.contracts import package_technical_features as contract
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_technical_features as features


def uid(number):
    return str(UUID(int=number))


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def projection():
    binding = {
        key: sha(key)
        for key in contract.BINDING["properties"]
        if key not in {"scope_id", "input_as_of"}
    }
    binding.update(scope_id=uid(1), input_as_of="2026-10-23T00:00:00.000000Z")
    catalog = []
    for i, text in enumerate(("合成正文：工期安排必须核对。", "")):
        catalog.append(
            {
                "evidence_id": uid(11 + i),
                "document_version_id": uid(21 + i),
                "parse_run_id": uid(31 + i),
                "physical_page": i + 1,
                "part_ids": ["正文" if i == 0 else "进度图"],
                "text": text,
                "text_digest": sha(text),
                "page_image_digest": sha(f"page-{i}"),
                "page_width": 100,
                "page_height": 50,
            }
        )
    rules, attempts = [], []
    for i in range(2):
        rule = {
            "rule_id": uid(51 + i),
            "rule_digest": sha(f"rule-{i}"),
            "semantic_input_digest": sha(f"packet-{i}"),
            "request_digest": sha(f"request-{i}"),
            "required_part_ids": ["正文", "进度图"],
            "band_ids": ["低", "中", "高"],
        }
        rules.append(rule)
        for slot in (1, 2, 3):
            citations = []
            for j, entry in enumerate(catalog):
                citations.append(
                    {
                        key: entry[key]
                        for key in (
                            "evidence_id",
                            "document_version_id",
                            "parse_run_id",
                            "physical_page",
                            "page_image_digest",
                        )
                    }
                )
                citations[-1].update(
                    quote="合成正文" if j == 0 else "", region=None if j == 0 else [0, 0, 50, 30]
                )
            judgment = {
                "status": "valid",
                "coverage": "complete",
                "band_id": "中" if slot == 3 else "高",
                "reason": "合成判断，仅用于机制验证。",
                "covered_part_ids": ["正文", "进度图"],
                "dimensions": {
                    "specificity": "uncertain" if slot == 2 else "supported",
                    "validity": ("supported", "unsupported", "uncertain")[slot - 1],
                    "consistency": "uncertain",
                },
                "evidence": citations,
            }
            attempts.append(
                {
                    "rule_id": rule["rule_id"],
                    "slot": slot,
                    "attempt": 1,
                    "call_id": uid(100 + i * 10 + slot),
                    "semantic_input_digest": rule["semantic_input_digest"],
                    "request_digest": rule["request_digest"],
                    "judgment_method_digest": binding["judgment_method_digest"],
                    "provider_profile_digest": binding["provider_profile_digest"],
                    "state": "succeeded",
                    "response_model": "synthetic-response-model",
                    "response_id": f"response-{i}-{slot}",
                    "response_digest": sha(f"response-{i}-{slot}"),
                    "judgment_digest": digest(judgment),
                    "judgment": judgment,
                }
            )
    return {
        "version": "package-technical-feature-projection/2",
        "binding": binding,
        "provider": {
            "provider_id": "synthetic",
            "model_alias": "synthetic-alias",
            "response_model": "synthetic-response-model",
        },
        "max_attempts_per_slot": 2,
        "rules": rules,
        "evidence_catalog": catalog,
        "attempts": attempts,
    }


def build(value):
    return features.build_features(
        value,
        expected_projection_digest=digest(value),
        expected_method_digest=features.method_digest(),
    )


def reseal(attempt):
    attempt["judgment_digest"] = (
        digest(attempt["judgment"]) if attempt["judgment"] is not None else None
    )


def expect_code(value, code):
    with pytest.raises(features.FeatureProjectionError) as error:
        build(value)
    assert error.value.code == code


def test_complete_three_slots_preserve_non_numeric_diagnostics_without_authority(
    projection, monkeypatch, record_testsuite_property
):
    record_testsuite_property("feature_method_digest", features.method_digest())
    record_testsuite_property("jsonschema_version", features.descriptor()["validator"]["version"])
    record_testsuite_property("feature_source_sha256", features.descriptor()["source_digest"])
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("network forbidden"))
    before = deepcopy(projection)
    result = build(projection)
    assert projection == before
    assert result["feature_coverage"] == "complete"
    assert result["complete_rule_count"] == result["expected_rule_count"] == 2
    row = result["items"][0]
    assert row["valid_slots"] == [1, 2, 3] and row["attempt_count"] == 3
    assert row["missing_valid_slots"] == row["unresolved_slots"] == []
    assert row["features"]["band_votes"] == [
        {"band_id": "低", "count": 0},
        {"band_id": "中", "count": 1},
        {"band_id": "高", "count": 2},
    ]
    assert row["features"]["modal_band_ids"] == ["高"]
    assert row["features"]["dimension_votes"]["validity"] == {
        "supported": 1,
        "unsupported": 1,
        "uncertain": 1,
    }
    assert row["features"]["dimension_votes"]["consistency"]["uncertain"] == 3
    assert row["cited_evidence_ids"] == [uid(11), uid(12)]
    assert result["raw_numeric_total"] is result["formal_prediction"] is None
    for key in (
        "input_authority_granted",
        "original_bytes_reverified",
        "visual_readability_verified",
        "formal_prediction_eligible",
        "training_eligible",
        "metrics_eligible",
    ):
        assert result[key] is False
    assert "THREE_CALLS_NOT_STATISTICAL_INDEPENDENCE" in result["limitations"]
    assert Draft202012Validator(contract.output_schema()).is_valid(result)
    assert result["digest"] == digest(
        {key: value for key, value in result.items() if key != "digest"}
    )


def test_deterministic_output_and_no_shared_mutable_source(projection):
    one, two = build(projection), build(deepcopy(projection))
    assert canonical(one) == canonical(two)
    one["binding"]["scope_id"] = uid(999)
    assert projection["binding"]["scope_id"] == uid(1)
    projection["attempts"].reverse()
    reordered = build(projection)
    assert reordered["items"] == two["items"]
    assert reordered["source_projection_digest"] != two["source_projection_digest"]


def test_band_tie_keeps_frozen_order_without_numeric_or_confidence(projection):
    for i, attempt in enumerate(projection["attempts"][:3]):
        attempt["judgment"]["band_id"] = ("高", "低", "中")[i]
        reseal(attempt)
    row = build(projection)["items"][0]["features"]
    assert row["modal_band_ids"] == ["低", "中", "高"]
    assert row["band_disagreement"] is True
    assert "confidence" not in row and "score" not in row


def test_no_band_authority_still_preserves_dimension_features(projection):
    projection["rules"][0]["band_ids"] = []
    for attempt in projection["attempts"][:3]:
        attempt["judgment"]["band_id"] = None
        reseal(attempt)
    row = build(projection)["items"][0]["features"]
    assert row["band_votes"] == row["modal_band_ids"] == []
    assert row["dimension_votes"]["specificity"]["supported"] == 2


def test_missing_slot_retains_other_rule_and_never_fills_zero(projection):
    projection["attempts"].pop(1)
    result = build(projection)
    assert result["feature_coverage"] == "partial" and result["complete_rule_count"] == 1
    assert result["items"][0]["features"] is None
    assert result["items"][0]["valid_slot_count"] == 2
    assert result["items"][0]["missing_valid_slots"] == [2]
    assert result["items"][1]["features"] is not None


def test_invalid_billed_attempt_is_not_a_valid_slot_and_a_distinct_retry_can_complete(projection):
    first = projection["attempts"][0]
    replacement = deepcopy(first)
    first["judgment"]["status"] = "invalid"
    reseal(first)
    partial = build(projection)
    assert partial["items"][0]["valid_slot_count"] == 2
    replacement.update(
        attempt=2,
        call_id=uid(999),
        response_id="replacement-response",
        response_digest=sha("replacement"),
    )
    projection["attempts"].append(replacement)
    row = build(projection)["items"][0]
    assert row["valid_slot_count"] == 3 and row["attempt_count"] == 4
    assert first["call_id"] not in row["call_ids"] and replacement["call_id"] in row["call_ids"]


def test_unknown_is_not_a_valid_slot_and_cannot_be_silently_retried(projection):
    attempt = projection["attempts"][0]
    replacement = deepcopy(attempt)
    attempt.update(
        state="unknown",
        judgment=None,
        judgment_digest=None,
        response_id=None,
        response_digest=None,
        response_model=None,
    )
    row = build(projection)["items"][0]
    assert row["unresolved_slots"] == row["missing_valid_slots"] == [1]
    assert row["features"] is None
    replacement.update(attempt=2, call_id=uid(999), response_id="replacement-response")
    projection["attempts"].append(replacement)
    expect_code(projection, "FEATURE_UNKNOWN_ATTEMPT_RETRIED")


def test_successful_slot_cannot_be_retried(projection):
    extra = deepcopy(projection["attempts"][0])
    extra.update(attempt=2, call_id=uid(999), response_id="replacement-response")
    projection["attempts"].append(extra)
    expect_code(projection, "FEATURE_SUCCESSFUL_SLOT_RETRIED")


@pytest.mark.parametrize(
    "field,code",
    [
        ("call_id", "FEATURE_CALL_REUSED_OR_RULE_UNKNOWN"),
        ("response_id", "FEATURE_PROVIDER_RESPONSE_REUSED"),
    ],
)
def test_same_receipt_cannot_count_across_rules(projection, field, code):
    projection["attempts"][3][field] = projection["attempts"][0][field]
    expect_code(projection, code)


@pytest.mark.parametrize(
    "field",
    [
        "semantic_input_digest",
        "request_digest",
        "judgment_method_digest",
        "provider_profile_digest",
        "response_model",
    ],
)
def test_attempt_must_match_the_frozen_rule_and_method_not_the_first_response(projection, field):
    projection["attempts"][0][field] = "changed" if field == "response_model" else sha("changed")
    expect_code(projection, "FEATURE_ATTEMPT_BINDING_MISMATCH")


@pytest.mark.parametrize(
    "field,value",
    [
        ("document_version_id", uid(999)),
        ("parse_run_id", uid(999)),
        ("physical_page", 9),
        ("page_image_digest", sha("other image")),
    ],
)
def test_quote_must_bind_original_document_parse_page_and_page_image(projection, field, value):
    attempt = projection["attempts"][0]
    attempt["judgment"]["evidence"][0][field] = value
    reseal(attempt)
    expect_code(projection, "FEATURE_CITATION_IDENTITY_MISMATCH")


@pytest.mark.parametrize(
    "region",
    [
        [-1, 0, 10, 10],
        [0, 0, 101, 10],
        [0, 0, 10, 51],
        [10, 0, 5, 10],
        [0, 0, 0, 10],
        [True, 0, 10, 10],
    ],
)
def test_graph_region_cannot_escape_or_use_boolean_coordinates(projection, region):
    attempt = projection["attempts"][0]
    attempt["judgment"]["evidence"][1]["region"] = region
    reseal(attempt)
    expect_code(
        projection,
        "FEATURE_PROJECTION_INVALID"
        if region[0] == -1 or type(region[0]) is bool
        else "FEATURE_REGION_OUT_OF_PAGE",
    )


def test_text_and_quote_digests_cannot_be_repaired_by_rehashing_the_outer_projection(projection):
    projection["evidence_catalog"][0]["text"] = "改写原文"
    expect_code(projection, "FEATURE_EVIDENCE_DIGEST_MISMATCH")


def test_fake_quote_cannot_count_as_a_valid_slot(projection):
    attempt = projection["attempts"][0]
    attempt["judgment"]["evidence"][0]["quote"] = "原文里没有这句话"
    reseal(attempt)
    expect_code(projection, "FEATURE_QUOTE_MISMATCH")


@pytest.mark.parametrize("field", ["coverage", "covered_part_ids", "band_id"])
def test_claimed_valid_needs_complete_declared_scope_and_an_allowed_band(projection, field):
    attempt = projection["attempts"][0]
    attempt["judgment"][field] = {
        "coverage": "partial",
        "covered_part_ids": ["正文"],
        "band_id": "任意档位",
    }[field]
    reseal(attempt)
    expect_code(projection, "FEATURE_VALID_JUDGMENT_INCOMPLETE")


def test_claimed_part_coverage_requires_actual_citations_for_each_part(projection):
    attempt = projection["attempts"][0]
    attempt["judgment"]["evidence"].pop()
    reseal(attempt)
    expect_code(projection, "FEATURE_REQUIRED_PART_UNSUPPORTED")


@pytest.mark.parametrize("field", ["official_score", "training_eligible", "execution_mode", "real"])
def test_no_label_or_qualification_switch_is_accepted(projection, field):
    projection[field] = True
    expect_code(projection, "FEATURE_PROJECTION_INVALID")


def test_expected_projection_and_feature_method_are_separate_owned_bindings(projection):
    with pytest.raises(features.FeatureProjectionError, match="FEATURE_PROJECTION_DIGEST_MISMATCH"):
        features.build_features(
            projection,
            expected_projection_digest=sha("other"),
            expected_method_digest=features.method_digest(),
        )
    with pytest.raises(features.FeatureProjectionError, match="FEATURE_METHOD_MISMATCH"):
        features.build_features(
            projection,
            expected_projection_digest=digest(projection),
            expected_method_digest=sha("old"),
        )


def test_duplicate_rules_and_evidence_are_rejected(projection):
    projection["rules"].append(deepcopy(projection["rules"][0]))
    expect_code(projection, "FEATURE_RULE_REUSED")
    projection["rules"].pop()
    projection["evidence_catalog"].append(deepcopy(projection["evidence_catalog"][0]))
    expect_code(projection, "FEATURE_EVIDENCE_REUSED")


def test_attempt_sequence_and_successful_raw_receipt_are_required(projection):
    projection["attempts"][0]["attempt"] = 2
    expect_code(projection, "FEATURE_ATTEMPT_SEQUENCE_INVALID")
    projection["attempts"][0]["attempt"] = 1
    projection["attempts"][0]["judgment_digest"] = sha("other")
    expect_code(projection, "FEATURE_RESPONSE_RECEIPT_INCOMPLETE")


def test_float_and_legacy_projection_do_not_enter_v2(projection):
    projection["evidence_catalog"][0]["page_width"] = 100.0
    with pytest.raises(features.FeatureProjectionError, match="FEATURE_PROJECTION_INVALID"):
        features.build_features(
            projection,
            expected_projection_digest=sha("owned input"),
            expected_method_digest=features.method_digest(),
        )
    projection["evidence_catalog"][0]["page_width"] = 100
    projection["version"] = "package-technical-judgments/1"
    expect_code(projection, "FEATURE_PROJECTION_INVALID")


def test_cannot_drop_a_rule_from_an_already_frozen_owned_projection(projection):
    frozen_digest = digest(projection)
    removed = projection["rules"].pop()
    projection["attempts"] = [
        row for row in projection["attempts"] if row["rule_id"] != removed["rule_id"]
    ]
    with pytest.raises(features.FeatureProjectionError, match="FEATURE_PROJECTION_DIGEST_MISMATCH"):
        features.build_features(
            projection,
            expected_projection_digest=frozen_digest,
            expected_method_digest=features.method_digest(),
        )


@pytest.mark.parametrize("state", ["failed", "unknown"])
def test_unresolved_receipt_cannot_claim_a_successful_judgment(projection, state):
    projection["attempts"][0]["state"] = state
    expect_code(projection, "FEATURE_UNRESOLVED_HAS_JUDGMENT")


@pytest.mark.parametrize(
    "field", ["judgment", "judgment_digest", "response_digest", "response_id", "response_model"]
)
def test_successful_slot_needs_the_complete_receipt(projection, field):
    projection["attempts"][0][field] = None
    expect_code(projection, "FEATURE_RESPONSE_RECEIPT_INCOMPLETE")


def test_empty_attempts_are_partial_not_zero_scores(projection):
    projection["attempts"] = []
    result = build(projection)
    assert result["feature_coverage"] == "partial" and result["complete_rule_count"] == 0
    assert all(
        row["missing_valid_slots"] == [1, 2, 3] and row["features"] is None
        for row in result["items"]
    )
    assert result["raw_numeric_total"] is None


def test_size_bound_rejects_without_truncating_or_calling_a_slot(projection, monkeypatch):
    original = deepcopy(projection)
    monkeypatch.setattr(features, "MAX_BYTES", len(canonical(projection)) - 1)
    monkeypatch.setattr(
        features, "_valid", lambda *_: pytest.fail("must reject before reading slots")
    )
    expect_code(projection, "FEATURE_PROJECTION_TOO_LARGE")
    assert projection == original


def test_schema_copies_cannot_mutate_the_frozen_contract():
    value = contract.schema()
    value["properties"]["version"]["const"] = "other"
    assert (
        contract.schema()["properties"]["version"]["const"]
        == "package-technical-feature-projection/2"
    )
    descriptor = features.descriptor()
    assert descriptor["valid_slots_required"] == 3 and descriptor["validator"]["version"]


@pytest.mark.parametrize(
    "field,value",
    [("page_image_digest", sha("different page")), ("page_width", 99), ("page_height", 49)],
)
def test_one_frozen_physical_page_cannot_have_conflicting_image_identities(
    projection, field, value
):
    other = deepcopy(projection["evidence_catalog"][0])
    other["evidence_id"] = uid(999)
    other[field] = value
    projection["evidence_catalog"].append(other)
    expect_code(projection, "FEATURE_PAGE_IMAGE_CONTRADICTION")


def test_multiple_blocks_can_share_the_exact_same_frozen_page(projection):
    other = deepcopy(projection["evidence_catalog"][0])
    other.update(
        evidence_id=uid(999),
        text="同一原页的另一个证据块",
        text_digest=sha("同一原页的另一个证据块"),
    )
    projection["evidence_catalog"].append(other)
    assert build(projection)["feature_coverage"] == "complete"
