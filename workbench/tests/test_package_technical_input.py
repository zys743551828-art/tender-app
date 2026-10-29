"""Synthetic complete-material binding, never business or formal input authority."""

import io
import socket
from copy import deepcopy
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from reportlab.pdfgen import canvas

from packages.contracts import package_technical_input as contract
from packages.domain.review_identity import digest
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import package_technical_features as features
from packages.model_governance import package_technical_input as inputs
from packages.model_governance import technical_png as png


def uid(number):
    return str(UUID(int=number))


@pytest.fixture(scope="module")
def frozen():
    bundles, documents, evidence = {}, [], []
    for index in (1, 2):
        output = io.BytesIO()
        pdf = canvas.Canvas(output, pagesize=(100, 150), invariant=1)
        for page in (1, 2):
            pdf.drawString(5, 70, f"Synthetic {index} {page}")
            pdf.showPage()
        pdf.save()
        data = output.getvalue()
        bundle = assets.render_static_pdf(
            data,
            document_version_id=uid(index),
            expected_source_digest=png.digest_bytes(data),
            expected_source_size=len(data),
            expected_method_digest=assets.render_method_digest(),
        )
        first = bundle.manifest["pages"][0]["asset"]
        bundle = assets.crop_page_assets(
            bundle,
            [
                {
                    "physical_page": 1,
                    "parent_image_digest": first["sha256"],
                    "rectangle": [0, 0, 90, 90],
                }
            ],
            expected_manifest_digest=bundle.manifest["digest"],
            expected_method_digest=assets.crop_method_digest(),
        )
        bundles[uid(index)] = bundle
        documents.append(
            {
                "document_version_id": uid(index),
                "package_role": "target" if index == 1 else "authority",
                "source_digest": png.digest_bytes(data),
                "source_byte_size": len(data),
                "parse_run_id": uid(index + 10),
                "parse_digest": "b" * 64,
                "page_count": 2,
                "asset_manifest_digest": bundle.manifest["digest"],
            }
        )
        for page in bundle.manifest["pages"]:
            text = f"Synthetic exact clause {index} page {page['physical_page']}"
            evidence.append(
                {
                    "evidence_id": uid(index * 100 + page["physical_page"]),
                    "document_version_id": uid(index),
                    "parse_run_id": uid(index + 10),
                    "physical_page": page["physical_page"],
                    "part_ids": ["section" if index == 1 else "appendix"],
                    "text": text,
                    "text_digest": png.digest_bytes(text.encode()),
                    "page_image_digest": page["asset"]["sha256"],
                    "page_width": page["asset"]["width"],
                    "page_height": page["asset"]["height"],
                }
            )
    binding = {key: "a" * 64 for key in contract.BINDING["properties"]}
    binding.update(scope_id=uid(99), input_as_of="2026-10-23T00:00:00Z")
    projection = {
        "version": "package-technical-input-projection/2",
        "binding": binding,
        "documents": documents,
        "parts": [
            {
                "part_id": "section",
                "document_version_id": uid(1),
                "parent_part_id": None,
                "related_part_ids": ["appendix"],
                "physical_pages": [1, 2],
            },
            {
                "part_id": "child",
                "document_version_id": uid(1),
                "parent_part_id": "section",
                "related_part_ids": [],
                "physical_pages": [1],
            },
            {
                "part_id": "appendix",
                "document_version_id": uid(2),
                "parent_part_id": None,
                "related_part_ids": ["section"],
                "physical_pages": [1, 2],
            },
        ],
        "rules": [
            {
                "rule_id": uid(55),
                "rule_digest": "c" * 64,
                "source_evidence_id": uid(201),
                "source_quote": evidence[2]["text"],
                "source_quote_digest": evidence[2]["text_digest"],
                "required_part_ids": ["section"],
                "band_ids": [],
            }
        ],
        "evidence_catalog": evidence,
    }
    return projection, bundles


