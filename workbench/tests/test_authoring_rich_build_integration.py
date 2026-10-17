"""Actual export/1 + nonowner PG + Memory; hard deny Docker and all provider HTTP."""

import copy
import io
import os
import zipfile
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from test_authoring_rich_integration import images, no_external, rich_api, rich_change, upload_body

from packages.authoring import rich_assets, rich_renderer, snapshot_structure
from packages.authoring.repository import freeze, latest_sections, save_draft, snapshot_content
from packages.domain import storage
from packages.domain.runtime import DomainError, connection, etag

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_AUTHORING_RICH_INTEGRATION") != "1",
    reason="Explicit fresh reviewed RICH nonowner profile required",
)

# Register the fixtures imported from the existing explicit Memory/HTTP harness.
_FIXTURES = (images, no_external, rich_api)


@pytest.fixture(autouse=True)
def no_docker(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Memory RICH build tests forbid all Docker access")

    monkeypatch.setattr(rich_renderer.sandbox, "_docker", forbidden)
    monkeypatch.setattr(rich_renderer.sandbox, "build_profile", forbidden)
    monkeypatch.delenv("AUTHORING_RICH_RENDER_PROFILE_PATH", raising=False)
    monkeypatch.setattr(storage, "bucket", lambda: "explicit-memory-only")


@pytest.fixture
def environment(images, rich_api):
    api, headers, path = rich_api
    uploaded = api.post(path, headers=headers, json=upload_body(images))
    assert uploaded.status_code == 201, uploaded.json()
    value = uploaded.json()
    with connection() as c:
        rows = latest_sections(c, images["bid"], images["draft"], include_deleted=True)
        state = snapshot_structure.reconcile(None, rows)
        c.execute("UPDATE drafts SET revision=2 WHERE id=%s", (images["draft"],))
        freeze(c, images["bid"], images["draft"], 2, actor=images["actor"], structure_state=state)
        body = rich_change(images, value)
        body["base_draft_revision"] = 2
        saved = save_draft(
            c,
            images["bid"],
            images["draft"],
            images["actor"],
            body,
            etag("draft", images["draft"], 2),
        )
        snapshot = snapshot_content(c, images["bid"], UUID(saved["snapshot_id"]))
    return images | {"asset": value, "snapshot": snapshot, "api": api, "headers": headers}


def request_body(env):
    extension = env["snapshot"]["authoring_structure"]
    return {
        "draft_id": str(env["draft"]),
        "draft_revision": 3,
        "directory_template_version_id": extension["directory_template"]["id"],
        "style_template_version_id": extension["style_template"]["id"],
        "formats": ["docx", "pdf"],
        "follow_up": "none",
        "pagination_mode": "chapter_start_new_page",
    }


def queue(env, body=None):
    result = env["api"].post(
        f"/api/v1/bids/{env['bid']}/builds",
        headers=env["headers"] | {"Idempotency-Key": uuid4().hex},
        json=body or request_body(env),
    )
    assert result.status_code == 202, result.json()
    with connection() as c:
        row = c.execute(
            "SELECT b.id,o.payload FROM builds b JOIN outbox o ON o.operation_id=b.operation_id WHERE b.bid_id=%s AND o.topic='tender.task.export.v1' LIMIT 1",
            (env["bid"],),
        ).fetchone()
    return row["id"], row["payload"]


def test_actual_export_no_profile_retains_real_docx_pdf_failed_and_explicit_unknowns(
    environment, monkeypatch
):
    from apps.worker import engine, export_handlers

    env = environment
    build, message = queue(env)
    connections = []
    original_connection = export_handlers.connection

    @contextmanager
    def observed(*args, **kwargs):
        with original_connection(*args, **kwargs) as c:
            connections.append(c)
            yield c

    original_put = storage.put

    def put(*args):
        assert connections and all(c.closed for c in connections)
        return original_put(*args)

    monkeypatch.setattr(export_handlers, "connection", observed)
    monkeypatch.setattr(storage, "put", put)
    lease = engine.acquire(message)
    assert lease
    computed = engine.run_compute(message, lease)
    assert computed["manifest"]["writer_kind"] == "generated_rich/3"
    docx, pdf = computed["outputs"]
    assert docx["state"] == "succeeded" and pdf["state"] == "failed"
    assert "TOC_PAGE_NUMBERS_UNKNOWN" in docx["gaps"]
    assert "ACTUAL_SECTION_PAGE_RANGES_UNKNOWN" in docx["gaps"]
    with zipfile.ZipFile(io.BytesIO(env["objects"][docx["object_key"]])) as archive:
        xml = archive.read("word/document.xml")
        assert b"gridSpan" in xml and b"vMerge" in xml and b"bookmarkStart" in xml
        assert len([name for name in archive.namelist() if name.startswith("word/media/")]) == 1
    assert engine.finish(message, lease, computed)
    assert engine.acquire(message) is None
    view = env["api"].get(f"/api/v1/builds/{build}", headers=env["headers"])
    assert view.status_code == 200, view.json()
    assert view.json()["layout"]["state"] == "partial"
    assert view.json()["layout"]["page_count"] is None
    assert view.json()["follow_up"]["state"] == "not_requested"
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM build_outputs WHERE build_id=%s", (build,)
            ).fetchone()["n"]
            == 2
        )
        assert (
            c.execute(
                "SELECT current_body_id FROM bid_profiles WHERE bid_id=%s", (env["bid"],)
            ).fetchone()["current_body_id"]
            is None
        )


