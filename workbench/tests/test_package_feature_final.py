"""Synthetic /3 mechanism checks; native channel is simulated, not PG acceptance."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from test_package_feature_training_io import cohort  # noqa: F401

# ruff: noqa: F811
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_final as final
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_feature_training_io as training_io
from packages.model_governance import package_history_complete as native
from packages.model_governance import package_history_runtime as runtime
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import PrivateContentStore, sha


@pytest.fixture(scope="module")
def material_base(cohort):
    root, index, _, selection, _, export, refs = cohort
    with PrivateContentStore(root) as store:
        store.put_object(canonical(refs))
        baseline = native.consume(
            export,
            canonical(refs),
            expected_reference_digest=digest(refs),
            expected_method_digest=native.method_digest(),
            store=store,
            artifact_dir=index,
        )
        projected = training_io.projections(
            store, index, [(r["admission_id"], r["reference"]) for r in refs["rows"]]
        )
        candidate = training.train(
            export["training_export"],
            projected,
            expected_method_digest=training.method()["digest"],
            source_digest=digest(refs),
        )
        member = selection["members"][-1]
        loaded = handoff.load(store, index, **member["reference"])
    binding = {
        "admission_id": member["id"],
        "proof_id": str(uuid4()),
        "context_digest": "a" * 64,
        "bid_id": member["project_id"],
        "scope_id": member["scope_id"],
        "scope_digest": member["scope_digest"],
        "scope_manifest": loaded.bundle.context.origin.material["scope"]["manifest"],
        "project_id": member["project_id"],
        "submitted_at": member["submitted_at"],
        "origin": "synthetic",
        "originals": [
            {"document_version_id": k, "digest": sha(v), "byte_size": len(v)}
            for k, v in loaded.bundle.context.origin.originals.items()
        ],
    }
    manifest = [
        {
            "id": member["id"],
            "project_id": member["project_id"],
            "group_id": member["group_id"],
            "method": "package-history-project-baselines/1",
            "engineering_type": "test",
            "maximum": "100",
            "status": "succeeded",
            "reason": None,
        }
    ]
    packet = {
        "schema": final.INPUT,
        "cohort_id": selection["cohort_id"],
        "membership_digest": export["training_export"]["membership_digest"],
        "origin": "synthetic",
        "candidate": candidate,
        "candidate_digest": digest(candidate),
        "manifest": manifest,
        "manifest_digest": digest(manifest),
        "material_bindings": [binding],
        "bindings_digest": digest([binding]),
        "training_members": [
            {k: r[k] for k in ("id", "project_id", "group_id")}
            for r in export["training_export"]["rows"]
        ],
        "training_inputs": baseline["complete_material_consumer"]["receipts"],
        "forbidden_label_sources": [
            {"id": b["label_document_id"], "digest": b["label_file_digest"]}
            for b in export["material_bindings"]
        ],
    }
    references = {
        "version": final.REFERENCE,
        "cohort_id": packet["cohort_id"],
        "membership_digest": packet["membership_digest"],
        "candidate_digest": packet["candidate_digest"],
        "rows": [{"admission_id": member["id"], "reference": member["reference"]}],
    }
    return root, index, packet, references


@pytest.fixture
def material(material_base):
    return deepcopy(material_base)


def consume(material):
    root, index, packet, refs = material
    with PrivateContentStore(root) as store:
        return final.consume(
            packet,
            canonical(refs),
            expected_reference_digest=digest(refs),
            expected_method_digest=final.method_digest(),
            store=store,
            artifact_dir=index,
        )


def test_frozen_model_predictions_reproducible_without_labels_or_refit(material, monkeypatch):
    monkeypatch.setattr(training, "train", lambda *a, **kw: pytest.fail("final must never train"))
    result = consume(material)
    assert result == consume(material)
    assert result["rows"][0]["status"] == "succeeded"
    assert 0 <= float(result["rows"][0]["prediction"]) <= 100
    assert result["formal_prediction"] is None and result["evaluation_status"] == "not_implemented"
    assert all("target" not in row for row in material[2]["manifest"])
    assert "labels" not in material[2]


@pytest.mark.parametrize(
    "change",
    [
        "label",
        "model",
        "method",
        "origin",
        "scope",
        "bytes",
        "project",
        "group",
        "input",
        "denominator",
        "reference_version",
        "candidate_version",
        "candidate_pin",
        "label_in_original",
    ],
)
def test_reject_changed_identity_and_leakage(material, change):
    root, index, packet, refs = material
    if change == "label":
        packet["manifest"][0]["target"] = "88"
    elif change == "model":
        packet["candidate"]["model"]["intercept"] = "99"
    elif change == "method":
        packet["candidate"]["method_digest"] = "f" * 64
    elif change == "origin":
        packet["material_bindings"][0]["origin"] = "external_evidence"
    elif change == "scope":
        packet["material_bindings"][0]["scope_digest"] = "f" * 64
    elif change == "bytes":
        packet["material_bindings"][0]["originals"][0]["digest"] = "f" * 64
    elif change == "project":
        packet["training_members"][0]["project_id"] = packet["manifest"][0]["project_id"]
    elif change == "group":
        packet["training_members"][0]["group_id"] = packet["manifest"][0]["group_id"]
    elif change == "input":
        packet["training_inputs"][0]["input_digest"] = refs["rows"][0]["reference"][
            "expected_input_digest"
        ]
    elif change == "denominator":
        refs["rows"].append(deepcopy(refs["rows"][0]))
    elif change == "reference_version":
        refs["version"] = "future/2"
    elif change == "candidate_version":
        packet["candidate"]["version"] = "future/2"
    elif change == "candidate_pin":
        refs["candidate_digest"] = "f" * 64
    elif change == "label_in_original":
        packet["forbidden_label_sources"][0] = {
            "id": "unused",
            "digest": packet["material_bindings"][0]["originals"][0]["digest"],
        }
    packet["bindings_digest"] = digest(packet["material_bindings"])
    packet["manifest_digest"] = digest(packet["manifest"])
    with pytest.raises(GovernanceError):
        consume((root, index, packet, refs))


def test_rejected_denominator_not_silently_projected(material):
    root, index, packet, refs = material
    packet["manifest"][0]["status"] = "rejected"
    packet["manifest_digest"] = digest(packet["manifest"])
    with pytest.raises(GovernanceError):
        consume(material)
    refs["rows"][0]["reference"] = None
    result = consume((root, index, packet, refs))
    assert result["rows"][0]["status"] == "rejected" and result["rows"][0]["prediction"] is None


def test_runtime_persists_before_any_label_access_and_recovers_lost_ack(
    material, monkeypatch, tmp_path
):
    root, index, packet, refs = material
    path = tmp_path / "refs"
    path.write_bytes(canonical(refs))
    path.chmod(0o600)
    config = {
        "references": path,
        "material_store": root,
        "artifact_dir": index,
        "reference_digest": digest(refs),
        "method_digest": final.method_digest(),
    }
    stored = []
    queries = []
    lose_ack = [True]

    class Connection:
        def execute(self, query, args):
            queries.append(query)
            if "claim_job" in query:
                self.value = {
                    "state": "running",
                    "generation": 1,
                    "fence": len(queries),
                    "feature_final_input": packet,
                    "feature_final_frozen": deepcopy(stored[0]) if stored else None,
                }
            elif "finish_job" in query:
                if stored:
                    assert stored[0] == args[-2].obj
                else:
                    stored.append(deepcopy(args[-2].obj))
                if lose_ack.pop() if lose_ack else False:
                    raise OSError("synthetic lost ACK after commit")
            else:
                pytest.fail("Unexpected access: " + query)
            return self

        def fetchone(self):
            return {"value": self.value}

    @contextmanager
    def connection(purpose):
        assert purpose == "evaluate"
        yield Connection()

    monkeypatch.setattr(runtime, "connection", connection)
    job = uuid4()
    with pytest.raises(OSError):
        runtime.run("evaluate", job, 1, final_material=config)
    receipt = runtime.run("evaluate", job, 1, final_material=config)
    assert receipt["replayed"] and receipt["predictions_digest"] == digest(stored[0])
    assert receipt["state"] == "predictions_frozen"
    assert all("open_final" not in q and "read_final" not in q for q in queries)
    stored[0]["rows"][0]["prediction"] = "99"
    with pytest.raises(GovernanceError, match="Frozen predictions"):
        runtime.run("evaluate", job, 1, final_material=config)


def test_optional_sql_preserves_signatures_and_denies_feature_exposure():
    sql = Path("deploy/sql/package-history-feature-final.sql").read_text()
    assert "GRANT " not in sql and "CREATE OR REPLACE FUNCTION" in sql
    assert "feature_final_fresh_install_required" in sql
    assert "feature_final_evaluation_unavailable" in sql
    opening = sql.split("CREATE OR REPLACE FUNCTION package_historical_research.open_final", 1)[1]
    assert opening.index("feature_final_evaluation_unavailable") < opening.index(
        "INSERT INTO package_historical_research.exposures"
    )
    assert "feature_final_prediction_changed" in sql
    assert "feature_final_input_drift" in sql


def test_cli_method_and_invalid_modes_are_credential_free():
    import json
    import subprocess
    import sys

    command = [sys.executable, "deploy/package_history_worker.py"]
    result = subprocess.run(
        command + ["--purpose", "final-feature-method"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["method_digest"] == final.method_digest()
    for purpose in ("train", "verify", "final-feature-method", "evaluate"):
        result = subprocess.run(
            command + ["--purpose", purpose, "--freeze-final-feature-predictions"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2 and "requires evaluate" in result.stderr


def test_private_reference_symlink_refused_before_prediction(material, tmp_path):
    root, index, packet, refs = material
    source = tmp_path / "source"
    source.write_bytes(canonical(refs))
    source.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises((GovernanceError, OSError)):
        final.run(
            packet,
            {
                "references": link,
                "material_store": root,
                "artifact_dir": index,
                "reference_digest": digest(refs),
                "method_digest": final.method_digest(),
            },
        )


@pytest.mark.parametrize("reuse", ["call", "response"])
def test_final_cannot_reuse_training_provider_identity(material, monkeypatch, reuse):
    from dataclasses import replace

    original = handoff.load
    training_identity = []
    final_input = material[3]["rows"][0]["reference"]["expected_input_digest"]

    def load(*args, **kwargs):
        value = original(*args, **kwargs)
        if kwargs["expected_input_digest"] != final_input:
            training_identity.append(value.attempts[0])
        else:
            attempts = list(value.attempts)
            if reuse == "call":
                attempts[0] = replace(attempts[0], call_id=training_identity[0].call_id)
            else:
                attempts[0] = replace(
                    attempts[0],
                    generation=replace(
                        attempts[0].generation,
                        response_id=training_identity[0].generation.response_id,
                    ),
                )
            value = replace(value, attempts=attempts)
        return value

    monkeypatch.setattr(handoff, "load", load)
    with pytest.raises(GovernanceError) as error:
        consume(material)
    assert error.value.code == "PACKAGE_FEATURE_FINAL_" + reuse.upper() + "_REUSED"
