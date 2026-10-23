"""B4 native PG17/API/Worker/S3 acceptance; model and source records are synthetic."""
# ruff: noqa: F401,F811

import io
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile

import psycopg
import pytest
from authoring_package_input_fixtures import ADMIN_DSN, world
from authoring_package_input_fixtures import exact as base_exact
from authoring_package_job_fixtures import case, current, finish, input_database, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_revisions_pg import confirm, published, qualified
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_package_inputs_pg import add_new_parse, mutate_authority
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api, headers

from apps.worker import engine, export_handlers
from packages.authoring import exact_builds, package_adoptions, package_outputs, repository
from packages.authoring.build_repository import DEFAULT_TEMPLATE_ID
from packages.authoring.content import empty_content
from packages.domain import original_verification, storage
from packages.domain.runtime import ROOT, DomainError, connection, sha
from packages.rag.indexing import original_source_id, parse_source_id

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated B4 PG17 and real S3")


@pytest.fixture(scope="module")
def database(revision_database):
    with connection() as c:
        assert not exact_builds.available(c)
    revision_database["owner"].execute(
        (ROOT / "packages/contracts/sql/authoring-exact-builds.sql").read_text()
    )
    return revision_database


@pytest.fixture
def exact(requirements, request):
    w = base_exact.__wrapped__(requirements)
    if getattr(request, "param", None) != "mixed":
        return w
    # A legacy chapter genuinely precedes B1 capture and B3 adoption. It must
    # retain ordinary latest-parse guards beside the exact qualified chapter.
    target = w["input_body"]["target_section"]
    section_id = uuid4()
    with connection() as c:
        draft = repository.lock_draft(c, UUID(w["bid"]), UUID(target["draft_id"]))
        evidence = c.execute(
            "SELECT id FROM design.evidence_blocks WHERE bid_id=%s AND parse_id=%s ORDER BY id LIMIT 1",
            (w["bid"], w["member"].parse.parse_run_id),
        ).fetchone()["id"]
        source = parse_source_id(UUID(w["member"].parse.parse_run_id))
        source_revision = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
        ).fetchone()["revision"]
        content = empty_content("Synthetic legacy chapter", 1)
        content["attrs"]["source_refs"] = [
            {
                "source_id": str(source),
                "source_revision": source_revision,
                "evidence_id": str(evidence),
                "document_version_id": w["member"].document_version_id,
            }
        ]
        c.execute(
            "INSERT INTO design.sections(id,bid_id,draft_id,head_revision) VALUES(%s,%s,%s,1)",
            (section_id, w["bid"], draft["id"]),
        )
        repository.append_section(
            c, UUID(w["bid"]), draft["id"], section_id, 1, content, UUID(w["actor"])
        )
        c.execute("UPDATE design.drafts SET revision=2 WHERE id=%s", (draft["id"],))
        saved = repository.freeze(c, UUID(w["bid"]), draft["id"], 2, actor=UUID(w["actor"]))
    target.update(
        base_draft_revision=2,
        snapshot_id=saved["snapshot_id"],
        snapshot_digest=saved["snapshot_digest"],
    )
    return w


@pytest.fixture
def adopted(published):
    response = confirm(published)
    assert response.status_code == 200, response.text
    published["saved"] = response.json()["result"]["assistant_resolution"]["domain_result"]
    return published


def request_body(w, **changes):
    return {
        "draft_id": w["saved"]["draft_id"],
        "draft_revision": w["saved"]["draft_revision"],
        "template_version_id": str(DEFAULT_TEMPLATE_ID),
        "formats": ["docx"],
        "follow_up": "none",
        **changes,
    }


def request_build(w, *, key=None, body=None):
    return w["client"].post(
        f"/api/v1/bids/{w['bid']}/builds",
        json=body or request_body(w),
        headers=headers(w, key=key),
    )


def start(w, *, formats=None):
    key = uuid4().hex
    body = request_body(w, formats=formats or ["docx"])
    response = request_build(w, key=key, body=body)
    assert response.status_code == 202, response.text
    with connection() as c:
        message = c.execute(
            "SELECT o.payload FROM design.builds b JOIN design.outbox o ON o.operation_id=b.operation_id "
            "WHERE b.id=%s AND o.topic='tender.task.export.v1'",
            (response.json()["resource_id"],),
        ).fetchone()["payload"]
    lease = engine.acquire(message)
    assert lease is not None
    return {
        "id": response.json()["resource_id"],
        "key": key,
        "body": body,
        "ack": response.json(),
        "message": message,
        "lease": lease,
    }


