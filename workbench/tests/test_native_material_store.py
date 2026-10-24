"""Byte storage with explicitly synthetic derivation claims, no authority."""
# ruff: noqa: F401,F811

from copy import deepcopy
from uuid import uuid4

import pytest
from test_fusion_context_derivation import rescheduled
from test_package_material_scope_findings import checked, draft_for
from test_package_material_scope_review import review_origin
from test_package_technical_material import context, synthetic

from deploy import fusion_context_derivation as derivation
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_native_material_store as store


def _synthetic_template():
    pins = {"image_id": "sha256:" + "a" * 64, "source_digest": "b" * 64, "hard_timeout_ms": 40000}

    def receipt(index):
        return {
            **pins,
            "container_id": f"{index:064x}",
            "compose_project": "tender-fusion",
            "compose_service": "asset-renderer",
            "container_started_at": "2026-10-24T05:00:00Z",
            "container_finished_at": "2026-10-24T05:00:01Z",
            "stopped_verified": True,
            "container_pid": 0,
            "oom_killed": False,
            "container_exit_code": 0,
            "was_running_before_stop": True,
            "source_fingerprint_checked_before_and_after": True,
            "observed_kernel_limits": {
                "memory.max": "1073741824",
                "memory.swap.max": "0",
                "pids.max": "32",
                "cpu.max": "100000 100000",
                "no_new_privileges": True,
                "seccomp_filter_active": True,
                "effective_permitted_bounding_ambient_capabilities_zero": True,
                "network_interfaces": ["lo"],
                "read_only_source_files": 7,
            },
        }

    return {
        "version": "fusion-exact-context-derivation/1",
        "runtime": pins,
        "runtime_description_receipt": receipt(100),
        "documents": [
            {
                "receipt": {
                    **receipt(index),
                    "version": "package-page-render-execution/1",
                    "container_boundary_observed": True,
                    "input_authority_granted": False,
                    "visual_readability_verified": False,
                    "formal_execution_authorized": False,
                }
            }
            for index in (1, 2)
        ],
        "exact_frozen_context_preserved": True,
        "trusted_derivation_bound": True,
        "frozen_detail_crops_preserved": True,
        "fresh_native_facts_checked_after_all_render_sessions": True,
        "visual_readability_verified": False,
        "necessary_scope_verified": False,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
        "atomic_snapshot_verified": False,
        "send_lease_granted": False,
    }


def claims_for(ctx):
    # Entirely synthetic claims, never evidence of actual kernel execution.
    template = _synthetic_template()
    m = deepcopy(template)
    links = []
    documents = []
    manifests = {}
    for index, (doc, old) in enumerate(ctx.origin.page_bundles.items()):
        fresh = rescheduled(old)
        links.append(derivation._link_assets(doc, old, fresh))
        manifests[doc] = fresh.manifest
        receipt = deepcopy(template["documents"][index]["receipt"])
        receipt["original_digest"] = fresh.manifest["source_digest"]
        receipt["result_manifest_digest"] = fresh.manifest["digest"]
        receipt["wire_result_digest"] = digest(
            ["synthetic wire claim", doc, fresh.manifest["digest"]]
        )
        documents.append(
            {
                "document_version_id": doc,
                "manifest_digest": fresh.manifest["digest"],
                "receipt": receipt,
            }
        )
    fresh_material = deepcopy(ctx.metadata["material"])
    fresh_material["page_asset_manifests"] = manifests
    observation = deepcopy(ctx.origin.metadata)
    observation["material_digest"] = digest(fresh_material)
    observation["digest"] = digest({k: v for k, v in observation.items() if k != "digest"})
    m.update(
        method_digest=derivation.method_digest(),
        context_digest=ctx.metadata["digest"],
        context_method_digest=ctx.metadata["context_method_digest"],
        frozen_material_digest=ctx.metadata["source_material_digest"],
        fresh_material_digest=digest(fresh_material),
        original_source_observation_digest=ctx.metadata["source_observation_digest"],
        fresh_material_observation=observation,
        documents=documents,
        document_manifest_links=links,
    )
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    return derivation.LiveDerivedContext(ctx, m)


def prepared(ctx, reason_suffix=""):
    packet = review.build(
        ctx,
        expected_context_digest=ctx.metadata["digest"],
        expected_method_digest=review.method_digest(),
    )
    draft = draft_for(packet)
    draft["findings"][0]["reason"] += reason_suffix
    report = checked(packet, draft)
    live = claims_for(ctx)
    return store.prepare(
        live,
        report,
        expected_context_digest=ctx.metadata["digest"],
        expected_findings_digest=report.metadata["digest"],
        expected_derivation_digest=live.metadata["digest"],
        expected_producer_method_digest=live.metadata["method_digest"],
        expected_method_digest=store.method_digest(),
    )


def test_complete_private_objects_and_packet_close_without_granting_authority(review_origin):
    p = prepared(context(review_origin))
    assert set(p.objects) == set(store._packet(p.packet))
    assert p.objects[p.packet["context_object"]["sha256"]] == canonical(p.live.context.metadata)
    assert p.packet["image_objects"]
    assert not any(p.findings.metadata[k] for k in store.FLAGS - {"historical_existence_verified"})


@pytest.mark.parametrize(
    "mutation",
    ["extra", "boolean_size", "duplicate_asset", "zero_digest", "oversize_context", "object_key"],
)
def test_closed_packet_rejects_malformed_or_excessive_references(review_origin, mutation):
    p = deepcopy(prepared(context(review_origin)).packet)
    if mutation == "extra":
        p["input_authority_granted"] = True
    elif mutation == "boolean_size":
        p["image_objects"][0]["byte_size"] = True
    elif mutation == "duplicate_asset":
        p["image_objects"].append(deepcopy(p["image_objects"][0]))
    elif mutation == "zero_digest":
        p["context_digest"] = "0" * 64
    elif mutation == "oversize_context":
        p["context_object"]["byte_size"] = store.CAPS[0] + 1
    else:
        p["context_object"]["locator"] = "not allowed"
    with pytest.raises(store.NativeMaterialStoreError):
        store._packet(p)


def test_rehashed_derivation_cannot_grant_qualification(review_origin):
    p = prepared(context(review_origin))
    m = p.live.metadata
    m["input_authority_granted"] = True
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    with pytest.raises(store.NativeMaterialStoreError, match="DERIVATION_CLAIM_INVALID"):
        store.prepare(
            p.live,
            p.findings,
            expected_context_digest=p.packet["context_digest"],
            expected_findings_digest=p.packet["findings_digest"],
            expected_derivation_digest=m["digest"],
            expected_producer_method_digest=p.producer_method_digest,
            expected_method_digest=store.method_digest(),
        )


def test_prepared_object_mutation_rejects_before_database(review_origin):
    p = prepared(context(review_origin))
    key = next(iter(p.objects))
    p.objects[key] = b"changed"
    with pytest.raises(store.NativeMaterialStoreError, match="PREPARED_EVIDENCE_INVALID"):
        store.put(
            None,
            p,
            command_id=str(uuid4()),
            expected_packet_digest=digest(p.packet),
            expected_method_digest=store.method_digest(),
        )
