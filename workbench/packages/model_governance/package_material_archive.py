"""Private context/page persistence; restoration is byte consistency only.

Original PDF bytes are deliberately not copied. Reloading does not construct an
authorized MaterialContext, re-observe current native facts, or grant execution.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_technical_material as material
from packages.storage import private_cas
from packages.storage.private_cas import PrivateContentStore, fail, is_digest, sha

MAX_TOTAL_BYTES = material.MAX_CONTEXT_BYTES + 64 * 1024 * 1024
FLAGS = {
    "native_binding_verified": False,
    "input_authority_granted": False,
    "execution_authorized": False,
    "current_native_facts_rechecked": False,
}


@dataclass(frozen=True, repr=False)
class ArchivedMaterial:
    manifest: dict
    context_metadata: dict
    image_blobs: dict[str, bytes]


@dataclass(frozen=True, repr=False)
class PreparedArchive:
    manifest: dict
    objects: dict[str, bytes]


def method_digest():
    return digest(
        {
            "version": "package-private-material-archive-method/1",
            "archive_source": sha(Path(__file__).read_bytes()),
            "store_source": sha(Path(private_cas.__file__).read_bytes()),
            "context_method_digest": material.context_method_digest(),
            "limits": [MAX_TOTAL_BYTES, private_cas.MAX_OBJECT_BYTES, private_cas.MAX_COMMIT_BYTES],
            "restoration_grants_authority": False,
        }
    )


def _decode(raw):
    result = None
    try:
        value = json.loads(raw)
        if type(value) is dict and canonical(value) == raw:
            result = value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    if result is None:
        fail("CANONICAL_JSON_INVALID")
    return result


def _images(context):
    rows = context.get("images")
    if type(rows) is not list or not 1 <= len(rows) <= material.MAX_IMAGES:
        fail("IMAGE_SET_INVALID")
    references = {}
    malformed = False
    try:
        for row in rows:
            asset = row["asset"]
            identity, key, size = asset["id"], asset["sha256"], asset["byte_size"]
            if (
                not is_digest(identity)
                or not is_digest(key)
                or type(size) is not int
                or not 1 <= size <= 32 * 1024 * 1024
                or identity in references
            ):
                fail("IMAGE_SET_INVALID")
            references[identity] = {"asset_id": identity, "sha256": key, "byte_size": size}
    except (KeyError, TypeError):
        malformed = True
    if malformed:
        fail("IMAGE_SET_INVALID")
    if sum(r["byte_size"] for r in references.values()) > 64 * 1024 * 1024:
        fail("IMAGE_LIMIT")
    return sorted(references.values(), key=lambda r: r["asset_id"])


def prepare(context, *, expected_context_digest):
    """Own and validate the complete snapshot before the first filesystem write."""
    verified = material.verify_context(context, expected_context_digest)
    metadata = deepcopy(verified.metadata)
    raw = canonical(metadata)
    images = _images(metadata)
    blobs = {
        identity: value
        for bundle in verified.origin.page_bundles.values()
        for identity, value in bundle.blobs.items()
    }
    # All validation completes before the first filesystem write.
    if set(blobs) != {r["asset_id"] for r in images}:
        fail("IMAGE_SET_INVALID")
    if (
        len(raw) > material.MAX_CONTEXT_BYTES
        or len(raw) + sum(len(b) for b in blobs.values()) > MAX_TOTAL_BYTES
    ):
        fail("ARCHIVE_LIMIT")
    for row in images:
        data = blobs[row["asset_id"]]
        if len(data) != row["byte_size"] or sha(data) != row["sha256"]:
            fail("CONTENT_MISMATCH")
    context_key = sha(raw)
    manifest = {
        "version": "package-private-material-archive/1",
        "archive_method_digest": method_digest(),
        "context_digest": expected_context_digest,
        "context_object": {"sha256": context_key, "byte_size": len(raw)},
        "images": images,
        "original_pdf_bytes_copied": False,
        **FLAGS,
    }
    objects = {context_key: raw}
    objects.update({row["sha256"]: blobs[row["asset_id"]] for row in images})
    return PreparedArchive(manifest, objects)


def save(store: PrivateContentStore, context, *, expected_context_digest):
    """Persist every dependency, re-read all, then publish the complete commit."""
    prepared = prepare(context, expected_context_digest=expected_context_digest)
    for key, raw in prepared.objects.items():
        if store.put_object(raw) != key:
            fail("CONTENT_MISMATCH")
    _load_objects(store, prepared.manifest, expected_context_digest)
    return store.publish(canonical(prepared.manifest))


def _load_objects(store, manifest, expected_context_digest):
    expected_keys = {
        "version",
        "archive_method_digest",
        "context_digest",
        "context_object",
        "images",
        "original_pdf_bytes_copied",
        *FLAGS,
    }
    if (
        set(manifest) != expected_keys
        or manifest["version"] != "package-private-material-archive/1"
        or not is_digest(manifest["archive_method_digest"])
        or not is_digest(expected_context_digest)
        or manifest["context_digest"] != expected_context_digest
        or manifest["original_pdf_bytes_copied"] is not False
        or any(manifest[k] is not False for k in FLAGS)
    ):
        fail("MANIFEST_INVALID")
    reference = manifest["context_object"]
    if (
        type(reference) is not dict
        or set(reference) != {"sha256", "byte_size"}
        or not is_digest(reference["sha256"])
        or type(reference["byte_size"]) is not int
        or not 1 <= reference["byte_size"] <= material.MAX_CONTEXT_BYTES
    ):
        fail("CONTEXT_REFERENCE_INVALID")
    raw = store.get_object(reference["sha256"])
    if len(raw) != reference["byte_size"]:
        fail("CONTENT_MISMATCH")
    metadata = _decode(raw)
    if (
        metadata.get("version") != "package-technical-material-context/3"
        or metadata.get("digest") != expected_context_digest
        or digest({k: v for k, v in metadata.items() if k != "digest"}) != expected_context_digest
        or any(metadata.get(k) is not False for k in FLAGS if k != "current_native_facts_rechecked")
    ):
        fail("CONTEXT_MISMATCH")
    images = _images(metadata)
    # Canonical comparison distinguishes False from integer zero.
    if canonical(images) != canonical(manifest["images"]):
        fail("IMAGE_SET_INVALID")
    blobs = {}
    for row in images:
        data = store.get_object(row["sha256"])
        if len(data) != row["byte_size"]:
            fail("CONTENT_MISMATCH")
        blobs[row["asset_id"]] = data
    return ArchivedMaterial(deepcopy(manifest), metadata, blobs)


def load(store: PrivateContentStore, commit_digest, *, expected_context_digest):
    """Caller supplies independently pinned commit/context digests; no 'latest'."""
    return _load_objects(store, _decode(store.get_commit(commit_digest)), expected_context_digest)
