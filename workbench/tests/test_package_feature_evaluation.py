"""Synthetic channel evaluation; not native exposure or real quality acceptance."""
# ruff: noqa: F811

from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from test_package_feature_final import material_base  # noqa: F401
from test_package_feature_training_io import cohort  # noqa: F401

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_feature_evaluation as evaluation
from packages.model_governance import package_feature_final as frozen
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance import package_history_runtime as runtime
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import PrivateContentStore


@pytest.fixture(scope="module")
def evaluation_base(material_base, cohort):
    root, index, packet, refs = material_base
    with PrivateContentStore(root) as store:
        predictions = frozen.consume(
            packet,
            canonical(refs),
            expected_reference_digest=digest(refs),
            expected_method_digest=frozen.method_digest(),
            store=store,
            artifact_dir=index,
        )
    trained = cpu.train(cohort[5]["training_export"])
    old_predictions = {
        "schema": "package-history-frozen-final-predictions/1",
        "model_digest": trained["model_digest"],
        "rows": [
            {
                "id": r["id"],
                "status": r["status"],
                "prediction": trained["model"]["constant"] if r["status"] == "succeeded" else None,
            }
            for r in packet["manifest"]
        ],
        "intervals": trained["intervals"],
        "baseline_predictions": {
            name: {r["id"]: value for r in packet["manifest"] if r["status"] == "succeeded"}
            for name, value in trained["baselines"].items()
        },
    }
    labels = [
        r | {"target": "80" if r["status"] == "succeeded" else None} for r in packet["manifest"]
    ]
    return {
        "schema": "package-history-final-evaluation-export/1",
        "origin": packet["origin"],
        "cohort_id": packet["cohort_id"],
        "protocol": cpu.protocol(),
        "timing": cohort[5]["training_export"]["timing"]
        | {
            "mode": "retrospective_submission_time_holdout",
            "historical_as_of": "per_exact_actual_submission",
            "group_spanning_policy": "exclude",
            "prediction_timing": "retrospective",
        },
        "labels": labels,
        "labels_digest": digest(labels),
        "predictions": old_predictions,
        "predictions_digest": digest(old_predictions),
        "model_digest": trained["model_digest"],
        "membership_digest": packet["membership_digest"],
        "denominator": {
            "selected_submissions": 15,
            "excluded_submissions": 0,
            "final_side_candidates": 1,
        },
        "feature_final": {
            "version": evaluation.INPUT,
            "exposure_id": str(uuid4()),
            "input": packet,
            "input_digest": digest(packet),
            "predictions": predictions,
            "predictions_digest": digest(predictions),
            "candidate_digest": packet["candidate_digest"],
        },
    }


@pytest.fixture
def bundle(evaluation_base):
    return deepcopy(evaluation_base)


def reseal(value):
    feature = value["feature_final"]
    feature["input_digest"] = digest(feature["input"])
    feature["predictions_digest"] = digest(feature["predictions"])


def test_actual_frozen_candidate_metrics_and_baseline_are_independent(bundle, monkeypatch):
    monkeypatch.setattr(training, "train", lambda *a, **kw: pytest.fail("final refit"))
    monkeypatch.setattr(training, "_fit", lambda *a, **kw: pytest.fail("final refit"))
    result = evaluation.evaluate(bundle)
    feature = result.pop("feature_final_evaluation")
    assert result == cpu.evaluate({k: v for k, v in bundle.items() if k != "feature_final"})
    predicted = float(bundle["feature_final"]["predictions"]["rows"][0]["prediction"])
    assert float(feature["report"]["sample_mae"]) == abs(predicted - 80)
    assert feature["report"]["counts"]["succeeded"] == 1
    assert feature["acceptance_decision"] == "unavailable" and feature["formal_prediction"] is None
    assert feature["paid_calls"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "value",
        "projection",
        "model",
        "method",
        "candidate_version",
        "cohort",
        "labels_identity",
        "duplicate",
        "proof",
        "project",
        "input",
        "exposure",
        "unfrozen",
    ],
)
def test_refuse_tamper_cross_task_and_method_mix(bundle, change):
    f = bundle["feature_final"]
    p = f["predictions"]
    i = f["input"]
    if change == "value":
        p["rows"][0]["prediction"] = "0"
    elif change == "projection":
        p["rows"][0]["projection"]["values"][0] = "0"
    elif change == "model":
        i["candidate"]["model"]["intercept"] = "0"
    elif change == "method":
        p["method_digest"] = "f" * 64
    elif change == "candidate_version":
        i["candidate"]["version"] = "future/2"
    elif change == "cohort":
        bundle["cohort_id"] = str(uuid4())
    elif change == "labels_identity":
        bundle["labels"][0]["project_id"] = str(uuid4())
        bundle["labels_digest"] = digest(bundle["labels"])
    elif change == "duplicate":
        p["rows"].append(deepcopy(p["rows"][0]))
    elif change == "proof":
        p["rows"][0]["receipt"]["proof_id"] = str(uuid4())
    elif change == "project":
        i["training_members"][0]["project_id"] = i["manifest"][0]["project_id"]
    elif change == "input":
        i["training_inputs"][0]["input_digest"] = p["rows"][0]["receipt"]["input_digest"]
    elif change == "exposure":
        f["exposure_id"] = "not-an-exposure"
    elif change == "unfrozen":
        f["predictions"] = None
    reseal(bundle)
    with pytest.raises((GovernanceError, ValueError)):
        evaluation.evaluate(bundle)


