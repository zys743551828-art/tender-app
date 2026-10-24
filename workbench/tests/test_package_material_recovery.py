"""Recovery envelope encoding only; fake store does not grant native authority."""
# ruff: noqa: F811

from copy import deepcopy

import pytest
from test_package_technical_material import context, synthetic  # noqa: F401

from packages.domain.review_identity import canonical
from packages.model_governance import package_material_recovery as recovery
from packages.storage.private_cas import sha


class MemoryStore:
    """Test-only codec port. Actual filesystem is tested separately on Linux."""

    def __init__(self):
        self.objects = {}
        self.commits = {}

    def put_object(self, raw):
        self.objects[sha(raw)] = raw
        return sha(raw)

    def publish(self, raw):
        self.commits[sha(raw)] = raw
        return sha(raw)

    def get_object(self, key):
        return self.objects[key]

    def get_commit(self, key):
        return self.commits[key]


def saved(synthetic):
    ctx = context(synthetic)
    store = MemoryStore()
    key = recovery.save(
        store,
        ctx,
        expected_context_digest=ctx.metadata["digest"],
        expected_method_digest=recovery.method_digest(),
    )
    return store, ctx, key


def test_observation_is_separate_and_retains_original_frozen_context(synthetic):
    store, ctx, key = saved(synthetic)
    envelope, content, observation = recovery._read(store, key, ctx.metadata["digest"])
    assert content.context_metadata == ctx.metadata
    assert observation == ctx.origin.metadata
    assert envelope["observation_object"]["sha256"] == sha(canonical(ctx.origin.metadata))
    assert len(store.commits) == 2 and len(store.objects) == 4
    assert sha(canonical(observation)) != observation["digest"]
    assert all(
        envelope[k] is False
        for k in ("native_binding_verified", "input_authority_granted", "execution_authorized")
    )
    assert "Synthetic" not in repr(content)


@pytest.mark.parametrize(
    "mutation", ["context", "method", "extra", "true", "zero", "size", "missing", "reference"]
)
def test_rehashed_envelope_cannot_bypass_binding_contract(synthetic, mutation):
    store, ctx, key = saved(synthetic)
    envelope, _, _ = recovery._read(store, key, ctx.metadata["digest"])
    if mutation == "context":
        envelope["context_digest"] = "a" * 64
    elif mutation == "method":
        envelope["method_digest"] = "a" * 64
    elif mutation == "extra":
        envelope["locator"] = "synthetic path"
    elif mutation == "true":
        envelope["native_binding_verified"] = True
    elif mutation == "zero":
        envelope["execution_authorized"] = 0
    elif mutation == "size":
        envelope["observation_object"]["byte_size"] += 1
    elif mutation == "missing":
        del envelope["observation_object"]
    else:
        envelope["observation_object"]["byte_size"] = True
    changed = store.publish(canonical(envelope))
    with pytest.raises(recovery.MaterialRecoveryError):
        recovery._read(store, changed, ctx.metadata["digest"])


def test_substituted_rehashed_observation_is_not_frozen_observation(synthetic):
    store, ctx, key = saved(synthetic)
    envelope, _, observation = recovery._read(store, key, ctx.metadata["digest"])
    changed = deepcopy(observation)
    changed["document_count"] = changed.get("document_count", 0) + 1
    raw = canonical(changed)
    envelope["observation_object"] = {"sha256": store.put_object(raw), "byte_size": len(raw)}
    forged = store.publish(canonical(envelope))
    with pytest.raises(recovery.MaterialRecoveryError, match="OBSERVATION_MISMATCH"):
        recovery._read(store, forged, ctx.metadata["digest"])


@pytest.mark.parametrize("failure", ["method", "context"])
def test_save_rejects_before_any_write(synthetic, failure):
    ctx = context(synthetic)
    store = MemoryStore()
    with pytest.raises(ValueError):
        recovery.save(
            store,
            ctx,
            expected_context_digest="a" * 64 if failure == "context" else ctx.metadata["digest"],
            expected_method_digest="a" * 64 if failure == "method" else recovery.method_digest(),
        )
    assert not store.objects and not store.commits
