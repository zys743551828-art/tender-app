"""Bind all frozen material and assets without performing source qualification.

No DB, object-store, provider or environment ports. Only an owned controller may
supply independently frozen expected digests; accepting a packet is not authority.
"""

import hashlib
import sys
import zlib
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import NoReturn

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts import package_technical_assets as asset_contract
from packages.contracts import package_technical_features as feature_contract
from packages.contracts import package_technical_input as contract
from packages.domain import review_identity
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import technical_png as png

MAX_PROJECTION_BYTES = 4 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_TOTAL_PIXELS = 128_000_000
MAX_PAGES = 256
MAX_IMAGES = 384


class TechnicalInputError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise TechnicalInputError(code)


@dataclass(frozen=True, repr=False)
class TechnicalInputBundle:
    metadata: dict
    blobs: dict[str, bytes]


def _source(module):
    filename = getattr(module, "__file__", None)
    if not isinstance(filename, str):
        fail("TECHNICAL_INPUT_METHOD_UNAVAILABLE")
    try:
        return png.digest_bytes(Path(filename).read_bytes())
    except OSError:
        fail("TECHNICAL_INPUT_METHOD_UNAVAILABLE")


def descriptor():
    return {
        "version": "package-technical-input-method/2",
        "source": png.digest_bytes(Path(__file__).read_bytes()),
        "contract_source": _source(contract),
        "feature_contract_source": _source(feature_contract),
        "asset_contract_source": _source(asset_contract),
        "canonical_source": _source(review_identity),
        "asset_verifier_source": _source(assets),
        "codec_source": _source(png),
        "schema_digest": digest(contract.schema()),
        "output_schema_digest": digest(contract.output_schema()),
        "python_version": list(sys.version_info[:3]),
        "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "schema_validator_version": version("jsonschema"),
        "maximum_projection_bytes": MAX_PROJECTION_BYTES,
        "maximum_metadata_bytes": MAX_METADATA_BYTES,
        "maximum_text_bytes": MAX_TEXT_BYTES,
        "maximum_asset_bytes": MAX_ASSET_BYTES,
        "maximum_total_pixels": MAX_TOTAL_PIXELS,
        "maximum_pages": MAX_PAGES,
        "maximum_images": MAX_IMAGES,
        "part_closure": "descendants_and_transitive_related_parts",
        "materials": "all_frozen_documents_pages_details_and_evidence_in_order",
        "semantic_packet": "version_method_projection_material_digest_rule_closure",
        "authority_grants": False,
    }


def method_digest():
    return digest(descriptor())


def _unique(rows, key, code):
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        fail(code)
    return result


def _parts(projection, documents):
    parts = _unique(projection["parts"], "part_id", "TECHNICAL_INPUT_PART_REUSED")
    children: dict[str, list[str]] = {key: [] for key in parts}
    for key, row in parts.items():
        document = documents.get(row["document_version_id"])
        if document is None or any(
            type(page) is not int or page > document["page_count"] for page in row["physical_pages"]
        ):
            fail("TECHNICAL_INPUT_PART_PAGE_MISMATCH")
        if row["physical_pages"] != sorted(row["physical_pages"]):
            fail("TECHNICAL_INPUT_PART_PAGE_ORDER")
        parent = row["parent_part_id"]
        if parent is not None:
            if (
                parent not in parts
                or parts[parent]["document_version_id"] != row["document_version_id"]
            ):
                fail("TECHNICAL_INPUT_PARENT_MISMATCH")
            children[parent].append(key)
            if not set(row["physical_pages"]).issubset(parts[parent]["physical_pages"]):
                fail("TECHNICAL_INPUT_CHILD_OUTSIDE_PARENT")
        if key in row["related_part_ids"] or any(
            target not in parts for target in row["related_part_ids"]
        ):
            fail("TECHNICAL_INPUT_RELATED_PART_MISMATCH")
    # Iterative coloring bounds deeply nested input without recursive stack growth.
    done: set[str] = set()
    for key in parts:
        chain: set[str] = set()
        node = key
        while node is not None and node not in done:
            if node in chain:
                fail("TECHNICAL_INPUT_PARENT_CYCLE")
            chain.add(node)
            node = parts[node]["parent_part_id"]
        done.update(chain)
    return parts, children


