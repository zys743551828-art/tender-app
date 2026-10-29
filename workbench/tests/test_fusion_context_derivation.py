"""Invalid control inputs cannot start a derivation or inspect private context."""
# ruff: noqa: F401,F811

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus
from test_package_technical_material import synthetic

from deploy import fusion_context_derivation as controller
from deploy.fusion_asset_runtime import FusionAssetRuntime
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import technical_png as png


def rescheduled(bundle):
    m = deepcopy(bundle.manifest)
    m["rendered_at"] = "2026-10-24T05:45:00.000000Z"
    if m["parent_manifest_digest"] is not None:
        m["cropped_at"] = "2026-10-24T05:45:01.000000Z"
        parent = deepcopy(m)
        parent.update(
            crop_method_digest=None, parent_manifest_digest=None, cropped_at=None, details=[]
        )
        m["parent_manifest_digest"] = digest({k: v for k, v in parent.items() if k != "digest"})
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    return assets.PageAssetBundle(m, dict(bundle.blobs))


def test_new_observation_time_keeps_both_manifests_and_exact_pixels(synthetic):
    old = next(b for b in synthetic.page_bundles.values() if b.manifest["details"])
    before = canonical(old.manifest)
    fresh = rescheduled(old)
    link = controller._link_assets(old.manifest["document_version_id"], old, fresh)
    assert link["frozen_manifest_digest"] == old.manifest["digest"]
    assert link["fresh_manifest"]["digest"] == fresh.manifest["digest"] != old.manifest["digest"]
    assert link["actual_png_bytes_equal"] and canonical(old.manifest) == before
    assert (
        link["fresh_manifest"]["parent_manifest_digest"] != old.manifest["parent_manifest_digest"]
    )


@pytest.mark.parametrize("mutation", ["method", "parent", "rectangle", "png"])
def test_observation_time_difference_cannot_hide_asset_or_parent_change(synthetic, mutation):
    old = next(b for b in synthetic.page_bundles.values() if b.manifest["details"])
    fresh = rescheduled(old)
    if mutation == "method":
        fresh.manifest["render_method_digest"] = "e" * 64
    elif mutation == "parent":
        fresh.manifest["parent_manifest_digest"] = "e" * 64
    elif mutation == "rectangle":
        fresh.manifest["details"][0]["rectangle"][0] = 1
    else:
        key = next(iter(fresh.blobs))
        raw = fresh.blobs[key]
        fresh.blobs[key] = b"!" + raw[1:]
    fresh.manifest["digest"] = digest({k: v for k, v in fresh.manifest.items() if k != "digest"})
    with pytest.raises((controller.ContextDerivationError, png.PageAssetError)):
        controller._link_assets(old.manifest["document_version_id"], old, fresh)


@pytest.mark.parametrize("fault", ["method", "connection", "transaction", "runtime"])
def test_invalid_controls_reject_before_frozen_material_or_docker(monkeypatch, fault):
    monkeypatch.setattr(
        controller.material,
        "verify_context",
        lambda *args: pytest.fail("must not inspect private context"),
    )
    conns = [
        SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
        for _ in range(3)
    ]
    runtime = FusionAssetRuntime(
        expected_image_id="sha256:" + "a" * 64, expected_source_digest="b" * 64
    )
    expected = controller.method_digest()
    if fault == "method":
        expected = "a" * 64
    elif fault == "connection":
        conns[2] = conns[0]
    elif fault == "transaction":
        conns[0].info.transaction_status = TransactionStatus.INTRANS
    else:
        runtime = object()
    with pytest.raises((controller.ContextDerivationError, current.CurrentMaterialError)):
        asyncio.run(
            controller.collect(
                None,
                *conns,
                runtime=runtime,
                expected_context_digest="c" * 64,
                expected_method_digest=expected,
                profile="development_s3",
                url_for_locator=lambda _: pytest.fail("no GET"),
            )
        )
