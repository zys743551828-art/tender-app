"""Explicit human edits over synthetic fixed sources; native PG17/API/Worker/S3."""
# ruff: noqa: F401,F811

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile

import psycopg
import pytest
from authoring_package_input_fixtures import ADMIN_DSN, world
from authoring_package_job_fixtures import case, current, finish, input_database, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_builds_pg import adopted, compute, exact, publish, start
from test_authoring_exact_builds_pg import database as build_database
from test_authoring_exact_revisions_pg import confirm, published, qualified
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_package_inputs_pg import mutate_authority
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api, headers

from packages.authoring import exact_sources, exact_text_edit_service, exact_text_edits, repository
from packages.domain import original_verification, storage
from packages.domain.runtime import ROOT, DomainError, connection, sha

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated B5 PG17 and real S3")


@pytest.fixture(scope="module")
def database(build_database):
    with connection() as c:
        assert not exact_text_edits.available(c)
    build_database["owner"].execute(
        (ROOT / "packages/contracts/sql/authoring-exact-text-edits.sql").read_text()
    )
    with connection() as c:
        assert exact_text_edits.available(c)
    return build_database


def request_body(w, q=None):
    q = q or qualified(w)
    m = q["manifest"]
    with connection() as c:
        row = c.execute(
            "SELECT content FROM design.section_revisions WHERE id=%s", (m["section_revision_id"],)
        ).fetchone()
    node = row["content"]["content"][0]
    return {
        "base_draft_revision": w["saved"]["draft_revision"],
        "section_revision_id": m["section_revision_id"],
        "node_id": node["attrs"]["id"],
        "before_node_digest": sha(node),
        "replacement_text": "Synthetic explicitly edited paragraph — 人工修改。",
        "reason": "Synthetic user wording correction; existing source chain retained",
    }


def edit(w, body=None, *, key=None, condition=None):
    body = body or request_body(w)
    return w["client"].post(
        f"/api/v1/bids/{w['bid']}/authoring/drafts/{w['saved']['draft_id']}/exact-text-edits",
        json=body,
        headers=headers(
            w,
            key=key,
            etag=condition
            or repository.draft_etag(w["saved"]["draft_id"], body["base_draft_revision"]),
        ),
    )


def unchanged(w):
    with connection() as c:
        assert (
            c.execute(
                "SELECT revision FROM design.drafts WHERE id=%s", (w["saved"]["draft_id"],)
            ).fetchone()["revision"]
            == w["saved"]["draft_revision"]
        )
        assert not c.execute(
            "SELECT 1 FROM design.authoring_exact_manual_revisions WHERE bid_id=%s", (w["bid"],)
        ).fetchone()


