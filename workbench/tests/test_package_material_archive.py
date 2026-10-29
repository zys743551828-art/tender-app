"""Byte-consistent persistence, explicitly without native authority recovery."""
# ruff: noqa: F811

import os
from copy import deepcopy

import pytest
from test_package_technical_material import context, synthetic  # noqa: F401

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_archive as archive
from packages.storage import private_cas as cas


@pytest.fixture
def store(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX private filesystem required")
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    with cas.PrivateContentStore(root) as value:
        yield value


def frozen(synthetic):
    return context(synthetic)


def test_complete_context_and_all_images_survive_reopen(store, synthetic, tmp_path):
    value = frozen(synthetic)
    key = archive.save(store, value, expected_context_digest=value.metadata["digest"])
    store.close()
    with cas.PrivateContentStore(tmp_path / "private") as reopened:
        loaded = archive.load(reopened, key, expected_context_digest=value.metadata["digest"])
        assert (
            archive.save(reopened, value, expected_context_digest=value.metadata["digest"]) == key
        )
    assert loaded.context_metadata == value.metadata
    assert len(loaded.image_blobs) == len(value.metadata["images"]) == 3
    assert loaded.image_blobs == {
        k: v for b in value.origin.page_bundles.values() for k, v in b.blobs.items()
    }
    assert all(loaded.manifest[k] is False for k in archive.FLAGS)
    assert loaded.manifest["original_pdf_bytes_copied"] is False
    assert type(loaded) is archive.ArchivedMaterial
    assert not hasattr(loaded, "origin")
    assert "Synthetic" not in repr(loaded)
    assert len(list((tmp_path / "private" / "objects").iterdir())) == 3
    assert not {p.name for p in (tmp_path / "private" / "objects").iterdir()} & {
        cas.sha(raw) for raw in value.origin.originals.values()
    }


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_interrupted_dependency_writes_publish_no_commit(store, synthetic, monkeypatch, stage):
    value = frozen(synthetic)
    write = store.put_object
    calls = 0

    def interrupted(data):
        nonlocal calls
        calls += 1
        if calls == stage:
            raise cas.PrivateStoreError("synthetic interruption")
        return write(data)

    monkeypatch.setattr(store, "put_object", interrupted)
    published = []
    monkeypatch.setattr(store, "publish", lambda data: published.append(data))
    with pytest.raises(cas.PrivateStoreError, match="synthetic interruption"):
        archive.save(store, value, expected_context_digest=value.metadata["digest"])
    assert published == []


def test_prewrite_validation_and_independent_expected_context(store, synthetic, monkeypatch):
    value = frozen(synthetic)
    value.metadata["input_authority_granted"] = True
    writes = []
    monkeypatch.setattr(store, "put_object", lambda raw: writes.append(raw))
    with pytest.raises(ValueError, match="MATERIAL_INPUT_"):
        archive.save(store, value, expected_context_digest=value.metadata["digest"])
    assert writes == []


@pytest.mark.parametrize("mode", ["missing", "damaged"])
def test_missing_or_corrupt_page_cannot_restore(store, synthetic, tmp_path, mode):
    value = frozen(synthetic)
    key = archive.save(store, value, expected_context_digest=value.metadata["digest"])
    loaded = archive.load(store, key, expected_context_digest=value.metadata["digest"])
    image_key = loaded.manifest["images"][0]["sha256"]
    path = tmp_path / "private" / "objects" / image_key
    if mode == "missing":
        path.unlink()
    else:
        path.write_bytes(b"synthetic damaged")
    with pytest.raises(cas.PrivateStoreError):
        archive.load(store, key, expected_context_digest=value.metadata["digest"])


@pytest.mark.parametrize(
    "mutation",
    ["authority", "extra", "missing_image", "wrong_image", "false_zero", "wrong_context_size"],
)
def test_rehashed_manifest_does_not_bypass_archive_contract(store, synthetic, mutation):
    value = frozen(synthetic)
    key = archive.save(store, value, expected_context_digest=value.metadata["digest"])
    loaded = archive.load(store, key, expected_context_digest=value.metadata["digest"])
    m = deepcopy(loaded.manifest)
    if mutation == "authority":
        m["native_binding_verified"] = True
    elif mutation == "extra":
        m["locator"] = "synthetic forbidden path"
    elif mutation == "missing_image":
        m["images"].pop()
    elif mutation == "wrong_image":
        m["images"][0]["sha256"] = "a" * 64
    elif mutation == "false_zero":
        m["execution_authorized"] = 0
    else:
        m["context_object"]["byte_size"] += 1
    forged = store.publish(canonical(m))
    with pytest.raises(cas.PrivateStoreError):
        archive.load(store, forged, expected_context_digest=value.metadata["digest"])


def test_rehashed_context_cannot_replace_independently_pinned_digest(store, synthetic):
    value = frozen(synthetic)
    key = archive.save(store, value, expected_context_digest=value.metadata["digest"])
    loaded = archive.load(store, key, expected_context_digest=value.metadata["digest"])
    m = loaded.manifest
    changed = loaded.context_metadata
    changed["input_as_of"] = "2030-01-01T00:00:00Z"
    changed["digest"] = digest({k: v for k, v in changed.items() if k != "digest"})
    raw = canonical(changed)
    m["context_object"] = {"sha256": store.put_object(raw), "byte_size": len(raw)}
    forged = store.publish(canonical(m))
    with pytest.raises(cas.PrivateStoreError, match="CONTEXT_MISMATCH"):
        archive.load(store, forged, expected_context_digest=value.metadata["digest"])


def test_dependency_reread_failure_prevents_commit(store, synthetic, monkeypatch):
    value = frozen(synthetic)
    published = []
    monkeypatch.setattr(store, "publish", lambda raw: published.append(raw))
    monkeypatch.setattr(store, "get_object", lambda key: b"synthetic swapped content")
    with pytest.raises(cas.PrivateStoreError):
        archive.save(store, value, expected_context_digest=value.metadata["digest"])
    assert published == []


def test_corrupt_commit_and_wrong_expected_digest_rejected(store, synthetic, tmp_path):
    value = frozen(synthetic)
    key = archive.save(store, value, expected_context_digest=value.metadata["digest"])
    with pytest.raises(cas.PrivateStoreError, match="MANIFEST_INVALID"):
        archive.load(store, key, expected_context_digest="a" * 64)
    (tmp_path / "private" / "commits" / key).write_bytes(b"synthetic damaged commit")
    with pytest.raises(cas.PrivateStoreError, match="CONTENT_MISMATCH"):
        archive.load(store, key, expected_context_digest=value.metadata["digest"])
