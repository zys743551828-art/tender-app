"""Private whole-package checklist; synthetic inventory is explicit test data."""
# ruff: noqa: F811

from copy import deepcopy

import pytest
from test_package_technical_material import context, reseal, synthetic, uid  # noqa: F401

from packages.domain.review_identity import digest
from packages.model_governance import package_material_scope_review as review


def refresh(origin):
    m = origin.material
    preview = m["scope"]["manifest"]["preview"]["manifest"]
    for role, key in (
        ("target", "package_digest"),
        ("authority", "authority_digest"),
        ("inventory", "inventory_digest"),
    ):
        m[role]["digest"] = digest(m[role]["manifest"])
        preview["basis"][key] = m[role]["digest"]
    return reseal(origin)


@pytest.fixture
def review_origin(synthetic):
    origin = deepcopy(synthetic)
    m = origin.material
    member = m["target"]["manifest"]["members"][0]
    member["parts"][0]["shared_attachment"] = True
    member["parts"].extend(
        [
            {
                "part_id": "target/detail",
                "category": "technical",
                "first_page": 1,
                "last_page": 1,
                "shared_attachment": True,
                "heading_path": [1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            },
            {
                "part_id": "business",
                "category": "commercial",
                "first_page": 1,
                "last_page": 1,
                "shared_attachment": True,
                "heading_path": [2],
            },
        ]
    )
    preview = m["scope"]["manifest"]["preview"]["manifest"]
    native = m["native_documents"][0]
    preview["parts"] = [
        {
            "member_id": member["member_id"],
            "document_version_id": member["document_version_id"],
            "file_digest": member["file_digest"],
            "part": deepcopy(part),
            "selected": index == 0,
            "read_physical_pages": [1],
            "block_ids": [b["id"] for b in native["blocks"]],
            "text_evidence_present": True,
            "visual_coverage": "unproven",
        }
        for index, part in enumerate(member["parts"])
    ]
    bindings = []
    for rule in preview["rules"]:
        requirement = {
            "target_part_ids": ["target"],
            "categories": ["technical"],
            "applicability": "applicable",
        }
        rule["requirement_digest"] = digest(requirement)
        bindings.append(
            {
                "rule_id": rule["rule_id"],
                "rule_digest": rule["rule_digest"],
                "rule_snapshot": deepcopy(rule["rule_snapshot"]),
                "requirement": requirement,
                "requirement_digest": digest(requirement),
                "annotation": {"kind": "synthetic_explicit_mapping"},
            }
        )
    snapshot = deepcopy(preview["rules"][0]["rule_snapshot"])
    snapshot.update(id=uid(63), kind="constraint")
    requirement = {
        "target_part_ids": ["business"],
        "categories": ["commercial"],
        "applicability": "unknown",
    }
    bindings.append(
        {
            "rule_id": snapshot["id"],
            "rule_digest": digest(snapshot),
            "rule_snapshot": snapshot,
            "requirement": requirement,
            "requirement_digest": digest(requirement),
        }
    )
    m["inventory"]["manifest"]["requirements"] = bindings
    return refresh(origin)


def build(origin):
    ctx = context(refresh(origin))
    return review.build(
        ctx,
        expected_context_digest=ctx.metadata["digest"],
        expected_method_digest=review.method_digest(),
    )


def test_complete_private_universe_exclusions_and_deep_heading_paths_retained(review_origin):
    result = build(review_origin)
    m = result.metadata
    assert (
        len(m["documents"]) == 2
        and len(m["parts"]) == 4
        and len(m["requirements"]) == 3
        and len(m["check_items"]) == 13
    )
    root = next(row for row in m["parts"] if row["part"]["part_id"] == "target")
    assert (
        root["declared_heading_descendant_ids"]
        == ["target/detail"]
        == root["unselected_declared_descendant_ids"]
    )
    assert (
        next(row for row in m["parts"] if row["part"]["part_id"] == "business")["part"]["category"]
        == "commercial"
    )
    assert any(
        row["kind"] == "constraint" and row["declared_selection"] is None
        for row in m["requirements"]
    )
    assert any(row["declared_selection"] == "exclude" for row in m["requirements"])
    included = next(row for row in m["requirements"] if row["declared_selection"] == "include")
    assert len(included["available_source_evidence_ids"]) == 3
    assert included["frozen_inventory_binding"]["rule_snapshot"]["bands"][1]["points"] == "0"
    assert all(item["state"] == "unreviewed" for item in m["check_items"])
    assert len({item["check_id"] for item in m["check_items"]}) == 13
    assert (
        m["state"] == "requires_independent_review"
        and m["cross_reference_semantic_closure"] == "unproven"
    )
    for flag in (
        "visual_readability_verified",
        "necessary_scope_verified",
        "input_authority_granted",
        "native_binding_verified",
        "execution_authorized",
    ):
        assert m[flag] is False
    assert "Synthetic" not in repr(result)
    assert review.verify(result, expected_digest=m["digest"]).metadata == m
    assert build(review_origin).metadata == m


@pytest.mark.parametrize(
    "mutation",
    [
        "drop_rule",
        "duplicate_rule",
        "rule_hash",
        "requirement_hash",
        "scope_binding",
        "member_file",
        "member_missing",
        "part_set",
        "part_range",
        "selection_zero",
        "read_pages",
        "block_ids",
        "duplicate_part",
    ],
)
def test_rehashed_material_cannot_hide_universe_binding_errors(review_origin, mutation):
    m = review_origin.material
    preview = m["scope"]["manifest"]["preview"]["manifest"]
    rows = m["inventory"]["manifest"]["requirements"]
    member = m["target"]["manifest"]["members"][0]
    if mutation == "drop_rule":
        rows.pop(0)
    elif mutation == "duplicate_rule":
        rows.append(deepcopy(rows[0]))
    elif mutation == "rule_hash":
        rows[0]["rule_snapshot"]["statement"] += " synthetic changed"
    elif mutation == "requirement_hash":
        rows[0]["requirement"]["categories"].append("commercial")
    elif mutation == "scope_binding":
        rows[0]["requirement"]["categories"].append("commercial")
        rows[0]["requirement_digest"] = digest(rows[0]["requirement"])
    elif mutation == "member_file":
        member["file_digest"] = "a" * 64
    elif mutation == "member_missing":
        extra = deepcopy(member)
        extra.update(member_id="missing", document_version_id=uid(999))
        m["target"]["manifest"]["members"].append(extra)
    elif mutation == "part_set":
        member["parts"].pop()
    elif mutation == "part_range":
        member["parts"][0]["last_page"] = 2
    elif mutation == "selection_zero":
        preview["parts"][1]["selected"] = 0
    elif mutation == "read_pages":
        preview["parts"][0]["read_physical_pages"].clear()
    elif mutation == "block_ids":
        preview["parts"][0]["block_ids"].pop()
    else:
        member["parts"].append(deepcopy(member["parts"][0]))
    with pytest.raises(review.MaterialScopeReviewError):
        build(review_origin)


def test_non_scoring_missing_sources_stay_visible_and_unqualified(review_origin):
    row = review_origin.material["inventory"]["manifest"]["requirements"][-1]
    row["rule_snapshot"]["evidence_ids"].append(uid(999))
    row["rule_digest"] = digest(row["rule_snapshot"])
    result = build(review_origin)
    item = next(r for r in result.metadata["requirements"] if r["kind"] == "constraint")
    assert item["missing_source_evidence_ids"] == [uid(999)]
    assert result.metadata["input_authority_granted"] is False


@pytest.mark.parametrize(
    "mutation", ["qualification", "zero", "approved", "drop_requirement", "drop_check"]
)
def test_rehashed_checklist_cannot_become_review_decision(review_origin, mutation):
    result = build(review_origin)
    m = result.metadata
    if mutation == "qualification":
        m["necessary_scope_verified"] = True
    elif mutation == "zero":
        m["input_authority_granted"] = 0
    elif mutation == "approved":
        m["check_items"][0]["state"] = "approved"
    elif mutation == "drop_requirement":
        m["requirements"].pop()
    else:
        m["check_items"].pop()
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    with pytest.raises(review.MaterialScopeReviewError, match="PACKET_MISMATCH"):
        review.verify(result, expected_digest=m["digest"])


@pytest.mark.parametrize(
    "limit", ["MAX_PARTS", "MAX_REQUIREMENTS", "MAX_DECLARED_RELATIONS", "MAX_BYTES"]
)
def test_limits_reject_without_truncation(review_origin, monkeypatch, limit):
    monkeypatch.setattr(review, limit, 0)
    with pytest.raises(review.MaterialScopeReviewError):
        build(review_origin)


def test_packet_owns_context_and_raw_frozen_declarations(review_origin):
    ctx = context(review_origin)
    result = review.build(
        ctx,
        expected_context_digest=ctx.metadata["digest"],
        expected_method_digest=review.method_digest(),
    )
    expected = deepcopy(result.metadata)
    ctx.metadata["material"]["inventory"]["manifest"]["requirements"].clear()
    assert result.metadata == expected
    assert review.verify(result, expected_digest=expected["digest"]).metadata == expected