def compute(build):
    return engine.run_compute(build["message"], build["lease"])


def publish(build, computed):
    assert engine.finish(build["message"], build["lease"], computed)


def adoption_body(w, build):
    with connection() as c:
        document = c.execute(
            "SELECT document_version_id FROM design.build_outputs WHERE build_id=%s "
            "AND format='docx' AND state='succeeded'",
            (build["id"],),
        ).fetchone()["document_version_id"]
    return {
        "snapshot_id": w["saved"]["snapshot_id"],
        "snapshot_digest": w["saved"]["snapshot_digest"],
        "package_id": None,
        "member": {
            "member_id": "generated-" + str(document),
            "document_version_id": str(document),
            "purposes": ["technical"],
            "parts": [],
        },
        "reason": "Explicit synthetic exact authoring output selection",
    }


def adopt(w, build, body, *, key=None):
    return w["client"].post(
        f"/api/v1/bids/{w['bid']}/builds/{build['id']}/package-adoptions",
        json=body,
        headers=headers(w, key=key),
    )


def unpublished(build):
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.build_outputs WHERE build_id=%s", (build["id"],)
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM design.effect_receipts WHERE operation_id=%s AND effect_key='build-document'",
            (build["message"]["operation_id"],),
        ).fetchone()


def observe(w, body):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return package_outputs.observe_admission(c, w["bid"], body["member"]["document_version_id"])


def export_http(w, build, body, adoption, view):
    directory = os.environ.get("FUSION_AUTHORING_EXACT_FIXTURE_DIR")
    if not directory:
        return
    base = f"/api/v1/bids/{w['bid']}"
    package = adoption.json()["package"]["manifest"]
    paths = [
        "/api/v1/authoring/capabilities",
        "/api/v1/authoring/rich-capabilities",
        "/api/v1/authoring/exact-revision-capabilities",
        "/api/v1/authoring/templates",
        "/api/v1/operations/" + view.json()["operation_id"],
        base + "/drafts",
        base + "/drafts/" + w["saved"]["draft_id"],
        base + "/drafts/" + w["saved"]["draft_id"] + "/structure",
        base + "/authoring/drafts/" + w["saved"]["draft_id"] + "/exact-qualification",
        "/api/v1/sections/" + w["input_body"]["target_section"]["section_id"],
        base + "/draft-snapshots/" + w["saved"]["snapshot_id"],
        base + "/builds?draft_id=" + w["saved"]["draft_id"],
        base + "/packages?kind=bid&limit=20",
        base + "/packages/" + package["package_id"],
        base + "/packages/" + package["package_id"] + "/revisions/" + package["revision_id"],
        base + "/package-documents/" + body["member"]["document_version_id"] + "/parses?limit=20",
    ]
    reads = {}
    for path in paths:
        response = w["client"].get(path)
        reads[path] = {
            "status": response.status_code,
            "etag": response.headers.get("etag"),
            "body": response.json(),
        }
    structure = reads[base + "/drafts/" + w["saved"]["draft_id"] + "/structure"]["body"]
    for name in ("directory_template_version_id", "style_template_version_id"):
        path = "/api/v1/authoring/template-versions/" + structure[name]
        response = w["client"].get(path)
        reads[path] = {
            "status": response.status_code,
            "etag": response.headers.get("etag"),
            "body": response.json(),
        }
    value = {
        "fixture_kind": "synthetic source/model data; unchanged real PG17/API/Worker/S3 responses",
        "member_id": w["actor"],
        "bid_id": w["bid"],
        "saved": w["saved"],
        "build_request": build["body"],
        "build_ack": build["ack"],
        "build": view.json(),
        "adoption_request": body,
        "adoption_ack": adoption.json(),
        "adoption_etag": adoption.headers.get("etag"),
        "reads": reads,
    }
    (Path(directory) / "built-and-adopted.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )


def test_real_word_fixed_old_parse_complete_lineage_and_explicit_adoption(adopted, monkeypatch):
    w = adopted
    add_new_parse(w)
    active, checked = [], []
    real_connection, verify = export_handlers.connection, original_verification.verify

    @contextmanager
    def observed_connection(*args):
        with real_connection(*args) as c:
            active.append(c)
            yield c

    def outside_transaction(document):
        assert all(c.closed for c in active), "object verification must follow DB closure"
        checked.append(document["document_version_id"])
        verify(document)

    monkeypatch.setattr(export_handlers, "connection", observed_connection)
    monkeypatch.setattr(original_verification, "verify", outside_transaction)
    build = start(w, formats=["docx", "pdf"])
    result = compute(build)
    assert checked
    assert result["authoring_exact_verified"] == result["manifest"]["authoring_exact"]["digest"]
    assert result["snapshot_id"] == w["saved"]["snapshot_id"]
    word, pdf = result["outputs"]
    raw = storage.get(word["object_key"])
    assert word["digest"] == sha(raw) and word["byte_size"] == len(raw)
    with ZipFile(io.BytesIO(raw)) as archive:
        assert w["raw"]["replacement_text"] in archive.read("word/document.xml").decode()
    assert pdf == {"format": "pdf", "state": "failed", "gaps": ["RENDERER_UNAVAILABLE"]}
    publish(build, result)
    body = adoption_body(w, build)
    response = adopt(w, build, body)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["package"]["manifest"]["members"][0]["parse"]["status"] == "not_frozen"
    assert saved["package"]["review_ready"] is False
    with connection() as c:
        assert package_outputs.admitted(c, w["bid"], body["member"]["document_version_id"])
        profile = c.execute(
            "SELECT current_body_id,current_review_id FROM design.bid_profiles WHERE bid_id=%s",
            (w["bid"],),
        ).fetchone()
        assert str(profile["current_body_id"]) == w["member"].document_version_id
        assert profile["current_review_id"] is None
        edges = {
            str(row["parent_id"])
            for row in c.execute(
                "SELECT parent_id FROM retrieval.lineage_edges WHERE child_id=%s",
                (original_source_id(UUID(body["member"]["document_version_id"])),),
            ).fetchall()
        }
        assert edges == set(result["manifest"]["authoring_exact"]["direct_source_ids"])
    with connection(True) as c:
        assert exact_builds.available(c)
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'design.authoring_exact_revisions','SELECT') AS granted"
        ).fetchone()["granted"]
    assert observe(w, body)["state"] == "matched"
    view = w["client"].get(f"/api/v1/builds/{build['id']}")
    assert view.status_code == 200, view.text
    assert view.json()["identity"]["snapshot_id"] == w["saved"]["snapshot_id"]
    export_http(w, build, body, response, view)
    assert len(w["calls"]) == 1


