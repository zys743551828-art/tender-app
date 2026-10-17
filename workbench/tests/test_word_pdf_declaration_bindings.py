"""Real nonowner API/Worker verification with explicit memory bytes; no Docker/provider."""

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from apps.api.auth import password_hash
from apps.api.main import app
from apps.api.views import upload_row
from packages.domain.runtime import Command, clean, connection, etag, fetch, sha, uid
from tests.test_slice_integration import pdf_bytes
from tests.test_word_intake import make_docx
from tests.test_word_mainflow_integration import commit, headers, pump, upload

pytest_plugins = ["tests.test_word_mainflow_integration"]
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_WORD_DECLARATION_BINDINGS") != "1",
    reason="Isolated reviewed nonowner Word/application DB only",
)


def fixture_uploads(w):
    prior = upload(w, pdf_bytes(), filename="prior.pdf")
    commit(w, prior)
    word = upload(w, make_docx("Synthetic declaration source " + uuid4().hex))
    pdf = upload(w, pdf_bytes(), filename="declared.pdf", source=word["version"])
    with connection() as c:
        file = fetch(c, "SELECT id,revision FROM document_files WHERE id=%s", (prior["file_id"],))
    return (
        word,
        pdf,
        {
            "kind": "new_version",
            "file_id": str(file["id"]),
            "expected_file_revision": file["revision"],
        },
    )


def get_upload(w, pdf):
    return w["client"].get(f"/api/v1/uploads/{pdf['upload_id']}")


def rebind(w, pdf, target):
    current = get_upload(w, pdf)
    return w["client"].post(
        f"/api/v1/uploads/{pdf['upload_id']}/bindings",
        json={"target": target, "reason": "显式恢复目标"},
        headers=headers(w, current.headers["etag"]),
    )


def validate_upload(response):
    schema = {"$ref": "#/components/schemas/UploadView", "components": app.openapi()["components"]}
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(response.json())
    old_ack = dict(response.json())
    old_ack.pop("word_pdf_declaration", None)
    validator.validate(old_ack)  # Immutable earlier ACK may predate this read projection.


