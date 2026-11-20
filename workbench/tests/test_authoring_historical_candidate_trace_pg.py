"""Read native candidate references for one immutable adoption, with offline model only."""
# ruff: noqa: F401,F811

import json
from uuid import uuid4

import pytest
from authoring_package_input_fixtures import ADMIN_DSN, exact, world
from authoring_package_job_fixtures import case, input_database, queued
from authoring_package_job_fixtures import database as job_database
from fastapi.testclient import TestClient
from test_authoring_exact_builds_pg import adopted
from test_authoring_exact_revisions_pg import database, published, qualified
from test_authoring_package_inputs_pg import add_new_parse, mutate_authority
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api

from apps.api.main import app
from packages.domain import storage
from packages.domain.runtime import connection, sha

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated synthetic PostgreSQL17")


@pytest.fixture
def historical(case):
    w = case
    with connection() as c:
        context = json.loads(
            c.execute(
                "SELECT context_text FROM design.authoring_package_inputs WHERE bid_id=%s AND id=%s",
                (w["bid"], w["fixed"]["manifest"]["id"]),
            ).fetchone()["context_text"]
        )
    docs = [
        next(d for d in context["documents"] if d["package_role"] == role)
        for role in ("authority", "target")
    ]
    w["raw"]["evidence_ids"] = [doc["blocks"][0]["id"] for doc in docs]
    w["expected_citations"] = docs
    return adopted.__wrapped__(published.__wrapped__(queued.__wrapped__(w)))


def selected(w):
    row = qualified(w)
    path = f"/api/v1/bids/{w['bid']}/authoring/section-revisions/{row['section_revision_id']}/candidate-source-trace"
    query = {
        "snapshot_id": w["saved"]["snapshot_id"],
        "snapshot_digest": w["saved"]["snapshot_digest"],
        "qualification_digest": row["digest"],
        "action_id": w["action_id"],
    }
    return path, query, row


def counts(w):
    with connection() as c:
        return c.execute(
            """SELECT (SELECT count(*) FROM design.commands) AS commands,
             (SELECT count(*) FROM design.operations) AS operations,
             (SELECT count(*) FROM design.outbox) AS outbox,
             (SELECT count(*) FROM design.audit_entries) AS audit,
             (SELECT count(*) FROM design.section_revisions WHERE bid_id=%s) AS revisions""",
            (w["bid"],),
        ).fetchone()


def test_exact_candidate_refs_are_not_entire_context_or_switched_to_new_parse(
    historical, monkeypatch
):
    w = historical
    path, query, qualification = selected(w)
    assert len(w["calls"]) == 1
    newer = add_new_parse(w)
    mutate_authority(w, "source")
    before = counts(w)
    with monkeypatch.context() as isolated:
        isolated.setattr(
            storage, "get", lambda *a, **kw: pytest.fail("must not fetch object bytes")
        )
        response = w["client"].get(path, params=query)
    assert response.status_code == 200, response.text
    payload = response.json()
    digest = payload.pop("trace_digest")
    assert sha(payload) == digest
    assert payload["candidate_digest"] == qualification["manifest"]["origin"]["candidate_digest"]
    assert payload["node"]["node_id"] == w["raw"]["node_id"]
    assert payload["node"]["before_digest"] == w["raw"]["before_digest"]
    assert payload["node"]["after_digest"] != payload["node"]["before_digest"]
    assert [row["evidence_id"] for row in payload["citations"]] == w["raw"]["evidence_ids"]
    chosen = w["input_body"]["package_context"]
    for row, expected in zip(payload["citations"], w["expected_citations"], strict=True):
        role = expected["package_role"]
        assert row["memberships"] == [{"role": role, **chosen[role]}]
        assert row["parse_run_id"] == expected["parse_id"] != str(newer)
        assert row["document_version_id"] == expected["document_version_id"]
        assert row["evidence_digest"] == expected["blocks"][0]["digest"]
        assert row["physical_page"] == expected["blocks"][0]["physical_page"]
    assert payload["historic_only"]
    assert not any(
        payload[key]
        for key in (
            "current_effectivity_verified",
            "original_bytes_reverified",
            "publication_authorized",
            "content_correctness_certified",
        )
    )
    assert "text_content" not in response.text and "object_key" not in response.text
    assert w["raw"]["replacement_text"] not in response.text
    assert counts(w) == before and len(w["calls"]) == 1


def test_route_requires_the_exact_original_receipt_and_same_bid(historical):
    w = historical
    path, query, _ = selected(w)
    original = w["input_body"]["target_section"]
    alternate = w["client"].post(
        "/api/v1/bids",
        json={"title": "隔离合成项目"},
        headers={
            "Origin": "http://identity-v2.test",
            "X-CSRF-Token": w["csrf"],
            "Idempotency-Key": uuid4().hex,
        },
    )
    assert alternate.status_code == 201, alternate.text
    separate_id = alternate.headers["Location"].rsplit("/", 1)[-1]
    before = counts(w)
    c = w["client"]
    for patch, status in (
        ({"snapshot_digest": "a" * 64}, 409),
        ({"qualification_digest": "d" * 64}, 409),
        ({"action_id": str(uuid4())}, 409),
        (
            {
                "snapshot_id": original["snapshot_id"],
                "snapshot_digest": original["snapshot_digest"],
            },
            404,
        ),
        ({"snapshot_digest": "invalid"}, 422),
    ):
        denied = c.get(path, params=query | patch)
        assert denied.status_code == status, denied.text
        assert "citations" not in denied.json()
    foreign = c.get(path.replace(w["bid"], separate_id), params=query)
    assert foreign.status_code == 404 and "citations" not in foreign.json()
    with TestClient(app, base_url="http://identity-v2.test") as anonymous:
        denied = anonymous.get(path, params=query)
    assert denied.status_code == 401 and "citations" not in denied.json()
    assert counts(w) == before and len(w["calls"]) == 1
