"""Real route contracts and exact request/transaction boundaries for package facts."""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest

from apps.api import bid_package_submission_routes as routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.domain.runtime import DomainError

IDS = tuple(UUID(int=value) for value in range(1, 7))
ACTOR = UUID(int=90)


def selection():
    return {
        "package_id": str(IDS[1]),
        "revision_id": str(IDS[2]),
        "package_digest": "a" * 64,
        "inventory": None,
        "coverage": None,
        "review_run": None,
    }


def request_body():
    return {
        "kind": "offline_fact",
        "selection": selection(),
        "input_digest": "b" * 64,
        "evidence": {"document_version_id": str(IDS[3]), "digest": "c" * 64, "byte_size": 20},
        "submitted_at": "2026-10-20T12:00:00.123450Z",
        "explanation": "确切投标包已经实际提交；附件为用户登记依据",
        "expected_head": None,
        "correction_reason": None,
    }


def test_actual_package_paths_are_authenticated_and_shared_reads_have_disjoint_subjects():
    actual = implemented_openapi(app)
    for path in (
        routes.BASE + "/submission-preview",
        routes.BASE + "/submissions",
        "/api/v1/submissions/{submission_id}/package-corrections",
    ):
        operation = actual["paths"][path]["post"]
        assert operation["security"] == [{"SessionCookie": []}]
        fields = {p["name"] for p in operation["parameters"] if p.get("required")}
        assert {"Origin", "X-CSRF-Token"} <= fields
        if not path.endswith("submission-preview"):
            assert {"Idempotency-Key", "If-Match"} <= fields
            assert "X-Bid-ETag" in operation["responses"]["201"]["headers"]
        else:
            assert not {"Idempotency-Key", "If-Match"} & fields
    schemas = actual["components"]["schemas"]
    assert schemas["SubmissionView"]["oneOf"] == [
        {"$ref": "#/components/schemas/SingleBodySubmissionView"},
        {"$ref": "#/components/schemas/PackageSubmissionView"},
    ]
    assert schemas["PackageSubmissionView"]["properties"]["body_version_id"] == {"type": "null"}
    assert schemas["ResearchOutcomeVerification"]["oneOf"][1] == {
        "$ref": "#/components/schemas/PackageOutcomeVerificationRequest"
    }


@pytest.fixture
def ports(monkeypatch):
    state = {"open": False, "auth": []}

    @contextmanager
    def connection():
        assert not state["open"]
        state["open"] = True
        try:
            yield SimpleNamespace(
                execute=lambda statement: (
                    None
                    if statement == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    else pytest.fail("Preview must not mutate data")
                )
            )
        finally:
            state["open"] = False

    def auth(_request, write=False):
        state["auth"].append(write)
        return {"member_id": ACTOR}

    service = SimpleNamespace()
    monkeypatch.setattr(routes, "connection", connection)
    monkeypatch.setattr(routes, "auth", auth)
    monkeypatch.setattr(routes, "service", lambda: service)
    return state, service


def test_preview_is_exact_readonly_and_does_not_claim_an_original_byte_check(ports):
    state, service = ports

    def prepare(_c, scope, body, *, bid_etag_fn):
        assert state["open"] and scope == tuple(map(str, IDS[:3]))
        assert body == selection() and bid_etag_fn is routes.bid_etag
        return {"gate": {"allowed": False}, "observed_only": True}

    service.prepare = prepare
    result = routes.preview(*IDS[:3], None, selection())
    assert result.headers["cache-control"] == "private, no-store"
    assert json.loads(result.body)["observed_only"] is True
    assert state["auth"] == [True] and not state["open"]


@pytest.mark.parametrize("correction", [False, True])
def test_save_and_correction_preserve_original_body_headers_and_final_auth(
    ports, monkeypatch, correction
):
    state, service = ports
    body = request_body()
    request = SimpleNamespace(headers={"idempotency-key": "original-key", "if-match": '"old"'})
    if correction:
        body["expected_head"] = {"id": str(IDS[4]), "revision": 2}
        body["correction_reason"] = "据实际投递内容更正完整包"
        monkeypatch.setattr(routes, "fetch", lambda *_args: {"bid_id": IDS[0]})

    def register(scope, actor, key, received, condition, *, supersedes, bid_etag_fn, final_auth):
        assert not state["open"], "Route connection must close before object IO"
        assert scope == tuple(map(str, IDS[:3]))
        assert (actor, key, received, condition) == (ACTOR, "original-key", body, '"old"')
        assert supersedes == (str(IDS[4]) if correction else None)
        assert bid_etag_fn is routes.bid_etag and final_auth() == ACTOR
        return {"body": {"original": True}, "status": 201, "headers": {"X-Bid-ETag": '"new"'}}, True

    service.register = register
    result = asyncio.run(
        routes.correct(IDS[4], request, body)
        if correction
        else routes.register(*IDS[:3], request, body)
    )
    assert result.status_code == 201
    assert result.headers["Idempotent-Replayed"] == "true"
    assert result.headers["X-Bid-ETag"] == '"new"'
    assert state["auth"] == [True, True]


def test_deferred_storage_rejection_never_appears_as_a_successful_ack(ports):
    _, service = ports

    def rejected(*_args, **_kwargs):
        raise psycopg.errors.CheckViolation("synthetic deferred integrity rejection")

    service.register = rejected
    with pytest.raises(DomainError) as failure:
        asyncio.run(routes.register(*IDS[:3], SimpleNamespace(headers={}), request_body()))
    assert failure.value.code == "PACKAGE_SUBMISSION_STORAGE_REJECTED"


@pytest.mark.parametrize("method", ["preview", "register", "correct"])
def test_invalid_body_never_opens_database_or_object_storage(monkeypatch, method):
    monkeypatch.setattr(routes, "auth", lambda *_args: {"member_id": ACTOR})
    monkeypatch.setattr(routes, "connection", lambda: pytest.fail("Invalid input opened DB"))
    monkeypatch.setattr(routes, "service", lambda: pytest.fail("Invalid input accessed objects"))
    with pytest.raises(DomainError):
        if method == "preview":
            routes.preview(*IDS[:3], None, {"body_version_id": str(IDS[4])})
        elif method == "correct":
            asyncio.run(routes.correct(IDS[4], None, {}))
        else:
            asyncio.run(routes.register(*IDS[:3], None, {}))
