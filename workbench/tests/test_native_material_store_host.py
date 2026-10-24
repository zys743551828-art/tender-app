"""Actual host rendering and independent native private storage, no local CAS."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus
from test_fusion_context_derivation_native import collect, freeze, runtime
from test_native_evidence_issuers_pg import SIGNER, assign, database
from test_package_current_material_pg import api, exact, pdf_data, requirements, saved, world
from test_package_current_original_set_pg import wire
from test_package_material_scope_findings import checked, draft_for

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_native_current_review as joint
from packages.model_governance import package_native_evidence_issuers as issuer
from packages.model_governance import package_native_evidence_registration as registration
from packages.model_governance import package_native_material_recovery as native_recovery
from packages.model_governance import package_native_material_store as store

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_NATIVE_MATERIAL_STORE_HOST") != "1",
    reason="explicit trusted host native private store integration required",
)


def test_actual_context_derivation_full_report_and_png_reopen_in_native_private_store(
    wire, runtime
):
    w, state, url = wire
    frozen = freeze(wire, runtime)
    live = collect(wire, runtime, frozen)
    plan = review.build(
        live.context,
        expected_context_digest=frozen.metadata["digest"],
        expected_method_digest=review.method_digest(),
    )
    report = checked(plan, draft_for(plan))
    p = store.prepare(
        live,
        report,
        expected_context_digest=frozen.metadata["digest"],
        expected_findings_digest=report.metadata["digest"],
        expected_derivation_digest=live.metadata["digest"],
        expected_producer_method_digest=live.metadata["method_digest"],
        expected_method_digest=store.method_digest(),
    )
    command = str(uuid4())
    packet_digest = digest(p.packet)
    record = store.put(
        w["database"]["material_writer"],
        p,
        command_id=command,
        expected_packet_digest=packet_digest,
        expected_method_digest=store.method_digest(),
    )
    args = {
        "bid_id": frozen.metadata["bid_id"],
        "command_id": command,
        "expected_packet_digest": packet_digest,
        "expected_record_digest": record.metadata["digest"],
        "expected_method_digest": store.method_digest(),
    }
    with w["database"]["material_reader_factory"]() as reopened:
        loaded = store.load(reopened, **args)
    assert canonical(loaded.context_metadata) == canonical(frozen.metadata)
    assert canonical(loaded.derivation_observation) == canonical(live.metadata)
    assert canonical(loaded.findings_metadata) == canonical(report.metadata)
    assert loaded.image_blobs == {
        key: raw
        for bundle in live.context.origin.page_bundles.values()
        for key, raw in bundle.blobs.items()
    }
    assert state["attempts"] == state["idle_checks"] == 4
    assert not any(record.metadata["document"][k] for k in store.FLAGS)
    directory = Path(os.environ["FUSION_NATIVE_MATERIAL_STORE_HOST_EVIDENCE"])
    (directory / "host-native-material-store-proof.json").write_text(
        json.dumps(
            {
                "store_method_digest": store.method_digest(),
                "producer_method_digest": live.metadata["method_digest"],
                "record": record.metadata,
                "object_count": len(p.objects),
                "asset_count": len(p.packet["image_objects"]),
                "actual_loopback_gets": 4,
                "actual_fresh_compose_sessions": 7,
                "physical_pages": 4,
                "frozen_details": 1,
                "actual_renderer_used": True,
                "exact_context_derivation_report_and_png_bytes_recovered_after_reopen": True,
                "private_native_byte_store_verified": True,
                "windows_private_acl_backend_installed": False,
                "synthetic_material": True,
                "synthetic_review_claims": True,
                "actual_human_review": False,
                "input_authority_granted": False,
                "provider_attempts": 0,
                "body_exported": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if os.environ.get("FUSION_NATIVE_MATERIAL_RECOVERY_HOST") == "1":
        restored = asyncio.run(
            native_recovery.restore(
                w["database"]["material_reader"],
                *(
                    w["database"][k]
                    for k in ("scope_verifier", "original_verifier", "parse_verifier")
                ),
                store_command_id=command,
                expected_packet_digest=packet_digest,
                expected_storage_record_digest=record.metadata["digest"],
                expected_context_digest=frozen.metadata["digest"],
                expected_method_digest=native_recovery.method_digest(),
                bid_id=frozen.metadata["bid_id"],
                scope_id=frozen.metadata["scope_id"],
                expected_scope_digest=frozen.metadata["scope_digest"],
                profile="development_s3",
                url_for_locator=url,
            )
        )
        assert canonical(restored.context.metadata) == canonical(frozen.metadata)
        assert canonical(restored.findings.metadata) == canonical(report.metadata)
        assert state["attempts"] == state["idle_checks"] == 6
        assert restored.metadata["trusted_derivation_freshly_verified"] is False
        assert restored.metadata["input_authority_granted"] is False
        (directory / "host-native-material-recovery-proof.json").write_text(
            json.dumps(
                {
                    "recovery_method_digest": native_recovery.method_digest(),
                    "observation": restored.metadata,
                    "actual_loopback_gets_total": 6,
                    "recovery_loopback_gets": 2,
                    "actual_prior_fresh_compose_sessions": 7,
                    "physical_pages": 4,
                    "frozen_details": 1,
                    "prior_actual_derivation_and_store_verified": True,
                    "exact_context_and_report_preserved_after_fresh_original_gets": True,
                    "renderer_replayed_during_recovery": False,
                    "live_derivation_certificate_constructed": False,
                    "actual_human_review": False,
                    "synthetic_material": True,
                    "input_authority_granted": False,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if os.environ.get("FUSION_NATIVE_EVIDENCE_REGISTRATION_HOST") == "1":
            registration_command = str(uuid4())
            registered = registration.record(
                w["database"]["native_registrar"],
                restored,
                command_id=registration_command,
                expected_context_digest=frozen.metadata["digest"],
                expected_storage_record_digest=record.metadata["digest"],
                expected_recovery_observation_digest=restored.metadata["digest"],
                expected_method_digest=registration.method_digest(),
            )
            with w["database"]["native_registrar_factory"]() as independent:
                found = registration.read(
                    independent,
                    bid_id=frozen.metadata["bid_id"],
                    command_id=registration_command,
                    expected_packet_digest=digest(registered.metadata["document"]["packet"]),
                    expected_method_digest=registration.method_digest(),
                )
            assert found.metadata == registered.metadata
            document = found.metadata["document"]
            assert document["version"] == "package-native-material-registration/2"
            assert not any(document[k] for k in registration.FALSE_FIELDS)
            assert not any("commit" in k for k in document["packet"])
            assert canonical(restored.context.metadata) == canonical(frozen.metadata)
            assert state["attempts"] == state["idle_checks"] == 6
            (directory / "host-native-evidence-registration-proof.json").write_text(
                json.dumps(
                    {
                        "registration_method_digest": registration.method_digest(),
                        "record": registered.metadata,
                        "actual_loopback_gets_total": 6,
                        "actual_prior_fresh_compose_sessions": 7,
                        "physical_pages": 4,
                        "frozen_details": 1,
                        "actual_derivation_store_and_current_recovery_before_registration": True,
                        "unknown_result_lookup_after_independent_reopen": True,
                        "old_cas_commit_fields_fabricated": False,
                        "exact_context_bytes_preserved": True,
                        "synthetic_material_and_review_claims": True,
                        "actual_human_review": False,
                        "input_authority_granted": False,
                        "provider_attempts": 0,
                        "body_exported": False,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            if os.environ.get("FUSION_NATIVE_EVIDENCE_ISSUERS_HOST") == "1":
                _, case_id = assign(
                    w,
                    registered,
                    restored.findings.metadata["review_digest"],
                    profile_changes={"login_name": SIGNER, "store": store.method_digest()},
                )
                issuer_command = str(uuid4())
                attested = issuer.attest(
                    w["database"]["native_issuer"],
                    registered,
                    restored,
                    case_id=case_id,
                    command_id=issuer_command,
                    expected_registration_digest=registered.metadata["digest"],
                    expected_findings_digest=restored.findings.metadata["digest"],
                    expected_method_digest=issuer.method_digest(),
                )
                with w["database"]["native_issuer_reader_factory"]() as verifier:
                    observed = issuer.read(
                        verifier,
                        bid_id=frozen.metadata["bid_id"],
                        command_id=issuer_command,
                        expected_reference_digest=digest(
                            attested.metadata["document"]["reference"]
                        ),
                        expected_method_digest=issuer.method_digest(),
                    )
                assert observed.metadata["record"]["digest"] == attested.metadata["digest"]
                assert observed.metadata["current"]["issuer_active"]
                assert observed.metadata["current"]["case_active"]
                assert observed.metadata["current"]["input_authority_granted"] is False
                assert canonical(restored.context.metadata) == canonical(frozen.metadata)
                assert state["attempts"] == state["idle_checks"] == 6
                (directory / "host-native-evidence-issuers-proof.json").write_text(
                    json.dumps(
                        {
                            "issuer_method_digest": issuer.method_digest(),
                            "record": attested.metadata,
                            "observation": observed.metadata,
                            "actual_loopback_gets_total": 6,
                            "actual_prior_fresh_compose_sessions": 7,
                            "physical_pages": 4,
                            "frozen_details": 1,
                            "actual_derivation_store_recovery_registration_before_attestation": True,
                            "independent_issuer_and_reader_logins": True,
                            "unknown_result_lookup_after_reader_reopen": True,
                            "synthetic_material_and_issuer_configuration": True,
                            "exact_context_bytes_preserved": True,
                            "old_cas_commit_fields_fabricated": False,
                            "actual_human_review": False,
                            "input_authority_granted": False,
                            "provider_attempts": 0,
                            "body_exported": False,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                if os.environ.get("FUSION_NATIVE_CURRENT_REVIEW_HOST") == "1":
                    connections = [
                        w["database"][key]
                        for key in (
                            "native_registrar",
                            "material_reader",
                            "scope_verifier",
                            "original_verifier",
                            "parse_verifier",
                            "native_issuer_reader",
                        )
                    ]

                    def idle():
                        assert all(
                            c.info.transaction_status == TransactionStatus.IDLE for c in connections
                        )

                    state["callback"] = idle
                    try:
                        combined = asyncio.run(
                            joint.observe(
                                *connections,
                                registration_command_id=registration_command,
                                expected_registration_packet_digest=document["packet_digest"],
                                expected_registration_digest=registered.metadata["digest"],
                                issuer_command_id=issuer_command,
                                expected_issuer_reference_digest=digest(
                                    attested.metadata["document"]["reference"]
                                ),
                                expected_issuer_digest=attested.metadata["digest"],
                                expected_context_digest=frozen.metadata["digest"],
                                expected_method_digest=joint.method_digest(),
                                bid_id=frozen.metadata["bid_id"],
                                scope_id=frozen.metadata["scope_id"],
                                expected_scope_digest=frozen.metadata["scope_digest"],
                                profile="development_s3",
                                url_for_locator=url,
                            )
                        )
                    finally:
                        state["callback"] = None
                    assert canonical(combined.context.metadata) == canonical(frozen.metadata)
                    assert canonical(combined.findings.metadata) == canonical(report.metadata)
                    assert combined.metadata["status"] == "synthetic_review_only"
                    assert state["attempts"] == state["idle_checks"] == 8
                    assert combined.metadata["input_authority_granted"] is False
                    (directory / "host-native-current-review-proof.json").write_text(
                        json.dumps(
                            {
                                "joint_method_digest": joint.method_digest(),
                                "observation": combined.metadata,
                                "actual_loopback_gets_total": 8,
                                "joint_recovery_loopback_gets": 2,
                                "actual_prior_fresh_compose_sessions": 7,
                                "physical_pages": 4,
                                "frozen_details": 1,
                                "independent_connections_idle_during_http": 6,
                                "actual_derivation_store_registration_issuer_and_current_joint_review": True,
                                "exact_context_report_and_registration_preserved": True,
                                "synthetic_material_and_issuer_configuration": True,
                                "actual_human_review": False,
                                "input_authority_granted": False,
                                "provider_attempts": 0,
                                "body_exported": False,
                            },
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
