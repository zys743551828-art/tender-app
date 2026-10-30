"""Opt-in real PG17/API/fenced Worker/S3/prebuilt conversion vertical slice.

The launcher creates fresh labelled dependencies and nonowner LOGIN roles. This
suite exercises real outbox/fence dispatch directly; it does not test Kafka.
"""
# ruff: noqa: F811

import json
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest

from packages.domain import storage
from packages.domain.runtime import assert_role, connection, fetch, sha
from packages.word_intake import conversion, prebuilt, repository
from packages.word_intake.inspection import DOCX, PDF
from tests.test_word_intake import make_docx
from tests.test_word_intake_integration import world as world
from tests.test_word_mainflow_integration import (
    REAL_STORAGE_CLIENT,
    REAL_STORAGE_GET,
    REAL_STORAGE_PUT,
    commit,
    pump,
    upload,
)
from tests.test_word_mainflow_integration import (
    shared as shared,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_WORD_PREBUILT_PG") != "1",
    reason="requires explicit fresh isolated PG17/S3/prebuilt integration launcher",
)


@pytest.fixture
def real_world(shared, monkeypatch):
    from apps.api import main as api

    original_connection = api.connection

    @contextmanager
    def diagnosed_connection(*args, **kwargs):
        try:
            with original_connection(*args, **kwargs) as connection:
                yield connection
        except psycopg.Error as error:
            # Controlled synthetic database only; no SQL, parameter, DSN,
            # environment value or exception detail is recorded.
            diagnostic = {
                "sqlstate": error.sqlstate,
                "table": error.diag.table_name,
                "constraint": error.diag.constraint_name,
                "message": error.diag.message_primary,
                "routine_context": error.diag.context,
            }
            directory = Path(os.environ["WORD_PREBUILT_PG_RESULT_DIRECTORY"])
            (directory / "database-diagnostic.json").write_text(
                json.dumps(diagnostic, indent=2) + "\n", encoding="utf-8"
            )
            raise

    monkeypatch.setattr(api, "connection", diagnosed_connection)
    profile_path = Path(os.environ["WORD_PREBUILT_PG_PROFILE"])
    assert profile_path.is_file()
    monkeypatch.setenv("WORD_RENDER_PROFILE_PATH", str(profile_path))
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
    # The product's S3 mode uses native presigned object transfer. Control-plane
    # requests remain Cookie/CSRF ASGI; bytes travel over real loopback HTTP.
    monkeypatch.delenv("OBJECT_TRANSFER_MODE", raising=False)
    monkeypatch.setattr(storage, "client", REAL_STORAGE_CLIENT)
    monkeypatch.setattr(storage, "get", REAL_STORAGE_GET)
    monkeypatch.setattr(storage, "put", REAL_STORAGE_PUT)
    assert_role()
    assert_role(True)
    profile = conversion.configured_profile()
    assert profile["identity"]["protocol"] == prebuilt.PROTOCOL
    assert (
        storage.client().head_bucket(Bucket=storage.bucket())["ResponseMetadata"]["HTTPStatusCode"]
        == 200
    )
    endpoint = urlsplit(os.environ["OBJECT_STORE_ENDPOINT"])

    class NativeByteClient:
        def __getattr__(self, name):
            return getattr(shared["client"], name)

        def get(self, url, **kwargs):
            if urlsplit(str(url)).netloc == endpoint.netloc:
                with httpx.Client(trust_env=False, timeout=30) as client:
                    return client.get(url, **kwargs)
            return shared["client"].get(url, **kwargs)

        def put(self, url, **kwargs):
            if urlsplit(str(url)).netloc == endpoint.netloc:
                # Cookie/CSRF belongs to the API, never forward it to S3.
                media = kwargs.pop("headers", {}).get("Content-Type")
                with httpx.Client(trust_env=False, timeout=30) as client:
                    return client.put(url, headers={"Content-Type": media}, **kwargs)
            return shared["client"].put(url, **kwargs)

    return shared | {"client": NativeByteClient()}


