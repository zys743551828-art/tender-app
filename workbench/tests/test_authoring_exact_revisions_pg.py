"""B3 uses native PG17/S3 and original B2 jobs; all domain/model content is synthetic."""
# ruff: noqa: F401,F811

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from authoring_package_input_fixtures import ADMIN_DSN, exact, world
from authoring_package_job_fixtures import (
    case,
    current,
    finish,
    input_database,
    queued,
)
from authoring_package_job_fixtures import (
    database as job_database,
)
from psycopg.types.json import Jsonb
from test_authoring_package_inputs_pg import add_new_parse, mutate_authority
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api, headers

from packages.authoring import exact_sources, package_proposals, repository
from packages.domain.runtime import ROOT, DomainError, connection, sha

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated B3 PG17 and real S3")


@pytest.fixture(scope="module")
def database(job_database):
    from apps.api.authoring_exact_revisions import router
    from apps.api.main import app

    with connection() as c:
        assert not exact_sources.available(c)
    job_database["owner"].execute(
        (ROOT / "packages/contracts/sql/authoring-exact-revisions.sql").read_text()
    )
    old = list(app.router.routes)
    if not any(
        getattr(route, "path", None) == "/api/v1/authoring/exact-revision-capabilities"
        for route in app.routes
    ):
        app.include_router(router)
    app.openapi_schema = None
    try:
        yield job_database
    finally:
        app.router.routes[:] = old
        app.openapi_schema = None


@pytest.fixture
def published(queued):
    w = queued
    result = finish(w)
    assert result["state"] == "succeeded", result
    w["action_ref"] = result["result"]["action_ref"]
    w["action_response"] = w["client"].get(w["action_ref"])
    assert w["action_response"].status_code == 200, w["action_response"].text
    w["action_id"] = w["action_response"].json()["action_id"]
    assert w["action_response"].json()["preview"]["apply_available"]
    w["adoption_key"] = uuid4().hex
    return w


def confirm(w, *, key=None, condition=None):
    return w["client"].post(
        w["action_ref"] + "/resolve",
        json={"decision": "confirm"},
        headers=headers(
            w, key=key or w["adoption_key"], etag=condition or w["action_response"].headers["etag"]
        ),
    )


def qualified(w):
    with connection() as c:
        row = c.execute(
            "SELECT * FROM design.authoring_exact_revisions WHERE action_id=%s", (w["action_id"],)
        ).fetchone()
        assert row is not None
        return row


def selected_adopted_input(w, response):
    from packages.contracts.authoring_input_catalog_api import NODES_PATH

    saved = response.json()["result"]["assistant_resolution"]["domain_result"]
    q = qualified(w)["manifest"]
    found = w["client"].get(
        NODES_PATH.format(
            bid_id=w["bid"], snapshot_id=saved["snapshot_id"], section_id=q["section_id"]
        ),
        params={
            "expected_snapshot_digest": saved["snapshot_digest"],
            "expected_section_digest": q["section_digest"],
        },
    )
    assert found.status_code == 200, found.text
    node_catalog = found.json()
    assert node_catalog["target"]["section_revision_id"] == q["section_revision_id"]
    assert node_catalog["section_content"] == response.json()["preview"]["after"]
    assert node_catalog["admission_granted"] is False
    selected_node = next(
        n
        for n in node_catalog["nodes"]
        if n["node_id"] == w["input_body"]["target_section"]["node_id"]
    )
    body = deepcopy(w["input_body"])
    body["target_section"] = {
        **node_catalog["target"],
        **{key: selected_node[key] for key in ("node_id", "before_node_digest")},
    }
    return body


def unmodified(w):
    with connection() as c:
        assert (
            c.execute(
                "SELECT revision FROM design.drafts WHERE id=%s",
                (w["input_body"]["target_section"]["draft_id"],),
            ).fetchone()["revision"]
            == 1
        )
        assert not c.execute(
            "SELECT 1 FROM design.authoring_exact_revisions WHERE bid_id=%s", (w["bid"],)
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM design.action_consumptions WHERE action_id=%s", (w["action_id"],)
        ).fetchone()


