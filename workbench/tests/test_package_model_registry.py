"""Synthetic artifact/consumer checks, not native registry or predictive-quality approval."""

import json
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from test_package_feature_training import data, fit
from test_package_feature_training_io import (  # noqa: F401 -- shared real /3 CAS fixture
    cohort,
    pins,
)

from apps.api import package_model_registry_routes as routes
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import DomainError
from packages.model_governance import artifacts as legacy
from packages.model_governance import package_feature_training as training
from packages.model_governance import package_feature_training_io as training_io
from packages.model_governance.common import GovernanceError
from packages.package_model_registry import artifact
from packages.package_model_registry.application import Registry
from packages.storage.private_cas import PrivateContentStore, sha


def source(candidate=None, bundle=None):
    if candidate is None:
        bundle, projections = data()
        candidate = fit(bundle, projections)
    return {
        "schema": artifact.SNAPSHOT,
        "training_job_id": str(uuid4()),
        "cohort_id": bundle["cohort_id"],
        "cohort_digest": "a" * 64,
        "membership_digest": candidate["membership_digest"],
        "protocol_digest": "b" * 64,
        "result_digest": "c" * 64,
        "candidate": candidate,
        "candidate_digest": digest(candidate),
        "origin": candidate["origin"],
    }


@pytest.mark.parametrize(
    "attack",
    [
        "order",
        "schema",
        "method",
        "alpha",
        "scales",
        "means",
        "coefficients",
        "intercept",
        "selection",
        "interval",
        "groups",
        "accepted",
        "candidate_version",
        "origin",
    ],
)
def test_rejects_candidate_corruption_even_if_outer_digest_is_recomputed(attack):
    packet = source()
    c = packet["candidate"]
    if attack == "order":
        c["feature_names"].reverse()
    elif attack == "schema":
        c["feature_schema"] = "complete-three-band-features/1"
    elif attack == "method":
        c["method_digest"] = "e" * 64
    elif attack == "alpha":
        c["model"]["alpha"] = "999"
    elif attack == "scales":
        c["model"]["scales"][0] = "0"
    elif attack == "means":
        c["model"]["means"][0] = "100"
    elif attack == "coefficients":
        c["model"]["coefficients"][0] = "NaN"
    elif attack == "intercept":
        c["model"]["intercept"] = True
    elif attack == "selection":
        c["selection"]["refit_with_development"] = True
    elif attack == "interval":
        c["intervals"]["0.9"]["rank"] = 1
    elif attack == "groups":
        c["groups"]["calibration"] = True
    elif attack == "accepted":
        c["formal_prediction_eligible"] = True
    elif attack == "candidate_version":
        c["version"] = "frozen-training-result/1"
    else:
        packet["origin"] = "external_evidence"
    c["model_digest"] = digest(c["model"])
    packet["candidate_digest"] = digest(c)
    with pytest.raises(GovernanceError):
        artifact.build(packet)


def test_old_and_new_versions_stay_separate_with_fixed_method_and_bytes():
    document = artifact.build(source())
    raw = canonical(document)
    assert artifact.load(raw, sha(raw)) == document
    with pytest.raises(GovernanceError):
        legacy.validate(document)
    changed = deepcopy(document)
    changed["schema"] = "registered-score-artifact/1"
    with pytest.raises(GovernanceError):
        artifact.validate(changed)
    changed = deepcopy(document)
    changed["feature_contract"]["target_scale"] = "original_points"
    with pytest.raises(GovernanceError):
        artifact.validate(changed)
    changed = deepcopy(document)
    changed["adapter_method_digest"] = "e" * 64
    with pytest.raises(GovernanceError):
        artifact.validate(changed)
    with pytest.raises(GovernanceError):
        artifact.load(raw + b" ", sha(raw))
    with pytest.raises(GovernanceError):
        artifact.load(b'{"schema":1,"schema":2}', sha(b'{"schema":1,"schema":2}'))


class Tx:
    def __init__(self, packet):
        self.packet, self.saved = packet, None

    def source(self, job, actor):
        return self.packet

    def register(self, job, actor, document, key, reason):
        self.saved = {"document": document, "artifact_digest": digest(document)}
        return self.saved

    def read(self, model, actor):
        return self.saved


def test_registry_build_and_compare_happen_in_one_owned_transaction():
    tx, events = Tx(source()), []

    @contextmanager
    def transactions():
        events.append("open")
        try:
            yield tx
        finally:
            events.append("close")

    registry = Registry(transactions)
    job = tx.packet["training_job_id"]
    preview = registry.preview(job, "actor")
    assert (
        registry.register(job, "actor", "key", "synthetic", digest(preview))["document"] == preview
    )
    assert registry.read(preview["model_id"], "actor")["document"] == preview
    tx.packet["cohort_digest"] = "d" * 64
    with pytest.raises(GovernanceError):
        registry.register(job, "actor", "key", "synthetic", digest(preview))
    assert events == ["open", "close"] * 4


