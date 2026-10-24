"""Actual host rendering and independent native private storage, no local CAS."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus
from test_fusion_context_derivation_native import collect, freeze, runtime
from test_native_evidence_issuers_pg import SIGNER, assign
from test_package_current_material_pg import api, exact, pdf_data, requirements, saved, world
from test_package_current_original_set_pg import wire
from test_package_material_scope_findings import checked, draft_for
from test_verification_commands_pg import configure, database

from deploy import fusion_verified_material as verified
from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_verification_commands as commands
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
    wire, runtime, monkeypatch
):
    w, state, url = wire
    kernel_receipts = []
    if os.environ.get("FUSION_VERIFIED_MATERIAL_HOST") == "1":

        def capture(name):
            operation = getattr(runtime, name)

            def wrapped(*args, **kwargs):
                assert all(
                    w["database"][key].info.transaction_status == TransactionStatus.IDLE
                    for key in (
                        "native_registrar",
                        "material_reader",
                        "scope_verifier",
                        "original_verifier",
                        "parse_verifier",
                        "native_issuer_reader",
                    )
                )
                value = operation(*args, **kwargs)
                receipt = (
                    value["execution_receipt"] if name == "describe" else value.execution_receipt
                )
                kernel_receipts.append(deepcopy(receipt))
                return value

            monkeypatch.setattr(runtime, name, wrapped)

        capture("describe")
        capture("render")
    frozen = freeze(wire, runtime)
    live = collect(wire, runtime, frozen)
    if os.environ.get("FUSION_VERIFIED_MATERIAL_HOST") == "1":
        assert len(kernel_receipts) == 7
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
                    if os.environ.get("FUSION_VERIFIED_MATERIAL_HOST") == "1":
                        review_arguments = {
                            "registration_command_id": registration_command,
                            "expected_registration_packet_digest": document["packet_digest"],
                            "expected_registration_digest": registered.metadata["digest"],
                            "issuer_command_id": issuer_command,
                            "expected_issuer_reference_digest": digest(
                                attested.metadata["document"]["reference"]
                            ),
                            "expected_issuer_digest": attested.metadata["digest"],
                            "expected_context_digest": frozen.metadata["digest"],
                            "bid_id": frozen.metadata["bid_id"],
                            "scope_id": frozen.metadata["scope_id"],
                            "expected_scope_digest": frozen.metadata["scope_digest"],
                            "profile": "development_s3",
                            "url_for_locator": url,
                        }
                        if os.environ.get("FUSION_VERIFICATION_COMMANDS_HOST") == "1":
                            program_case = configure(w, registered, attested)
                            logical_command = str(uuid4())
                            staged = commands.begin(
                                w["database"]["verification_requester"],
                                case_id=program_case[1],
                                command_id=logical_command,
                                expected_case_digest=program_case[2],
                                expected_method_digest=commands.method_digest(),
                            )
                            assert state["attempts"] == 8 and len(kernel_receipts) == 7
                            assert (
                                w["database"]["verification_requester"].info.transaction_status
                                == TransactionStatus.IDLE
                            )

                        def execute():
                            return asyncio.run(
                                verified.collect(
                                    *connections,
                                    runtime=runtime,
                                    review_arguments=review_arguments,
                                    expected_method_digest=verified.method_digest(),
                                )
                            )

                        state["callback"] = idle
                        try:
                            capsule = execute()
                            assert state["attempts"] == state["idle_checks"] == 14
                            assert len(kernel_receipts) == 10
                            assert canonical(capsule.context.metadata) == canonical(frozen.metadata)
                            assert canonical(capsule.findings.metadata) == canonical(
                                report.metadata
                            )
                            assert capsule.metadata["trusted_derivation_bound"]
                            assert capsule.metadata["input_authority_granted"] is False

                            def reenabling():
                                idle()
                                if state["attempts"] == 18:
                                    owner = w["database"]["owner"]
                                    owner.execute(
                                        "UPDATE scope_review_issuer.profile_heads SET enabled=false,revision=revision+1 WHERE login_name=%s",
                                        (SIGNER,),
                                    )
                                    owner.execute(
                                        "UPDATE scope_review_issuer.profile_heads SET enabled=true,revision=revision+1 WHERE login_name=%s",
                                        (SIGNER,),
                                    )

                            state["callback"] = reenabling
                            with pytest.raises(
                                verified.VerifiedMaterialError,
                                match="ISSUER_STATE_CHANGED_ACROSS_DERIVATION",
                            ):
                                execute()
                        finally:
                            state["callback"] = None
                        assert state["attempts"] == state["idle_checks"] == 20
                        assert len(kernel_receipts) == 13
                        assert len({r["container_id"] for r in kernel_receipts}) == 13
                        assert all(
                            r["stopped_verified"] and r["container_pid"] == 0
                            for r in kernel_receipts
                        )
                        (directory / "host-verified-material-proof.json").write_text(
                            json.dumps(
                                {
                                    "controller_method_digest": verified.method_digest(),
                                    "positive_live_observation": capsule.metadata,
                                    "actual_loopback_gets_total": 20,
                                    "positive_stage_gets_total": 14,
                                    "positive_controller_gets": 6,
                                    "negative_controller_gets": 6,
                                    "actual_fresh_compose_sessions": 13,
                                    "positive_stage_compose_sessions": 10,
                                    "controller_compose_sessions_each": 3,
                                    "kernel_receipts": kernel_receipts,
                                    "physical_pages": 4,
                                    "frozen_details": 1,
                                    "independent_connections_idle_during_http_and_kernel_execution": 6,
                                    "reenabled_issuer_between_two_joint_checks_rejected": True,
                                    "positive_observation_precedes_injected_head_revision": True,
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
                        if os.environ.get("FUSION_VERIFICATION_COMMANDS_HOST") == "1":
                            with w["database"]["verification_requester_factory"]() as reopened:
                                recovered_command = commands.read(
                                    reopened,
                                    case_id=program_case[1],
                                    command_id=logical_command,
                                    expected_case_digest=program_case[2],
                                    expected_method_digest=commands.method_digest(),
                                )
                            assert recovered_command.metadata["record"] == {
                                k: staged.metadata[k] for k in ("document", "digest")
                            }
                            assert (
                                recovered_command.metadata["current"][
                                    "program_runtime_authenticated"
                                ]
                                is False
                            )
                            assert (
                                recovered_command.metadata["current"]["input_authority_granted"]
                                is False
                            )
                            (directory / "host-verification-commands-proof.json").write_text(
                                json.dumps(
                                    {
                                        "command_method_digest": commands.method_digest(),
                                        "record": staged.metadata,
                                        "observation_after_host_checks": recovered_command.metadata,
                                        "prior_gets_at_command_commit": 8,
                                        "prior_sessions_at_command_commit": 7,
                                        "subsequent_actual_gets": 12,
                                        "subsequent_actual_sessions": 6,
                                        "actual_loopback_gets_total": 20,
                                        "actual_fresh_compose_sessions": 13,
                                        "logical_command_durable_before_next_actual_verification": True,
                                        "unknown_result_reopened_without_repeating_io": True,
                                        "operator_host_checks_do_not_authenticate_declared_program": True,
                                        "target_program_execution_not_recorded": True,
                                        "synthetic_material_and_configuration": True,
                                        "input_authority_granted": False,
                                        "provider_attempts": 0,
                                        "body_exported": False,
                                    },
                                    indent=2,
                                )
                                + "\n",
                                encoding="utf-8",
                            )
