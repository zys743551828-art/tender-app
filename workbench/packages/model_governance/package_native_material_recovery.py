"""Re-read exact native private evidence against fresh sources and originals.

Stored derivation statements remain statements. Restoring bytes does not replay
a renderer or construct a trusted live-derivation certificate or input grant.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

from deploy import fusion_context_derivation as derivation
from deploy import fusion_material_derivation as derivation_receipts
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_current_original as locator
from packages.model_governance import package_current_original_set as originals
from packages.model_governance import package_current_parse_material as parses
from packages.model_governance import package_current_scope as scope
from packages.model_governance import package_material_recovery as recovery_checks
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_native_material_store as store
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import is_digest, sha


class NativeMaterialRecoveryError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise NativeMaterialRecoveryError("NATIVE_MATERIAL_RECOVERY_" + code)


@dataclass(frozen=True, repr=False)
class RecoveredNativeEvidence:
    context: material.MaterialContext
    findings: findings.CheckedScopeFindings
    stored_record: store.NativeEvidenceRecord
    stored_derivation_claim: dict
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "package-native-material-evidence-recovery-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "store_method": store.method_digest(),
            "recovery_comparison_method": recovery_checks.method_digest(),
            "scope_method": scope.method_digest(),
            "parse_method": parses.method_digest(),
            "original_set_method": originals.method_digest(),
            "context_method": material.context_method_digest(),
            "review_method": review.method_digest(),
            "findings_method": findings.method_digest(),
            "derivation_claim_verifier_source": sha(Path(derivation.__file__).read_bytes()),
            "derivation_receipt_verifier_source": sha(
                Path(derivation_receipts.__file__).read_bytes()
            ),
            "qualification_granted": False,
        }
    )


def _check_stored_derivation(content, context):
    m = deepcopy(content.derivation_observation)
    p = content.record.metadata["document"]["packet"]
    if (
        m.get("version") != "fusion-exact-context-derivation/1"
        or not is_digest(m.get("method_digest"))
        or m.get("context_digest") != context.metadata["digest"]
        or m.get("digest") != p["derivation_observation_digest"]
        or m.get("frozen_material_digest") != context.metadata["source_material_digest"]
        or m.get("original_source_observation_digest")
        != context.metadata["source_observation_digest"]
    ):
        fail("STORED_DERIVATION_INVALID")
    for field in store.FLAGS | {
        "visual_readability_verified",
        "atomic_snapshot_verified",
        "send_lease_granted",
    }:
        if m.get(field) is not False:
            fail("STORED_DERIVATION_INVALID")
    links = m.get("document_manifest_links")
    docs = m.get("documents")
    pins = m.get("runtime")
    description = m.get("runtime_description_receipt")
    if (
        type(links) is not list
        or type(docs) is not list
        or type(pins) is not dict
        or set(pins) != {"image_id", "source_digest", "hard_timeout_ms"}
        or type(description) is not dict
    ):
        fail("STORED_DERIVATION_INVALID")
    manifests = {}
    for link in links:
        if type(link) is not dict or set(link) != {
            "document_version_id",
            "frozen_manifest_digest",
            "fresh_manifest",
            "stable_assets_digest",
            "actual_png_bytes_equal",
            "derivation_observation_times_retained_separately",
        }:
            fail("STORED_DERIVATION_INVALID")
        doc = link["document_version_id"]
        if (
            type(doc) is not str
            or doc not in context.origin.page_bundles
            or doc in manifests
            or type(link["fresh_manifest"]) is not dict
        ):
            fail("STORED_DERIVATION_INVALID")
        old = context.origin.page_bundles[doc]
        fresh = assets.PageAssetBundle(deepcopy(link["fresh_manifest"]), dict(old.blobs))
        if canonical(derivation._link_assets(doc, old, fresh)) != canonical(link):
            fail("STORED_DERIVATION_INVALID")
        manifests[doc] = fresh.manifest
    if (
        set(manifests) != set(context.origin.page_bundles)
        or len(docs) != len(manifests)
        or any(
            type(d) is not dict
            or set(d) != {"document_version_id", "manifest_digest", "receipt"}
            or type(d["receipt"]) is not dict
            for d in docs
        )
    ):
        fail("STORED_DERIVATION_INVALID")
    projection = deepcopy(context.metadata["material"])
    projection["page_asset_manifests"] = manifests
    observation = m.get("fresh_material_observation")
    if (
        type(observation) is not dict
        or observation.get("material_digest") != digest(projection)
        or m.get("fresh_material_digest") != digest(projection)
        or observation.get("digest")
        != digest({k: v for k, v in observation.items() if k != "digest"})
    ):
        fail("STORED_DERIVATION_INVALID")
    for field in ("bid_id", "scope_id", "scope_digest"):
        if observation.get(field) != context.metadata[field]:
            fail("STORED_DERIVATION_INVALID")
    actual = current.CurrentMaterial(
        observation,
        projection,
        context.origin.originals,
        {
            doc: assets.PageAssetBundle(
                manifests[doc], dict(context.origin.page_bundles[doc].blobs)
            )
            for doc in manifests
        },
    )
    _, checked = derivation_receipts._checked_receipts(
        actual, SimpleNamespace(receipts=[description, *[d["receipt"] for d in docs]]), pins
    )
    if canonical(checked) != canonical(docs):
        fail("STORED_DERIVATION_INVALID")
    return m


def _compare_current(facts, native, content):
    malformed = False
    try:
        recovery_checks._compare(facts, native, content, content.source_observation)
    except (KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
        malformed = True
    if malformed:
        fail("STORED_EVIDENCE_INVALID")


def _reconstruct(content, original_bytes):
    malformed = False
    try:
        meta = deepcopy(content.context_metadata)
        projection = deepcopy(meta["material"])
        bundles = {}
        for doc, manifest in projection["page_asset_manifests"].items():
            ids = [r["asset"]["id"] for r in [*manifest["pages"], *manifest["details"]]]
            bundles[doc] = assets.PageAssetBundle(
                deepcopy(manifest), {key: content.image_blobs[key] for key in ids}
            )
        origin = current.CurrentMaterial(
            deepcopy(content.source_observation), projection, original_bytes, bundles
        )
    except (KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
        malformed = True
    if malformed:
        fail("STORED_EVIDENCE_INVALID")
    return material.verify_context(material.MaterialContext(meta, origin), meta["digest"])


async def restore(
    store_connection,
    scope_connection,
    original_connection,
    parse_connection,
    *,
    store_command_id,
    expected_packet_digest,
    expected_storage_record_digest,
    expected_context_digest,
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
        fail("METHOD_MISMATCH")
    if any(
        not is_digest(v)
        for v in (
            expected_packet_digest,
            expected_storage_record_digest,
            expected_context_digest,
            expected_scope_digest,
        )
    ):
        fail("DIGEST_INVALID")
    connections = (store_connection, scope_connection, original_connection, parse_connection)
    if len({id(c) for c in connections}) != 4:
        fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    current._idle(connections)
    content = store.load(
        store_connection,
        bid_id=bid_id,
        command_id=store_command_id,
        expected_packet_digest=expected_packet_digest,
        expected_record_digest=expected_storage_record_digest,
        expected_method_digest=store.method_digest(),
    )
    meta = content.context_metadata
    if meta.get("digest") != expected_context_digest or any(
        meta.get(k) != v
        for k, v in (
            ("bid_id", bid_id),
            ("scope_id", scope_id),
            ("scope_digest", expected_scope_digest),
        )
    ):
        fail("CONTEXT_SCOPE_MISMATCH")
    args = {"bid_id": bid_id, "scope_id": scope_id, "expected_scope_digest": expected_scope_digest}
    scope_method, parse_method = scope.method_digest(), parses.method_digest()
    before_scope = scope.observe(scope_connection, **args, expected_method_digest=scope_method)
    expected = current._expected(before_scope.metadata)
    before = parses.observe(
        parse_connection,
        bid_id=bid_id,
        expected_documents=expected,
        expected_method_digest=parse_method,
    )
    _compare_current(before_scope.metadata, before, content)
    current._idle(connections)
    originals_read = await originals.collect(
        scope_connection,
        original_connection,
        **args,
        expected_method_digest=originals.method_digest(),
        profile=profile,
        url_for_locator=url_for_locator,
        byte_client=byte_client,
    )
    current._idle(connections)
    after = parses.observe(
        parse_connection,
        bid_id=bid_id,
        expected_documents=expected,
        expected_method_digest=parse_method,
    )
    final_scope = scope.observe(scope_connection, **args, expected_method_digest=scope_method)
    _compare_current(final_scope.metadata, after, content)
    if canonical(before.documents) != canonical(after.documents) or canonical(
        before.metadata["graph"]
    ) != canonical(after.metadata["graph"]):
        fail("NATIVE_FACTS_CHANGED")
    for receipt in originals_read.metadata["files"]:
        old = receipt["final_locator_observation"]
        located = locator.observe(
            original_connection,
            **args,
            document_version_id=old["document_version_id"],
            expected_original_digest=old["source_digest"],
            expected_method_digest=locator.method_digest(),
        )
        if originals._stable_locator(located) != canonical(
            {k: v for k, v in old.items() if k not in {"observed_at", "digest"}}
        ):
            fail("LOCATOR_CHANGED")
    restored = _reconstruct(content, originals_read.originals)
    plan = review.build(
        restored,
        expected_context_digest=expected_context_digest,
        expected_method_digest=review.method_digest(),
    )
    packet = content.record.metadata["document"]["packet"]
    if plan.metadata["digest"] != packet["review_digest"]:
        fail("STORED_REVIEW_MISMATCH")
    checked = findings.verify(
        findings.CheckedScopeFindings(deepcopy(content.findings_metadata), plan),
        expected_digest=packet["findings_digest"],
    )
    claim = _check_stored_derivation(content, restored)
    current._idle(connections)
    if method_digest() != method:
        fail("METHOD_CHANGED")
    metadata = {
        "version": "package-native-material-evidence-recovery/1",
        "method_digest": method,
        "storage_record_id": content.record.metadata["document"]["record_id"],
        "storage_record_digest": expected_storage_record_digest,
        "store_command_id": store_command_id,
        "store_packet_digest": expected_packet_digest,
        "context_digest": expected_context_digest,
        "original_source_observation_digest": meta["source_observation_digest"],
        "stored_findings_digest": packet["findings_digest"],
        "stored_derivation_observation_digest": packet["derivation_observation_digest"],
        "fresh_initial_parse_digest": before.metadata["digest"],
        "fresh_final_parse_digest": after.metadata["digest"],
        "fresh_final_scope_digest": final_scope.metadata["digest"],
        "fresh_original_set_digest": originals_read.metadata["digest"],
        "observed_at": after.metadata["observed_at"],
        "native_evidence_bytes_reloaded": True,
        "exact_frozen_context_recovered": True,
        "current_native_parse_and_originals_rechecked": True,
        "stored_scope_findings_revalidated": True,
        "stored_derivation_claim_consistent": True,
        "page_assets_rerendered": False,
        "trusted_derivation_freshly_verified": False,
        "actual_human_reading_verified": False,
        "all_findings_claimed_confirmed": checked.metadata["all_findings_claimed_confirmed"],
        "scope_changes_requested": checked.metadata["scope_changes_requested"],
        "necessary_scope_verified": False,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
        "atomic_snapshot_verified": False,
        "send_lease_granted": False,
    }
    return RecoveredNativeEvidence(
        restored, checked, content.record, claim, metadata | {"digest": digest(metadata)}
    )
