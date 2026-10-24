"""Exact private evidence, independent native issuer and fresh original reads."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from test_package_current_material_pg import api, exact, pdf_data, requirements, saved, world
from test_package_current_original_set_pg import wire
from test_package_material_recovery_pg import restore
from test_package_material_recovery_pg import setup as recovery_setup
from test_package_material_scope_findings import checked, draft_for
from test_scope_review_issuers_pg import SIGNER, assign, database

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_original as original
from packages.model_governance import package_current_parse_material as parses
from packages.model_governance import package_current_scope as scope
from packages.model_governance import package_current_scope_review as joint
from packages.model_governance import package_material_archive as archive
from packages.model_governance import package_material_registration as registration
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_scope_findings_store as findings_store
from packages.model_governance import package_scope_review_issuers as issuers
from packages.storage.private_cas import PrivateContentStore, PrivateStoreError

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_CURRENT_SCOPE_REVIEW_PG") != "1",
    reason="explicit grouped joint scope review required",
)


def prepared(wire, tmp_path, outcome="confirmed", *, simulated_prebid=False):
    w, state, url = wire
    root, recovery_key, bundle = recovery_setup(wire, tmp_path)
    restored = restore(root, recovery_key, bundle, wire)
    with PrivateContentStore(root) as store:
        registration_key = registration.stage_command(
            store,
            restored,
            command_id=str(uuid4()),
            expected_context_digest=bundle.context.metadata["digest"],
            expected_recovery_commit_digest=recovery_key,
            expected_method_digest=registration.method_digest(),
        )
        pending = registration.record(
            w["database"]["registration_verifier"],
            store,
            command_commit_digest=registration_key,
            expected_method_digest=registration.method_digest(),
        )
        packet = review.build(
            restored.context,
            expected_context_digest=bundle.context.metadata["digest"],
            expected_method_digest=review.method_digest(),
        )
        draft = draft_for(packet)
        draft["findings"][0]["outcome"] = outcome
        report = checked(packet, draft)
        sealed = findings_store.save(
            store,
            report,
            expected_findings_digest=report.metadata["digest"],
            expected_method_digest=findings_store.method_digest(),
        )
        profile_id, case_id = assign(w, pending, packet.metadata["digest"])
        if simulated_prebid:
            # Fresh immutable configuration in a synthetic check DB; no claim
            # that an actual person reviewed these materials.
            owner = w["database"]["owner"]
            new_profile, new_case = str(uuid4()), str(uuid4())
            owner.execute(
                "INSERT INTO scope_review_issuer.profiles SELECT %s,login_name,subject_id,issuer_kind,'current_prebid',authority_policy_digest,findings_method_digest,store_method_digest,database_oid,database_name,valid_from,valid_until FROM scope_review_issuer.profiles WHERE id=%s",
                (new_profile, profile_id),
            )
            owner.execute(
                "UPDATE scope_review_issuer.profile_heads SET profile_id=%s,revision=revision+1 WHERE login_name=%s",
                (new_profile, SIGNER),
            )
            owner.execute(
                "INSERT INTO scope_review_issuer.cases SELECT %s,%s,registration_id,registration_digest,context_digest,review_digest,valid_from,valid_until FROM scope_review_issuer.cases WHERE id=%s",
                (new_case, new_profile, case_id),
            )
            owner.execute(
                "INSERT INTO scope_review_issuer.case_heads VALUES(%s,1,true)", (new_case,)
            )
            profile_id, case_id = new_profile, new_case
        issuer_key = issuers.stage_command(
            store,
            packet,
            case_id=case_id,
            command_id=str(uuid4()),
            findings_commit_digest=sealed,
            expected_findings_digest=report.metadata["digest"],
            expected_method_digest=issuers.method_digest(),
        )
        record = issuers.attest(
            w["database"]["issuer"],
            store,
            command_commit_digest=issuer_key,
            expected_method_digest=issuers.method_digest(),
        )
    return {
        "root": root,
        "recovery_key": recovery_key,
        "bundle": bundle,
        "registration_key": registration_key,
        "issuer_key": issuer_key,
        "pending": pending,
        "record": record,
        "sealed": sealed,
        "profile_id": profile_id,
        "case_id": case_id,
    }


def observe(wire, p, **changes):
    w, state, url = wire
    args = {
        "recovery_commit_digest": p["recovery_key"],
        "registration_command_commit_digest": p["registration_key"],
        "issuer_command_commit_digest": p["issuer_key"],
        "expected_context_digest": p["bundle"].context.metadata["digest"],
        "expected_registration_digest": p["pending"].metadata["digest"],
        "expected_issuer_digest": p["record"].metadata["digest"],
        "expected_method_digest": joint.method_digest(),
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "expected_scope_digest": w["saved_scope"]["digest"],
        "profile": "development_s3",
        "url_for_locator": url,
    } | changes
    with PrivateContentStore(p["root"]) as store:
        return asyncio.run(
            joint.observe(
                store,
                *(
                    w["database"][k]
                    for k in (
                        "scope_verifier",
                        "original_verifier",
                        "parse_verifier",
                        "registration_verifier",
                        "issuer_reader",
                    )
                ),
                **args,
            )
        )


def test_joint_native_private_review_keeps_context_and_observations_separate(wire, tmp_path):
    p = prepared(wire, tmp_path)
    before = canonical(p["bundle"].context.metadata)
    result = observe(wire, p)
    m = result.metadata
    assert canonical(result.context.metadata) == before
    assert (
        m["status"] == "synthetic_review_only" and m["configured_current_review_confirmed"] is False
    )
    assert m["all_findings_claimed_confirmed"] and m["current_native_material_rechecked"]
    assert wire[1]["attempts"] == wire[1]["idle_checks"] == 8
    assert m["initial_recovery"]["digest"] != m["final_recovery"]["digest"]
    assert m["initial_issuer_observation"]["record"] == m["final_issuer_observation"]["record"]
    assert m["registration_digest"] == p["pending"].metadata["digest"]
    assert not any(
        m[k]
        for k in (
            "actual_human_reading_verified",
            "trusted_derivation_bound",
            "necessary_scope_verified",
            "native_binding_verified",
            "input_authority_granted",
            "execution_authorized",
            "historical_existence_verified",
            "send_lease_granted",
            "atomic_snapshot_verified",
        )
    )
    assert m["digest"] == digest({k: v for k, v in m.items() if k != "digest"})
    directory = os.environ.get("FUSION_CURRENT_SCOPE_REVIEW_EVIDENCE")
    if directory:
        (Path(directory) / "current-scope-review-native-proof.json").write_text(
            json.dumps(
                {
                    "joint_method_digest": joint.method_digest(),
                    "observation": m,
                    "actual_loopback_gets": 8,
                    "independent_purpose_connections": 5,
                    "synthetic_review_claims": True,
                    "exact_frozen_context_bytes_preserved": True,
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


@pytest.mark.parametrize(
    "outcome,status",
    [("change_required", "review_changes_required"), ("unable_to_verify", "review_incomplete")],
)
def test_incomplete_review_never_turns_into_confirmation(wire, tmp_path, outcome, status):
    result = observe(wire, prepared(wire, tmp_path, outcome))
    assert (
        result.metadata["status"] == status
        and not result.metadata["configured_current_review_confirmed"]
    )


@pytest.mark.parametrize("mutation", ["profile", "case", "revoke_reenable"])
def test_late_reviewer_revocation_or_head_change_rejects(wire, tmp_path, mutation):
    p = prepared(wire, tmp_path)
    w, state, url = wire

    def changing():
        if state["attempts"] != 8:
            return
        owner = w["database"]["owner"]
        if mutation == "case":
            owner.execute(
                "UPDATE scope_review_issuer.case_heads SET enabled=false,revision=revision+1 WHERE case_id=%s",
                (p["case_id"],),
            )
        else:
            owner.execute(
                "UPDATE scope_review_issuer.profile_heads SET enabled=false,revision=revision+1 WHERE login_name=%s",
                (SIGNER,),
            )
            if mutation == "revoke_reenable":
                owner.execute(
                    "UPDATE scope_review_issuer.profile_heads SET enabled=true,revision=revision+1 WHERE login_name=%s",
                    (SIGNER,),
                )

    state["callback"] = changing
    with pytest.raises(joint.CurrentScopeReviewError, match="UNAVAILABLE|STATE_CHANGED"):
        observe(wire, p)


@pytest.mark.parametrize("mutation", ["withdraw", "close"])
def test_late_source_change_rejects_even_with_unchanged_review(wire, tmp_path, mutation):
    p = prepared(wire, tmp_path)
    w, state, url = wire

    def changing():
        if state["attempts"] == 8:
            owner = w["database"]["owner"]
            if mutation == "close":
                owner.execute(
                    "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                    (w["technical_scope"][0],),
                )
            else:
                root = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0][
                    "source_id"
                ]
                owner.execute(
                    "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
                    (root,),
                )

    state["callback"] = changing
    with pytest.raises(
        (scope.CurrentScopeError, parses.CurrentParseMaterialError, original.CurrentOriginalError),
        match="SOURCE|CURRENT_PREBID",
    ):
        observe(wire, p)


@pytest.mark.parametrize(
    "field",
    ["expected_registration_digest", "expected_issuer_digest", "issuer_command_commit_digest"],
)
def test_native_records_and_saved_commands_must_match_exactly(wire, tmp_path, field):
    p = prepared(wire, tmp_path)
    wrong = "e" * 64
    if field == "issuer_command_commit_digest":
        with PrivateContentStore(p["root"]) as store:
            command = issuers._command(store, p["issuer_key"])
            command["reference"]["context_digest"] = "e" * 64
            wrong = store.publish(canonical(command))
    with pytest.raises(
        (
            registration.MaterialRegistrationError,
            issuers.ScopeIssuerError,
            joint.CurrentScopeReviewError,
        )
    ):
        observe(wire, p, **{field: wrong})


def test_private_report_corruption_does_not_fall_back_to_another_report(wire, tmp_path):
    p = prepared(wire, tmp_path)
    with PrivateContentStore(p["root"]) as store:
        manifest = archive._decode(store.get_commit(p["sealed"]))
    path = p["root"] / "objects" / manifest["object"]["sha256"]
    raw = path.read_bytes()
    path.write_bytes(b"!" + raw[1:])
    with pytest.raises(PrivateStoreError, match="PRIVATE_STORE"):
        observe(wire, p)


def test_simulated_current_configuration_accepts_claim_without_input_authority(wire, tmp_path):
    p = prepared(wire, tmp_path, simulated_prebid=True)
    m = observe(wire, p).metadata
    assert m["status"] == "configured_review_confirmed" and m["configured_current_review_confirmed"]
    assert m["actual_human_reading_verified"] is False
    assert m["trusted_derivation_bound"] is False and m["necessary_scope_verified"] is False
    assert m["native_binding_verified"] is False and m["input_authority_granted"] is False