def test_failed_projection_remains_in_denominator(bundle):
    row = bundle["feature_final"]["predictions"]["rows"][0]
    row.update(status="failed", prediction=None, projection=None)
    reseal(bundle)
    result = evaluation.evaluate(bundle)
    assert result["report"]["counts"]["succeeded"] == 1
    report = result["feature_final_evaluation"]["report"]
    assert (
        report["denominator"] == 1
        and report["counts"]["failed"] == 1
        and report["sample_mae"] is None
    )


@pytest.mark.parametrize(
    "failure",
    ["none", "open_denied", "read_denied", "lease_expired", "lost_exposure_ack", "lost_result_ack"],
)
def test_runtime_commit_order_recovery_and_authority_failures(bundle, monkeypatch, failure):
    import psycopg

    state = {"exposed": False, "finished": False, "fault": failure}
    events = []

    class Connection:
        def execute(self, query, args):
            if "claim_job" in query:
                self.value = (
                    {"state": "succeeded", "result_digest": state["digest"]}
                    if state["finished"]
                    else {
                        "state": "running",
                        "generation": 1,
                        "fence": 1,
                        "feature_final_input": bundle["feature_final"]["input"],
                        "feature_final_frozen": bundle["feature_final"]["predictions"],
                    }
                )
            elif "open_final" in query:
                events.append("open")
                if state["fault"] in {"open_denied", "lease_expired"}:
                    raise psycopg.OperationalError("synthetic authority rejection")
                self.open = True
            elif "read_final" in query:
                assert state["exposed"]
                events.append("read")
                if state["fault"] == "read_denied":
                    raise psycopg.OperationalError("synthetic authority rejection")
                self.value = deepcopy(bundle)
            elif "finish_job" in query:
                events.append("finish")
                assert state["exposed"]
                assert args[-2].obj == evaluation.evaluate(bundle)
                self.result = args[-1]
            else:
                pytest.fail(query)
            return self

        def fetchone(self):
            return {"value": self.value}

    @contextmanager
    def connection(purpose):
        assert purpose == "evaluate"
        c = Connection()
        yield c
        if getattr(c, "open", False):
            state["exposed"] = True
            events.append("commit-exposure")
            if state["fault"] == "lost_exposure_ack":
                state["fault"] = "none"
                raise psycopg.OperationalError("synthetic lost ACK")
        if getattr(c, "result", None):
            state["finished"] = True
            state["digest"] = c.result
            if state["fault"] == "lost_result_ack":
                state["fault"] = "none"
                raise psycopg.OperationalError("synthetic lost ACK")

    monkeypatch.setattr(runtime, "connection", connection)
    job = uuid4()
    if failure != "none":
        with pytest.raises(psycopg.OperationalError):
            runtime.run("evaluate", job, 1)
        if failure in {"open_denied", "lease_expired"}:
            assert events == ["open"] and not state["exposed"]
            return
        if failure == "read_denied":
            assert "finish" not in events
            return
    receipt = runtime.run("evaluate", job, 1)
    assert receipt["state"] == "succeeded" and receipt["result_digest"] == state["digest"]
    assert events.index("commit-exposure") < events.index("read") < events.index("finish")


def test_tampered_predictions_stop_before_exposure(bundle, monkeypatch):
    bundle["feature_final"]["predictions"]["rows"][0]["prediction"] = "0"

    @contextmanager
    def connection(purpose):
        class Connection:
            def execute(self, query, args):
                assert "claim_job" in query
                return self

            def fetchone(self):
                return {
                    "value": {
                        "state": "running",
                        "generation": 1,
                        "fence": 1,
                        "feature_final_input": bundle["feature_final"]["input"],
                        "feature_final_frozen": bundle["feature_final"]["predictions"],
                    }
                }

        yield Connection()

    monkeypatch.setattr(runtime, "connection", connection)
    with pytest.raises(GovernanceError):
        runtime.run("evaluate", uuid4(), 1)


def test_persisted_result_fits_closed_api_contract_without_private_material(bundle):
    from jsonschema import Draft202012Validator, ValidationError

    from packages.contracts.package_historical_research_api import EVALUATION_RESULT

    result = evaluation.evaluate(bundle)
    Draft202012Validator(EVALUATION_RESULT).validate(result)
    feature = result["feature_final_evaluation"]
    assert not {"input", "predictions", "labels", "source_commit", "originals"} & feature.keys()
    for field, value in (
        ("formal_prediction", "80"),
        ("acceptance_decision", "passed"),
        ("exposed", True),
        ("version", "future/2"),
    ):
        bad = deepcopy(result)
        bad["feature_final_evaluation"][field] = value
        with pytest.raises(ValidationError):
            Draft202012Validator(EVALUATION_RESULT).validate(bad)
