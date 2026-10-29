"""Trusted host orchestration of native material and actual Compose rendering.

No API/Worker wiring, environment discovery, supplied execution receipts, grants,
or content-qualification decisions. Old material observations remain unchanged.
"""

import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from deploy import fusion_asset_runtime as runtime_port
from deploy import fusion_current_material as pages_port
from packages.domain.review_identity import digest
from packages.model_governance import package_current_material as current
from packages.model_governance import technical_png as png
from packages.parsing import page_asset_wire as wire


class MaterialDerivationError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class DerivedMaterial:
    material: current.CurrentMaterial
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "fusion-material-derivation-method/1",
            "source": png.digest_bytes(Path(__file__).read_bytes()),
            "page_adapter_source": png.digest_bytes(Path(pages_port.__file__).read_bytes()),
            "runtime_source": runtime_port.source_digest(),
            "material_method": current.method_digest(),
            "authority_grants": False,
        }
    )


def _pins(runtime):
    return {
        "image_id": runtime.expected_image_id,
        "source_digest": runtime.expected_source_digest,
        "hard_timeout_ms": runtime.hard_timeout_ms,
    }


def _checked_receipts(material, pages, pins):
    manifests = material.material["page_asset_manifests"]
    if len(pages.receipts) != len(manifests) + 1:
        raise MaterialDerivationError("DERIVATION_RECEIPT_COUNT_MISMATCH")
    receipts = deepcopy(pages.receipts)
    identities = set()
    for receipt in receipts:
        if (
            any(receipt.get(k) != v for k, v in pins.items())
            or receipt.get("stopped_verified") is not True
            or type(receipt.get("container_pid")) is not int
            or receipt["container_pid"] != 0
            or receipt.get("source_fingerprint_checked_before_and_after") is not True
            or receipt.get("oom_killed") is not False
            or receipt.get("was_running_before_stop") is not True
            or receipt.get("compose_project") != "tender-fusion"
            or receipt.get("compose_service") != "asset-renderer"
            or type(receipt.get("container_id")) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", receipt["container_id"])
            or receipt["container_id"] in identities
        ):
            raise MaterialDerivationError("DERIVATION_RUNTIME_RECEIPT_MISMATCH")
        identities.add(receipt["container_id"])
    documents = []
    for (doc, manifest), receipt in zip(manifests.items(), receipts[1:], strict=True):
        wire.check(receipt, wire.execution_schema())
        if (
            receipt["original_digest"] != manifest["source_digest"]
            or receipt["result_manifest_digest"] != manifest["digest"]
        ):
            raise MaterialDerivationError("DERIVATION_DOCUMENT_RECEIPT_MISMATCH")
        documents.append(
            {"document_version_id": doc, "manifest_digest": manifest["digest"], "receipt": receipt}
        )
    return receipts[0], documents


async def collect(
    scope_connection,
    original_connection,
    parse_connection,
    *,
    runtime,
    expected_method_digest,
    bid_id,
    scope_id,
    expected_scope_digest,
    profile,
    url_for_locator,
    byte_client=None,
):
    method = method_digest()
    if expected_method_digest != method:
        raise MaterialDerivationError("DERIVATION_METHOD_MISMATCH")
    connections = (scope_connection, original_connection, parse_connection)
    if len({id(c) for c in connections}) != 3:
        raise MaterialDerivationError("DERIVATION_INDEPENDENT_CONNECTIONS_REQUIRED")
    current._idle(connections)
    if type(runtime) is not runtime_port.FusionAssetRuntime:
        raise MaterialDerivationError("DERIVATION_TRUSTED_RUNTIME_REQUIRED")
    pins = _pins(runtime)
    pages = pages_port.FusionMaterialPages(runtime)
    origin = await current.collect(
        *connections,
        bid_id=bid_id,
        scope_id=scope_id,
        expected_scope_digest=expected_scope_digest,
        expected_method_digest=current.method_digest(),
        profile=profile,
        url_for_locator=url_for_locator,
        byte_client=byte_client,
        render_page_assets=pages,
        expected_render_method_digest=pages.render_method_digest,
    )
    # collect has now completed fresh parse/scope and all locator observations,
    # after every render session stopped. No database transaction spans rendering.
    current._idle(connections)
    if method_digest() != method or _pins(runtime) != pins:
        raise MaterialDerivationError("DERIVATION_METHOD_OR_RUNTIME_CHANGED")
    description, documents = _checked_receipts(origin, pages, pins)
    metadata = {
        "version": "fusion-current-material-derivation/1",
        "method_digest": method,
        "material_observation_digest": origin.metadata["digest"],
        "material_digest": origin.metadata["material_digest"],
        "runtime": pins,
        "runtime_description_receipt": description,
        "documents": documents,
        "fresh_native_facts_checked_after_all_render_sessions": True,
        "actual_render_boundaries_observed": True,
        "renderer_receipts_match_all_documents": True,
        "visual_readability_verified": False,
        "necessary_scope_verified": False,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    return DerivedMaterial(origin, metadata | {"digest": digest(metadata)})
