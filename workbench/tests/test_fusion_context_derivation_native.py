"""Real frozen full pages/crop, native PG and repeated isolated derivation."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
from pathlib import Path

import pytest
from test_fusion_material_derivation_native import runtime
from test_package_current_material_pg import (
    api,
    database,
    exact,
    pdf_data,
    requirements,
    saved,
    world,
)
from test_package_current_material_pg import collect as native_collect
from test_package_current_original_set_pg import wire
from test_package_technical_material import context

from deploy import fusion_context_derivation as controller
from deploy.fusion_current_material import FusionMaterialPages
from packages.domain.review_identity import canonical, digest

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_CONTEXT_DERIVATION_NATIVE") != "1",
    reason="explicit grouped live context derivation required",
)


def freeze(wire, runtime):
    w, state, url = wire
    pages = FusionMaterialPages(runtime)
    received = []

    def render(raw, doc):
        args = {
            "document_version_id": doc["document_version_id"],
            "expected_source_digest": doc["source_digest"],
            "expected_source_size": doc["source_byte_size"],
            "expected_render_method_digest": pages.render_method_digest,
            "expected_crop_method_digest": pages.profile["crop_method_digest"],
        }
        baseline = runtime.render(raw, regions=[], **args)
        received.append(baseline.execution_receipt)
        if len(received) == 1:
            first = baseline.bundle.manifest["pages"][0]["asset"]
            cropped = runtime.render(
                raw,
                regions=[
                    {
                        "physical_page": 1,
                        "parent_image_digest": first["sha256"],
                        "rectangle": [0, 0, 120, 160],
                    }
                ],
                **args,
            )
            received.append(cropped.execution_receipt)
            return cropped.bundle
        return baseline.bundle

    native = native_collect(
        w, url, render=render, expected_render_method_digest=pages.render_method_digest
    )
    return context(native)


def collect(wire, runtime, frozen, **changes):
    w, state, url = wire
    args = {
        "runtime": runtime,
        "expected_context_digest": frozen.metadata["digest"],
        "expected_method_digest": controller.method_digest(),
        "profile": "development_s3",
        "url_for_locator": url,
    } | changes
    return asyncio.run(
        controller.collect(
            frozen,
            *(w["database"][k] for k in ("scope_verifier", "original_verifier", "parse_verifier")),
            **args,
        )
    )


def test_actual_new_derivation_preserves_exact_frozen_context_and_detail_crop(wire, runtime):
    frozen = freeze(wire, runtime)
    before = canonical(frozen.metadata)
    result = collect(wire, runtime, frozen)
    m = result.metadata
    assert canonical(result.context.metadata) == before
    assert result.context.origin.metadata == frozen.origin.metadata
    assert result.context.origin.originals == frozen.origin.originals
    assert sum(len(b.manifest["details"]) for b in result.context.origin.page_bundles.values()) == 1
    assert sum(len(b.manifest["pages"]) for b in result.context.origin.page_bundles.values()) == 4
    assert wire[1]["attempts"] == wire[1]["idle_checks"] == 4
    assert m["trusted_derivation_bound"] and m["frozen_detail_crops_preserved"]
    assert m["fresh_material_observation"]["digest"] != frozen.origin.metadata["digest"]
    assert (
        m["fresh_material_observation"]["material_digest"]
        != frozen.metadata["source_material_digest"]
    )
    assert m["frozen_material_digest"] == frozen.metadata["source_material_digest"]
    assert all(
        link["fresh_manifest"]["digest"] != link["frozen_manifest_digest"]
        for link in m["document_manifest_links"]
    )
    assert all(link["actual_png_bytes_equal"] for link in m["document_manifest_links"])
    assert all(row["receipt"]["stopped_verified"] for row in m["documents"])
    assert len({row["receipt"]["container_id"] for row in m["documents"]}) == 2
    assert not any(
        m[k]
        for k in (
            "visual_readability_verified",
            "necessary_scope_verified",
            "native_binding_verified",
            "input_authority_granted",
            "execution_authorized",
            "historical_existence_verified",
            "atomic_snapshot_verified",
            "send_lease_granted",
        )
    )
    assert m["digest"] == digest({k: v for k, v in m.items() if k != "digest"})
    directory = Path(os.environ["FUSION_CONTEXT_DERIVATION_EVIDENCE"])
    (directory / "context-derivation-native-proof.json").write_text(
        json.dumps(
            {
                "controller_method_digest": controller.method_digest(),
                "observation": m,
                "actual_loopback_gets": 4,
                "actual_fresh_compose_sessions": 7,
                "physical_pages": 4,
                "frozen_details": 1,
                "exact_context_time_and_digest_preserved": True,
                "actual_derived_image_bytes_equal": True,
                "database_rechecked_after_new_derivation": True,
                "synthetic_material": True,
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


def test_actual_valid_full_pages_cannot_silently_drop_frozen_detail_crop(
    wire, runtime, monkeypatch
):
    frozen = freeze(wire, runtime)
    real_render = runtime.render

    def dropping(*args, **kwargs):
        kwargs["regions"] = []
        return real_render(*args, **kwargs)

    monkeypatch.setattr(runtime, "render", dropping)
    with pytest.raises(controller.ContextDerivationError, match="ASSETS_MISMATCH"):
        collect(wire, runtime, frozen)


def test_wrong_frozen_context_digest_rejects_before_describe(wire, runtime, monkeypatch):
    frozen = freeze(wire, runtime)
    monkeypatch.setattr(
        runtime, "describe", lambda: pytest.fail("must not render for wrong frozen identity")
    )
    with pytest.raises(ValueError, match="CONTEXT_MISMATCH"):
        collect(wire, runtime, frozen, expected_context_digest="e" * 64)