def export_adoption(w, response):
    directory = os.environ.get("FUSION_AUTHORING_EXACT_FIXTURE_DIR")
    if not directory:
        return

    def read(path):
        value = w["client"].get(path)
        assert value.status_code == 200, value.text
        return value.json()

    saved = response.json()["result"]["assistant_resolution"]["domain_result"]
    q = qualified(w)
    base = f"/api/v1/bids/{w['bid']}"
    bid_response = w["client"].get(base)
    assert bid_response.status_code == 200, bid_response.text
    input_path = w["input_base"] + "/" + w["fixed"]["manifest"]["id"]
    value = {
        "fixture_kind": "synthetic originals and model HTTP; unchanged native PG17/S3/API responses",
        "member_id": w["actor"],
        "bid_id": w["bid"],
        "bid": bid_response.json(),
        "bid_etag": bid_response.headers["etag"],
        "input": read(input_path),
        "context": read(input_path + "/context"),
        "capabilities": read("/api/v1/authoring/exact-revision-capabilities"),
        "before_action": w["action_response"].json(),
        "before_etag": w["action_response"].headers["etag"],
        "resolve_request": {"decision": "confirm"},
        "resolve_ack": response.json(),
        "resolve_etag": response.headers["etag"],
        "snapshot": read(base + "/draft-snapshots/" + saved["snapshot_id"]),
        "work_context": read(base + "/work-contexts/draft_snapshot/" + saved["snapshot_id"]),
        "draft_status": read(
            base + "/authoring/drafts/" + saved["draft_id"] + "/exact-qualification"
        ),
        "qualification": read(
            base
            + "/authoring/section-revisions/"
            + str(q["section_revision_id"])
            + "/exact-qualification"
        ),
    }
    (Path(directory) / "adopted.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )


def test_real_published_action_adopts_exact_revision_once_and_original_ack_replays(published):
    w = published
    result = confirm(w)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["state"] == "executed"
    saved = value["result"]["assistant_resolution"]["domain_result"]
    assert saved["draft_revision"] == 2
    q = qualified(w)
    assert q["manifest"]["source_scope"] == "exact_package_context"
    with connection() as c:
        snapshot = repository.snapshot_content(c, UUID(w["bid"]), UUID(saved["snapshot_id"]))
        assert snapshot["sections"][0] == value["preview"]["after"]
        assert (
            snapshot["authoring_exact_sections"]["sections"][0]["qualification_digest"]
            == q["digest"]
        )
        exact_sources.assert_current(c, UUID(w["bid"]), q["section_revision_id"])
    repeated = confirm(w)
    assert repeated.status_code == 200 and repeated.json() == value, repeated.text
    another = confirm(w, key=uuid4().hex)
    assert another.status_code == 200 and another.json() == value, another.text
    assert len(w["calls"]) == 1
    export_adoption(w, result)


def test_newer_parse_never_replaces_selected_old_parse_during_adoption(published, monkeypatch):
    w = published
    add_new_parse(w)

    def forbidden(*args, **kwargs):
        raise AssertionError("exact adoption used legacy latest source authority")

    monkeypatch.setattr(repository, "assert_sources", forbidden)
    result = confirm(w)
    assert result.status_code == 200, result.text
    q = qualified(w)
    with connection() as c:
        exact_sources.assert_current(c, UUID(w["bid"]), q["section_revision_id"])
    assert len(w["calls"]) == 1


def test_exact_snapshot_history_and_new_input_preserve_all_original_bindings(published):
    from authoring_package_input_fixtures import save

    from packages.work_contexts import authoring_repository

    w = published
    response = confirm(w)
    assert response.status_code == 200, response.text
    saved = response.json()["result"]["assistant_resolution"]["domain_result"]
    context = w["client"].get(
        f"/api/v1/bids/{w['bid']}/work-contexts/draft_snapshot/{saved['snapshot_id']}"
    )
    assert context.status_code == 200, context.text
    value = context.json()
    assert value["selection"]["snapshot_digest"] == saved["snapshot_digest"]
    assert value["document"]["sections"][0]["content"] == response.json()["preview"]["after"]
    assert value["document"]["editable"] is False
    assert value["qualification_assessed"] is False
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        history = authoring_repository.snapshot(c, w["bid"], saved["snapshot_id"])
        assert (
            history["native"]["authoring_exact_sections"]["sections"][0]["qualification_digest"]
            == qualified(w)["digest"]
        )
    body = selected_adopted_input(w, response)
    captured = save(w, body=body)
    assert captured.status_code == 201, captured.text
    assert captured.json()["manifest"]["selection"] == body
    with connection() as c:
        original = c.execute(
            "SELECT manifest FROM design.draft_snapshots WHERE id=%s", (saved["snapshot_id"],)
        ).fetchone()["manifest"]
        frozen = json.loads(
            c.execute(
                "SELECT context_text FROM design.authoring_package_inputs WHERE id=%s",
                (captured.json()["manifest"]["id"],),
            ).fetchone()["context_text"]
        )
    assert original["authoring_exact_sections"]["sections"][0]["qualification_digest"]
    assert frozen["target"]["snapshot_manifest"] == original


def test_next_exact_candidate_derives_new_qualification_from_actual_parent(published, monkeypatch):
    w = published
    first = confirm(w)
    assert first.status_code == 200, first.text
    original_qualification = qualified(w)
    next_case = {**w, "input_body": selected_adopted_input(w, first)}
    next_case = case.__wrapped__(next_case, monkeypatch)
    next_case["raw"]["replacement_text"] = "Explicit synthetic second candidate with new wording."
    next_case = queued.__wrapped__(next_case)
    # Use the same native publication path; no synthetic action or copied proof.
    result = finish(next_case)
    assert result["state"] == "succeeded", result
    next_case["action_ref"] = result["result"]["action_ref"]
    next_case["action_response"] = next_case["client"].get(next_case["action_ref"])
    assert next_case["action_response"].status_code == 200
    next_case["action_id"] = next_case["action_response"].json()["action_id"]
    next_case["adoption_key"] = uuid4().hex
    second = confirm(next_case)
    assert second.status_code == 200, second.text
    derived = qualified(next_case)
    assert derived["manifest"]["draft_revision"] == 3
    assert derived["manifest"]["section_revision"] == 3
    assert derived["parent_revision_id"] == original_qualification["section_revision_id"]
    assert derived["input_id"] != original_qualification["input_id"]
    assert derived["action_id"] != original_qualification["action_id"]
    assert confirm(w).json() == first.json()
    with connection() as c:
        exact_sources.assert_current(
            c, UUID(w["bid"]), original_qualification["section_revision_id"]
        )
        exact_sources.assert_current(c, UUID(w["bid"]), derived["section_revision_id"])
        status = exact_sources.draft_status(c, UUID(w["bid"]), derived["draft_id"])
    assert status["draft_revision"] == 3
    assert status["exact_sections"][0]["qualification_digest"] == derived["digest"]


@pytest.mark.parametrize("change", ["source", "facts", "rule", "closed"])
def test_changed_authority_rejects_adoption_without_consumption_or_partial_revision(
    published, change
):
    w = published
    mutate_authority(w, change)
    result = confirm(w)
    assert result.status_code == 409, result.text
    unmodified(w)


def test_shared_save_and_append_keep_their_cas_guards(published, monkeypatch):
    calls = []
    save, append = repository.save_draft, repository.append_section

    def shared_save(*args, **kwargs):
        calls.append("save")
        assert isinstance(kwargs.get("exact_admission"), exact_sources.ExactAdoption)
        return save(*args, **kwargs)

    def shared_append(*args, **kwargs):
        calls.append("append")
        assert isinstance(kwargs.get("exact_admission"), exact_sources.ExactAdoption)
        return append(*args, **kwargs)

    monkeypatch.setattr(repository, "save_draft", shared_save)
    monkeypatch.setattr(repository, "append_section", shared_append)
    response = confirm(published)
    assert response.status_code == 200, response.text
    assert calls == ["save", "append"]


def test_qualification_failure_rolls_back_inserted_revision_and_consumption(published, monkeypatch):
    def fail_after_revision(c, manifest, *args):
        assert c.execute(
            "SELECT 1 FROM design.section_revisions WHERE id=%s",
            (manifest["section_revision_id"],),
        ).fetchone()
        raise DomainError(
            "AUTHORING_EXACT_SYNTHETIC_FAILURE", "injected qualification failure", 409
        )

    monkeypatch.setattr(exact_sources, "insert", fail_after_revision)
    response = confirm(published)
    assert (
        response.status_code == 409
        and response.json()["code"] == "AUTHORING_EXACT_SYNTHETIC_FAILURE"
    )
    unmodified(published)
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.section_revisions WHERE bid_id=%s",
                (published["bid"],),
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_confirmations_have_one_global_consumption(published, same_key):
    keys = [published["adoption_key"], published["adoption_key"] if same_key else uuid4().hex]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda key: confirm(published, key=key), keys))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert results[0].json() == results[1].json()
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.authoring_exact_revisions WHERE action_id=%s",
                (published["action_id"],),
            ).fetchone()["n"]
            == 1
        )
    assert len(published["calls"]) == 1


