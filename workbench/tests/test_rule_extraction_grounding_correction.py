"""Synthetic extraction mechanism checks; no provider, database or paid calls."""

import json
from contextlib import nullcontext
from copy import deepcopy

import pytest

from apps.worker import review_handlers as handlers
from packages.domain import reviews
from packages.domain.runtime import DomainError, sha

BID = "00000000-0000-4000-8000-000000000001"
EVIDENCE = "00000000-0000-4000-8000-000000000002"
SOURCE = "SYNTHETIC 工期90天。如需延期，必须书面批准。紧急情况除外。"


def extraction():
    return {
        "rules": [
            {
                "kind": "mandatory",
                "statement": "工期90天。",
                "conditions": ["如需延期，必须书面批准。"],
                "exceptions": ["紧急情况除外。"],
                "scope": {"bid_id": BID, "description": "SYNTHETIC 本项目"},
                "maximum": None,
                "bands": [],
                "evidence_quotes": [{"evidence_id": EVIDENCE, "quote": SOURCE}],
            }
        ],
        "ambiguities": [],
        "read_evidence_ids": [EVIDENCE],
    }


@pytest.fixture
def prepare(monkeypatch):
    documents = [
        {
            "role": "tender",
            "document_version_id": "00000000-0000-4000-8000-000000000003",
            "coverage": "complete",
            "gaps": [],
            "pages": [],
            "blocks": [{"id": EVIDENCE, "text_content": SOURCE}],
        }
    ]
    method = {"synthetic": "grounding-correction-test"}
    descriptor = {
        "method_digest": sha(method),
        "base_rule_set_id": None,
        "bid_id": BID,
        "source_refs": [],
        "documents": documents,
        "source_closure": [],
        "as_of": "2030-01-01",
        "material_snapshot_id": "synthetic-material",
    }
    monkeypatch.setattr(reviews, "method_profile", lambda: method)
    monkeypatch.setattr(handlers, "connection", lambda *args: nullcontext(None))
    monkeypatch.setattr(handlers, "fetch", lambda *args: {})
    monkeypatch.setattr(handlers, "read_json_blob", lambda blob: descriptor)
    monkeypatch.setattr(handlers, "restore_documents", lambda *args: deepcopy(documents))
    monkeypatch.setattr(handlers, "source_closure", lambda *args: [])
    monkeypatch.setattr(handlers, "effective_at", lambda *args: None)
    monkeypatch.setattr(handlers, "verify_bytes", lambda *args: None)
    message = {"bid_id": BID, "payload_ref": "synthetic", "operation_id": "operation"}
    lease = {"owner": "synthetic-owner", "fence": 1}
    calls = []

    def run(responses):
        start = len(calls)

        def generate(actual_message, actual_lease, **kwargs):
            assert actual_message is message
            assert actual_lease is lease
            assert kwargs["max_tokens"] == 8192
            assert kwargs.get("purpose", "core_review") == "core_review"
            assert kwargs["json_schema"] == handlers.extraction_schema()
            calls.append(deepcopy(kwargs))
            response = responses[len(calls) - start - 1]
            if isinstance(response, Exception):
                raise response
            return {"data": deepcopy(response)}, f"call-{len(calls)}"

        monkeypatch.setattr(handlers.model_calls, "generate", generate)
        return handlers.compute_prepare(message, lease)

    return run, calls


def test_valid_first_response_has_no_correction(prepare):
    run, calls = prepare
    result = run([extraction()])
    assert len(calls) == 1
    assert result["model_call_id"] == "call-1"
    assert result["coverage"] == "complete"


