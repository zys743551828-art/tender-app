"""Current /3 role binding, refusal cases and a real nonempty two-cluster migration."""
# ruff: noqa: F401,F811 -- actual existing authoring fixture graph

import io
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from extended_recovery_helpers import proof, s3
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from reportlab.pdfgen import canvas
from test_extended_recovery_authoring_pg import (
    adopted,
    api,
    build_database,
    case,
    compute,
    database,
    edit,
    exact,
    input_database,
    job_database,
    publish,
    published,
    queued,
    request_body,
    requirements,
    revision_database,
    start,
    text_edit_database,
    world,
)

from deploy import extended_recovery
from deploy import extended_recovery_runtime as runtime
from deploy.backups import run

OWNER = "extended_recovery_owner_" + "a" * 16
READER = "migration_reader"


def rows():
    return [
        ("purpose_group", False, True, False, False, False, False, False),
        ("purpose_worker", True, True, False, False, False, False, False),
        (READER, True, True, False, False, False, False, False),
    ]


def test_actual_acl_membership_closure_keeps_nonowner_attributes():
    result = runtime.validated_role_plan(
        rows(),
        [("purpose_group", "purpose_worker", False, True, True)],
        ["purpose_group"],
        owner=OWNER,
        reader=READER,
    )
    assert {r[0] for r in result["roles"]} == {"purpose_group", "purpose_worker", READER}
    assert result["memberships"] == [["purpose_group", "purpose_worker", False, True, True]]


@pytest.mark.parametrize("name", ["pg_read_all_data", "bad;role", OWNER, "unknown_role"])
def test_untrusted_privileged_or_missing_role_rejected(name):
    with pytest.raises(run.BackupError, match="PRIVILEGED_OR_UNKNOWN_ROLE"):
        runtime.validated_role_plan(rows(), [], [name], owner=OWNER, reader=READER)


@pytest.mark.parametrize("attribute", [3, 4, 5, 6, 7])
def test_source_privileged_attributes_never_recreated(attribute):
    changed = [list(r) for r in rows()]
    changed[1][attribute] = True
    with pytest.raises(run.BackupError, match="PRIVILEGED_OR_UNKNOWN_ROLE"):
        runtime.validated_role_plan(changed, [], ["purpose_worker"], owner=OWNER, reader=READER)


def test_admin_membership_rejected_instead_of_expanding_worker_power():
    with pytest.raises(run.BackupError, match="ROLE_ADMIN_FORBIDDEN"):
        runtime.validated_role_plan(
            rows(),
            [("purpose_group", "purpose_worker", True, True, True)],
            ["purpose_group"],
            owner=OWNER,
            reader=READER,
        )


@pytest.mark.parametrize(
    "edge", [("purpose_group",), ("purpose_group", "purpose_worker", 1, True, True)]
)
def test_malformed_role_edges_rejected(edge):
    with pytest.raises(run.BackupError, match="MEMBERSHIP_INVALID"):
        runtime.validated_role_plan(rows(), [edge], ["purpose_group"], owner=OWNER, reader=READER)


@pytest.mark.parametrize("source,target", [("7", "7"), ("not-an-id", "8")])
def test_same_or_unverified_cluster_identity_rejected(source, target):
    with pytest.raises(run.BackupError, match="DISTINCT_CLUSTER_REQUIRED"):
        runtime.require_distinct_clusters(source, target)


def test_initial_owner_refused_before_any_resource_creation(tmp_path):
    with pytest.raises(run.BackupError, match="INITIAL_OWNER_INVALID"):
        with runtime.temporary_postgres(tmp_path, None, {}, [], initial_owner="postgres"):
            pytest.fail("must not yield")
    assert list(tmp_path.iterdir()) == []