def test_original_adoption_receipt_recovers_after_source_and_original_loss(published):
    from authoring_package_input_fixtures import save
    from authoring_package_job_fixtures import launch

    from packages.domain import storage

    w = published
    response = confirm(w)
    assert response.status_code == 200, response.text
    original = response.json()
    next_input = selected_adopted_input(w, response)
    saved = original["result"]["assistant_resolution"]["domain_result"]
    mutate_authority(w, "source")
    storage.client().delete_object(Bucket=storage.bucket(), Key=w["blob"]["object_key"])
    repeated = confirm(w)
    assert repeated.status_code == 200 and repeated.json() == original, repeated.text
    assert repeated.headers["Idempotent-Replayed"] == "true"
    # The earlier generation ACK stays queued even though the candidate is now adopted.
    generation_ack = launch(w, key=w["key"])
    assert generation_ack.status_code == 202 and generation_ack.json() == w["task"]
    history = w["client"].get(
        f"/api/v1/bids/{w['bid']}/work-contexts/draft_snapshot/{saved['snapshot_id']}"
    )
    assert history.status_code == 200, history.text
    assert history.json()["document"]["sections"][0]["content"] == original["preview"]["after"]
    assert history.json()["current_observation"]["sources"]["status"] == "changed"
    new_capture = save(w, body=next_input)
    assert new_capture.status_code == 409, new_capture.text
    with connection() as c:
        q = qualified(w)
        with pytest.raises(DomainError) as failure:
            exact_sources.assert_current(c, UUID(w["bid"]), q["section_revision_id"])
        assert failure.value.code == "AUTHORING_PACKAGE_SOURCE_CHANGED"