def test_api_uses_authenticated_actor_and_explicit_versioned_paths(monkeypatch):
    packet, calls = source(), []
    tx = Tx(packet)

    @contextmanager
    def transactions():
        yield tx

    monkeypatch.setattr(routes, "service", lambda: Registry(transactions))

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
        prefix = f"/api/v1/package-model-registry/training-jobs/{packet['training_job_id']}"
        preview = client.get(prefix + "/preview").json()
        payload = {"expected_artifact_digest": preview["artifact_digest"], "reason": "synthetic"}
        assert client.post(prefix + "/registration", json=payload).status_code == 409
        registered = client.post(
            prefix + "/registration", json=payload, headers={"Idempotency-Key": "key"}
        )
        assert registered.status_code == 200
        assert registered.json()["document"]["formal_eligibility"] == "unavailable"
    assert calls == [False, True, True]


def test_real_cas_material_revalidation_inference_and_cli_receipt_recovery(cohort, tmp_path):  # noqa: F811
    root, index, _, selection, labels, export, _ = cohort
    sr, lr, expected = pins(selection, labels)
    results = tmp_path / "predictions"
    results.mkdir(mode=0o700)
    with PrivateContentStore(root) as store:
        result = training_io.assemble(store, index, sr, lr, **expected)
        doc = artifact.build(source(result["complete_feature_training"], export["training_export"]))
        model_digest = digest(doc)
        receipt_path = tmp_path / "registry-receipt"
        receipt_path.write_bytes(
            canonical(
                {
                    "schema": "registered-package-score-receipt/1",
                    "model_id": doc["model_id"],
                    "document": doc,
                    "artifact_digest": model_digest,
                    "created_at": "2026-10-26T00:00:00Z",
                    "research_only": True,
                    "formal_eligibility": "unavailable",
                    "certification_issued": False,
                }
            )
        )
        receipt_path.chmod(0o600)
        ref = selection["members"][-1]["reference"]
        predicted = artifact.consume(
            doc, store, index, ref, expected_input_digest=ref["expected_input_digest"]
        )
        assert (
            predicted["formal_eligibility"] == "unavailable"
            and not predicted["formal_prediction_eligible"]
        )
        assert 0 <= float(predicted["value"]) <= 100
        loaded = artifact.handoff.load(store, index, **ref)
        assert float(predicted["value"]) == training.predict(
            doc["source"]["candidate"]["model"], training.project(loaded)["values"]
        )
        with pytest.raises(GovernanceError):
            artifact.consume(doc, store, index, ref, expected_input_digest="e" * 64)
        wrong = dict(ref, expected_binding_digest="e" * 64)
        with pytest.raises(GovernanceError):
            artifact.consume(
                doc, store, index, wrong, expected_input_digest=ref["expected_input_digest"]
            )
    request = {
        "version": "registered-package-research-request/1",
        "command_id": str(uuid4()),
        "artifact_digest": model_digest,
        "reference": ref,
        "expected_input_digest": ref["expected_input_digest"],
    }
    path = tmp_path / "request"
    raw = canonical(request)
    path.write_bytes(raw)
    path.chmod(0o600)
    args = [
        sys.executable,
        "deploy/package_registered_prediction.py",
        "--store",
        str(root),
        "--artifact-dir",
        str(index),
        "--result-dir",
        str(results),
        "--request",
        str(path),
        "--expected-request-digest",
        sha(raw),
    ]
    first = subprocess.run(
        args + ["--registry-receipt", str(receipt_path)], capture_output=True, text=True, check=True
    )  # nosec B603
    second = subprocess.run(args, capture_output=True, text=True, check=True)  # nosec B603
    a, b = json.loads(first.stdout), json.loads(second.stdout)
    assert not a["replayed"] and b["replayed"] and a["result_digest"] == b["result_digest"]
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    rejected = subprocess.run(args, capture_output=True, text=True)  # nosec B603
    assert rejected.returncode == 2 and str(tmp_path) not in rejected.stdout + rejected.stderr


def test_sql_requires_native_source_and_never_writes_legacy_certificates():
    sql = (Path(__file__).parents[1] / "deploy/sql/package-model-registry.sql").read_text()
    for guard in (
        "assert_role('api')",
        "current_cohort(cohort.id)",
        "package_history_exposure_bridge.readiness()",
        "stored.document IS DISTINCT FROM document",
        "stored.request_key IS DISTINCT FROM request_key",
    ):
        assert guard in sql
    assert "INSERT INTO model_release" not in sql and "CREATE ROLE" not in sql


def test_top_level_boolean_cannot_be_relabelled_as_integer():
    document = artifact.build(source())
    document["research_only"] = 1
    with pytest.raises(GovernanceError):
        artifact.validate(document)
    raw = canonical(document)
    with pytest.raises(GovernanceError):
        artifact.load(raw, sha(raw))
