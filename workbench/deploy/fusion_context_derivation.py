"""Live trusted-host derivation for an exact frozen complete material context.

Preserves frozen acquisition identity/time and every declared crop. Actual new
render/source observations stay separate and grant no input or send authority.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from deploy import fusion_material_derivation as derivation
from deploy.fusion_asset_runtime import FusionAssetRuntime
from deploy.fusion_current_material import FusionMaterialPages
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import sha

MAX_OBSERVATION_BYTES = 4 * 1024 * 1024


class ContextDerivationError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise ContextDerivationError("CONTEXT_DERIVATION_" + code)


@dataclass(frozen=True, repr=False)
class LiveDerivedContext:
    context: material.MaterialContext
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "fusion-context-derivation-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "derivation_method": derivation.method_digest(),
            "context_method": material.context_method_digest(),
            "maximum_observation_bytes": MAX_OBSERVATION_BYTES,
            "authority_grants": False,
        }
    )


def _stable_assets(bundle):
    m, blobs = assets.verify_bundle(bundle, expected_manifest_digest=bundle.manifest["digest"])
    if m["parent_manifest_digest"] is not None:
        parent = deepcopy(m)
        parent.update(
            crop_method_digest=None, parent_manifest_digest=None, cropped_at=None, details=[]
        )
        if m["parent_manifest_digest"] != digest(
            {k: v for k, v in parent.items() if k != "digest"}
        ):
            fail("PARENT_MANIFEST_MISMATCH")
    stable = {
        k: deepcopy(v)
        for k, v in m.items()
        if k not in {"digest", "rendered_at", "cropped_at", "parent_manifest_digest"}
    }
    return stable, blobs


def _link_assets(doc, frozen, fresh):
    old, old_blobs = _stable_assets(frozen)
    new, new_blobs = _stable_assets(fresh)
    if canonical(old) != canonical(new) or old_blobs != new_blobs:
        fail("ASSETS_MISMATCH")
    return {
        "document_version_id": doc,
        "frozen_manifest_digest": frozen.manifest["digest"],
        "fresh_manifest": deepcopy(fresh.manifest),
        "stable_assets_digest": digest(old),
        "actual_png_bytes_equal": True,
        "derivation_observation_times_retained_separately": True,
    }


class _FrozenPages(FusionMaterialPages):
    def __init__(self, runtime, context):
        self.regions = {
            doc: [
                {k: deepcopy(r[k]) for k in ("physical_page", "parent_image_digest", "rectangle")}
                for r in manifest["details"]
            ]
            for doc, manifest in context.metadata["material"]["page_asset_manifests"].items()
        }
        super().__init__(runtime)

    def __call__(self, data, document):
        doc = document["document_version_id"]
        if doc not in self.regions:
            fail("DOCUMENT_NOT_FROZEN")
        result = self.runtime.render(
            data,
            document_version_id=doc,
            expected_source_digest=document["source_digest"],
            expected_source_size=document["source_byte_size"],
            expected_render_method_digest=self.render_method_digest,
            expected_crop_method_digest=self.profile["crop_method_digest"],
            regions=deepcopy(self.regions[doc]),
        )
        self.receipts.append(result.execution_receipt)
        return result.bundle


async def collect(
    frozen_context,
    scope_connection,
    original_connection,
    parse_connection,
    *,
    runtime,
    expected_context_digest,
    expected_method_digest,
    profile,
    url_for_locator,
    byte_client=None,
):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    connections = (scope_connection, original_connection, parse_connection)
    if len({id(c) for c in connections}) != 3:
        fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    current._idle(connections)
    if type(runtime) is not FusionAssetRuntime:
        fail("TRUSTED_RUNTIME_REQUIRED")
    owned = material.verify_context(frozen_context, expected_context_digest)
    pins = derivation._pins(runtime)
    pages = _FrozenPages(runtime, owned)
    m = owned.metadata
    fresh = await current.collect(
        *connections,
        bid_id=m["bid_id"],
        scope_id=m["scope_id"],
        expected_scope_digest=m["scope_digest"],
        expected_method_digest=current.method_digest(),
        profile=profile,
        url_for_locator=url_for_locator,
        byte_client=byte_client,
        render_page_assets=pages,
        expected_render_method_digest=pages.render_method_digest,
    )
    current._idle(connections)
    if method_digest() != method or derivation._pins(runtime) != pins:
        fail("METHOD_OR_RUNTIME_CHANGED")
    description, documents = derivation._checked_receipts(fresh, pages, pins)
    if (
        canonical({k: v for k, v in fresh.material.items() if k != "page_asset_manifests"})
        != canonical({k: v for k, v in m["material"].items() if k != "page_asset_manifests"})
        or fresh.originals != owned.origin.originals
    ):
        fail("MATERIAL_MISMATCH")
    if set(fresh.page_bundles) != set(owned.origin.page_bundles):
        fail("DOCUMENT_SET_MISMATCH")
    links = [
        _link_assets(doc, owned.origin.page_bundles[doc], bundle)
        for doc, bundle in fresh.page_bundles.items()
    ]
    rebound_bundles = {
        doc: assets.PageAssetBundle(
            deepcopy(owned.origin.page_bundles[doc].manifest), dict(bundle.blobs)
        )
        for doc, bundle in fresh.page_bundles.items()
    }
    # Reconstruct only with the independently re-fetched bytes and actual derived
    # assets. The frozen observation/time is not replaced by a new acquisition.
    origin = current.CurrentMaterial(
        deepcopy(owned.origin.metadata),
        deepcopy(m["material"]),
        fresh.originals,
        rebound_bundles,
    )
    restored = material.verify_context(
        material.MaterialContext(deepcopy(m), origin), expected_context_digest
    )
    metadata = {
        "version": "fusion-exact-context-derivation/1",
        "method_digest": method,
        "context_digest": expected_context_digest,
        "context_method_digest": material.context_method_digest(),
        "frozen_material_digest": m["source_material_digest"],
        "fresh_material_digest": fresh.metadata["material_digest"],
        "original_source_observation_digest": m["source_observation_digest"],
        "fresh_material_observation": deepcopy(fresh.metadata),
        "runtime": pins,
        "runtime_description_receipt": description,
        "documents": documents,
        "document_manifest_links": links,
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
    if len(canonical(metadata)) > MAX_OBSERVATION_BYTES:
        fail("OBSERVATION_LIMIT")
    if method_digest() != method:
        fail("METHOD_CHANGED")
    return LiveDerivedContext(restored, metadata | {"digest": digest(metadata)})