def _closure(selected, parts, children):
    pending = list(selected)
    found: set[str] = set()
    while pending:
        key = pending.pop()
        if key not in parts:
            fail("TECHNICAL_INPUT_REQUIRED_PART_MISSING")
        if key in found:
            continue
        found.add(key)
        pending.extend(children[key])
        pending.extend(parts[key]["related_part_ids"])
    return [key for key in parts if key in found]


def _materials(documents, bundles):
    if type(bundles) is not dict or set(bundles) != set(documents):
        fail("TECHNICAL_INPUT_DOCUMENT_ASSETS_MISMATCH")
    pages: list[dict] = []
    details: list[dict] = []
    blobs: dict[str, bytes] = {}
    for key, document in documents.items():
        manifest, content = assets.verify_bundle(
            bundles[key], expected_manifest_digest=document["asset_manifest_digest"]
        )
        if any(
            manifest[field] != document[field]
            for field in ("document_version_id", "source_digest", "source_byte_size", "page_count")
        ):
            fail("TECHNICAL_INPUT_SOURCE_MISMATCH")
        for row in manifest["pages"]:
            pages.append(
                {"document_version_id": key, "parse_run_id": document["parse_run_id"], **row}
            )
        for row in manifest["details"]:
            details.append({"document_version_id": key, **row})
        if set(blobs).intersection(content):
            fail("TECHNICAL_INPUT_ASSET_ID_REUSED")
        blobs.update(content)
        if (
            len(pages) > MAX_PAGES
            or len(pages) + len(details) > MAX_IMAGES
            or sum(len(raw) for raw in blobs.values()) > MAX_ASSET_BYTES
            or sum(row["asset"]["width"] * row["asset"]["height"] for row in pages + details)
            > MAX_TOTAL_PIXELS
        ):
            fail("TECHNICAL_INPUT_ASSET_LIMIT")
    return pages, details, blobs


def _evidence(projection, documents, parts, pages):
    catalog = _unique(
        projection["evidence_catalog"], "evidence_id", "TECHNICAL_INPUT_EVIDENCE_REUSED"
    )
    page_index = {(row["document_version_id"], row["physical_page"]): row["asset"] for row in pages}
    text_bytes = 0
    for row in catalog.values():
        document = documents.get(row["document_version_id"])
        image = page_index.get((row["document_version_id"], row["physical_page"]))
        if (
            document is None
            or image is None
            or row["parse_run_id"] != document["parse_run_id"]
            or row["page_image_digest"] != image["sha256"]
            or (row["page_width"], row["page_height"]) != (image["width"], image["height"])
            or type(row["physical_page"]) is not int
            or type(row["page_width"]) is not int
            or type(row["page_height"]) is not int
        ):
            fail("TECHNICAL_INPUT_EVIDENCE_PAGE_MISMATCH")
        if png.digest_bytes(row["text"].encode("utf-8")) != row["text_digest"]:
            fail("TECHNICAL_INPUT_TEXT_MISMATCH")
        for key in row["part_ids"]:
            part = parts.get(key)
            if (
                part is None
                or part["document_version_id"] != row["document_version_id"]
                or row["physical_page"] not in part["physical_pages"]
            ):
                fail("TECHNICAL_INPUT_EVIDENCE_PART_MISMATCH")
        text_bytes += len(row["text"].encode("utf-8"))
        if text_bytes > MAX_TEXT_BYTES:
            fail("TECHNICAL_INPUT_TEXT_LIMIT")
    return catalog