def test_changed_confirmation_key_binding_does_not_replay_another_request(published):
    response = confirm(published)
    assert response.status_code == 200, response.text
    changed = confirm(published, condition='"another-action-precondition"')
    assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert qualified(published)["manifest"]["section_revision"] == 2


def test_missing_original_rejects_new_adoption_without_partial_effect(published):
    from packages.domain import storage

    storage.client().delete_object(Bucket=storage.bucket(), Key=published["blob"]["object_key"])
    response = confirm(published)
    assert response.status_code == 409 and response.json()["code"] == "ORIGINAL_NOT_AVAILABLE"
    unmodified(published)


@pytest.mark.parametrize("change", ["source", "facts", "rule", "closed"])
def test_changes_during_original_io_cannot_cross_final_save_fence(published, monkeypatch, change):
    from packages.domain import original_verification

    original_verify = original_verification.verify
    observed = []

    def during_io(document):
        original_verify(document)
        if not observed:
            observed.append(True)
            mutate_authority(published, change)

    monkeypatch.setattr(original_verification, "verify", during_io)
    response = confirm(published)
    assert observed and response.status_code == 409, response.text
    unmodified(published)


def test_fact_purpose_withdrawal_invalidates_new_adoption(published):
    w = published
    declaration = w["fixed"]["manifest"]["fact_declarations"][0]
    response = w["client"].post(
        w["input_base"] + "/" + w["fixed"]["manifest"]["id"] + "/fact-withdrawals",
        json={
            "input_digest": w["fixed"]["digest"],
            "fact_id": declaration["manifest"]["fact_id"],
            "declaration_digest": declaration["digest"],
            "reason": "Explicit synthetic purpose withdrawal before adoption",
        },
        headers=headers(w),
    )
    assert response.status_code == 201, response.text
    response = confirm(w)
    assert (
        response.status_code == 409
        and response.json()["code"] == "AUTHORING_PACKAGE_FACT_DECLARATION_WITHDRAWN"
    )
    unmodified(w)