def test_external_archive_cannot_enter_capture_path(tmp_path, monkeypatch):
    directory = tmp_path / "untrusted"
    directory.mkdir()
    (directory / "database.dump").write_bytes(b"not a trusted dump")
    monkeypatch.setattr(
        extended_recovery, "snapshot", lambda *_a, **_k: pytest.fail("no SQL capture")
    )
    owner = make_conninfo(
        host="127.0.0.1", port=54321, user=OWNER, password="synthetic-test-only", dbname="synthetic"
    )
    values = {"OWNER_DATABASE_DSN": owner, "API_DATABASE_DSN": make_conninfo(owner, user=READER)}
    with pytest.raises(run.BackupError, match="FRESH_SYNTHETIC_ARCHIVE_REQUIRED"):
        runtime.capture_migration(
            values, directory, tool=None, client=None, bucket="tender-ci-authoring-abcd"
        )
    assert (directory / "database.dump").read_bytes() == b"not a trusted dump"


def test_modified_archive_binding_rejected_before_connections(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_bytes(b"changed")
    source = SimpleNamespace(directory=tmp_path, fingerprints={"manifest.json": "0" * 64})
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: pytest.fail("no DB connection"))
    with pytest.raises(run.BackupError, match="ARCHIVE_BINDING_CHANGED"):
        runtime.verify_migration_source(source)


@pytest.mark.skipif(
    os.environ.get("FUSION_EXTENDED_RECOVERY_PG") != "1",
    reason="explicit owned two-cluster PG17/S3 migration required",
)
def test_nonempty_authoring_migrates_to_distinct_owned_pg17_cluster(adopted):
    w = adopted
    response = edit(w, request_body(w))
    assert response.status_code == 200
    w["saved"].update(
        {k: response.json()[k] for k in ("draft_revision", "snapshot_id", "snapshot_digest")}
    )
    built = start(w)
    computed = compute(built)
    publish(built, computed)
    owner = w["database"]["owner"]
    source_owner_dsn = make_conninfo(
        os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"], dbname=owner.info.dbname
    )
    tool = extended_recovery.local_tool(
        os.environ["FUSION_EXTENDED_RECOVERY_PG_BIN"],
        os.environ.get("FUSION_EXTENDED_RECOVERY_PG_LIBRARY_DIR"),
    )
    run.ARCHIVE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = run.ARCHIVE_ROOT / ("migration-" + uuid4().hex)
    cleanup = []
    result = None
    try:
        with runtime.migration_reader(source_owner_dsn) as values:
            source = runtime.capture_migration(
                values, directory, tool=tool, client=s3(), bucket=os.environ["OBJECT_STORE_BUCKET"]
            )
            assert any(
                row["schema"] == "design"
                and row["name"] == "authoring_exact_manual_revisions"
                and row["rows"] > 0
                for row in source.rows
            )
            with runtime.temporary_postgres(
                Path(os.environ["FUSION_EXTENDED_RECOVERY_PG_BIN"]),
                Path(os.environ["FUSION_EXTENDED_RECOVERY_PG_LIBRARY_DIR"])
                if os.environ.get("FUSION_EXTENDED_RECOVERY_PG_LIBRARY_DIR")
                else None,
                runtime.ci_checks.test_environment(),
                cleanup,
                initial_owner=source.owner,
            ) as target_owner:
                target = runtime.provision_migration_target(source, target_owner)
                assert (
                    conninfo_to_dict(target_owner)["password"]
                    != conninfo_to_dict(source_owner_dsn)["password"]
                )
                assert (
                    conninfo_to_dict(target["values"]["API_DATABASE_DSN"])["password"]
                    != conninfo_to_dict(values["API_DATABASE_DSN"])["password"]
                )
                assert target["system_identifier"] != source.system_identifier
                with runtime.migrated_database(
                    source, target, tool=tool, client=s3(admin=True)
                ) as result:
                    database_name = result["database_receipt"]["database"]
                    reader_dsn = make_conninfo(
                        target["values"]["API_DATABASE_DSN"], dbname=database_name
                    )
                    with psycopg.connect(reader_dsn) as c:
                        assert (
                            c.execute(
                                "SELECT count(*) FROM design.authoring_exact_manual_revisions"
                            ).fetchone()[0]
                            > 0
                        )
                        assert (
                            c.execute("SELECT count(*) FROM design.build_outputs").fetchone()[0] > 0
                        )
                    with psycopg.connect(
                        make_conninfo(reader_dsn, options="-c default_transaction_read_only=off")
                    ) as c:
                        with pytest.raises(psycopg.errors.InsufficientPrivilege):
                            c.execute(
                                "UPDATE design.members SET display_name=display_name WHERE false"
                            )
                    originals = runtime.completion_recovery.validate_originals(directory)
                    for item in originals["objects"]:
                        actual = run.read_object(
                            s3(admin=True),
                            result["object_receipt"]["target_bucket"],
                            item["key"],
                            item["bytes"],
                            item["sha256"],
                        )
                        assert actual == (directory / item["file"]).read_bytes()
                assert result["source_unchanged"] and result["new_database_and_bucket_removed"]
            assert len(cleanup) == 1 and all(all(record.values()) for record in cleanup)
            result = {
                "format": "current-authoring-cross-cluster-offline-migration/1",
                "source_system_identifier": source.system_identifier,
                "target_system_identifier": target["system_identifier"],
                "distinct_pg17_clusters": True,
                "current_ordered_sql": runtime.completion_recovery.plan_receipt(
                    extended_recovery.frozen_plan()
                ),
                "nonempty_authoring_rows": True,
                "original_restore_definition_acl_row_byte_assertions_preserved": True,
                "source_unchanged": result["source_unchanged"],
                "target_database_and_bucket_removed": result["new_database_and_bucket_removed"],
                "target_cluster_cleanup": cleanup,
                "new_target_passwords_generated": True,
                "model_calls": 0,
                "full_application_restore_qualified": False,
                "production_rpo_rto_qualified": False,
            }
    finally:
        if directory.exists():
            run.private_archive(directory, existing=True)
            shutil.rmtree(directory)
    assert result is not None
    proof("migration", result)


