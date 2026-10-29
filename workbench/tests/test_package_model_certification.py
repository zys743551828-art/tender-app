"""Mock authority only: fixtures never mint native or production certificates."""

from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from test_package_model_admission import context, document, packet
from test_package_model_registry import source

from packages.domain.review_identity import digest
from packages.model_governance.common import GovernanceError
from packages.package_model_certification import policy
from packages.package_model_certification.application import Certificates

NOW = "2026-01-05T00:00:00Z"


def fixture():
    def model():
        src = source()
        src["origin"] = src["candidate"]["origin"] = "external_evidence"
        src["candidate_digest"] = digest(src["candidate"])
        return policy.artifact.build(src)

    candidate, fallback = model(), model()
    ctx = context()
    ctx["binding"].update(
        model_id=candidate["model_id"],
        artifact_digest=digest(candidate),
        candidate_digest=candidate["source"]["candidate_digest"],
    )
    report = packet(document(ctx))
    report["report"]["origin"] = "external_evidence"
    binding = {
        "schema": "score-business-admission-protocol/3",
        "protocol": report["protocol"],
        "protocol_digest": report["protocol_digest"],
        "evidence_contract": policy.producer.contract(),
    }
    src = {
        "mode": "live",
        "producer_method_digest": policy.producer.method_digest(),
        "input_digest": "f" * 64,
    }
    route = str(uuid4())

    def event(doc, revision):
        return {
            "command_id": str(uuid4()),
            "route_id": route,
            "revision": revision,
            "action": "consume" if revision == 1 else "rollback",
            "previous_model_id": candidate["model_id"],
            "selected_model_id": doc["model_id"],
            "created_at": f"2026-01-0{revision + 2}T01:00:00Z",
            "source": deepcopy(src),
            "result": {
                "schema": "package-business-shadow-result/1",
                "mode": "live",
                "producer_method_digest": policy.producer.method_digest(),
                "source_digest": digest(src),
                "input_digest": src["input_digest"],
                "model_id": doc["model_id"],
                "artifact_digest": digest(doc),
                "formal_eligibility": "unavailable",
                "certification_issued": False,
            },
        }

    shadow, rollback = event(candidate, 1), event(fallback, 2)
    value = {
        "schema": "package-certification-source/1",
        "model": candidate,
        "fallback_model": fallback,
        "report": report,
        "binding": {
            "document": binding,
            "digest": digest(binding),
            "frozen_at": "2026-01-01T00:00:00Z",
        },
        "shadow": shadow,
        "rollback": rollback,
        "current_source": src,
        "captured_at": "2026-01-03T00:00:00Z",
        "evidence_valid_until": "2026-01-07T00:00:00Z",
    }
    body = {
        "shadow_event_id": shadow["command_id"],
        "rollback_event_id": rollback["command_id"],
        "valid_until": "2026-01-06T00:00:00Z",
        "reason": "isolated mechanism fixture",
    }
    return value, candidate["model_id"], body


def test_mock_native_live_positive_is_not_prediction():
    value, model, body = fixture()
    assert policy.assess(value, model, body, NOW)["artifact_digest"] == digest(value["model"])


@pytest.mark.parametrize(
    "attack",
    [
        "synthetic",
        "retrospective",
        "threshold",
        "expired",
        "overlong",
        "binding",
        "source",
        "fallback",
        "time",
        "method",
    ],
)
def test_evidence_rejected(attack):
    value, model, body = fixture()
    if attack in {"synthetic", "retrospective"}:
        value["current_source"]["mode"] = attack
    elif attack == "threshold":
        value["report"]["report"]["report"]["project_mae"] = "10.01"
    elif attack == "expired":
        body["valid_until"] = NOW
    elif attack == "overlong":
        body["valid_until"] = "2027-01-01T00:00:00Z"
    elif attack == "binding":
        value["binding"]["document"]["protocol_digest"] = "0" * 64
    elif attack == "source":
        value["rollback"]["source"]["input_digest"] = "0" * 64
    elif attack == "fallback":
        value["rollback"]["selected_model_id"] = model
    elif attack == "time":
        value["captured_at"] = "2025-01-01T00:00:00Z"
    elif attack == "method":
        value["shadow"]["result"]["producer_method_digest"] = "0" * 64
    with pytest.raises(GovernanceError):
        policy.assess(value, model, body, NOW)


