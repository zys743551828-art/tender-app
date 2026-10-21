"""Real PG17/nonowner/HTTP checks for fixed authoring and explicit stage choices.

All contents, source records and model responses are explicit synthetic fixtures.
Context requests perform no original-object I/O, model calls or business writes.
"""
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
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb
from test_authoring_package_adoptions_pg import build, env
from test_authoring_rich import cell, paragraph, row, table
from test_bid_package_submissions_pg import (
    api,
    catalog,
    database,
    exact,
    inventory,
    requirements,
    uid,
    world,
)
from test_package_outcomes_pg import setup as official_result
from test_work_contexts_pg import TestExactRunContexts as _RunCases
from test_work_contexts_pg import build_client, forbid_io, totals
from work_context_catalog_fixtures import (
    catalog_app,
    client_for,
    complete_build,
    current,
    image_asset,
    openapi,
    path,
    queue_build,
    save,
)

from apps.worker import engine
from deploy.work_context_catalog_readiness import verify
from packages.authoring import build_repository, rich_assets
from packages.authoring.repository import create_draft, freeze, latest_sections
from packages.authoring.snapshot_structure import reconcile
from packages.contracts import work_context_catalog_api as contract
from packages.domain.review_identity import digest
from packages.domain.runtime import connection, sha
from packages.work_contexts import (
    authoring_repository,
    catalog_permissions,
    permissions,
)
from packages.work_contexts import catalog as directory

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner work-context catalog PostgreSQL 17 required",
)


def test_saved_snapshot_remains_exact_after_edit_nonowner_rr_ro_and_no_effects(
    env, build_client, monkeypatch
):
    old_id = env["saved"]["snapshot_id"]
    later = save(env, text="新版正文不能替换所选历史正文")
    forbid_io(monkeypatch)
    checked, original = [], permissions.require

    def verify_role(c, kind):
        value = original(c, kind)
        checked.append(value)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction), c.transaction():
            c.execute("UPDATE design.drafts SET revision=revision WHERE id=%s", (env["draft"],))
        return value

    monkeypatch.setattr(permissions, "require", verify_role)
    before = totals(env["database"]["owner"])
    with client_for(build_client) as client:
        response = client.get(path(env["bid"], "draft_snapshot", old_id))
        assert response.status_code == 200, response.text
        value = response.json()
        assert contract.valid("AuthoringWorkContext", value)
        assert value["selection"]["snapshot_id"] == old_id != later["snapshot_id"]
        assert value["selection_digest"] == digest(value["selection"])
        assert value["current_observation"]["draft_head"]["status"] == "changed"
        assert value["current_observation"]["sources"]["status"] == "unknown"
        assert (
            value["current_observation"]["sources"]["reason"]
            == "REFERENCES_MATCH_QUALIFICATION_UNASSESSED"
        )
        assert value["document"]["sections"][0]["content"]["content"][0]["content"][0][
            "text"
        ].startswith("Synthetic manual")
        assert value["summary"]["formal_scoring"]["numeric_prediction"] is None
        assert value["summary"]["whole_package_blocking_risk_count"] is None
        assert not value["qualification_assessed"] and not value["document"]["editable"]
        assert response.headers["cache-control"] == "private, no-store"
        fixed = client.get(
            path(env["bid"], "draft_snapshot", old_id),
            params={"expected_selection_digest": value["selection_digest"]},
        )
        assert (
            fixed.status_code == 200
            and fixed.json()["observation_digest"] == value["observation_digest"]
        )
        assert (
            client.get(
                path(env["bid"], "draft_snapshot", old_id),
                params={"expected_selection_digest": "0" * 64},
            ).status_code
            == 412
        )
        assert client.get(path(uid(), "draft_snapshot", old_id)).status_code == 404
        assert client.get(path(env["bid"], "draft_snapshot", uid())).status_code == 404
    assert totals(env["database"]["owner"]) == before
    assert checked and all(
        item["role"]["isolation"] == "repeatable read" and item["role"]["read_only"] == "on"
        for item in checked
    )