@pytest.mark.parametrize(
    "record",
    [("schema", "design", "", "", "CREATE"), ("unknown", "design", "x", "", "SELECT"), None],
)
def test_api_activation_rejects_ddl_or_unrecognized_metadata(record):
    with pytest.raises(run.BackupError, match="API_CREATE_FORBIDDEN|API_ACL_INVALID"):
        runtime.api_acl_grants([record])


def test_api_projection_keeps_column_scope_and_does_not_restore_truncate():
    column = ("column", "design", "members", "display_name", "UPDATE")
    truncate = ("table", "design", "members", "", "TRUNCATE")
    assert runtime.api_acl_grants([column, truncate]) == [column]


def test_api_acl_expansion_rejected():
    source = [("table", "design", "bids", "", "SELECT")]
    with pytest.raises(run.BackupError, match="API_PRIVILEGE_EXPANSION"):
        runtime.require_api_acl_subset(source + [("table", "design", "bids", "", "UPDATE")], source)


def test_api_activation_needs_original_completed_offline_verification(monkeypatch):
    monkeypatch.setattr(runtime, "verify_migration_source", lambda _source: None)
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: pytest.fail("no target connection"))
    with pytest.raises(run.BackupError, match="OFFLINE_VERIFICATION_REQUIRED"):
        runtime.activate_migrated_api(None, {"system_identifier": "2", "passwords": {}}, {}, "api")


