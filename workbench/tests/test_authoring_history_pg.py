"""Real PG17 nonowner/API and old-revision restore; explicit synthetic data only."""
# ruff: noqa: F401,F811

import json
import os
import socket
import threading
import time
from copy import deepcopy
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
import uvicorn
from authoring_history_fixtures import counts, history_app, history_case, restore, url
from psycopg.types.json import Jsonb
from test_authoring_package_adoptions_pg import database, env
from test_authoring_rich import cell, paragraph, row, table
from work_context_catalog_fixtures import current, image_asset, save

from deploy.authoring_history_readiness import verify
from packages.authoring import rich_assets
from packages.authoring.content import schema_digest_for
from packages.authoring.repository import create_draft
from packages.authoring_history import repository, service
from packages.contracts import authoring_history_api as contract
from packages.domain import storage
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.runtime import Command, DomainError, connection, etag, sha
from packages.lifecycle import service as lifecycle
from packages.rag.indexing import original_source_id, withdraw_source

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="explicit isolated PG17/nonowner history acceptance required",
)


def no_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("history read must not use storage/model I/O")

    monkeypatch.setattr(storage, "get", forbidden)
    monkeypatch.setattr(storage, "client", forbidden)
    monkeypatch.setattr(DeepSeekClient, "from_env", forbidden)


def test_native_read_auth_scope_metadata_no_write_and_unchanged_restore_roundtrip(
    history_case, monkeypatch
):
    case, old = history_case, history_case["section"]
    save(case, text="明确更新后的当前正文")
    before = counts(case)
    no_io(monkeypatch)
    client = case["client"]
    response = client.get(url(case))
    assert response.status_code == 200, response.text
    body = contract.checked(response.json())
    assert body["content"] == old["content"]
    assert body["section_revision_id"] == str(old["id"])
    assert body["created_by"] == str(case["actor"])
    assert body["digest"] == old["digest"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie" and "etag" not in response.headers
    assert counts(case) == before

    applied, headers, request = restore(case, old["revision"])
    assert applied.status_code == 200, applied.text
    after_revision, after = current(case)
    assert after_revision == 4 and after["revision"] == 4
    assert after["content"] == old["content"] and after["id"] != old["id"]
    assert applied.json()["draft_revision"] == after_revision
    assert client.get(url(case)).json() == body
    replay = client.post(
        f"/api/v1/bids/{case['bid']}/sections/{old['section_id']}/restore",
        headers=headers,
        json=request,
    )
    assert replay.status_code == 200 and replay.json() == applied.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    final = counts(case)
    assert final["sections"] == before["sections"] + 1
    assert final["snapshots"] == before["snapshots"] + 1
    assert final["commands"] == before["commands"] + 1
    assert final["operations"] == before["operations"]


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?expected_digest=",
        "?expected_digest=" + "A" * 64,
        "?expected_digest=" + "a" * 64 + "&expected_digest=" + "a" * 64,
        "?expected_digest=" + "a" * 64 + "&latest=true",
    ],
)
def test_digest_is_required_single_closed_query(history_case, query):
    response = history_case["client"].get(url(history_case).split("?")[0] + query)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("scope", ["bid", "draft", "section", "revision"])
def test_wrong_scope_or_missing_revision_never_reads_current(history_case, scope):
    case = history_case
    path = url(case)
    if scope == "revision":
        path = path.replace(f"/revisions/{case['section']['revision']}?", "/revisions/999?")
    elif scope == "section":
        path = path.replace(str(case["section"]["section_id"]), str(uuid4()))
    else:
        path = path.replace(str(case[scope]), str(uuid4()))
    assert case["client"].get(path).status_code == 404


def test_existing_other_draft_same_project_does_not_match(history_case):
    case = history_case
    with connection() as c:
        other, _ = create_draft(c, case["bid"], case["actor"], "同项目的其他草稿")
    assert case["client"].get(url(case).replace(str(case["draft"]), str(other))).status_code == 404
    assert case["client"].get(url(case, digest="f" * 64)).status_code == 412


def test_closed_project_read_survives_but_restore_still_requires_reopen(history_case):
    case = history_case
    with connection() as c:
        command = Command(c, case["actor"], "history-test-terminate", case["bid"], uuid4().hex, {})
        lifecycle.change(c, case["bid"], case["actor"], "terminate", "明确关闭合成项目", command.id)
        command.finish({"closed": True})
    response = case["client"].get(url(case))
    assert response.status_code == 200 and response.json()["restoration_authorized"] is False
    before = counts(case)
    denied, _, _ = restore(case, case["section"]["revision"])
    assert denied.status_code == 409 and denied.json()["code"] == "PROJECT_WORK_CLOSED"
    assert counts(case) == before


