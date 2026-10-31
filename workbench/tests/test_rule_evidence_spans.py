"""Synthetic same-page source-span proofs; no external services or model calls."""

from copy import deepcopy
from pathlib import Path

import pytest

from apps.worker import review_handlers as handlers
from packages.domain import reviews
from packages.domain.evidence_spans import unique_cross_block_span
from packages.domain.runtime import DomainError

BID = "00000000-0000-4000-8000-000000000001"
IDS = ["00000000-0000-4000-8000-000000000002", "00000000-0000-4000-8000-000000000003"]


def source():
    return [
        {
            "document_version_id": "doc",
            "parse_id": "parse",
            "blocks": [
                {"id": IDS[0], "physical_page": 1, "ordinal": 5, "text_content": "要求。施工前"},
                {"id": IDS[1], "physical_page": 1, "ordinal": 6, "text_content": "完成检查。"},
            ],
        }
    ]


def extraction():
    return {
        "rules": [
            {
                "kind": "mandatory",
                "statement": "要求。",
                "conditions": ["施工前完成检查。"],
                "exceptions": [],
                "scope": {"bid_id": BID, "description": "合成"},
                "maximum": None,
                "bands": [],
                "evidence_quotes": [
                    {"evidence_id": IDS[0], "quote": "要求。施工前"},
                    {"evidence_id": IDS[1], "quote": "完成检查。"},
                ],
            }
        ],
        "ambiguities": [],
        "read_evidence_ids": IDS,
    }


def test_exact_adjacent_proof_preserves_raw_character_ranges_and_receipt_identity():
    docs = source()
    proofs = []
    items = handlers._validated_extraction(
        extraction(), BID, docs[0]["blocks"], span_documents=docs, provenance=proofs
    )
    assert len(items) == len(proofs) == 1
    assert proofs[0] == {
        "rule_index": 0,
        "rule_semantic_key": handlers.semantic_key(items[0]),
        "field": "conditions",
        "position": 0,
        "document_version_id": "doc",
        "parse_id": "parse",
        "physical_page": 1,
        "blocks": [
            {"evidence_id": IDS[0], "ordinal": 5, "start": 3, "end": 6},
            {"evidence_id": IDS[1], "ordinal": 6, "start": 0, "end": 5},
        ],
    }


@pytest.mark.parametrize(
    "fault", ["page", "ordinal", "document", "uncited", "ambiguous", "punctuation", "space"]
)
def test_never_join_unproven_sources_or_alter_characters(fault):
    docs = source()
    text = "施工前完成检查。"
    cited = set(IDS)
    if fault == "page":
        docs[0]["blocks"][1]["physical_page"] = 2
    elif fault == "ordinal":
        docs[0]["blocks"][1]["ordinal"] = 7
    elif fault == "document":
        second = docs[0]["blocks"].pop()
        docs.append({"document_version_id": "other", "parse_id": "other", "blocks": [second]})
    elif fault == "uncited":
        cited.remove(IDS[1])
    elif fault == "ambiguous":
        other = deepcopy(docs[0])
        other["document_version_id"] = "other"
        other["parse_id"] = "other"
        docs.append(other)
    elif fault == "punctuation":
        text = "施工前完成检查，"
    elif fault == "space":
        text = "施工前 完成检查。"
    assert unique_cross_block_span(docs, text, cited) is None


def test_valid_span_cannot_be_changed_during_model_correction():
    before = extraction()
    after = deepcopy(before)
    after["rules"][0]["conditions"][0] = "施工前完成检查，"
    with pytest.raises(DomainError, match="EXTRACTION_CORRECTION_STRUCTURE_CHANGED"):
        handlers._check_correction_structure(before, after, span_documents=source())


def test_cross_document_newline_does_not_gain_grounding_from_quote_join():
    result = extraction()
    result["rules"][0]["conditions"] = ["施工前\n完成检查。"]
    with pytest.raises(DomainError, match="RULE_CONDITION_UNGROUNDED"):
        handlers._validated_extraction(result, BID, source()[0]["blocks"])


@pytest.mark.parametrize("text", ["前完成检查。", "施工前完成检查"])
def test_exact_but_truncated_clause_is_not_accepted(text):
    assert unique_cross_block_span(source(), text, set(IDS)) is None


def test_spans_cannot_use_changed_source_blocks():
    docs = source()
    altered = deepcopy(docs)
    altered[0]["blocks"][1]["text_content"] = "完成检查。伪造"
    with pytest.raises(DomainError, match="RULE_CONDITION_UNGROUNDED"):
        handlers._validated_extraction(
            extraction(), BID, docs[0]["blocks"], span_documents=altered, provenance=[]
        )


def test_unproven_later_condition_does_not_publish_partial_provenance():
    docs = source()
    result = extraction()
    result["rules"][0]["conditions"].append("模型新增的条件。")
    proofs = []
    with pytest.raises(DomainError, match="RULE_CONDITION_UNGROUNDED"):
        handlers._validated_extraction(
            result, BID, docs[0]["blocks"], span_documents=docs, provenance=proofs
        )
    assert proofs == []


def test_unproven_later_rule_does_not_publish_earlier_provenance():
    docs = source()
    result = extraction()
    other = deepcopy(result["rules"][0])
    other["conditions"] = ["模型新增的条件。"]
    result["rules"].append(other)
    proofs = []
    with pytest.raises(DomainError, match="RULE_CONDITION_UNGROUNDED"):
        handlers._validated_extraction(
            result, BID, docs[0]["blocks"], span_documents=docs, provenance=proofs
        )
    assert proofs == []


def test_publish_preserves_provenance_in_existing_effect_receipt_result(monkeypatch):
    docs = source()
    proofs = []
    items = handlers._validated_extraction(
        extraction(), BID, docs[0]["blocks"], span_documents=docs, provenance=proofs
    )
    monkeypatch.setattr(handlers, "source_closure", lambda *args, **kwargs: [])
    monkeypatch.setattr(handlers, "fetch", lambda *args: {"current_rule_set_id": None})
    monkeypatch.setattr(handlers, "create_extracted_set", lambda *args: "synthetic-rule-set")
    outcome = {
        "refs": [],
        "closure": [],
        "base_rule_set_id": None,
        "material_id": "material",
        "items": items,
        "coverage": "complete",
        "documents": [],
        "gaps": [],
        "ambiguities": [],
        "model_call_id": "call",
        "method_digest": "method",
        "grounding_spans": proofs,
    }
    value = handlers.publish(
        None, {"handler_version": "prepare/1", "step_key": "extract-rules", "bid_id": BID}, outcome
    )
    assert value["result_ref"] == "synthetic-rule-set"
    assert value["grounding_spans"] == proofs


@pytest.mark.parametrize("target", ["evidence_spans.py", "rule_sets.py"])
def test_method_identity_changes_when_grounding_code_changes(monkeypatch, target):
    before = reviews.method_profile()
    original = Path.read_bytes

    def changed(path):
        value = original(path)
        return value + b"\n# synthetic change" if path.name == target else value

    monkeypatch.setattr(Path, "read_bytes", changed)
    after = reviews.method_profile()
    assert after["assertion_and_scope_digest"] != before["assertion_and_scope_digest"]
