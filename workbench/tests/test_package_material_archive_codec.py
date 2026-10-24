"""Cross-platform archive encoding only; no filesystem or native qualification."""
# ruff: noqa: F811

from copy import deepcopy

import pytest
from test_package_technical_material import context, synthetic  # noqa: F401

from packages.domain.review_identity import canonical
from packages.model_governance import package_material_archive as archive
from packages.storage import private_cas as cas


def test_prepare_owns_complete_context_without_original_pdf_copy(synthetic):
    value = context(synthetic)
    prepared = archive.prepare(value, expected_context_digest=value.metadata["digest"])
    manifest = prepared.manifest
    assert manifest["archive_method_digest"] == archive.method_digest()
    assert len(manifest["images"]) == 3
    # Distinct page identities may share bytes; retain all references, dedupe only objects.
    assert len(prepared.objects) == 1 + len({r["sha256"] for r in manifest["images"]}) == 3
    assert all(cas.sha(raw) == key for key, raw in prepared.objects.items())
    assert set(prepared.objects).isdisjoint(cas.sha(raw) for raw in value.origin.originals.values())
    raw = prepared.objects[manifest["context_object"]["sha256"]]
    assert raw == canonical(value.metadata)
    value.metadata["rules"].clear()
    assert prepared.objects[manifest["context_object"]["sha256"]] == raw
    assert manifest["original_pdf_bytes_copied"] is False
    assert all(manifest[k] is False for k in archive.FLAGS)


@pytest.mark.parametrize(
    "raw", [b"{} ", b'{"a":1,"a":2}', b'{"a":1.0}', b"[]", b"null", b"invalid", b'{"a":NaN}']
)
def test_decode_requires_exact_canonical_object(raw):
    with pytest.raises(cas.PrivateStoreError, match="CANONICAL_JSON_INVALID"):
        archive._decode(raw)


@pytest.mark.parametrize("mutation", ["duplicate", "bool_size", "huge", "zero_digest", "empty"])
def test_image_reference_contract_is_closed(synthetic, mutation):
    value = deepcopy(context(synthetic).metadata)
    if mutation == "duplicate":
        value["images"].append(deepcopy(value["images"][0]))
    elif mutation == "bool_size":
        value["images"][0]["asset"]["byte_size"] = True
    elif mutation == "huge":
        value["images"][0]["asset"]["byte_size"] = 32 * 1024 * 1024 + 1
    elif mutation == "zero_digest":
        value["images"][0]["asset"]["sha256"] = "0" * 64
    else:
        value["images"].clear()
    with pytest.raises(cas.PrivateStoreError):
        archive._images(value)


def test_windows_backend_fails_closed_before_touching_root(monkeypatch):
    monkeypatch.setattr(cas.os, "name", "nt")
    with pytest.raises(cas.PrivateStoreError, match="POSIX_REQUIRED"):
        cas.PrivateContentStore("synthetic unprovisioned root")