def test_edit_is_new_qualification_and_replays_original_ack(adopted):
    w = adopted
    root = qualified(w)
    body, key = request_body(w), str(uuid4())
    before_section = w["client"].get(f"/api/v1/sections/{root['section_id']}").json()
    before_status = (
        w["client"]
        .get(
            f"/api/v1/bids/{w['bid']}/authoring/drafts/{w['saved']['draft_id']}/exact-qualification"
        )
        .json()
    )
    response = edit(w, body, key=key)
    assert response.status_code == 200, response.text
    result = response.json()
    q = result["qualification"]
    assert result["draft_revision"] == body["base_draft_revision"] + 1
    assert q["manifest"]["candidate_adopted"] is False
    assert q["manifest"]["content_correctness_certified"] is False
    assert q["manifest"]["origin"]["root_qualification_id"] == str(root["id"])
    assert q["manifest"]["origin"]["root_qualification_digest"] == root["digest"]
    assert q["manifest"]["input"] == root["manifest"]["input"]
    assert q["digest"] == sha(q["manifest"])
    with connection() as c:
        loaded = exact_sources.load(c, UUID(w["bid"]), UUID(result["section_revision_id"]))
        assert loaded == q
        assert qualified(w) == root
        before = c.execute(
            "SELECT content FROM design.section_revisions WHERE id=%s",
            (body["section_revision_id"],),
        ).fetchone()["content"]
        after = c.execute(
            "SELECT content FROM design.section_revisions WHERE id=%s",
            (result["section_revision_id"],),
        ).fetchone()["content"]
        assert after == exact_text_edits.materialize(before, body)
        assert after["attrs"] == before["attrs"]
        status = exact_sources.draft_status(c, UUID(w["bid"]), UUID(result["draft_id"]))
        assert status["ordinary_edit_available"] is False
        assert status["exact_sections"][0]["qualification_id"] == q["manifest"]["id"]
    replayed = edit(w, body, key=key)
    assert replayed.status_code == 200 and replayed.json() == result, replayed.text
    assert replayed.headers["etag"] == response.headers["etag"]
    old = confirm(w)
    assert old.status_code == 200, old.text
    assert old.json()["result"]["assistant_resolution"]["domain_result"] == w["saved"]
    assert len(w["calls"]) == 1
    fixture_path = os.environ.get("FUSION_AUTHORING_TEXT_EDIT_FIXTURE_PATH")
    if fixture_path:
        Path(fixture_path).write_text(
            json.dumps(
                {
                    "fixture_kind": "synthetic source/model content; unchanged native PG17/API/Worker/S3 HTTP",
                    "member_id": w["actor"],
                    "bid_id": w["bid"],
                    "parent_section": before_section,
                    "parent_status": before_status,
                    "parent_qualification": {
                        "manifest": root["manifest"],
                        "digest": root["digest"],
                    },
                    "request": body,
                    "request_key": key,
                    "request_etag": repository.draft_etag(
                        w["saved"]["draft_id"], body["base_draft_revision"]
                    ),
                    "ack": result,
                    "ack_etag": response.headers["etag"],
                    "capabilities": w["client"]
                    .get("/api/v1/authoring/exact-text-edit-capabilities")
                    .json(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )


def test_repeated_manual_revision_builds_real_word(adopted):
    w = adopted
    first = edit(w)
    assert first.status_code == 200, first.text
    w["saved"] = first.json()
    body = request_body(w, first.json()["qualification"])
    body["replacement_text"] = "Synthetic second manual revision — 再次修改。"
    second = edit(w, body)
    assert second.status_code == 200, second.text
    w["saved"] = second.json()
    assert (
        second.json()["qualification"]["manifest"]["origin"]["parent_qualification_id"]
        == first.json()["qualification"]["manifest"]["id"]
    )
    build = start(w)
    result = compute(build)
    raw = storage.get(result["outputs"][0]["object_key"])
    with ZipFile(io.BytesIO(raw)) as archive:
        assert body["replacement_text"] in archive.read("word/document.xml").decode()
    publish(build, result)
    assert len(w["calls"]) == 1


@pytest.mark.parametrize("change", ["source", "facts", "rule", "closed"])
def test_old_ack_survives_authority_loss_but_new_edit_cannot(adopted, change):
    w = adopted
    body, key = request_body(w), uuid4().hex
    saved = edit(w, body, key=key)
    assert saved.status_code == 200, saved.text
    mutate_authority(w, change)
    replay = edit(w, body, key=key)
    assert replay.status_code == 200 and replay.json() == saved.json(), replay.text
    w["saved"] = saved.json()
    newbody = request_body(w, saved.json()["qualification"])
    newbody["replacement_text"] = "Synthetic forbidden newer wording"
    failed = edit(w, newbody)
    assert failed.status_code == 409, failed.text


@pytest.mark.parametrize("mutation", ["node", "revision", "draft", "refs"])
def test_request_cannot_replace_saved_base_or_metadata(adopted, mutation):
    body = request_body(adopted)
    if mutation == "node":
        body["before_node_digest"] = "0" * 64
    elif mutation == "revision":
        body["section_revision_id"] = str(uuid4())
    elif mutation == "draft":
        body["base_draft_revision"] -= 1
    else:
        body["source_refs"] = []
    response = edit(adopted, body)
    assert response.status_code in {404, 412, 422}, response.text
    unchanged(adopted)


@pytest.mark.parametrize("missing", [False, True])
def test_original_bytes_are_required_without_partial_save(adopted, missing):
    w = adopted
    if missing:
        storage.client().delete_object(Bucket=storage.bucket(), Key=w["blob"]["object_key"])
    else:
        storage.put(w["blob"]["object_key"], b"synthetic incorrect source", "application/pdf")
    failed = edit(w)
    assert failed.status_code == 409, failed.text
    assert failed.json()["code"] in {"ORIGINAL_NOT_AVAILABLE", "ORIGINAL_BYTES_CORRUPTED"}
    unchanged(w)


def test_authority_change_during_original_io_cannot_save(adopted, monkeypatch):
    real_verify = original_verification.verify
    changed = []

    def verify(document):
        real_verify(document)
        if not changed:
            changed.append(True)
            mutate_authority(adopted, "source")

    monkeypatch.setattr(original_verification, "verify", verify)
    response = edit(adopted)
    assert response.status_code == 409, response.text
    unchanged(adopted)


def test_changed_actor_after_original_io_cannot_save(adopted):
    w = adopted
    body = request_body(w)
    with pytest.raises(DomainError) as error:
        exact_text_edit_service.save(
            w["actor"],
            w["bid"],
            w["saved"]["draft_id"],
            uuid4().hex,
            repository.draft_etag(w["saved"]["draft_id"], body["base_draft_revision"]),
            body,
            final_auth=lambda: {"member_id": uuid4()},
        )
    assert error.value.code == "AUTHORING_EXACT_ACTOR_CHANGED"
    unchanged(w)


def test_raw_sql_cannot_bypass_manual_qualification(adopted):
    w = adopted
    parent = qualified(w)
    with pytest.raises(psycopg.errors.CheckViolation):
        with connection() as c:
            original = c.execute(
                "SELECT * FROM design.section_revisions WHERE id=%s",
                (parent["section_revision_id"],),
            ).fetchone()
            c.execute(
                "INSERT INTO design.section_revisions(id,bid_id,draft_id,section_id,revision,content,digest,schema_digest,created_by) "
                "SELECT %s,bid_id,draft_id,section_id,revision+1,content,digest,schema_digest,created_by FROM design.section_revisions WHERE id=%s",
                (uuid4(), original["id"]),
            )
    unchanged(w)


def test_concurrent_same_original_request_gets_one_ack(adopted):
    w = adopted
    body, key = request_body(w), uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: edit(w, body, key=key), range(2)))
    assert all(r.status_code == 200 for r in replies), [r.text for r in replies]
    assert replies[0].json() == replies[1].json()
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.authoring_exact_manual_revisions WHERE bid_id=%s",
                (w["bid"],),
            ).fetchone()["n"]
            == 1
        )


