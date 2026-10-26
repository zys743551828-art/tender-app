"""Synthetic protocol/report mechanisms; never real evidence or certification."""
# ruff: noqa: F811

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from test_package_feature_evaluation import cohort, evaluation_base, material_base  # noqa: F401
from test_package_model_registry import source

from apps.api import package_model_admission_routes as routes
from packages.domain.runtime import DomainError
from packages.model_admission.application import AdmissionError
from packages.model_admission.application import validate as legacy_validate
from packages.model_governance.common import GovernanceError
from packages.package_model_admission import policy
from packages.package_model_admission.application import Admission
from packages.package_model_registry import artifact


def context():
    doc = artifact.build(source())
    src = doc["source"]
    return {
        "artifact": doc,
        "binding": {
            "model_id": doc["model_id"],
            "artifact_digest": artifact.digest(doc),
            "cohort_id": src["cohort_id"],
            "cohort_digest": src["cohort_digest"],
            "membership_digest": src["membership_digest"],
            "candidate_digest": src["candidate_digest"],
            "training_method_digest": src["candidate"]["method_digest"],
            "input_reference_digest": src["candidate"]["source_digest"],
            "final_manifest_digest": "f" * 64,
        },
    }


def document(ctx=None):
    return {
        "schema": policy.VERSION,
        "artifact_family": artifact.VERSION,
        "binding": (ctx or context())["binding"],
        "baseline": "mean",
        "thresholds": {
            "maximum_project_mae": "10",
            "minimum_paired_baseline_gain": "0.2",
            "minimum_success_coverage": "0.9",
            "minimum_interval_coverage": "0.8",
            "interval_level": "0.9",
        },
    }


def packet(doc=None):
    doc = doc or document()
    binding = doc["binding"]
    exposure = str(uuid4())
    return {
        "schema": "package-admission-native-report/1",
        "protocol": doc,
        "protocol_digest": artifact.digest(doc),
        "protocol_frozen_at": "2026-01-01T00:00:00Z",
        "exposure_at": "2026-01-02T00:00:00Z",
        "exposure_id": exposure,
        "evaluation_job_id": str(uuid4()),
        "result_digest": "a" * 64,
        "report": {
            "version": policy.evaluation.VERSION,
            "method_digest": policy.evaluation.method_digest(),
            "freeze_method_digest": policy.evaluation.frozen.method_digest(),
            "candidate_digest": binding["candidate_digest"],
            "cohort_id": binding["cohort_id"],
            "membership_digest": binding["membership_digest"],
            "exposure_id": exposure,
            "origin": "synthetic",
            "research_only": True,
            "formal_prediction": None,
            "acceptance_decision": "unavailable",
            "provider_requests": 0,
            "paid_calls": 0,
            "report": {
                "denominator": 10,
                "project_mae": "10",
                "success_coverage": "0.9",
                "paired_baselines": {"mean": {"gain": "0.2"}},
                "intervals": {"0.9": {"coverage": "0.8"}},
            },
        },
    }


@pytest.mark.parametrize("key", list(policy.BOUNDS))
def test_each_threshold_required_with_no_defaults(key):
    doc = document()
    del doc["thresholds"][key]
    with pytest.raises(GovernanceError):
        policy.validate(doc)


@pytest.mark.parametrize("value", [None, True, 0.9, 1, "NaN", "Infinity", "-0.1", "1.1", "9" * 81])
def test_wire_numbers_are_explicit_bounded_finite_decimal_strings(value):
    doc = document()
    doc["thresholds"]["minimum_success_coverage"] = value
    with pytest.raises(GovernanceError):
        policy.validate(doc)


def test_legacy_version_not_relabelled_and_self_attestation_rejected():
    doc = document()
    with pytest.raises(AdmissionError):
        legacy_validate(doc)
    doc["schema"] = "score-business-admission-protocol/1"
    with pytest.raises(GovernanceError):
        policy.validate(doc)
    doc = document()
    doc["verified"] = True
    with pytest.raises(GovernanceError):
        policy.validate(doc)


def test_exact_decimal_boundary_pass_is_not_certification():
    value = packet()
    result = policy.assess(value)
    assert result["all_declared_metric_checks_pass"]
    assert result["formal_eligibility"] == "unavailable" and not result["certification_issued"]
    assert "package_shadow_observation" in result["missing_authorities"]
    value["report"]["report"]["project_mae"] = "10.0000000000000000001"
    assert not policy.assess(value)["checks"]["maximum_project_mae"]


