"""HTTP remains responsible for authentication, request metadata and status mapping."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api import package_technical_execution as routes
from packages.domain.errors import DomainError


@pytest.mark.parametrize("accepted", [False, True])
def test_request_passes_session_and_exact_idempotency_metadata_to_use_case(monkeypatch, accepted):
    calls = []

    def auth(request, write=False):
        assert write is True
        calls.append("auth")
        return {"member_id": "session-member"}

    def request(target, body, condition, key):
        assert target.actor == "session-member" and len(target.scope) == 3
        assert (body, condition, key) == ({"fixed": True}, "etag", "same-key")
        calls.append("use-case")
        return {"job": {"id": "native"} if accepted else None}

    monkeypatch.setattr(routes, "auth", auth)
    monkeypatch.setattr(
        routes, "material_jobs_service", lambda connect: SimpleNamespace(request=request)
    )
    identity = UUID("00000000-0000-4000-8000-000000000001")
    result = routes.qualified_job_request(
        identity,
        identity,
        identity,
        identity,
        SimpleNamespace(headers={"if-match": "etag", "idempotency-key": "same-key"}),
        {"fixed": True},
    )
    assert calls == ["auth", "use-case"]
    assert result.status_code == (200 if accepted else 202)
    assert result.headers["cache-control"] == "private, no-store"


def test_auth_failure_does_not_construct_application_or_open_resources(monkeypatch):
    def denied(*args, **kwargs):
        raise DomainError("AUTH_REQUIRED", "login required", 401)

    monkeypatch.setattr(routes, "auth", denied)
    monkeypatch.setattr(
        routes, "material_jobs_service", lambda *args: pytest.fail("unauthenticated composition")
    )
    identity = UUID("00000000-0000-4000-8000-000000000001")
    with pytest.raises(DomainError, match="login required"):
        routes.qualified_job_read(identity, identity, identity, identity, identity, None)
