"""Synthetic mechanism checks, never certificates or real evaluation claims."""

import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from apps.api import model_admission_routes as routes
from packages.domain.runtime import DomainError
from packages.model_admission.application import AdmissionError, AdmissionProtocols, validate
from packages.model_admission.infrastructure import NativeProtocols


def document():
    # Illustrative mechanism fixture only: never installed or supplied as defaults.
    return {
        "schema": "score-business-admission-protocol/1",
        "artifact_family": "registered-score-artifact/1",
        "baseline": "mean",
        "thresholds": {
            "maximum_project_mae": 10,
            "minimum_paired_baseline_gain": 0.2,
            "minimum_success_coverage": 0.9,
            "minimum_interval_coverage": 0.8,
            "interval_level": 0.9,
        },
    }


@pytest.mark.parametrize("key", list(document()["thresholds"]))
def test_every_threshold_is_explicit(key):
    value = document()
    del value["thresholds"][key]
    with pytest.raises(AdmissionError, match="REQUIRED"):
        validate(value)


@pytest.mark.parametrize("value", [True, "0.9", None, float("nan"), float("inf"), -1, 2, 10**1000])
def test_coverage_rejects_coercion_nonfinite_and_out_of_range(value):
    data = document()
    data["thresholds"]["minimum_success_coverage"] = value
    with pytest.raises(AdmissionError):
        validate(data)


@pytest.mark.parametrize(
    "name,value",
    [
        ("schema", "score-training-protocol/1"),
        ("artifact_family", "package-complete-ridge-model/1"),
        ("baseline", "caller-selected-best-final"),
        ("accepted", True),
    ],
)
def test_no_training_protocol_version_relabel_or_acceptance_flags(name, value):
    data = document()
    data[name] = value
    with pytest.raises(AdmissionError):
        validate(data)


def test_validation_does_not_share_mutable_thresholds():
    original = document()
    copy = validate(original)
    copy["thresholds"]["maximum_project_mae"] = 90
    assert original["thresholds"]["maximum_project_mae"] == 10


class Store:
    def __init__(self):
        self.calls = []

    def freeze(self, *args):
        self.calls.append(args)
        return {"formal_eligibility": "unavailable", "certification_issued": False}

    def read(self, *args):
        self.calls.append(args)
        return {"formal_eligibility": "unavailable"}


def test_service_validates_before_port_and_preserves_fixed_identity():
    store = Store()
    service = AdmissionProtocols(store)
    cohort, actor = uuid4(), uuid4()
    with pytest.raises(AdmissionError):
        service.freeze(cohort, actor, document(), None, "synthetic")
    assert not store.calls
    result = service.freeze(cohort, actor, document(), "stable-key", "synthetic")
    assert store.calls == [(cohort, actor, document(), "stable-key", "synthetic")]
    assert result["certification_issued"] is False


@pytest.mark.parametrize("failure", [None, RuntimeError("lost ACK"), KeyboardInterrupt()])
def test_native_port_single_connection_and_failure_cleanup(failure):
    events = []

    class C:
        def execute(self, sql, params=None):
            events.append((sql, params))
            if params and failure is not None:
                raise failure
            return self

        def fetchone(self):
            return {"ready": True, "receipt": {"formal_eligibility": "unavailable"}}

    @contextmanager
    def connections():
        events.append("open")
        try:
            yield C()
        finally:
            events.append("close")

    store = NativeProtocols(connections)
    if failure is None:
        assert store.read(uuid4(), uuid4())["formal_eligibility"] == "unavailable"
    else:
        with pytest.raises(type(failure)):
            store.read(uuid4(), uuid4())
    assert events[0] == "open" and events[-1] == "close"
    assert len(events) == 4


def test_http_entry_requires_auth_and_does_not_accept_qualification(monkeypatch):
    store = Store()
    monkeypatch.setattr(routes, "service", lambda: AdmissionProtocols(store))
    actor = uuid4()
    calls = []

    def auth(request, write=False):
        calls.append(write)
        return {"member_id": actor}

    monkeypatch.setattr(routes, "auth", auth)
    app = FastAPI()
    app.include_router(routes.router)

    @app.exception_handler(DomainError)
    async def handle(request, error):
        return JSONResponse({"code": error.code}, status_code=error.status)

    with TestClient(app) as client:
        path = f"/api/v1/model-admission/cohorts/{uuid4()}/protocol"
        payload = {"document": document(), "reason": "synthetic"}
        assert client.post(path, json=payload).status_code == 422
        invalid = deepcopy(payload)
        invalid["document"]["thresholds"].pop("maximum_project_mae")
        assert (
            client.post(path, json=invalid, headers={"Idempotency-Key": "key"}).status_code == 422
        )
        response = client.post(path, json=payload, headers={"Idempotency-Key": "key"})
        assert response.status_code == 200 and not response.json()["certification_issued"]
        assert client.get(path).status_code == 200
    assert calls == [True, True, True, False]
    assert len(store.calls) == 2


def test_application_is_framework_free_and_sql_keeps_fail_closed_boundary():
    root = Path(__file__).parents[1]
    tree = ast.parse((root / "packages/model_admission/application.py").read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert imports == ["typing"]
    sql = (root / "deploy/sql/model-admission-protocol.sql").read_text()
    assert "CREATE ROLE" not in sql and "INSERT INTO model_release.certifications" not in sql
    assert "GRANT INSERT" not in sql
    assert sql.index("model_governance.current_cohort(target)") < sql.index(
        "pg_advisory_xact_lock(91144,1)"
    )
    assert sql.index("pg_advisory_xact_lock(91144,1)") < sql.index(
        "INSERT INTO model_admission.protocols"
    )
    for guard in (
        "admission_actor_denied",
        "admission_source_stale",
        "admission_final_already_exposed",
        "admission_protocol_already_frozen",
    ):
        assert guard in sql
