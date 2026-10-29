"""Persist private checked claims, independently of review identity or decisions."""

from pathlib import Path

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_archive as archive
from packages.model_governance import package_material_scope_findings as findings
from packages.storage.private_cas import is_digest, sha

MAX_STORED_BYTES = findings.MAX_BYTES + 4096


def method_digest():
    return digest(
        {
            "version": "package-scope-findings-store-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "findings_method": findings.method_digest(),
            "archive_codec_and_private_store_method": archive.method_digest(),
            "maximum_stored_bytes": MAX_STORED_BYTES,
            "authority_grants": False,
        }
    )


def save(store, value, *, expected_findings_digest, expected_method_digest):
    method = method_digest()
    if expected_method_digest != method:
        findings.fail("STORE_METHOD_MISMATCH")
    checked = findings.verify(value, expected_digest=expected_findings_digest)
    raw = canonical(checked.metadata)
    if len(raw) > MAX_STORED_BYTES:
        findings.fail("STORE_BYTE_LIMIT")
    key = store.put_object(raw)
    if key != sha(raw) or store.get_object(key) != raw:
        findings.fail("STORE_CONTENT_MISMATCH")
    manifest = {
        "version": "package-scope-findings-object/1",
        "method_digest": method,
        "context_digest": checked.metadata["context_digest"],
        "review_digest": checked.metadata["review_digest"],
        "checked_findings_digest": expected_findings_digest,
        "object": {"sha256": key, "byte_size": len(raw)},
        "reviewer_identity_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
    }
    if method_digest() != method:
        findings.fail("STORE_METHOD_CHANGED")
    return store.publish(canonical(manifest))


def load(store, packet, *, commit_digest, expected_findings_digest, expected_method_digest):
    if expected_method_digest != method_digest():
        findings.fail("STORE_METHOD_MISMATCH")
    manifest = archive._decode(store.get_commit(commit_digest))
    keys = {
        "version",
        "method_digest",
        "context_digest",
        "review_digest",
        "checked_findings_digest",
        "object",
        "reviewer_identity_verified",
        "input_authority_granted",
        "execution_authorized",
    }
    if (
        set(manifest) != keys
        or manifest["version"] != "package-scope-findings-object/1"
        or manifest["method_digest"] != expected_method_digest
        or not is_digest(expected_findings_digest)
        or manifest["checked_findings_digest"] != expected_findings_digest
        or any(
            manifest[k] is not False
            for k in (
                "reviewer_identity_verified",
                "input_authority_granted",
                "execution_authorized",
            )
        )
    ):
        findings.fail("STORE_MANIFEST_INVALID")
    reference = manifest["object"]
    if (
        type(reference) is not dict
        or set(reference) != {"sha256", "byte_size"}
        or not is_digest(reference["sha256"])
        or type(reference["byte_size"]) is not int
        or not 1 <= reference["byte_size"] <= MAX_STORED_BYTES
    ):
        findings.fail("STORE_REFERENCE_INVALID")
    raw = store.get_object(reference["sha256"])
    if len(raw) != reference["byte_size"]:
        findings.fail("STORE_CONTENT_MISMATCH")
    metadata = archive._decode(raw)
    if any(metadata.get(k) != manifest[k] for k in ("context_digest", "review_digest")):
        findings.fail("STORE_BINDING_MISMATCH")
    checked = findings.verify(
        findings.CheckedScopeFindings(metadata, packet), expected_digest=expected_findings_digest
    )
    if method_digest() != expected_method_digest:
        findings.fail("STORE_METHOD_CHANGED")
    return checked
