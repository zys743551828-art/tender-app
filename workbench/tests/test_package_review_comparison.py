"""Synthetic exact identities distinguish definition, judgment and human-opinion changes."""
# ruff: noqa: F401,F811

from copy import deepcopy

import pytest
from test_package_review_decisions import case, make, report, request, uid

from packages.contracts.package_review_comparisons_api import valid
from packages.domain import package_review_comparison as comparison
from packages.domain.package_review_execution_identity import identify
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha


def sync(side):
    """Build an explicitly synthetic, self-consistent stored input/result vector."""
    run, packet = side["run"], side["input"]
    m = packet["manifest"]
    m["executor_method"]["digest"] = digest(m["executor_method"]["profile"])
    binding = m["execution_input"]["identity"]["binding"]
    binding.update(m["scope"])
    binding.update(
        {
            "frozen_input_id": m["frozen_input"]["id"],
            "frozen_digest": m["frozen_input"]["digest"],
            "input_digest": m["frozen_input"]["input_digest"],
            "evidence_digest": m["frozen_input"]["evidence_digest"],
        }
    )
    m["execution_input"]["identity"] = identify(binding, m["execution_input"]["identity"]["rerun"])
    packet["digest"] = digest(m)
    run.update(
        {
            "scope": deepcopy(m["scope"]),
            "frozen_input_id": m["frozen_input"]["id"],
            "frozen_input_digest": m["frozen_input"]["digest"],
            "execution_input_id": m["execution_input"]["id"],
            "execution_input_digest": m["execution_input"]["digest"],
            "execution_digest": m["execution_input"]["identity"]["execution_digest"],
            "input_digest": packet["digest"],
            "method_digest": m["executor_method"]["digest"],
            "dependency_plan_id": m["dependency_plan"]["id"],
            "dependency_plan_digest": m["dependency_plan"]["digest"],
        }
    )
    run["operation"]["input_digest"] = run["input_digest"]
    result = run["result"]["manifest"]
    result.update(
        {
            **{
                key: deepcopy(run[key])
                for key in (
                    "scope",
                    "execution_input_id",
                    "execution_input_digest",
                    "execution_digest",
                    "input_digest",
                    "method_digest",
                    "dependency_plan_id",
                    "dependency_plan_digest",
                )
            },
            "run_id": run["id"],
            "bid_id": run["scope"]["bid_id"],
            "requirement_count": len(result["matrix"]),
        }
    )
    result["counts"] = {
        key: sum(row["verdict"] == key for row in result["matrix"]) for key in result["counts"]
    }
    result["matrix_coverage"] = "partial" if result["counts"]["unable_to_judge"] else "complete"
    run["result"]["digest"] = digest(result)
    side["human"] = {
        **{key: deepcopy(run[key]) for key in ("scope", "frozen_input_id", "execution_input_id")},
        "run_id": run["id"],
        "result_digest": run["result"]["digest"],
        "items": [
            {"requirement_id": row["requirement_id"], "row_digest": digest(row), "current": None}
            for row in sorted(result["matrix"], key=lambda row: row["requirement_id"])
        ],
    }
    return side


@pytest.fixture
def pair(case, report):
    left = sync(
        {
            "run": deepcopy(report),
            "input": {"manifest": deepcopy(case["manifest"]), "digest": report["input_digest"]},
        }
    )
    right = deepcopy(left)
    right["run"]["id"] = uid(150)
    right["run"]["operation"]["id"] = uid(151)
    right["run"]["created_at"] = "2026-10-21T02:00:00.000000Z"
    right["input"]["manifest"]["execution_input"].update(
        {"id": uid(106), "digest": sha(b"synthetic-right-prepared")}
    )
    right["input"]["manifest"]["execution_input"]["identity"]["rerun"] = {
        "nonce": uid(160),
        "reason": "明确请求新一轮合成核查，不复用原执行身份",
    }
    sync(right)
    return left, right