def test_complete_long_rich_body_native_asset_withdrawal_and_source_change_keep_history(
    env, build_client, monkeypatch
):
    image = image_asset(env)
    _, section = current(env)
    content = deepcopy(section["content"])
    text = "完整长文保持原稿并支持精确检视。" * 15000
    content["content"] = [
        paragraph(text),
        table(row(cell(2, 2), cell()), row(cell())),
        {
            "type": "image",
            "attrs": {
                "id": uuid4().hex,
                "asset_id": image["asset_id"],
                "asset_revision": image["revision"],
                "asset_version_id": image["id"],
                "width_twips": 2400,
                "height_twips": 2400,
                "alt": "合成图片",
                "caption": "真实图片版本机制",
            },
        },
    ]
    saved = save(env, content=content)
    forbid_io(monkeypatch)
    endpoint = path(env["bid"], "draft_snapshot", saved["snapshot_id"])
    with client_for(build_client) as client:
        response = client.get(endpoint)
        assert response.status_code == 200, response.text
        before = response.json()
        assert before["document"]["sections"][0]["content"] == content
        assert len(before["document"]["images"]) == 1
        assert before["document"]["images"][0]["asset_version_id"] == image["id"]
        assert before["current_observation"]["assets"]["status"] == "matched"
        assert "object_key" not in response.text and "authoring-images/" not in response.text
        with connection() as c:
            rich_assets.withdraw(
                c,
                env["bid"],
                UUID(image["asset_id"]),
                env["actor"],
                image["etag"],
                "明确撤回合成图片",
            )
            c.execute("SELECT pg_advisory_xact_lock(90127,1)")
            c.execute(
                "UPDATE retrieval.source_heads h SET status='withdrawn',revision=revision+1 FROM retrieval.source_nodes n WHERE h.source_id=n.id AND n.document_version_id=%s",
                (env["source_document"],),
            )
        response = client.get(
            endpoint, params={"expected_selection_digest": before["selection_digest"]}
        )
        assert response.status_code == 200, response.text
        after = response.json()
        assert after["selection"] == before["selection"] and after["document"] == before["document"]
        assert after["observation_digest"] != before["observation_digest"]
        assert after["current_observation"]["sources"]["status"] == "changed"
        assert after["current_observation"]["assets"]["status"] == "changed"


def test_one_snapshot_prevents_mixed_old_body_and_new_head_observation(
    env, build_client, monkeypatch
):
    original, changed = authoring_repository.snapshot, []

    def change_after_read(c, bid, identity):
        result = original(c, bid, identity)
        if not changed:
            changed.append(save(env, text="并发保存后的正文"))
        return result

    monkeypatch.setattr(authoring_repository, "snapshot", change_after_read)
    endpoint = path(env["bid"], "draft_snapshot", env["saved"]["snapshot_id"])
    with client_for(build_client) as client:
        first = client.get(endpoint)
        assert first.status_code == 200, first.text
        assert first.json()["current_observation"]["draft_head"]["status"] == "matched"
        second = client.get(endpoint)
        assert second.status_code == 200, second.text
        assert second.json()["current_observation"]["draft_head"]["status"] == "changed"
        assert second.json()["document"] == first.json()["document"]
        assert second.json()["selection_digest"] == first.json()["selection_digest"]


@pytest.mark.parametrize(
    "mutation", ["section_id", "revision_id", "revision", "duplicate", "extra_key"]
)
def test_resealed_snapshot_cannot_replace_native_section_identity(env, build_client, mutation):
    owner, identity = env["database"]["owner"], env["saved"]["snapshot_id"]
    original = owner.execute(
        "SELECT manifest,digest FROM design.draft_snapshots WHERE id=%s", (identity,)
    ).fetchone()
    altered = deepcopy(original["manifest"])
    if mutation in {"section_id", "revision_id"}:
        altered["sections"][0]["id" if mutation == "section_id" else mutation] = uid()
    elif mutation == "revision":
        altered["sections"][0]["revision"] += 1
    elif mutation == "duplicate":
        altered["sections"].append(deepcopy(altered["sections"][0]))
    else:
        altered["sections"][0]["private_request"] = "must not become trusted snapshot data"
    owner.execute("ALTER TABLE design.draft_snapshots DISABLE TRIGGER immutable_guard")
    try:
        owner.execute(
            "UPDATE design.draft_snapshots SET manifest=%s,digest=%s WHERE id=%s",
            (Jsonb(altered), sha(altered), identity),
        )
        with client_for(build_client) as client:
            response = client.get(path(env["bid"], "draft_snapshot", identity))
            assert (
                response.status_code == 500 and response.json()["code"] == "WORK_CONTEXT_CORRUPT"
            ), response.text
    finally:
        owner.execute(
            "UPDATE design.draft_snapshots SET manifest=%s,digest=%s WHERE id=%s",
            (Jsonb(original["manifest"]), original["digest"], identity),
        )
        owner.execute("ALTER TABLE design.draft_snapshots ENABLE TRIGGER immutable_guard")