@pytest.mark.parametrize("field", ["statement", "conditions", "exceptions"])
def test_one_correction_reports_exact_violation_and_original_sources(prepare, field):
    run, calls = prepare
    bad = extraction()
    bad["rules"][0][field] = "推断原文" if field == "statement" else ["推断原文"]
    original = deepcopy(bad)
    result = run([bad, extraction()])
    assert bad == original  # No local deletion, normalization or rewriting.
    assert [call["logical_key"] for call in calls] == [
        "extract-rules",
        "extract-rules-grounding-correction-1",
    ]
    request = calls[1]["messages"]
    assert request[:2] == calls[0]["messages"]
    assert (
        json.loads(request[1]["content"])["documents"][0]["evidence_blocks"][0]["text_content"]
        == SOURCE
    )
    assert json.loads(request[2]["content"]) == original
    feedback = json.loads(request[3]["content"][request[3]["content"].index("{") :])
    assert feedback == {
        "error_code": "RULE_STATEMENT_UNGROUNDED"
        if field == "statement"
        else "RULE_CONDITION_UNGROUNDED",
        "rule_index": 0,
        "field": "statement" if field == "statement" else f"{field}[0]",
    }
    assert result["model_call_id"] == "call-2"
    assert result["items"][0]["conditions"] == extraction()["rules"][0]["conditions"]


def test_second_bad_response_fails_without_third_call(prepare):
    run, calls = prepare
    first, second = extraction(), extraction()
    first["rules"][0]["conditions"] = ["不是原文"]
    second["rules"][0]["conditions"] = ["仍然不是原文"]
    with pytest.raises(DomainError) as caught:
        run([first, second])
    assert caught.value.code == "RULE_CONDITION_UNGROUNDED"
    assert len(calls) == 2


@pytest.mark.parametrize("fault", ["quote", "scope", "range", "band", "schema"])
def test_other_validation_errors_do_not_trigger_correction(prepare, fault):
    run, calls = prepare
    bad = extraction()
    rule = bad["rules"][0]
    if fault == "quote":
        rule["evidence_quotes"][0]["quote"] = "未提供的证据"
    elif fault == "scope":
        rule["scope"]["bid_id"] = EVIDENCE
    elif fault == "range":
        bad["read_evidence_ids"] = []
    elif fault == "band":
        rule.update(kind="scoring", maximum="10", bands=[])
    else:
        rule["statement"] = ""
    with pytest.raises(DomainError):
        run([bad])
    assert len(calls) == 1


@pytest.mark.parametrize(
    "code",
    [
        "MODEL_CALL_BUDGET_EXCEEDED",
        "MODEL_EXECUTION_STALE",
        "MODEL_CALL_REQUIRES_RECONCILIATION",
        "MODEL_PURPOSE_NOT_ALLOWED",
    ],
)
def test_correction_admission_failure_is_not_retried_or_bypassed(prepare, code):
    run, calls = prepare
    bad = extraction()
    bad["rules"][0]["conditions"] = ["未逐字引用"]
    error = DomainError(code, "synthetic admission rejection")
    with pytest.raises(DomainError) as caught:
        run([bad, error])
    assert caught.value is error
    assert len(calls) == 2


def test_provider_failure_is_not_retried(prepare):
    run, calls = prepare
    error = DomainError("MODEL_PROVIDER_FAILED", "synthetic")
    with pytest.raises(DomainError) as caught:
        run([error])
    assert caught.value is error
    assert len(calls) == 1


def test_correction_still_requires_all_original_evidence(prepare):
    run, calls = prepare
    bad, corrected = extraction(), extraction()
    bad["rules"][0]["conditions"] = ["未逐字引用"]
    corrected["read_evidence_ids"] = []
    with pytest.raises(DomainError) as caught:
        run([bad, corrected])
    assert caught.value.code == "EXTRACTION_RANGE_INCOMPLETE"
    assert len(calls) == 2


def test_feedback_identifies_later_rule_and_exact_exception_index(prepare):
    run, calls = prepare
    bad = extraction()
    bad["rules"].append(deepcopy(bad["rules"][0]))
    bad["rules"][1]["exceptions"].append("未逐字引用")
    corrected = deepcopy(bad)
    corrected["rules"][1]["exceptions"][1] = "紧急情况除外。"
    run([bad, corrected])
    feedback_text = calls[1]["messages"][-1]["content"]
    feedback = json.loads(feedback_text[feedback_text.index("{") :])
    assert feedback["rule_index"] == 1
    assert feedback["field"] == "exceptions[1]"


def test_same_frozen_inputs_recreate_identical_ledger_request_identities(prepare):
    run, calls = prepare
    bad = extraction()
    bad["rules"][0]["conditions"] = ["未逐字引用"]
    run([bad, extraction()])
    run([bad, extraction()])
    # Actual successful-result reuse/unknown-call rejection belong to generate's
    # ledger. This verifies both requests reach it with identical stable identities.
    assert calls[:2] == calls[2:]


