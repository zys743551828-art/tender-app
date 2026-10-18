"""整包的身份、范围与未知反例，不依赖模型、数据库或服务器。"""

import json
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from packages.domain.bid_packages import (
    MAX_SAFE_INTEGER,
    BidScope,
    CoverageState,
    DocumentPart,
    InspectedRange,
    PackageError,
    PackageKind,
    PackageMember,
    PackageRevision,
    ParseIdentity,
    Requirement,
    RequirementCoverage,
    assess_coverage,
)


def scope(**changes):
    return replace(BidScope("project-1", "lot-1", "round-1", "bid-1", "bidder-1"), **changes)


def member(member_id="member-1", *, category="technical", pages=4, **changes):
    result = PackageMember(
        member_id,
        "version-" + member_id,
        "a" * 64,
        "own",
        "upload-" + member_id,
        scope(),
        (category,),
        pages,
        ParseIdentity("frozen", "parse-" + member_id, "b" * 64, "c" * 64, "d" * 64),
        (DocumentPart("part-" + member_id, category, 1, pages),),
    )
    return replace(result, **changes)


def package(*members, **changes):
    result = PackageRevision(
        "package-1", "revision-1", 1, PackageKind.BID, scope(), tuple(members) or (member(),)
    )
    return replace(result, **changes)


def requirement(package_value, *, categories=("technical",), **changes):
    result = Requirement(
        "requirement-1",
        package_value.scope,
        "authority",
        ("authority:version-1:page-2",),
        categories,
        applicability="applicable",
    )
    return replace(result, **changes)


def checked(
    package_value,
    requirement_value=None,
    *,
    state=CoverageState.VERIFIED,
    inspected=None,
    reason=None,
    **changes,
):
    if inspected is None:
        inspected = tuple(
            InspectedRange(p.part_id, p.first_page, p.last_page)
            for m in package_value.members
            for p in m.parts
        )
    requirement_value = requirement_value or requirement(package_value)
    return replace(
        RequirementCoverage(
            requirement_value.requirement_id,
            package_value.manifest_digest,
            requirement_value.manifest_digest,
            state,
            inspected,
            ("evidence-1",),
            reason,
        ),
        **changes,
    )


def assess(package_value, requirement_value, result_value, **changes):
    return assess_coverage(
        package_value,
        (requirement_value,),
        (result_value,),
        requirement_inventory_complete=True,
        **changes,
    )


def test_combined_pdf_has_independent_parts_and_unlimited_parsed_heading_depth():
    combined = member(
        pages=10,
        purposes=("qualification", "technical"),
        parts=(
            DocumentPart("qualification", "qualification", 1, 2),
            DocumentPart("technical", "technical", 3, 10, heading_path=tuple(range(1, 15))),
        ),
    )
    p = package(combined)
    r = requirement(p, target_part_ids=("technical",))
    good = checked(p, r, inspected=(InspectedRange("technical", 3, 10),))
    assert assess(p, r, good)["complete"]
    with pytest.raises(PackageError, match="SCOPE_INCOMPLETE"):
        assess(p, r, replace(good, inspected=(InspectedRange("technical", 3, 9),)))


def test_multiple_volumes_jointly_cover_one_requirement_without_last_body_selection():
    p = package(member("one"), member("two"))
    r = requirement(p)
    assert assess(p, r, checked(p))["complete"]
    with pytest.raises(PackageError, match="SCOPE_INCOMPLETE"):
        assess(p, r, checked(p, inspected=(InspectedRange("part-one", 1, 4),)))


@pytest.mark.parametrize(
    "state",
    [
        state
        for state in CoverageState
        if state not in {CoverageState.VERIFIED, CoverageState.NOT_APPLICABLE}
    ],
)
def test_missing_volume_and_every_unknown_state_block_complete(state):
    p = package()
    result = checked(p, state=state, inspected=(), reason="material state explicit")
    report = assess(p, requirement(p), result)
    assert not report["complete"]
    assert report["requirement_states"]["requirement-1"] == state.value


