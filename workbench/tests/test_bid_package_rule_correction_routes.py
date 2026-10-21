"""Actual correction routes preserve scope, request identity and the IO boundary."""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api import bid_package_rule_correction_routes as routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.domain.runtime import DomainError

IDS = tuple(UUID(int=value) for value in range(1, 7))
ACTOR = UUID(int=90)


def request_body():
    return {
        "base_inventory_digest": "a" * 64,
        "base_rule_set_digest": "b" * 64,
        "reason": "人工核对所选权威原页后不采用该条款",
        "changes": [
            {
                "op": "withdraw",
                "rule_id": str(IDS[4]),
                "rule_digest": "c" * 64,
                "evidence_quotes": [{"evidence_id": str(IDS[5]), "quote": "原页明确的适用条件"}],
            }
        ],
    }


def test_actual_routes_separate_read_only_preview_from_conditional_save():
    actual = implemented_openapi(app)
    entries = [
        ("/rule-corrections/preview", "post"),
        ("/rule-corrections", "post"),
        ("/rule-corrections", "get"),
        ("/rule-corrections/{correction_id}", "get"),
        ("/rule-correction-evidence", "get"),
        ("/rule-correction-evidence/{evidence_id}", "get"),
    ]
    for suffix, method in entries:
        operation = actual["paths"][routes.BASE + suffix][method]
        assert operation["security"] == [{"SessionCookie": []}]
        fields = {p["name"] for p in operation["parameters"] if p.get("required")}
        if method == "post":
            assert {"Origin", "X-CSRF-Token"} <= fields
            if suffix == "/rule-corrections":
                assert {"Idempotency-Key", "If-Match"} <= fields
            else:
                assert not {"Idempotency-Key", "If-Match"} & fields
        else:
            assert "requestBody" not in operation


@pytest.fixture
def ports(monkeypatch):
    state = {"open": False, "calls": [], "auth": []}

    @contextmanager
    def connection():
        assert not state["open"]
        state["open"] = True
        try:
            yield SimpleNamespace(
                execute=lambda statement: (
                    None
                    if statement == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    else pytest.fail("Previews and history must be read only")
                )
            )
        finally:
            state["open"] = False

    def auth(_request, write=False):
        state["auth"].append(write)
        return {"member_id": ACTOR}

    def read(name):
        def invoke(_c, scope, *args, **kwargs):
            assert state["open"]
            state["calls"].append((name, scope, args, kwargs))
            return {"read": name}

        return invoke

    service = SimpleNamespace(
        **{
            name: read(name)
            for name in ("preview", "history", "load", "evidence_directory", "evidence_detail")
        }
    )
    monkeypatch.setattr(routes, "auth", auth)
    monkeypatch.setattr(routes, "connection", connection)
    monkeypatch.setattr(routes, "service", lambda: service)
    return state, service


def test_all_reads_keep_the_exact_inventory_scope_and_use_private_uncached_responses(ports):
    state, _ = ports
    responses = [
        routes.preview(*IDS[:4], None, request_body()),
        routes.history(*IDS[:4], None, cursor="this-inventory", limit=7),
        routes.detail(*IDS[:5], None),
        routes.evidence_directory(*IDS[:4], None, cursor=None, limit=11),
        routes.evidence_detail(*IDS[:4], IDS[5], None),
    ]
    assert all(r.headers["cache-control"] == "private, no-store" for r in responses)
    assert all(call[1] == tuple(map(str, IDS[:4])) for call in state["calls"])
    assert state["calls"][2][2] == (str(IDS[4]),)
    assert state["calls"][4][2] == (str(IDS[5]),)
    assert state["auth"] == [True, False, False, False, False]
    assert not state["open"]


def test_apply_keeps_object_io_outside_the_route_transaction_and_preserves_original_headers(ports):
    state, service = ports
    body = {"request": request_body(), "preview_digest": "d" * 64}
    request = SimpleNamespace(headers={"idempotency-key": "original-key", "if-match": '"base"'})

    def apply(scope, actor, key, received, condition, *, final_auth):
        assert not state["open"]
        assert scope == tuple(map(str, IDS[:4]))
        assert (actor, key, received, condition) == (ACTOR, "original-key", body, '"base"')
        assert final_auth() == ACTOR
        return {
            "body": {"saved": "original-ack"},
            "status": 201,
            "headers": {"ETag": '"new"'},
        }, True

    service.apply = apply
    response = asyncio.run(routes.apply(*IDS[:4], request, body))
    assert response.status_code == 201
    assert response.headers["Idempotent-Replayed"] == "true"
    assert response.headers["ETag"] == '"new"'
    assert json.loads(response.body) == {"saved": "original-ack"}
    assert state["auth"] == [True, True]


@pytest.mark.parametrize("method", ["preview", "apply"])
def test_invalid_requests_never_open_storage_or_a_transaction(monkeypatch, method):
    monkeypatch.setattr(routes, "auth", lambda *_args: {"member_id": ACTOR})
    monkeypatch.setattr(routes, "connection", lambda: pytest.fail("Invalid input opened DB"))
    monkeypatch.setattr(routes, "service", lambda: pytest.fail("Invalid input accessed originals"))
    with pytest.raises(DomainError):
        if method == "apply":
            asyncio.run(routes.apply(*IDS[:4], None, {"unexpected": "value"}))
        else:
            routes.preview(*IDS[:4], None, {"unexpected": "value"})


def test_missing_session_cannot_read_history_or_apply(monkeypatch):
    def denied(*_args):
        raise DomainError("AUTH_REQUIRED", "请先登录", 401)

    monkeypatch.setattr(routes, "auth", denied)
    monkeypatch.setattr(routes, "connection", lambda: pytest.fail("Unauthenticated read"))
    monkeypatch.setattr(routes, "service", lambda: pytest.fail("Unauthenticated write"))
    with pytest.raises(DomainError, match="请先登录"):
        routes.detail(*IDS[:5], None)
    with pytest.raises(DomainError, match="请先登录"):
        asyncio.run(routes.apply(*IDS[:4], None, {}))
