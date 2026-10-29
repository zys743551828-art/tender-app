"""Synthetic exact receipts separate submitted frozen scope from semantic completeness."""
# ruff: noqa: F401,F811

from copy import deepcopy

import pytest
from test_package_input_dependencies import case, rebind, uid

from packages.domain.package_inventory_proof import _page_count, assess
from packages.domain.review_identity import digest


@pytest.fixture
def proof_case(case):
    root = case["root"]
    member = {
        "member_id": "authority",
        "document_version_id": uid(40),
        "file_digest": "c" * 64,
        "page_count": 2,
        "parse": {
            "status": "frozen",
            "parse_run_id": uid(41),
            "parser_digest": "e" * 64,
            "config_digest": "f" * 64,
            "evidence_digest": "a" * 64,
        },
        "parts": [{"part_id": "main", "first_page": 1, "last_page": 2, "shared_attachment": False}],
    }
    authority = {
        "package_id": uid(60),
        "revision_id": uid(61),
        "scope": {"bid_id": case["prepared"].scope[0], "lot_id": uid(62)},
        "members": [member],
    }
    original = {
        "manifest": authority,
        "digest": digest(authority),
        "identity": {"digest": "d" * 64},
    }
    root["selection"].update(bid_id=case["prepared"].scope[0], authority=original)
    doc = root["documents"][0]
    doc.update(
        member_id="authority",
        document_version_id=uid(40),
        parse_id=uid(41),
        digest=member["file_digest"],
        parser_digest="e" * 64,
        config_digest="f" * 64,
        page_count=2,
    )
    doc["blocks"] = [{"id": uid(30), "physical_page": 1}, {"id": uid(32), "physical_page": 2}]
    inv = root["selection"]["inventory"]["manifest"]
    inv.update(
        version="bid-package-requirements/2",
        extraction_binding="exact_frozen_input_result",
        authority_revision_id=authority["revision_id"],
        authority_digest=original["digest"],
        rule_set_id=uid(70),
    )
    method = {"engine": "synthetic-test-only"}
    members = [
        {
            **{
                k: member[k]
                for k in ("member_id", "document_version_id", "file_digest", "page_count", "parts")
            },
            **{
                k: member["parse"][k]
                for k in ("parse_run_id", "parser_digest", "config_digest", "evidence_digest")
            },
        }
    ]
    im = {
        "identity_version": "package-rule-extraction-input/1",
        "bid_id": case["prepared"].scope[0],
        "scope": authority["scope"],
        "authority_package": {
            "package_id": authority["package_id"],
            "revision_id": authority["revision_id"],
            "digest": original["digest"],
            "manifest": authority,
            "identity_digest": original["identity"]["digest"],
            "identity_snapshot": original["identity"],
        },
        "members": members,
        "extraction_scope": {
            "policy": "all_declared_package_parts",
            "coverage": "all_physical_pages",
            "parts": [
                {
                    "member_id": "authority",
                    "document_version_id": uid(40),
                    "parse_run_id": uid(41),
                    "part_id": "main",
                    "first_page": 1,
                    "last_page": 2,
                    "shared_attachment": False,
                }
            ],
        },
        "method_profile": method,
        "method_digest": digest(method),
    }
    result = {
        "input_digest": digest(im),
        "rule_set_id": inv["rule_set_id"],
        "authority_revision_id": authority["revision_id"],
        "authority_digest": original["digest"],
        "method_digest": digest(method),
        "range_status": "all_frozen_evidence_submitted",
        "read_evidence_ids_digest": digest([uid(30), uid(32)]),
        "extraction_coverage": "complete",
        "quality_status": "not_measured",
    }
    run = {
        "id": uid(71),
        "bid_id": case["prepared"].scope[0],
        "authority_revision_id": authority["revision_id"],
        "authority_digest": original["digest"],
        "input_digest": digest(im),
        "input_manifest": im,
        "operation_id": uid(72),
        "operation_input_digest": "b" * 64,
        "rule_set_id": inv["rule_set_id"],
        "result_digest": digest(result),
        "result": result,
    }
    receipt = {
        "run": run,
        "operation": {
            "id": uid(72),
            "bid_id": run["bid_id"],
            "input_digest": run["operation_input_digest"],
            "handler_version": "prepare/1",
            "state": "succeeded",
        },
        "effect": {
            "result_ref": run["rule_set_id"],
            "method_digest": result["method_digest"],
            "extraction_input_digest": run["input_digest"],
        },
    }
    inv.update(
        extraction_result_id=run["id"],
        extraction_input_digest=run["input_digest"],
        extraction_result_digest=run["result_digest"],
        extraction_range_status=result["range_status"],
        extraction_coverage=result["extraction_coverage"],
        extraction_quality_status="not_measured",
    )
    rebind(case)
    return case, receipt