def test_saved_structure_and_zero_active_sections_are_native_complete_snapshots(env, build_client):
    with connection() as c:
        rows = latest_sections(c, env["bid"], env["draft"], include_deleted=True)
        state = reconcile(None, rows)
        # This is the native tree deletion representation, retaining the old node.
        state["nodes"][0]["deleted"] = True
        c.execute("UPDATE design.drafts SET revision=revision+1 WHERE id=%s", (env["draft"],))
        saved = freeze(c, env["bid"], env["draft"], 3, actor=env["actor"], structure_state=state)
    with client_for(build_client) as client:
        response = client.get(path(env["bid"], "draft_snapshot", saved["snapshot_id"]))
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["snapshot"]["section_count"] == 0
        assert value["document"]["sections"] == value["document"]["outline"] == []
        old = client.get(path(env["bid"], "draft_snapshot", env["saved"]["snapshot_id"]))
        assert old.status_code == 200 and len(old.json()["document"]["sections"]) == 1


def test_missing_native_snapshot_section_binding_is_not_silently_omitted(env, build_client):
    owner, identity = env["database"]["owner"], env["saved"]["snapshot_id"]
    member = owner.execute(
        "SELECT * FROM design.draft_snapshot_sections WHERE snapshot_id=%s", (identity,)
    ).fetchone()
    owner.execute("ALTER TABLE design.draft_snapshot_sections DISABLE TRIGGER immutable_guard")
    try:
        owner.execute(
            "DELETE FROM design.draft_snapshot_sections WHERE snapshot_id=%s", (identity,)
        )
        with client_for(build_client) as client:
            response = client.get(path(env["bid"], "draft_snapshot", identity))
            assert (
                response.status_code == 500 and response.json()["code"] == "WORK_CONTEXT_CORRUPT"
            ), response.text
            response = client.get(path(env["bid"], "choices"), params={"kind": "draft_snapshot"})
            assert response.status_code == 500, response.text
    finally:
        owner.execute(
            "INSERT INTO design.draft_snapshot_sections(snapshot_id,bid_id,draft_id,section_revision_id,ordinal) VALUES(%s,%s,%s,%s,%s)",
            tuple(
                member[key]
                for key in ("snapshot_id", "bid_id", "draft_id", "section_revision_id", "ordinal")
            ),
        )
        owner.execute("ALTER TABLE design.draft_snapshot_sections ENABLE TRIGGER immutable_guard")


def test_exact_build_real_word_failed_pdf_distinct_build_and_no_original_io(
    env, build_client, monkeypatch
):
    first, message = queue_build(env, ("docx", "pdf"))
    complete_build(message)
    second, _ = queue_build(env)
    forbid_io(monkeypatch)
    before = totals(env["database"]["owner"])
    with client_for(build_client) as client:
        response = client.get(path(env["bid"], "build", first))
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["selection"]["build_id"] == str(first) != str(second)
        assert value["selection"]["snapshot_id"] == env["saved"]["snapshot_id"]
        assert value["document"] is None and value["build"]["operation_state"] == "succeeded"
        outputs = {item["format"]: item for item in value["build"]["outputs"]}
        assert (
            outputs["docx"]["state"] == "succeeded" and outputs["docx"]["document"]["byte_size"] > 0
        )
        assert (
            outputs["pdf"]["state"] == "failed"
            and outputs["pdf"]["document"] is None
            and outputs["pdf"]["gaps"]
        )
        assert value["native_targets"]["build_relations"]["build_id"] == str(first)
        assert "object_key" not in response.text and "idempotency" not in response.text
        assert client.get(path(uid(), "build", first)).status_code == 404
        listed = client.get(path(env["bid"], "choices"), params={"kind": "build"})
        assert listed.status_code == 200, listed.text
        choices = {item["id"]: item for item in listed.json()["items"]}
        assert set(choices) == {str(first), str(second)}
        assert choices[str(first)]["selection"] == value["selection"]
        assert choices[str(first)]["selection_digest"] == value["selection_digest"]
    assert totals(env["database"]["owner"]) == before


