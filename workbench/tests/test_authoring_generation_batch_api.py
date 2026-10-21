"""Actual route exposure and the read/write boundary for multi-section candidates."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api import authoring_generation_batches as routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.domain.runtime import DomainError


def test_registered_batch_routes_require_session_and_explicit_write_headers():
    actual = implemented_openapi(app)
    base = "/api/v1" + routes.BASE
    paths = (
        ("/api/v1/authoring/generation-batch-capabilities", "get"),
        (base, "get"),
        (base, "post"),
        (base + "/{batch_id}", "get"),
        (base + "/{batch_id}/candidates/{action_id}", "get"),
        (base + "/{batch_id}/retry", "post"),
        (base + "/{batch_id}/resolve", "post"),
    )
    for path, method in paths:
        operation = actual["paths"][path][method]
        assert operation["security"] == [{"SessionCookie": []}]
        if method == "post":
            required = {field["name"] for field in operation["parameters"] if field.get("required")}
            assert {"Origin", "X-CSRF-Token", "Idempotency-Key"} <= required
            if path != base + "/{batch_id}/resolve":
                assert "If-Match" in required
        else:
            assert "requestBody" not in operation
    history = actual["paths"][base]["get"]
    limit = next(field for field in history["parameters"] if field["name"] == "limit")
    assert limit["schema"]["maximum"] == 50


@pytest.fixture
def read_port(monkeypatch):
    state = {"open": False, "reads": [], "auth": []}

    @contextmanager
    def connection():
        assert not state["open"]
        state["open"] = True
        try:
            yield SimpleNamespace(
                execute=lambda statement: (
                    None
                    if statement == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    else pytest.fail("History and previews must not acquire write locks")
                )
            )
        finally:
            state["open"] = False

    def auth(*args):
        state["auth"].append(args)
        return {"member_id": str(UUID(int=99))}

    def read(kind):
        def run(_c, *scope, **options):
            assert state["open"]
            state["reads"].append((kind, scope, options))
            return {
                "kind": kind,
                "etag": '"batch-read-immutable-result"',
                "base_draft_etag": '"draft-frozen-writing-base"',
            }

        return run

    monkeypatch.setattr(routes, "connection", connection)
    monkeypatch.setattr(routes, "auth", auth)
    port = SimpleNamespace(
        **{name: read(name) for name in ("capabilities", "history", "load", "candidate")}
    )
    monkeypatch.setattr(routes, "service", lambda: port)
    return state


def test_historical_reads_are_scoped_read_only_and_do_not_expose_draft_cas_as_read_etag(
    read_port,
):
    ids = [UUID(int=value) for value in range(1, 5)]
    assert routes.capabilities(None).headers["cache-control"] == "private, no-store"
    routes.history(*ids[:2], None, cursor="cursor-for-this-draft", limit=7)
    detail = routes.detail(*ids[:3], None)
    candidate = routes.candidate(*ids, None)
    for result in (detail, candidate):
        value = json.loads(result.body)
        assert result.headers["etag"] == value["etag"]
        assert result.headers["etag"] != value["base_draft_etag"]
        assert result.headers["cache-control"] == "private, no-store"
    assert read_port["reads"] == [
        ("capabilities", (), {}),
        ("history", tuple(ids[:2]), {"cursor": "cursor-for-this-draft", "limit": 7}),
        ("load", tuple(ids[:3]), {}),
        ("candidate", tuple(ids), {}),
    ]
    assert not read_port["open"]
    assert all(len(args) == 1 for args in read_port["auth"])


@pytest.mark.parametrize("name", ["create", "retry", "resolve"])
def test_unrecognized_generation_request_is_rejected_before_a_database_transaction(
    monkeypatch, name
):
    authenticated = []

    def auth(_request, write=False):
        authenticated.append(write)
        return {"member_id": UUID(int=99)}

    def unexpected_connection():
        pytest.fail("Invalid body must not reserve budget or queue a generation")

    monkeypatch.setattr(routes, "auth", auth)
    monkeypatch.setattr(routes, "connection", unexpected_connection)
    identity = UUID(int=1)
    args = (identity, identity) if name == "create" else (identity, identity, identity)
    with pytest.raises(DomainError):
        getattr(routes, name)(*args, None, {"unrecognized": "do not queue"})
    assert authenticated == [True]


def test_authentication_failure_precedes_history_or_generation_access(monkeypatch):
    def denied(*_args):
        raise DomainError("AUTH_REQUIRED", "请先登录", 401)

    monkeypatch.setattr(routes, "auth", denied)
    monkeypatch.setattr(routes, "connection", lambda: pytest.fail("Unauthenticated access"))
    identity = UUID(int=1)
    with pytest.raises(DomainError, match="请先登录"):
        routes.detail(identity, identity, identity, None)
    with pytest.raises(DomainError, match="请先登录"):
        routes.create(identity, identity, None, {})