def proof(c, receipt=None):
    return assess(c["frozen"], c["prepared"], receipt).view()


def reseal(c, receipt):
    r = receipt["run"]
    m = r["input_manifest"]
    r["input_digest"] = digest(m)
    r["result"]["input_digest"] = r["input_digest"]
    r["result_digest"] = digest(r["result"])
    receipt["effect"]["extraction_input_digest"] = r["input_digest"]
    inv = c["root"]["selection"]["inventory"]["manifest"]
    inv.update(
        extraction_input_digest=r["input_digest"],
        extraction_result_digest=r["result_digest"],
        extraction_coverage=r["result"]["extraction_coverage"],
    )
    rebind(c)


def test_exact_all_pages_and_read_set_never_prove_semantic_extraction_or_current_authority(
    proof_case,
):
    c, receipt = proof_case
    value = proof(c, receipt)
    m = value["manifest"]
    assert m["extraction_range_proven"] is True and m["extraction_receipt_state"] == "matched"
    assert (
        m["documents"][0]["member_id"] == "authority"
        and m["documents"][0]["declared_page_count"] == 2
    )
    assert (
        m["inventory_complete"]
        is m["facts_qualified"]
        is m["original_bytes_verified"]
        is m["launch_available"]
        is m["publication_authorized"]
        is False
    )
    assert m["quality_status"] == "not_measured" and m["blockers"] == [
        "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"
    ]
    assert value["digest"] == digest(m)
    receipt["run"]["result"]["extraction_coverage"] = "partial"
    assert value["manifest"]["extraction_coverage"] == "complete"


def test_missing_exact_archive_cannot_fall_back_to_current_rule_set_or_latest_parse(proof_case):
    c, _ = proof_case
    m = proof(c)["manifest"]
    assert (
        m["extraction_receipt_state"] == "archive_missing" and m["extraction_range_proven"] is False
    )


def test_legacy_inventory_remains_unproven_even_when_matching_new_receipt_exists(proof_case):
    c, receipt = proof_case
    inv = c["root"]["selection"]["inventory"]["manifest"]
    inv.update(version="bid-package-requirements/1", extraction_binding="unproven_legacy_rule_set")
    rebind(c)
    assert proof(c)["manifest"]["extraction_receipt_state"] == "not_frozen"
    with pytest.raises(ValueError):
        proof(c, receipt)


@pytest.mark.parametrize("coverage", ["partial", "conflict"])
def test_full_submitted_scope_can_still_have_incomplete_extraction(proof_case, coverage):
    c, receipt = proof_case
    receipt["run"]["result"]["extraction_coverage"] = coverage
    reseal(c, receipt)
    m = proof(c, receipt)["manifest"]
    assert m["extraction_range_proven"] is True and m["inventory_complete"] is False
    assert "INVENTORY_EXTRACTION_" + coverage.upper() in m["blockers"]


def test_inconsistent_read_set_is_explicit_gap_not_an_all_evidence_claim(proof_case):
    c, receipt = proof_case
    receipt["run"]["result"]["read_evidence_ids_digest"] = digest([uid(30)])
    reseal(c, receipt)
    m = proof(c, receipt)["manifest"]
    assert (
        m["extraction_receipt_state"] == "read_set_mismatch"
        and m["extraction_range_proven"] is False
    )
    assert "INVENTORY_READ_EVIDENCE_MISMATCH" in m["blockers"]