def _free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@contextmanager
def _current_api(environment, origin, records, label):
    """One actual current API process, isolated purpose environment, no consumer."""
    port = urlsplit(origin).port
    record = {"role": label, "loopback_only": True, "stopped": False}
    records.append(record)
    with tempfile.TemporaryDirectory(prefix="recovery-api-") as directory:
        with (Path(directory) / "api.log").open("wb") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "uvicorn",
                    "apps.api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                    "--no-access-log",
                ],
                cwd=run.ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            record["pid"] = process.pid
            try:
                with httpx.Client(base_url=origin, timeout=10, trust_env=False) as client:
                    deadline = time.monotonic() + 30
                    while True:
                        if process.poll() is not None:
                            pytest.fail(
                                "current API exited before readiness; private log suppressed"
                            )
                        try:
                            response = client.get("/api/v1/auth/session")
                            if response.status_code == 401:
                                break
                        except httpx.TransportError:
                            pass
                        if time.monotonic() >= deadline:
                            pytest.fail("current API readiness deadline")
                        time.sleep(0.1)
                    yield client
            finally:
                if process.poll() is None:
                    try:
                        if os.getpgid(process.pid) != process.pid:
                            raise RuntimeError("OWNED_API_PROCESS_GROUP_CHANGED")
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                record.update(stopped=process.poll() is not None, exit_code=process.returncode)


def _api_environment(dsn, origin, object_values):
    environment = {
        k: v
        for k, v in runtime.ci_checks.test_environment().items()
        if k in {"PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE"}
    }
    environment.update({k: v for k, v in object_values.items() if k.startswith("OBJECT_STORE_")})
    environment.update(
        API_DATABASE_DSN=dsn,
        APP_ORIGIN=origin,
        SESSION_SECRET=secrets.token_urlsafe(48),
        CSRF_SECRET=secrets.token_urlsafe(48),
        WORKBENCH_ENV_FILE="explicit-owned-api-smoke-no-ambient-profile",
        OBJECT_TRANSFER_MODE="same_origin",
        PYTHONDONTWRITEBYTECODE="1",
    )
    assert not any(
        key.endswith("_DATABASE_DSN") and key != "API_DATABASE_DSN" or key.startswith("DEEPSEEK_")
        for key in environment
    )
    return environment


def _login(client, origin, login_name, password):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": origin},
        json={"login_name": login_name, "password": password},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _command(client, origin, csrf, method, path, body, *, etag=None, key=None):
    headers = {"Origin": origin, "X-CSRF-Token": csrf, "Idempotency-Key": key or uuid4().hex}
    if etag is not None:
        headers["If-Match"] = etag
    return client.request(method, path, headers=headers, json=body)


