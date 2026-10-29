"""Mock native authority with actual private /3 material; no real certificate or model call."""

# ruff: noqa: F811
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from test_package_business_shadow import mirror  # noqa: F401
from test_package_feature_training_io import cohort  # noqa: F401
from test_package_model_certification import NOW, fixture
from test_package_model_observation import material  # noqa: F401

from packages.domain.review_identity import digest
from packages.model_governance.common import GovernanceError
from packages.package_model_certification import policy
from packages.package_model_live import producer
from packages.package_prediction.application import Predictions, method_digest


class Authority:
    def __init__(self, packet):
        self.packet = packet
        self.receipt = None
        self.active = False
        self.transitions = []
        self.revoke = False

    @contextmanager
    def __call__(self):
        assert not self.active
        self.active = True
        self.transitions.append("begin")
        try:
            yield self
        finally:
            self.active = False
            self.transitions.append("end")

    def now(self):
        return NOW

    def prepare(self, actor, bid, scope, certificate, method, cert_method):
        assert self.active
        if actor != "owner":
            policy.admission.fail()
        value = deepcopy(self.packet)
        value["method_digest"] = method
        if self.revoke:
            value["authority"]["state"] = "revoked"
        return value

    def read(self, actor, bid, scope, command, method, cert_method):
        if actor != "owner":
            policy.admission.fail()
        return deepcopy(self.receipt)

    def commit(self, actor, bid, scope, certificate, command, pinned, result, method, cert_method):
        assert self.active and not self.revoke
        assert 0 <= float(result["low"]) <= float(result["value"]) <= float(result["high"]) <= 100
        assert result["interval_level"] == "0.8"
        assert result["training_groups"]["fit"] >= 3
        self.receipt = {
            "schema": "package-formal-prediction/1",
            "certificate_id": str(certificate),
            "state": "valid",
            "value": result["value"],
            "command_id": str(command),
        }
        return deepcopy(self.receipt)


def setup():
    source, model, body = fixture()
    certificate = str(uuid4())
    return {
        "authority": {
            "certificate": {
                "id": certificate,
                "model_id": model,
                "request": body,
                "source_digest": digest(source),
                "method_digest": policy.method_digest(),
            },
            "state": "active",
            "source": source,
        },
        "reference": {},
        "method_digest": method_digest(),
    }, certificate


def compute(packet):
    return {
        "schema": "package-business-shadow-result/1",
        "formal_eligibility": "unavailable",
        "certification_issued": False,
        "packet_digest": digest(packet),
        "mode": "live",
        "source_digest": digest(packet["source"]),
        "artifact_digest": digest(packet["artifact"]),
        "model_id": packet["artifact"]["model_id"],
        "input_digest": packet["source"]["input_digest"],
        "producer_method_digest": producer.method_digest(),
        "projection_digest": "a" * 64,
        "value": "50",
    }


def test_real_private_material_consumer_with_mock_authority(mirror):
    root, index, material_packet = mirror
    packet, cert = setup()
    src = deepcopy(material_packet["source"])
    src["mode"] = "live"
    authority = packet["authority"]
    source = authority["source"]
    source["current_source"] = src
    for event in ("shadow", "rollback"):
        source[event]["source"] = deepcopy(src)
        source[event]["result"]["source_digest"] = digest(src)
        source[event]["result"]["input_digest"] = src["input_digest"]
    authority["certificate"]["source_digest"] = digest(source)
    packet["reference"] = material_packet["reference"]
    tx = Authority(packet)

    def executor(p):
        assert not tx.active
        return producer.Executor(root, index)(p)

    service = Predictions(tx, executor)
    bid, scope, command = str(uuid4()), str(uuid4()), str(uuid4())
    receipt = service.execute("owner", bid, scope, cert, command)
    assert receipt["state"] == "valid" and 0 <= float(receipt["value"]) <= 100
    assert service.execute("owner", bid, scope, cert, command) == receipt
    assert tx.transitions == ["begin", "end", "begin", "end", "begin", "end"]


@pytest.mark.parametrize(
    "attack",
    [
        "revoked_before",
        "revoked_after",
        "expired",
        "synthetic",
        "wrong_model",
        "wrong_input",
        "wrong_value",
        "mutated_packet",
        "wrong_certificate_replay",
        "other_member",
    ],
)
def test_rejects_ineligible_or_drifting_predictions(attack):
    packet, cert = setup()
    tx = Authority(packet)
    if attack == "revoked_before":
        tx.revoke = True
    if attack == "expired":
        packet["authority"]["certificate"]["request"]["valid_until"] = NOW
    if attack == "synthetic":
        packet["authority"]["source"]["current_source"]["mode"] = "synthetic"

    def executor(p):
        assert not tx.active
        result = compute(p)
        if attack == "revoked_after":
            tx.revoke = True
        if attack == "wrong_model":
            result["model_id"] = str(uuid4())
        if attack == "wrong_input":
            result["input_digest"] = "b" * 64
        if attack == "wrong_value":
            result["value"] = "NaN"
        if attack == "mutated_packet":
            p["source"]["mode"] = "synthetic"
        return result

    service = Predictions(tx, executor)
    args = ("owner", str(uuid4()), str(uuid4()), cert, str(uuid4()))
    if attack == "wrong_certificate_replay":
        tx.receipt = {"certificate_id": str(uuid4())}
    if attack == "other_member":
        args = ("other", *args[1:])
    with pytest.raises(GovernanceError):
        service.execute(*args)
    if attack != "wrong_certificate_replay":
        assert tx.receipt is None
    assert not tx.active


