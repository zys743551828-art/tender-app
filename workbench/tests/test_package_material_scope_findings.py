"""Synthetic substantive claims remain untrusted until independent issuer binding."""
# ruff: noqa: F401,F811

from copy import deepcopy

import pytest
from test_package_material_recovery import MemoryStore
from test_package_material_scope_review import build, refresh, review_origin, synthetic

from packages.domain.review_identity import digest
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_scope_findings_store as store_port


def citation(packet, *, evidence_id=None, document=None, pages=None):
    context = packet.context.metadata
    if evidence_id is not None:
        evidence = next(e for e in context["evidence_catalog"] if e["id"] == evidence_id)
    else:
        evidence = next(
            (
                e
                for e in context["evidence_catalog"]
                if e["document_version_id"] == document
                and (pages is None or e["physical_page"] in pages)
                and e["text_content"].strip()
            ),
            None,
        )
    if evidence is not None:
        image = next(
            r
            for r in context["images"]
            if r["kind"] == "full_page"
            and r["document_version_id"] == evidence["document_version_id"]
            and r["physical_page"] == evidence["physical_page"]
        )
    else:
        image = next(
            r
            for r in context["images"]
            if r["kind"] == "full_page"
            and r["document_version_id"] == document
            and (pages is None or r["physical_page"] in pages)
        )
    return {
        "image_asset_id": image["asset"]["id"],
        "document_version_id": image["document_version_id"],
        "parse_run_id": image["parse_run_id"],
        "physical_page": image["physical_page"],
        "evidence_id": evidence["id"] if evidence else None,
        "quote": evidence["text_content"] if evidence else None,
        "rectangle": None,
    }


def draft_for(packet):
    rows = []
    m = packet.metadata
    for item in m["check_items"]:
        kind = item["kind"]
        subject = item["subject"]
        relation = None
        required = []
        outcome = "confirmed"
        if kind in review.OBLIGATIONS:
            roles = (
                {"authority"}
                if kind in {"authority_and_amendment_completeness", "inventory_exhaustiveness"}
                else {"target", "authority"}
            )
            ids = list(
                dict.fromkeys(
                    r["member"]["document_version_id"]
                    for r in m["documents"]
                    if r["package_role"] in roles
                )
            )
            cites = [citation(packet, document=identity) for identity in ids]
        elif kind == "document_source_and_full_page_review":
            row = next(
                r
                for r in m["documents"]
                if r["package_role"] == subject["package_role"]
                and r["member"]["member_id"] == subject["member_id"]
            )
            cites = [citation(packet, document=row["member"]["document_version_id"])]
        elif kind == "declared_section_and_related_range_review":
            row = next(
                r
                for r in m["parts"]
                if r["package_role"] == subject["package_role"]
                and r["part"]["part_id"] == subject["part_id"]
            )
            relation = (
                "source_reference"
                if row["package_role"] == "authority"
                else ("in_scope" if row["declared_selected"] else "out_of_scope")
            )
            cites = [
                citation(packet, document=row["document_version_id"], pages=row["physical_pages"])
            ]
        else:
            row = next(r for r in m["requirements"] if r["rule_id"] == subject["rule_id"])
            cites = [
                citation(packet, evidence_id=identity)
                for identity in row["available_source_evidence_ids"]
            ]
            if row["missing_source_evidence_ids"]:
                outcome = "unable_to_verify"
            if row["kind"] == "scoring":
                relation = "in_scope" if row["declared_selection"] == "include" else "out_of_scope"
                required = list(row["frozen_technical_scope_rule"]["required_part_ids"])
                if row["declared_selection"] not in {"include", "exclude"}:
                    relation = None
                    outcome = "unable_to_verify"
            else:
                relation = "retained_non_scoring"
        rows.append(
            {
                "check_id": item["check_id"],
                "outcome": outcome,
                "scope_relation": relation,
                "required_part_ids": required,
                "reason": "Explicit synthetic review claim, not actual human review.",
                "citations": cites,
            }
        )
    return {
        "version": "package-material-scope-findings/1",
        "context_digest": m["context_digest"],
        "review_digest": m["digest"],
        "reviewed_image_ids": [r["asset"]["id"] for r in packet.context.metadata["images"]],
        "findings": rows,
    }


def checked(packet, draft):
    return findings.validate(
        packet,
        draft,
        expected_review_digest=packet.metadata["digest"],
        expected_method_digest=findings.method_digest(),
    )