def test_manual_qualification_command_and_worker_grants_are_immutable(adopted):
    w = adopted
    response = edit(w)
    assert response.status_code == 200, response.text
    result = response.json()
    manifest = result["qualification"]["manifest"]
    for query, identifier in (
        (
            "UPDATE design.authoring_exact_manual_revisions SET digest=digest WHERE id=%s",
            manifest["id"],
        ),
        ("DELETE FROM design.authoring_exact_manual_revisions WHERE id=%s", manifest["id"]),
        (
            "UPDATE design.commands SET response='{}'::jsonb WHERE id=%s",
            manifest["origin"]["command_id"],
        ),
        ("DELETE FROM design.commands WHERE id=%s", manifest["origin"]["command_id"]),
    ):
        with pytest.raises(
            (psycopg.errors.ObjectNotInPrerequisiteState, psycopg.errors.InsufficientPrivilege)
        ):
            with connection() as c:
                c.execute(query, (identifier,))
    with connection(True) as c:
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'design.authoring_exact_manual_revisions','SELECT') AS granted"
        ).fetchone()["granted"]
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'design.authoring_exact_revision_records','SELECT') AS granted"
        ).fetchone()["granted"]
        proof = c.execute(
            "SELECT design.authoring_exact_snapshot_proof(%s) AS value", (result["snapshot_id"],)
        ).fetchone()["value"]
        assert proof["sections"][0]["qualification_id"] == manifest["id"]
        assert not c.execute(
            "SELECT has_function_privilege(current_user,'design.authoring_exact_check_manual_record(uuid)','EXECUTE') AS granted"
        ).fetchone()["granted"]


def test_capability_fails_closed_without_insert_grant(adopted, database):
    owner = database["owner"]
    owner.execute("REVOKE INSERT ON design.authoring_exact_manual_revisions FROM tender_api")
    try:
        capabilities = adopted["client"].get("/api/v1/authoring/exact-text-edit-capabilities")
        assert capabilities.status_code == 200, capabilities.text
        assert capabilities.json()["available"] is False
        response = edit(adopted)
        assert response.status_code == 503, response.text
        unchanged(adopted)
    finally:
        owner.execute("GRANT INSERT ON design.authoring_exact_manual_revisions TO tender_api")


def test_missing_audit_receipt_fails_entire_native_transaction(adopted, monkeypatch):
    monkeypatch.setattr(exact_text_edit_service, "audit", lambda *args: None)
    response = edit(adopted)
    assert response.status_code == 409, response.text
    unchanged(adopted)


def test_same_key_changed_request_is_not_a_new_edit(adopted):
    w = adopted
    body, key = request_body(w), uuid4().hex
    response = edit(w, body, key=key)
    assert response.status_code == 200, response.text
    changed = {**body, "replacement_text": "Synthetic different request with old key"}
    conflict = edit(w, changed, key=key)
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT", (
        conflict.text
    )


@pytest.mark.parametrize("exact", ["mixed"], indirect=True)
def test_manual_edit_retains_unchanged_legacy_chapter(adopted):
    w = adopted
    response = edit(w)
    assert response.status_code == 200, response.text
    with connection() as c:
        snapshot = repository.snapshot_content(
            c, UUID(w["bid"]), UUID(response.json()["snapshot_id"])
        )
        assert len(snapshot["sections"]) == 2
        assert len(snapshot["authoring_exact_sections"]["sections"]) == 1