class FakeAuthority:
    def __init__(self, value):
        self.value = value
        self.record = None
        self.owner = "owner"
        self.key = None
        self.clock = NOW

    @contextmanager
    def __call__(self):
        yield self

    def now(self):
        return self.clock

    def check(self, actor):
        if actor != self.owner:
            raise GovernanceError("DENIED", "denied")

    def source(self, actor, model, body):
        self.check(actor)
        return deepcopy(self.value)

    def replay(self, actor, model, body, key, expected, method):
        self.check(actor)
        if self.record:
            if key != self.key or body != self.record["certificate"]["request"]:
                raise GovernanceError("CONFLICT", "conflict")
            return self.read(actor, "id", method)

    def issue(self, actor, model, body, key, expected, method):
        self.key = key
        self.record = {
            "certificate": {
                "id": "id",
                "model_id": model,
                "request": deepcopy(body),
                "source_digest": expected,
                "method_digest": method,
            },
            "state": "active",
            "source": deepcopy(self.value),
        }
        return deepcopy(self.record)

    def read(self, actor, certificate, method):
        self.check(actor)
        result = deepcopy(self.record)
        result["source"] = deepcopy(self.value)
        return result

    def revoke(self, actor, certificate, key, reason, method):
        self.check(actor)
        self.record["state"] = "revoked"
        return deepcopy(self.record)


def test_issue_lost_ack_replay_stale_and_terminal_revocation():
    value, model, body = fixture()
    tx = FakeAuthority(value)
    app = Certificates(tx)
    key = str(uuid4())
    preview = app.preview("owner", model, body)
    first = app.issue("owner", model, body, key, preview["source_digest"])
    assert first["eligible"] and not first["prediction_issued"]
    assert app.issue("owner", model, body, key, preview["source_digest"]) == first
    with pytest.raises(GovernanceError):
        app.issue("owner", model, body, str(uuid4()), preview["source_digest"])
    with pytest.raises(GovernanceError):
        app.read("other", "id")
    tx.value["current_source"]["mode"] = "synthetic"
    assert app.read("owner", "id")["state"] == "stale"
    assert app.revoke("owner", "id", str(uuid4()), "withdraw")["state"] == "revoked"
    assert app.issue("owner", model, body, key, preview["source_digest"])["state"] == "revoked"


def test_request_rejects_client_authority():
    _, _, body = fixture()
    body["verified"] = True
    with pytest.raises(GovernanceError):
        policy.request(body)


def test_http_closed_requests_auth_and_receipts(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from apps.api import package_model_certification_routes as routes

    calls = []
    monkeypatch.setattr(
        routes, "auth", lambda request, write=False: calls.append(write) or {"member_id": "owner"}
    )

    class Service:
        def preview(self, *args):
            return {"certification_issued": False}

        def issue(self, *args):
            return {"state": "active", "prediction_issued": False}

        def read(self, *args):
            return {"state": "expired", "eligible": False}

        def revoke(self, *args):
            return {"state": "revoked", "eligible": False}

    monkeypatch.setattr(routes, "service", Service)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    model = str(uuid4())
    base = "/api/v1/package-model-certification"
    body = {
        "shadow_event_id": str(uuid4()),
        "rollback_event_id": str(uuid4()),
        "valid_until": "2026-01-06T00:00:00Z",
        "reason": "fixture",
    }
    assert (
        client.post(f"{base}/models/{model}/preview", json={**body, "verified": True}).status_code
        == 422
    )
    assert (
        client.post(f"{base}/models/{model}/preview", json=body).json()["certification_issued"]
        is False
    )
    assert (
        client.post(
            f"{base}/models/{model}/certificates", json={**body, "expected_source_digest": "a" * 64}
        ).json()["state"]
        == "active"
    )
    assert client.get(f"{base}/certificates/{model}").json()["state"] == "expired"
    assert (
        client.post(f"{base}/certificates/{model}/revoke", json={"reason": "withdraw"}).json()[
            "state"
        ]
        == "revoked"
    )
    assert calls == [True, True, False, True]


def test_native_transaction_releases_on_exception():
    from packages.package_model_certification.infrastructure import NativeTransactions

    lifecycle = []

    @contextmanager
    def connections():
        lifecycle.append("enter")
        try:
            yield object()
        finally:
            lifecycle.append("exit")

    with pytest.raises(RuntimeError), NativeTransactions(connections)():
        raise RuntimeError("cancel")
    assert lifecycle == ["enter", "exit"]


def test_native_sql_uses_existing_authority_and_terminal_unique_model():
    from pathlib import Path

    sql = Path("deploy/sql/package-model-certification.sql").read_text()
    for required in (
        "model_id uuid NOT NULL UNIQUE",
        "package_model_admission.report_source(",
        "package_model_observation.business_source(",
        "package_historical_research.test_environments",
        "certificate_terminal_revocation",
        "design.append_only()",
        "created_xact=frozen.frozen_xact",
        "FOR SHARE",
        "pg_advisory_xact_lock(91143,1)",
    ):
        assert required in sql
    assert "CREATE ROLE" not in sql