def test_target_change_before_confirmation_preserves_manual_revision(published):
    w = published
    selected = w["input_body"]["target_section"]
    content = deepcopy(w["action_response"].json()["preview"]["before"])
    content["content"][0]["content"] = [
        {"type": "text", "text": "synthetic manual edit before confirm"}
    ]
    changed = w["client"].patch(
        f"/api/v1/bids/{w['bid']}/drafts/{selected['draft_id']}",
        json={
            "base_draft_revision": 1,
            "changes": [
                {
                    "section_id": selected["section_id"],
                    "base_section_revision": 1,
                    "schema_digest": selected["schema_digest"],
                    "content": content,
                }
            ],
        },
        headers=headers(w, etag=repository.draft_etag(selected["draft_id"], 1)),
    )
    assert changed.status_code == 200, changed.text
    response = confirm(w)
    assert response.status_code == 409, response.text
    section = w["client"].get("/api/v1/sections/" + selected["section_id"])
    assert section.status_code == 200 and section.json()["content"] == content
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.action_consumptions WHERE action_id=%s", (w["action_id"],)
        ).fetchone()


def test_legacy_apply_cannot_consume_exact_candidate(published):
    w = published
    selected = w["input_body"]["target_section"]
    response = w["client"].post(
        f"/api/v1/bids/{w['bid']}/authoring-actions/{w['action_id']}/apply",
        json={},
        headers=headers(w, etag=repository.draft_etag(selected["draft_id"], 1)),
    )
    assert response.status_code == 409 and response.json()["code"] == "ACTION_KIND_INVALID"
    unmodified(w)


@pytest.mark.parametrize("operation", ["save", "restore", "add_section"])
def test_adopted_exact_revision_cannot_be_downgraded_by_ordinary_routes(published, operation):
    w = published
    response = confirm(w)
    assert response.status_code == 200, response.text
    selected = w["input_body"]["target_section"]
    tag = repository.draft_etag(selected["draft_id"], 2)
    if operation == "save":
        content = deepcopy(response.json()["preview"]["after"])
        content["attrs"]["source_refs"] = []
        changed = w["client"].patch(
            f"/api/v1/bids/{w['bid']}/drafts/{selected['draft_id']}",
            json={
                "base_draft_revision": 2,
                "changes": [
                    {
                        "section_id": selected["section_id"],
                        "base_section_revision": 2,
                        "schema_digest": selected["schema_digest"],
                        "content": content,
                    }
                ],
            },
            headers=headers(w, etag=tag),
        )
    elif operation == "restore":
        changed = w["client"].post(
            f"/api/v1/bids/{w['bid']}/sections/{selected['section_id']}/restore",
            json={"revision": 1, "base_draft_revision": 2, "base_section_revision": 2},
            headers=headers(w, etag=tag),
        )
    else:
        changed = w["client"].post(
            f"/api/v1/bids/{w['bid']}/drafts/{selected['draft_id']}/sections",
            json={"title": "synthetic new section"},
            headers=headers(w, etag=tag),
        )
    assert (
        changed.status_code == 409
        and changed.json()["code"] == "AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED"
    ), changed.text
    assert qualified(w)["manifest"]["section_revision"] == 2


