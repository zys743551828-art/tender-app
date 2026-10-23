"""New PG/Kafka/S3, real nonowner API/Worker processes and synthetic original bytes."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import subprocess  # nosec B404
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from botocore.exceptions import ClientError
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from deploy import fusion_full_init as initialize
from deploy import fusion_full_probe as probe
from deploy import fusion_full_runtime as runtime
from deploy import fusion_full_spec as spec

DIRECTORY = os.environ.get("FUSION_FULL_NATIVE_DIRECTORY")
RECEIPT = os.environ.get("FUSION_FULL_NATIVE_RECEIPT")
TOOLS = os.environ.get("FUSION_FULL_NATIVE_TOOLS")
pytestmark = pytest.mark.skipif(
    not DIRECTORY or not RECEIPT or not TOOLS,
    reason="explicit new native full-runtime launcher required",
)


@pytest.fixture(scope="module")
def native():
    directory = Path(DIRECTORY)
    operator = initialize.operator(directory)
    assert operator["plan"]["topology"]["mode"] == "loopback"
    assert operator["plan"]["topology"]["postgres_port"] != 55441
    receipt = initialize.initialize(directory)
    assert receipt["state"] == "created_fresh"
    profiles = {
        role: spec.load_private_json(directory / "runtime" / role / "profile.json")
        for role in receipt["runtime_roles"]
    }
    value = {
        "directory": directory,
        "operator": operator,
        "receipt": receipt,
        "profiles": profiles,
        "checks": {},
    }
    yield value


def test_fresh_initialization_and_replay_use_distinct_real_nonowner_roles(native):
    first = native["receipt"]
    replay = initialize.initialize(native["directory"])
    assert replay == first | {"state": "validated_existing", "provider_calls": 0}
    assert set(native["profiles"]) == {"api", "worker", "relay", "reconcile", "controller"}
    roles = {}
    for role, profile in native["profiles"].items():
        result = probe.check(profile)
        assert result["ready"] and result["provider_calls"] == 0
        assert result["database"]["nonowner"]
        assert result["database"]["schema_tables_verified"] == len(probe.REQUIRED_TABLES)
        if "KAFKA_BOOTSTRAP_SERVERS" in profile["environment"]:
            assert result["kafka"]["topics_verified"] == 9 and not result["kafka"]["topics_created"]
        roles[role] = result
    with psycopg.connect(
        native["profiles"]["api"]["environment"]["API_DATABASE_DSN"], row_factory=dict_row
    ) as c:
        assert c.execute("SELECT count(*) AS n FROM design.model_calls").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM design.assistant_jobs").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM design.task_definitions").fetchone()["n"] == 0
        table_count = c.execute(
            "SELECT count(*) AS n FROM pg_tables WHERE schemaname NOT IN('pg_catalog','information_schema')"
        ).fetchone()["n"]
        caps = c.execute(
            "SELECT to_regclass('design.assistant_generation_batches') IS NOT NULL AS batch,to_regclass('design.bid_package_submission_bindings') IS NOT NULL AS package_submission"
        ).fetchone()
        assert all(caps.values())
    native["checks"]["initialization"] = {
        "replay_no_mutation": True,
        "roles": roles,
        "table_count": table_count,
        "source_sql_identity_scope": "exact SQL bytes applied by fresh initializer; readiness checks required table presence and role isolation",
        "provider_calls": 0,
    }


def test_real_scoped_store_credentials_wrong_key_missing_and_corrupted_marker(native):
    profile = native["profiles"]["api"]
    bucket = profile["environment"]["OBJECT_STORE_BUCKET"]
    clients = {
        name: probe.store_client(
            initialize.store_environment(native["operator"], name, "synthetic/")
        )
        for name in ("init", "api", "worker")
    }
    isolated_bucket = "native-other-" + uuid4().hex
    clients["init"].create_bucket(Bucket=isolated_bucket)
    try:
        for name in ("api", "worker"):
            key = "native-profile-check/" + name
            clients[name].put_object(Bucket=bucket, Key=key, Body=b"synthetic exact scoped object")
            body = clients[name].get_object(Bucket=bucket, Key=key)["Body"]
            try:
                assert body.read() == b"synthetic exact scoped object"
            finally:
                body.close()
            with pytest.raises(ClientError) as denied:
                clients[name].put_object(Bucket=isolated_bucket, Key=key, Body=b"must be denied")
            assert denied.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403
            clients["init"].delete_object(Bucket=bucket, Key=key)
        changed = copy.deepcopy(profile)
        changed["environment"]["OBJECT_STORE_SECRET_KEY"] = "wrong-private-key-" + uuid4().hex
        with pytest.raises(spec.ConfigurationError, match="FULL_OBJECT_STORE_UNAVAILABLE"):
            probe.check(changed)
        marker = profile["probe"]["key"]
        stream = clients["init"].get_object(Bucket=bucket, Key=marker)["Body"]
        original = stream.read()
        stream.close()
        try:
            clients["init"].put_object(Bucket=bucket, Key=marker, Body=b"synthetic corruption")
            with pytest.raises(spec.ConfigurationError, match="FULL_OBJECT_BINDING_MISMATCH"):
                probe.check(profile)
            clients["init"].delete_object(Bucket=bucket, Key=marker)
            with pytest.raises(spec.ConfigurationError, match="FULL_OBJECT_STORE_UNAVAILABLE"):
                probe.check(profile)
        finally:
            clients["init"].put_object(Bucket=bucket, Key=marker, Body=original)
        assert probe.check(profile)["ready"]
    finally:
        clients["init"].delete_bucket(Bucket=isolated_bucket)
    native["checks"]["object_store"] = {
        "api_worker_credentials_distinct": profile["environment"]["OBJECT_STORE_ACCESS_KEY"]
        != native["profiles"]["worker"]["environment"]["OBJECT_STORE_ACCESS_KEY"],
        "actual_put_get": True,
        "cross_bucket_writes_denied": 2,
        "wrong_secret_denied": True,
        "corrupted_marker_rejected": True,
        "missing_marker_rejected": True,
        "restored_marker_ready": True,
    }


def test_database_privilege_and_kafka_identity_drift_fail_closed(native):
    profile = native["profiles"]["worker"]
    plan = native["operator"]["plan"]
    dsn = make_conninfo(
        host="127.0.0.1",
        port=plan["topology"]["postgres_port"],
        user="postgres",
        password=native["operator"]["owner_password"],
        dbname=profile["database"],
    )
    from psycopg import sql

    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(sql.SQL("GRANT tender_api TO {}").format(sql.Identifier(profile["login"])))
        try:
            with pytest.raises(spec.ConfigurationError, match="FULL_DATABASE_ROLE_NOT_ISOLATED"):
                probe.check(profile)
        finally:
            c.execute(sql.SQL("REVOKE tender_api FROM {}").format(sql.Identifier(profile["login"])))
    changed = copy.deepcopy(profile)
    changed["plan"]["kafka_cluster_id"] = "z" * 22
    changed["plan_digest"] = spec.digest(changed["plan"])
    with pytest.raises(spec.ConfigurationError, match="FULL_KAFKA_IDENTITY_OR_TOPICS_UNAVAILABLE"):
        probe.check(changed)
    assert probe.check(profile)["ready"]
    native["checks"]["negative_identity"] = {
        "extra_database_membership_rejected": True,
        "wrong_kafka_cluster_rejected": True,
        "restored_role_ready": True,
    }


def _eventually(callback, processes, *, timeout=35):
    deadline = time.monotonic() + timeout
    while True:
        if any(process.poll() is not None for process in processes):
            raise AssertionError("a positively configured native component exited")
        value = callback()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError("native full-runtime completion deadline exceeded")
        time.sleep(0.1)


def _pdf():
    from reportlab.pdfgen import canvas

    stream = io.BytesIO()
    value = canvas.Canvas(stream, pagesize=(420, 595))
    value.drawString(30, 550, "Synthetic full runtime original, real S3 transport.")
    value.showPage()
    value.setPageRotation(90)
    value.drawString(30, 250, "Actual second physical page, no paid model.")
    value.save()
    return stream.getvalue()


def test_cookie_upload_real_relay_worker_exact_parse_and_authenticated_download(native):
    from fastapi.testclient import TestClient

    profile, directory = native["profiles"]["api"], native["directory"]
    allowed = runtime.environment(profile, "api")
    processes, handles = [], []
    try:
        for component in (
            "document",
            "export",
            "comparison",
            "relay",
            "reconcile",
            "build-controller",
            "word-controller",
        ):
            role = spec.COMMANDS[component][0]
            log = os.fdopen(
                os.open(
                    directory / ("component-" + component + ".log"),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                ),
                "wb",
            )
            handles.append(log)
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "deploy.fusion_full_runtime",
                    component,
                    "--profile",
                    str(directory / "runtime" / role / "profile.json"),
                ],
                cwd=spec.fresh.ROOT,
                env={
                    "PATH": os.defpath,
                    "WORKBENCH_ENV_FILE": "explicit-native-component-bootstrap",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                stdout=log,
                stderr=log,
            )  # nosec B603
            processes.append(child)
        with pytest.MonkeyPatch.context() as patch:
            for key in tuple(os.environ):
                if key.endswith("_DSN") or key.startswith(
                    ("DEEPSEEK_", "PARSING_", "RAG_", "WORD_RENDER_")
                ):
                    patch.delenv(key, raising=False)
            for key, value in allowed.items():
                patch.setenv(key, value)
            from apps.api.main import app

            with TestClient(app, base_url=profile["plan"]["origin"]) as client:
                login = client.post(
                    "/api/v1/auth/login",
                    json={"login_name": "admin", "password": native["operator"]["admin_password"]},
                    headers={"Origin": profile["plan"]["origin"]},
                )
                assert login.status_code == 200, login.text

                def headers(*, etag=None):
                    return {
                        "Origin": profile["plan"]["origin"],
                        "X-CSRF-Token": login.json()["csrf_token"],
                        "Idempotency-Key": str(uuid4()),
                    } | ({"If-Match": etag} if etag else {})

                bid_response = client.post(
                    "/api/v1/bids",
                    json={"title": "Synthetic full local profile acceptance"},
                    headers=headers(),
                )
                assert bid_response.status_code == 201, bid_response.text
                bid = bid_response.json()["id"]
                batch = client.post(
                    f"/api/v1/bids/{bid}/upload-batches", json={}, headers=headers()
                )
                assert batch.status_code == 201, batch.text
                raw = _pdf()
                digest = hashlib.sha256(raw).hexdigest()
                grant = client.post(
                    f"/api/v1/bids/{bid}/uploads",
                    json={
                        "batch_id": batch.json()["id"],
                        "filename": "synthetic-runtime.pdf",
                        "role": "supplement",
                        "declared_sha256": digest,
                        "byte_size": len(raw),
                        "target": {"kind": "new_file"},
                    },
                    headers=headers(),
                )
                assert grant.status_code == 200, grant.text
                url = grant.json()["upload_url"]
                assert urlsplit(url).netloc == urlsplit(profile["plan"]["origin"]).netloc
                assert urlsplit(url).path.startswith("/api/v1/object-transfers/uploads/")
                assert "X-Amz" not in url and "object-store" not in url
                upload = grant.json()["upload_id"]
                refreshed = client.post(
                    f"/api/v1/uploads/{upload}/authorizations",
                    json={"part_numbers": [1]},
                    headers=headers(etag=grant.headers["etag"]),
                )
                assert refreshed.status_code == 200, refreshed.text
                assert refreshed.json()["revision"] == grant.json()["revision"] + 1
                stale = client.put(
                    url, content=raw, headers=headers() | {"Content-Type": "application/pdf"}
                )
                assert stale.status_code == 403
                assert stale.json()["code"] == "TRANSFER_TICKET_INVALID"
                url = refreshed.json()["upload_url"]
                assert urlsplit(url).netloc == urlsplit(profile["plan"]["origin"]).netloc
                with TestClient(app, base_url=profile["plan"]["origin"]) as another:
                    assert (
                        another.put(
                            url,
                            content=raw,
                            headers=headers() | {"Content-Type": "application/pdf"},
                        ).status_code
                        == 401
                    )
                    second_login = another.post(
                        "/api/v1/auth/login",
                        json={
                            "login_name": "admin",
                            "password": native["operator"]["admin_password"],
                        },
                        headers={"Origin": profile["plan"]["origin"]},
                    )
                    assert second_login.status_code == 200
                    cross_session = another.put(
                        url,
                        content=raw,
                        headers=headers()
                        | {
                            "Content-Type": "application/pdf",
                            "X-CSRF-Token": second_login.json()["csrf_token"],
                        },
                    )
                    assert cross_session.status_code == 403
                    assert cross_session.json()["code"] == "TRANSFER_TICKET_INVALID"
                sent = client.put(
                    url, content=raw, headers=headers() | {"Content-Type": "application/pdf"}
                )
                assert sent.status_code == 200, sent.text
                finished = client.post(
                    f"/api/v1/uploads/{upload}/complete",
                    json={"parts": [], "declared_sha256": digest},
                    headers=headers(),
                )
                assert finished.status_code == 202, finished.text

                def verified():
                    value = client.get(f"/api/v1/uploads/{upload}")
                    assert value.status_code == 200
                    value = value.json()
                    return value if value["state"] == "verified" else None

                verified_value = _eventually(verified, processes)
                current = client.get(f"/api/v1/bids/{bid}")
                committed = client.post(
                    f"/api/v1/bids/{bid}/upload-batches/{batch.json()['id']}/commit",
                    json={
                        "accepted_upload_ids": [upload],
                        "accepted_binding_ids": [verified_value["binding_id"]],
                        "explicit_partial_acceptance": False,
                    },
                    headers=headers(etag=current.headers["etag"]),
                )
                assert committed.status_code == 202, committed.text

                def material_parsed():
                    value = client.get("/api/v1/operations/" + committed.json()["operation"]["id"])
                    assert value.status_code == 200
                    value = value.json()
                    assert value["state"] not in {"failed", "cancelled"}, value
                    return value if value["state"] == "succeeded" else None

                _eventually(material_parsed, processes)
                with psycopg.connect(allowed["API_DATABASE_DSN"], row_factory=dict_row) as c:
                    document = str(
                        c.execute(
                            "SELECT verified_version_id FROM design.uploads WHERE id=%s", (upload,)
                        ).fetchone()["verified_version_id"]
                    )
                context_url = f"/api/v1/bids/{bid}/documents/{document}"
                context = client.get(context_url + "/parse-context")
                assert context.status_code == 200, context.text
                requested = client.post(
                    context_url + "/parse-requests",
                    json={
                        "context_digest": context.json()["context_digest"],
                        "reason": "Read this exact synthetic original through the actual full runtime",
                    },
                    headers=headers(),
                )
                assert requested.status_code == 202, requested.text
                request_id = requested.json()["request"]["id"]

                def parsed():
                    value = client.get(context_url + "/parse-requests/" + request_id)
                    assert value.status_code == 200
                    value = value.json()
                    assert value["operation"]["state"] not in {"failed", "cancelled"}, value
                    return value if value["operation"]["state"] == "succeeded" else None

                parsed_value = _eventually(parsed, processes)
                assert parsed_value["result"]["coverage"] == "partial"
                assert parsed_value["current_body_changed"] is False
                signed = client.get(f"/api/v1/artifacts/{document}/download")
                assert signed.status_code == 200
                download_url = signed.json()["download_url"]
                assert urlsplit(download_url).netloc == urlsplit(profile["plan"]["origin"]).netloc
                download = client.get(download_url)
                assert download.status_code == 200 and download.content == raw
                with TestClient(app, base_url=profile["plan"]["origin"]) as anonymous:
                    assert anonymous.get(download_url).status_code == 401
                with psycopg.connect(allowed["API_DATABASE_DSN"], row_factory=dict_row) as c:
                    assert (
                        c.execute("SELECT count(*) AS n FROM design.model_calls").fetchone()["n"]
                        == 0
                    )
                    assert (
                        c.execute("SELECT count(*) AS n FROM design.assistant_jobs").fetchone()["n"]
                        == 0
                    )
                    state = c.execute(
                        "SELECT current_body_id,current_review_id FROM design.bid_profiles WHERE bid_id=%s",
                        (bid,),
                    ).fetchone()
                    assert state == {"current_body_id": None, "current_review_id": None}
                    count = c.execute(
                        "SELECT count(*) AS n FROM design.document_parse_results WHERE request_id=%s",
                        (request_id,),
                    ).fetchone()["n"]
                    assert count == 1
                native["checks"]["main_flow"] = {
                    "actual_nonowner_cookie_login": True,
                    "same_origin_upload": True,
                    "same_origin_authorization_refresh": True,
                    "prior_revision_ticket_rejected": True,
                    "anonymous_upload_denied": True,
                    "cross_session_upload_ticket_rejected": True,
                    "private_s3_put_get": True,
                    "kafka_relay_and_standalone_worker_process": True,
                    "default_component_processes_started": 7,
                    "exact_document_parse": True,
                    "coverage": "partial",
                    "authenticated_download_sha256": digest,
                    "source_byte_size": len(raw),
                    "anonymous_download_denied": True,
                    "current_body_changed": False,
                    "model_calls": 0,
                    "assistant_jobs": 0,
                }
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for handle in handles:
            handle.close()


def test_emit_scoped_native_receipt_only_after_all_checks(native):
    assert set(native["checks"]) == {
        "initialization",
        "object_store",
        "negative_identity",
        "main_flow",
    }
    tools = json.loads(TOOLS)
    pg_bin, weed, kafka_dir = Path(tools["pg_bin"]), Path(tools["weed"]), Path(tools["kafka_dir"])
    kafka_jars = sorted((kafka_dir / "libs").glob("kafka_2.13-*.jar"))
    assert len(kafka_jars) == 1
    binary_hashes = {
        "postgres": spec.digest((pg_bin / "postgres").read_bytes()),
        "seaweedfs": spec.digest(weed.read_bytes()),
        "kafka_server_jar": spec.digest(kafka_jars[0].read_bytes()),
    }
    result = {
        "version": "fusion-full-native-acceptance/1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "plan_digest": native["receipt"]["plan_digest"],
        "ordered_sql": native["receipt"]["ordered_sql"],
        "runtime": native["receipt"]["runtime"],
        "binary_sha256": binary_hashes,
        "checks": native["checks"],
        "only_synthetic_originals": True,
        "shared_pg55441_used": False,
        "provider_calls": 0,
        "scheduled_tasks_created": 0,
        "docker_execution_verified": False,
        "nginx_execution_verified": False,
        "configured_ocr_verified": False,
        "semantic_retrieval_verified": False,
        "office_render_sandbox_verified": False,
        "research_model_lanes_started": False,
        "production_qualification": False,
    }
    spec.write_private(Path(RECEIPT), result)
