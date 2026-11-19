"""Exact DOCX advisory never changes project state or infers candidate approval."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.testclient import TestClient
from test_technical_candidate_checks import margin_snapshot

from apps.api import auth as session_auth
from apps.api import technical_candidate_routes as routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.authoring.build import assemble_docx
from packages.authoring.content import empty_content
from packages.domain.runtime import DomainError, sha

BID, BUILD, VERSION, SNAPSHOT, ACTOR, OTHER = (UUID(int=i) for i in range(1, 7))
URL = f"/api/v1/bids/{BID}/builds/{BUILD}/technical-docx-check"
DOCX = assemble_docx({"sections": [empty_content("示例单位施工方案", 0)]})
BODY = {
    "document_version_id": str(VERSION),
    "filename": "技术标.docx",
    "prohibited_names": ["示例单位"],
}


@pytest.fixture
def ports(monkeypatch):
    events = []
    descriptor = {"digest": sha(DOCX), "byte_size": len(DOCX), "object_key": "private-synthetic"}
    proof = {
        "bid_id": str(BID),
        "build_id": str(BUILD),
        "document_version_id": str(VERSION),
        "format": "docx",
        "sha256": sha(DOCX),
        "byte_size": len(DOCX),
        "build_identity": {"snapshot_id": str(SNAPSHOT), "snapshot_digest": "a" * 64},
    }
    config = SimpleNamespace(
        open=False,
        auth_error=None,
        final_actor=ACTOR,
        read_data=DOCX,
        read_error=None,
        proof=proof,
        descriptor=descriptor,
        snapshot={},
        events=events,
    )

    @contextmanager
    def connection():
        assert not config.open
        config.open = True
        events.append("open")
        try:
            yield SimpleNamespace(execute=lambda statement: events.append(statement))
        finally:
            config.open = False
            events.append("closed")

    def authenticate(_request, write):
        assert write is True and not config.open
        events.append("auth")
        if config.auth_error:
            raise config.auth_error
        return {"member_id": ACTOR if events.count("auth") == 1 else config.final_actor}

    def capture(_c, bid_id, build_id, document_version_id, *, historical):
        assert config.open and historical is True
        events.append(("observe", bid_id, build_id, document_version_id))
        if (bid_id, build_id, document_version_id) != (BID, BUILD, VERSION):
            raise DomainError("AUTHORING_OUTPUT_NOT_QUALIFIED", "该生成件无匹配项", 409)
        return {"proof": proof, "documents": [descriptor], "snapshot": config.snapshot}

    def read(held):
        assert not config.open and held == descriptor
        events.append("read")
        if config.read_error:
            raise config.read_error
        return config.read_data

    monkeypatch.setattr(routes, "connection", connection)
    monkeypatch.setattr(routes, "auth", authenticate)
    monkeypatch.setattr(routes.package_outputs, "capture", capture)
    monkeypatch.setattr(routes.rich_build, "read_checked", read)
    return config


def test_openapi_describes_session_csrf_and_readonly_post():
    spec = implemented_openapi(app)
    path = "/api/v1" + routes.PATH
    assert set(spec["paths"][path]) == {"post"}
    operation = spec["paths"][path]["post"]
    assert operation["operationId"] == "checkTechnicalDocxCandidate"
    assert operation["security"] == [{"SessionCookie": []}]
    headers = {
        row["name"]
        for row in operation["parameters"]
        if row.get("required") and row["in"] == "header"
    }
    assert headers == {"Origin", "X-CSRF-Token"}
    request_model = spec["components"]["schemas"]["TechnicalDocxCheckRequest"]
    assert request_model["additionalProperties"] is False
    assert request_model["properties"]["prohibited_names"]["maxItems"] == 100


def test_checks_exact_bytes_with_transactions_closed_and_no_sensitive_echo(ports):
    result = TestClient(app).post(URL, json=BODY)
    assert result.status_code == 200
    value = result.json()
    assert ports.events == [
        "auth",
        "open",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        ("observe", BID, BUILD, VERSION),
        "closed",
        "read",
        "auth",
    ]
    assert result.headers["Cache-Control"] == "private,no-store"
    assert value["artifact_sha256"] == sha(DOCX)
    assert value["snapshot_id"] == str(SNAPSHOT)
    assert value["snapshot_digest"] == "a" * 64
    assert value["document_version_id"] == str(VERSION)
    assert value["blocking_codes"] == ["PROHIBITED_NAME_CONTENT"]
    assert "FORMAT_AND_RENDER_REVIEW" in value["manual_check_codes"]
    assert "DOCX_PAGE_MARGINS_NO_FROZEN_BASIS" in value["manual_check_codes"]
    assert value["historical_advisory"] is True and value["publication_authorized"] is False
    assert "示例单位" not in result.text and "private-synthetic" not in result.text


def test_only_snapshot_bound_margin_controls_check_of_same_download_bytes(ports):
    client = TestClient(app)
    ports.snapshot = margin_snapshot(("margin_top_twips", 1440))
    match = client.post(URL, json=BODY)
    assert match.status_code == 200
    assert match.json()["blocking_codes"] == ["PROHIBITED_NAME_CONTENT"]
    assert "FORMAT_AND_RENDER_REVIEW" in match.json()["manual_check_codes"]
    ports.events.clear()
    ports.snapshot = margin_snapshot(("margin_top_twips", 1337))
    mismatch = client.post(URL, json=BODY)
    assert mismatch.status_code == 200
    assert mismatch.json()["blocking_codes"] == [
        "DOCX_PAGE_MARGINS_MISMATCH",
        "PROHIBITED_NAME_CONTENT",
    ]
    assert match.json()["artifact_sha256"] == mismatch.json()["artifact_sha256"] == sha(DOCX)
    assert match.json()["policy_sha256"] != mismatch.json()["policy_sha256"]
    assert mismatch.json()["publication_authorized"] is False


def test_real_session_auth_rejects_anonymous_request_before_observation(ports, monkeypatch):
    monkeypatch.setattr(routes, "auth", session_auth.auth)
    result = TestClient(app).post(URL, json=BODY)
    assert (result.status_code, result.json()["code"]) == (401, "UNAUTHENTICATED")
    assert not ports.events


def test_real_session_auth_rejects_wrong_origin_before_observation(ports, monkeypatch):
    @contextmanager
    def logged_in_connection():
        yield SimpleNamespace(
            execute=lambda *_args: SimpleNamespace(fetchone=lambda: {"member_id": ACTOR})
        )

    monkeypatch.setattr(routes, "auth", session_auth.auth)
    monkeypatch.setattr(session_auth, "connection", logged_in_connection)
    monkeypatch.setattr(session_auth, "secret_hash", lambda _: "test-digest")
    monkeypatch.setattr(session_auth, "required", lambda _: "https://workbench.example.invalid")
    result = TestClient(app).post(
        URL,
        json=BODY,
        cookies={"session": "synthetic"},
        headers={"Origin": "https://other.example.invalid"},
    )
    assert (result.status_code, result.json()["code"]) == (403, "ORIGIN_REJECTED")
    assert not ports.events


@pytest.mark.parametrize(
    ("url", "payload"),
    (
        (URL, {**BODY, "document_version_id": str(OTHER)}),
        (URL.replace(str(BID), str(OTHER)), BODY),
    ),
)
def test_wrong_bid_or_document_cannot_read_object(ports, url, payload):
    result = TestClient(app).post(url, json=payload)
    assert result.status_code == 409
    assert "read" not in ports.events


@pytest.mark.parametrize(
    ("change", "status", "code"),
    (
        ("pdf", 422, "TECHNICAL_DOCX_BUILD_REQUIRED"),
        ("descriptor", 409, "TECHNICAL_DOCX_BUILD_MISMATCH"),
        ("huge", 422, "TECHNICAL_DOCX_CHECK_LIMIT"),
    ),
)
def test_pdf_mismatched_and_overlimit_objects_are_not_read(ports, change, status, code):
    if change == "pdf":
        ports.proof["format"] = "pdf"
    if change == "descriptor":
        ports.descriptor["digest"] = "f" * 64
    if change == "huge":
        assert routes.MAX_CHECK_BYTES == 64 * 1024 * 1024
        ports.descriptor["byte_size"] = ports.proof["byte_size"] = routes.MAX_CHECK_BYTES + 1
    result = TestClient(app).post(URL, json=BODY)
    assert (result.status_code, result.json()["code"]) == (status, code)
    assert "read" not in ports.events


@pytest.mark.parametrize(
    ("change", "status", "code"),
    (
        ("bytes_changed", 503, "BUILD_OBJECT_CORRUPT"),
        ("object_error", 503, "OBJECT_STORE_UNAVAILABLE"),
        ("actor_changed", 403, "TECHNICAL_DOCX_ACTOR_CHANGED"),
    ),
)
def test_changed_bytes_provider_failure_and_replaced_session_are_not_returned(
    ports, change, status, code
):
    if change == "bytes_changed":
        ports.read_data = b"x" + DOCX[1:]
    if change == "object_error":
        ports.read_error = OSError("internal object url")
    if change == "actor_changed":
        ports.final_actor = OTHER
    result = TestClient(app).post(URL, json=BODY)
    assert (result.status_code, result.json()["code"]) == (status, code)
    assert "internal object url" not in result.text


@pytest.mark.parametrize(
    "provider_error",
    (
        ClientError({"Error": {"Code": "Denied", "Message": "private-provider-url"}}, "GetObject"),
        BotoCoreError(),
    ),
)
def test_provider_errors_are_normalized_without_private_details(ports, provider_error):
    ports.read_error = provider_error
    result = TestClient(app).post(URL, json=BODY)
    assert (result.status_code, result.json()["code"]) == (503, "OBJECT_STORE_UNAVAILABLE")
    assert "private-provider-url" not in result.text


def test_extra_or_oversize_policy_fields_are_rejected(ports):
    for invalid in (
        {**BODY, "approved": True},
        {**BODY, "margin_top_twips": 1440},
        {**BODY, "prohibited_names": ["a"] * 101},
    ):
        result = TestClient(app).post(URL, json=invalid)
        assert result.status_code == 422
        assert result.json()["code"] == "INVALID_REQUEST"
    assert ports.events == []
