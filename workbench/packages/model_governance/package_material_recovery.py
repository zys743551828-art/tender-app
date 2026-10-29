"""Exact archived context recovery with fresh native facts, never a send lease.

The immutable envelope retains the original acquisition observation separately.
Fresh observations stay in a new receipt and never rewrite frozen context time.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_current_original as locator
from packages.model_governance import package_current_original_set as originals
from packages.model_governance import package_current_parse_material as parses
from packages.model_governance import package_current_scope as scope
from packages.model_governance import package_material_archive as archive
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import PrivateContentStore, is_digest, sha

MAX_OBSERVATION_BYTES = 2 * 1024 * 1024


class MaterialRecoveryError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise MaterialRecoveryError("MATERIAL_RECOVERY_" + code)


@dataclass(frozen=True, repr=False)
class RecoveredContext:
    context: material.MaterialContext
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "package-native-material-recovery-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "archive_method": archive.method_digest(),
            "context_method": material.context_method_digest(),
            "current_material_method": current.method_digest(),
            "current_parse_method": parses.method_digest(),
            "current_scope_method": scope.method_digest(),
            "current_original_set_method": originals.method_digest(),
            "current_locator_method": locator.method_digest(),
            "maximum_observation_bytes": MAX_OBSERVATION_BYTES,
            "authority_grants": False,
        }
    )


def save(store: PrivateContentStore, context, *, expected_context_digest, expected_method_digest):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    checked = material.verify_context(context, expected_context_digest)
    raw = canonical(checked.origin.metadata)
    if not 1 <= len(raw) <= MAX_OBSERVATION_BYTES:
        fail("OBSERVATION_LIMIT")
    # The existing archive contract/method remains unchanged.
    content_commit = archive.save(store, checked, expected_context_digest=expected_context_digest)
    observation_key = store.put_object(raw)
    if store.get_object(observation_key) != raw:
        fail("OBSERVATION_MISMATCH")
    envelope = {
        "version": "package-native-material-recovery/1",
        "method_digest": method,
        "context_digest": expected_context_digest,
        "material_commit_digest": content_commit,
        "observation_object": {"sha256": observation_key, "byte_size": len(raw)},
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
    }
    if method_digest() != method:
        fail("METHOD_CHANGED")
    return store.publish(canonical(envelope))


def _read(store, recovery_commit_digest, expected_context_digest):
    envelope = archive._decode(store.get_commit(recovery_commit_digest))
    expected = {
        "version",
        "method_digest",
        "context_digest",
        "material_commit_digest",
        "observation_object",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
    }
    if (
        set(envelope) != expected
        or envelope["version"] != "package-native-material-recovery/1"
        or envelope["method_digest"] != method_digest()
        or not is_digest(expected_context_digest)
        or envelope["context_digest"] != expected_context_digest
        or not is_digest(envelope["material_commit_digest"])
        or any(
            envelope[k] is not False
            for k in ("native_binding_verified", "input_authority_granted", "execution_authorized")
        )
    ):
        fail("ENVELOPE_INVALID")
    reference = envelope["observation_object"]
    if (
        type(reference) is not dict
        or set(reference) != {"sha256", "byte_size"}
        or not is_digest(reference["sha256"])
        or type(reference["byte_size"]) is not int
        or not 1 <= reference["byte_size"] <= MAX_OBSERVATION_BYTES
    ):
        fail("OBSERVATION_REFERENCE_INVALID")
    raw = store.get_object(reference["sha256"])
    if len(raw) != reference["byte_size"]:
        fail("OBSERVATION_MISMATCH")
    observation = archive._decode(raw)
    content = archive.load(
        store, envelope["material_commit_digest"], expected_context_digest=expected_context_digest
    )
    if (
        observation.get("digest") != content.context_metadata["source_observation_digest"]
        or digest({k: v for k, v in observation.items() if k != "digest"})
        != observation.get("digest")
        or observation.get("material_digest") != content.context_metadata["source_material_digest"]
    ):
        fail("OBSERVATION_MISMATCH")
    return envelope, content, observation


def _compare(facts, native, content, observation):
    frozen = content.context_metadata["material"]
    if canonical(
        {k: facts[k] for k in ("scope", "target", "authority", "inventory", "current_identity")}
    ) != canonical(
        {k: frozen[k] for k in ("scope", "target", "authority", "inventory", "current_identity")}
    ):
        fail("CURRENT_SCOPE_CHANGED")
    current._check_frozen(facts, native)
    if canonical(native.documents) != canonical(frozen["native_documents"]) or canonical(
        native.metadata["graph"]
    ) != canonical(observation["final_parse_observation"]["graph"]):
        fail("CURRENT_PARSE_OR_GRAPH_CHANGED")


async def restore(
    store: PrivateContentStore,
    scope_connection,
    original_connection,
    parse_connection,
    *,
    recovery_commit_digest,
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
    if len({id(c) for c in (scope_connection, original_connection, parse_connection)}) != 3:
        fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    current._idle((scope_connection, original_connection, parse_connection))
    envelope, content, observation = _read(store, recovery_commit_digest, expected_context_digest)
    meta = content.context_metadata
    if any(
        meta[k] != value
        for k, value in (
            ("bid_id", bid_id),
            ("scope_id", scope_id),
            ("scope_digest", expected_scope_digest),
        )
    ):
        fail("SCOPE_BINDING_MISMATCH")
    args = {"bid_id": bid_id, "scope_id": scope_id, "expected_scope_digest": expected_scope_digest}
    scope_method, parse_method = scope.method_digest(), parses.method_digest()
    initial = scope.observe(scope_connection, **args, expected_method_digest=scope_method)
    expected = current._expected(initial.metadata)
    before = parses.observe(
        parse_connection,
        bid_id=bid_id,
        expected_documents=expected,
        expected_method_digest=parse_method,
    )
    _compare(initial.metadata, before, content, observation)
    current._idle((scope_connection, original_connection, parse_connection))
    read = await originals.collect(
        scope_connection,
        original_connection,
        **args,
        expected_method_digest=originals.method_digest(),
        profile=profile,
        url_for_locator=url_for_locator,
        byte_client=byte_client,
    )
    after = parses.observe(
        parse_connection,
        bid_id=bid_id,
        expected_documents=expected,
        expected_method_digest=parse_method,
    )
    final = scope.observe(scope_connection, **args, expected_method_digest=scope_method)
    _compare(final.metadata, after, content, observation)
    if canonical(before.documents) != canonical(after.documents) or canonical(
        before.metadata["graph"]
    ) != canonical(after.metadata["graph"]):
        fail("NATIVE_FACTS_CHANGED")
    for receipt in read.metadata["files"]:
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
    frozen = deepcopy(meta["material"])
    bundles = {}
    for doc, manifest in frozen["page_asset_manifests"].items():
        asset_ids = [r["asset"]["id"] for r in [*manifest["pages"], *manifest["details"]]]
        bundles[doc] = assets.PageAssetBundle(
            deepcopy(manifest), {identity: content.image_blobs[identity] for identity in asset_ids}
        )
    origin = current.CurrentMaterial(deepcopy(observation), frozen, read.originals, bundles)
    restored = material.verify_context(
        material.MaterialContext(deepcopy(meta), origin), expected_context_digest
    )
    current._idle((scope_connection, original_connection, parse_connection))
    if method_digest() != method:
        fail("METHOD_CHANGED")
    receipt = {
        "version": "package-native-material-recovery-observation/1",
        "method_digest": method,
        "recovery_commit_digest": recovery_commit_digest,
        "material_commit_digest": envelope["material_commit_digest"],
        "context_digest": expected_context_digest,
        "original_source_observation_digest": observation["digest"],
        "fresh_initial_parse_digest": before.metadata["digest"],
        "fresh_final_parse_digest": after.metadata["digest"],
        "fresh_final_scope_digest": final.metadata["digest"],
        "fresh_original_set_digest": read.metadata["digest"],
        "observed_at": after.metadata["observed_at"],
        "exact_frozen_context_recovered": True,
        "current_native_parse_and_originals_rechecked": True,
        "page_assets_rerendered": False,
        "native_binding_verified": False,
        "necessary_scope_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    return RecoveredContext(restored, receipt | {"digest": digest(receipt)})
