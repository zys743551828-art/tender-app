"""Actual trusted-host target-program execution and native completion recovery."""
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
from test_package_current_original_set_pg import wire
from test_package_material_scope_findings import checked, draft_for
from test_verification_commands_pg import begin, configure
from test_verification_program_pg import (
    KEYS,
    api,
    database,
    exact,
    pdf_data,
    requirements,
    saved,
    world,
)

from deploy import fusion_verification_program as program
from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_verification_program as port
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_native_evidence_issuers as issuer
from packages.model_governance import package_native_evidence_registration as registration
from packages.model_governance import package_native_material_recovery as recovery
from packages.model_governance import package_native_material_store as store

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_VERIFICATION_PROGRAM_HOST") != "1",
    reason="explicit actual trusted-host program execution required",
)


def test_actual_program_identity_kernel_execution_native_result_and_unknown_recovery(
    wire, runtime, monkeypatch
):
    w, state, url = wire
    db = w["database"]
    receipts = []
    connections = [db["verification_program"], *(db[k] for k in KEYS)]

    def idle():
        assert all(c.info.transaction_status == TransactionStatus.IDLE for c in connections)

    def capture(name):
        operation = getattr(runtime, name)

        def wrapped(*args, **kwargs):
            idle()
            result = operation(*args, **kwargs)
            receipts.append(
                deepcopy(
                    result["execution_receipt"] if name == "describe" else result.execution_receipt
                )
            )
            return result

        monkeypatch.setattr(runtime, name, wrapped)

    capture("describe")
    capture("render")
    state["callback"] = idle
    frozen = freeze(wire, runtime)
    live = collect(wire, runtime, frozen)
    plan = review.build(
        live.context,
        expected_context_digest=frozen.metadata["digest"],
        expected_method_digest=review.method_digest(),
    )
    report = checked(plan, draft_for(plan))
    prepared = store.prepare(
        live,
        report,
        expected_context_digest=frozen.metadata["digest"],
        expected_findings_digest=report.metadata["digest"],
        expected_derivation_digest=live.metadata["digest"],
        expected_producer_method_digest=live.metadata["method_digest"],
        expected_method_digest=store.method_digest(),
    )
    store_command = str(uuid4())
    stored = store.put(
        db["material_writer"],
        prepared,
        command_id=store_command,
        expected_packet_digest=digest(prepared.packet),
        expected_method_digest=store.method_digest(),
    )
    restored = asyncio.run(
        recovery.restore(
            db["material_reader"],
            db["scope_verifier"],
            db["original_verifier"],
            db["parse_verifier"],
            store_command_id=store_command,
            expected_packet_digest=digest(prepared.packet),
            expected_storage_record_digest=stored.metadata["digest"],
            expected_context_digest=frozen.metadata["digest"],
            expected_method_digest=recovery.method_digest(),
            bid_id=frozen.metadata["bid_id"],
            scope_id=frozen.metadata["scope_id"],
            expected_scope_digest=frozen.metadata["scope_digest"],
            profile="development_s3",
            url_for_locator=url,
        )
    )
    pending = registration.record(
        db["native_registrar"],
        restored,
        command_id=str(uuid4()),
        expected_context_digest=frozen.metadata["digest"],
        expected_storage_record_digest=stored.metadata["digest"],
        expected_recovery_observation_digest=restored.metadata["digest"],
        expected_method_digest=registration.method_digest(),
    )
    _, case_id = assign(
        w,
        pending,
        report.metadata["review_digest"],
        profile_changes={"login_name": SIGNER, "store": store.method_digest()},
    )
    signed = issuer.attest(
        db["native_issuer"],
        pending,
        restored,
        case_id=case_id,
        command_id=str(uuid4()),
        expected_registration_digest=pending.metadata["digest"],
        expected_findings_digest=report.metadata["digest"],
        expected_method_digest=issuer.method_digest(),
    )
    program_case = configure(w, pending, signed, profile_changes={"policy": port.policy_digest()})
    logical = str(uuid4())
    ticket = begin(w, program_case, logical)
    assert state["attempts"] == state["idle_checks"] == 6 and len(receipts) == 7
    args = {"command_id": logical, "expected_command_digest": ticket.metadata["digest"]}

    def execute():
        return asyncio.run(
            program.execute(
                *connections,
                runtime=runtime,
                **args,
                expected_method_digest=program.method_digest(),
                profile="development_s3",
                url_for_locator=url,
            )
        )

    first = execute()
    assert not first.metadata["resumed_completed_native_result"]
    assert state["attempts"] == state["idle_checks"] == 12 and len(receipts) == 10
    with db["verification_program_factory"]() as reopened:
        found = port.context(reopened, **args, expected_method_digest=port.method_digest())
    assert found.prior_result.metadata == first.result.metadata
    again = execute()
    assert (
        again.metadata["resumed_completed_native_result"]
        and again.result.metadata == first.result.metadata
    )
    assert state["attempts"] == state["idle_checks"] == 12 and len(receipts) == 10
    assert len({r["container_id"] for r in receipts}) == 10 and all(
        r["stopped_verified"] and r["container_pid"] == 0 for r in receipts
    )
    result = first.result.metadata
    assert result["document"]["program_runtime_authenticated"]
    assert not any(result["document"][k] for k in port.FALSE_FIELDS)
    assert result["document"]["context_digest"] == frozen.metadata["digest"]
    assert result["document"]["findings_digest"] == report.metadata["digest"]
    assert canonical(
        result["observation"]["verified_material"]["live_derivation"]["context_digest"]
    ) == canonical(frozen.metadata["digest"])
    directory = Path(os.environ["FUSION_MATERIAL_DERIVATION_EVIDENCE"])
    (directory / "host-verification-program-proof.json").write_text(
        json.dumps(
            {
                "port_method_digest": port.method_digest(),
                "program_method_digest": program.method_digest(),
                "record": result,
                "execution": first.metadata,
                "recovered_execution": again.metadata,
                "actual_loopback_gets_total": 12,
                "prior_gets_before_program": 6,
                "program_gets": 6,
                "actual_fresh_compose_sessions": 10,
                "prior_sessions_before_program": 7,
                "program_sessions": 3,
                "kernel_receipts": receipts,
                "independent_connections_idle_during_http_and_kernel_execution": 7,
                "physical_pages": 4,
                "frozen_details": 1,
                "actual_renderer_used": True,
                "synthetic_renderer_stub": False,
                "actual_target_program_login_oid_and_native_completion_bound": True,
                "durable_command_precedes_actual_program_io": True,
                "unknown_result_reopen_and_resume_without_io": True,
                "exact_frozen_context_and_full_report_bound": True,
                "synthetic_material_and_configuration": True,
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
