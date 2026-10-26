"""Actual /3 CAS and research CLI; all documents/labels/groups are synthetic."""

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
import test_package_complete_features as cases
import test_package_technical_material as materials

from packages.domain.providers.deepseek_vision import parse_response
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_complete_calibration as calibration
from packages.model_governance import package_complete_features as features
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_feature_training_io as consumer
from packages.model_governance import package_history_complete as native
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import PrivateContentStore, sha


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("feature-training-mechanism")
    root, index, results = (tmp / k for k in ("cas", "index", "results"))
    for path in (root, index, results):
        path.mkdir(mode=0o700)
    # Repeated fixture documents do NOT assert real statistical independence.
    # Native group truth is separately enforced by SQL; this is a synthetic channel.
    base = materials.synthetic.__wrapped__()
    members, bindings, native_rows = [], [], []
    with PrivateContentStore(root) as store:
        purposes = ["fit"] * 3 + ["development"] * 2 + ["calibration"] * 9 + ["final_test"]
        for i, purpose in enumerate(purposes):

            def identity(value, offset=i):
                raw = json.dumps(value).replace(materials.uid(40), materials.uid(400 + offset))
                return json.loads(raw.replace(materials.uid(41), materials.uid(500 + offset)))

            origin = replace(
                base, metadata=identity(base.metadata), material=identity(base.material)
            )
            bundle = materials.bound(materials.reseal(origin))
            attempts = []
            for slot in (1, 2, 3):
                attempt = cases.attempt(bundle, slot, call=3000 + i * 10 + slot)
                data = materials.judgment(bundle)
                data["band_id"] = bundle.context.metadata["rules"][0]["bands"][i % 2]["band_id"]
                data["dimensions"]["specificity"] = "uncertain" if i % 2 else "supported"
                generation = parse_response(
                    materials.response(data, id=f"feature-fixture-{i}-{slot}"),
                    f"feature-fixture-{i}-{slot}",
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
            ref = expected | {
                "source_commit": source,
                "command_id": str(uuid4()),
                "origin": "synthetic_mechanism",
            }
            saved = handoff.freeze(store, index, **ref)
            ref["expected_artifact_digest"] = saved["artifact_digest"]
            member = {
                "id": str(uuid4()),
                "project_id": materials.uid(400 + i),
                "scope_id": materials.uid(500 + i),
                "scope_digest": bundle.context.metadata["scope_digest"],
                "group_id": str(uuid4()),
                "purpose": purpose,
                "submitted_at": "2026-10-26T00:00:00Z"
                if purpose == "final_test"
                else "2026-10-24T12:00:00Z",
                "reference": ref,
            }
            members.append(member)
            if purpose == "final_test":
                continue
            native_rows.append(
                {k: member[k] for k in ("id", "project_id", "group_id", "purpose", "submitted_at")}
                | {"target": "30" if i % 2 else "70", "label_known_at": "2026-10-24T18:00:00Z"}
            )
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
    selection = {
        "version": calibration.VERSION,
        "origin": "synthetic_mechanism",
        "cohort_id": str(uuid4()),
        "method_digest": calibration.method_digest(),
        "members": members,
        "timing": {
            "submission_split_at": "2026-10-25T00:00:00Z",
            "label_available_as_of": "2026-10-25T00:00:00Z",
            "training_frozen_at": "2026-10-26T00:00:00Z",
        },
    }
    labels = {
        "version": calibration.VERSION,
        "origin": "synthetic_mechanism",
        "selection_digest": sha(canonical(selection)),
        "rows": [{k: row[k] for k in ("id", "target", "label_known_at")} for row in native_rows],
    }
    bundle = {
        "schema": "package-history-training-export/1",
        "origin": "synthetic",
        "cohort_id": selection["cohort_id"],
        "membership_digest": labels["selection_digest"],
        "protocol": cpu.protocol(),
        "timing": selection["timing"],
        "rows": native_rows,
    }
    export = {
        "schema": native.EXPORT,
        "training_export": bundle,
        "material_bindings": bindings,
        "bindings_digest": digest(bindings),
    }
    refs = {
        "version": native.VERSION,
        "method_digest": native.method_digest(),
        "cohort_id": bundle["cohort_id"],
        "membership_digest": bundle["membership_digest"],
        "rows": [{"admission_id": m["id"], "reference": m["reference"]} for m in members[:-1]],
    }
    return root, index, results, selection, labels, export, refs


def pins(selection, labels):
    sr, lr = canonical(selection), canonical(labels)
    return (
        sr,
        lr,
        {
            "expected_selection_digest": sha(sr),
            "expected_labels_digest": sha(lr),
            "expected_calibration_method_digest": calibration.method_digest(),
            "expected_feature_training_method_digest": training.method()["digest"],
        },
    )


def test_actual_projection_rejects_forged_votes_without_label_inputs(cohort):
    root, index, _, selection, *_ = cohort
    with PrivateContentStore(root) as store:
        loaded = handoff.load(store, index, **selection["members"][0]["reference"])
        projection = training.project(loaded)
        assert projection["values"][0] == "1.0" and len(projection["values"]) == 6
        changed = deepcopy(loaded)
        changed.features[0]["features"]["band_votes"][0]["count"] = 0
        with pytest.raises(GovernanceError):
            training.project(changed)


def test_actual_local_cli_fits_persists_recomputes_and_preserves_old_mode(cohort, tmp_path):
    root, index, results, selection, labels, *_ = cohort
    sr, lr, expected = pins(selection, labels)
    sp, lp = tmp_path / "selection", tmp_path / "labels"
    for path, raw in ((sp, sr), (lp, lr)):
        path.write_bytes(raw)
        path.chmod(0o600)

    def run(*args):
        result = subprocess.run(
            [sys.executable, "deploy/package_history_worker.py", *args],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)["result"]

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
    saved = run(
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
        saved["artifact_digest"],
        "--expected-feature-training-method-digest",
        expected["expected_feature_training_method_digest"],
    )
    assert read["result_digest"] == saved["result_digest"]
    assert (
        saved["feature_candidate_status"]
        == read["feature_candidate_status"]
        == "research_candidate"
    )
    with PrivateContentStore(root) as store:
        value = json.loads(store.get_object(saved["result_digest"]))
        candidate = value["complete_feature_training"]
        assert candidate["status"] == "research_candidate" and candidate["features_used_for_fit"]
        assert not candidate["formal_prediction_eligible"]
        assert candidate["source_digest"] == expected["expected_selection_digest"]
        baseline = calibration.assemble(
            store,
            index,
            sr,
            lr,
            **{k: v for k, v in expected.items() if k != "expected_feature_training_method_digest"},
        )
        assert value == baseline | {"complete_feature_training": candidate}


def test_native_consumer_fits_and_keeps_original_baseline_identity(cohort, tmp_path):
    root, index, _, _, _, export, refs = cohort
    raw = canonical(refs)
    path = tmp_path / "refs"
    path.write_bytes(raw)
    path.chmod(0o600)
    config = {
        "references": path,
        "material_store": root,
        "artifact_dir": index,
        "reference_digest": sha(raw),
        "method_digest": native.method_digest(),
    }
    result = consumer.native_run(export, config, training.method()["digest"])
    candidate = result.pop("complete_feature_training")
    assert result == native.run(export, config)
    from jsonschema import Draft202012Validator

    from packages.contracts.package_historical_research_api import TRAINING_RESULT

    Draft202012Validator(TRAINING_RESULT).validate(
        result | {"complete_feature_training": candidate}
    )
    assert candidate["status"] == "research_candidate"
    assert candidate["source_digest"] == result["complete_material_consumer"]["reference_digest"]
    assert result["model"]["schema"] == "package-history-constant-model/1"
    assert candidate["model"]["version"] == training.MODEL
    assert candidate["final_test_consumption"] == "not_implemented"


def test_final_label_is_rejected_before_any_result_publish(cohort, tmp_path):
    root, index, _, selection, labels, *_ = cohort
    labels = deepcopy(labels)
    labels["rows"][0]["id"] = selection["members"][-1]["id"]
    sr, lr, expected = pins(selection, labels)
    result_dir = tmp_path / "result"
    result_dir.mkdir(mode=0o700)
    with PrivateContentStore(root) as store, pytest.raises(GovernanceError):
        consumer.freeze(store, index, result_dir, sr, lr, command_id=str(uuid4()), **expected)
    assert not list(result_dir.iterdir())


@pytest.mark.parametrize("change", ["nonnumeric", "same_points"])
def test_valid_material_with_unsupported_numeric_scale_is_unavailable(change):
    origin = deepcopy(materials.synthetic.__wrapped__())
    rule = origin.material["scope"]["manifest"]["preview"]["manifest"]["rules"][0]
    rule["rule_snapshot"]["bands"][0]["points"] = "unknown" if change == "nonnumeric" else "0"
    rule["rule_digest"] = digest(rule["rule_snapshot"])
    bundle = materials.bound(materials.reseal(origin))
    attempts = [cases.attempt(bundle, slot) for slot in (1, 2, 3)]
    loaded = handoff.CompleteResearchInput(bundle, attempts, [cases.aggregate(bundle, attempts)])
    with pytest.raises(training.ProjectionUnavailable):
        training.project(loaded)


def test_native_runtime_publishes_actual_candidate_in_existing_result_sink(
    cohort, tmp_path, monkeypatch
):
    from contextlib import contextmanager

    from packages.model_governance import package_history_runtime as runtime

    root, index, _, _, _, export, refs = cohort
    raw = canonical(refs)
    path = tmp_path / "native-refs"
    path.write_bytes(raw)
    path.chmod(0o600)
    config = {
        "references": path,
        "material_store": root,
        "artifact_dir": index,
        "reference_digest": sha(raw),
        "method_digest": native.method_digest(),
    }
    published = []

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return {"value": self.value}

    class Connection:
        def execute(self, statement, arguments):
            if "claim_job" in statement:
                return Result({"state": "running", "generation": 1, "fence": 1})
            if "read_training" in statement:
                return Result(deepcopy(export))
            if "finish_job" in statement:
                published.append(arguments[-2].obj)
                assert digest(published[-1]) == arguments[-1]
                return Result(True)
            raise AssertionError(statement)

    @contextmanager
    def connection(purpose):
        assert purpose == "train"
        yield Connection()

    monkeypatch.setattr(runtime, "connection", connection)
    result = runtime.run(
        "train",
        uuid4(),
        1,
        complete_material=config,
        feature_training_method=training.method()["digest"],
    )
    assert result["state"] == "succeeded" and len(published) == 1
    assert result["feature_candidate_status"] == "research_candidate"
    assert published[0]["complete_feature_training"]["features_used_for_fit"]


def test_declared_rule_maxima_weight_projection_without_any_outcome():
    from packages.model_governance import package_technical_complete_vision as vision

    origin = deepcopy(materials.synthetic.__wrapped__())
    rule = origin.material["scope"]["manifest"]["preview"]["manifest"]["rules"][1]
    rule.update(selection="include", part_ids=["target"])
    rule["rule_snapshot"]["max_points"] = "30"
    rule["rule_snapshot"]["bands"][0]["points"] = "30"
    rule["rule_digest"] = digest(rule["rule_snapshot"])
    bundle = materials.bound(materials.reseal(origin))
    attempts, summaries = [], []
    for index, context_rule in enumerate(bundle.context.metadata["rules"]):
        rule_id = context_rule["rule_id"]
        request = vision.prepare_request(
            bundle,
            rule_id,
            expected_input_digest=bundle.metadata["digest"],
            expected_serializer_digest=vision.serializer_digest(),
        )
        data = materials.judgment(bundle)
        data["band_id"] = context_rule["bands"][index]["band_id"]
        rows = []
        for slot in (1, 2, 3):
            generation = parse_response(
                materials.response(data, id=f"weighted-{index}-{slot}"),
                f"weighted-{index}-{slot}",
                request.receipt["request_digest"],
            )
            rows.append(
                features.CompleteJudgmentAttempt(
                    rule_id, slot, 1, str(uuid4()), "succeeded", request, generation
                )
            )
        attempts.extend(rows)
        summaries.append(
            features.aggregate_rule(
                bundle,
                rule_id,
                rows,
                expected_input_digest=bundle.metadata["digest"],
                expected_method_digest=features.method_digest(),
            )
        )
    projected = training.project(handoff.CompleteResearchInput(bundle, attempts, summaries))
    assert projected["values"][0] == "0.25"


def test_missing_calibration_group_persists_explicit_unavailable_without_model(cohort):
    root, index, results, selection, labels, *_ = cohort
    selection, labels = deepcopy(selection), deepcopy(labels)
    omitted = next(m for m in selection["members"] if m["purpose"] == "calibration")
    selection["members"].remove(omitted)
    labels["rows"] = [r for r in labels["rows"] if r["id"] != omitted["id"]]
    labels["selection_digest"] = sha(canonical(selection))
    sr, lr, expected = pins(selection, labels)
    with PrivateContentStore(root) as store:
        saved = consumer.freeze(store, index, results, sr, lr, command_id=str(uuid4()), **expected)
        assert saved["feature_candidate_status"] == "unavailable"
        result = json.loads(store.get_object(saved["result_digest"]))["complete_feature_training"]
        assert result["model"] is None and result["intervals"] is None
        assert not result["features_used_for_fit"] and not result["metrics_eligible"]