def test_shared_attachment_reused_by_requirements_without_duplicating_physical_file():
    p = package(
        member(
            category="custom-proof",
            parts=(DocumentPart("proof", "custom-proof", 1, 4, shared_attachment=True),),
        )
    )
    r1 = requirement(p, categories=("custom-proof",), target_part_ids=("proof",))
    r2 = replace(r1, requirement_id="requirement-2")
    result = checked(p, r1)
    report = assess_coverage(
        p,
        (r1, r2),
        (result, checked(p, r2)),
        requirement_inventory_complete=True,
    )
    assert report["complete"]
    with pytest.raises(PackageError, match="VERSION_DUPLICATE"):
        package(member(), replace(member(), member_id="duplicate"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("bidder_id", "bidder-2"),
        ("round_id", "round-2"),
        ("lot_id", "lot-2"),
        ("engineering_project_id", "near-name-project"),
    ],
)
def test_cross_subject_lot_round_project_references_rejected(field, value):
    with pytest.raises(PackageError, match="SCOPE_MISMATCH"):
        package(member(scope=scope(**{field: value})))
    p = package()
    with pytest.raises(PackageError, match="REQUIREMENT_SCOPE_MISMATCH"):
        assess(p, requirement(p, scope=scope(**{field: value})), checked(p))


def test_pending_bidder_can_be_stored_but_cannot_be_used_formally():
    pending = scope(bidder_status="pending")
    p = PackageRevision(
        "package", "revision", 1, PackageKind.BID, pending, (member(scope=pending),)
    )
    assert not p.formal_eligible
    with pytest.raises(PackageError, match="BIDDER_UNCONFIRMED"):
        p.require_formal()


def test_authority_supplement_replacement_creates_revision_and_cannot_enter_own_package():
    tender = member("tender", source_kind="authority", category="tender")
    p = PackageRevision("authority", "revision-1", 1, PackageKind.AUTHORITY, scope(), (tender,))
    supplement = member("supplement", source_kind="authority", category="supplement")
    old_manifest, old_digest = p.manifest(), p.manifest_digest
    updated = p.next_revision("revision-2", (tender, supplement))
    assert updated.predecessor_digest == old_digest
    assert updated.manifest_digest != old_digest
    assert p.manifest() == old_manifest
    with pytest.raises(PackageError, match="SOURCE_KIND_MISMATCH"):
        package(supplement)


def test_parse_correction_same_file_bytes_new_package_old_evidence_stays_frozen():
    p = package()
    old_digest = p.manifest_digest
    old_report = assess(p, requirement(p), checked(p))
    corrected = replace(
        p.members[0],
        parse=replace(p.members[0].parse, parse_run_id="parse-corrected", evidence_digest="e" * 64),
    )
    new = p.next_revision("revision-2", (corrected,))
    assert new.members[0].file_digest == p.members[0].file_digest
    assert new.manifest_digest != old_digest
    assert p.manifest_digest == old_digest == old_report["package_digest"]
    with pytest.raises(PackageError, match="COVERAGE_STALE"):
        assess(new, requirement(new), checked(p))


def test_old_package_reopened_is_immutable_and_manifest_copy_is_detached():
    p = package()
    original = p.manifest_digest
    returned = p.manifest()
    returned["members"][0]["parts"][0]["last_page"] = 99
    assert p.manifest_digest == original
    with pytest.raises(FrozenInstanceError):
        p.revision = 99
    with pytest.raises(PackageError, match="REVISION_ID_REUSED"):
        p.next_revision(p.revision_id, p.members)


def test_unfrozen_historical_parse_never_inferred_from_time_and_cannot_pass():
    unknown = ParseIdentity("not_frozen", reason="historical manifest omitted parse identity")
    p = package(member(parse=unknown))
    assert not p.formal_eligible
    with pytest.raises(PackageError, match="INFERRED_ID_FORBIDDEN"):
        replace(unknown, parse_run_id="guessed-by-time")
    with pytest.raises(PackageError, match="PARSE_NOT_FROZEN"):
        p.require_formal()
    with pytest.raises(PackageError, match="PARSE_NOT_FROZEN"):
        assess(p, requirement(p), checked(p))


