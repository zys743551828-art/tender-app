"""Registered import routes and exact historical image delivery; no live IO claims."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from apps.api import authoring
from apps.api import authoring_word_import as routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.domain.runtime import DomainError, sha


def test_word_import_capability_only_follows_actual_router_registration(monkeypatch):
    monkeypatch.setattr(authoring, "auth", lambda *_: {})
    isolated = FastAPI()
    isolated.include_router(authoring.router)
    assert not authoring.capabilities(Request({"type": "http", "app": isolated}))[
        "supports_external_docx_import"
    ]
    assert authoring.capabilities(Request({"type": "http", "app": app}))[
        "supports_external_docx_import"
    ]


def test_registered_word_import_contracts_include_binary_image_and_exact_mutations():
    actual = implemented_openapi(app)
    base = "/api/v1" + routes.BASE
    for path, verb, status, schema in (
        (
            "/api/v1/authoring/word-import-capabilities",
            "get",
            "200",
            "AuthoringWordImportCapabilities",
        ),
        (base, "get", "200", "AuthoringWordImportPage"),
        (base, "post", "201", "AuthoringWordImportCandidate"),
        (base + "/{candidate_id}", "get", "200", "AuthoringWordImportCandidate"),
        (base + "/{candidate_id}/resolve", "post", "200", "AuthoringWordImportResult"),
    ):
        operation = actual["paths"][path][verb]
        assert operation["security"] == [{"SessionCookie": []}]
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/" + schema
        }
        if verb == "post":
            required = {p["name"] for p in operation["parameters"] if p.get("required")}
            assert {"Origin", "X-CSRF-Token", "Idempotency-Key"} <= required
            if path == base:
                assert "If-Match" in required
    image = actual["paths"][base + "/{candidate_id}/images/{image_key}"]["get"]
    assert set(image["responses"]["200"]["content"]) == {"image/png"}
    assert "X-Content-SHA256" in image["responses"]["200"]["headers"]
    history = actual["paths"][base]["get"]
    limit = next(p for p in history["parameters"] if p["name"] == "limit")
    assert limit["schema"]["maximum"] == 50


@pytest.fixture
def image_port(monkeypatch):
    data = b"\x89PNG\r\n\x1a\nexact controlled fixture bytes"
    state = {
        "open": False,
        "object_reads": 0,
        "descriptor": {
            "object_key": "private/import/exact-image",
            "digest": sha(data),
            "byte_size": len(data),
            "media_type": "image/png",
        },
    }
    ids = [UUID(int=i) for i in range(1, 5)]

    @contextmanager
    def connection():
        assert not state["open"]
        state["open"] = True
        try:
            yield SimpleNamespace(
                execute=lambda sql: (
                    None
                    if sql == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    else pytest.fail("historical preview must remain SELECT-only")
                )
            )
        finally:
            state["open"] = False

    def descriptor(_c, *scope):
        assert state["open"] and list(scope) == ids
        return dict(state["descriptor"])

    def get(key):
        assert not state["open"], "never hold a DB connection during an object download"
        assert key == "private/import/exact-image"
        state["object_reads"] += 1
        return data

    monkeypatch.setattr(routes, "auth", lambda *_: {"member_id": str(UUID(int=9))})
    monkeypatch.setattr(routes, "connection", connection)
    monkeypatch.setattr(routes.service, "image_descriptor", descriptor)
    monkeypatch.setattr(routes.storage, "get", get)
    return ids, state, data


def test_image_delivery_releases_read_transaction_and_checks_actual_digest(image_port):
    ids, state, data = image_port
    response = routes.image_preview(*ids, None)
    assert response.body == data and state["object_reads"] == 1
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-sha256"] == sha(data)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "field,value",
    [
        ("digest", "f" * 64),
        ("byte_size", 1),
        ("media_type", "image/svg+xml"),
    ],
)
def test_changed_image_bytes_or_media_never_leave_as_success(image_port, field, value):
    ids, state, _ = image_port
    state["descriptor"][field] = value
    with pytest.raises(DomainError) as error:
        routes.image_preview(*ids, None)
    assert error.value.code == "AUTHORING_WORD_IMPORT_IMAGE_CHANGED"
    assert not state["open"]


def test_foreign_candidate_or_session_failure_never_reads_an_object(image_port, monkeypatch):
    ids, state, _ = image_port

    def missing(*_):
        raise DomainError("AUTHORING_WORD_IMPORT_NOT_FOUND", "未找到", 404)

    monkeypatch.setattr(routes.service, "image_descriptor", missing)
    with pytest.raises(DomainError, match="未找到"):
        routes.image_preview(*ids, None)
    assert state["object_reads"] == 0 and not state["open"]
    monkeypatch.setattr(routes, "auth", missing)
    with pytest.raises(DomainError):
        routes.image_preview(*ids, None)
    assert state["object_reads"] == 0 and not state["open"]