def test_database_cannot_mark_candidate_executed_without_revision_qualification(published):
    from packages.domain.runtime import Command

    w = published
    with pytest.raises(
        psycopg.errors.CheckViolation, match="AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED"
    ):
        with connection() as c:
            command = Command(
                c,
                UUID(w["actor"]),
                package_proposals.KIND,
                UUID(w["action_id"]),
                uuid4().hex,
                {"decision": "confirm"},
                w["action_response"].headers["etag"],
            )
            c.execute(
                "INSERT INTO design.action_consumptions(action_id,command_id,consumed_by,result) VALUES(%s,%s,%s,%s)",
                (
                    w["action_id"],
                    command.id,
                    w["actor"],
                    Jsonb({"assistant_resolution": {"state": "executed"}}),
                ),
            )
            command.finish({"synthetic": "not an adoption"})
    unmodified(w)


def test_database_rejects_unqualified_revision_even_when_sources_are_stripped(published):
    w = published
    result = confirm(w)
    assert result.status_code == 200, result.text
    q = qualified(w)
    with pytest.raises(
        psycopg.errors.CheckViolation, match="AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED"
    ):
        with connection() as c:
            content = deepcopy(result.json()["preview"]["after"])
            content["attrs"]["source_refs"] = []
            c.execute(
                "INSERT INTO design.section_revisions(id,bid_id,draft_id,section_id,revision,schema_digest,content,digest,created_by) VALUES(%s,%s,%s,%s,3,%s,%s,%s,%s)",
                (
                    uuid4(),
                    w["bid"],
                    q["draft_id"],
                    q["section_id"],
                    q["manifest"]["schema_digest"],
                    Jsonb(content),
                    sha(content),
                    w["actor"],
                ),
            )
    assert qualified(w)["manifest"]["section_revision"] == 2


def test_typed_admission_cannot_authorize_arbitrary_content_or_command(published):
    from packages.domain.runtime import Command

    w = published
    before = w["action_response"].json()
    selected = w["input_body"]["target_section"]
    with pytest.raises(DomainError) as rejected:
        with connection() as c:
            command = Command(
                c,
                UUID(w["actor"]),
                package_proposals.KIND,
                UUID(w["action_id"]),
                uuid4().hex,
                {"decision": "confirm"},
                w["action_response"].headers["etag"],
            )
            admission = exact_sources.ExactAdoption(
                UUID(w["action_id"]),
                command.id,
                UUID(w["actor"]),
                w["action_response"].headers["etag"],
                before,
            )
            forged = deepcopy(before["preview"]["after"])
            forged["attrs"]["source_refs"] = []
            repository.save_draft(
                c,
                UUID(w["bid"]),
                UUID(selected["draft_id"]),
                UUID(w["actor"]),
                {
                    "base_draft_revision": 1,
                    "changes": [
                        {
                            "section_id": selected["section_id"],
                            "base_section_revision": 1,
                            "schema_digest": selected["schema_digest"],
                            "content": forged,
                        }
                    ],
                },
                repository.draft_etag(selected["draft_id"], 1),
                exact_admission=admission,
            )
    assert rejected.value.code == "AUTHORING_EXACT_ADMISSION_INVALID"
    unmodified(w)