def test_withdrawn_source_history_is_readable_but_old_revision_restore_rejected(history_case):
    case = history_case
    save(case, text="撤回前已经保存的新稿")
    with connection() as c:
        root = original_source_id(case["source_document"])
        revision = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (root,)
        ).fetchone()["revision"]
        withdraw_source(c, case["bid"], root, revision)
    response = case["client"].get(url(case))
    assert response.status_code == 200, response.text
    assert response.json()["content"] == case["section"]["content"]
    assert response.json()["source_qualification_assessed"] is False
    before = counts(case)
    denied, _, _ = restore(case, case["section"]["revision"])
    assert denied.status_code == 409 and denied.json()["code"] == "AUTHORING_SOURCE_STALE"
    assert counts(case) == before


def test_restore_conflict_keeps_old_history_and_does_not_append(history_case):
    case = history_case
    save(case, text="另一次明确保存")
    before = counts(case)
    response, _, _ = restore(case, 2, base_draft=2, base_section=2)
    assert response.status_code == 412
    assert counts(case) == before
    assert case["client"].get(url(case)).status_code == 200


def test_long_rich_original_image_binding_and_withdrawn_asset_boundary(history_case, monkeypatch):
    case = history_case
    asset = image_asset(case)
    content = deepcopy(case["section"]["content"])
    content["attrs"]["ordinal"] = 7
    content["content"] = [
        paragraph("原生历史正文。" * 20000),
        table(row(cell(2, 2), cell()), row(cell())),
        {
            "type": "image",
            "attrs": {
                "id": uuid4().hex,
                "asset_id": asset["asset_id"],
                "asset_revision": asset["revision"],
                "asset_version_id": asset["id"],
                "width_twips": 2400,
                "height_twips": 2400,
                "alt": "合成历史图片",
                "caption": "固定原版本",
            },
        },
    ]
    save(case, content=content)
    _, rich = current(case)
    save(case, content=case["section"]["content"])
    with connection() as c:
        rich_assets.withdraw(
            c,
            case["bid"],
            UUID(asset["asset_id"]),
            case["actor"],
            asset["etag"],
            "合成图片明确停用",
        )
    no_io(monkeypatch)
    response = case["client"].get(url(case, section=rich))
    assert response.status_code == 200, response.text
    value = contract.checked(response.json())
    assert value["content"] == content and value["content"]["attrs"]["ordinal"] == 7
    assert value["images"] == [
        {
            "asset_id": asset["asset_id"],
            "asset_revision": asset["revision"],
            "asset_version_id": asset["id"],
            "version_digest": asset["digest"],
            "normalized_sha256": asset["normalization_proof"]["output_digest"],
            "media_type": "image/png",
        }
    ]
    assert "object_key" not in response.text and "normalization_proof" not in response.text
    before = counts(case)
    denied, _, _ = restore(case, rich["revision"])
    assert denied.status_code == 409 and denied.json()["code"] == "AUTHORING_IMAGE_STALE"
    assert counts(case) == before


@pytest.mark.parametrize("damage", ["digest", "schema", "closed_content"])
def test_native_bad_record_cannot_be_accepted_by_resealing_only_digest(history_case, damage):
    case, old = history_case, history_case["section"]
    content = deepcopy(old["content"])
    if damage == "closed_content":
        content["attrs"]["unrecognized"] = True
    digest = "e" * 64 if damage == "digest" else sha(content)
    schema = "e" * 64 if damage == "schema" else old["schema_digest"]
    with connection() as c:
        c.execute(
            """INSERT INTO design.section_revisions(id,bid_id,draft_id,section_id,revision,schema_digest,content,digest,created_by)
        VALUES(%s,%s,%s,%s,999,%s,%s,%s,%s)""",
            (
                uuid4(),
                case["bid"],
                case["draft"],
                old["section_id"],
                schema,
                Jsonb(content),
                digest,
                case["actor"],
            ),
        )
    response = case["client"].get(url(case, revision=999, digest=digest))
    assert response.status_code == 500 and response.json()["code"] == "AUTHORING_HISTORY_CORRUPT"


def test_same_rr_snapshot_and_actual_read_only_guard(history_case, monkeypatch):
    case = history_case
    native = repository.section
    observations = []

    def checked(c, *args):
        before = c.execute(
            "SELECT max(revision) AS revision FROM design.section_revisions WHERE section_id=%s",
            (case["section"]["section_id"],),
        ).fetchone()["revision"]
        save(case, text="读取期间的另一个事务保存")
        after = c.execute(
            "SELECT max(revision) AS revision FROM design.section_revisions WHERE section_id=%s",
            (case["section"]["section_id"],),
        ).fetchone()["revision"]
        observations.append((before, after))
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction), c.transaction():
            c.execute("UPDATE design.drafts SET revision=revision WHERE id=%s", (case["draft"],))
        return native(c, *args)

    monkeypatch.setattr(repository, "section", checked)
    response = case["client"].get(url(case))
    assert response.status_code == 200 and observations == [(2, 2)]
    assert current(case)[0] == 3


