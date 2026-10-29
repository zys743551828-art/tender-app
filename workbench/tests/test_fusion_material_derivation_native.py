"""Opt-in host controller, actual grouped PG, HTTP originals and isolated renderer."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from psycopg.pq import TransactionStatus
from test_package_current_material_pg import (
    api,
    database,
    exact,
    pdf_data,
    requirements,
    saved,
    world,
)
from test_package_current_original_set_pg import wire

from deploy import fusion_material_derivation as controller
from deploy.fusion_asset_runtime import FusionAssetRuntime, source_digest
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_parse_material as parses
from packages.model_governance import package_current_scope as scope

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_DERIVATION_NATIVE") != "1",
    reason="explicit trusted host and grouped isolated PG checks required",
)


@pytest.fixture
def runtime():
    return FusionAssetRuntime(
        expected_image_id=os.environ["FUSION_MATERIAL_DERIVATION_IMAGE"],
        expected_source_digest=source_digest(),
    )


def collect(wire, runtime, **changes):
    w, state, url = wire
    args = {
        "runtime": runtime,
        "expected_method_digest": controller.method_digest(),
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "expected_scope_digest": w["saved_scope"]["digest"],
        "profile": "development_s3",
        "url_for_locator": url,
    } | changes
    return asyncio.run(
        controller.collect(
            *(w["database"][k] for k in ("scope_verifier", "original_verifier", "parse_verifier")),
            **args,
        )
    )


def test_native_sources_actual_compose_render_and_fresh_post_render_observations(
    wire, runtime, monkeypatch
):
    w, state, url = wire
    real_render = runtime.render
    connections = [
        w["database"][k] for k in ("scope_verifier", "original_verifier", "parse_verifier")
    ]
    events = []

    def rendering(*args, **kwargs):
        assert all(c.info.transaction_status == TransactionStatus.IDLE for c in connections)
        value = real_render(*args, **kwargs)
        assert value.execution_receipt["stopped_verified"]
        events.append("render_stopped")
        return value

    real_observe = parses.observe

    def observing(*args, **kwargs):
        events.append("parse_observation")
        return real_observe(*args, **kwargs)

    monkeypatch.setattr(runtime, "render", rendering)
    monkeypatch.setattr(parses, "observe", observing)
    result = collect(wire, runtime)
    assert events == ["parse_observation", "render_stopped", "render_stopped", "parse_observation"]
    assert state["attempts"] == state["idle_checks"] == 2
    m = result.metadata
    assert len(m["documents"]) == 2
    assert len({r["receipt"]["container_id"] for r in m["documents"]}) == 2
    assert sum(len(b.manifest["pages"]) for b in result.material.page_bundles.values()) == 4
    assert m["fresh_native_facts_checked_after_all_render_sessions"]
    assert m["actual_render_boundaries_observed"] and m["renderer_receipts_match_all_documents"]
    assert result.material.metadata["renderer_boundary_verified"] is False
    assert m["digest"] == digest({k: v for k, v in m.items() if k != "digest"})
    assert all(c.info.transaction_status == TransactionStatus.IDLE for c in connections)
    assert not any(
        m[k]
        for k in (
            "input_authority_granted",
            "execution_authorized",
            "native_binding_verified",
            "necessary_scope_verified",
            "visual_readability_verified",
            "historical_existence_verified",
        )
    )
    assert w["io"]["data"].decode("latin-1") not in canonical(m).decode("utf-8")
    proof = {
        "controller_method_digest": controller.method_digest(),
        "derivation": m,
        "native_material_observation": result.material.metadata,
        "events": events,
        "actual_loopback_gets": 2,
        "actual_fresh_compose_sessions": 3,
        "physical_pages": 4,
        "database_rechecked_after_container_render": True,
        "transactions_idle_during_get_and_render": True,
        "synthetic_material": True,
        "input_authority_granted": False,
        "provider_attempts": 0,
        "body_exported": False,
    }
    (
        Path(os.environ["FUSION_MATERIAL_DERIVATION_EVIDENCE"])
        / "material-derivation-native-proof.json"
    ).write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("mutation", ["withdraw", "close"])
def test_change_after_actual_render_rejects_whole_result(wire, runtime, monkeypatch, mutation):
    w, state, url = wire
    real_render = runtime.render
    receipts = []

    def rendering(*args, **kwargs):
        value = real_render(*args, **kwargs)
        receipts.append(value.execution_receipt)
        if len(receipts) == 1:
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
        return value

    monkeypatch.setattr(runtime, "render", rendering)
    with pytest.raises((parses.CurrentParseMaterialError, scope.CurrentScopeError)):
        collect(wire, runtime)
    assert len(receipts) == 2 and all(r["stopped_verified"] for r in receipts)


@pytest.mark.parametrize("mutation", ["original", "manifest", "container_reuse"])
def test_receipt_must_match_exact_derived_document(wire, runtime, monkeypatch, mutation):
    real_render = runtime.render
    previous = []

    def rendering(*args, **kwargs):
        value = real_render(*args, **kwargs)
        r = dict(value.execution_receipt)
        if mutation == "original":
            r["original_digest"] = "e" * 64
        elif mutation == "manifest":
            r["result_manifest_digest"] = "e" * 64
        elif previous:
            r["container_id"] = previous[0]
        previous.append(r["container_id"])
        return replace(value, execution_receipt=r)

    monkeypatch.setattr(runtime, "render", rendering)
    with pytest.raises(controller.MaterialDerivationError, match="RECEIPT_MISMATCH"):
        collect(wire, runtime)


def test_wrong_controller_method_rejects_before_network_or_render(wire, runtime, monkeypatch):
    monkeypatch.setattr(runtime, "describe", lambda: pytest.fail("must not start renderer"))
    with pytest.raises(controller.MaterialDerivationError, match="METHOD_MISMATCH"):
        collect(wire, runtime, expected_method_digest="a" * 64)
    assert wire[1]["attempts"] == 0