def compare(pair):
    left, right = pair
    return comparison.compare(left["run"]["scope"]["bid_id"], left, right)


def rows(side):
    return side["run"]["result"]["manifest"]["matrix"]


def test_same_definition_can_change_verdict_without_claiming_risk_resolution(pair):
    left, right = pair
    rows(left)[0]["verdict"] = "violated"
    sync(left)
    old = deepcopy(pair)
    value = compare(pair)
    m = value["manifest"]
    assert valid("PackageReviewComparisonManifest", m)
    row = m["items"][0]
    assert row["definition_change"] == "unchanged" and row["machine_row_changed"] is True
    assert row["verdict_transition"] == {"from": "violated", "to": "satisfied", "changed": True}
    assert m["counts"] == {
        "added": 0,
        "removed": 0,
        "changed": 0,
        "unchanged": 1,
        "machine_row_changed": 1,
        "verdict_changed": 1,
    }
    assert m["overall_coverage"] == "partial"
    assert not any(
        m[key]
        for key in (
            "risk_resolution_assessed",
            "inventory_complete",
            "formal_scoring_eligible",
            "submission_eligible",
        )
    )
    assert pair == old and value["digest"] == digest(m)
    assert compare(pair) == value


def test_equal_text_with_different_requirement_ids_is_added_and_removed(pair):
    rows(pair[1])[0]["requirement_id"] = uid(2000)
    sync(pair[1])
    manifest = compare(pair)["manifest"]
    assert manifest["counts"]["added"] == manifest["counts"]["removed"] == 1
    assert manifest["counts"]["unchanged"] == manifest["counts"]["verdict_changed"] == 0
    assert {row["definition_change"] for row in manifest["items"]} == {"added", "removed"}
    assert all(
        row["machine_row_changed"] is None and row["verdict_transition"] is None
        for row in manifest["items"]
    )


@pytest.mark.parametrize("field", ["requirement_digest", "rule_digest"])
def test_shared_id_with_changed_definition_is_not_reported_unchanged(pair, field):
    rows(pair[1])[0][field] = "0" * 64
    sync(pair[1])
    m = compare(pair)["manifest"]
    assert m["items"][0]["definition_change"] == "changed"
    assert m["input_changes"]["requirements"] is True and m["counts"]["changed"] == 1
    assert m["items"][0]["verdict_transition"]["changed"] is False


def test_quote_only_change_is_machine_row_change_without_definition_or_verdict_change(pair):
    rows(pair[1])[0]["target_quotes"][0]["quote"] = "工期为 120"
    sync(pair[1])
    row = compare(pair)["manifest"]["items"][0]
    assert row["definition_change"] == "unchanged" and row["machine_row_changed"] is True
    assert row["verdict_transition"]["changed"] is False
    assert "target_quotes" not in row["right"] and "authority_quotes" not in row["right"]


def test_each_context_change_is_explicit_without_reading_current_configuration(pair, monkeypatch):
    left, right = pair
    m = right["input"]["manifest"]
    m["scope"]["inventory_id"] = uid(204)
    m["frozen_input"]["digest"] = "0" * 64
    m["selected_facts_digest"] = "1" * 64
    m["fact_admission"]["proofs_digest"] = "2" * 64
    m["dependency_plan"]["digest"] = "3" * 64
    m["inventory_proof_digest"] = "4" * 64
    m["executor_method"]["profile"]["model"] = "deepseek-v4-pro"
    right["run"]["result"]["manifest"]["submitted_documents"][0]["file_digest"] = "5" * 64
    sync(right)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://unavailable.example/never-read")
    changed = compare(pair)["manifest"]["input_changes"]
    assert all(
        changed[key]
        for key in (
            "run_input",
            "scope",
            "frozen_input",
            "prepared_input",
            "selected_facts",
            "fact_admission",
            "dependency_plan",
            "inventory_proof",
            "method",
            "submitted_documents",
        )
    )
    assert not changed["requirements"] and changed["rerun_intent"]
    assert changed["method_fields"] == ["model"]