@pytest.mark.parametrize("mutation", ["wrong_snapshot", "wrong_output", "missing_receipt"])
def test_build_publication_proof_is_native_and_cannot_be_replaced(env, build_client, mutation):
    identity, _body, _computed = build(env)
    owner = env["database"]["owner"]
    saved = owner.execute(
        "SELECT id,event_type,payload FROM design.audit_entries WHERE bid_id=%s AND event_type='build.outputs_published' AND payload->>'build_id'=%s",
        (env["bid"], str(identity)),
    ).fetchone()
    altered = deepcopy(saved["payload"])
    if mutation == "wrong_snapshot":
        altered["snapshot_id"] = uid()
    elif mutation == "wrong_output":
        altered["outputs"]["docx"] = uid()
    event = (
        "synthetic.missing-publication" if mutation == "missing_receipt" else saved["event_type"]
    )
    owner.execute("ALTER TABLE design.audit_entries DISABLE TRIGGER immutable_guard")
    try:
        owner.execute(
            "UPDATE design.audit_entries SET event_type=%s,payload=%s WHERE id=%s",
            (event, Jsonb(altered), saved["id"]),
        )
        with client_for(build_client) as client:
            response = client.get(path(env["bid"], "build", identity))
            assert (
                response.status_code == 500 and response.json()["code"] == "WORK_CONTEXT_CORRUPT"
            ), response.text
            response = client.get(path(env["bid"], "choices"), params={"kind": "build"})
            assert response.status_code == 500, response.text
    finally:
        owner.execute(
            "UPDATE design.audit_entries SET event_type=%s,payload=%s WHERE id=%s",
            (saved["event_type"], Jsonb(saved["payload"]), saved["id"]),
        )
        owner.execute("ALTER TABLE design.audit_entries ENABLE TRIGGER immutable_guard")


def test_failed_native_build_never_remains_pending_or_claims_a_document(
    env, build_client, monkeypatch
):
    identity, message = queue_build(env)
    with client_for(build_client) as client:
        response = client.get(path(env["bid"], "build", identity))
        assert response.status_code == 200, response.text
        before = response.json()
        assert before["build"]["outputs"][0]["state"] == "pending"
        with monkeypatch.context() as patch:
            patch.setattr(build_repository, "WRITER_DIGEST", "0" * 64)
            engine.handle_lane("export", message)
        forbid_io(monkeypatch)
        response = client.get(path(env["bid"], "build", identity))
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["selection"] == before["selection"]
        assert value["build"]["operation_state"] == "failed"
        assert value["build"]["outputs"][0]["state"] == "not_published"
        assert value["build"]["outputs"][0]["document"] is None


def test_choice_pagination_has_no_default_and_rejects_new_record_or_wrong_scope(
    env, build_client, monkeypatch
):
    saved = save(env, text="第三次明确保存")
    endpoint = path(env["bid"], "choices")
    with client_for(build_client) as client:
        first = client.get(endpoint, params={"kind": "draft_snapshot", "limit": 1})
        assert first.status_code == 200, first.text
        first = first.json()
        assert first["total"] == 3 and first["has_more"]
        assert first["items"][0]["id"] == saved["snapshot_id"]
        assert "selected" not in first and first["selection_requires_resolution"]
        identities, cursor = [first["items"][0]["id"]], first["next_cursor"]
        while cursor:
            response = client.get(
                endpoint, params={"kind": "draft_snapshot", "limit": 1, "cursor": cursor}
            )
            assert response.status_code == 200, response.text
            value = response.json()
            assert value["observation_digest"] == first["observation_digest"]
            identities += [item["id"] for item in value["items"]]
            cursor = value["next_cursor"]
        assert len(identities) == len(set(identities)) == 3
        assert (
            client.get(
                endpoint, params={"kind": "build", "cursor": first["next_cursor"]}
            ).status_code
            == 422
        )
        assert (
            client.get(
                endpoint,
                params={
                    "kind": "draft_snapshot",
                    "draft_id": str(env["draft"]),
                    "cursor": first["next_cursor"],
                },
            ).status_code
            == 422
        )
        save(env, text="分页后明确新增的保存")
        stale = client.get(
            endpoint, params={"kind": "draft_snapshot", "cursor": first["next_cursor"]}
        )
        assert (
            stale.status_code == 409 and stale.json()["code"] == "WORK_CONTEXT_OBSERVATION_CHANGED"
        ), stale.text
        with monkeypatch.context() as patch:
            patch.setattr(directory, "MAX_RECORDS", 1)
            assert client.get(endpoint, params={"kind": "draft_snapshot"}).status_code == 413
        with monkeypatch.context() as patch:
            patch.setattr(authoring_repository, "MAX_SNAPSHOT_BYTES", 1)
            assert (
                client.get(path(env["bid"], "draft_snapshot", saved["snapshot_id"])).status_code
                == 413
            )


