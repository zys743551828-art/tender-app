# ruff: noqa: F811 -- shared pytest fixtures
"""Synthetic mechanism tests. Fake native live packets never enter a real database."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from test_package_feature_training_io import cohort  # noqa: F401
from test_package_model_observation import material  # noqa: F401

from apps.api import package_business_shadow_routes as routes
from packages.domain.errors import DomainError
from packages.domain.review_identity import digest
from packages.model_governance import material_execution_runtime as runtime
from packages.model_governance import material_live_sender as live
from packages.model_governance import package_complete_handoff as handoff
from packages.model_governance.common import GovernanceError
from packages.package_model_live import application, host, producer
from packages.package_model_registry import artifact
from packages.storage.private_cas import PrivateContentStore, sha


@pytest.fixture(scope="module")
def mirror(material):
    root, index, retrospective, old_request = material
    reference = deepcopy(old_request["reference"])
    with PrivateContentStore(root) as store:
        loaded = handoff.load(store, index, **reference)
    metadata = loaded.bundle.context.metadata
    source = {
        "schema": "package-business-shadow-source/1",
        "mode": "synthetic",
        "capture_id": str(uuid4()),
        "producer_method_digest": producer.method_digest(),
        "job_id": str(uuid4()),
        "intent_id": str(uuid4()),
        "input_digest": loaded.bundle.metadata["digest"],
        "context_digest": metadata["digest"],
        **{k: metadata[k] for k in ("bid_id", "scope_id", "scope_digest")},
        "scope_manifest": loaded.bundle.context.origin.material["scope"]["manifest"],
        "originals": [
            {"document_version_id": k, "digest": sha(v), "byte_size": len(v)}
            for k, v in loaded.bundle.context.origin.originals.items()
        ],
        "attempts": [
            {
                "rule_id": a.rule_id,
                "slot": a.slot,
                "attempt_id": a.call_id,
                "request_digest": a.request.receipt["request_digest"],
                "raw_response_digest": a.generation.raw_response_digest,
                "response_id": a.generation.response_id,
            }
            for a in loaded.attempts
        ],
    }
    return (
        root,
        index,
        {"source": source, "reference": reference, "artifact": retrospective["document"]},
    )


def test_actual_originals_and_native_raw_responses_are_consumed_without_send(mirror):
    root, index, packet = mirror
    with PrivateContentStore(root) as store:
        result = producer.consume(packet, store, index)
    assert result["mode"] == "synthetic" and result["packet_digest"] == digest(packet)
    assert 0 <= float(result["value"]) <= 100
    assert result["formal_eligibility"] == "unavailable" and not result["certification_issued"]


def test_trusted_channel_live_branch_is_computed_without_issuing_qualification(mirror):
    # This packet is a unit-test native-channel double, not a captured live event.
    root, index, packet = deepcopy(mirror)
    packet["source"]["mode"] = "live"
    source = packet["artifact"]["source"]
    source["origin"] = source["candidate"]["origin"] = "external_evidence"
    source["candidate_digest"] = digest(source["candidate"])
    packet["artifact"] = artifact.build(source)
    with PrivateContentStore(root) as store:
        result = producer.consume(packet, store, index)
    assert result["mode"] == "live" and not result["certification_issued"]
    assert result["formal_eligibility"] == "unavailable"


@pytest.mark.parametrize(
    "attack",
    [
        "input",
        "context",
        "scope",
        "original",
        "response",
        "request",
        "call",
        "slot",
        "missing",
        "duplicate",
        "retrospective",
        "synthetic_to_live",
    ],
)
def test_forged_or_mixed_native_input_rejected(mirror, attack):
    root, index, packet = deepcopy(mirror)
    source = packet["source"]
    if attack in {"input", "context", "scope"}:
        source[attack + "_digest"] = "e" * 64
    elif attack == "original":
        source["originals"][0]["digest"] = "e" * 64
    elif attack in {"request", "response"}:
        source["attempts"][0][
            "request_digest" if attack == "request" else "raw_response_digest"
        ] = "e" * 64
    elif attack == "call":
        source["attempts"][0]["attempt_id"] = str(uuid4())
    elif attack == "slot":
        source["attempts"][0]["slot"] = 9
    elif attack == "missing":
        source["attempts"].pop()
    elif attack == "duplicate":
        source["attempts"].append(source["attempts"][0])
    else:
        source["mode"] = "retrospective_internal" if attack == "retrospective" else "live"
    with PrivateContentStore(root) as store, pytest.raises(GovernanceError):
        producer.consume(packet, store, index)


class FakeNative:
    def __init__(self, packet):
        self.packet = deepcopy(packet)
        self.saved = None
        self.active = False
        self.revoked = False
        self.calls = []

    @contextmanager
    def transactions(self):
        self.active = True
        try:
            yield self
        finally:
            self.active = False

    def replay(self, actor, body):
        if actor != "actor":
            raise PermissionError()
        if self.saved:
            if self.saved[0] != body:
                raise ValueError("command conflict")
            return self.saved[1]
        return None

    def prepare(self, actor, body):
        if self.revoked:
            raise ValueError("revoked")
        return deepcopy(self.packet)

    def commit(self, actor, body, pin, result):
        if self.revoked or digest(self.packet) != pin:
            raise ValueError("stale")
        self.saved = (
            deepcopy(body),
            {"result_digest": digest(result), "formal_eligibility": "unavailable"},
        )
        return self.saved[1]

    def freeze(self, actor, model, expected, key, contract):
        self.calls.append((actor, model, expected, key, contract))
        return {"digest": digest(contract)}


def command():
    return {
        "version": "package-business-shadow-command/1",
        "command_id": str(uuid4()),
        "route_id": str(uuid4()),
        "action": "observe",
        "expected_revision": 1,
        "producer_method_digest": producer.method_digest(),
    }


def test_two_transactions_replay_revocation_and_atomic_failure(mirror):
    root, index, packet = mirror
    native = FakeNative(packet)
    calls = []

    def execute(value):
        assert not native.active
        calls.append(1)
        return producer.Executor(root, index)(value)

    service = application.Service(native.transactions, execute, enabled=True)
    body = command()
    first = service.execute("actor", body)
    native.revoked = True
    assert service.execute("actor", body) == first and len(calls) == 1
    with pytest.raises(PermissionError):
        service.execute("other", body)
    native.saved = None
    native.revoked = False

    def stale(value):
        result = execute(value)
        native.revoked = True
        return result

    service.executor = stale
    with pytest.raises(ValueError):
        service.execute("actor", command())
    assert native.saved is None and not native.active


@pytest.mark.parametrize("field", ["mode", "verified", "source", "result"])
def test_client_cannot_set_source_purpose_or_result(mirror, field):
    native = FakeNative(mirror[2])
    service = application.Service(native.transactions, None, enabled=True)
    with pytest.raises(GovernanceError):
        service.execute("actor", command() | {field: "live"})
    with pytest.raises(GovernanceError):
        application.Service(native.transactions, None).execute("actor", command())


class Connection:
    @contextmanager
    def transaction(self):
        yield self

    @contextmanager
    def cursor(self, **kwargs):
        yield self

    def execute(self, query):
        assert "pg_backend_pid" in query
        return self

    def fetchone(self):
        return {"pid": 1234}


@pytest.mark.parametrize(
    "mock,state",
    [(True, "qualified_completed"), (False, "qualified_completed"), (True, "billing_unresolved")],
)
def test_host_provenance_is_derived_from_transport_not_message(monkeypatch, mock, state):
    calls = []

    class Tx:
        def begin_capture(self, *args):
            calls.append(("begin", args))
            return "capture"

        def finish_capture(self, *args):
            calls.append(("finish", args))

    @contextmanager
    def transactions():
        yield Tx()

    async def deliver(*args, **kwargs):
        calls.append(("deliver", kwargs))
        return SimpleNamespace(
            observation=SimpleNamespace(metadata={"state": state}), acknowledge=True
        )

    monkeypatch.setattr(runtime, "deliver", deliver)
    sender = live.Sender(
        str(uuid4()),
        str(uuid4()),
        "a" * 64,
        lambda _: pytest.fail("credential must not be read by mirror host"),
        enabled=True,
        transport=httpx.MockTransport(lambda _: pytest.fail("no real delivery in this wiring test"))
        if mock
        else None,
    )
    ports = runtime.QualifiedPorts(
        None, None, None, None, None, Connection(), "development_s3", None, sender
    )
    message = {
        "version": "material-judgment-task/1",
        "event_id": str(uuid4()),
        "job_id": str(uuid4()),
        "generation": 1,
    }
    with pytest.raises(ValueError):
        asyncio.run(
            host.Host(transactions).deliver(
                "actor", None, message, qualified_ports=ports, expected_method_digest="a" * 64
            )
        )
    result = asyncio.run(
        host.Host(transactions, True).deliver(
            "actor", None, message, qualified_ports=ports, expected_method_digest="a" * 64
        )
    )
    assert calls[0][1][-2:] == ("synthetic" if mock else "live", 1234)
    assert result.capture_completed == (state == "qualified_completed")
    assert [c[0] for c in calls] == (
        ["begin", "deliver", "finish"] if state == "qualified_completed" else ["begin", "deliver"]
    )
    assert result.delivery.acknowledge


def test_api_is_default_off_and_binds_authenticated_actor(monkeypatch, mirror):
    app = FastAPI()
    app.include_router(routes.router)
    monkeypatch.setattr(routes, "auth", lambda request, write=False: {"member_id": "actor"})

    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    native = FakeNative(mirror[2])
    with TestClient(app) as client:
        body = command()
        assert (
            client.post(
                "/api/v1/package-business-shadow/actions", json={"command": body}
            ).status_code
            == 503
        )
        app.state.business_shadow_service = application.Service(
            native.transactions, lambda _: {"internal": "synthetic"}, enabled=True
        )
        assert (
            client.post(
                "/api/v1/package-business-shadow/actions", json={"command": body, "mode": "live"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/package-business-shadow/actions", json={"command": body}
            ).status_code
            == 200
        )
        assert native.saved[0] == body


def test_native_sql_sources_and_binding_have_no_client_verified_or_qualification_grant():
    from pathlib import Path

    sql = (Path(__file__).parents[1] / "deploy/sql/package-business-shadow.sql").read_text()
    for guard in [
        "capture.executor_pid<>pg_backend_pid()",
        "capture.executor_login<>session_user",
        "business_shadow_prior_execution_not_live_evidence",
        "state='completed' AND held_minor=0",
        "'billing_state' IS DISTINCT FROM 'usage_reported'",
        "'raw_response_digest',encode(sha256(o.raw_response)",
        "business_evidence_final_already_exposed",
        "pg_current_xact_id()",
        "business_shadow_training_project_leak",
        "packet:=package_model_route.business_prepare",
        "design.package_technical_digest(packet) IS DISTINCT FROM pinned",
    ]:
        assert guard in sql
    assert "CREATE ROLE" not in sql and "INSERT INTO design.model_routes" not in sql
    assert (
        "INSERT INTO package_model_observation.events" in sql
        and "INSERT INTO package_model_route.events" in sql
    )
    assert "'mode',c.mode" in sql and "'certification_issued',false" in sql


def test_business_route_switch_consumes_fixed_fallback_and_rejects_old_revision(mirror):
    root, index, base = deepcopy(mirror)
    candidate = base["artifact"]
    other = deepcopy(candidate["source"])
    other["training_job_id"] = str(uuid4())
    other["candidate"]["model"]["intercept"] = "80"
    other["candidate"]["model_digest"] = digest(other["candidate"]["model"])
    other["candidate_digest"] = digest(other["candidate"])
    fallback = artifact.build(other)

    class RouteNative(FakeNative):
        revision = 0
        selected = None
        config = None
        rolled_back = False
        events = None

        def replay(self, actor, body):
            if actor != "actor":
                raise PermissionError()
            if self.events and body["command_id"] in self.events:
                old, value = self.events[body["command_id"]]
                if old != body:
                    raise ValueError("command conflict")
                return value

        def prepare(self, actor, body):
            if body["expected_revision"] != self.revision:
                raise ValueError("revision")
            if body["action"] == "activate":
                if self.revision:
                    raise ValueError("already active")
                chosen = candidate
            elif body["action"] == "rollback":
                if self.rolled_back:
                    raise ValueError("already rolled back")
                chosen = fallback
            else:
                chosen = self.selected
            return deepcopy(base) | {"artifact": chosen, "revision": self.revision + 1}

        def commit(self, actor, body, pinned, result):
            packet = self.prepare(actor, body)
            if digest(packet) != pinned or result["model_id"] != packet["artifact"]["model_id"]:
                raise ValueError("drift")
            self.revision += 1
            self.selected = packet["artifact"]
            self.rolled_back |= body["action"] == "rollback"
            value = {
                "selected_model_id": self.selected["model_id"],
                "revision": self.revision,
                "result_digest": digest(result),
                "mode": result["mode"],
                "formal_eligibility": "unavailable",
            }
            if self.events is None:
                self.events = {}
            self.events[body["command_id"]] = deepcopy(body), value
            return value

    native = RouteNative(base)
    service = application.Service(native.transactions, producer.Executor(root, index), enabled=True)
    activate = command() | {
        "action": "activate",
        "expected_revision": 0,
        "config": {
            "candidate_model_id": candidate["model_id"],
            "fallback_model_id": fallback["model_id"],
            "intent_id": base["source"]["intent_id"],
            "reference": base["reference"],
            "binding_digest": "a" * 64,
        },
    }
    first = service.execute("actor", activate)
    rollback = {k: v for k, v in activate.items() if k != "config"} | {
        "action": "rollback",
        "expected_revision": 1,
        "command_id": str(uuid4()),
    }
    second = service.execute("actor", rollback)
    third = service.execute(
        "actor",
        rollback | {"action": "observe", "expected_revision": 2, "command_id": str(uuid4())},
    )
    assert first["selected_model_id"] == candidate["model_id"]
    assert second["selected_model_id"] == third["selected_model_id"] == fallback["model_id"]
    assert second["mode"] == "synthetic" and second["formal_eligibility"] == "unavailable"
    assert service.execute("actor", rollback) == second
    with pytest.raises(ValueError):
        service.execute("actor", rollback | {"command_id": str(uuid4())})


def test_freeze_uses_server_contract_and_preserves_explicit_protocol_digest(mirror):
    native = FakeNative(mirror[2])
    model_id, key = str(uuid4()), str(uuid4())
    application.Service(native.transactions, None).freeze("actor", model_id, "e" * 64, key)
    actor, model, expected, command_id, contract = native.calls[0]
    assert (actor, model, expected, command_id) == ("actor", model_id, "e" * 64, key)
    assert contract == producer.contract()
    assert "thresholds" not in contract


def test_live_enrollment_must_follow_protocol_freeze_not_backfill_old_runs():
    from pathlib import Path

    sql = (Path(__file__).parents[1] / "deploy/sql/package-business-shadow.sql").read_text()
    assert "captured.created_at>binding.frozen_at" in sql
    assert "THEN kind:='synthetic'; END IF" in sql
    assert "package_historical_research.test_environments" in sql
    assert "capture.executor_backend_start IS DISTINCT FROM" in sql
    assert "bids IS DISTINCT FROM actual_bids" in sql
    assert "material_qualification.heads h WHERE h.record_id=i.qualification_id FOR SHARE" in sql
