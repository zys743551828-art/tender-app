"""Synthetic local persistence and real isolated launcher; no native or model authority."""

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
import test_package_technical_features as cases

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_feature_handoff as handoff
from packages.model_governance import package_technical_features as features
from packages.model_governance.common import GovernanceError


@pytest.fixture
def material(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    projection = cases.projection.__wrapped__()
    expected = {
        "command_id": str(uuid4()),
        "origin": "synthetic_mechanism",
        "expected_projection_digest": digest(projection),
        "expected_binding_digest": digest(projection["binding"]),
        "expected_feature_method_digest": features.method_digest(),
        "expected_handoff_method_digest": handoff.method_digest(),
    }
    return root, projection, expected


def test_freeze_reopen_and_lost_ack_replay_preserve_exact_bytes(material):
    root, projection, expected = material
    result = handoff.freeze(root, projection, **expected)
    path = root / (expected["command_id"] + ".json")
    raw = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert result["feature_coverage"] == "complete"
    assert result["formal_prediction"] is None
    assert result["training_eligible"] is False
    assert not result["replayed"]
    assert handoff.freeze(root, deepcopy(projection), **expected) == result | {"replayed": True}
    assert handoff.reopen(
        root, expected_artifact_digest=result["artifact_digest"], **expected
    ) == result | {"replayed": True}
    assert path.read_bytes() == raw
    value = json.loads(raw)
    assert value["projection"] == projection
    assert value["result"] == features.build_features(
        projection,
        expected_projection_digest=digest(projection),
        expected_method_digest=features.method_digest(),
    )
    projection["attempts"][0]["judgment"]["reason"] = "changed source"
    assert path.read_bytes() == raw


@pytest.mark.parametrize(
    "field",
    [
        "expected_projection_digest",
        "expected_binding_digest",
        "expected_feature_method_digest",
        "expected_handoff_method_digest",
        "command_id",
        "origin",
    ],
)
def test_wrong_expected_identity_never_publishes(material, field):
    root, projection, expected = material
    expected[field] = "1" * 64 if field.startswith("expected") else "invalid"
    with pytest.raises((GovernanceError, features.FeatureProjectionError)):
        handoff.freeze(root, projection, **expected)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "attack", ["missing", "unknown", "duplicate_call", "extra_label", "wrong_scope", "old_version"]
)
def test_incomplete_or_unbound_input_cannot_be_handed_off(material, attack):
    root, projection, expected = material
    if attack == "missing":
        projection["attempts"].pop()
    elif attack == "unknown":
        row = projection["attempts"][-1]
        row.update(
            state="unknown",
            response_model=None,
            response_id=None,
            response_digest=None,
            judgment_digest=None,
            judgment=None,
        )
    elif attack == "duplicate_call":
        projection["attempts"][1]["call_id"] = projection["attempts"][0]["call_id"]
    elif attack == "extra_label":
        projection["official_score"] = 99
    elif attack == "wrong_scope":
        projection["binding"]["scope_id"] = str(uuid4())
    else:
        projection["version"] = "package-technical-feature-projection/1"
    expected["expected_projection_digest"] = digest(projection)
    with pytest.raises((GovernanceError, features.FeatureProjectionError)):
        handoff.freeze(root, projection, **expected)
    assert list(root.iterdir()) == []


def test_concurrent_same_command_is_idempotent(material):
    root, projection, expected = material
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: handoff.freeze(root, projection, **expected), range(4)))
    assert sum(not r["replayed"] for r in results) == 1
    assert len({r["artifact_digest"] for r in results}) == 1
    assert len(list(root.iterdir())) == 1


def test_conflicting_command_does_not_overwrite(material):
    root, projection, expected = material
    result = handoff.freeze(root, projection, **expected)
    with pytest.raises(GovernanceError) as conflict:
        handoff.freeze(root, projection, **(expected | {"origin": "unqualified_research"}))
    assert conflict.value.code == "PACKAGE_FEATURE_HANDOFF_COMMAND_CONFLICT"
    assert (
        handoff.reopen(root, expected_artifact_digest=result["artifact_digest"], **expected)[
            "artifact_digest"
        ]
        == result["artifact_digest"]
    )