def build_input(projection, bundles, *, expected_projection_digest, expected_method_digest):
    """Return all supplied frozen material; expected digests come from owned state.

    Mechanical completeness here is relative to that external projection. This
    function cannot prove semantic scope, original bytes, readability or rights.
    """
    if expected_method_digest != method_digest():
        fail("TECHNICAL_INPUT_METHOD_MISMATCH")
    try:
        raw = canonical(projection)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        fail("TECHNICAL_INPUT_PROJECTION_INVALID")
    if len(raw) > MAX_PROJECTION_BYTES:
        fail("TECHNICAL_INPUT_PROJECTION_LIMIT")
    if hashlib.sha256(raw).hexdigest() != expected_projection_digest:
        fail("TECHNICAL_INPUT_PROJECTION_MISMATCH")
    if not Draft202012Validator(contract.schema(), format_checker=FormatChecker()).is_valid(
        projection
    ):
        fail("TECHNICAL_INPUT_PROJECTION_INVALID")
    documents = _unique(
        projection["documents"], "document_version_id", "TECHNICAL_INPUT_DOCUMENT_REUSED"
    )
    if {row["package_role"] for row in documents.values()} != {"authority", "target"}:
        fail("TECHNICAL_INPUT_PACKAGE_ROLES_MISSING")
    _unique(projection["documents"], "parse_run_id", "TECHNICAL_INPUT_PARSE_REUSED")
    rules = _unique(projection["rules"], "rule_id", "TECHNICAL_INPUT_RULE_REUSED")
    parts, children = _parts(projection, documents)
    pages, details, blobs = _materials(documents, bundles)
    catalog = _evidence(projection, documents, parts, pages)
    material = {
        "binding": deepcopy(projection["binding"]),
        "documents": deepcopy(projection["documents"]),
        "parts": deepcopy(projection["parts"]),
        "pages": pages,
        "details": details,
        "evidence_catalog": deepcopy(projection["evidence_catalog"]),
    }
    material_digest = digest(material)
    packets = []
    for rule in rules.values():
        source = catalog.get(rule["source_evidence_id"])
        quote = rule["source_quote"]
        if (
            source is None
            or documents[source["document_version_id"]]["package_role"] != "authority"
            or not quote.strip()
            or quote not in source["text"]
            or png.digest_bytes(quote.encode("utf-8")) != rule["source_quote_digest"]
        ):
            fail("TECHNICAL_INPUT_RULE_SOURCE_MISMATCH")
        closure = _closure(rule["required_part_ids"], parts, children)
        if any(
            documents[parts[key]["document_version_id"]]["package_role"] != "target"
            for key in rule["required_part_ids"]
        ):
            fail("TECHNICAL_INPUT_RULE_TARGET_MISMATCH")
        # Every packet binds every page/detail/block. No top-k or rule-local
        # filtering can silently discard context from the owned projection.
        semantic = {
            "version": "package-technical-rule-input/2",
            "material_digest": material_digest,
            "input_method_digest": expected_method_digest,
            "source_projection_digest": expected_projection_digest,
            "rule": deepcopy(rule),
            "required_part_ids": closure,
        }
        packets.append(
            {
                "rule": deepcopy(rule),
                "required_part_ids": closure,
                "semantic_input_digest": digest(semantic),
            }
        )
    metadata = {
        "version": "package-technical-input/2",
        "source_projection_digest": expected_projection_digest,
        "input_method_digest": expected_method_digest,
        "material": material,
        "material_digest": material_digest,
        "rule_packets": packets,
        "physical_page_count": len(pages),
        "image_count": len(pages) + len(details),
        "asset_byte_count": sum(len(raw) for raw in blobs.values()),
        "pixel_count": sum(
            row["asset"]["width"] * row["asset"]["height"] for row in pages + details
        ),
        "text_byte_count": sum(len(row["text"].encode("utf-8")) for row in catalog.values()),
        "all_projected_material_retained": True,
        **{
            key: False
            for key in (
                "input_authority_granted",
                "original_bytes_reverified",
                "visual_readability_verified",
                "historical_byte_existence_verified",
                "provider_payload_verified",
                "execution_authorized",
                "formal_prediction_eligible",
                "training_eligible",
            )
        },
    }
    metadata["digest"] = digest(metadata)
    if len(canonical(metadata)) > MAX_METADATA_BYTES:
        fail("TECHNICAL_INPUT_METADATA_LIMIT")
    if not Draft202012Validator(contract.output_schema(), format_checker=FormatChecker()).is_valid(
        metadata
    ):
        fail("TECHNICAL_INPUT_OUTPUT_INVALID")
    return TechnicalInputBundle(metadata, dict(blobs))
