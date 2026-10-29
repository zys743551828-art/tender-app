"""Bounded synthetic evidence, private launch profiles, and actual CPU invariants."""

import base64
from copy import deepcopy
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from package_history_fixtures import evidence, revise

from deploy.package_history_worker import environment
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance import package_history_proofs as proofs
from packages.model_governance.common import GovernanceError, digest


def source_fixture():
    """No real historical evidence: source assertions and raster are synthetic."""
    original, official = b"synthetic complete package original", b"synthetic official zero"
    quote = "技术总分满分为20分，量尺为未加权原始分；聚合口径为官方公布的最终技术总分。"
    identity = str(uuid4())
    context = {
        "scope": {"id": str(uuid4()), "digest": "a" * 64},
        "identity": {"digest": "b" * 64, "bidder_id": str(uuid4())},
        "basis": {"inventory_digest": "c" * 64, "package_digest": "d" * 64},
        "submission": {"submitted_at": "2025-03-01T00:00:00Z"},
        "target_files": [{"digest": proofs.sha(original), "byte_size": len(original)}],
        "technical_part_ids": [str(uuid4())],
        "rule_scopes": [{"rule_id": str(uuid4()), "selection": "include"}],
        "applicable_rules": [{"maximum": "20"}],
        "originals": [
            {
                "document_version_id": identity,
                "digest": proofs.sha(original),
                "byte_size": len(original),
                "obtained_at": "2025-01-01T00:00:00Z",
                "requires_effective_proof": True,
            }
        ],
        "documents": [
            {
                "document_version_id": identity,
                "file_digest": proofs.sha(original),
                "package_role": "authority",
                "parse": {"parse_run_id": str(uuid4())},
                "pages": [{"physical_page": 1, "quality": "usable", "gaps": []}],
                "blocks": [
                    {
                        "id": str(uuid4()),
                        "physical_page": 1,
                        "text_content": quote,
                        "digest": proofs.sha(quote.encode()),
                    }
                ],
            }
        ],
        "label": {
            "value": "0",
            "maximum": "20",
            "file_digest": proofs.sha(official),
            "byte_size": len(official),
        },
    }
    key = Ed25519PrivateKey.generate()
    adapter = {
        "id": str(uuid4()),
        "method": proofs.ADAPTER,
        "origin": "synthetic",
        "source_prefix": "fixture://",
        "public_key_hex": key.public_key().public_bytes_raw().hex(),
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_until": None,
    }
    signed = evidence(
        context,
        adapter["id"],
        key,
        {proofs.sha(original): original, proofs.sha(official): official},
    )
    return context, adapter, key, signed


def verify(context, adapter, signed):
    return proofs.verify(
        signed, adapter=adapter, context=context, observed_at=signed["payload"]["issued_at"]
    )


def resign(envelope, key):
    envelope["signature_base64"] = base64.b64encode(
        key.sign(proofs.canonical(envelope["payload"]))
    ).decode()
    return envelope


def test_valid_signature_binds_all_synthetic_evidence_without_formal_qualification():
    context, adapter, key, signed = source_fixture()
    result = verify(context, adapter, signed)
    assert result["historical_as_of"] == context["submission"]["submitted_at"]
    assert result["origin"] == "synthetic" and result["research_only"]
    assert not result["strict_prebid_eligible"] and not result["online_metrics_eligible"]
    assert result["formal_eligibility"] == "unavailable"
    assert result["scale"]["maximum"] == "20"
    assert result["context_digest"] == digest(context)


@pytest.mark.parametrize(
    ("kind", "change", "code"),
    [
        ("exists", {"original_sha256": "0" * 64}, "HISTORICAL_BYTES_UNPROVEN"),
        ("exists", {"recorded_at": "2025-04-01T00:00:00Z"}, "HISTORICAL_TIME_UNPROVEN"),
        ("acquired", {"party_id": "wrong-bidder"}, "HISTORICAL_PARTY_UNPROVEN"),
        ("acquired", {"at": "2024-01-01T00:00:00Z"}, "HISTORICAL_ACQUISITION_MISMATCH"),
        ("effective", {"valid_until": "2025-02-01T00:00:00Z"}, "HISTORICAL_AUTHORITY_EXPIRED"),
    ],
)
def test_authentic_signed_but_incompatible_historical_assertions_are_rejected(kind, change, code):
    context, adapter, key, signed = source_fixture()
    revise(signed, key, signed["payload"]["documents"][0][kind], lambda value: value.update(change))
    with pytest.raises(GovernanceError) as caught:
        verify(context, adapter, signed)
    assert caught.value.code == "PACKAGE_HISTORY_" + code


