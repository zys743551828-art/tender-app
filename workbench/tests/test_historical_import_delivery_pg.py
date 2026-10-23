"""Real non-owner imports: discoverable history, exact source and original ACK replay."""

# ruff: noqa: F401,F811

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from test_bid_package_requirements_api import database
from test_research_integration import client, seed
from test_research_integration import (
    test_historical_import_dry_run_exceptions_confirmation_and_same_bytes_reuse as legacy_import,
)

from packages.domain import storage
from packages.domain.runtime import DomainError, connection, sha
from packages.research import import_history, import_originals
from packages.research.import_contracts import HistoricalImportRequest

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires an explicitly isolated non-owner PG17 import test database",
)


@pytest.fixture(autouse=True)
def ready_database(database):
    yield


def request_for(actor, *, key="historical-input"):
    item = seed(actor)
    return {
        "records": [
            {
                "external_record_id": key,
                "bid_id": item["bid"],
                "actual_document_version_id": item["body"],
                "submitted_at": "2024-02-02T00:00:00Z",
                "evidence_ref": item["source"],
                "explanation": "合成事后实际提交记录，不宣称平台接受或事前闸门通过",
                "score_kind": "unknown",
                "value": None,
                "maximum": None,
                "source_version_id": None,
                "known_at": None,
            }
        ]
    }


def test_directory_exact_source_and_audited_creation_remain_available(client):
    web, actor, headers, _ = client
    body = request_for(actor)
    first = web.post("/api/v1/research/import-previews", json=body, headers=headers())
    assert first.status_code == 201, first.text
    value = first.json()
    page = web.get("/api/v1/research/imports", params={"mode": "dry_run", "limit": 1})
    assert page.status_code == 200, page.text
    entry = page.json()["items"][0]
    assert entry["id"] == value["id"] and entry["created_by"] == str(actor)
    assert entry["created_at"] is not None and entry["counts"] == value["counts"]
    source = web.get(f"/api/v1/research/imports/{value['id']}/source")
    assert source.status_code == 200, source.text
    assert source.json()["request"] == HistoricalImportRequest.model_validate(body).model_dump(
        mode="json"
    )
    assert source.json()["manifest_blob_id"] == value["manifest_blob_id"]
    assert source.headers["Cache-Control"] == "private, no-store"
    assert value["command"]["request_digest"] == sha(
        {"body": source.json()["request"], "if_match": None}
    )
    with connection() as c:
        event = c.execute(
            "SELECT created_at FROM audit_entries WHERE event_type='historical_import.preview_created' AND payload->>'batch_id'=%s",
            (value["id"],),
        ).fetchone()
        assert entry["created_at"] == event["created_at"].isoformat()


def test_preview_original_ack_survives_storage_failure_but_changed_input_is_rejected(
    client, monkeypatch
):
    web, actor, headers, _ = client
    body, original_headers = request_for(actor), headers()
    first = web.post("/api/v1/research/import-previews", json=body, headers=original_headers)
    assert first.status_code == 201, first.text
    monkeypatch.setattr(
        storage, "put", lambda *_args: pytest.fail("Committed replay wrote an object")
    )
    replay = web.post("/api/v1/research/import-previews", json=body, headers=original_headers)
    assert replay.status_code == 201 and replay.json() == first.json(), replay.text
    assert replay.headers["Idempotent-Replayed"] == "true"
    changed = {"records": [body["records"][0] | {"explanation": "不能复用原键的另一份说明"}]}
    conflict = web.post("/api/v1/research/import-previews", json=changed, headers=original_headers)
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_confirm_original_ack_survives_missing_manifest_and_does_not_duplicate_submission(
    client, monkeypatch
):
    web, actor, headers, _ = client
    body = request_for(actor)
    preview = web.post("/api/v1/research/import-previews", json=body, headers=headers())
    assert preview.status_code == 201, preview.text
    path = f"/api/v1/research/imports/{preview.json()['id']}/confirm"
    original_headers = headers(preview.headers["ETag"])
    first = web.post(path, json={}, headers=original_headers)
    assert first.status_code == 200, first.text
    assert first.json()["counts"]["imported"] == 1
    assert first.json()["standard_submission_gate_checked"] is False
    assert first.json()["command"]["command_kind"] == import_history.CONFIRM_KIND
    monkeypatch.setattr(
        storage, "get", lambda *_args: pytest.fail("Committed confirm reread an object")
    )
    replay = web.post(path, json={}, headers=original_headers)
    assert replay.status_code == 200 and replay.json() == first.json(), replay.text
    assert replay.headers["Idempotent-Replayed"] == "true"
    conflict = web.post(path, json={}, headers=original_headers | {"If-Match": '"different"'})
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM submission_records WHERE bid_id=%s",
                (body["records"][0]["bid_id"],),
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM outcomes WHERE bid_id=%s",
                (body["records"][0]["bid_id"],),
            ).fetchone()["n"]
            == 0
        )


def test_corrupted_source_is_rejected_without_hiding_batch_history(client):
    web, actor, headers, objects = client
    preview = web.post(
        "/api/v1/research/import-previews", json=request_for(actor), headers=headers()
    )
    assert preview.status_code == 201, preview.text
    identity = preview.json()["id"]
    with connection() as c:
        metadata = import_history.source_metadata(c, identity)
    objects[metadata["object_key"]] += b"changed"
    source = web.get(f"/api/v1/research/imports/{identity}/source")
    assert source.status_code == 409 and source.json()["code"] == "MANIFEST_CORRUPTED"
    assert web.get(f"/api/v1/research/imports/{identity}").status_code == 200


