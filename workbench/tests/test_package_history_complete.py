"""Synthetic SQL-channel simulation plus actual /3 CAS and native runtime consumer."""
# ruff: noqa: F811

import json
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from test_package_complete_calibration import cohort  # noqa: F401

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_history_complete as complete
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance import package_history_runtime as runtime
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import PrivateContentStore, sha


@pytest.fixture(scope="module")
def native(cohort):
    root, index, _, selection, labels = cohort
    rows, bindings, refs = [], [], []
    with PrivateContentStore(root) as store:
        for member, label in zip(selection["members"][:-1], labels["rows"], strict=True):
            loaded = handoff.load(store, index, **member["reference"])
            rows.append(
                {k: member[k] for k in ("id", "project_id", "group_id", "purpose", "submitted_at")}
                | label
            )
            origin = loaded.bundle.context.origin
            bindings.append(
                {
                    "admission_id": member["id"],
                    "proof_id": str(uuid4()),
                    "context_digest": "a" * 64,
                    "bid_id": member["project_id"],
                    "scope_id": member["scope_id"],
                    "scope_digest": member["scope_digest"],
                    "scope_manifest": origin.material["scope"]["manifest"],
                    "project_id": member["project_id"],
                    "submitted_at": member["submitted_at"],
                    "origin": "synthetic",
                    "originals": [
                        {"document_version_id": key, "digest": sha(blob), "byte_size": len(blob)}
                        for key, blob in origin.originals.items()
                    ],
                    "label_document_id": str(uuid4()),
                    "label_file_digest": "f" * 64,
                }
            )
            refs.append({"admission_id": member["id"], "reference": member["reference"]})
    bundle = {
        "schema": "package-history-training-export/1",
        "origin": "synthetic",
        "cohort_id": selection["cohort_id"],
        "membership_digest": digest(selection),
        "protocol": cpu.protocol(),
        "timing": selection["timing"],
        "rows": rows,
    }
    export = {
        "schema": complete.EXPORT,
        "training_export": bundle,
        "material_bindings": bindings,
        "bindings_digest": digest(bindings),
    }
    references = {
        "version": complete.VERSION,
        "method_digest": complete.method_digest(),
        "cohort_id": bundle["cohort_id"],
        "membership_digest": bundle["membership_digest"],
        "rows": refs,
    }
    return root, index, export, references


def consume(native, export=None, references=None):
    root, index, original, refs = native
    raw = canonical(refs if references is None else references)
    with PrivateContentStore(root) as store:
        return complete.consume(
            original if export is None else export,
            raw,
            expected_reference_digest=sha(raw),
            expected_method_digest=complete.method_digest(),
            store=store,
            artifact_dir=index,
        )