@pytest.mark.skipif(
    os.environ.get("FUSION_EXTENDED_RECOVERY_PG") != "1",
    reason="explicit owned current-API recovery PG17/S3 smoke required",
)
def test_current_api_post_activation_old_cookie_login_reads_and_once_only_write():
    from apps.api.auth import password_hash
    from deploy import bootstrap_fresh as fresh
    from deploy.initialize_database import file_configuration

    binary = Path(os.environ["FUSION_EXTENDED_RECOVERY_PG_BIN"])
    library = (
        Path(os.environ["FUSION_EXTENDED_RECOVERY_PG_LIBRARY_DIR"])
        if os.environ.get("FUSION_EXTENDED_RECOVERY_PG_LIBRARY_DIR")
        else None
    )
    tool = extended_recovery.local_tool(binary, library)
    cleanup, processes = [], []
    name = "api_recovery_" + uuid4().hex[:8]
    base = run.ROOT / ".local" / (name + "-base.env")
    directory = run.ARCHIVE_ROOT / ("api-migration-" + uuid4().hex)
    source_objects = {
        k: os.environ[k]
        for k in [
            "OBJECT_STORE_BACKEND",
            "OBJECT_STORE_ENDPOINT",
            "OBJECT_STORE_REGION",
            "OBJECT_STORE_BUCKET",
            "OBJECT_STORE_ACCESS_KEY",
            "OBJECT_STORE_SECRET_KEY",
        ]
    }
    result = None
    try:
        with runtime.temporary_postgres(
            binary, library, runtime.ci_checks.test_environment(), cleanup
        ) as source_admin:
            fields = conninfo_to_dict(source_admin)
            uri = f"postgresql://{quote(str(fields['user']), safe='')}:{quote(str(fields['password']), safe='')}@127.0.0.1:{fields['port']}/postgres"
            with psycopg.connect(source_admin, autocommit=True) as c:
                for group in fresh.GROUPS:
                    c.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
            fresh.write_private(
                base,
                {
                    "OWNER_DATABASE_DSN": uri,
                    "OBJECT_STORE_PREFIX": "synthetic-api-recovery",
                    **source_objects,
                },
            )
            plan = extended_recovery.frozen_plan()
            prepared = fresh.bootstrap(
                base_profile=base,
                name=name,
                extensions=[
                    (run.ROOT / item.path, item.sha256)
                    for item in plan
                    if item.path not in fresh.BASE_SQL
                ],
                expected_sql_plan=[(item.path, item.sha256) for item in plan],
            )
            business = file_configuration(run.ROOT / prepared["profiles"]["business"])
            source_dsn = business["API_DATABASE_DSN"]
            member, login_name, password = (
                uuid4(),
                "recovery_" + uuid4().hex[:8],
                secrets.token_urlsafe(32),
            )
            with psycopg.connect(source_dsn) as c:
                c.execute("SET LOCAL search_path=design,public")
                c.execute(
                    "INSERT INTO members(id,display_name) VALUES(%s,'Synthetic recovery operator')",
                    (member,),
                )
                c.execute(
                    "INSERT INTO credentials(member_id,login_name,password_hash) VALUES(%s,%s,%s)",
                    (member, login_name, password_hash(password)),
                )
            source_origin = "http://127.0.0.1:" + str(_free_port())
            source_env = _api_environment(source_dsn, source_origin, source_objects)
            with _current_api(source_env, source_origin, processes, "source_api") as source_http:
                csrf = _login(source_http, source_origin, login_name, password)
                created = _command(
                    source_http,
                    source_origin,
                    csrf,
                    "POST",
                    "/api/v1/bids",
                    {"title": "Synthetic current recovery smoke"},
                )
                assert created.status_code == 201
                bid = created.json()["id"]
                settings = source_http.get("/api/v1/bids/" + bid + "/settings")
                changed = _command(
                    source_http,
                    source_origin,
                    csrf,
                    "PATCH",
                    "/api/v1/bids/" + bid + "/settings",
                    {"auto_review": False},
                    etag=settings.headers["etag"],
                )
                assert changed.status_code == 200
                created = _command(
                    source_http,
                    source_origin,
                    csrf,
                    "POST",
                    "/api/v1/bids/" + bid + "/drafts",
                    {"title": "Synthetic restored draft", "outline_template_version_id": None},
                )
                assert created.status_code == 201
                draft = created.json()
                section = source_http.get("/api/v1/sections/" + draft["sections"][0]["id"]).json()
                content = section["content"]
                content["content"] = [
                    {
                        "type": "paragraph",
                        "attrs": {"id": str(uuid4())},
                        "content": [
                            {
                                "type": "text",
                                "text": "Synthetic current application recovery content.",
                            }
                        ],
                    }
                ]
                saved = _command(
                    source_http,
                    source_origin,
                    csrf,
                    "PATCH",
                    "/api/v1/bids/" + bid + "/drafts/" + draft["id"],
                    {
                        "base_draft_revision": draft["revision"],
                        "changes": [
                            {
                                "section_id": section["id"],
                                "base_section_revision": section["revision"],
                                "schema_digest": section["schema_digest"],
                                "content": content,
                            }
                        ],
                    },
                    etag='"draft:' + draft["id"] + ":" + str(draft["revision"]) + '"',
                )
                assert saved.status_code == 200
                stream = io.BytesIO()
                pdf = canvas.Canvas(stream, pagesize=(150, 200), invariant=1)
                pdf.drawString(10, 80, "Synthetic recovery original")
                pdf.save()
                raw = stream.getvalue()
                checksum = run.digest(raw)
                key = "recovery-smoke/" + uuid4().hex + ".pdf"
                blob, document = uuid4(), uuid4()
                s3().put_object(
                    Bucket=source_objects["OBJECT_STORE_BUCKET"],
                    Key=key,
                    Body=raw,
                    ContentType="application/pdf",
                )
                assert (
                    run.read_object(
                        s3(), source_objects["OBJECT_STORE_BUCKET"], key, len(raw), checksum
                    )
                    == raw
                )
                # Explicit fixture, using only the normal API login; no parse/upload or
                # qualification success, worker result or producer receipt is inserted.
                with psycopg.connect(source_dsn) as c:
                    c.execute("SET LOCAL search_path=design,public")
                    c.execute(
                        "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf')",
                        (blob, checksum, key, len(raw)),
                    )
                    c.execute(
                        "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic-recovery-original.pdf',%s,'source_original',%s)",
                        (document, bid, blob, datetime.now(timezone.utc), member),
                    )
                old_cookie = source_http.cookies.get("session")
                assert old_cookie is not None
            assert processes[-1]["stopped"]
            owner_dsn = make_conninfo(source_admin, dbname=prepared["database"])
            with runtime.migration_reader(owner_dsn) as values:
                source = runtime.capture_migration(
                    values,
                    directory,
                    tool=tool,
                    client=s3(),
                    bucket=source_objects["OBJECT_STORE_BUCKET"],
                )
                with runtime.temporary_postgres(
                    binary,
                    library,
                    runtime.ci_checks.test_environment(),
                    cleanup,
                    initial_owner=source.owner,
                ) as target_owner:
                    target = runtime.provision_migration_target(source, target_owner)
                    with runtime.migrated_database(
                        source, target, tool=tool, client=s3(admin=True)
                    ) as restored:
                        api_login = str(conninfo_to_dict(source_dsn)["user"])
                        api_dsn, activation = runtime.activate_migrated_api(
                            source, target, restored, api_login
                        )
                        target_origin = "http://127.0.0.1:" + str(_free_port())
                        target_objects = source_objects | {
                            "OBJECT_STORE_BUCKET": restored["object_receipt"]["target_bucket"],
                            "OBJECT_STORE_ACCESS_KEY": os.environ[
                                "FUSION_EXTENDED_RECOVERY_S3_READER_ACCESS_KEY"
                            ],
                            "OBJECT_STORE_SECRET_KEY": os.environ[
                                "FUSION_EXTENDED_RECOVERY_S3_READER_SECRET_KEY"
                            ],
                        }
                        target_env = _api_environment(api_dsn, target_origin, target_objects)
                        rotated = (
                            target_env["SESSION_SECRET"] != source_env["SESSION_SECRET"]
                            and target_env["CSRF_SECRET"] != source_env["CSRF_SECRET"]
                        )
                        assert rotated
                        with _current_api(
                            target_env, target_origin, processes, "target_api"
                        ) as target_http:
                            response = target_http.get(
                                "/api/v1/auth/session", cookies={"session": old_cookie}
                            )
                            assert response.status_code == 401
                            csrf = _login(target_http, target_origin, login_name, password)
                            assert target_http.get("/api/v1/bids/" + bid).status_code == 200
                            response = target_http.get(
                                "/api/v1/bids/" + bid + "/drafts/" + draft["id"]
                            )
                            assert response.status_code == 200 and response.json()["revision"] == 2
                            original = target_http.get(
                                "/api/v1/artifacts/" + str(document) + "/download"
                            )
                            artifact = {
                                "status": original.status_code,
                                "fixture_upload_pipeline_qualified": False,
                            }
                            if original.status_code == 200:
                                url = original.json()["download_url"]
                                assert (
                                    urlsplit(url).scheme == "http"
                                    and urlsplit(url).netloc == urlsplit(target_origin).netloc
                                )
                                downloaded = target_http.get(url)
                                artifact["transfer_status"] = downloaded.status_code
                                if downloaded.status_code == 200:
                                    assert downloaded.content == raw
                                    artifact["bytes_equal"] = True
                                else:
                                    assert downloaded.status_code in {403, 404, 409, 422, 503}
                                    artifact["refused_without_bypass"] = True
                            else:
                                assert original.status_code in {403, 404, 409, 422, 503}
                                artifact["refused_without_bypass"] = True
                            path = "/api/v1/bids/" + bid + "/settings"
                            current = target_http.get(path)
                            revision = current.json()["revision"]
                            idempotency = uuid4().hex
                            denied = target_http.patch(
                                path,
                                json={"result_reminder": False},
                                headers={"Idempotency-Key": uuid4().hex},
                            )
                            assert denied.status_code == 403
                            first = _command(
                                target_http,
                                target_origin,
                                csrf,
                                "PATCH",
                                path,
                                {"result_reminder": False},
                                etag=current.headers["etag"],
                                key=idempotency,
                            )
                            replay = _command(
                                target_http,
                                target_origin,
                                csrf,
                                "PATCH",
                                path,
                                {"result_reminder": False},
                                etag=current.headers["etag"],
                                key=idempotency,
                            )
                            assert first.status_code == replay.status_code == 200
                            assert replay.headers.get("Idempotent-Replayed") == "true"
                            assert target_http.get(path).json()["revision"] == revision + 1
                            with psycopg.connect(api_dsn) as c:
                                identity = c.execute(
                                    "SELECT current_user,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
                                ).fetchone()
                                assert identity[0] == api_login and not any(identity[1:])
                                assert (
                                    c.execute(
                                        "SELECT count(*) FROM design.commands WHERE actor_id=%s AND idempotency_key=%s",
                                        (member, idempotency),
                                    ).fetchone()[0]
                                    == 1
                                )
                                assert (
                                    c.execute("SHOW transaction_read_only").fetchone()[0] == "off"
                                )
                            with psycopg.connect(
                                make_conninfo(
                                    target["values"]["API_DATABASE_DSN"],
                                    dbname=restored["database_receipt"]["database"],
                                )
                            ) as c:
                                assert c.execute("SHOW transaction_read_only").fetchone()[0] == "on"
                        assert processes[-1]["stopped"]
                        result = {
                            "format": "current-application-post-migration-smoke/1",
                            "activation": activation,
                            "source_system_identifier": source.system_identifier,
                            "target_system_identifier": target["system_identifier"],
                            "old_cookie_rejected": True,
                            "new_login_verified": True,
                            "bid_and_nonempty_draft_read": True,
                            "original_artifact": artifact,
                            "csrf_enforced": True,
                            "new_keys_rotated": True,
                            "idempotent_settings_write_once": True,
                            "api_login": api_login,
                            "api_nonowner_high_privileges_false": True,
                            "backup_reader_remains_readonly": True,
                            "api_processes": processes,
                            "workers_started": False,
                            "model_calls": 0,
                            "full_application_restore_qualified": False,
                            "production_rpo_rto_qualified": False,
                        }
                    assert (
                        restored["source_unchanged"] and restored["new_database_and_bucket_removed"]
                    )
                    result.update(
                        source_unchanged=True, new_target_database_and_bucket_removed=True
                    )
            assert all(record["stopped"] for record in processes)
    finally:
        if directory.exists():
            run.private_archive(directory, existing=True)
            shutil.rmtree(directory)
        for path in [
            base,
            run.ROOT / ".local" / (name + "-init.env"),
            run.ROOT / ".local" / (name + "-checks.env"),
        ]:
            if path.exists():
                assert path.parent == run.ROOT / ".local" and not path.is_symlink()
                path.unlink()
    assert (
        result is not None and len(cleanup) == 2 and all(all(record.values()) for record in cleanup)
    )
    result["owned_source_target_cluster_cleanup"] = cleanup
    proof("api-smoke", result)
