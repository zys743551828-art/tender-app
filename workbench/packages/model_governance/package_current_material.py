"""Owned native material projection retaining all frozen declarations and records.

It does not adapt multi-source rules to the single-source /2 model contract.
It grants no necessary-scope, readability, input, execution or historical authority.
"""

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import NoReturn

from psycopg.pq import TransactionStatus

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_original as locator
from packages.model_governance import package_current_original_set as originals
from packages.model_governance import package_current_parse_material as parses
from packages.model_governance import package_current_scope as scope
from packages.model_governance import package_technical_assets as assets
from packages.model_governance.technical_png import digest_bytes

MAX_PAGES = 256
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_TOTAL_PIXELS = 128_000_000
MAX_MATERIAL_BYTES = 8 * 1024 * 1024


class CurrentMaterialError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise CurrentMaterialError("CURRENT_MATERIAL_" + code)


@dataclass(frozen=True, repr=False)
class CurrentMaterial:
    metadata: dict
    material: dict
    originals: dict[str, bytes]
    page_bundles: dict[str, assets.PageAssetBundle]


def method_digest():
    return digest(
        {
            "version": "package-current-material-method/1",
            "source_digest": digest_bytes(Path(__file__).read_bytes()),
            "original_set_method_digest": originals.method_digest(),
            "parse_material_method_digest": parses.method_digest(),
            "render_verifier_source_digest": digest_bytes(Path(assets.__file__).read_bytes()),
            "limits": [MAX_PAGES, MAX_ASSET_BYTES, MAX_TOTAL_PIXELS, MAX_MATERIAL_BYTES],
            "authority_grants": False,
        }
    )


def _expected(facts):
    documents = facts["scope"]["manifest"]["preview"]["manifest"]["documents"]
    expected: dict[str, dict] = {}
    for row in documents:
        p = row["parse"]
        if p["status"] != "frozen":
            fail("EXACT_PARSE_REQUIRED")
        identity = {
            "document_version_id": row["document_version_id"],
            "source_digest": row["file_digest"],
            "source_byte_size": row["byte_size"],
            "parse_run_id": p["parse_run_id"],
            "parse_digest": p["evidence_digest"],
            "parser_digest": p["parser_digest"],
            "config_digest": p["config_digest"],
            "page_count": row["page_count"],
        }
        key = row["document_version_id"]
        if key in expected and expected[key] != identity:
            fail("DOCUMENT_PARSE_AMBIGUOUS")
        expected[key] = identity
    return [expected[key] for key in sorted(expected)]


def _check_frozen(facts, native):
    actual = {row["document_version_id"]: row for row in native.documents}
    frozen = facts["scope"]["manifest"]["preview"]["manifest"]["documents"]
    for document in frozen:
        row = actual[document["document_version_id"]]
        pages = [
            {
                "physical_page": p["physical_page"],
                "quality": p["quality"],
                "gaps": json.loads(p["gaps"]),
            }
            for p in row["pages"]
        ]
        blocks = [
            {
                **{k: v for k, v in b.items() if k not in {"bbox", "structure"}},
                "bbox_json": b["bbox"],
                "structure_json": b["structure"],
            }
            for b in row["blocks"]
        ]
        if canonical(document["pages"]) != canonical(pages) or canonical(
            document["blocks"]
        ) != canonical(blocks):
            fail("FROZEN_PARSE_CONTENT_MISMATCH")


def _idle(connections):
    if any(c.info.transaction_status != TransactionStatus.IDLE for c in connections):
        fail("IDLE_CONNECTIONS_REQUIRED")


def _check_page_geometry(manifest, native_pages):
    if len(manifest["pages"]) != len(native_pages):
        fail("PAGE_GEOMETRY_MISMATCH")
    for page, native in zip(manifest["pages"], native_pages, strict=True):
        valid = False
        try:
            dimensions = [
                Decimal(value)
                for value in (
                    page["canvas_width"],
                    page["canvas_height"],
                    native["width"],
                    native["height"],
                )
            ]
            valid = (
                all(value.is_finite() and value > 0 for value in dimensions)
                and dimensions[:2] == dimensions[2:]
            )
        except (InvalidOperation, ValueError, TypeError):
            pass
        if (
            not valid
            or page["physical_page"] != native["physical_page"]
            or page["rotation"] != native["rotation"]
        ):
            fail("PAGE_GEOMETRY_MISMATCH")