def test_final_authorization_cannot_switch_actor_after_original_io(published):
    w = published
    with pytest.raises(DomainError) as rejected:
        package_proposals.resolve(
            UUID(w["actor"]),
            UUID(w["action_id"]),
            w["adoption_key"],
            w["action_response"].headers["etag"],
            final_auth=lambda: uuid4(),
        )
    assert rejected.value.code == "AUTHORING_EXACT_ACTOR_CHANGED"
    unmodified(w)


def test_expired_actual_candidate_is_not_consumed(queued, monkeypatch):
    from datetime import timedelta

    from packages.authoring import package_publication

    w = queued
    monkeypatch.setattr(package_publication, "timedelta", lambda **_: timedelta(seconds=-1))
    current_run = finish(w)
    assert current_run["state"] == "succeeded", current_run
    w["action_ref"] = current_run["result"]["action_ref"]
    w["action_response"] = w["client"].get(w["action_ref"])
    w["action_id"] = w["action_response"].json()["action_id"]
    w["adoption_key"] = uuid4().hex
    response = confirm(w)
    assert response.status_code == 409 and response.json()["code"] == "ACTION_EXPIRED", (
        response.text
    )
    unmodified(w)


def test_rejected_candidate_returns_actual_rejection_when_confirmed_later(published):
    w = published
    rejected = w["client"].post(
        w["action_ref"] + "/resolve",
        json={"decision": "reject"},
        headers=headers(w, etag=w["action_response"].headers["etag"]),
    )
    assert rejected.status_code == 200 and rejected.json()["state"] == "rejected", rejected.text
    later = confirm(w)
    assert later.status_code == 200 and later.json() == rejected.json(), later.text
    assert later.json()["result"]["assistant_resolution"]["business_effect_executed"] is False
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.authoring_exact_revisions WHERE action_id=%s", (w["action_id"],)
        ).fetchone()


def test_completed_confirmation_ack_is_immutable(published):
    w = published
    response = confirm(w)
    assert response.status_code == 200, response.text
    with pytest.raises(psycopg.Error, match="AUTHORING_EXACT_COMMAND_IMMUTABLE"):
        with connection() as c:
            c.execute(
                "UPDATE design.commands SET response=jsonb_set(response,'{body,state}','\"pending\"'::jsonb) WHERE command_kind=%s AND actor_id=%s AND target_id=%s AND idempotency_key=%s",
                (package_proposals.KIND, w["actor"], w["action_id"], w["adoption_key"]),
            )
    repeated = confirm(w)
    assert repeated.status_code == 200 and repeated.json() == response.json()


def test_snapshot_cannot_drop_actual_exact_revision_binding(published):
    w = published
    response = confirm(w)
    assert response.status_code == 200, response.text
    q = qualified(w)
    new_snapshot = uuid4()
    with pytest.raises(psycopg.errors.CheckViolation, match="AUTHORING_EXACT_SNAPSHOT_CORRUPT"):
        with connection() as c:
            original = c.execute(
                "SELECT manifest FROM design.draft_snapshots WHERE draft_id=%s AND revision=2",
                (q["draft_id"],),
            ).fetchone()["manifest"]
            original.pop("authoring_exact_sections")
            original["revision"] = 3
            c.execute(
                "INSERT INTO design.draft_snapshots(id,bid_id,draft_id,revision,manifest,digest) VALUES(%s,%s,%s,3,%s,%s)",
                (new_snapshot, w["bid"], q["draft_id"], Jsonb(original), sha(original)),
            )
            c.execute(
                "INSERT INTO design.draft_snapshot_sections(snapshot_id,bid_id,draft_id,section_revision_id,ordinal) VALUES(%s,%s,%s,%s,0)",
                (new_snapshot, w["bid"], q["draft_id"], q["section_revision_id"]),
            )
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.draft_snapshots WHERE id=%s", (new_snapshot,)
        ).fetchone()