def test_default_has_no_executor_and_never_writes():
    packet, cert = setup()
    tx = Authority(packet)
    with pytest.raises(GovernanceError):
        Predictions(tx).execute("owner", str(uuid4()), str(uuid4()), cert, str(uuid4()))
    assert tx.receipt is None


def test_native_guard_scope_and_no_cherry_picking():
    from pathlib import Path

    sql = Path("deploy/sql/package-formal-prediction.sql").read_text()
    for requirement in (
        "scope_id uuid NOT NULL UNIQUE",
        "package_model_admission.read_certificate",
        "package_prediction.prepare",
        "design.outcomes",
        "related_entities",
        "p.created_at<s.submitted_at",
        "jsonb_array_length(matches) IS DISTINCT FROM 1",
        "show_prediction",
        "certificate_revocations",
        "design.append_only()",
    ):
        assert requirement in sql
    assert "CREATE ROLE" not in sql


def test_http_default_closed_and_server_injected_path(monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from apps.api import package_prediction_routes as routes
    from packages.domain.errors import DomainError

    packet, cert = setup()
    tx = Authority(packet)
    writes = []
    monkeypatch.setattr(
        routes, "auth", lambda request, write=False: writes.append(write) or {"member_id": "owner"}
    )
    app = FastAPI()
    app.include_router(routes.router)

    @app.exception_handler(DomainError)
    async def error(_, e):
        return JSONResponse({"code": e.code}, status_code=e.status)

    client = TestClient(app)
    bid, scope, command = str(uuid4()), str(uuid4()), str(uuid4())
    url = f"/api/v1/bids/{bid}/technical-scopes/{scope}/formal-predictions"
    body = {"certificate_id": cert, "command_id": command}
    assert client.post(url, json=body).status_code == 503
    assert client.post(url, json={**body, "verified": True}).status_code == 422
    app.state.package_prediction_service = Predictions(tx, compute)
    assert client.post(url, json=body).json()["state"] == "valid"
    assert writes == [True, True]


def test_metrics_consumes_official_authority_and_rejects_late_or_unverified_labels(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from packages.package_prediction import metrics

    at = datetime(2026, 1, 10, tzinfo=timezone.utc)
    outcome = {
        "id": "outcome",
        "known_at": datetime(2026, 1, 8, tzinfo=timezone.utc),
        "score_kind": "technical_total",
        "value": "80",
        "maximum": "100",
    }

    def execute(sql, params=None):
        if "to_regprocedure" in sql:
            value = {"ready": True}
        elif "submission_pair" in sql:
            value = {
                "value": {"value": "75", "maximum": "100", "created_at": "2026-01-06T00:00:00Z"}
            }
        elif "outcome_heads" in sql:
            value = outcome
        else:
            value = {"created_at": datetime(2026, 1, 9, tzinfo=timezone.utc)}
        return SimpleNamespace(fetchone=lambda: value)

    c = SimpleNamespace(execute=execute)
    submission = {"id": "submission", "settings": {"show_prediction": True}}
    monkeypatch.setattr(metrics, "outcome_view", lambda *_: {"verification": "verified"})
    monkeypatch.setattr(metrics, "outcome_reasons", lambda *_: [])
    monkeypatch.setattr(metrics, "submission_identity", lambda *_: {"status": "confirmed"})
    pair, reason = metrics.eligible_pair(c, submission, at)
    assert pair["predicted"] == "75" and pair["official"] == "80" and reason is None
    monkeypatch.setattr(metrics, "outcome_view", lambda *_: {"verification": "pending"})
    assert metrics.eligible_pair(c, submission, at) == (None, "official_outcome_unverified")
    outcome["known_at"] = datetime(2026, 1, 5, tzinfo=timezone.utc)
    assert metrics.eligible_pair(c, submission, at) == (
        None,
        "label_known_before_prediction_freeze",
    )
    submission["settings"]["show_prediction"] = False
    outcome["known_at"] = datetime(2026, 1, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(metrics, "outcome_view", lambda *_: {"verification": "verified"})
    assert metrics.eligible_pair(c, submission, at)[0]["predicted"] == "75"