async def collect(
    scope_connection,
    original_connection,
    parse_connection,
    *,
    bid_id,
    scope_id,
    expected_scope_digest,
    expected_method_digest,
    profile,
    url_for_locator,
    render_page_assets,
    expected_render_method_digest,
    byte_client=None,
):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    scope_method, parse_method = scope.method_digest(), parses.method_digest()
    original_method, set_method = locator.method_digest(), originals.method_digest()
    args = {"bid_id": bid_id, "scope_id": scope_id, "expected_scope_digest": expected_scope_digest}
    initial = scope.observe(scope_connection, **args, expected_method_digest=scope_method)
    expected = _expected(initial.metadata)
    if sum(row["page_count"] for row in expected) > MAX_PAGES:
        fail("PAGE_LIMIT")
    before = parses.observe(
        parse_connection,
        bid_id=bid_id,
        expected_documents=expected,
        expected_method_digest=parse_method,
    )
    _check_frozen(initial.metadata, before)
    read = await originals.collect(
        scope_connection,
        original_connection,
        **args,
        expected_method_digest=set_method,
        profile=profile,
        url_for_locator=url_for_locator,
        byte_client=byte_client,
    )
    if _expected(read.scope_facts) != expected:
        fail("FROZEN_IDENTITY_CHANGED")
    bundles, total_pages, total_bytes, total_pixels = {}, 0, 0, 0
    for document in expected:
        _idle((scope_connection, original_connection, parse_connection))
        # The trusted host supplies a pinned renderer; this layer only verifies
        # its exact byte/page bindings and does not manufacture an isolation proof.
        bundle = render_page_assets(read.originals[document["document_version_id"]], dict(document))
        manifest, content = assets.verify_bundle(
            bundle, expected_manifest_digest=bundle.manifest["digest"]
        )
        for key in ("document_version_id", "source_digest", "source_byte_size", "page_count"):
            if manifest[key] != document[key]:
                fail("ASSET_BINDING_MISMATCH")
        if manifest["render_method_digest"] != expected_render_method_digest:
            fail("RENDER_METHOD_MISMATCH")
        native = next(
            row
            for row in before.documents
            if row["document_version_id"] == document["document_version_id"]
        )
        _check_page_geometry(manifest, native["pages"])
        total_pages += len(manifest["pages"])
        total_bytes += sum(len(raw) for raw in content.values())
        total_pixels += sum(
            r["asset"]["width"] * r["asset"]["height"]
            for r in [*manifest["pages"], *manifest["details"]]
        )
        if (
            total_pages > MAX_PAGES
            or total_bytes > MAX_ASSET_BYTES
            or total_pixels > MAX_TOTAL_PIXELS
        ):
            fail("ASSET_LIMIT")
        bundles[document["document_version_id"]] = assets.PageAssetBundle(manifest, content)
    final = parses.observe(
        parse_connection,
        bid_id=bid_id,
        expected_documents=expected,
        expected_method_digest=parse_method,
    )
    if canonical(final.documents) != canonical(before.documents) or canonical(
        final.metadata["graph"]
    ) != canonical(before.metadata["graph"]):
        fail("SOURCES_CHANGED")
    facts = scope.observe(scope_connection, **args, expected_method_digest=scope_method).metadata
    _check_frozen(facts, final)
    for receipt in read.metadata["files"]:
        old = receipt["final_locator_observation"]
        current = locator.observe(
            original_connection,
            **args,
            document_version_id=old["document_version_id"],
            expected_original_digest=old["source_digest"],
            expected_method_digest=original_method,
        )
        if originals._stable_locator(current) != canonical(
            {k: v for k, v in old.items() if k not in {"observed_at", "digest"}}
        ):
            fail("LOCATOR_CHANGED")
    # Preserve the complete source structures, including excluded rules, every
    # rule's evidence, numeric bands, exceptions, declared parts and coverage gaps.
    material = {
        "version": "package-current-material-projection/1",
        "scope": facts["scope"],
        "target": facts["target"],
        "authority": facts["authority"],
        "inventory": facts["inventory"],
        "current_identity": facts["current_identity"],
        "native_documents": final.documents,
        "page_asset_manifests": {key: value.manifest for key, value in bundles.items()},
    }
    if len(canonical(material)) > MAX_MATERIAL_BYTES:
        fail("MATERIAL_LIMIT")
    if method_digest() != method:
        fail("METHOD_CHANGED")
    public = {
        "version": "package-current-material-observation/1",
        "bid_id": bid_id,
        "scope_id": scope_id,
        "scope_digest": expected_scope_digest,
        "method_digest": method,
        "material_digest": digest(material),
        "original_set_digest": read.metadata["digest"],
        "initial_parse_observation": before.metadata,
        "final_parse_observation": final.metadata,
        "final_scope_observation_digest": facts["digest"],
        "document_count": len(expected),
        "physical_page_count": total_pages,
        "asset_bytes": total_bytes,
        "asset_pixels": total_pixels,
        "native_parse_and_original_material_observed": True,
        "complete_frozen_declarations_retained": True,
        "renderer_boundary_verified": False,
        "visual_readability_verified": False,
        "necessary_scope_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    return CurrentMaterial(public | {"digest": digest(public)}, material, read.originals, bundles)