def test_unknown_requirements_empty_inventory_and_zero_quantity_are_not_automatic_pass():
    p = package()
    assert not assess_coverage(p, (), (), requirement_inventory_complete=True)["complete"]
    assert not assess_coverage(p, (requirement(p),), (checked(p),))["complete"]
    assert not assess_coverage(p, (requirement(p),), (), requirement_inventory_complete=True)[
        "complete"
    ]
    r = requirement(p, minimum_count=0, checks=("quantity",))
    assert r.minimum_count == 0
    assert requirement(p).minimum_count is None


def test_not_applicable_needs_requirement_basis_and_assessment_evidence():
    p = package()
    with pytest.raises(PackageError, match="NOT_APPLICABLE_EVIDENCE_REQUIRED"):
        requirement(p, applicability="not_applicable")
    result = checked(p, state=CoverageState.NOT_APPLICABLE, inspected=())
    with pytest.raises(PackageError, match="NOT_APPLICABLE_UNPROVEN"):
        assess(p, requirement(p), result)
    r = requirement(p, applicability="not_applicable", applicability_evidence=("authority:page-3",))
    assert assess(p, r, checked(p, r, state=CoverageState.NOT_APPLICABLE, inspected=()))["complete"]


def test_overlap_requires_explicit_shared_attachment_on_both_parts():
    with pytest.raises(PackageError, match="OVERLAP_UNDECLARED"):
        member(parts=(DocumentPart("a", "technical", 1, 3), DocumentPart("b", "technical", 3, 4)))
    p = package(
        member(
            parts=(DocumentPart("a", "annex", 1, 4, True), DocumentPart("b", "proof", 1, 4, True))
        )
    )
    assert len(p.members) == 1


@pytest.mark.parametrize("first,last", [(0, 2), (3, 2), (True, 2)])
def test_physical_page_ranges_reject_invalid_or_boolean(first, last):
    with pytest.raises(PackageError, match="PAGE_RANGE_INVALID"):
        DocumentPart("a", "technical", first, last)


def test_json_schema_validates_real_manifest_and_rejects_extra_fields():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).parents[1] / "packages/contracts/schemas/bid-package.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    manifest = package().manifest()
    jsonschema.validate(manifest, schema)
    manifest["current_body_id"] = "implicit-last-file"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_missing_target_category_cannot_be_verified_even_with_evidence():
    p = package()
    r = requirement(p, categories=("qualification",))
    with pytest.raises(PackageError, match="VERIFIED_TARGET_EMPTY"):
        assess(p, r, checked(p, r, inspected=()))


def test_disjoint_inspected_intervals_cannot_hide_one_missing_page():
    p = package(member(pages=100000000))
    intervals = (
        InspectedRange("part-member-1", 1, 50),
        InspectedRange("part-member-1", 52, 100000000),
    )
    with pytest.raises(PackageError, match="SCOPE_INCOMPLETE"):
        assess(p, requirement(p), checked(p, inspected=intervals))
    assert assess(
        p,
        requirement(p),
        checked(
            p,
            inspected=(
                InspectedRange("part-member-1", 1, 51),
                intervals[1],
            ),
        ),
    )["complete"]


def test_count_expiry_format_and_signature_are_recorded_without_fabricating_checks():
    p = package()
    r = requirement(
        p,
        minimum_count=2,
        conditions=("joint venture only",),
        checks=("quantity", "expiry", "signature", "format"),
        valid_at="2026-10-18T12:00:00+08:00",
    )
    assert r.minimum_count == 2
    with pytest.raises(PackageError, match="VALID_AT_INVALID"):
        replace(r, valid_at="2026-10-18T12:00:00")
    unknown = replace(r, applicability="unknown")
    with pytest.raises(PackageError, match="APPLICABILITY_UNRESOLVED"):
        assess(p, unknown, checked(p, unknown))