def build(projection, bundles):
    return inputs.build_input(
        projection,
        bundles,
        expected_projection_digest=digest(projection),
        expected_method_digest=inputs.method_digest(),
    )


def test_actual_rendered_pages_details_all_text_and_transitive_parts_are_retained(frozen):
    projection, bundles = frozen
    original_digest = digest(projection)
    result = build(projection, bundles)
    m = result.metadata
    assert m["physical_page_count"] == 4 and m["image_count"] == 6
    assert m["rule_packets"][0]["required_part_ids"] == ["section", "child", "appendix"]
    assert m["material"]["evidence_catalog"] == projection["evidence_catalog"]
    assert [(r["document_version_id"], r["physical_page"]) for r in m["material"]["pages"]] == [
        (uid(1), 1),
        (uid(1), 2),
        (uid(2), 1),
        (uid(2), 2),
    ]
    assert result.blobs == {
        key: raw for bundle in bundles.values() for key, raw in bundle.blobs.items()
    }
    assert m["asset_byte_count"] == sum(map(len, result.blobs.values()))
    assert digest(projection) == original_digest
    assert Draft202012Validator(contract.output_schema(), format_checker=FormatChecker()).is_valid(
        m
    )
    assert all(
        not m[key]
        for key in (
            "input_authority_granted",
            "original_bytes_reverified",
            "visual_readability_verified",
            "historical_byte_existence_verified",
            "provider_payload_verified",
            "execution_authorized",
            "formal_prediction_eligible",
            "training_eligible",
        )
    )
    assert "Synthetic" not in repr(result)


def test_same_input_repeats_identically_and_does_not_alias_caller_metadata(frozen):
    projection, bundles = frozen
    result = build(projection, bundles)
    assert result.metadata == build(projection, bundles).metadata
    result.metadata["material"]["evidence_catalog"][0]["text"] = "changed output"
    result.blobs.clear()
    assert (
        build(projection, bundles).metadata["material"]["evidence_catalog"]
        == projection["evidence_catalog"]
    )


def test_even_unselected_page_or_evidence_change_changes_every_rule_semantic_input(frozen):
    projection, bundles = frozen
    baseline = build(projection, bundles).metadata
    changed = deepcopy(projection)
    changed["evidence_catalog"][-1]["text"] += " retained context"
    changed["evidence_catalog"][-1]["text_digest"] = png.digest_bytes(
        changed["evidence_catalog"][-1]["text"].encode()
    )
    current = build(changed, bundles).metadata
    assert current["material_digest"] != baseline["material_digest"]
    assert (
        current["rule_packets"][0]["semantic_input_digest"]
        != baseline["rule_packets"][0]["semantic_input_digest"]
    )


@pytest.mark.parametrize(
    "field", ["official_score", "final_export", "chat", "previous_judgment", "real"]
)
def test_foreign_channels_cannot_enter_closed_projection(frozen, field):
    projection, bundles = frozen
    changed = deepcopy(projection)
    changed[field] = "forbidden"
    with pytest.raises(inputs.TechnicalInputError, match="PROJECTION_INVALID"):
        build(changed, bundles)