@pytest.mark.parametrize("change", ["source", "facts", "rule"])
def test_changed_authority_after_compute_prevents_all_publication(adopted, change):
    build = start(adopted)
    result = compute(build)
    mutate_authority(adopted, change)
    with pytest.raises(DomainError):
        publish(build, result)
    unpublished(build)


@pytest.mark.parametrize("change", ["source", "closed"])
def test_old_build_ack_survives_authority_loss_but_new_use_is_rejected(adopted, change):
    build = start(adopted)
    mutate_authority(adopted, change)
    replayed = request_build(adopted, key=build["key"], body=build["body"])
    assert replayed.status_code == 202 and replayed.json() == build["ack"], replayed.text
    fresh = request_build(adopted)
    assert fresh.status_code == 409, fresh.text
    unpublished(build)


@pytest.mark.parametrize("missing", [False, True])
def test_original_bytes_must_still_exist_and_match_before_render(adopted, missing):
    build = start(adopted)
    key = adopted["blob"]["object_key"]
    if missing:
        storage.client().delete_object(Bucket=storage.bucket(), Key=key)
    else:
        storage.put(key, b"synthetic corrupted original", "application/pdf")
    with pytest.raises(DomainError) as error:
        compute(build)
    assert error.value.code == ("ORIGINAL_NOT_AVAILABLE" if missing else "ORIGINAL_BYTES_CORRUPTED")
    unpublished(build)


def test_adoption_rechecks_after_object_io_without_partial_package(adopted, monkeypatch):
    w = adopted
    build = start(w)
    publish(build, compute(build))
    body = adoption_body(w, build)
    verify = package_outputs.verify_bytes

    def during_io(packet):
        verify(packet)
        mutate_authority(w, "facts")

    monkeypatch.setattr(package_outputs, "verify_bytes", during_io)
    response = adopt(w, build, body)
    assert response.status_code == 409, response.text
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.audit_entries WHERE bid_id=%s AND event_type=%s",
            (w["bid"], package_outputs.EVENT),
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM design.bid_package_members WHERE bid_id=%s AND document_version_id=%s",
            (w["bid"], body["member"]["document_version_id"]),
        ).fetchone()


