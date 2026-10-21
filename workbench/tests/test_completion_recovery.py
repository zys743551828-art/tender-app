"""Current recovery exact-definition and complete-original guards, no external I/O."""

import json
from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import pytest

from deploy import completion_recovery as recovery
from deploy.backups import generic, run


def definitions(identity, expression):
    return {"constraints": [[*identity, expression]], "acl": [["application", "SELECT"]]}


@pytest.mark.parametrize("identity,pair", list(recovery.REPARSED_CHECKS.items()))
def test_only_exact_observed_check_reparse_pair_is_equivalent(identity, pair):
    original = definitions(identity, pair[0])
    before = deepcopy(original)
    assert recovery.equivalent_definitions(original, definitions(identity, pair[1]))
    assert recovery.equivalent_definitions(definitions(identity, pair[1]), original)
    assert original == before


@pytest.mark.parametrize("identity,pair", list(recovery.REPARSED_CHECKS.items()))
@pytest.mark.parametrize("change", ["bound", "operator", "identity", "acl", "duplicate"])
def test_unreviewed_definition_change_is_never_normalized(identity, pair, change):
    original, altered = definitions(identity, pair[0]), definitions(identity, pair[1])
    if change == "bound":
        altered["constraints"][0][4] = pair[1].replace(">= 1", ">= 0")
    elif change == "operator":
        altered["constraints"][0][4] = pair[1].replace(" AND ", " OR ", 1)
    elif change == "identity":
        original["constraints"][0][0] += "_different"
        altered["constraints"][0][0] += "_different"
    elif change == "acl":
        altered["acl"][0][1] = "UPDATE"
    else:
        altered["constraints"].append(deepcopy(altered["constraints"][0]))
    assert not recovery.equivalent_definitions(original, altered)


def test_frozen_schema_contains_current_features_and_explicit_optional_capabilities():
    plan = recovery.frozen_plan()
    paths = {item.path for item in plan}
    assert recovery.REQUIRED_BASE <= paths and set(recovery.EXTENSIONS) <= paths
    assert len(paths) == len(plan)
    assert all(run.digest(item.content) == item.sha256 for item in plan)
    assert recovery.plan_receipt(plan) == [
        {"path": item.path, "sha256": item.sha256} for item in plan
    ]


@pytest.fixture
def original_archive(tmp_path, monkeypatch):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    (root / "objects").mkdir(mode=0o700)
    identity, raw = str(uuid4()), b"synthetic original bytes"
    item = {
        "id": identity,
        "key": "synthetic/" + identity,
        "sha256": run.digest(raw),
        "bytes": len(raw),
        "media_type": "application/octet-stream",
    }
    database = {"database_sha256": run.digest(b"synthetic dump"), "objects": [item]}
    run.private_write(root / "manifest.json", b"synthetic database component")
    path = root / "objects" / (identity + ".bin")
    run.private_write(path, raw)
    value = {
        "format": recovery.ORIGINALS_FORMAT,
        "database_manifest_sha256": generic.hash_file(root / "manifest.json"),
        "database_sha256": database["database_sha256"],
        "source_bucket": "explicit-synthetic-source",
        "transport": "real_loopback_s3_synthetic_only",
        "objects": [{**item, "file": "objects/" + identity + ".bin"}],
        "native_oss_qualified": False,
        "full_application_restore_qualified": False,
    }
    content = json.dumps(value).encode()
    run.private_write(root / "originals.json", content)
    run.private_write(root / "originals.sha256", run.digest(content).encode())
    monkeypatch.setattr(generic, "validate", lambda _: deepcopy(database))
    return root, path, raw, value


@pytest.mark.parametrize("fault", ["missing", "corrupt", "public", "symlink", "db_changed"])
def test_invalid_original_is_rejected_before_any_target_request(original_archive, fault):
    root, path, raw, _ = original_archive
    if fault == "missing":
        path.unlink()
    elif fault == "corrupt":
        path.write_bytes(raw + b"changed")
    elif fault == "public":
        path.chmod(0o644)
    elif fault == "symlink":
        target = root / "another-file"
        path.rename(target)
        path.symlink_to(target)
    else:
        (root / "manifest.json").write_bytes(b"another database component")
    client = Mock()
    with pytest.raises(run.BackupError):
        recovery.restore_originals(root, client, "explicit-fresh-target")
    assert not client.mock_calls


def test_restore_never_overwrites_source_or_existing_target_objects(original_archive):
    root, _, _, value = original_archive
    client = Mock()
    with pytest.raises(run.BackupError, match="MUST_BE_DISTINCT"):
        recovery.restore_originals(root, client, value["source_bucket"])
    assert not client.mock_calls
    client.list_objects_v2.return_value = {"Contents": [{"Key": "existing"}]}
    with pytest.raises(run.BackupError, match="MUST_BE_EMPTY"):
        recovery.restore_originals(root, client, "explicit-fresh-target")
    client.put_object.assert_not_called()