@pytest.mark.parametrize("target", ["projection", "method"])
def test_owned_expected_digests_are_required_independently(frozen, target):
    projection, bundles = frozen
    with pytest.raises(inputs.TechnicalInputError, match="MISMATCH"):
        inputs.build_input(
            projection,
            bundles,
            expected_projection_digest="0" * 64 if target == "projection" else digest(projection),
            expected_method_digest="0" * 64 if target == "method" else inputs.method_digest(),
        )


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda p: p["documents"].append(deepcopy(p["documents"][0])), "DOCUMENT_REUSED"),
        (lambda p: p["documents"][1].update(parse_run_id=uid(11)), "PARSE_REUSED"),
        (lambda p: p["documents"][0].update(source_digest="0" * 64), "SOURCE_MISMATCH"),
        (lambda p: p["documents"][0].update(page_count=1), "PART_PAGE_MISMATCH"),
        (lambda p: p["documents"][0].update(source_byte_size=1), "SOURCE_MISMATCH"),
        (lambda p: p["evidence_catalog"][0].update(parse_run_id=uid(12)), "EVIDENCE_PAGE_MISMATCH"),
        (lambda p: p["evidence_catalog"][0].update(physical_page=3), "EVIDENCE_PAGE_MISMATCH"),
        (lambda p: p["evidence_catalog"][0].update(page_width=1), "EVIDENCE_PAGE_MISMATCH"),
        (
            lambda p: p["evidence_catalog"][0].update(page_image_digest="0" * 64),
            "EVIDENCE_PAGE_MISMATCH",
        ),
        (lambda p: p["evidence_catalog"][0].update(text="invented"), "TEXT_MISMATCH"),
        (
            lambda p: p["evidence_catalog"][0].update(part_ids=["appendix"]),
            "EVIDENCE_PART_MISMATCH",
        ),
        (
            lambda p: p["evidence_catalog"].append(deepcopy(p["evidence_catalog"][0])),
            "EVIDENCE_REUSED",
        ),
        (lambda p: p["parts"].append(deepcopy(p["parts"][0])), "PART_REUSED"),
        (lambda p: p["parts"][1].update(parent_part_id="appendix"), "PARENT_MISMATCH"),
        (lambda p: p["parts"][0].update(parent_part_id="child"), "CHILD_OUTSIDE_PARENT"),
        (lambda p: p["parts"][0].update(physical_pages=[2, 1]), "PART_PAGE_ORDER"),
        (lambda p: p["parts"][0].update(related_part_ids=["missing"]), "RELATED_PART_MISMATCH"),
        (lambda p: p["rules"][0].update(required_part_ids=["missing"]), "REQUIRED_PART_MISSING"),
        (lambda p: p["rules"][0].update(source_evidence_id=uid(999)), "RULE_SOURCE_MISMATCH"),
        (lambda p: p["rules"][0].update(source_quote="not in original"), "RULE_SOURCE_MISMATCH"),
        (lambda p: p["rules"][0].update(source_quote_digest="0" * 64), "RULE_SOURCE_MISMATCH"),
        (lambda p: p["rules"].append(deepcopy(p["rules"][0])), "RULE_REUSED"),
    ],
)
def test_cross_document_missing_page_and_scope_corruption_fail_closed(frozen, change, code):
    projection, bundles = frozen
    changed = deepcopy(projection)
    change(changed)
    with pytest.raises(inputs.TechnicalInputError, match=code):
        build(changed, bundles)


def test_parent_cycles_are_rejected_but_related_cycles_are_bounded(frozen):
    projection, bundles = frozen
    changed = deepcopy(projection)
    changed["parts"][1]["physical_pages"] = [1, 2]
    changed["parts"][0]["parent_part_id"] = "child"
    with pytest.raises(inputs.TechnicalInputError, match="PARENT_CYCLE"):
        build(changed, bundles)


@pytest.mark.parametrize("mode", ["missing", "extra", "replaced"])
def test_asset_bundle_map_has_exact_frozen_documents(frozen, mode):
    projection, bundles = frozen
    changed = dict(bundles)
    if mode == "missing":
        changed.pop(uid(1))
    elif mode == "extra":
        changed[uid(999)] = bundles[uid(1)]
    else:
        changed[uid(1)] = bundles[uid(2)]
    with pytest.raises((inputs.TechnicalInputError, png.PageAssetError), match="MISMATCH"):
        build(projection, changed)


def test_changed_blob_cannot_be_hidden_by_projection_rehash(frozen):
    projection, bundles = frozen
    bad = assets.PageAssetBundle(deepcopy(bundles[uid(1)].manifest), dict(bundles[uid(1)].blobs))
    first = next(iter(bad.blobs))
    bad.blobs[first] = b"not a PNG"
    changed = dict(bundles)
    changed[uid(1)] = bad
    with pytest.raises(png.PageAssetError, match="BLOB_MISMATCH"):
        build(projection, changed)