@pytest.mark.parametrize(
    ("resource", "change", "code"),
    [
        ("submission_resource", {"identity_digest": "f" * 64}, "ACTUAL_SUBMISSION_UNPROVEN"),
        ("submission_resource", {"files": []}, "ACTUAL_SUBMISSION_UNPROVEN"),
        ("coverage_resource", {"parts": []}, "REQUIRED_RANGE_UNPROVEN"),
        ("coverage_resource", {"rules": []}, "REQUIRED_RANGE_UNPROVEN"),
        ("coverage_resource", {"pages": []}, "FULL_VISUAL_UNPROVEN"),
        ("scale_resource", {"aggregation": "unknown"}, "MAXIMUM_AGGREGATION_UNPROVEN"),
        ("scale_resource", {"aggregation": "mean"}, "MAXIMUM_AGGREGATION_UNPROVEN"),
        ("scale_resource", {"maximum": "60"}, "MAXIMUM_AGGREGATION_UNPROVEN"),
        ("grouping_resource", {"source_references": []}, "GROUPING_UNPROVEN"),
    ],
)
def test_authentic_signature_cannot_replace_actual_submission_range_scale_or_group_evidence(
    resource, change, code
):
    context, adapter, key, signed = source_fixture()
    revise(signed, key, signed["payload"][resource], lambda value: value.update(change))
    with pytest.raises(GovernanceError) as caught:
        verify(context, adapter, signed)
    assert caught.value.code == "PACKAGE_HISTORY_" + code


def test_all_ancestors_and_all_original_resource_bytes_are_required():
    context, adapter, key, signed = source_fixture()
    signed["payload"]["documents"] = []
    resign(signed, key)
    with pytest.raises(GovernanceError, match="All originals"):
        verify(context, adapter, signed)
    context, adapter, key, signed = source_fixture()
    signed["resources"][0]["data_base64"] = base64.b64encode(b"different modern bytes").decode()
    with pytest.raises(GovernanceError) as caught:
        verify(context, adapter, signed)
    assert caught.value.code == "PACKAGE_HISTORY_EVIDENCE_BYTES"


def test_tampered_signature_context_duplicates_or_surplus_boolean_do_not_qualify():
    context, adapter, key, signed = source_fixture()
    signed["payload"]["receipt_id"] = "different"
    with pytest.raises(GovernanceError) as caught:
        verify(context, adapter, signed)
    assert caught.value.code == "PACKAGE_HISTORY_SIGNATURE_INVALID"
    resign(signed, key)
    context["identity"]["digest"] = "e" * 64
    with pytest.raises(GovernanceError) as caught:
        verify(context, adapter, signed)
    assert caught.value.code == "PACKAGE_HISTORY_PROOF_BINDING"
    with pytest.raises(GovernanceError):
        proofs.load(b'{"key":1,"key":2}')
    context, adapter, key, signed = source_fixture()
    signed["qualified"] = True
    with pytest.raises(GovernanceError) as caught:
        verify(context, adapter, signed)
    assert caught.value.code == "PACKAGE_HISTORY_EVIDENCE_SHAPE"


def test_private_profiles_reject_cross_purpose_secrets_permissions_and_symlinks(tmp_path):
    profile = tmp_path / "purpose.env"
    profile.write_text("PACKAGE_HISTORY_TRAIN_DSN='dbname=synthetic user=trainer'\n")
    profile.chmod(0o600)
    assert set(environment(profile, "train")) == {
        "PACKAGE_HISTORY_TRAIN_DSN",
        "LANG",
        "LC_ALL",
        "TZ",
    }
    with pytest.raises(ValueError):
        environment(profile, "evaluate")
    profile.write_text(profile.read_text() + "OPENAI_API_KEY=must-never-inherit\n")
    with pytest.raises(ValueError):
        environment(profile, "train")
    profile.chmod(0o644)
    with pytest.raises(ValueError):
        environment(profile, "train")
    link = tmp_path / "linked.env"
    link.symlink_to(profile)
    with pytest.raises(ValueError):
        environment(link, "train")


def training_bundle():
    rows = []
    for purpose, target in (("fit", "0"), ("fit", "40"), ("development", "35")):
        rows.append(
            {
                "id": str(uuid4()),
                "project_id": str(uuid4()),
                "group_id": str(uuid4()),
                "purpose": purpose,
                "submitted_at": "2024-01-01T00:00:00Z",
                "label_known_at": "2024-02-01T00:00:00Z",
                "target": target,
            }
        )
    return {
        "schema": "package-history-training-export/1",
        "origin": "synthetic",
        "cohort_id": str(uuid4()),
        "protocol": cpu.protocol(bootstrap_iterations=100),
        "membership_digest": "a" * 64,
        "timing": {
            "submission_split_at": "2025-01-01T00:00:00Z",
            "label_available_as_of": "2025-02-01T00:00:00Z",
            "training_frozen_at": "2025-03-01T00:00:00Z",
        },
        "rows": rows,
    }