def test_real_prebuilt_api_worker_s3_adoption_and_exact_download(real_world):
    from apps.api.word_coordinator import tick

    w = real_world
    source = make_docx("施工工期120天，质量合格。真实隔离对象存储转换验证。" + uuid4().hex)
    # Missing CSRF is rejected by the actual Cookie-authenticated API.
    denied = w["client"].post(f"/api/v1/bids/{w['bid']}/upload-batches", json={})
    assert denied.status_code == 403
    original = upload(w, source)
    assert original["verified"]["word_original_saved"] is True
    commit(w, original)
    _, rendered = pump(original["verified"]["conversion_operation_id"])
    outcome = rendered["outcome"]
    assert outcome["state"] == "succeeded"
    assert outcome["coverage"] == "complete"
    assert outcome["conversion_attempted"] is True
    assert outcome["resource_receipt"]["closed"] is True
    receipts = Path(os.environ["WORD_RENDER_TEST_RECEIPT_DIRECTORY"])
    records = [
        json.loads(path.read_text(encoding="utf-8")) for path in receipts.glob("conversion-*.json")
    ]
    own_record = next(
        record for record in records if record["run_id"] == outcome["resource_receipt"]["run_id"]
    )
    assert own_record["closed"] is True
    assert own_record["resources"] and all(
        resource["state"] == "removed" for resource in own_record["resources"]
    )
    assert repository.controlled_qualified(outcome)
    assert outcome["chain"]["source_docx_digest"] == sha(source)

    adopted = tick(w["bid"], UUID(original["version"]))
    assert adopted["state"] == "adopted"
    pump(adopted["parse_operation_id"])
    pdf_id = UUID(adopted["document_version_id"])
    with connection() as c:
        rows = c.execute(
            "SELECT v.id,b.object_key,b.digest,b.byte_size,b.media_type "
            "FROM document_versions v JOIN blobs b ON b.id=v.blob_id "
            "WHERE v.id=ANY(%s::uuid[])",
            ([original["version"], str(pdf_id)],),
        ).fetchall()
        assert len(rows) == 2
        relation = fetch(
            c,
            "SELECT kind,verification,source_document_version_id FROM document_relations "
            "WHERE document_version_id=%s",
            (pdf_id,),
        )
        assert relation["kind"] == "controlled_render"
        assert relation["verification"] == "verified"
        assert relation["source_document_version_id"] == UUID(original["version"])
        assert (
            fetch(c, "SELECT current_body_id FROM bid_profiles WHERE bid_id=%s", (w["bid"],))[
                "current_body_id"
            ]
            == pdf_id
        )
        parsed = fetch(
            c,
            "SELECT id,coverage,page_count,gaps FROM parse_runs WHERE document_version_id=%s",
            (pdf_id,),
        )
        # The actual built-in text parser intentionally preserves incomplete
        # layout/OCR coverage; this is not a Parser03 complete assertion.
        assert parsed["coverage"] == "partial"
        assert parsed["page_count"] == 1 and parsed["gaps"]
        evidence = fetch(
            c,
            "SELECT physical_page,text_content FROM evidence_blocks WHERE parse_id=%s "
            "ORDER BY physical_page,ordinal LIMIT 1",
            (parsed["id"],),
        )
        assert evidence["physical_page"] == 1
        assert "120" in evidence["text_content"]

    assert {row["media_type"] for row in rows} == {DOCX, PDF}
    for row in rows:
        data = REAL_STORAGE_GET(row["object_key"])
        assert len(data) == row["byte_size"] and sha(data) == row["digest"]
    pdf_row = next(row for row in rows if row["media_type"] == PDF)
    assert outcome["chain"]["pdf_digest"] == pdf_row["digest"]
    preview = w["client"].get(f"/api/v1/artifacts/{pdf_id}/download")
    assert preview.status_code == 200
    download = w["client"].get(preview.json()["download_url"])
    assert download.status_code == 200
    assert sha(download.content) == pdf_row["digest"]
    unsigned_url = (
        os.environ["OBJECT_STORE_ENDPOINT"]
        + "/"
        + storage.bucket()
        + "/"
        + quote(pdf_row["object_key"], safe="/")
    )
    with httpx.Client(trust_env=False, timeout=10) as anonymous:
        assert anonymous.get(unsigned_url).status_code == 403
    original_preview = w["client"].get(f"/api/v1/artifacts/{original['version']}/download")
    assert original_preview.status_code == 200
    original_download = w["client"].get(original_preview.json()["download_url"])
    assert original_download.status_code == 200 and original_download.content == source
    listed = storage.client().list_objects_v2(Bucket=storage.bucket())
    assert listed.get("KeyCount", 0) >= 2

    report = {
        "scope": "fresh PG17, two nonowner LOGIN roles, Cookie/CSRF ASGI API, real S3, direct real outbox/fence Worker, prebuilt Gotenberg",
        "kafka_broker_tested": False,
        "in_memory_storage_used": False,
        "conversion": outcome,
        "adopted": True,
        "controlled_relation": {"kind": relation["kind"], "verification": relation["verification"]},
        "parse_coverage": parsed["coverage"],
        "physical_pages": parsed["page_count"],
        "evidence_physical_page": evidence["physical_page"],
        "original_sha256": sha(source),
        "pdf_sha256": pdf_row["digest"],
        "exact_api_downloads_verified": True,
        "byte_transport": "real native presigned S3 over loopback; API Cookie/CSRF grants",
        "anonymous_s3_read_denied": True,
        "private_bucket_object_count": listed["KeyCount"],
    }
    directory = Path(os.environ["WORD_PREBUILT_PG_RESULT_DIRECTORY"])
    directory.mkdir(parents=True, exist_ok=True)
    # Export only synthetic bytes read back and checked against the stored SHA.
    (directory / "actual-source.docx").write_bytes(original_download.content)
    (directory / "actual-output.pdf").write_bytes(download.content)
    (directory / "vertical-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
