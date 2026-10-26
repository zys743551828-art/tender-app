"""Synthetic /3 selection to existing baseline engine; no real metric claims."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
import test_package_complete_features as cases
import test_package_technical_material as materials

from packages.domain.providers.deepseek_vision import parse_response
from packages.domain.review_identity import canonical
from packages.model_governance import package_complete_calibration as calibration
from packages.model_governance import package_complete_features as features
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import PrivateContentStore, sha


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("synthetic-calibration")
    root, index, results = (tmp / k for k in ("cas", "index", "results"))
    for path in (root, index, results):
        path.mkdir(mode=0o700)
    members = []
    base = materials.synthetic.__wrapped__()
    with PrivateContentStore(root) as store:
        for i, purpose in enumerate(("fit", "fit", "development", "calibration", "final_test")):

            def identity(value, offset=i):
                raw = json.dumps(value).replace(materials.uid(40), materials.uid(400 + offset))
                return json.loads(raw.replace(materials.uid(41), materials.uid(500 + offset)))

            origin = replace(
                base, metadata=identity(base.metadata), material=identity(base.material)
            )
            bundle = materials.bound(materials.reseal(origin))
            attempts = []
            for slot in (1, 2, 3):
                attempt = cases.attempt(bundle, slot, call=2000 + i * 10 + slot)
                generation = parse_response(
                    materials.response(materials.judgment(bundle), id=f"synthetic-{i}-{slot}"),
                    f"synthetic-{i}-{slot}",
                    attempt.request.receipt["request_digest"],
                )
                attempts.append(replace(attempt, generation=generation))
            expected = {
                "expected_input_digest": bundle.metadata["digest"],
                "expected_binding_digest": bundle.metadata["binding_reference_digest"],
                "expected_feature_method_digest": features.method_digest(),
                "expected_handoff_method_digest": handoff.method_digest(),
            }
            source = handoff.save_source(store, bundle, attempts, **expected)
            ref = dict(
                expected,
                source_commit=source,
                command_id=str(uuid4()),
                origin="synthetic_mechanism",
            )
            saved = handoff.freeze(store, index, **ref)
            ref["expected_artifact_digest"] = saved["artifact_digest"]
            members.append(
                {
                    "id": str(uuid4()),
                    "project_id": materials.uid(400 + i),
                    "scope_id": materials.uid(500 + i),
                    "group_id": str(uuid4()),
                    "scope_digest": bundle.context.metadata["scope_digest"],
                    "purpose": purpose,
                    "submitted_at": "2026-10-24T12:00:00Z"
                    if purpose != "final_test"
                    else "2026-10-26T00:00:00Z",
                    "reference": ref,
                }
            )
    selection = {
        "version": calibration.VERSION,
        "origin": "synthetic_mechanism",
        "cohort_id": str(uuid4()),
        "method_digest": calibration.method_digest(),
        "timing": {
            "submission_split_at": "2026-10-25T00:00:00Z",
            "label_available_as_of": "2026-10-25T00:00:00Z",
            "training_frozen_at": "2026-10-26T00:00:00Z",
        },
        "members": members,
    }
    labels = {
        "version": calibration.VERSION,
        "origin": "synthetic_mechanism",
        "selection_digest": sha(canonical(selection)),
        "rows": [
            {
                "id": member["id"],
                "target": str(40 + i * 10),
                "label_known_at": "2026-10-24T18:00:00Z",
            }
            for i, member in enumerate(members[:-1])
        ],
    }
    return root, index, results, selection, labels


def inputs(selection, labels):
    selection_raw = canonical(selection)
    labels_raw = canonical(labels | {"selection_digest": sha(selection_raw)})
    return (
        selection_raw,
        labels_raw,
        {
            "expected_selection_digest": sha(selection_raw),
            "expected_labels_digest": sha(labels_raw),
            "expected_calibration_method_digest": calibration.method_digest(),
        },
    )


def test_persistent_closure_and_replay(cohort):
    root, index, results, selection, labels = cohort
    sr, lr, expected = inputs(selection, labels)
    command = str(uuid4())
    with PrivateContentStore(root) as store:
        result = calibration.assemble(store, index, sr, lr, **expected)
        assert result["features_used_for_fit"] is False
        assert len(result["verified_features"]) == 5
        assert result["mechanism_baseline_result"]["model"]["constant"] == "45.0"
        assert result["mechanism_baseline_result"]["intervals"]["0.9"]["radius"] is None
        assert not result["training_eligible"] and result["formal_prediction"] is None
        saved = calibration.freeze(store, index, results, sr, lr, command_id=command, **expected)
        assert not saved["replayed"]
        assert calibration.freeze(store, index, results, sr, lr, command_id=command, **expected)[
            "replayed"
        ]
        assert calibration.reopen(
            store,
            index,
            results,
            command_id=command,
            expected_artifact_digest=saved["artifact_digest"],
        )["replayed"]
        assert json.loads(store.get_object(saved["result_digest"])) == result


@pytest.mark.parametrize(
    "attack",
    [
        "real",
        "mixed",
        "project",
        "group",
        "scope",
        "stale",
        "repeat",
        "extra_feature_label",
        "extra_label",
        "final_label",
        "missing_label",
        "duplicate_label",
        "late_label",
        "early_label",
        "split",
        "post_submission",
        "method",
    ],
)
def test_rejected_before_persistence(cohort, attack):
    root, index, _, selection, labels = cohort
    s, attacked_labels = deepcopy(selection), deepcopy(labels)
    members = s["members"]
    if attack == "real":
        s["origin"] = "unqualified_research"
    elif attack == "mixed":
        members[0]["reference"]["origin"] = "unqualified_research"
    elif attack == "project":
        members[2]["project_id"] = members[0]["project_id"]
    elif attack == "group":
        members[4]["group_id"] = members[0]["group_id"]
    elif attack == "scope":
        members[0]["scope_id"] = str(uuid4())
    elif attack == "stale":
        members[0]["scope_digest"] = "f" * 64
    elif attack == "repeat":
        members[1] = deepcopy(members[0])
    elif attack == "extra_feature_label":
        members[0]["target"] = "99"
    elif attack == "extra_label":
        attacked_labels["rows"][0]["features"] = [1]
    elif attack == "final_label":
        attacked_labels["rows"][0]["id"] = members[-1]["id"]
    elif attack == "missing_label":
        attacked_labels["rows"].pop()
    elif attack == "duplicate_label":
        attacked_labels["rows"][1] = deepcopy(attacked_labels["rows"][0])
    elif attack == "late_label":
        attacked_labels["rows"][0]["label_known_at"] = "2026-10-26T00:00:00Z"
    elif attack == "early_label":
        attacked_labels["rows"][0]["label_known_at"] = "2026-10-23T00:00:00Z"
    elif attack == "split":
        members[-1]["submitted_at"] = "2026-10-24T12:00:00Z"
    elif attack == "post_submission":
        members[0]["submitted_at"] = "2026-10-23T00:00:00Z"
    elif attack == "method":
        s["method_digest"] = "f" * 64
    sr, lr, expected = inputs(s, attacked_labels)
    with PrivateContentStore(root) as store, pytest.raises(GovernanceError):
        calibration.assemble(store, index, sr, lr, **expected)


def test_label_changes_do_not_change_features(cohort):
    root, index, _, s, labels = cohort
    changed = deepcopy(labels)
    changed["rows"][0]["target"] = "80"
    with PrivateContentStore(root) as store:
        sr, lr, expected = inputs(s, labels)
        first = calibration.assemble(store, index, sr, lr, **expected)
        sr, lr, expected = inputs(s, changed)
        second = calibration.assemble(store, index, sr, lr, **expected)
        assert first["verified_features"] == second["verified_features"]
        assert (
            first["mechanism_baseline_result"]["model"]
            != second["mechanism_baseline_result"]["model"]
        )


def test_real_cli_freeze_read_isolated_and_redacted(cohort, tmp_path):
    root, index, results, selection, labels = cohort
    sr, lr, expected = inputs(selection, labels)
    sp, lp = tmp_path / "selection.json", tmp_path / "labels.json"
    for path, raw in ((sp, sr), (lp, lr)):
        path.write_bytes(raw)
        path.chmod(0o600)

    def run(*args):
        proc = subprocess.run(
            [sys.executable, "deploy/package_history_worker.py", *args],
            capture_output=True,
            text=True,
            env=dict(os.environ, PACKAGE_HISTORY_TRAIN_DSN="must-not-be-read"),
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "must-not-be-read" not in proc.stdout + proc.stderr
        return json.loads(proc.stdout)["result"]

    method = run("--purpose", "complete-calibration-method")
    assert method["calibration_method_digest"] == expected["expected_calibration_method_digest"]
    common = [
        "--material-store",
        str(root),
        "--artifact-dir",
        str(index),
        "--result-dir",
        str(results),
        "--command-id",
        str(uuid4()),
    ]
    frozen = run(
        "--purpose",
        "complete-calibration-freeze",
        *common,
        "--selection",
        str(sp),
        "--labels",
        str(lp),
        *[part for k, v in expected.items() for part in ("--" + k.replace("_", "-"), v)],
    )
    read = run(
        "--purpose",
        "complete-calibration-read",
        *common,
        "--expected-artifact-digest",
        frozen["artifact_digest"],
    )
    assert read["result_digest"] == frozen["result_digest"]


@pytest.mark.parametrize(
    "field",
    ["expected_selection_digest", "expected_labels_digest", "expected_calibration_method_digest"],
)
def test_independent_pins_required(cohort, field):
    root, index, _, selection, labels = cohort
    sr, lr, expected = inputs(selection, labels)
    expected[field] = "f" * 64
    with PrivateContentStore(root) as store, pytest.raises(GovernanceError):
        calibration.assemble(store, index, sr, lr, **expected)


def test_failed_assembly_never_publishes(cohort, tmp_path):
    root, index, _, selection, labels = cohort
    results = tmp_path / "results"
    results.mkdir(mode=0o700)
    broken = deepcopy(labels)
    broken["rows"][0]["id"] = selection["members"][-1]["id"]
    sr, lr, expected = inputs(selection, broken)
    with PrivateContentStore(root) as store, pytest.raises(GovernanceError):
        calibration.freeze(store, index, results, sr, lr, command_id=str(uuid4()), **expected)
    assert not list(results.iterdir())


def test_lost_ack_recovered_and_conflict_does_not_replace(cohort, tmp_path, monkeypatch):
    root, index, _, selection, labels = cohort
    results = tmp_path / "results"
    results.mkdir(mode=0o700)
    sr, lr, expected = inputs(selection, labels)
    command = str(uuid4())
    original = handoff._index

    def lost_ack(*args):
        original(*args)
        raise OSError("synthetic lost ACK")

    with PrivateContentStore(root) as store:
        with monkeypatch.context() as patch:
            patch.setattr(handoff, "_index", lost_ack)
            with pytest.raises(OSError, match="lost ACK"):
                calibration.freeze(store, index, results, sr, lr, command_id=command, **expected)
        saved = calibration.freeze(store, index, results, sr, lr, command_id=command, **expected)
        assert saved["replayed"]
        previous = (results / (command + ".json")).read_bytes()
        changed = deepcopy(labels)
        changed["rows"][0]["target"] = "81"
        sr, lr, expected = inputs(selection, changed)
        with pytest.raises(GovernanceError):
            calibration.freeze(store, index, results, sr, lr, command_id=command, **expected)
        assert (results / (command + ".json")).read_bytes() == previous
        assert calibration.reopen(
            store,
            index,
            results,
            command_id=command,
            expected_artifact_digest=saved["artifact_digest"],
        )["replayed"]


@pytest.mark.parametrize(
    "purpose,extra",
    [
        ("complete-calibration-method", ["--profile", "private"]),
        ("complete-calibration-method", ["--expected-selection-digest", ""]),
        ("complete-calibration-method", ["--origin", "synthetic_mechanism"]),
        ("complete-feature-method", ["--labels", "private"]),
        ("train", ["--labels", "private"]),
    ],
)
def test_cli_rejects_mixed_purposes(purpose, extra):
    result = subprocess.run(
        [sys.executable, "deploy/package_history_worker.py", "--purpose", purpose, *extra],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("kind", ["call", "response"])
def test_cross_sample_execution_identity_not_reusable(cohort, monkeypatch, kind):
    root, index, _, selection, labels = cohort
    sr, lr, expected = inputs(selection, labels)
    original = handoff.load
    first = []

    def reused(*args, **kwargs):
        loaded = original(*args, **kwargs)
        if not first:
            first.append(loaded.attempts[0])
            return loaded
        attempts = list(loaded.attempts)
        if kind == "call":
            attempts[0] = replace(attempts[0], call_id=first[0].call_id)
        else:
            attempts[0] = replace(
                attempts[0],
                generation=replace(
                    attempts[0].generation, response_id=first[0].generation.response_id
                ),
            )
        return replace(loaded, attempts=attempts)

    monkeypatch.setattr(handoff, "load", reused)
    with PrivateContentStore(root) as store, pytest.raises(GovernanceError) as error:
        calibration.assemble(store, index, sr, lr, **expected)
    assert error.value.code.endswith("CALL_REUSED" if kind == "call" else "RESPONSE_REUSED")


def test_reopen_requires_retained_result_bytes(cohort, tmp_path, monkeypatch):
    root, index, _, selection, labels = cohort
    results = tmp_path / "results"
    results.mkdir(mode=0o700)
    sr, lr, expected = inputs(selection, labels)
    command = str(uuid4())
    with PrivateContentStore(root) as store:
        saved = calibration.freeze(store, index, results, sr, lr, command_id=command, **expected)
        original = store.get_object
        monkeypatch.setattr(
            store,
            "get_object",
            lambda key: b"{}" if key == saved["result_digest"] else original(key),
        )
        with pytest.raises(GovernanceError) as error:
            calibration.reopen(
                store,
                index,
                results,
                command_id=command,
                expected_artifact_digest=saved["artifact_digest"],
            )
        assert error.value.code.endswith("RESULT_CHANGED")


def test_private_cli_inputs_reject_symlink_without_disclosing_content(cohort, tmp_path):
    root, index, results, selection, labels = cohort
    sr, lr, expected = inputs(selection, labels)
    source, alias, lp = (tmp_path / k for k in ("private", "alias", "labels"))
    source.write_bytes(sr)
    source.chmod(0o600)
    alias.symlink_to(source)
    lp.write_bytes(lr)
    lp.chmod(0o600)
    args = [
        "--purpose",
        "complete-calibration-freeze",
        "--material-store",
        str(root),
        "--artifact-dir",
        str(index),
        "--result-dir",
        str(results),
        "--command-id",
        str(uuid4()),
        "--selection",
        str(alias),
        "--labels",
        str(lp),
    ]
    args += [
        part for key, value in expected.items() for part in ("--" + key.replace("_", "-"), value)
    ]
    result = subprocess.run(
        [sys.executable, "deploy/package_history_worker.py", *args], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert not json.loads(result.stdout)["ok"]
    assert selection["cohort_id"] not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