def test_declared_page_hole_cannot_be_hidden_by_matching_receipt(proof_case):
    c, receipt = proof_case
    member = c["root"]["selection"]["authority"]["manifest"]["members"][0]
    member["parts"][0]["last_page"] = 1
    # The receipt and frozen package are both internally resealed; the hole still remains.
    authority = c["root"]["selection"]["authority"]
    authority["digest"] = digest(authority["manifest"])
    inv = c["root"]["selection"]["inventory"]["manifest"]
    inv["authority_digest"] = authority["digest"]
    im = receipt["run"]["input_manifest"]
    im["authority_package"]["digest"] = authority["digest"]
    receipt["run"]["authority_digest"] = receipt["run"]["result"]["authority_digest"] = authority[
        "digest"
    ]
    im["extraction_scope"]["parts"][0]["last_page"] = 1
    reseal(c, receipt)
    m = proof(c, receipt)["manifest"]
    assert m["documents"][0]["declared_page_count"] == 1 and m["extraction_range_proven"] is False


@pytest.mark.parametrize(
    "change",
    [
        "run_id",
        "run_scope",
        "method",
        "parse",
        "input_digest",
        "result_digest",
        "operation",
        "effect",
    ],
)
def test_changed_or_resealed_foreign_original_binding_is_rejected(proof_case, change):
    c, receipt = proof_case
    if change == "run_id":
        receipt["run"]["id"] = uid(99)
    elif change == "run_scope":
        receipt["run"]["bid_id"] = uid(99)
    elif change == "method":
        receipt["run"]["input_manifest"]["method_digest"] = "a" * 64
    elif change == "parse":
        receipt["run"]["input_manifest"]["members"][0]["parse_run_id"] = uid(99)
        reseal(c, receipt)
    elif change == "input_digest":
        receipt["run"]["input_digest"] = "a" * 64
    elif change == "result_digest":
        receipt["run"]["result_digest"] = "a" * 64
    elif change == "operation":
        receipt["operation"]["state"] = "running"
    else:
        receipt["effect"]["result_ref"] = uid(99)
    with pytest.raises(ValueError):
        proof(c, receipt)


def test_empty_and_unbound_requirements_are_not_proved_by_receipt_counts(proof_case):
    c, receipt = proof_case
    inv = c["root"]["selection"]["inventory"]["manifest"]
    inv["requirements"][0]["source_bound"] = False
    rebind(c)
    assert "INVENTORY_UNBOUND_REQUIREMENT" in proof(c, receipt)["manifest"]["blockers"]
    inv["requirements"] = []
    rebind(c)
    assert "INVENTORY_EMPTY_REQUIREMENTS" in proof(c, receipt)["manifest"]["blockers"]


@pytest.mark.parametrize(
    "parts,total,count",
    [
        ([(1, 2), (2, 2)], 2, 2),
        ([(1, 1), (3, 4)], 4, 3),
        ([(2, 3)], 4, 2),
        ([(1, 4), (1, 3)], 4, 4),
        ([(1, 2_000_000_000)], 2_000_000_000, 2_000_000_000),
    ],
)
def test_page_union_counts_actual_scope_without_double_counting_or_page_expansion(
    parts, total, count
):
    assert _page_count([{"first_page": a, "last_page": b} for a, b in parts], total) == count


@pytest.mark.parametrize("first,last", [(0, 1), (2, 1), (1, 3)])
def test_invalid_declared_physical_range_is_rejected(first, last):
    with pytest.raises(ValueError):
        _page_count([{"first_page": first, "last_page": last}], 2)


def test_empty_frozen_evidence_never_proves_model_input_range(proof_case):
    c, receipt = proof_case
    c["root"]["documents"][0]["blocks"] = []
    receipt["run"]["result"]["read_evidence_ids_digest"] = digest([])
    reseal(c, receipt)
    m = proof(c, receipt)["manifest"]
    assert m["extraction_range_proven"] is False and "INVENTORY_NO_FROZEN_EVIDENCE" in m["blockers"]
    assert m["unbound_requirement_count"] == 1


def test_legacy_reader_does_not_query_any_later_extraction_record():
    from packages.domain.bid_package_inventory_proof import _receipt

    class NoQueries:
        def execute(self, *args):
            pytest.fail("legacy identity must not be inferred by a new query")

    assert _receipt(NoQueries(), (uid(1),), {"version": "bid-package-requirements/1"}) is None