def test_requirement_and_coverage_schema_definitions_and_parse_negative_case():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).parents[1] / "packages/contracts/schemas/bid-package.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    p = package()
    for definition, value in (("requirement", requirement(p)), ("coverage", checked(p))):
        selected = {
            "$schema": schema["$schema"],
            "$ref": "#/$defs/" + definition,
            "$defs": schema["$defs"],
        }
        jsonschema.validate(
            json.loads(json.dumps(asdict(value))),
            selected,
            format_checker=jsonschema.FormatChecker(),
        )
    invalid = p.manifest()
    invalid["members"][0]["parse"]["status"] = "not_frozen"
    invalid["members"][0]["parse"]["reason"] = "inferred later"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_refs": ("supplement:v2:page-10",)},
        {"checks": ("quantity", "expiry", "signature")},
        {"checks": ("quantity",), "minimum_count": 20},
        {"valid_at": "2026-11-01T00:00:00Z"},
        {"conditions": ("joint venture mandatory",)},
        {"target_part_ids": ("part-member-1",)},
    ],
)
def test_same_requirement_id_changed_content_cannot_reuse_previous_verification(changes):
    p = package()
    old = requirement(p)
    result = checked(p, old)
    assert assess(p, old, result)["complete"]
    altered = replace(old, **changes)
    assert altered.requirement_id == old.requirement_id
    assert altered.manifest_digest != old.manifest_digest
    with pytest.raises(PackageError, match="COVERAGE_REQUIREMENT_STALE"):
        assess(p, altered, result)
    assert assess(p, old, result)["complete"]
    detached = old.manifest()
    detached["source_refs"].append("untrusted-new-source")
    assert old.manifest_digest == result.requirement_digest


@pytest.mark.parametrize("different_bytes", [False, True])
def test_one_parse_run_id_cannot_bind_two_document_versions(different_bytes):
    one = member("one")
    two = member("two", parse=one.parse, file_digest=("e" if different_bytes else "a") * 64)
    with pytest.raises(PackageError, match="PARSE_ID_REUSED"):
        package(one, two)


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_digest": "e" * 64},
        {"parser_digest": "e" * 64},
        {"config_digest": "e" * 64},
    ],
)
def test_next_revision_cannot_rebind_existing_parse_id_to_changed_parse(changes):
    p = package()
    altered = replace(p.members[0], parse=replace(p.members[0].parse, **changes))
    with pytest.raises(PackageError, match="PARSE_ID_REBOUND"):
        p.next_revision("revision-2", (altered,))
    # 同一精确解析可用于仅改变逻辑分类的新包；不会伪造新的解析。
    updated = p.next_revision(
        "revision-2", (replace(p.members[0], purposes=("technical", "annex")),)
    )
    assert updated.members[0].parse == p.members[0].parse