def test_missing_frozen_page_is_rejected_even_after_resealing_asset_manifest(frozen):
    projection, bundles = frozen
    changed_projection = deepcopy(projection)
    bad = assets.PageAssetBundle(deepcopy(bundles[uid(1)].manifest), dict(bundles[uid(1)].blobs))
    missing = bad.manifest["pages"].pop()
    bad.blobs.pop(missing["asset"]["id"])
    bad.manifest["digest"] = digest(
        {key: value for key, value in bad.manifest.items() if key != "digest"}
    )
    changed_projection["documents"][0]["asset_manifest_digest"] = bad.manifest["digest"]
    changed = dict(bundles)
    changed[uid(1)] = bad
    with pytest.raises(png.PageAssetError, match="PAGE_SET_INCOMPLETE"):
        build(changed_projection, changed)


@pytest.mark.parametrize(
    "limit",
    [
        "MAX_PROJECTION_BYTES",
        "MAX_METADATA_BYTES",
        "MAX_TEXT_BYTES",
        "MAX_ASSET_BYTES",
        "MAX_TOTAL_PIXELS",
        "MAX_PAGES",
        "MAX_IMAGES",
    ],
)
def test_capacity_failure_returns_no_partial_input(frozen, monkeypatch, limit):
    projection, bundles = frozen
    monkeypatch.setattr(inputs, limit, 1)
    with pytest.raises(inputs.TechnicalInputError, match="LIMIT"):
        build(projection, bundles)


def test_invalid_canonical_values_fail_with_bounded_error(frozen):
    projection, bundles = frozen
    for value in (0.5, "\ud800"):
        changed = deepcopy(projection)
        changed["foreign"] = value
        with pytest.raises(inputs.TechnicalInputError, match="PROJECTION_INVALID"):
            inputs.build_input(
                changed,
                bundles,
                expected_projection_digest="0" * 64,
                expected_method_digest=inputs.method_digest(),
            )


def test_rule_quote_must_come_from_authority_and_required_root_from_target(frozen):
    projection, bundles = frozen
    changed = deepcopy(projection)
    row = changed["evidence_catalog"][0]
    changed["rules"][0].update(
        source_evidence_id=row["evidence_id"],
        source_quote=row["text"],
        source_quote_digest=row["text_digest"],
    )
    with pytest.raises(inputs.TechnicalInputError, match="RULE_SOURCE_MISMATCH"):
        build(changed, bundles)
    changed = deepcopy(projection)
    changed["rules"][0]["required_part_ids"] = ["appendix"]
    with pytest.raises(inputs.TechnicalInputError, match="RULE_TARGET_MISMATCH"):
        build(changed, bundles)


@pytest.mark.parametrize("role", ["authority", "target"])
def test_both_package_roles_are_required(frozen, role):
    projection, bundles = frozen
    changed = deepcopy(projection)
    for row in changed["documents"]:
        row["package_role"] = role
    with pytest.raises(inputs.TechnicalInputError, match="PACKAGE_ROLES_MISSING"):
        build(changed, bundles)