def test_build_state_change_invalidates_choice_cursor(env, build_client):
    first, message = queue_build(env)
    queue_build(env)
    with client_for(build_client) as client:
        endpoint = path(env["bid"], "choices")
        response = client.get(endpoint, params={"kind": "build", "limit": 1})
        assert response.status_code == 200, response.text
        cursor = response.json()["next_cursor"]
        assert cursor
        complete_build(message)
        response = client.get(endpoint, params={"kind": "build", "cursor": cursor})
        assert response.status_code == 409, response.text


def test_choices_auth_filters_explicit_empty_and_actual_additional_permission_failure(
    env, build_client
):
    endpoint = path(env["bid"], "choices")
    with TestClient(catalog_app()) as unauth:
        assert unauth.get(endpoint, params={"kind": "draft_snapshot"}).status_code == 401
    with client_for(build_client) as client:
        for suffix in (
            "?kind=latest",
            "?kind=build&kind=draft_snapshot",
            "?kind=build&latest=true",
            "?kind=build&limit=0",
            "",
        ):
            assert client.get(endpoint + suffix).status_code == 422
        assert client.post(endpoint, json={}).status_code == 405
        assert (
            client.get(endpoint, params={"kind": "draft_snapshot", "package_id": uid()}).status_code
            == 422
        )
        assert (
            client.get(
                endpoint, params={"kind": "package_submission", "draft_id": str(env["draft"])}
            ).status_code
            == 422
        )
        assert (
            client.get(endpoint, params={"kind": "draft_snapshot", "draft_id": uid()}).status_code
            == 404
        )
        for kind in ("build", "package_review_run", "package_submission"):
            response = client.get(endpoint, params={"kind": kind})
            assert response.status_code == 200, response.text
            value = response.json()
            assert (
                value["items"] == []
                and value["total"] == 0
                and not value["has_more"]
                and value["next_cursor"] is None
            )
        owner = env["database"]["owner"]
        owner.execute("REVOKE SELECT ON design.drafts FROM tender_api")
        try:
            response = client.get(endpoint, params={"kind": "draft_snapshot"})
            assert (
                response.status_code == 503
                and response.json()["code"] == "WORK_CONTEXT_UNAVAILABLE"
            ), response.text
        finally:
            owner.execute("GRANT SELECT ON design.drafts TO tender_api")


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestPackageRunChoices:
    original_case = _RunCases.original_case
    frozen_case = _RunCases.frozen_case
    execution_case = _RunCases.execution_case
    prepared_case = _RunCases.prepared_case
    exact_inventory_proof_case = _RunCases.exact_inventory_proof_case
    launch_case = _RunCases.launch_case
    post = _RunCases.post
    launch = _RunCases.launch
    message = _RunCases.message
    provider = _RunCases.provider
    equivalent_case = _RunCases.equivalent_case
    finish = _RunCases.finish
    completed = _RunCases.completed

    def test_exact_run_directory_fixed_resolver_and_explicit_package_filter(
        self, completed, monkeypatch
    ):
        case, w = completed, completed["w"]
        later = self.finish(
            self.equivalent_case(case, rerun={"nonce": uid(), "reason": "合成第二轮核查"})
        )
        forbid_io(monkeypatch)
        endpoint = path(case["scope"][0], "choices")
        with client_for(w["client"]) as client:
            response = client.get(
                endpoint,
                params={
                    "kind": "package_review_run",
                    "package_id": case["scope"][1],
                    "revision_id": case["scope"][2],
                },
            )
            assert response.status_code == 200, response.text
            choices = {item["id"]: item for item in response.json()["items"]}
            assert set(choices) == {case["run"]["id"], later["id"]}
            exact = client.get(path(case["scope"][0], "package_review_run", case["run"]["id"]))
            assert exact.status_code == 200, exact.text
            assert choices[case["run"]["id"]]["selection"] == exact.json()["selection"]
            assert (
                choices[case["run"]["id"]]["selection_digest"] == exact.json()["selection_digest"]
            )
            assert (
                client.get(
                    endpoint, params={"kind": "package_review_run", "package_id": uid()}
                ).status_code
                == 404
            )