def test_asset_withdraw_after_compute_rejects_all_publication_but_keeps_old_snapshot(environment):
    from apps.worker import engine

    env = environment
    build, message = queue(env)
    lease = engine.acquire(message)
    computed = engine.run_compute(message, lease)
    with connection() as c:
        value = env["asset"]
        rich_assets.withdraw(
            c, env["bid"], UUID(value["asset_id"]), env["actor"], value["etag"], "计算后停用"
        )
    with pytest.raises(DomainError) as error:
        engine.finish(message, lease, computed)
    assert error.value.code == "AUTHORING_IMAGE_STALE"
    with connection() as c:
        assert not c.execute("SELECT 1 FROM build_outputs WHERE build_id=%s", (build,)).fetchone()
        assert not c.execute(
            "SELECT 1 FROM effect_receipts WHERE operation_id=%s", (UUID(message["operation_id"]),)
        ).fetchone()
        assert (
            snapshot_content(c, env["bid"], UUID(env["snapshot"]["snapshot_id"])) == env["snapshot"]
        )


def test_rich_requires_explicit_mode_and_exact_template_versions_and_pdf_for_review(environment):
    env = environment
    original = request_body(env)
    variants = [
        ({key: value for key, value in original.items() if key != "pagination_mode"}, 422),
        (original | {"style_template_version_id": str(uuid4())}, 409),
        (original | {"formats": ["docx"], "follow_up": "review"}, 422),
        (original | {"pagination_mode": "guess"}, 422),
    ]
    for body, status in variants:
        response = env["api"].post(
            f"/api/v1/bids/{env['bid']}/builds",
            headers=env["headers"] | {"Idempotency-Key": uuid4().hex},
            json=body,
        )
        assert response.status_code == status, response.json()
    with connection() as c:
        assert not c.execute("SELECT 1 FROM builds WHERE bid_id=%s", (env["bid"],)).fetchone()


def test_tampered_snapshot_identity_cannot_publish_same_manifest(environment):
    from apps.worker import engine

    env = environment
    build, message = queue(env)
    lease = engine.acquire(message)
    computed = engine.run_compute(message, lease)
    bad = copy.deepcopy(computed)
    bad["snapshot_id"] = str(uuid4())
    with pytest.raises(DomainError) as error:
        engine.finish(message, lease, bad)
    assert error.value.code == "BUILD_RESULT_IDENTITY_MISMATCH"
    with connection() as c:
        assert not c.execute("SELECT 1 FROM build_outputs WHERE build_id=%s", (build,)).fetchone()