def test_input_semantics_and_real_page_catalog_feed_three_slot_features(frozen):
    projection, bundles = frozen
    projection = deepcopy(projection)
    projection["evidence_catalog"][0]["part_ids"].append("child")
    built = build(projection, bundles).metadata
    packet = built["rule_packets"][0]
    rule = {key: packet["rule"][key] for key in ("rule_id", "rule_digest", "band_ids")}
    rule.update(
        semantic_input_digest=packet["semantic_input_digest"],
        request_digest="d" * 64,
        required_part_ids=packet["required_part_ids"],
    )
    citations = [
        {
            **{
                key: row[key]
                for key in (
                    "evidence_id",
                    "document_version_id",
                    "parse_run_id",
                    "physical_page",
                    "page_image_digest",
                )
            },
            "quote": row["text"],
            "region": None,
        }
        for row in projection["evidence_catalog"]
    ]
    judgment = {
        "status": "valid",
        "coverage": "complete",
        "band_id": None,
        "reason": "Synthetic only",
        "covered_part_ids": packet["required_part_ids"],
        "evidence": citations,
        "dimensions": {key: "uncertain" for key in ("specificity", "validity", "consistency")},
    }
    attempts = []
    for slot in (1, 2, 3):
        attempts.append(
            {
                "rule_id": rule["rule_id"],
                "slot": slot,
                "attempt": 1,
                "call_id": uid(900 + slot),
                "semantic_input_digest": rule["semantic_input_digest"],
                "request_digest": rule["request_digest"],
                "judgment_method_digest": projection["binding"]["judgment_method_digest"],
                "provider_profile_digest": projection["binding"]["provider_profile_digest"],
                "state": "succeeded",
                "response_model": "synthetic-response",
                "response_id": f"synthetic-{slot}",
                "response_digest": digest({"synthetic": slot}),
                "judgment_digest": digest(judgment),
                "judgment": deepcopy(judgment),
            }
        )
    feature_projection = {
        "version": "package-technical-feature-projection/2",
        "binding": projection["binding"],
        "provider": {
            "provider_id": "synthetic",
            "model_alias": "synthetic",
            "response_model": "synthetic-response",
        },
        "max_attempts_per_slot": 1,
        "rules": [rule],
        "evidence_catalog": projection["evidence_catalog"],
        "attempts": attempts,
    }
    result = features.build_features(
        feature_projection,
        expected_projection_digest=digest(feature_projection),
        expected_method_digest=features.method_digest(),
    )
    assert result["feature_coverage"] == "complete"
    assert result["items"][0]["valid_slot_count"] == 3
    feature_projection["attempts"].pop()
    partial = features.build_features(
        feature_projection,
        expected_projection_digest=digest(feature_projection),
        expected_method_digest=features.method_digest(),
    )
    assert partial["feature_coverage"] == "partial" and partial["items"][0]["features"] is None


def test_build_has_no_network_or_private_environment_port(frozen, monkeypatch):
    projection, bundles = frozen
    expected = build(projection, bundles).metadata

    def no_network(*args, **kwargs):
        raise AssertionError("no network allowed in pure material binding")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("WORKBENCH_ENV_FILE", "nonexistent-explicit-forbidden-profile")
    assert build(projection, bundles).metadata == expected


def context_projection(projection):
    value = deepcopy(projection)
    value["version"] = "package-technical-context-projection/2"
    value["binding"].pop("input_verification_digest")
    return value


def make_context(frozen):
    projection, bundles = frozen
    projection = context_projection(projection)
    return inputs.build_verification_context(
        projection,
        bundles,
        expected_projection_digest=digest(projection),
        expected_method_digest=inputs.context_method_digest(),
    )


def reference(context, receipt="synthetic receipt one"):
    return {
        "version": "package-technical-verification-binding/2",
        "verification_id": uid(999),
        "verification_receipt_digest": png.digest_bytes(receipt.encode()),
        "context_digest": context.metadata["digest"],
        "context_method_digest": context.metadata["context_method_digest"],
    }


def bind(context, record):
    return inputs.bind_input(
        context,
        record,
        expected_context_digest=context.metadata["digest"],
        expected_binding_digest=digest(record),
        expected_method_digest=inputs.method_digest(),
    )


def test_verification_context_has_no_receipt_and_binding_is_acyclic(frozen):
    context = make_context(frozen)
    before = digest(context.metadata)
    assert "input_verification_digest" not in context.metadata["material"]["binding"]
    one, two = reference(context), reference(context, "synthetic receipt two")
    first, second = bind(context, one), bind(context, two)
    assert digest(context.metadata) == before
    assert first.metadata["digest"] != second.metadata["digest"]
    assert (
        first.metadata["material"]["binding"]["input_verification_digest"]
        == one["verification_receipt_digest"]
    )
    assert (
        second.metadata["material"]["binding"]["input_verification_digest"]
        == two["verification_receipt_digest"]
    )
    assert first.blobs == second.blobs
    assert (
        not first.metadata["input_authority_granted"] and not first.metadata["execution_authorized"]
    )
    assert "Synthetic" not in repr(context)