def test_same_key_concurrent_previews_create_one_batch_and_one_ack(client):
    web, actor, headers, _ = client
    body, original_headers = request_for(actor), headers()
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(
            workers.map(
                lambda _: web.post(
                    "/api/v1/research/import-previews", json=body, headers=original_headers
                ),
                range(2),
            )
        )
    assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM import_batches WHERE created_by=%s", (actor,)
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM commands WHERE actor_id=%s AND command_kind=%s AND idempotency_key=%s",
                (actor, import_history.PREVIEW_KIND, original_headers["Idempotency-Key"]),
            ).fetchone()["n"]
            == 1
        )


def test_prior_partial_success_and_same_bytes_reuse_contract_still_holds(client):
    legacy_import(client)


def test_missing_and_corrupt_originals_fail_only_their_records(client):
    web, actor, headers, objects = client
    records = [request_for(actor, key=f"actual-{index}")["records"][0] for index in range(3)]
    # Seed includes a historical fact. These new exact bytes have never been recorded.
    with connection() as c:
        for row in records:
            blob, document = uuid4(), uuid4()
            key = f"synthetic-new-original/{blob}"
            raw = str(document).encode()
            objects[key] = raw
            c.execute(
                "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf')",
                (blob, sha(raw), key, len(raw)),
            )
            c.execute(
                "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) "
                "SELECT %s,bid_id,%s,'new-synthetic-body.pdf',obtained_at,artifact_kind,created_by "
                "FROM document_versions WHERE id=%s",
                (document, blob, row["actual_document_version_id"]),
            )
            row["actual_document_version_id"] = str(document)
    with connection() as c:
        keys = [
            c.execute(
                "SELECT b.object_key FROM blobs b JOIN document_versions d ON d.blob_id=b.id WHERE d.id=%s",
                (row["actual_document_version_id"],),
            ).fetchone()["object_key"]
            for row in records
        ]
    del objects[keys[0]]
    objects[keys[1]] += b"corrupted"
    preview = web.post(
        "/api/v1/research/import-previews", json={"records": records}, headers=headers()
    )
    assert preview.status_code == 201, preview.text
    assert preview.json()["counts"]["pending"] == 3
    result = web.post(
        f"/api/v1/research/imports/{preview.json()['id']}/confirm",
        json={},
        headers=headers(preview.headers["ETag"]),
    )
    assert result.status_code == 200, result.text
    assert result.json()["counts"] == {"total": 3, "imported": 1, "pending": 0, "errors": 2}
    if destination := os.environ.get("HISTORICAL_IMPORT_BROWSER_FIXTURE_DIR"):
        output = Path(destination)
        output.mkdir(parents=True, exist_ok=True)
        source = web.get(f"/api/v1/research/imports/{preview.json()['id']}/source")
        assert source.status_code == 200, source.text
        directory = web.get("/api/v1/research/imports?mode=confirmed_import&limit=1")
        fixture = {
            "request": {"records": records},
            "preview": preview.json(),
            "preview_etag": preview.headers["ETag"],
            "confirmed": result.json(),
            "confirmed_etag": result.headers["ETag"],
            "source": source.json(),
            "directory": directory.json(),
        }
        (output / "import-native-pg.json").write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    assert [row["errors"] for row in result.json()["records"]] == [
        ["IMPORT_ORIGINAL_MISSING"],
        ["IMPORT_ORIGINAL_CORRUPTED"],
        [],
    ]
    with connection() as c:
        for index, row in enumerate(records):
            saved = c.execute(
                "SELECT evidence FROM submission_records WHERE bid_id=%s AND body_version_id=%s",
                (row["bid_id"], row["actual_document_version_id"]),
            ).fetchall()
            assert len(saved) == (1 if index == 2 else 0)
            if saved:
                proof = saved[0]["evidence"]["original_verification"]
                assert proof["version"] == import_originals.VERSION
                assert proof["platform_submission_verified"] is False
                assert len(proof["documents"]) == 2
                assert all("object_key" not in document for document in proof["documents"])


def test_storage_outage_does_not_commit_confirmation_and_original_key_can_retry(
    client, monkeypatch
):
    web, actor, headers, _ = client
    preview = web.post(
        "/api/v1/research/import-previews", json=request_for(actor), headers=headers()
    )
    assert preview.status_code == 201, preview.text
    path = f"/api/v1/research/imports/{preview.json()['id']}/confirm"
    original_headers = headers(preview.headers["ETag"])

    def outage(_value):
        raise DomainError("OBJECT_STORE_UNAVAILABLE", "合成对象存储暂时不可用", 503, retryable=True)

    with monkeypatch.context() as patch:
        patch.setattr(import_originals.original_verification, "verify", outage)
        failed = web.post(path, json={}, headers=original_headers)
    assert failed.status_code == 503, failed.text
    assert web.get(f"/api/v1/research/imports/{preview.json()['id']}").json()["mode"] == "dry_run"
    with connection() as c:
        assert (
            c.execute(
                "SELECT id FROM commands WHERE actor_id=%s AND command_kind=%s AND idempotency_key=%s",
                (actor, import_history.CONFIRM_KIND, original_headers["Idempotency-Key"]),
            ).fetchone()
            is None
        )
    restored = web.post(path, json={}, headers=original_headers)
    assert restored.status_code == 200 and restored.json()["counts"]["imported"] == 1, restored.text