def test_actual_feature_free_cpu_baseline_preserves_zero_and_does_not_invent_intervals():
    bundle = training_bundle()
    result = cpu.train(bundle)
    assert result["model"]["family"] == "mean"
    assert result["model"]["constant"] == "20.0"
    assert result["training_export_digest"] == digest(bundle)
    assert result["model_digest"] == digest(result["model"])
    assert result["intervals"]["0.8"]["radius"] is None
    assert result["intervals"]["0.9"]["radius"] is None
    assert result["research_only"] and result["provider_requests"] == 0


def evaluation_bundle():
    training = training_bundle()
    result = cpu.train(training)
    labels = [
        {
            "id": str(uuid4()),
            "project_id": str(uuid4()),
            "group_id": str(uuid4()),
            "method": cpu.VERSION,
            "maximum": "20",
            "engineering_type": "synthetic",
            "status": "succeeded",
            "target": "0",
            "reason": None,
        },
        {
            "id": str(uuid4()),
            "project_id": str(uuid4()),
            "group_id": str(uuid4()),
            "method": cpu.VERSION,
            "maximum": "20",
            "engineering_type": "synthetic",
            "status": "unlabeled",
            "target": None,
            "reason": "label_after_available_cutoff",
        },
    ]
    predictions = {
        "schema": "package-history-frozen-final-predictions/1",
        "model_digest": result["model_digest"],
        "rows": [
            {
                "id": row["id"],
                "status": row["status"],
                "prediction": "20.0" if row["status"] == "succeeded" else None,
            }
            for row in labels
        ],
        "intervals": result["intervals"],
        "baseline_predictions": {
            "mean": {labels[0]["id"]: "20.0"},
            "median": {labels[0]["id"]: "20.0"},
        },
    }
    return {
        "schema": "package-history-final-evaluation-export/1",
        "origin": "synthetic",
        "cohort_id": training["cohort_id"],
        "protocol": training["protocol"],
        "timing": training["timing"],
        "labels": labels,
        "labels_digest": digest(labels),
        "predictions": predictions,
        "predictions_digest": digest(predictions),
        "model_digest": result["model_digest"],
        "membership_digest": training["membership_digest"],
        "denominator": {
            "selected_submissions": 5,
            "excluded_submissions": 1,
            "final_side_candidates": 2,
        },
    }


def test_decimal_string_evaluation_computes_actual_metrics_without_rewriting_seals_or_unknowns():
    bundle = evaluation_bundle()
    original = deepcopy(bundle)
    result = cpu.evaluate(bundle)
    assert bundle == original
    assert result["report"]["counts"] == {
        "succeeded": 1,
        "unlabeled": 1,
        "rejected": 0,
        "failed": 0,
    }
    assert result["report"]["project_mae"] == "20.0"
    assert result["report"]["original_scale_project_mae"] == "4.0"
    assert result["report"]["denominator"] == 2
    assert result["acceptance_decision"] == "unavailable"
    assert result["labels_digest"] == original["labels_digest"]


def test_evaluation_cannot_drop_unknown_candidates_or_relabel_them_as_success():
    bundle = evaluation_bundle()
    bundle["predictions"]["rows"].pop()
    bundle["predictions_digest"] = digest(bundle["predictions"])
    with pytest.raises(GovernanceError) as caught:
        cpu.evaluate(bundle)
    assert caught.value.code == "PACKAGE_HISTORY_CPU_DENOMINATOR_CHANGED"
    bundle = evaluation_bundle()
    bundle["predictions"]["rows"][1]["status"] = "succeeded"
    bundle["predictions_digest"] = digest(bundle["predictions"])
    with pytest.raises(GovernanceError) as caught:
        cpu.evaluate(bundle)
    assert caught.value.code == "PACKAGE_HISTORY_CPU_DENOMINATOR_CHANGED"


@pytest.mark.parametrize(
    "failure", ["final", "unknown", "group", "future", "method", "boolean", "duplicate"]
)
def test_cpu_refuses_label_leaks_unknowns_cross_groups_times_and_changed_method(failure):
    bundle = training_bundle()
    if failure == "final":
        bundle["rows"][0]["purpose"] = "final"
    elif failure == "unknown":
        bundle["rows"][0]["target"] = None
    elif failure == "group":
        bundle["rows"][-1]["group_id"] = bundle["rows"][0]["group_id"]
    elif failure == "future":
        bundle["rows"][0]["label_known_at"] = "2026-01-01T00:00:00Z"
    elif failure == "method":
        bundle["protocol"]["method"]["digest"] = "f" * 64
    elif failure == "boolean":
        bundle["protocol"]["seed"] = True
    else:
        bundle["rows"].append(deepcopy(bundle["rows"][0]))
    with pytest.raises(GovernanceError):
        cpu.train(bundle)
