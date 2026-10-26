"""Existing /3 synthetic raw material and responses through actual private persistence."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
import test_package_complete_features as cases
import test_package_technical_material as materials

from packages.domain.providers.deepseek_vision import VisionProviderError
from packages.domain.review_identity import canonical
from packages.model_governance import package_complete_features as features
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_technical_material as inputs
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import PrivateContentStore, PrivateStoreError


@pytest.fixture
def sample(tmp_path):
    bundle = materials.bound(deepcopy(materials.synthetic.__wrapped__()))
    attempts = [cases.attempt(bundle, slot) for slot in (1, 2, 3)]
    expected = {
        "expected_input_digest": bundle.metadata["digest"],
        "expected_binding_digest": bundle.metadata["binding_reference_digest"],
        "expected_feature_method_digest": features.method_digest(),
        "expected_handoff_method_digest": handoff.method_digest(),
    }
    root, index = tmp_path / "cas", tmp_path / "index"
    root.mkdir(mode=0o700)
    index.mkdir(mode=0o700)
    return bundle, attempts, expected, root, index


def command(expected, source):
    return expected | {
        "source_commit": source,
        "command_id": str(uuid4()),
        "origin": "synthetic_mechanism",
    }


def test_roundtrip_retains_exact_original_request_response_and_consumable_features(sample):
    bundle, attempts, expected, root, index = sample
    with PrivateContentStore(root) as store:
        source = handoff.save_source(store, bundle, attempts, **expected)
        args = command(expected, source)
        saved = handoff.freeze(store, index, **args)
        loaded = handoff.load(
            store, index, expected_artifact_digest=saved["artifact_digest"], **args
        )
        assert loaded.bundle.metadata == bundle.metadata
        assert loaded.bundle.context.origin.originals == bundle.context.origin.originals
        assert loaded.bundle.context.origin.page_bundles == bundle.context.origin.page_bundles
        assert loaded.attempts == attempts
        assert loaded.features == [cases.aggregate(bundle, attempts)]
        assert loaded.features[0]["training_eligible"] is False
        assert loaded.features[0]["formal_prediction"] is None
        assert handoff.freeze(store, index, **args)["replayed"]
        assert (
            handoff.reopen(store, index, expected_artifact_digest=saved["artifact_digest"], **args)[
                "rule_count"
            ]
            == 1
        )


@pytest.mark.parametrize(
    "field",
    [
        "expected_input_digest",
        "expected_binding_digest",
        "expected_feature_method_digest",
        "expected_handoff_method_digest",
    ],
)
def test_independent_identity_required_on_restore(sample, field):
    bundle, attempts, expected, root, _ = sample
    with PrivateContentStore(root) as store:
        source = handoff.save_source(store, bundle, attempts, **expected)
        with pytest.raises((GovernanceError, inputs.MaterialInputError)):
            handoff.load_source(store, source, **(expected | {field: "a" * 64}))


@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "unknown",
        "response",
        "model",
        "request",
        "original",
        "call",
        "partial_source",
        "generation_flags",
        "generation_content",
    ],
)
def test_invalid_material_or_three_slot_records_do_not_publish_source(sample, attack):
    bundle, attempts, expected, root, _ = sample
    if attack == "missing":
        attempts.pop()
    elif attack == "unknown":
        attempts[0] = replace(attempts[0], state="unknown", generation=None)
    elif attack == "response":
        attempts[0] = replace(
            attempts[0],
            generation=replace(attempts[0].generation, raw_response=b"malformed secret response"),
        )
    elif attack == "model":
        attempts[0] = replace(
            attempts[0], generation=replace(attempts[0].generation, model="other-model")
        )
    elif attack == "request":
        attempts[0] = replace(
            attempts[0], request=replace(attempts[0].request, body=attempts[0].request.body + b" ")
        )
    elif attack == "generation_flags":
        attempts[0] = replace(
            attempts[0], generation=replace(attempts[0].generation, formal_scoring_eligible=0)
        )
    elif attack == "generation_content":
        attempts[0] = replace(
            attempts[0], generation=replace(attempts[0].generation, content="forged parsed content")
        )
    elif attack == "original":
        key = next(iter(bundle.context.origin.originals))
        bundle.context.origin.originals[key] += b"corrupt"
    elif attack == "call":
        attempts[1] = replace(attempts[1], call_id=attempts[0].call_id)
    else:
        bundle.metadata["native_binding_verified"] = True
    with PrivateContentStore(root) as store:
        with pytest.raises(
            (GovernanceError, inputs.MaterialInputError, ValueError, VisionProviderError)
        ):
            handoff.save_source(store, bundle, attempts, **expected)
        assert not list((root / "commits").iterdir())
        assert not list((root / "objects").iterdir())


@pytest.mark.parametrize(
    "kind",
    [
        "original",
        "response",
        "request",
        "input",
        "scope",
        "extra",
        "duplicate",
        "size",
        "authority",
    ],
)
def test_resealed_storage_envelope_cannot_change_original_semantics(sample, kind):
    bundle, attempts, expected, root, _ = sample
    with PrivateContentStore(root) as store:
        source = handoff.save_source(store, bundle, attempts, **expected)
        packet = json.loads(store.get_commit(source))
        if kind == "original":
            packet["originals"][0]["object"] = {
                "sha256": store.put_object(b"not original"),
                "byte_size": 12,
            }
        elif kind == "response":
            packet["attempts"][0]["generation"]["raw_response"] = packet["attempts"][1][
                "generation"
            ]["raw_response"]
        elif kind == "request":
            packet["attempts"][0]["request_body"] = {
                "sha256": store.put_object(b"{}"),
                "byte_size": 2,
            }
        elif kind == "input":
            packet["input_digest"] = "a" * 64
        elif kind == "scope":
            packet["binding_digest"] = "a" * 64
        elif kind == "extra":
            packet["official_score"] = 99
        elif kind == "duplicate":
            packet["originals"].append(packet["originals"][0])
        elif kind == "size":
            packet["attempts"][0]["generation"]["raw_response"]["byte_size"] = 2 * 1024 * 1024
        else:
            packet["training_eligible"] = True
        tampered = store.publish(canonical(packet))
        with pytest.raises((GovernanceError, inputs.MaterialInputError, ValueError, KeyError)):
            handoff.load_source(store, tampered, **expected)


def test_concurrent_command_and_lost_ack_are_idempotent_and_conflict_is_rejected(sample):
    bundle, attempts, expected, root, index = sample
    with PrivateContentStore(root) as store:
        source = handoff.save_source(store, bundle, attempts, **expected)
    args = command(expected, source)

    def invoke(_):
        with PrivateContentStore(root) as store:
            return handoff.freeze(store, index, **args)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(invoke, range(3)))
    assert sum(not r["replayed"] for r in results) == 1
    assert len({r["artifact_digest"] for r in results}) == 1
    with PrivateContentStore(root) as store:
        assert handoff.freeze(store, index, **args)["replayed"]
        with pytest.raises(GovernanceError) as conflict:
            handoff.freeze(store, index, **(args | {"origin": "unqualified_research"}))
        assert conflict.value.code.endswith("COMMAND_CONFLICT")


@pytest.mark.parametrize("target", ["cas_root", "object", "index"])
def test_symlinks_are_not_followed(sample, tmp_path, target):
    bundle, attempts, expected, root, index = sample
    with PrivateContentStore(root) as store:
        source = handoff.save_source(store, bundle, attempts, **expected)
        args = command(expected, source)
        saved = handoff.freeze(store, index, **args)
    if target == "cas_root":
        link = tmp_path / "link"
        link.symlink_to(root, target_is_directory=True)
        with pytest.raises(PrivateStoreError):
            PrivateContentStore(link)
        return
    if target == "index":
        path = index / (args["command_id"] + ".json")
    else:
        packet = json.loads((root / "commits" / source).read_bytes())
        path = root / "objects" / packet["originals"][0]["object"]["sha256"]
    moved = tmp_path / "elsewhere"
    path.rename(moved)
    path.symlink_to(moved)
    with PrivateContentStore(root) as store:
        with pytest.raises((PrivateStoreError, OSError)):
            handoff.load(store, index, expected_artifact_digest=saved["artifact_digest"], **args)


def test_actual_research_cli_freezes_reads_and_rejects_downcast(sample):
    bundle, attempts, expected, root, index = sample
    with PrivateContentStore(root) as store:
        source = handoff.save_source(store, bundle, attempts, **expected)
    args = command(expected, source)
    flags = ["--material-store", str(root), "--artifact-dir", str(index)]
    for key, value in args.items():
        flags += ["--" + key.replace("_", "-"), value]

    def cli(*extra):
        return subprocess.run(
            [sys.executable, "deploy/package_history_worker.py", *extra, *flags],
            text=True,
            capture_output=True,
            timeout=30,
            env=os.environ | {"PRIVATE_SENTINEL": "must-not-inherit"},
        )

    saved = cli("--purpose", "complete-feature-freeze")
    assert saved.returncode == 0, saved.stdout + saved.stderr
    receipt = json.loads(saved.stdout)["result"]
    read = cli(
        "--purpose",
        "complete-feature-read",
        "--expected-artifact-digest",
        receipt["artifact_digest"],
    )
    assert read.returncode == 0, read.stdout + read.stderr
    assert json.loads(read.stdout)["result"]["training_eligible"] is False
    assert "Synthetic" not in saved.stdout + read.stdout
    assert cli("--purpose", "feature-freeze", "--projection", "unused").returncode == 2


@pytest.mark.parametrize(
    "limit", ["MAX_ATTEMPTS", "MAX_TOTAL_BYTES", "MAX_RESPONSE_BYTES", "MAX_REQUEST_BYTES"]
)
def test_budget_failure_precedes_source_publication(sample, monkeypatch, limit):
    bundle, attempts, expected, root, _ = sample
    monkeypatch.setattr(handoff, limit, 1)
    expected["expected_handoff_method_digest"] = handoff.method_digest()
    with PrivateContentStore(root) as store:
        with pytest.raises(GovernanceError):
            handoff.save_source(store, bundle, attempts, **expected)
        assert not list((root / "commits").iterdir())
        assert not list((root / "objects").iterdir())


def test_interrupted_source_write_does_not_publish_commit(sample, monkeypatch):
    bundle, attempts, expected, root, _ = sample
    with PrivateContentStore(root) as store:
        put = store.put_object
        count = 0

        def interrupted(raw):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("interrupted private write")
            return put(raw)

        with monkeypatch.context() as patch:
            patch.setattr(store, "put_object", interrupted)
            with pytest.raises(OSError):
                handoff.save_source(store, bundle, attempts, **expected)
        assert not list((root / "commits").iterdir())
        source = handoff.save_source(store, bundle, attempts, **expected)
        assert handoff.load_source(store, source, **expected).attempts == attempts


def test_publish_then_lost_ack_recovers_exact_command(sample, monkeypatch):
    bundle, attempts, expected, root, index = sample
    with PrivateContentStore(root) as store:
        source = handoff.save_source(store, bundle, attempts, **expected)
        args = command(expected, source)
        rename = os.rename

        def lost(*a, **kw):
            rename(*a, **kw)
            if a[1] == args["command_id"] + ".json":
                raise OSError("lost ACK")

        with monkeypatch.context() as patch:
            patch.setattr(handoff.os, "rename", lost)
            with pytest.raises(OSError):
                handoff.freeze(store, index, **args)
        assert handoff.freeze(store, index, **args)["replayed"]


def test_read_tampered_feature_object_never_yields_consumer_data(sample):
    bundle, attempts, expected, root, index = sample
    with PrivateContentStore(root) as store:
        source = handoff.save_source(store, bundle, attempts, **expected)
        args = command(expected, source)
        saved = handoff.freeze(store, index, **args)
        record = json.loads((index / (args["command_id"] + ".json")).read_bytes())
        path = root / "objects" / record["features_object"]["sha256"]
        path.write_bytes(b"forged private features")
        with pytest.raises(PrivateStoreError):
            handoff.load(store, index, expected_artifact_digest=saved["artifact_digest"], **args)


def test_prepare_owns_receipts_before_caller_mutates_them(sample, monkeypatch):
    bundle, attempts, expected, root, _ = sample
    original = deepcopy(attempts)
    prepare = handoff.archive.prepare

    def mutate_caller_after_validation(*args, **kwargs):
        attempts[0].request.receipt["rule_id"] = str(uuid4())
        attempts[0].generation.data["reason"] = "caller changed after validation"
        return prepare(*args, **kwargs)

    with PrivateContentStore(root) as store:
        with monkeypatch.context() as patch:
            patch.setattr(handoff.archive, "prepare", mutate_caller_after_validation)
            source = handoff.save_source(store, bundle, attempts, **expected)
        loaded = handoff.load_source(store, source, **expected)
        assert loaded.attempts == original
        assert loaded.attempts != attempts
