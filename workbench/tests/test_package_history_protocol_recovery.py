"""Original CPU-protocol receipts survive method changes; new uses do not.

These focused route tests replace only the command store and connection. Native
PG coverage remains separate and must exercise the public installation guard.
"""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import UUID

import pytest
from starlette.requests import Request

from apps.api import package_historical_research as routes
from packages.contracts.package_historical_research_api import PackageHistoryProtocolRequest
from packages.domain.runtime import DomainError

ACTOR = UUID("10000000-0000-4000-8000-000000000001")
REQUEST = PackageHistoryProtocolRequest(
    method_digest="a" * 64,
    seed=17,
    bootstrap_iterations=100,
    reason="Explicit synthetic protocol recovery verification",
)
RECEIPT = {
    "body": {"id": "20000000-0000-4000-8000-000000000001", "digest": "b" * 64},
    "status": 201,
    "headers": {"ETag": '"original-protocol-receipt"'},
}


@pytest.fixture
def route_store(monkeypatch):
    command = SimpleNamespace(replay=RECEIPT)
    monkeypatch.setattr(routes, "auth", lambda *_: {"member_id": ACTOR})
    monkeypatch.setattr(routes, "connection", lambda: nullcontext(object()))
    monkeypatch.setattr(routes.repository, "require", lambda *_, **__: None)
    monkeypatch.setattr(routes, "command", lambda *args: command)
    return command


def request():
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def test_original_ack_is_replayed_when_current_method_digest_changed(route_store, monkeypatch):
    monkeypatch.setattr(routes.cpu, "protocol", lambda **_: {"method": {"digest": "c" * 64}})
    response = routes.create_protocol(request(), REQUEST)
    assert response.status_code == 201
    assert json.loads(response.body) == RECEIPT["body"]
    assert response.headers["etag"] == RECEIPT["headers"]["ETag"]
    assert response.headers["idempotency-replayed"] == "true"


def test_original_ack_does_not_execute_the_current_cpu_method(route_store, monkeypatch):
    def unavailable(**_):
        raise AssertionError("A historical ACK must not run the current method factory")

    monkeypatch.setattr(routes.cpu, "protocol", unavailable)
    response = routes.create_protocol(request(), REQUEST)
    assert json.loads(response.body) == RECEIPT["body"]


def test_fresh_request_still_rejects_a_changed_method(route_store, monkeypatch):
    route_store.replay = None
    monkeypatch.setattr(routes.cpu, "protocol", lambda **_: {"method": {"digest": "c" * 64}})
    with pytest.raises(DomainError) as caught:
        routes.create_protocol(request(), REQUEST)
    assert caught.value.code == "PACKAGE_HISTORY_METHOD_CHANGED"


def test_replay_still_requires_current_authentication(route_store, monkeypatch):
    def forbidden(*_):
        raise DomainError("SESSION_REQUIRED", "Synthetic expired session", 401)

    monkeypatch.setattr(routes, "auth", forbidden)
    with pytest.raises(DomainError) as caught:
        routes.create_protocol(request(), REQUEST)
    assert caught.value.code == "SESSION_REQUIRED"


def test_replay_still_requires_installed_read_dependencies(route_store, monkeypatch):
    def missing(*_, **__):
        raise DomainError("PACKAGE_HISTORY_NOT_CONFIGURED", "Synthetic missing schema", 503)

    monkeypatch.setattr(routes.repository, "require", missing)
    with pytest.raises(DomainError) as caught:
        routes.create_protocol(request(), REQUEST)
    assert caught.value.code == "PACKAGE_HISTORY_NOT_CONFIGURED"