def test_actual_cpu_and_handoff_preserve_native_export_digest(native):
    result = consume(native)
    from jsonschema import Draft202012Validator, ValidationError

    from packages.contracts.package_historical_research_api import TRAINING_RESULT

    Draft202012Validator(TRAINING_RESULT).validate(result)
    bad = deepcopy(result)
    bad["complete_material_consumer"]["training_eligible"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(TRAINING_RESULT).validate(bad)
    expected = cpu.train(native[2]["training_export"])
    receipt = result.pop("complete_material_consumer")
    assert result == expected
    assert len(receipt["receipts"]) == 4
    assert receipt["features_used_for_fit"] is False and not receipt["training_eligible"]
    assert receipt["formal_prediction"] is None
    assert complete.training_export(native[2]) == native[2]["training_export"]
    assert complete.training_export(native[2]["training_export"]) == native[2]["training_export"]


@pytest.mark.parametrize(
    "attack",
    [
        "cohort",
        "membership",
        "verified",
        "label",
        "missing",
        "duplicate",
        "final",
        "group",
        "origin",
        "scope",
        "manifest",
        "original",
        "extra_original",
        "label_id",
        "label_digest",
        "project",
        "time",
        "method",
        "bindings_pin",
        "cross_label",
        "project_partition",
    ],
)
def test_local_claims_cannot_override_native_identity(native, attack):
    export, refs = deepcopy(native[2]), deepcopy(native[3])
    binding = export["material_bindings"][0]
    if attack == "cohort":
        refs["cohort_id"] = str(uuid4())
    elif attack == "membership":
        refs["membership_digest"] = "f" * 64
    elif attack == "verified":
        refs["verified"] = True
    elif attack == "label":
        refs["rows"][0]["target"] = "99"
    elif attack == "missing":
        refs["rows"].pop()
    elif attack == "duplicate":
        refs["rows"][1] = deepcopy(refs["rows"][0])
    elif attack == "final":
        export["training_export"]["rows"][0]["purpose"] = "final"
    elif attack == "group":
        export["training_export"]["rows"][2]["group_id"] = export["training_export"]["rows"][0][
            "group_id"
        ]
    elif attack == "origin":
        binding["origin"] = "external_evidence"
    elif attack == "scope":
        binding["scope_digest"] = "e" * 64
    elif attack == "manifest":
        binding["scope_manifest"]["forged"] = True
    elif attack == "original":
        binding["originals"][0]["digest"] = "e" * 64
    elif attack == "extra_original":
        binding["originals"].pop()
    elif attack == "label_id":
        binding["label_document_id"] = binding["originals"][0]["document_version_id"]
    elif attack == "label_digest":
        binding["label_file_digest"] = binding["originals"][0]["digest"]
    elif attack == "project":
        binding["project_id"] = str(uuid4())
    elif attack == "time":
        binding["submitted_at"] = "2026-10-23T00:00:00Z"
    elif attack == "method":
        refs["method_digest"] = "f" * 64
    elif attack == "cross_label":
        export["material_bindings"][1]["label_file_digest"] = binding["originals"][0]["digest"]
    elif attack == "project_partition":
        export["training_export"]["rows"][2]["project_id"] = export["training_export"]["rows"][0][
            "project_id"
        ]
    export["bindings_digest"] = (
        "e" * 64 if attack == "bindings_pin" else digest(export["material_bindings"])
    )
    with pytest.raises(GovernanceError):
        consume(native, export, refs)


def test_runtime_claim_read_compute_finish_existing_result_path(native, tmp_path, monkeypatch):
    root, index, export, refs = native
    file = tmp_path / "refs.json"
    raw = canonical(refs)
    file.write_bytes(raw)
    file.chmod(0o600)
    config = {
        "references": file,
        "material_store": root,
        "artifact_dir": index,
        "reference_digest": sha(raw),
        "method_digest": complete.method_digest(),
    }
    statements, results = [], []

    class Cursor:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return {"value": self.value}

    class Connection:
        def execute(self, statement, args):
            statements.append(statement)
            if "claim_job" in statement:
                return Cursor({"state": "running", "generation": 1, "fence": 2})
            if "read_training" in statement:
                return Cursor(deepcopy(export))
            if "finish_job" in statement:
                result = args[-2].obj
                assert args[-1] == digest(result)
                results.append(result)
                return Cursor(True)
            raise AssertionError(statement)

    @contextmanager
    def connection(purpose):
        assert purpose == "train"
        yield Connection()

    monkeypatch.setattr(runtime, "connection", connection)
    receipt = runtime.run("train", uuid4(), 1, complete_material=config)
    assert receipt["state"] == "succeeded" and len(results) == 1
    assert results[0]["complete_material_consumer"]["reference_digest"] == sha(raw)
    assert not any("read_final" in s or "open_final" in s for s in statements)
    with PrivateContentStore(root) as store:
        assert store.get_object(sha(raw)) == raw
    # A changed pin fails before CPU publication; the same native result sink is used.
    results.clear()
    with pytest.raises(GovernanceError):
        runtime.run("train", uuid4(), 1, complete_material=config | {"reference_digest": "e" * 64})
    assert not results


def test_completed_job_never_claims_different_references_were_verified(monkeypatch):
    class Connection:
        def execute(self, *args):
            return self

        def fetchone(self):
            return {"value": {"state": "succeeded", "result_digest": "a" * 64}}

    @contextmanager
    def connection(purpose):
        yield Connection()

    monkeypatch.setattr(runtime, "connection", connection)
    with pytest.raises(GovernanceError) as error:
        runtime.run("train", uuid4(), 1, complete_material={})
    assert error.value.code == "PACKAGE_HISTORY_COMPLETE_RESULT_ALREADY_FINISHED"
    assert runtime.run("train", uuid4(), 1)["state"] == "succeeded"


def test_cli_method_isolated_and_native_input_mixing_rejected():
    result = subprocess.run(
        [sys.executable, "deploy/package_history_worker.py", "--purpose", "native-feature-method"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["result"]["method_digest"] == complete.method_digest()
    for purpose in ("verify", "evaluate", "complete-feature-method", "native-feature-method"):
        result = subprocess.run(
            [
                sys.executable,
                "deploy/package_history_worker.py",
                "--purpose",
                purpose,
                "--complete-references",
                "private",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2 and "Traceback" not in result.stderr


def test_native_launcher_passes_references_only_to_dedicated_train_child(tmp_path, monkeypatch):
    from deploy import package_history_worker as launcher

    profile = tmp_path / "private.profile"
    profile.write_text("PACKAGE_HISTORY_TRAIN_DSN=synthetic.invalid\n")
    profile.chmod(0o600)
    argv = [
        "worker",
        "--purpose",
        "train",
        "--profile",
        str(profile),
        "--job-id",
        str(uuid4()),
        "--complete-references",
        str(tmp_path / "refs"),
        "--complete-material-store",
        str(tmp_path / "cas"),
        "--complete-artifact-dir",
        str(tmp_path / "index"),
        "--expected-complete-reference-digest",
        "a" * 64,
        "--expected-complete-method-digest",
        "b" * 64,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    captured = []

    def run(command, *, cwd, env, check):
        captured.append(command)
        assert "--owned-child" in command and "-I" in command
        assert "--profile" not in command
        assert env == {
            "PACKAGE_HISTORY_TRAIN_DSN": "synthetic.invalid",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
        }
        for field in (
            "--complete-references",
            "--complete-material-store",
            "--complete-artifact-dir",
            "--expected-complete-reference-digest",
            "--expected-complete-method-digest",
        ):
            assert command[command.index(field) + 1] == argv[argv.index(field) + 1]
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main() == 0 and len(captured) == 1