@pytest.mark.parametrize(
    "attack", ["bytes", "recomputed_hash", "new_binding", "new_method", "extra_authority"]
)
def test_read_recomputes_features_and_rejects_stale_or_forged_packets(material, attack):
    root, projection, expected = material
    saved = handoff.freeze(root, projection, **expected)
    path = root / (expected["command_id"] + ".json")
    expected_hash = saved["artifact_digest"]
    if attack == "new_binding":
        expected["expected_binding_digest"] = "1" * 64
    elif attack == "new_method":
        expected["expected_handoff_method_digest"] = "1" * 64
    else:
        value = json.loads(path.read_bytes())
        if attack == "extra_authority":
            value["training_eligible"] = True
        else:
            value["result"]["items"][0]["features"]["band_disagreement"] = False
        raw = canonical(value)
        path.write_bytes(raw)
        if attack != "bytes":
            expected_hash = hashlib.sha256(raw).hexdigest()
    with pytest.raises(GovernanceError):
        handoff.reopen(root, expected_artifact_digest=expected_hash, **expected)


def test_failure_before_publication_leaves_no_partial_record(material, monkeypatch):
    root, projection, expected = material
    monkeypatch.setattr(
        handoff.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("interrupted"))
    )
    with pytest.raises(OSError):
        handoff.freeze(root, projection, **expected)
    assert list(root.iterdir()) == []


def test_lost_publication_ack_is_recovered_without_replacement(material, monkeypatch):
    root, projection, expected = material
    link = os.link

    def published_then_lost(*args, **kwargs):
        link(*args, **kwargs)
        raise OSError("lost ACK")

    with monkeypatch.context() as patch:
        patch.setattr(handoff.os, "link", published_then_lost)
        with pytest.raises(OSError):
            handoff.freeze(root, projection, **expected)
    result = handoff.freeze(root, projection, **expected)
    assert result["replayed"]
    assert len(list(root.iterdir())) == 1


@pytest.mark.parametrize(
    "attack", ["directory_mode", "directory_link", "file_mode", "file_link", "file_owner"]
)
def test_private_store_does_not_follow_or_repair_foreign_access(
    material, tmp_path, monkeypatch, attack
):
    root, projection, expected = material
    saved = handoff.freeze(root, projection, **expected)
    path = root / (expected["command_id"] + ".json")
    if attack == "directory_mode":
        root.chmod(0o755)
    elif attack == "directory_link":
        link = tmp_path / "alias"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif attack == "file_mode":
        path.chmod(0o644)
    elif attack == "file_link":
        target = root / "original"
        path.rename(target)
        path.symlink_to(target)
    else:
        original = os.getuid()
        monkeypatch.setattr(handoff.os, "getuid", lambda: original + 1)
    with pytest.raises((GovernanceError, OSError)):
        handoff.reopen(root, expected_artifact_digest=saved["artifact_digest"], **expected)


@pytest.mark.parametrize(
    "raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1.0}', b'{"a":9007199254740992}', b"not-json"]
)
def test_json_parser_rejects_ambiguous_values(raw):
    with pytest.raises(GovernanceError):
        handoff.decode(raw)


def cli(*arguments):
    return subprocess.run(
        [sys.executable, "deploy/package_history_worker.py", *arguments],
        text=True,
        capture_output=True,
        timeout=30,
        env=os.environ | {"PRIVATE_SENTINEL": "must-not-inherit"},
    )