def test_complete_claims_and_all_sources_are_structurally_bound_without_authority(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    result = checked(packet, draft)
    m = result.metadata
    assert m["all_findings_claimed_confirmed"] and m["all_images_claimed_reviewed"]
    assert len(m["draft"]["findings"]) == 13 and not m["scope_changes_requested"]
    for flag in (
        "reviewer_identity_verified",
        "semantic_completeness_verified",
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
    ):
        assert m[flag] is False
    assert findings.verify(result, expected_digest=m["digest"]).metadata == m
    assert "synthetic" not in repr(result)
    draft["findings"].clear()
    assert findings.verify(result, expected_digest=m["digest"]).metadata == m


def test_unable_and_change_requested_remain_explicit_without_zero_fill(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    for row in draft["findings"]:
        row.update(
            outcome="unable_to_verify", scope_relation=None, required_part_ids=[], citations=[]
        )
    draft["reviewed_image_ids"] = []
    draft["findings"][0]["outcome"] = "change_required"
    result = checked(packet, draft)
    assert (
        not result.metadata["all_findings_claimed_confirmed"]
        and result.metadata["scope_changes_requested"]
    )
    assert not result.metadata["all_images_claimed_reviewed"]


@pytest.mark.parametrize(
    "mutation",
    [
        "omit",
        "duplicate",
        "foreign_check",
        "actor",
        "qualification",
        "context",
        "image_duplicate",
        "image_unknown",
        "image_incomplete",
    ],
)
def test_draft_cannot_drop_subjects_or_self_assert_identity(review_origin, mutation):
    packet = build(review_origin)
    draft = draft_for(packet)
    if mutation == "omit":
        draft["findings"].pop()
    elif mutation == "duplicate":
        draft["findings"][-1] = deepcopy(draft["findings"][0])
    elif mutation == "foreign_check":
        draft["findings"][0]["check_id"] = "a" * 64
    elif mutation == "actor":
        draft["reviewer_id"] = "admin"
    elif mutation == "qualification":
        draft["verified"] = True
    elif mutation == "context":
        draft["context_digest"] = "a" * 64
    elif mutation == "image_duplicate":
        draft["reviewed_image_ids"].append(draft["reviewed_image_ids"][0])
    elif mutation == "image_unknown":
        draft["reviewed_image_ids"].append("a" * 64)
    else:
        detail = next(r for r in packet.context.metadata["images"] if r["kind"] == "detail")
        draft["reviewed_image_ids"].remove(detail["asset"]["id"])
    with pytest.raises(findings.ScopeFindingsError):
        checked(packet, draft)


@pytest.mark.parametrize(
    "mutation",
    [
        "document",
        "parse",
        "page_bool",
        "page",
        "quote",
        "quote_missing",
        "quote_without_id",
        "image",
        "rectangle_bool",
        "rectangle_outside",
        "duplicate",
        "extra",
    ],
)
def test_citations_cannot_cross_page_source_or_geometry(review_origin, mutation):
    packet = build(review_origin)
    draft = draft_for(packet)
    row = draft["findings"][0]
    c = row["citations"][0]
    if mutation in {"document", "parse"}:
        c["document_version_id" if mutation == "document" else "parse_run_id"] = (
            "00000000-0000-0000-0000-000000000999"
        )
    elif mutation == "page_bool":
        c["physical_page"] = True
    elif mutation == "page":
        c["physical_page"] += 1
    elif mutation == "quote":
        c["quote"] = "not in the actual source"
    elif mutation == "quote_missing":
        c["quote"] = None
    elif mutation == "quote_without_id":
        c["evidence_id"] = None
    elif mutation == "image":
        c["image_asset_id"] = "a" * 64
    elif mutation == "rectangle_bool":
        c["rectangle"] = [False, 0, 1, 1]
    elif mutation == "rectangle_outside":
        c["rectangle"] = [0, 0, 999999, 1]
    elif mutation == "duplicate":
        row["citations"].append(deepcopy(c))
    else:
        c["verified"] = True
    with pytest.raises(findings.ScopeFindingsError):
        checked(packet, draft)


def test_confirmed_rule_must_cite_every_original_source_not_only_first(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    item = next(
        r
        for r in packet.metadata["check_items"]
        if r["kind"] == "requirement_applicability_and_scope_review"
    )
    row = next(r for r in draft["findings"] if r["check_id"] == item["check_id"])
    row["citations"].pop()
    with pytest.raises(findings.ScopeFindingsError, match="RULE_SOURCE_EVIDENCE_INCOMPLETE"):
        checked(packet, draft)


def test_foreign_but_valid_source_cannot_confirm_a_part(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    item = next(
        r
        for r in packet.metadata["check_items"]
        if r["kind"] == "declared_section_and_related_range_review"
        and r["subject"]["package_role"] == "target"
    )
    row = next(r for r in draft["findings"] if r["check_id"] == item["check_id"])
    doc = next(
        r["member"]["document_version_id"]
        for r in packet.metadata["documents"]
        if r["package_role"] == "authority"
    )
    row["citations"] = [citation(packet, document=doc)]
    with pytest.raises(findings.ScopeFindingsError, match="PART_SCOPE_REVISION_REQUIRED"):
        checked(packet, draft)


def test_change_of_declared_scope_is_change_required_not_confirmation(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    item = next(
        r
        for r in packet.metadata["check_items"]
        if r["kind"] == "declared_section_and_related_range_review"
        and r["subject"]["part_id"] == "business"
    )
    row = next(r for r in draft["findings"] if r["check_id"] == item["check_id"])
    row["scope_relation"] = "in_scope"
    with pytest.raises(findings.ScopeFindingsError, match="PART_SCOPE_REVISION_REQUIRED"):
        checked(packet, draft)
    row["outcome"] = "change_required"
    assert checked(packet, draft).metadata["scope_changes_requested"]


def test_crop_can_support_image_observation_but_cannot_host_text_quote(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    crop = next(r for r in packet.context.metadata["images"] if r["kind"] == "detail")
    item = next(
        r
        for r in packet.metadata["check_items"]
        if r["kind"] == "document_source_and_full_page_review"
        and r["subject"]["package_role"] == "target"
    )
    row = next(r for r in draft["findings"] if r["check_id"] == item["check_id"])
    c = row["citations"][0]
    c["image_asset_id"] = crop["asset"]["id"]
    with pytest.raises(findings.ScopeFindingsError, match="CITATION_TEXT_INVALID"):
        checked(packet, draft)
    c.update(
        evidence_id=None,
        quote=None,
        rectangle=[0, 0, crop["asset"]["width"], crop["asset"]["height"]],
    )
    assert checked(packet, draft).metadata["all_findings_claimed_confirmed"]


@pytest.mark.parametrize("mutation", ["identity", "semantic", "zero", "drop_claim"])
def test_rehashed_checked_claims_cannot_turn_into_authority(review_origin, mutation):
    packet = build(review_origin)
    result = checked(packet, draft_for(packet))
    m = result.metadata
    if mutation == "identity":
        m["reviewer_identity_verified"] = True
    elif mutation == "semantic":
        m["semantic_completeness_verified"] = True
    elif mutation == "zero":
        m["execution_authorized"] = 0
    else:
        m["draft"]["findings"].pop()
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    with pytest.raises(findings.ScopeFindingsError):
        findings.verify(result, expected_digest=m["digest"])


@pytest.mark.parametrize("limit", ["MAX_BYTES", "MAX_NODES", "MAX_REASON", "MAX_CITATIONS"])
def test_limits_fail_without_truncation(review_origin, monkeypatch, limit):
    packet = build(review_origin)
    draft = draft_for(packet)
    monkeypatch.setattr(findings, limit, 0)
    with pytest.raises(findings.ScopeFindingsError):
        checked(packet, draft)


def test_cyclic_or_noncanonical_inputs_are_controlled_errors():
    cycle = []
    cycle.append(cycle)
    for value in (cycle, {"x": 1.5}, {"\U0001f600": 0}, {"x": "\ud800"}):
        with pytest.raises(findings.ScopeFindingsError) as caught:
            findings._bounded(value)
        assert caught.value.__context__ is None


def test_private_claims_store_roundtrip_preserves_all_qualifications_false(review_origin):
    packet = build(review_origin)
    value = checked(packet, draft_for(packet))
    store = MemoryStore()
    key = store_port.save(
        store,
        value,
        expected_findings_digest=value.metadata["digest"],
        expected_method_digest=store_port.method_digest(),
    )
    restored = store_port.load(
        store,
        packet,
        commit_digest=key,
        expected_findings_digest=value.metadata["digest"],
        expected_method_digest=store_port.method_digest(),
    )
    assert (
        restored.metadata == value.metadata and len(store.objects) == 1 and len(store.commits) == 1
    )
    assert restored.metadata["reviewer_identity_verified"] is False


@pytest.mark.parametrize("mutation", ["authority", "reference", "context", "unknown"])
def test_rehashed_private_manifest_cannot_change_bindings_or_authority(review_origin, mutation):
    from packages.domain.review_identity import canonical
    from packages.model_governance.package_material_archive import _decode

    packet = build(review_origin)
    value = checked(packet, draft_for(packet))
    store = MemoryStore()
    key = store_port.save(
        store,
        value,
        expected_findings_digest=value.metadata["digest"],
        expected_method_digest=store_port.method_digest(),
    )
    manifest = _decode(store.get_commit(key))
    if mutation == "authority":
        manifest["reviewer_identity_verified"] = True
    elif mutation == "reference":
        manifest["object"]["byte_size"] += 1
    elif mutation == "context":
        manifest["context_digest"] = "a" * 64
    else:
        manifest["verified"] = True
    changed = store.publish(canonical(manifest))
    with pytest.raises(findings.ScopeFindingsError):
        store_port.load(
            store,
            packet,
            commit_digest=changed,
            expected_findings_digest=value.metadata["digest"],
            expected_method_digest=store_port.method_digest(),
        )


def test_confirmed_rule_cannot_add_new_required_parts_without_scope_revision(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    item = next(
        r
        for r in packet.metadata["check_items"]
        if r["kind"] == "requirement_applicability_and_scope_review"
    )
    row = next(r for r in draft["findings"] if r["check_id"] == item["check_id"])
    row["required_part_ids"].append("business")
    with pytest.raises(findings.ScopeFindingsError, match="RULE_SCOPE_REVISION_REQUIRED"):
        checked(packet, draft)
    row["outcome"] = "change_required"
    assert checked(packet, draft).metadata["scope_changes_requested"]


def test_global_authority_cannot_use_only_target_evidence(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    doc = next(
        r["member"]["document_version_id"]
        for r in packet.metadata["documents"]
        if r["package_role"] == "target"
    )
    draft["findings"][0]["citations"] = [citation(packet, document=doc)]
    with pytest.raises(findings.ScopeFindingsError, match="GLOBAL_DOCUMENT_EVIDENCE_INCOMPLETE"):
        checked(packet, draft)


def test_confirmation_needs_evidence_and_cited_image_claim(review_origin):
    packet = build(review_origin)
    draft = draft_for(packet)
    image = draft["findings"][0]["citations"][0]["image_asset_id"]
    draft["reviewed_image_ids"].remove(image)
    with pytest.raises(findings.ScopeFindingsError, match="CITATION_IMAGE_NOT_REVIEWED"):
        checked(packet, draft)
    draft = draft_for(packet)
    draft["findings"][0]["citations"] = []
    with pytest.raises(findings.ScopeFindingsError, match="CONFIRMED_EVIDENCE_REQUIRED"):
        checked(packet, draft)


def test_missing_non_scoring_source_cannot_be_claimed_confirmed(review_origin):
    binding = review_origin.material["inventory"]["manifest"]["requirements"][-1]
    binding["rule_snapshot"]["evidence_ids"].append("00000000-0000-0000-0000-000000000999")
    binding["rule_digest"] = digest(binding["rule_snapshot"])
    packet = build(review_origin)
    draft = draft_for(packet)
    item = next(
        r for r in packet.metadata["check_items"] if r["subject"] == {"rule_id": binding["rule_id"]}
    )
    row = next(r for r in draft["findings"] if r["check_id"] == item["check_id"])
    assert (
        row["outcome"] == "unable_to_verify"
        and not checked(packet, draft).metadata["all_findings_claimed_confirmed"]
    )
    row["outcome"] = "confirmed"
    with pytest.raises(findings.ScopeFindingsError, match="RULE_SOURCE_EVIDENCE_INCOMPLETE"):
        checked(packet, draft)


def test_unclassified_rule_is_not_an_exclusion_confirmation(review_origin):
    preview = review_origin.material["scope"]["manifest"]["preview"]["manifest"]
    preview["rules"][1]["selection"] = "unclassified"
    packet = build(review_origin)
    draft = draft_for(packet)
    item = next(
        r
        for r in packet.metadata["check_items"]
        if r["subject"] == {"rule_id": preview["rules"][1]["rule_id"]}
    )
    row = next(r for r in draft["findings"] if r["check_id"] == item["check_id"])
    assert row["outcome"] == "unable_to_verify"
    row.update(outcome="confirmed", scope_relation="out_of_scope")
    with pytest.raises(findings.ScopeFindingsError, match="RULE_SCOPE_REVISION_REQUIRED"):
        checked(packet, draft)
