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
from test_cost_quotes_pg import publish as publish_prices
from test_cost_quotes_pg import quote
from test_cost_quotes_pg import reread as read_quote
from test_fusion_context_derivation_native import collect, freeze, runtime
from test_input_authority_pg import approve, qualify, reread
from test_input_renewals_pg import publish as publish_renewal
from test_input_renewals_pg import record, wire_digests
from test_input_renewals_pg import reread as read_renewal
from test_input_seals_pg import publish, seal
from test_input_seals_pg import reread as read_seal
from test_judgment_jobs_pg import database
from test_judgment_jobs_pg import publish as publish_job
from test_judgment_jobs_pg import refresh_args as job_refresh_args
from test_judgment_jobs_pg import reread as read_job
from test_judgment_jobs_pg import start as start_job
from test_native_evidence_issuers_pg import SIGNER, assign
from test_package_current_original_set_pg import wire
from test_package_material_scope_findings import checked, draft_for
from test_verification_commands_pg import begin, configure
from test_verification_program_pg import (
    KEYS,
    api,
    exact,
    pdf_data,
    requirements,
    saved,
    world,
)

from deploy import fusion_verification_program as program
from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_judgment_jobs as jobs
from packages.model_governance import material_verification_program as port
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_native_evidence_issuers as issuer
from packages.model_governance import package_native_evidence_registration as registration
from packages.model_governance import package_native_material_recovery as recovery
from packages.model_governance import package_native_material_store as store
from packages.model_governance import package_technical_material as material

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_VERIFICATION_PROGRAM_HOST") != "1"
    or os.environ.get("FUSION_INPUT_SEALS_HOST") != "1"
    or os.environ.get("FUSION_COST_QUOTES_HOST") != "1"
    or os.environ.get("FUSION_INPUT_RENEWALS_HOST") != "1"
    or os.environ.get("FUSION_JUDGMENT_JOBS_HOST") != "1",
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
    authority_args = approve(
        w,
        first.result,
        image=runtime.expected_image_id,
        source=runtime.expected_source_digest,
        changes={"max_program_age_seconds": 5},
    )
    verified = qualify(w, authority_args)
    current = reread(w, verified)
    assert current.record == verified and current.metadata["current"]["software_input_current"]
    assert not current.metadata["current"]["current_input_verified"]
    bound = material.bind_input(
        frozen,
        verified.binding,
        expected_context_digest=frozen.metadata["digest"],
        expected_binding_digest=digest(verified.binding),
        expected_method_digest=material.method_digest(),
    )
    assert bound.metadata["native_binding_verified"] is False
    assert bound.metadata["input_authority_granted"] is False
    seal_args = publish(w, verified)
    sealed = seal(w, seal_args)
    reopened_seal = read_seal(w, sealed)
    assert reopened_seal.record == sealed
    assert reopened_seal.metadata["current"]["software_input_current"]
    assert not reopened_seal.metadata["current"]["current_input_verified"]
    seal_document = sealed.metadata["document"]
    assert seal_document["material_input"] == bound.metadata
    assert seal_document["storage_record_id"] == stored.metadata["document"]["record_id"]
    assert seal_document["storage_record_digest"] == stored.metadata["digest"]
    assert seal_document["context_object_digest"] == prepared.packet["context_object"]["sha256"]
    price_args, price_data = publish_prices(w, sealed)
    quoted = quote(w, price_args)
    current_quote = read_quote(w, quoted)
    assert current_quote.record == quoted
    assert current_quote.metadata["current"]["software_budget_sufficient"]
    price_policy = cost.bind_policy(price_data, expected_policy_digest=digest(price_data))
    expected_quote = cost.quote(
        frozen,
        price_policy,
        expected_context_digest=frozen.metadata["digest"],
        expected_policy_digest=price_policy.metadata["digest"],
        expected_method_digest=cost.method_digest(),
        as_of=quoted.metadata["document"]["recorded_at"],
        max_attempts_per_slot=5,
        budget_currency="USD",
        budget_ceiling_minor=price_args["budget_ceiling_minor"],
    )
    assert quoted.metadata["document"]["quote"] == expected_quote.metadata
    assert state["attempts"] == 12 and len(receipts) == 10
    directory = Path(os.environ["FUSION_MATERIAL_DERIVATION_EVIDENCE"])
    (directory / "host-cost-quotes-proof.json").write_text(
        json.dumps(
            {
                "quote": quoted.metadata,
                "current": current_quote.metadata,
                "independent_quoter_login_and_oid": True,
                "exact_pure_quote_metadata_matches": True,
                "complete_included_rules_from_native_context": True,
                "actual_renderer_used": True,
                "synthetic_renderer_stub": False,
                "actual_loopback_gets_total": 12,
                "actual_fresh_compose_sessions": 10,
                "quote_additional_gets": 0,
                "quote_additional_sessions": 0,
                "synthetic_material_and_configuration": True,
                "actual_human_review": False,
                "account_price_confirmed": False,
                "fee_ledger_reserved": False,
                "input_authority_granted": False,
                "execution_authorized": False,
                "provider_attempts": 0,
                "body_exported": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "host-input-seals-proof.json").write_text(
        json.dumps(
            {
                "seal": sealed.metadata,
                "current": reopened_seal.metadata,
                "exact_old_input_metadata_matches": True,
                "complete_native_object_set_rehashed": True,
                "independent_sealer_login_and_oid": True,
                "actual_renderer_used": True,
                "synthetic_renderer_stub": False,
                "actual_loopback_gets_total": 12,
                "actual_fresh_compose_sessions": 10,
                "sealing_additional_gets": 0,
                "sealing_additional_sessions": 0,
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
    (directory / "host-input-authority-proof.json").write_text(
        json.dumps(
            {
                "verification": verified.metadata,
                "current": current.metadata,
                "binding": verified.binding,
                "material_input": bound.metadata,
                "actual_renderer_used": True,
                "synthetic_renderer_stub": False,
                "actual_loopback_gets_total": 12,
                "actual_fresh_compose_sessions": 10,
                "qualification_additional_gets": 0,
                "qualification_additional_sessions": 0,
                "independent_verifier_login_and_oid": True,
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
    # Earlier proofs are milestones before renewal, not totals for this longer case.
    profile_id, profile_digest = publish_renewal(w, quoted)
    old_input, old_wire = wire_digests(frozen, verified.binding)
    assert old_input == bound.metadata["digest"]
    new_logical = str(uuid4())
    new_ticket = begin(w, program_case, new_logical)
    assert state["attempts"] == 12 and len(receipts) == 10
    renewed_program = asyncio.run(
        program.execute(
            *connections,
            runtime=runtime,
            command_id=new_logical,
            expected_command_digest=new_ticket.metadata["digest"],
            expected_method_digest=program.method_digest(),
            profile="development_s3",
            url_for_locator=url,
        )
    )
    expired_seal = read_seal(w, sealed)
    expired_quote = read_quote(w, quoted)
    assert not expired_seal.metadata["current"]["software_input_current"]
    assert not expired_quote.metadata["current"]["software_quote_current"]
    fresh = qualify(
        w,
        authority_args
        | {
            "program_result_id": renewed_program.result.metadata["document"]["result_id"],
            "expected_program_result_digest": renewed_program.result.metadata["digest"],
            "command_id": new_logical,
        },
    )
    renewal_args = {
        "seal_id": seal_document["seal_id"],
        "expected_seal_digest": sealed.metadata["digest"],
        "quote_id": quoted.metadata["document"]["quote_id"],
        "expected_quote_digest": quoted.metadata["digest"],
        "verification_id": fresh.metadata["document"]["verification_id"],
        "expected_verification_digest": fresh.metadata["digest"],
        "profile_id": profile_id,
        "expected_profile_digest": profile_digest,
        "command_id": new_logical,
    }
    from packages.model_governance import material_input_renewals as renewals

    renewal_args["expected_method_digest"] = renewals.method_digest()
    renewed = record(w, renewal_args)
    reopened_renewal = read_renewal(w, renewed)
    assert reopened_renewal.record == renewed
    assert reopened_renewal.metadata["current"]["software_evidence_current"]
    assert reopened_renewal.metadata["current"]["software_budget_sufficient"]
    assert record(w, renewal_args) == renewed
    assert wire_digests(frozen, verified.binding) == (old_input, old_wire)
    assert wire_digests(frozen, fresh.binding) != (old_input, old_wire)
    assert renewed.metadata["document"]["quote_digest"] == quoted.metadata["digest"]
    assert state["attempts"] == state["idle_checks"] == 18 and len(receipts) == 13
    assert len({r["container_id"] for r in receipts}) == 13
    assert all(r["stopped_verified"] and r["container_pid"] == 0 for r in receipts)
    (directory / "host-input-renewals-proof.json").write_text(
        json.dumps(
            {
                "renewal": renewed.metadata,
                "current": reopened_renewal.metadata,
                "original_verification": verified.metadata,
                "fresh_verification": fresh.metadata,
                "original_seal_expired": expired_seal.metadata,
                "original_quote_input_expired": expired_quote.metadata,
                "wire_digests": old_wire,
                "prior_milestone_gets": 12,
                "prior_milestone_sessions": 10,
                "renewal_program_gets": 6,
                "renewal_program_sessions": 3,
                "actual_loopback_gets_total": 18,
                "actual_fresh_compose_sessions": 13,
                "kernel_receipts": receipts,
                "independent_connections_idle_during_http_and_kernel_execution": 7,
                "native_program_command_precedes_new_io": True,
                "exact_input_and_quote_preserved": True,
                "naive_rebinding_changes_input_and_wire": True,
                "actual_renderer_used": True,
                "synthetic_renderer_stub": False,
                "synthetic_material_and_configuration": True,
                "actual_human_review": False,
                "fee_ledger_reserved": False,
                "execution_authorized": False,
                "model_calls_created": 0,
                "provider_attempts": 0,
                "body_exported": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    job_profile, job_profile_digest = publish_job(w, renewed)
    job_args = {
        "renewal_id": renewed.metadata["document"]["renewal_id"],
        "expected_renewal_digest": renewed.metadata["digest"],
        "profile_id": job_profile,
        "expected_profile_digest": job_profile_digest,
        "command_id": str(uuid4()),
        "expected_method_digest": jobs.method_digest(),
    }
    job = start_job(w, job_args)
    initial_job = read_job(w, job)
    assert initial_job.metadata["current"]["software_preparation_current"]
    assert job.metadata["document"]["material_input_digest"] == old_input
    assert job.metadata["document"]["quote_digest"] == quoted.metadata["digest"]
    next_logical = str(uuid4())
    next_ticket = begin(w, program_case, next_logical)
    next_program = asyncio.run(
        program.execute(
            *connections,
            runtime=runtime,
            command_id=next_logical,
            expected_command_digest=next_ticket.metadata["digest"],
            expected_method_digest=program.method_digest(),
            profile="development_s3",
            url_for_locator=url,
        )
    )
    expired_job = read_job(w, job)
    assert not expired_job.metadata["current"]["software_preparation_current"]
    assert start_job(w, job_args) == job
    next_verified = qualify(
        w,
        authority_args
        | {
            "program_result_id": next_program.result.metadata["document"]["result_id"],
            "expected_program_result_digest": next_program.result.metadata["digest"],
            "command_id": next_logical,
        },
    )
    next_renewal = record(
        w,
        renewal_args
        | {
            "verification_id": next_verified.metadata["document"]["verification_id"],
            "expected_verification_digest": next_verified.metadata["digest"],
            "command_id": next_logical,
        },
    )
    update_args = job_refresh_args(job, next_renewal)
    updated_evidence = jobs.refresh(db["job_submitter"], **update_args)
    final_job = read_job(w, job)
    assert final_job.record == job and final_job.evidence == updated_evidence
    assert final_job.metadata["current"]["software_preparation_current"]
    assert final_job.metadata["current"]["evidence_revision"] == 2
    assert jobs.refresh(db["job_submitter"], **update_args) == updated_evidence
    with pytest.raises(jobs.JudgmentJobError, match="INTENT_ALREADY_REGISTERED"):
        start_job(
            w,
            job_args
            | {
                "renewal_id": next_renewal.metadata["document"]["renewal_id"],
                "expected_renewal_digest": next_renewal.metadata["digest"],
                "command_id": str(uuid4()),
            },
        )
    assert wire_digests(frozen, verified.binding) == (old_input, old_wire)
    assert state["attempts"] == state["idle_checks"] == 24 and len(receipts) == 16
    assert len({r["container_id"] for r in receipts}) == 16
    assert all(r["stopped_verified"] and r["container_pid"] == 0 for r in receipts)
    (directory / "host-judgment-jobs-proof.json").write_text(
        json.dumps(
            {
                "job": job.metadata,
                "initial": initial_job.metadata,
                "expired": expired_job.metadata,
                "refreshed": final_job.metadata,
                "wire_digests": old_wire,
                "original_intent_unique": True,
                "complete_rules_and_three_native_slots": True,
                "evidence_refresh_preserves_job_input_quote_and_slots": True,
                "durable_program_commands_precede_new_io": True,
                "actual_loopback_gets_total": 24,
                "actual_fresh_compose_sessions": 16,
                "prior_milestone_gets": 18,
                "prior_milestone_sessions": 13,
                "job_evidence_program_gets": 6,
                "job_evidence_program_sessions": 3,
                "kernel_receipts": receipts,
                "independent_connections_idle_during_http_and_kernel_execution": 7,
                "actual_renderer_used": True,
                "synthetic_renderer_stub": False,
                "synthetic_material_and_configuration": True,
                "actual_human_review": False,
                "fee_ledger_reserved": False,
                "execution_authorized": False,
                "model_calls_created": 0,
                "provider_attempts": 0,
                "outbox_delivered": False,
                "body_exported": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