def test_real_history_launcher_freezes_and_reopens_without_inheriting_credentials(
    material, tmp_path
):
    root, projection, expected = material
    source = tmp_path / "projection.json"
    source.write_bytes(canonical(projection))
    source.chmod(0o600)
    method = cli("--purpose", "feature-method")
    assert method.returncode == 0, method.stdout + method.stderr
    assert (
        json.loads(method.stdout)["result"]["handoff_method_digest"]
        == expected["expected_handoff_method_digest"]
    )
    arguments = ["--artifact-dir", str(root)]
    for key, value in expected.items():
        arguments += ["--" + key.replace("_", "-"), value]
    saved = cli("--purpose", "feature-freeze", "--projection", str(source), *arguments)
    assert saved.returncode == 0, saved.stdout + saved.stderr
    result = json.loads(saved.stdout)["result"]
    assert projection["evidence_catalog"][0]["text"] not in saved.stdout
    loaded = cli(
        "--purpose",
        "feature-read",
        "--expected-artifact-digest",
        result["artifact_digest"],
        *arguments,
    )
    assert loaded.returncode == 0, loaded.stdout + loaded.stderr
    assert json.loads(loaded.stdout)["result"] == result | {"replayed": True}
    denied = cli(
        "--purpose",
        "feature-freeze",
        "--projection",
        str(source),
        "--profile",
        "forbidden.env",
        *arguments,
    )
    assert denied.returncode != 0
    assert "Traceback" not in denied.stderr


def test_research_consumer_receives_verified_copy_not_numeric_or_training_authority(material):
    root, projection, expected = material
    saved = handoff.freeze(root, projection, **expected)
    bundle = handoff.load(root, expected_artifact_digest=saved["artifact_digest"], **expected)
    assert bundle["result"]["complete_rule_count"] == 2
    assert bundle["result"]["raw_numeric_total"] is None
    assert bundle["training_eligible"] is False
    bundle["result"]["items"].clear()
    restored = handoff.load(root, expected_artifact_digest=saved["artifact_digest"], **expected)
    assert len(restored["result"]["items"]) == 2


def test_private_reader_rejects_fifo_without_blocking(tmp_path):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(GovernanceError):
        handoff.private_read(fifo)


def test_cli_errors_do_not_echo_private_projection_or_traceback(material, tmp_path):
    root, _, expected = material
    source = tmp_path / "invalid.json"
    source.write_text('{"private":"never-log-this-private-value", "bad":')
    source.chmod(0o600)
    arguments = ["--artifact-dir", str(root), "--projection", str(source)]
    for key, value in expected.items():
        arguments += ["--" + key.replace("_", "-"), value]
    result = cli("--purpose", "feature-freeze", *arguments)
    assert result.returncode == 2
    assert json.loads(result.stdout)["ok"] is False
    assert "never-log-this-private-value" not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert list(root.iterdir()) == []


def test_native_history_worker_cannot_consume_unqualified_feature_bundle(material):
    root, _, _ = material
    result = cli("--purpose", "train", "--job-id", str(uuid4()), "--artifact-dir", str(root))
    assert result.returncode == 2
    assert "native history purposes do not accept feature artifacts" in result.stderr


@pytest.mark.parametrize("purpose", ["train", "feature-method"])
def test_empty_feature_flag_is_not_silently_ignored_by_other_modes(purpose):
    arguments = ["--purpose", purpose, "--expected-binding-digest", ""]
    if purpose == "train":
        arguments += ["--job-id", str(uuid4())]
    result = cli(*arguments)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_reader_allows_only_the_publishers_link_cleanup_during_read(tmp_path, monkeypatch):
    target = tmp_path / "published"
    temporary = tmp_path / "temporary"
    target.write_bytes(b"frozen bytes")
    target.chmod(0o600)
    os.link(target, temporary)
    fstat = os.fstat
    calls = 0

    def observe_then_cleanup(fd):
        nonlocal calls
        info = fstat(fd)
        calls += 1
        if calls == 1:
            temporary.unlink()
        return info

    monkeypatch.setattr(handoff.os, "fstat", observe_then_cleanup)
    assert handoff.private_read(target) == b"frozen bytes"
    assert calls == 2


def test_reader_rejects_concurrent_permission_change(tmp_path, monkeypatch):
    target = tmp_path / "published"
    target.write_bytes(b"frozen bytes")
    target.chmod(0o600)
    fstat = os.fstat
    calls = 0

    def observe_then_change(fd):
        nonlocal calls
        info = fstat(fd)
        calls += 1
        if calls == 1:
            target.chmod(0o644)
        return info

    monkeypatch.setattr(handoff.os, "fstat", observe_then_change)
    with pytest.raises(GovernanceError) as changed:
        handoff.private_read(target)
    assert changed.value.code == "PACKAGE_FEATURE_HANDOFF_FILE_CHANGED"