@pytest.mark.parametrize("page_count", [None, 4])
def test_unknown_pages_or_unassigned_parts_can_be_registered_without_fabrication(page_count):
    unread = member(
        "encrypted",
        category="qualification",
        page_count=page_count,
        parse=ParseIdentity("not_frozen", reason="encrypted or awaiting segmentation"),
        parts=(),
    )
    p = package(member(), unread)
    assert p.manifest()["members"][1]["page_count"] == page_count
    assert p.manifest()["members"][1]["parts"] == []
    assert not p.formal_eligible
    with pytest.raises(PackageError, match="PARSE_NOT_FROZEN"):
        p.require_formal()
    r = requirement(p, categories=("qualification",))
    report = assess(
        p,
        r,
        checked(
            p,
            r,
            state=CoverageState.UNSUPPORTED,
            inspected=(),
            reason="encrypted source requires decryption",
        ),
    )
    assert not report["complete"]
    assert report["inspected_ranges"] == []
    assert report["member_gaps"][0]["document_version_id"] == unread.document_version_id
    assert "parts_unassigned" in report["member_gaps"][0]["codes"]
    assert ("page_count_unknown" in report["member_gaps"][0]["codes"]) == (page_count is None)
    with pytest.raises(PackageError, match="VERIFIED_TARGET_EMPTY"):
        assess(p, r, checked(p, r, inspected=()))
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (
            Path(__file__).parents[1] / "packages/contracts/schemas/bid-package.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(p.manifest(), schema)


def test_unknown_page_scope_cannot_invent_parts_or_claim_frozen_parse():
    with pytest.raises(PackageError, match="UNKNOWN_PAGE_SCOPE_FORBIDDEN"):
        member(page_count=None)
    with pytest.raises(PackageError, match="UNKNOWN_SCOPE_PARSE_FROZEN"):
        member(page_count=None, parts=())
    with pytest.raises(PackageError, match="UNKNOWN_SCOPE_PARSE_FROZEN"):
        member(parts=())


INTEGER_FACTORIES = [
    (
        lambda value: replace(package(), revision=value, predecessor_digest="e" * 64),
        None,
        "PACKAGE_REVISION_INVALID",
        ("revision",),
    ),
    (
        lambda value: member(page_count=value),
        "member",
        "PACKAGE_PAGE_COUNT_INVALID",
        ("page_count",),
    ),
    (
        lambda value: DocumentPart("part", "technical", value, MAX_SAFE_INTEGER),
        "part",
        "PACKAGE_PAGE_RANGE_INVALID",
        ("first_page",),
    ),
    (
        lambda value: DocumentPart("part", "technical", 1, value),
        "part",
        "PACKAGE_PAGE_RANGE_INVALID",
        ("last_page",),
    ),
    (
        lambda value: DocumentPart("part", "technical", 1, 2, heading_path=(value,)),
        "part",
        "PACKAGE_HEADING_PATH_INVALID",
        ("heading_path", 0),
    ),
    (
        lambda value: requirement(package(), minimum_count=value, checks=("quantity",)),
        "requirement",
        "PACKAGE_REQUIREMENT_COUNT_INVALID",
        ("minimum_count",),
    ),
    (
        lambda value: InspectedRange("part", value, MAX_SAFE_INTEGER),
        "inspectedRange",
        "PACKAGE_INSPECTED_RANGE_INVALID",
        ("first_page",),
    ),
    (
        lambda value: InspectedRange("part", 1, value),
        "inspectedRange",
        "PACKAGE_INSPECTED_RANGE_INVALID",
        ("last_page",),
    ),
]


@pytest.mark.parametrize("factory,definition,error_code,path", INTEGER_FACTORIES)
def test_safe_integer_boundaries_match_domain_schema_and_canonical(
    factory, definition, error_code, path
):
    from packages.domain.review_identity import digest

    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (
            Path(__file__).parents[1] / "packages/contracts/schemas/bid-package.schema.json"
        ).read_text(encoding="utf-8")
    )
    selected = (
        schema
        if definition is None
        else {
            "$schema": schema["$schema"],
            "$ref": "#/$defs/" + definition,
            "$defs": schema["$defs"],
        }
    )
    valid = factory(MAX_SAFE_INTEGER)
    payload = json.loads(json.dumps(asdict(valid)))
    assert len(digest(payload)) == 64
    jsonschema.validate(payload, selected)
    with pytest.raises(PackageError) as error:
        factory(MAX_SAFE_INTEGER + 1)
    assert error.value.code == error_code
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = MAX_SAFE_INTEGER + 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, selected)


def test_revision_exhaustion_is_stable_domain_error_before_canonical_hash_failure():
    p = replace(package(), revision=MAX_SAFE_INTEGER, predecessor_digest="e" * 64)
    with pytest.raises(PackageError, match="PACKAGE_REVISION_INVALID"):
        p.next_revision("too-large-revision", p.members)