def test_actual_http_cancel_rejects_late_rich_result_without_metadata(environment):
    from apps.worker import engine

    env = environment
    build, message = queue(env)
    lease = engine.acquire(message)
    computed = engine.run_compute(message, lease)
    path = f"/api/v1/operations/{message['operation_id']}"
    current = env["api"].get(path, headers=env["headers"])
    assert current.status_code == 200
    response = env["api"].post(
        path + "/cancel",
        headers=env["headers"]
        | {"Idempotency-Key": uuid4().hex, "If-Match": current.headers["ETag"]},
        json={"reason": "明确取消合成表图构建", "cancel_pending_same_input": False},
    )
    assert response.status_code == 200, response.json()
    assert engine.finish(message, lease, computed) is False
    with connection() as c:
        assert not c.execute("SELECT 1 FROM build_outputs WHERE build_id=%s", (build,)).fetchone()
        assert not c.execute(
            "SELECT 1 FROM effect_receipts WHERE operation_id=%s", (UUID(message["operation_id"]),)
        ).fetchone()


def test_real_http_restore_uses_rich_digest_and_rechecks_withdrawn_assets(environment):
    env = environment
    path = f"/api/v1/bids/{env['bid']}/sections/{env['section']['section_id']}/restore"
    body = {"revision": 2, "base_draft_revision": 3, "base_section_revision": 2}
    headers = env["headers"] | {
        "Idempotency-Key": uuid4().hex,
        "If-Match": etag("draft", env["draft"], 3),
    }
    restored = env["api"].post(path, headers=headers, json=body)
    assert restored.status_code == 200 and restored.json()["draft_revision"] == 4, restored.json()
    with connection() as c:
        old = snapshot_content(c, env["bid"], UUID(restored.json()["snapshot_id"]))
        assert old["sections"] == env["snapshot"]["sections"]
        value = env["asset"]
        rich_assets.withdraw(
            c, env["bid"], UUID(value["asset_id"]), env["actor"], value["etag"], "恢复后撤回"
        )
    replay = env["api"].post(path, headers=headers, json=body)
    assert replay.status_code == 200 and replay.json() == restored.json()
    rejected = env["api"].post(
        path,
        headers=env["headers"]
        | {"Idempotency-Key": uuid4().hex, "If-Match": etag("draft", env["draft"], 4)},
        json=body | {"base_draft_revision": 4, "base_section_revision": 3},
    )
    assert rejected.status_code == 409 and rejected.json()["code"] == "AUTHORING_IMAGE_STALE"
    with connection() as c:
        assert snapshot_content(c, env["bid"], UUID(restored.json()["snapshot_id"])) == old
        assert (
            c.execute("SELECT revision FROM drafts WHERE id=%s", (env["draft"],)).fetchone()[
                "revision"
            ]
            == 4
        )


def test_actual_rich_schema_projects_real_http_responses_and_build_payload(environment):
    from jsonschema import Draft202012Validator, FormatChecker

    from apps.api.export_openapi import implemented_openapi
    from apps.api.main import app
    from packages.authoring.rich_contracts import extend_openapi

    env = environment
    actual = implemented_openapi(app)
    extend_openapi(actual)

    def valid(name, value):
        root = {"$ref": "#/components/schemas/" + name, "components": actual["components"]}
        Draft202012Validator(root, format_checker=FormatChecker()).validate(value)

    valid("AuthoringImageCreated", env["asset"])
    valid("AuthoringSnapshot", env["snapshot"])
    valid("BuildRequest", request_body(env))
    capabilities = env["api"].get("/api/v1/authoring/rich-capabilities", headers=env["headers"])
    assert capabilities.status_code == 200
    valid("AuthoringRichCapabilities", capabilities.json())
    assert capabilities.json()["renderer_configured"] is False
    build, message = queue(env)
    pending = env["api"].get(f"/api/v1/builds/{build}", headers=env["headers"])
    valid("BuildView", pending.json())
    assert pending.json()["layout"]["state"] == "pending"
    from apps.worker import engine

    lease = engine.acquire(message)
    assert engine.finish(message, lease, engine.run_compute(message, lease))
    result = env["api"].get(f"/api/v1/builds/{build}", headers=env["headers"])
    valid("BuildView", result.json())
    assert result.json()["layout"]["state"] == "partial"
    for name, value in [
        ("AuthoringImageCreated", env["asset"] | {"unexpected": True}),
        ("BuildRequest", request_body(env) | {"renderer_profile": {}}),
    ]:
        with pytest.raises(Exception) as error:
            valid(name, value)
        assert type(error.value).__name__ == "ValidationError"