def test_submission_choices_exclude_single_body_and_cannot_read_official_labels(exact, monkeypatch):
    w = official_result(exact)
    legacy = uid()
    with connection() as c:
        c.execute(
            "INSERT INTO design.submission_records(id,bid_id,subject_kind,body_version_id,kind,evidence,submitted_at,created_by) VALUES(%s,%s,'single_body',%s,'offline_fact','{}',clock_timestamp(),%s)",
            (legacy, w["scope"].bid_id, w["member"].document_version_id, w["actor"]),
        )
    owner = w["database"]["owner"]
    names = [
        row["name"]
        for row in owner.execute(
            "SELECT n.nspname||'.'||c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='design' AND c.relname IN ('outcomes','outcome_heads','business_results','business_result_heads','package_outcome_verifications')"
        ).fetchall()
    ]
    for name in names:
        owner.execute(
            sql.SQL("REVOKE SELECT ON {} FROM tender_api").format(sql.Identifier(*name.split(".")))
        )
    forbid_io(monkeypatch)
    before = totals(owner)
    try:
        with client_for(w["client"]) as client:
            response = client.get(
                path(w["scope"].bid_id, "choices"), params={"kind": "package_submission"}
            )
            assert response.status_code == 200, response.text
            value = response.json()
            assert value["total"] == 1 and value["items"][0]["id"] == w["submission"]["id"]
            resolved = client.get(
                path(w["scope"].bid_id, "package_submission", w["submission"]["id"])
            )
            assert resolved.status_code == 200, resolved.text
            assert value["items"][0]["selection"] == resolved.json()["selection"]
            assert value["items"][0]["selection"]["review_run"] is None
            assert (
                w["result"]["id"] not in response.text
                and "technical_total" not in response.text
                and legacy not in response.text
            )
        assert totals(owner) == before
    finally:
        for name in names:
            owner.execute(
                sql.SQL("GRANT SELECT ON {} TO tender_api").format(sql.Identifier(*name.split(".")))
            )


def test_actual_loopback_http_cookie_readiness_and_native_snapshot(env, build_client):
    readiness = verify()
    assert readiness["ready"] and not readiness["ddl_applied"]
    assert set(readiness["checks"]) == set(contract.KINDS)
    channel = socket.socket()
    channel.bind(("127.0.0.1", 0))
    channel.listen(16)
    server = uvicorn.Server(
        uvicorn.Config(catalog_app(), log_level="critical", access_log=False, lifespan="off")
    )
    worker = threading.Thread(target=server.run, kwargs={"sockets": [channel]}, daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    try:
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        url = f"http://127.0.0.1:{channel.getsockname()[1]}" + path(
            env["bid"], "draft_snapshot", env["saved"]["snapshot_id"]
        )
        with httpx.Client(trust_env=False, timeout=15) as client:
            assert client.get(url).status_code == 401
            response = client.get(
                url, headers={"Cookie": "session=" + build_client.cookies.get("session")}
            )
            assert response.status_code == 200, response.text
            assert response.json()["selection"]["snapshot_id"] == env["saved"]["snapshot_id"]
            assert response.headers["cache-control"] == "private, no-store"
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        channel.close()
        assert not worker.is_alive()