@pytest.mark.parametrize("change", ["source", "facts"])
def test_output_history_replays_but_new_admission_tracks_full_authority(
    adopted, monkeypatch, change
):
    w = adopted
    build = start(w)
    publish(build, compute(build))
    body, key = adoption_body(w, build), uuid4().hex
    accepted = adopt(w, build, body, key=key)
    assert accepted.status_code == 201, accepted.text
    assert observe(w, body)["state"] == "matched"
    mutate_authority(w, change)
    assert observe(w, body)["state"] == "blocked"
    history = f"/api/v1/bids/{w['bid']}/work-contexts/build/{build['id']}"
    for path in (history, history + "/relations?target=package_revision"):
        result = w["client"].get(path)
        assert result.status_code == 200, result.text
    with connection() as c, pytest.raises(DomainError):
        package_outputs.admitted(c, w["bid"], body["member"]["document_version_id"])
    monkeypatch.setattr(
        package_outputs, "verify_bytes", lambda *_: pytest.fail("historical ACK re-read objects")
    )
    replayed = adopt(w, build, body, key=key)
    assert replayed.status_code == 201 and replayed.json() == accepted.json(), replayed.text
    fresh = adopt(w, build, body)
    assert fresh.status_code == 409, fresh.text


def test_cas_followup_and_stripped_exact_binding_cannot_create_build(adopted):
    w = adopted
    stale = request_build(w, body=request_body(w, draft_revision=w["saved"]["draft_revision"] - 1))
    assert stale.status_code == 412 and stale.json()["code"] == "DRAFT_REVISION_CONFLICT"
    review = request_build(w, body=request_body(w, follow_up="review"))
    assert review.status_code == 422
    assert review.json()["code"] == "AUTHORING_EXACT_BUILD_FOLLOW_UP_UNSUPPORTED"
    build = start(w)
    forged = uuid4()
    with pytest.raises(psycopg.Error, match="AUTHORING_EXACT_BUILD_CHANGED"), connection() as c:
        c.execute(
            "INSERT INTO design.build_inputs(id,bid_id,draft_snapshot_id,template_digest,render_digest,manifest) "
            "SELECT %s,i.bid_id,i.draft_snapshot_id,i.template_digest,i.render_digest,i.manifest-'authoring_exact' "
            "FROM design.build_inputs i JOIN design.builds b ON b.input_id=i.id WHERE b.id=%s",
            (forged, build["id"]),
        )
    with connection() as c:
        assert not c.execute("SELECT 1 FROM design.build_inputs WHERE id=%s", (forged,)).fetchone()
    result = compute(build)
    result.pop("authoring_exact_verified")
    with pytest.raises(DomainError, match="原件核验"):
        publish(build, result)
    unpublished(build)


def test_missing_snapshot_read_privilege_blocks_new_build_but_keeps_original_ack(adopted):
    w = adopted
    build = start(w)
    owner = w["database"]["owner"]
    permission = "EXECUTE ON FUNCTION design.authoring_exact_snapshot_proof(uuid)"
    owner.execute("REVOKE " + permission + " FROM tender_api,tender_worker")
    try:
        capability = w["client"].get("/api/v1/authoring/exact-revision-capabilities")
        assert capability.status_code == 200 and capability.json()["build_available"] is False
        fresh = request_build(w)
        assert (
            fresh.status_code == 409
            and fresh.json()["code"] == "AUTHORING_EXACT_BUILD_NOT_CONFIGURED"
        )
        replayed = request_build(w, key=build["key"], body=build["body"])
        assert replayed.status_code == 202 and replayed.json() == build["ack"]
        with pytest.raises(DomainError) as error:
            compute(build)
        assert error.value.code == "AUTHORING_EXACT_BUILD_NOT_CONFIGURED"
        unpublished(build)
    finally:
        owner.execute("GRANT " + permission + " TO tender_api,tender_worker")


@pytest.mark.parametrize("exact", ["mixed"], indirect=True)
def test_mixed_snapshot_legacy_chapter_retains_guards_at_build_publish_and_adoption(adopted):
    w = adopted
    ready = start(w)
    publish(ready, compute(ready))
    body = adoption_body(w, ready)
    pending = start(w)
    result = compute(pending)
    assert len(result["manifest"]["authoring_exact"]["section_revisions"]) == 2
    add_new_parse(w)
    fresh = request_build(w)
    assert fresh.status_code == 409 and fresh.json()["code"] == "AUTHORING_SOURCE_STALE", fresh.text
    with pytest.raises(DomainError) as error:
        publish(pending, result)
    assert error.value.code == "AUTHORING_SOURCE_STALE"
    unpublished(pending)
    selected = adopt(w, ready, body)
    assert selected.status_code == 409 and selected.json()["code"] == "AUTHORING_SOURCE_STALE"