def test_missing_select_is_reported_without_privilege_repair(history_case):
    case = history_case
    owner = case["database"]["owner"]
    owner.execute("REVOKE SELECT ON design.section_revisions FROM tender_api")
    try:
        response = case["client"].get(url(case))
        assert (
            response.status_code == 503
            and response.json()["code"] == "AUTHORING_HISTORY_UNAVAILABLE"
        )
        assert not owner.execute(
            "SELECT has_table_privilege('tender_api','design.section_revisions','SELECT') AS ok"
        ).fetchone()["ok"]
    finally:
        owner.execute("GRANT SELECT ON design.section_revisions TO tender_api")


def test_nonowner_readiness_and_real_loopback_http(history_case):
    case = history_case
    ready = verify()
    assert ready["ready"] and ready["checks"]["role"]["owns"] is False
    channel = socket.socket()
    channel.bind(("127.0.0.1", 0))
    channel.listen(16)
    server = uvicorn.Server(
        uvicorn.Config(history_app(), log_level="critical", access_log=False, lifespan="off")
    )
    worker = threading.Thread(target=server.run, kwargs={"sockets": [channel]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        target = f"http://127.0.0.1:{channel.getsockname()[1]}" + url(case)
        with httpx.Client(trust_env=False, timeout=15) as client:
            assert client.get(target).status_code == 401
            response = client.get(
                target, headers={"Cookie": "session=" + case["client"].cookies.get("session")}
            )
            assert response.status_code == 200 and response.json()["revision"] == 2
            assert response.headers["cache-control"] == "private, no-store"
            case["database"]["owner"].execute(
                "UPDATE design.members SET active=false WHERE id=%s", (case["actor"],)
            )
            assert (
                client.get(
                    target, headers={"Cookie": "session=" + case["client"].cookies.get("session")}
                ).status_code
                == 401
            )
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        channel.close()
        assert not worker.is_alive()


def test_actual_main_http_old_restore_and_public_contract(history_case, monkeypatch):
    """No test router overlays; exercise the actual application and real TCP."""
    from apps.api.authoring_history_routes import historical_section
    from apps.api.main import app

    case = history_case
    save(case, text="主入口恢复前的当前稿")
    no_io(monkeypatch)
    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == contract.PATH and "GET" in getattr(route, "methods", [])
    ]
    assert len(routes) == 1 and routes[0].endpoint is historical_section
    channel = socket.socket()
    channel.bind(("127.0.0.1", 0))
    channel.listen(16)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on")
    )
    worker = threading.Thread(target=server.run, kwargs={"sockets": [channel]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        base = f"http://127.0.0.1:{channel.getsockname()[1]}"
        with httpx.Client(base_url=base, trust_env=False, timeout=15) as client:
            assert client.get(url(case)).status_code == 401
            client.cookies.set("session", case["client"].cookies.get("session"))
            before = counts(case)
            old = client.get(url(case))
            assert old.status_code == 200 and old.json()["revision"] == 2
            assert old.headers["cache-control"].replace(" ", "") == "private,no-store"
            assert old.headers["vary"] == "Cookie" and "etag" not in old.headers
            assert counts(case) == before
            assert client.get(url(case) + "&expected_digest=" + "a" * 64).status_code == 422
            assert client.get(url(case) + "&unknown=true").status_code == 422
            spec = client.get("/openapi.json")
            assert spec.status_code == 200
            assert spec.json()["paths"][contract.PATH]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"] == {"$ref": "#/components/schemas/AuthoringHistoricalSectionView"}
            headers = {
                "Origin": os.environ["APP_ORIGIN"],
                "X-CSRF-Token": case["csrf"],
                "If-Match": etag("draft", case["draft"], 3),
                "Idempotency-Key": uuid4().hex,
            }
            path = f"/api/v1/bids/{case['bid']}/sections/{case['section']['section_id']}/restore"
            body = {"revision": 2, "base_draft_revision": 3, "base_section_revision": 3}
            restored = client.post(path, headers=headers, json=body)
            assert restored.status_code == 200 and restored.json()["draft_revision"] == 4
            assert current(case)[1]["content"] == old.json()["content"]
            replay = client.post(path, headers=headers, json=body)
            assert replay.status_code == 200 and replay.json() == restored.json()
            assert replay.headers["Idempotent-Replayed"] == "true"
            assert client.get(url(case)).json() == old.json()
            after = counts(case)
            assert after["sections"] == before["sections"] + 1
            assert after["snapshots"] == before["snapshots"] + 1
            assert after["commands"] == before["commands"] + 1
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        channel.close()
        assert not worker.is_alive()