@pytest.mark.parametrize(
    "attack",
    [
        "late",
        "same_time",
        "timezone_missing",
        "candidate",
        "cohort",
        "membership",
        "method",
        "freeze_method",
        "exposure",
        "null_metric",
        "zero_denominator",
        "bool_denominator",
        "claimed_acceptance",
        "origin",
    ],
)
def test_report_identity_and_missing_observations_fail_closed(attack):
    value = packet()
    report = value["report"]
    if attack == "late":
        value["protocol_frozen_at"] = "2026-01-03T00:00:00Z"
    elif attack == "same_time":
        value["protocol_frozen_at"] = value["exposure_at"]
    elif attack == "timezone_missing":
        value["exposure_at"] = "2026-01-02T00:00:00"
    elif attack in {"candidate", "membership", "method", "freeze_method"}:
        report[attack + "_digest"] = "e" * 64
    elif attack in {"cohort", "exposure"}:
        report[attack + "_id"] = str(uuid4())
    elif attack == "null_metric":
        report["report"]["project_mae"] = None
    elif attack == "zero_denominator":
        report["report"]["denominator"] = 0
    elif attack == "bool_denominator":
        report["report"]["denominator"] = True
    elif attack == "claimed_acceptance":
        report["acceptance_decision"] = "accepted"
    else:
        report["origin"] = "verified"
    with pytest.raises(GovernanceError):
        policy.assess(value)


def test_consumes_actual_existing_feature_evaluator_output(evaluation_base):
    evaluated = policy.evaluation.evaluate(deepcopy(evaluation_base))["feature_final_evaluation"]
    doc = document()
    doc["binding"].update(
        {key: evaluated[key] for key in ("cohort_id", "membership_digest", "candidate_digest")}
    )
    value = packet(doc)
    value["exposure_id"] = evaluated["exposure_id"]
    value["report"] = evaluated
    result = policy.assess(value)
    assert set(result["checks"]) == set(policy.BOUNDS) - {"interval_level"}
    assert not result["certification_issued"]


class Tx:
    def __init__(self):
        self.ctx = context()
        self.doc = document(self.ctx)
        self.packet = packet(self.doc)
        self.calls = []
        self.record = None

    def context(self, model, actor):
        return self.ctx

    def freeze(self, *args):
        self.calls.append(args)
        return {"document": self.doc, "snapshot_only": True}

    def read_protocol(self, *args):
        return {"document": self.doc, "snapshot_only": True}

    def report_source(self, *args):
        return self.packet

    def register_report(self, *args):
        self.calls.append(args)
        self.record = {"packet": self.packet, "packet_digest": artifact.digest(self.packet)}
        return self.record

    def read_report(self, *args):
        return self.record


def test_owned_transaction_preview_cas_and_persisted_report_consumption():
    tx, events = Tx(), []

    @contextmanager
    def transactions():
        events.append("open")
        try:
            yield tx
        finally:
            events.append("close")

    app = Admission(transactions)
    model = tx.doc["binding"]["model_id"]
    app.freeze(model, "actor", tx.doc, "key", "synthetic")
    preview = app.preview_report(model, "job", "actor")
    app.register_report(model, "job", "actor", preview["packet_digest"], "report-key", "synthetic")
    assert app.read_report(model, "actor")["assessment"]["formal_eligibility"] == "unavailable"
    tx.packet["result_digest"] = "f" * 64
    with pytest.raises(GovernanceError):
        app.register_report(
            model, "job", "actor", preview["packet_digest"], "report-key", "synthetic"
        )
    assert len(tx.calls) == 2 and events == ["open", "close"] * 5


def test_http_accepts_only_native_job_reference_and_fixed_digest(monkeypatch):
    tx = Tx()

    @contextmanager
    def transactions():
        yield tx

    monkeypatch.setattr(routes, "service", lambda: Admission(transactions))
    calls = []

    def auth(request, write=False):
        calls.append(write)
        return {"member_id": "actor"}

    monkeypatch.setattr(routes, "auth", auth)
    app = FastAPI()
    app.include_router(routes.router)

    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    with TestClient(app) as client:
        model = tx.doc["binding"]["model_id"]
        base = f"/api/v1/package-model-admission/models/{model}"
        assert client.get(base + "/context").status_code == 200
        body = {
            "evaluation_job_id": str(uuid4()),
            "expected_packet_digest": artifact.digest(tx.packet),
            "reason": "synthetic",
        }
        assert client.post(base + "/report", json=body | {"verified": True}).status_code == 422
        response = client.post(base + "/report", json=body, headers={"Idempotency-Key": "key"})
        assert (
            response.status_code == 200
            and not response.json()["assessment"]["certification_issued"]
        )
    assert calls == [False, True]


def test_sql_keeps_commit_order_authority_and_immutable_recovery():
    sql = (Path(__file__).parents[1] / "deploy/sql/package-model-admission.sql").read_text()
    for guard in (
        "frozen.frozen_xact=exposure.created_xact",
        "frozen.frozen_at>=exposure.created_at",
        "exposure.created_xact=pg_current_xact_id()",
        "purpose='final_labels'",
        "old.request_key IS DISTINCT FROM request_key",
        "old.packet_digest::text IS DISTINCT FROM expected_digest",
        "UNIQUE REFERENCES package_historical_research.cohorts",
        "SET TimeZone='UTC'",
    ):
        assert guard in sql
    assert "INSERT INTO model_release.certifications" not in sql and "CREATE ROLE" not in sql