def test_changed_frozen_method_fails_before_any_model_call(prepare, monkeypatch):
    run, calls = prepare
    monkeypatch.setattr(reviews, "method_profile", lambda: {"changed": True})
    with pytest.raises(DomainError) as caught:
        run([extraction()])
    assert caught.value.code == "REVIEW_METHOD_PROFILE_CHANGED"
    assert calls == []


@pytest.mark.parametrize(
    "attack",
    [
        "drop_rule",
        "drop_condition",
        "drop_exception",
        "clear_ambiguity",
        "rewrite_valid_statement",
        "rewrite_valid_condition",
        "rewrite_valid_exception",
        "change_scope",
        "change_kind",
        "change_maximum",
        "change_bands",
        "swap_rules",
        "drop_evidence",
        "add_evidence",
        "replace_evidence",
    ],
)
def test_correction_cannot_discard_requirements_or_change_valid_content(prepare, attack):
    run, calls = prepare
    bad = extraction()
    # One actual defective excerpt must not authorize changing other requirements.
    bad["rules"][0]["conditions"].append("未经原文支持的条件")
    bad["ambiguities"] = ["SYNTHETIC 补遗是否改变原工期需明确核对"]
    second = deepcopy(bad["rules"][0])
    second["statement"] = "必须书面批准。"
    bad["rules"].append(second)
    corrected = deepcopy(bad)
    for rule in corrected["rules"]:
        rule["conditions"][1] = "必须书面批准。"
    rule = corrected["rules"][0]
    if attack == "drop_rule":
        corrected["rules"].pop()
    elif attack == "drop_condition":
        rule["conditions"].pop()
    elif attack == "drop_exception":
        rule["exceptions"].clear()
    elif attack == "clear_ambiguity":
        corrected["ambiguities"].clear()
    elif attack == "rewrite_valid_statement":
        rule["statement"] = "工期90天"
    elif attack == "rewrite_valid_condition":
        rule["conditions"][0] = "必须书面批准。"
    elif attack == "rewrite_valid_exception":
        rule["exceptions"][0] = "紧急情况"
    elif attack == "change_scope":
        rule["scope"]["description"] = "仅部分项目"
    elif attack == "change_kind":
        rule["kind"] = "advisory"
    elif attack == "change_maximum":
        rule["maximum"] = "90"
    elif attack == "change_bands":
        rule["bands"] = [{"description": "工期90天。", "points": "90", "evidence_ids": [EVIDENCE]}]
    elif attack == "swap_rules":
        corrected["rules"].reverse()
    elif attack == "drop_evidence":
        rule["evidence_quotes"].clear()
    elif attack == "add_evidence":
        rule["evidence_quotes"].append(deepcopy(rule["evidence_quotes"][0]))
    else:
        rule["evidence_quotes"][0]["evidence_id"] = BID
    with pytest.raises(DomainError) as caught:
        run([bad, corrected])
    assert caught.value.code == "EXTRACTION_CORRECTION_STRUCTURE_CHANGED"
    assert len(calls) == 2


def test_correction_may_expand_quote_within_original_evidence_and_keep_ambiguity(prepare):
    run, calls = prepare
    bad, corrected = extraction(), extraction()
    bad["rules"][0]["evidence_quotes"][0]["quote"] = "工期90天。"
    bad["ambiguities"] = corrected["ambiguities"] = ["SYNTHETIC 需确认补遗范围"]
    result = run([bad, corrected])
    assert len(calls) == 2
    assert result["coverage"] == "conflict"
    assert result["ambiguities"] == bad["ambiguities"]
    assert result["items"][0]["statement"] == bad["rules"][0]["statement"]


def test_quote_adjustment_still_must_match_actual_original_evidence(prepare):
    run, calls = prepare
    bad, corrected = extraction(), extraction()
    bad["rules"][0]["conditions"] = ["未逐字引用"]
    corrected["rules"][0]["evidence_quotes"][0]["quote"] += "伪造补充条款"
    with pytest.raises(DomainError) as caught:
        run([bad, corrected])
    assert caught.value.code == "RULE_QUOTE_INVALID"
    assert len(calls) == 2