def test_exact_qualification_privileges_are_narrow_nonowner_roles(published):
    from psycopg.rows import dict_row

    for role in ("api", "worker"):
        with psycopg.connect(published["database"][role + "_dsn"], row_factory=dict_row) as c:
            assert exact_sources.available(c)
            assert exact_sources.apply_available(c) is (role == "api")
            flags = c.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert flags == {"rolsuper": False, "rolbypassrls": False}
            privileges = c.execute(
                "SELECT has_table_privilege(current_user,'design.authoring_exact_revisions','SELECT') AS read,"
                "has_table_privilege(current_user,'design.authoring_exact_revisions','INSERT') AS append,"
                "has_table_privilege(current_user,'design.authoring_exact_revisions','UPDATE') AS change,"
                "has_table_privilege(current_user,'design.authoring_exact_revisions','DELETE') AS remove,"
                "has_function_privilege(current_user,'design.authoring_exact_assert_dependencies(uuid)','EXECUTE') AS unbound_check,"
                "has_function_privilege(current_user,'design.authoring_exact_snapshot_proof(uuid)','EXECUTE') AS bound_read"
            ).fetchone()
            assert privileges == {
                "read": role == "api",
                "append": role == "api",
                "change": False,
                "remove": False,
                "unbound_check": False,
                "bound_read": True,
            }


@pytest.mark.parametrize(
    "permission",
    [
        "SELECT ON design.authoring_exact_revisions",
        "INSERT ON design.authoring_exact_revisions",
        "EXECUTE ON FUNCTION design.authoring_exact_check_revision(uuid)",
        "EXECUTE ON FUNCTION design.authoring_exact_assert_revision(uuid)",
        "EXECUTE ON FUNCTION design.authoring_exact_snapshot_proof(uuid)",
        "EXECUTE ON FUNCTION design.authoring_package_assert_job(uuid)",
    ],
)
def test_missing_api_adoption_privilege_is_unavailable_before_original_io(
    published, monkeypatch, permission
):
    from packages.domain import original_verification

    w = published
    monkeypatch.setattr(
        original_verification,
        "verify",
        lambda *_: pytest.fail("unavailable adoption attempted original I/O"),
    )
    owner = w["database"]["owner"]
    owner.execute("REVOKE " + permission + " FROM tender_api")
    try:
        capability = w["client"].get("/api/v1/authoring/exact-revision-capabilities")
        assert capability.status_code == 200, capability.text
        assert capability.json()["apply_available"] is False
        action = w["client"].get(w["action_ref"])
        assert action.status_code == 200 and action.json()["preview"]["apply_available"] is False
        response = confirm(w)
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "AUTHORING_PACKAGE_APPLY_NOT_CONFIGURED"
    finally:
        owner.execute("GRANT " + permission + " TO tender_api")
    unmodified(w)


def test_revoked_adoption_insert_preserves_original_ack_and_worker_historical_read(published):
    w = published
    adopted = confirm(w)
    assert adopted.status_code == 200, adopted.text
    saved = adopted.json()["result"]["assistant_resolution"]["domain_result"]
    owner = w["database"]["owner"]
    owner.execute("REVOKE INSERT ON design.authoring_exact_revisions FROM tender_api")
    try:
        capability = w["client"].get("/api/v1/authoring/exact-revision-capabilities")
        assert capability.status_code == 200 and capability.json()["apply_available"] is False
        replayed = confirm(w)
        assert replayed.status_code == 200 and replayed.json() == adopted.json(), replayed.text
        assert replayed.headers["Idempotent-Replayed"] == "true"
        with connection(True) as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            historical = repository.snapshot_content(c, UUID(w["bid"]), UUID(saved["snapshot_id"]))
            assert historical["authoring_exact_sections"]["sections"][0][
                "section_revision_id"
            ] == str(qualified(w)["section_revision_id"])
    finally:
        owner.execute("GRANT INSERT ON design.authoring_exact_revisions TO tender_api")