def test_human_opinions_are_independent_and_change_only_comparison_snapshot(pair):
    left, right = pair
    before = compare(pair)
    saved = make(right["run"], request(right["run"], state="rejected"))
    right["human"]["items"][0]["current"] = {
        **{
            key: saved["manifest"][key]
            for key in ("id", "sequence_no", "actor_id", "created_at", "state", "reason")
        },
        "digest": saved["digest"],
    }
    after = compare(pair)
    assert after["digest"] != before["digest"]
    assert after["manifest"]["counts"] == before["manifest"]["counts"]
    row = after["manifest"]["items"][0]
    assert row["right_human"]["state"] == "rejected" and row["right"]["verdict"] == "satisfied"
    assert row["left_human"] is None
    assert (
        after["manifest"]["left"]["human_heads_digest"]
        == before["manifest"]["left"]["human_heads_digest"]
    )
    assert (
        after["manifest"]["right"]["human_heads_digest"]
        != before["manifest"]["right"]["human_heads_digest"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "run_input",
        "result_digest",
        "result_scope",
        "human_scope",
        "human_row",
        "duplicate_row",
        "missing_human",
    ],
)
def test_crossed_or_corrupt_historical_bases_cannot_be_compared(pair, change):
    right = pair[1]
    if change == "run_input":
        right["run"]["input_digest"] = "0" * 64
    elif change == "result_digest":
        right["run"]["result"]["digest"] = "0" * 64
    elif change == "result_scope":
        right["run"]["result"]["manifest"]["scope"]["inventory_id"] = uid(999)
        right["run"]["result"]["digest"] = digest(right["run"]["result"]["manifest"])
    elif change == "human_scope":
        right["human"]["run_id"] = pair[0]["run"]["id"]
    elif change == "human_row":
        right["human"]["items"][0]["row_digest"] = "0" * 64
    elif change == "duplicate_row":
        rows(right).append(deepcopy(rows(right)[0]))
        sync(right)
    else:
        right["human"]["items"].clear()
    with pytest.raises(DomainError) as error:
        compare(pair)
    assert error.value.code == "PACKAGE_REVIEW_COMPARISON_CORRUPT"


def test_same_run_foreign_bid_and_pending_run_are_explicitly_rejected(pair):
    with pytest.raises(DomainError) as error:
        comparison.compare(pair[0]["run"]["scope"]["bid_id"], pair[0], pair[0])
    assert error.value.code == "PACKAGE_REVIEW_COMPARISON_SAME_RUN"
    with pytest.raises(DomainError) as error:
        comparison.compare(uid(999), *pair)
    assert error.value.code == "PACKAGE_REVIEW_COMPARISON_RUN_NOT_FOUND"
    pair[1]["run"]["result"] = None
    pair[1]["run"]["operation"]["state"] = "running"
    pair[1]["run"]["operation"]["finished_at"] = None
    with pytest.raises(DomainError) as error:
        compare(pair)
    assert error.value.code == "PACKAGE_REVIEW_COMPARISON_RUN_UNFINISHED"


def test_union_of_two_capacity_limit_runs_is_complete_and_sorted(pair):
    for side_index, side in enumerate(pair):
        original = deepcopy(rows(side)[0])
        side["run"]["result"]["manifest"]["matrix"] = [
            deepcopy(original) | {"requirement_id": uid(10000 + side_index * 1000 + index)}
            for index in range(400)
        ]
        sync(side)
    value = compare(pair)
    assert len(value["manifest"]["items"]) == 800
    assert value["manifest"]["counts"]["added"] == value["manifest"]["counts"]["removed"] == 400
    assert [row["requirement_id"] for row in value["manifest"]["items"]] == sorted(
        row["requirement_id"] for row in value["manifest"]["items"]
    )
