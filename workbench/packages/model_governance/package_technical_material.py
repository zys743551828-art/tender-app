"""Complete multi-source context and reference binding, with no authority grant.

Native acquisition belongs to current_material; this layer validates and retains
its exact owned material. A hash or Python object is never native authorization.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts import package_technical_material as contract
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_technical_assets as assets
from packages.model_governance.technical_png import digest_bytes

MAX_IMAGES = 384
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_CONTEXT_BYTES = 12 * 1024 * 1024
MAX_RULES = 400


class MaterialInputError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise MaterialInputError("MATERIAL_INPUT_" + code)


@dataclass(frozen=True, repr=False)
class MaterialContext:
    metadata: dict
    origin: current.CurrentMaterial


@dataclass(frozen=True, repr=False)
class MaterialInput:
    metadata: dict
    context: MaterialContext


@dataclass(frozen=True)
class _ParseRecords:
    documents: list[dict]


def descriptor():
    return {
        "version": "package-technical-material-method/3",
        "source_digest": digest_bytes(Path(__file__).read_bytes()),
        "contract_source_digest": digest_bytes(Path(contract.__file__).read_bytes()),
        "current_material_method_digest": current.method_digest(),
        "asset_verifier_source_digest": digest_bytes(Path(assets.__file__).read_bytes()),
        "png_codec_source_digest": digest_bytes(
            Path(assets.__file__).with_name("technical_png.py").read_bytes()
        ),
        "binding_schema_digest": digest(contract.binding_schema()),
        "limits": [MAX_IMAGES, MAX_TEXT_BYTES, MAX_CONTEXT_BYTES, MAX_RULES],
        "authority_grants": False,
    }


def method_digest():
    return digest(descriptor())


def context_method_digest():
    return digest(
        {"version": "package-technical-material-context-method/3", "method": descriptor()}
    )


def _sha(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and value != "0" * 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _checked_origin(origin, expected_observation_digest, expected_material_digest):
    if type(origin) is not current.CurrentMaterial:
        fail("ORIGIN_INVALID")
    m = deepcopy(origin.material)
    meta = origin.metadata
    try:
        if (
            meta["version"] != "package-current-material-observation/1"
            or meta["method_digest"] != current.method_digest()
            or meta["digest"] != expected_observation_digest
            or digest({k: v for k, v in meta.items() if k != "digest"})
            != expected_observation_digest
            or meta["material_digest"] != expected_material_digest
            or digest(m) != expected_material_digest
            or m["version"] != "package-current-material-projection/1"
            or m["scope"]["digest"] != meta["scope_digest"]
            or digest(m["scope"]["manifest"]) != meta["scope_digest"]
            or m["scope"]["manifest"]["id"] != meta["scope_id"]
        ):
            fail("ORIGIN_DIGEST_MISMATCH")
        if any(
            meta[k] is not False
            for k in (
                "input_authority_granted",
                "execution_authorized",
                "necessary_scope_verified",
                "historical_existence_verified",
            )
        ):
            fail("ORIGIN_AUTHORITY_INVALID")
        if len(canonical(m)) > current.MAX_MATERIAL_BYTES:
            fail("MATERIAL_LIMIT")
        expected = current._expected({"scope": m["scope"]})
        if (
            not 1 <= len(expected) <= 32
            or sum(row["page_count"] for row in expected) > current.MAX_PAGES
        ):
            fail("DOCUMENT_PAGE_LIMIT")
        native = m["native_documents"]
        if len(native) != len(expected) or {r["document_version_id"] for r in native} != {
            r["document_version_id"] for r in expected
        }:
            fail("DOCUMENT_SET_MISMATCH")
        for row, identity in zip(
            sorted(native, key=lambda d: d["document_version_id"]), expected, strict=True
        ):
            if (
                any(row[k] != v for k, v in identity.items())
                or digest(
                    {
                        "identity_version": "package-parse-evidence/1",
                        "parse_run_id": row["parse_run_id"],
                        "pages": row["pages"],
                        "blocks": row["blocks"],
                    }
                )
                != row["parse_digest"]
            ):
                fail("PARSE_MISMATCH")
        current._check_frozen({"scope": m["scope"]}, _ParseRecords(native))
        preview = m["scope"]["manifest"]["preview"]
        if (
            digest(preview["manifest"]) != preview["digest"]
            or preview["manifest"]["scope"]["bid_id"] != meta["bid_id"]
            or any(
                digest(m[key]["manifest"]) != m[key]["digest"]
                for key in ("target", "authority", "inventory")
            )
        ):
            fail("PACKAGE_DIGEST_MISMATCH")
        basis = preview["manifest"]["basis"]
        if (
            basis["package_digest"] != m["target"]["digest"]
            or basis["authority_digest"] != m["authority"]["digest"]
            or basis["inventory_digest"] != m["inventory"]["digest"]
            or basis["identity_digest"] != m["current_identity"]["digest"]
        ):
            fail("PACKAGE_BINDING_MISMATCH")
        pending = [m]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if set(value) & {
                    "object_key",
                    "locator",
                    "signed_url",
                    "api_key",
                    "access_key",
                    "secret_key",
                }:
                    fail("PRIVATE_FIELD_REJECTED")
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        files = m["scope"]["manifest"]["original_verification"]["files"]
        if (
            not 1 <= len(files) <= 32
            or any(not 1 <= row["byte_size"] <= 32 * 1024 * 1024 for row in files)
            or sum(row["byte_size"] for row in files) > 64 * 1024 * 1024
        ):
            fail("ORIGINAL_LIMIT")
        if set(origin.originals) != {r["document_version_id"] for r in files}:
            fail("ORIGINAL_SET_MISMATCH")
        for row in files:
            raw = origin.originals[row["document_version_id"]]
            if (
                type(raw) is not bytes
                or len(raw) != row["byte_size"]
                or digest_bytes(raw) != row["digest"]
            ):
                fail("ORIGINAL_BYTES_MISMATCH")
        if set(origin.page_bundles) != {r["document_version_id"] for r in expected} or set(
            m["page_asset_manifests"]
        ) != set(origin.page_bundles):
            fail("ASSET_SET_MISMATCH")
    except MaterialInputError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        fail("ORIGIN_INVALID")
    return m, expected


def _catalog(origin, material, documents):
    pages, evidence = [], []
    blobs: dict[str, bytes] = {}
    total_pixels = total_bytes = text_bytes = 0
    native = {r["document_version_id"]: r for r in material["native_documents"]}
    for doc in documents:
        key = doc["document_version_id"]
        bundle = origin.page_bundles[key]
        manifest, content = assets.verify_bundle(
            bundle, expected_manifest_digest=material["page_asset_manifests"][key]["digest"]
        )
        if canonical(manifest) != canonical(material["page_asset_manifests"][key]) or any(
            manifest[k] != doc[k]
            for k in ("document_version_id", "source_digest", "source_byte_size", "page_count")
        ):
            fail("ASSET_BINDING_MISMATCH")
        current._check_page_geometry(manifest, native[key]["pages"])
        if set(blobs) & set(content):
            fail("ASSET_ID_REUSED")
        blobs.update(content)
        full = {r["physical_page"]: r["asset"] for r in manifest["pages"]}
        for kind, rows in (("full_page", manifest["pages"]), ("detail", manifest["details"])):
            for row in rows:
                pages.append(
                    {
                        "document_version_id": key,
                        "parse_run_id": doc["parse_run_id"],
                        "kind": kind,
                        **row,
                    }
                )
                total_pixels += row["asset"]["width"] * row["asset"]["height"]
        total_bytes += sum(len(raw) for raw in content.values())
        for block in native[key]["blocks"]:
            image = full[block["physical_page"]]
            if digest_bytes(block["text_content"].encode()) != block["digest"]:
                fail("TEXT_MISMATCH")
            text_bytes += len(block["text_content"].encode())
            evidence.append(
                {
                    "document_version_id": key,
                    "parse_run_id": doc["parse_run_id"],
                    **block,
                    "page_image_digest": image["sha256"],
                    "page_width": image["width"],
                    "page_height": image["height"],
                }
            )
    if (
        len(pages) > MAX_IMAGES
        or total_pixels > current.MAX_TOTAL_PIXELS
        or total_bytes > current.MAX_ASSET_BYTES
        or text_bytes > MAX_TEXT_BYTES
    ):
        fail("CAPACITY_LIMIT")
    if len({e["id"] for e in evidence}) != len(evidence):
        fail("EVIDENCE_ID_REUSED")
    return pages, blobs, evidence


def _rules(material, evidence):
    preview = material["scope"]["manifest"]["preview"]["manifest"]
    rules = preview["rules"]
    if not 1 <= len(rules) <= MAX_RULES or len({r["rule_id"] for r in rules}) != len(rules):
        fail("RULE_SET_INVALID")
    catalog = {e["id"]: e for e in evidence}
    authority = {
        (d["member_id"], d["document_version_id"], d["parse"]["parse_run_id"])
        for d in preview["documents"]
        if d["package_role"] == "authority"
    }
    parts = {r["part"]["part_id"]: r for r in preview["parts"]}
    if len(parts) != len(preview["parts"]):
        fail("PART_ID_REUSED")
    result = []
    for rule in rules:
        snapshot = rule["rule_snapshot"]
        if digest(snapshot) != rule["rule_digest"] or snapshot["id"] != rule["rule_id"]:
            fail("RULE_DIGEST_MISMATCH")
        sources = rule["source_evidence"]
        complete = {r["evidence_id"] for r in sources} == set(snapshot["evidence_ids"]) and bool(
            sources
        )
        if (rule["selection"] == "include" and not complete) or not {
            r["evidence_id"] for r in sources
        } <= set(snapshot["evidence_ids"]):
            fail("RULE_SOURCES_INCOMPLETE")
        for ref in sources:
            actual = catalog.get(ref["evidence_id"])
            if (
                actual is None
                or (ref["member_id"], ref["document_version_id"], ref["parse_run_id"])
                not in authority
                or any(
                    ref[k] != actual[a]
                    for k, a in [
                        ("document_version_id", "document_version_id"),
                        ("parse_run_id", "parse_run_id"),
                        ("physical_page", "physical_page"),
                        ("evidence_digest", "digest"),
                        ("text_content", "text_content"),
                    ]
                )
            ):
                fail("RULE_SOURCE_MISMATCH")
            frozen = next(
                d
                for d in preview["documents"]
                if d["package_role"] == "authority"
                and d["member_id"] == ref["member_id"]
                and d["document_version_id"] == ref["document_version_id"]
            )
            if ref["file_digest"] != frozen["file_digest"]:
                fail("RULE_SOURCE_MISMATCH")
        if rule["selection"] == "include" and (
            not rule["part_ids"] or any(key not in parts for key in rule["part_ids"])
        ):
            fail("RULE_PARTS_INVALID")
        if len(snapshot["bands"]) > 100:
            fail("BAND_LIMIT")
        bands = [
            {
                "band_id": f"band/{index}/{digest(value)}",
                "ordinal": index,
                "source": deepcopy(value),
            }
            for index, value in enumerate(snapshot["bands"], 1)
        ]
        result.append(
            {
                "rule_id": rule["rule_id"],
                "frozen_rule": deepcopy(rule),
                "bands": bands,
                "required_part_ids": list(rule["part_ids"]),
                "selection": rule["selection"],
                "source_coverage": "complete" if complete else "incomplete",
            }
        )
    return result


def build_context(
    origin,
    *,
    expected_observation_digest,
    expected_material_digest,
    expected_method_digest,
    provider_profile_digest,
    judgment_method_digest,
    input_as_of,
):
    if expected_method_digest != context_method_digest():
        fail("CONTEXT_METHOD_MISMATCH")
    if not _sha(provider_profile_digest) or not _sha(judgment_method_digest):
        fail("PROFILE_METHOD_INVALID")
    valid = False
    try:
        valid = (
            isinstance(input_as_of, str)
            and len(input_as_of) <= 40
            and datetime.fromisoformat(input_as_of.replace("Z", "+00:00")).tzinfo is not None
        )
    except (ValueError, TypeError):
        pass
    if not valid:
        fail("TIME_INVALID")
    frozen_origin = deepcopy(origin)
    material, documents = _checked_origin(
        frozen_origin, expected_observation_digest, expected_material_digest
    )
    pages, blobs, evidence = _catalog(frozen_origin, material, documents)
    rules = _rules(material, evidence)
    meta = {
        "version": "package-technical-material-context/3",
        "source_observation_digest": expected_observation_digest,
        "source_material_digest": expected_material_digest,
        "context_method_digest": expected_method_digest,
        "provider_profile_digest": provider_profile_digest,
        "judgment_method_digest": judgment_method_digest,
        "input_as_of": input_as_of,
        "bid_id": frozen_origin.metadata["bid_id"],
        "scope_id": frozen_origin.metadata["scope_id"],
        "scope_digest": frozen_origin.metadata["scope_digest"],
        "material": material,
        "evidence_catalog": evidence,
        "images": pages,
        "rules": rules,
        "originals_digest": digest(
            {k: digest_bytes(v) for k, v in sorted(frozen_origin.originals.items())}
        ),
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
    }
    if len(canonical(meta)) > MAX_CONTEXT_BYTES:
        fail("CONTEXT_LIMIT")
    return MaterialContext(meta | {"digest": digest(meta)}, frozen_origin)


def verify_context(context, expected_digest):
    if type(context) is not MaterialContext or context.metadata.get("digest") != expected_digest:
        fail("CONTEXT_MISMATCH")
    m = deepcopy(context.metadata)
    try:
        rebuilt = build_context(
            context.origin,
            expected_observation_digest=m["source_observation_digest"],
            expected_material_digest=m["source_material_digest"],
            expected_method_digest=m["context_method_digest"],
            provider_profile_digest=m["provider_profile_digest"],
            judgment_method_digest=m["judgment_method_digest"],
            input_as_of=m["input_as_of"],
        )
        if canonical(rebuilt.metadata) != canonical(m):
            fail("CONTEXT_MISMATCH")
    except (KeyError, TypeError, UnicodeError, RecursionError):
        fail("CONTEXT_MISMATCH")
    return rebuilt


def bind_input(
    context, binding, *, expected_context_digest, expected_binding_digest, expected_method_digest
):
    if expected_method_digest != method_digest():
        fail("METHOD_MISMATCH")
    verified = verify_context(context, expected_context_digest)
    binding = deepcopy(binding)
    try:
        if (
            not Draft202012Validator(
                contract.binding_schema(), format_checker=FormatChecker()
            ).is_valid(binding)
            or digest(binding) != expected_binding_digest
            or binding["context_digest"] != expected_context_digest
            or binding["context_method_digest"] != context_method_digest()
        ):
            fail("BINDING_REFERENCE_MISMATCH")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        fail("BINDING_REFERENCE_MISMATCH")
    meta = {
        "version": "package-technical-material-input/3",
        "context_digest": expected_context_digest,
        "input_method_digest": expected_method_digest,
        "binding_reference": deepcopy(binding),
        "binding_reference_digest": expected_binding_digest,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
    }
    return MaterialInput(meta | {"digest": digest(meta)}, verified)


def verify_input(bundle, expected_digest):
    if type(bundle) is not MaterialInput or bundle.metadata.get("digest") != expected_digest:
        fail("INPUT_MISMATCH")
    m = deepcopy(bundle.metadata)
    rebuilt = bind_input(
        bundle.context,
        m["binding_reference"],
        expected_context_digest=m["context_digest"],
        expected_binding_digest=m["binding_reference_digest"],
        expected_method_digest=m["input_method_digest"],
    )
    if canonical(m) != canonical(rebuilt.metadata):
        fail("INPUT_MISMATCH")
    return rebuilt