def test_context_rejects_receipt_placeholder_field_and_final_input_protocol(frozen):
    projection, bundles = frozen
    for changed in (deepcopy(projection), context_projection(projection)):
        changed["binding"]["input_verification_digest"] = "0" * 64
        with pytest.raises(inputs.TechnicalInputError, match="CONTEXT_PROJECTION_INVALID"):
            inputs.build_verification_context(
                changed,
                bundles,
                expected_projection_digest=digest(changed),
                expected_method_digest=inputs.context_method_digest(),
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_digest", "0" * 64),
        ("context_method_digest", "0" * 64),
        ("verification_receipt_digest", "0" * 64),
    ],
)
def test_reference_must_belong_to_exact_context_and_have_nonplaceholder_receipt(
    frozen, field, value
):
    context = make_context(frozen)
    record = reference(context)
    record[field] = value
    with pytest.raises(inputs.TechnicalInputError, match="BINDING_MISMATCH"):
        bind(context, record)


@pytest.mark.parametrize("owned", ["context", "binding", "method"])
def test_context_and_native_binding_each_need_independent_owned_digest(frozen, owned):
    context = make_context(frozen)
    record = reference(context)
    with pytest.raises(inputs.TechnicalInputError, match="MISMATCH"):
        inputs.bind_input(
            context,
            record,
            expected_context_digest="0" * 64 if owned == "context" else context.metadata["digest"],
            expected_binding_digest="0" * 64 if owned == "binding" else digest(record),
            expected_method_digest="0" * 64 if owned == "method" else inputs.method_digest(),
        )


def test_context_rebuild_rejects_scope_forgery_even_with_new_outer_hash(frozen):
    context = make_context(frozen)
    context.metadata["rule_scopes"][0]["required_part_ids"].remove("child")
    context.metadata["digest"] = digest(
        {key: value for key, value in context.metadata.items() if key != "digest"}
    )
    with pytest.raises(inputs.TechnicalInputError, match="REBUILD_MISMATCH"):
        bind(context, reference(context))


def test_final_binding_reverifies_frozen_assets_and_keeps_context_immutable(frozen):
    context = make_context(frozen)
    projection, original_bundles = frozen
    original_hashes = {key: bundle.manifest["digest"] for key, bundle in original_bundles.items()}
    first = next(iter(context.bundles[uid(1)].blobs))
    context.bundles[uid(1)].blobs[first] = b"changed private context blob"
    with pytest.raises(png.PageAssetError, match="BLOB_MISMATCH"):
        bind(context, reference(context))
    assert {
        key: bundle.manifest["digest"] for key, bundle in original_bundles.items()
    } == original_hashes
    assert build(projection, original_bundles).metadata["physical_page_count"] == 4


def test_contexts_change_with_any_material_binding_and_method_mismatch_is_rejected(frozen):
    projection, bundles = frozen
    old = make_context(frozen)
    changed = context_projection(projection)
    changed["binding"]["input_as_of"] = "2026-10-24T00:00:00Z"
    current = inputs.build_verification_context(
        changed,
        bundles,
        expected_projection_digest=digest(changed),
        expected_method_digest=inputs.context_method_digest(),
    )
    assert current.metadata["digest"] != old.metadata["digest"]
    with pytest.raises(inputs.TechnicalInputError, match="CONTEXT_METHOD_MISMATCH"):
        inputs.build_verification_context(
            changed,
            bundles,
            expected_projection_digest=digest(changed),
            expected_method_digest="0" * 64,
        )