def test_declared_rebind_cannot_target_existing_pdf(shared):
    w = shared
    word, pdf, target = fixture_uploads(w)
    result = rebind(w, pdf, target)
    observation = os.environ.get("WORD_DECLARATION_OBSERVATION_PATH")
    if observation:
        import apps.api.main as backend

        Path(observation).write_text(
            json.dumps(
                {
                    "status_code": result.status_code,
                    "error_code": result.json().get("code"),
                    "backend_main_path": backend.__file__,
                    "backend_main_sha256": hashlib.sha256(
                        Path(backend.__file__).read_bytes()
                    ).hexdigest(),
                    "scope": "Real nonowner HTTP bind after actual shared byte verification; explicit memory objects, no Docker/model",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    assert result.status_code == 409 and result.json()["code"] == "WORD_PDF_NEW_FILE_REQUIRED"
    with connection() as c:
        assert str(upload_row(c, UUID(pdf["upload_id"]))["current_binding_id"]) == pdf["binding"]
        relation = fetch(
            c,
            "SELECT source_document_version_id,verification,kind FROM document_relations WHERE document_version_id=%s",
            (pdf["version"],),
        )
        assert str(relation["source_document_version_id"]) == word["version"]
        assert (
            relation["kind"] == "user_declared_same_draft"
            and relation["verification"] == "unverified"
        )


def test_new_browser_reads_exact_declaration_and_regular_pdf_rebind_still_works(shared):
    w = shared
    word, pdf, target = fixture_uploads(w)
    login, password = uuid4().hex, uuid4().hex
    with connection() as c:
        c.execute(
            "INSERT INTO credentials(member_id,login_name,password_hash) VALUES(%s,%s,%s)",
            (w["actor"], login, password_hash(password)),
        )
    with TestClient(app) as second:
        logged = second.post(
            "/api/v1/auth/login",
            json={"login_name": login, "password": password},
            headers={"Origin": "http://word-intake.test"},
        )
        assert logged.status_code == 200
        actual = second.get(f"/api/v1/uploads/{pdf['upload_id']}")
        validate_upload(actual)
        assert actual.json()["word_pdf_declaration"] == {
            "source_document_version_id": word["version"],
            "role": "body",
            "required_target_kind": "new_file",
            "relation_kind": "user_declared_same_draft",
            "verification_status": "unverified",
        }
        denied = second.post(
            f"/api/v1/uploads/{pdf['upload_id']}/bindings",
            json={"target": target, "reason": "第二会话不得混旧PDF链"},
            headers={
                "Origin": "http://word-intake.test",
                "X-CSRF-Token": logged.json()["csrf_token"],
                "Idempotency-Key": uuid4().hex,
                "If-Match": actual.headers["etag"],
            },
        )
        assert denied.status_code == 409 and denied.json()["code"] == "WORD_PDF_NEW_FILE_REQUIRED"
    regular = upload(w, pdf_bytes(), filename="regular.pdf")
    assert get_upload(w, regular).json()["word_pdf_declaration"] is None
    assert rebind(w, regular, target).status_code == 200
    chosen = rebind(w, pdf, {"kind": "new_file"})
    assert chosen.status_code == 200
    pdf["binding"] = chosen.json()["id"]
    commit(w, pdf)
    with connection() as c:
        relation = fetch(
            c,
            "SELECT kind,verification FROM document_relations WHERE document_version_id=%s",
            (pdf["version"],),
        )
        assert relation == {"kind": "user_declared_same_draft", "verification": "unverified"}


def test_single_and_multipart_initial_targets_are_checked_before_creating_new_intent(
    shared, monkeypatch
):
    from packages.uploads import service
    from packages.uploads.protocol import PART_SIZE

    w = shared
    word, pdf, target = fixture_uploads(w)
    batch = (
        w["client"]
        .post(f"/api/v1/bids/{w['bid']}/upload-batches", json={}, headers=headers(w))
        .json()["id"]
    )
    native_calls = []

    class ExplicitMetadataNative:
        def initialize(self, key, media):
            native_calls.append((key, media))
            return "synthetic-native-session"

        def parts(self, key, identity):
            return []

    monkeypatch.setattr(service, "NativeMultipart", ExplicitMetadataNative)
    for size in (123, PART_SIZE + 17):
        body = {
            "batch_id": batch,
            "filename": "declaration.pdf",
            "role": "body",
            "byte_size": size,
            "declared_sha256": sha("metadata only"),
            "target": target,
            "declared_source_document_version_id": word["version"],
        }
        response = w["client"].post(
            f"/api/v1/bids/{w['bid']}/uploads", json=body, headers=headers(w)
        )
        assert (
            response.status_code == 409 and response.json()["code"] == "WORD_PDF_NEW_FILE_REQUIRED"
        )
    assert native_calls == []
    body = {
        "batch_id": batch,
        "filename": "declaration.pdf",
        "role": "body",
        "byte_size": PART_SIZE + 17,
        "declared_sha256": sha("metadata only"),
        "target": {"kind": "new_file"},
        "declared_source_document_version_id": word["version"],
    }
    allowed = w["client"].post(f"/api/v1/bids/{w['bid']}/uploads", json=body, headers=headers(w))
    assert (
        allowed.status_code == 200
        and allowed.json()["mode"] == "multipart"
        and len(native_calls) == 1
    )
    state = w["client"].get(f"/api/v1/uploads/{allowed.json()['upload_id']}")
    assert state.json()["word_pdf_declaration"]["source_document_version_id"] == word["version"]
    assert state.json()["document_version_id"] is None  # this is an intent, not verified PDF bytes
    wrong_role = body | {"role": "tender", "byte_size": 123}
    denied = w["client"].post(
        f"/api/v1/bids/{w['bid']}/uploads", json=wrong_role, headers=headers(w)
    )
    assert denied.status_code == 409 and denied.json()["code"] == "WORD_PDF_ROLE_MISMATCH"


def test_closed_batch_reuse_keeps_declaration_and_only_allows_independent_file(shared):
    w = shared
    word, pdf, target = fixture_uploads(w)
    path = f"/api/v1/bids/{w['bid']}/upload-batches/{pdf['batch_id']}/closure-state"
    closure = w["client"].get(path)
    assert (
        w["client"]
        .post(
            path.removesuffix("closure-state") + "close",
            json={"reason": "保留已核验PDF暂存"},
            headers=headers(w, closure.headers["etag"]),
        )
        .status_code
        == 200
    )
    batch = (
        w["client"]
        .post(f"/api/v1/bids/{w['bid']}/upload-batches", json={}, headers=headers(w))
        .json()["id"]
    )
    url = f"/api/v1/bids/{w['bid']}/upload-batches/{batch}/retained-uploads"
    current = get_upload(w, pdf)
    rejected = w["client"].post(
        url,
        json={
            "source_upload_id": pdf["upload_id"],
            "target": target,
            "reason": "不得改成既有PDF链",
        },
        headers=headers(w, current.headers["etag"]),
    )
    assert rejected.status_code == 409 and rejected.json()["code"] == "WORD_PDF_NEW_FILE_REQUIRED"
    h = headers(w, current.headers["etag"])
    body = {
        "source_upload_id": pdf["upload_id"],
        "target": {"kind": "new_file"},
        "reason": "显式独立PDF重选",
    }
    accepted = w["client"].post(url, json=body, headers=h)
    assert accepted.status_code == 201, (accepted.status_code, accepted.json().get("code"))
    validate_upload(accepted)
    replay = w["client"].post(url, json=body, headers=h)
    assert replay.status_code == 201 and replay.json() == accepted.json()
    assert accepted.json()["word_pdf_declaration"]["source_document_version_id"] == word["version"]
    with connection() as c:
        op = fetch(
            c,
            "SELECT o.id FROM operations o JOIN outbox x ON x.operation_id=o.id WHERE o.bid_id=%s AND x.payload->>'payload_ref'=%s",
            (w["bid"], accepted.json()["id"]),
        )
    pump(op["id"])
    verified = w["client"].get(f"/api/v1/uploads/{accepted.json()['id']}")
    assert verified.json()["state"] == "verified"
    assert verified.json()["word_pdf_declaration"] == accepted.json()["word_pdf_declaration"]
    import psycopg

    from apps.worker import engine
    from packages.domain.retained_uploads import verification_object_key
    from packages.domain.runtime import DomainError

    other_batch = (
        w["client"]
        .post(f"/api/v1/bids/{w['bid']}/upload-batches", json={}, headers=headers(w))
        .json()["id"]
    )
    second = w["client"].post(
        f"/api/v1/bids/{w['bid']}/upload-batches/{other_batch}/retained-uploads",
        json=body,
        headers=headers(w, current.headers["etag"]),
    )
    assert second.status_code == 201, (second.status_code, second.json().get("code"))
    with connection(True) as c:
        message = fetch(
            c,
            "SELECT x.payload FROM operations o JOIN outbox x ON x.operation_id=o.id WHERE o.bid_id=%s AND x.payload->>'payload_ref'=%s",
            (w["bid"], second.json()["id"]),
        )["payload"]
        pending = fetch(c, "SELECT * FROM uploads WHERE id=%s", (second.json()["id"],))
        first_pending = fetch(
            c, "SELECT staging_key FROM uploads WHERE id=%s", (accepted.json()["id"],)
        )
        assert pending["staging_key"] != first_pending["staging_key"]
        assert pending["staging_key"] not in w["objects"]  # no pretend object or new-key HEAD
        assert verification_object_key(c, message, pending) in w["objects"]
        for bad_message, bad_upload in [
            (message | {"bid_id": str(uuid4())}, pending),
            (message | {"operation_id": str(uuid4())}, pending),
            (message, pending | {"declared_digest": "f" * 64}),
            (message, pending | {"declared_size": pending["declared_size"] + 1}),
        ]:
            with pytest.raises(DomainError) as invalid:
                verification_object_key(c, bad_message, bad_upload)
            assert invalid.value.code == "RETAINED_SOURCE_INVALID"
    # The frozen audit itself is append-only: changing exact version, project or SHA is rejected.
    for field, value in [("source_document_version_id", str(uuid4())), ("sha256", "f" * 64)]:
        with pytest.raises(psycopg.Error):
            with connection() as c:
                c.execute(
                    "UPDATE audit_entries SET payload=jsonb_set(payload,ARRAY[%s],to_jsonb(%s::text)) WHERE event_type='upload.retained_bytes_reselected' AND payload->>'upload_id'=%s",
                    (field, value, second.json()["id"]),
                )
    with pytest.raises(psycopg.Error):
        with connection() as c:
            c.execute(
                "UPDATE audit_entries SET bid_id=%s WHERE event_type='upload.retained_bytes_reselected' AND payload->>'upload_id'=%s",
                (uuid4(), second.json()["id"]),
            )
    lease = engine.acquire(message)
    assert lease is not None
    result = engine.run_compute(message, lease)
    assert engine.finish(message, lease, result)
    assert w["client"].get(f"/api/v1/uploads/{second.json()['id']}").json()["state"] == "verified"


def test_pending_old_binding_receipt_replays_but_new_commit_requires_rebinding(shared):
    w = shared
    word, pdf, target = fixture_uploads(w)
    before = get_upload(w, pdf)
    body = {"target": target, "reason": "合成历史02可接受的旧链选择"}
    h = headers(w, before.headers["etag"])
    # Explicit legacy binding/immutable command fixture, after real shared Worker byte verification.
    # It grants no model/core/controlled-render success and does not rewrite a prior receipt.
    with connection() as c:
        c.execute("SELECT id FROM bids WHERE id=%s FOR UPDATE", (w["bid"],))
        old = upload_row(c, UUID(pdf["upload_id"]), True)
        command = Command(
            c,
            w["actor"],
            "rebind_upload",
            UUID(pdf["upload_id"]),
            h["Idempotency-Key"],
            body,
            h["If-Match"],
        )
        binding = uid()
        revision = old["revision"] + 1
        c.execute(
            "INSERT INTO upload_bindings(id,bid_id,upload_id,file_id,expected_file_revision,previous_binding_id,reason,command_id,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                binding,
                w["bid"],
                pdf["upload_id"],
                target["file_id"],
                target["expected_file_revision"],
                old["current_binding_id"],
                body["reason"],
                command.id,
                w["actor"],
            ),
        )
        c.execute(
            "UPDATE upload_transfers SET current_binding_id=%s,revision=%s WHERE upload_id=%s",
            (binding, revision, pdf["upload_id"]),
        )
        old_response = clean(
            {
                "id": binding,
                "upload_id": pdf["upload_id"],
                "bid_id": w["bid"],
                "file_id": target["file_id"],
                "expected_file_revision": target["expected_file_revision"],
                "previous_binding_id": old["current_binding_id"],
                "upload_revision": revision,
                "verified_retain_until": old["verified_retain_until"],
            }
        )
        command.finish(old_response, headers={"ETag": etag("upload", pdf["upload_id"], revision)})
    replay = w["client"].post(f"/api/v1/uploads/{pdf['upload_id']}/bindings", json=body, headers=h)
    assert (
        replay.status_code == 200
        and replay.headers["Idempotent-Replayed"] == "true"
        and replay.json() == old_response
    )
    commit_body = {
        "accepted_upload_ids": [pdf["upload_id"]],
        "accepted_binding_ids": [str(binding)],
        "explicit_partial_acceptance": False,
    }
    tag = w["client"].get(f"/api/v1/bids/{w['bid']}").headers["etag"]
    blocked = w["client"].post(
        f"/api/v1/bids/{w['bid']}/upload-batches/{pdf['batch_id']}/commit",
        json=commit_body,
        headers=headers(w, tag),
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "WORD_PDF_NEW_FILE_REQUIRED"
    chosen = rebind(w, pdf, {"kind": "new_file"})
    assert chosen.status_code == 200
    pdf["binding"] = chosen.json()["id"]
    commit(w, pdf)
    with connection() as c:
        assert (
            fetch(
                c,
                "SELECT verification FROM document_relations WHERE document_version_id=%s",
                (pdf["version"],),
            )["verification"]
            == "unverified"
        )


def pending_retained(w):
    word, pdf, _ = fixture_uploads(w)
    path = f"/api/v1/bids/{w['bid']}/upload-batches/{pdf['batch_id']}/closure-state"
    state = w["client"].get(path)
    assert (
        w["client"]
        .post(
            path.removesuffix("closure-state") + "close",
            json={"reason": "显式保留暂存"},
            headers=headers(w, state.headers["etag"]),
        )
        .status_code
        == 200
    )
    batch = (
        w["client"]
        .post(f"/api/v1/bids/{w['bid']}/upload-batches", json={}, headers=headers(w))
        .json()["id"]
    )
    current = get_upload(w, pdf)
    accepted = w["client"].post(
        f"/api/v1/bids/{w['bid']}/upload-batches/{batch}/retained-uploads",
        json={
            "source_upload_id": pdf["upload_id"],
            "target": {"kind": "new_file"},
            "reason": "受控保留原件复核",
        },
        headers=headers(w, current.headers["etag"]),
    )
    assert accepted.status_code == 201, (accepted.status_code, accepted.json().get("code"))
    with connection(True) as c:
        message = fetch(
            c,
            "SELECT x.payload FROM operations o JOIN outbox x ON x.operation_id=o.id WHERE o.bid_id=%s AND x.payload->>'payload_ref'=%s",
            (w["bid"], accepted.json()["id"]),
        )["payload"]
    from apps.worker import engine

    lease = engine.acquire(message)
    assert lease is not None
    computed = engine.run_compute(message, lease)
    return word, pdf, accepted.json(), message, lease, computed


@pytest.mark.parametrize("change", ["source_version", "expiry"])
def test_retained_source_is_revalidated_after_real_byte_io(shared, change):
    from apps.worker import engine
    from packages.domain.runtime import DomainError

    w = shared
    word, pdf, accepted, message, lease, computed = pending_retained(w)
    with connection(True) as c:
        if change == "source_version":
            c.execute(
                "UPDATE uploads SET verified_version_id=%s WHERE id=%s",
                (word["version"], pdf["upload_id"]),
            )
        else:
            c.execute(
                "UPDATE uploads SET verified_retain_until=clock_timestamp()-interval '1 second' WHERE id=%s",
                (pdf["upload_id"],),
            )
    with pytest.raises(DomainError) as rejected:
        engine.finish(message, lease, computed)
    assert rejected.value.code == "RETAINED_SOURCE_INVALID"
    assert engine.finish(message, lease, None, rejected.value)
    with connection(True) as c:
        assert (
            fetch(c, "SELECT verified_version_id FROM uploads WHERE id=%s", (accepted["id"],))[
                "verified_version_id"
            ]
            is None
        )
        assert fetch(
            c,
            "SELECT result FROM effect_receipts WHERE operation_id=%s",
            (message["operation_id"],),
        )["result"] == {"error_code": "RETAINED_SOURCE_INVALID", "result_ref": None}


@pytest.mark.parametrize("stop", ["cancel", "close_project"])
def test_retained_cancel_and_close_refuse_late_publication(shared, stop):
    from apps.worker import engine

    w = shared
    _, _, accepted, message, lease, computed = pending_retained(w)
    batch_path = f"/api/v1/bids/{w['bid']}/upload-batches/{accepted['batch_id']}/closure-state"
    current = w["client"].get(batch_path)
    blocked = w["client"].post(
        batch_path.removesuffix("closure-state") + "close",
        json={"reason": "不能暗结束正在核验的批次"},
        headers=headers(w, current.headers["etag"]),
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "BATCH_VERIFICATION_IN_FLIGHT"
    if stop == "cancel":
        operation = w["client"].get(f"/api/v1/operations/{message['operation_id']}")
        assert (
            w["client"]
            .post(
                f"/api/v1/operations/{message['operation_id']}/cancel",
                json={"reason": "明确取消本次复用核验", "cancel_pending_same_input": False},
                headers=headers(w, operation.headers["etag"]),
            )
            .status_code
            == 200
        )
        assert engine.finish(message, lease, computed) is False
    else:
        path = f"/api/v1/bids/{w['bid']}/lifecycle"
        current = w["client"].get(path)
        assert (
            w["client"]
            .post(
                path,
                json={"action": "terminate", "reason": "明确终止后拒晚到结果"},
                headers=headers(w, current.headers["etag"]),
            )
            .status_code
            == 200
        )
        assert engine.finish(message, lease, computed)
    with connection(True) as c:
        assert (
            fetch(c, "SELECT verified_version_id FROM uploads WHERE id=%s", (accepted["id"],))[
                "verified_version_id"
            ]
            is None
        )
        if stop == "cancel":
            assert (
                fetch(
                    c,
                    "SELECT count(*) AS n FROM effect_receipts WHERE operation_id=%s",
                    (message["operation_id"],),
                )["n"]
                == 0
            )
        else:
            assert fetch(
                c,
                "SELECT result FROM effect_receipts WHERE operation_id=%s",
                (message["operation_id"],),
            )["result"] == {"error_code": "PROJECT_WORK_CLOSED", "result_ref": None}
