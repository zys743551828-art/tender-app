"""Versioned context sensitivity and explicit candidate limits; no execution claims."""

from copy import deepcopy

import pytest

from packages.domain.package_review_identity import candidate, summary
from packages.domain.package_review_method import POLICY


def context(as_of="2026-10-19T08:00:00Z"):
    selected = {"bid_id": "synthetic-bid", "target": {"identity": {"digest": "a" * 64}}}
    facts = {"head": {"fact_set_id": None, "revision": 0}, "items": []}
    method = {
        "engine": "package-review/1",
        "purpose": POLICY["purpose"],
        "executor_available": False,
        "formal_scoring_eligible": False,
    }
    return candidate(selected, facts, [], method, POLICY, as_of)


def test_same_semantics_keep_semantic_digest_but_each_observation_freezes_its_time():
    a, b = context(), context("2026-10-19T08:01:00Z")
    assert a["semantic_digest"] == b["semantic_digest"]
    assert a["snapshot_digest"] != b["snapshot_digest"]
    assert context("2026-10-19T16:00:00+08:00") == a
    result = summary(a)
    assert result["facts_binding"] == "empty"
    assert result["executor_available"] is result["formal_scoring_eligible"] is False


@pytest.mark.parametrize("part", ["package", "fact", "decision", "source", "method"])
def test_semantic_changes_cannot_reuse_old_context_identity(part):
    original = context()
    value = deepcopy(original["manifest"])
    selected = {"bid_id": "synthetic-bid", "target": {"identity": {"digest": "a" * 64}}}
    if part == "package":
        selected["target"]["identity"]["digest"] = "b" * 64
    if part in {"fact", "decision"}:
        value["facts"]["items"] = [
            {
                "value_jsonb_text": '{"n": 1.25}',
                "decision": {"decision": "confirmed" if part == "decision" else "rejected"},
            }
        ]
    if part == "source":
        value["sources"] = [{"source_id": "synthetic-source", "revision": 2}]
    if part == "method":
        value["method"]["configured_model"] = "synthetic-other-model"
    updated = candidate(
        selected, value["facts"], value["sources"], value["method"], value["policy"], value["as_of"]
    )
    assert updated["semantic_digest"] != original["semantic_digest"]
    assert updated["snapshot_digest"] != original["snapshot_digest"]


@pytest.mark.parametrize("invalid", ["naive_time", "purpose", "executor", "scoring"])
def test_candidate_refuses_guessed_time_or_unimplemented_execution_grants(invalid):
    value = context()["manifest"]
    if invalid == "purpose":
        value["method"]["purpose"] = "formal_scoring"
    if invalid == "executor":
        value["method"]["executor_available"] = True
    if invalid == "scoring":
        value["policy"]["formal_scoring_eligible"] = True
    with pytest.raises(ValueError):
        candidate(
            {"bid_id": "synthetic-bid", "target": {"identity": {"digest": "a" * 64}}},
            value["facts"],
            value["sources"],
            value["method"],
            value["policy"],
            "2026-10-19T08:00:00" if invalid == "naive_time" else value["as_of"],
        )


def test_candidate_owns_captured_values_and_cannot_be_rewritten_through_callers():
    from packages.domain.review_identity import digest

    selected = {"bid_id": "synthetic-bid", "target": {"identity": {"digest": "a" * 64}}}
    facts = {"head": {"fact_set_id": None, "revision": 0}, "items": []}
    method = {
        "engine": "package-review/1",
        "purpose": POLICY["purpose"],
        "executor_available": False,
        "formal_scoring_eligible": False,
    }
    policy = deepcopy(POLICY)
    sources = []
    captured = candidate(selected, facts, sources, method, policy, "2026-10-19T08:00:00Z")
    selected["target"]["identity"]["digest"] = "b" * 64
    facts["head"]["revision"] = 2
    sources.append({"source_id": "later"})
    method["engine"] = "later"
    policy["version"] = "later"
    assert digest(captured["manifest"]) == captured["snapshot_digest"]
    assert captured["manifest"]["identity"]["digest"] == "a" * 64
    assert captured["manifest"]["facts"]["head"]["revision"] == 0
    assert captured["manifest"]["sources"] == []
