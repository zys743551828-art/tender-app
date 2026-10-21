"""Explicit synthetic native setup, genuine session and unchanged restore router."""

import os
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from apps.api.authoring import router as authoring_router
from apps.api.authoring_history_routes import router
from packages.domain.runtime import DomainError, connection, etag, secret_hash, sha


def history_app():
    app = FastAPI()
    app.include_router(authoring_router)
    app.include_router(router)

    @app.exception_handler(DomainError)
    async def failed(_request: Request, error: DomainError):
        return JSONResponse(
            {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "details": error.details,
            },
            status_code=error.status,
            headers={"Cache-Control": "private, no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, _error: RequestValidationError):
        return await failed(request, DomainError("INVALID_REQUEST", "请求不符合协议", 422))

    return app


@pytest.fixture
def history_case(env):
    token, csrf = uuid4().hex, uuid4().hex
    with connection() as c:
        c.execute(
            "INSERT INTO design.sessions(id,member_id,token_digest,csrf_digest,expires_at) VALUES(%s,%s,%s,%s,clock_timestamp()+interval '10 minutes')",
            (uuid4(), env["actor"], secret_hash(token), sha(csrf.encode())),
        )
        section = c.execute(
            "SELECT r.* FROM design.sections s JOIN design.section_revisions r ON r.section_id=s.id AND r.revision=s.head_revision WHERE s.bid_id=%s AND s.draft_id=%s",
            (env["bid"], env["draft"]),
        ).fetchone()
    with TestClient(history_app()) as client:
        client.cookies.set("session", token)
        yield env | {"client": client, "section": section, "csrf": csrf}


def url(case, *, section=None, revision=None, digest=None):
    selected = section or case["section"]
    return (
        f"/api/v1/bids/{case['bid']}/drafts/{case['draft']}/sections/{selected['section_id']}/revisions/{revision or selected['revision']}"
        f"?expected_digest={digest or selected['digest']}"
    )


def restore(case, revision, *, base_draft=None, base_section=None, headers=None):
    with connection() as c:
        draft = c.execute(
            "SELECT revision FROM design.drafts WHERE id=%s", (case["draft"],)
        ).fetchone()["revision"]
        section = c.execute(
            "SELECT head_revision FROM design.sections WHERE id=%s",
            (case["section"]["section_id"],),
        ).fetchone()["head_revision"]
    request_headers = headers or {
        "Origin": os.environ["APP_ORIGIN"],
        "X-CSRF-Token": case["csrf"],
        "If-Match": etag("draft", case["draft"], base_draft or draft),
        "Idempotency-Key": uuid4().hex,
    }
    body = {
        "revision": revision,
        "base_draft_revision": base_draft or draft,
        "base_section_revision": base_section or section,
    }
    response = case["client"].post(
        f"/api/v1/bids/{case['bid']}/sections/{case['section']['section_id']}/restore",
        json=body,
        headers=request_headers,
    )
    return response, request_headers, body


def counts(case):
    with connection() as c:
        return c.execute(
            """SELECT (SELECT count(*) FROM design.section_revisions WHERE draft_id=%s) AS sections,
            (SELECT count(*) FROM design.draft_snapshots WHERE draft_id=%s) AS snapshots,
            (SELECT count(*) FROM design.commands) AS commands,
            (SELECT count(*) FROM design.audit_entries) AS audits,
            (SELECT count(*) FROM design.operations) AS operations,
            (SELECT count(*) FROM design.model_calls) AS model_calls""",
            (case["draft"], case["draft"]),
        ).fetchone()
