"""Current schema + native PG17 + actual loopback S3; no shared PG or paid calls.

Creates a separate disposable cluster, two distinct databases and two synthetic
S3 buckets. F04/F05 native records are made through their actual services first.
"""
# ruff: noqa: F401,F811

import json
import os
import pwd
import secrets
import shutil
import socket
import subprocess  # nosec B404
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from botocore.exceptions import ClientError
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_bid_package_rule_corrections_pg import RAW, api, apply, exact, requirements, world

from apps.api.views import bid_etag
from deploy import completion_recovery as recovery
from deploy.application_recovery import archive as application_archive
from deploy.backups import generic, run
from packages.domain import bid_package_submissions as submissions
from packages.domain import storage
from packages.domain.runtime import connection, sha

PG_BIN = os.environ.get("FUSION_COMPLETION_RECOVERY_PG_BIN")
PROFILE = os.environ.get("FUSION_TRANSPORT_PROFILE")
pytestmark = pytest.mark.skipif(
    not PG_BIN or not PROFILE,
    reason="explicit disposable native PG17 and synthetic loopback S3 profile required",
)


@pytest.fixture(scope="module")
def native_cluster():
    plan, configuration = recovery.frozen_plan(), recovery.synthetic_s3(PROFILE)
    directory = Path(tempfile.mkdtemp(prefix="tender-completion-recovery-"))
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
    os.chown(directory, account.pw_uid, account.pw_gid)
    password = secrets.token_urlsafe(36)
    password_file = directory / "initial-password"
    run.private_write(password_file, password.encode())
    os.chown(password_file, account.pw_uid, account.pw_gid)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert port != 55441
    owner_name = "completion_owner_" + uuid4().hex[:16]
    environment = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}

    def native(tool, arguments):
        result = subprocess.run(  # nosec B603
            [str(Path(PG_BIN) / tool), *arguments],
            env=environment,
            user=account.pw_uid,
            group=account.pw_gid,
            extra_groups=[],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise AssertionError("self-owned native PG process failed: " + tool)

    started = False
    try:
        native(
            "initdb",
            [
                "-D",
                str(directory / "data"),
                "-U",
                owner_name,
                "--pwfile=" + str(password_file),
                "--auth-host=scram-sha-256",
                "--auth-local=scram-sha-256",
                "--encoding=UTF8",
                "--no-locale",
            ],
        )
        native(
            "pg_ctl",
            [
                "-D",
                str(directory / "data"),
                "-l",
                str(directory / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {port} -k {directory} -c shared_buffers=32MB -c max_connections=30 -c max_wal_size=128MB",
                "-w",
                "-t",
                "15",
                "start",
            ],
        )
        started = True
        admin_dsn = make_conninfo(
            host="127.0.0.1", port=port, dbname="postgres", user=owner_name, password=password
        )
        with psycopg.connect(admin_dsn) as c:
            server_version = c.execute("SHOW server_version").fetchone()[0]
        yield {
            "admin_dsn": admin_dsn,
            "owner_name": owner_name,
            "plan": plan,
            "configuration": configuration,
            "server_version": server_version,
        }
    finally:
        if started:
            native("pg_ctl", ["-D", str(directory / "data"), "-m", "fast", "-w", "stop"])
        shutil.rmtree(directory)


@pytest.fixture(scope="module")
def database(native_cluster):
    name = "completion_source_" + uuid4().hex
    owner_dsn = make_conninfo(native_cluster["admin_dsn"], dbname=name)
    with psycopg.connect(native_cluster["admin_dsn"], autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    with psycopg.connect(owner_dsn, autocommit=True, row_factory=dict_row) as owner:
        for item in native_cluster["plan"]:
            owner.execute(item.content.decode())
        roles = {}
        for kind, role, group in (
            ("api", "fusion_package_requirements_service", "tender_api"),
            ("worker", "fusion_package_requirements_worker", "tender_worker"),
            ("reader", "completion_backup_reader", None),
        ):
            password = secrets.token_urlsafe(36)
            owner.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            if group:
                owner.execute(
                    sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(role))
                )
            roles[kind + "_dsn"] = make_conninfo(owner_dsn, user=role, password=password)
        for row in owner.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname<>'information_schema'"
        ).fetchall():
            namespace = sql.Identifier(row["nspname"])
            owner.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO completion_backup_reader").format(namespace)
            )
            owner.execute(
                sql.SQL(
                    "GRANT SELECT ON ALL TABLES IN SCHEMA {} TO completion_backup_reader"
                ).format(namespace)
            )
            owner.execute(
                sql.SQL(
                    "GRANT SELECT ON ALL SEQUENCES IN SCHEMA {} TO completion_backup_reader"
                ).format(namespace)
            )
        owner.execute("ALTER ROLE completion_backup_reader SET default_transaction_read_only=on")
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("WORKBENCH_ENV_FILE", "explicit-current-recovery-no-business-profile")
            patch.setenv("APP_ORIGIN", "http://identity-v2.test")
            patch.setenv("SESSION_SECRET", secrets.token_urlsafe(36))
            patch.setenv("CSRF_SECRET", secrets.token_urlsafe(36))
            patch.setenv("API_DATABASE_DSN", roles["api_dsn"])
            yield {
                "owner": owner,
                "owner_dsn": owner_dsn,
                "name": name,
                "native": native_cluster,
                **roles,
            }


def definition(c, database):
    return application_archive.detail(
        c, {"accounts": {"owner": {"user": database["native"]["owner_name"]}}}
    )


def column_writes(c):
    return c.execute(
        "SELECT n.nspname,t.relname,a.attname FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=t.oid WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' "
        "AND t.relkind IN('r','p','v','m') AND a.attnum>0 AND NOT a.attisdropped "
        "AND has_column_privilege(current_user,t.oid,a.attnum,'INSERT,UPDATE,REFERENCES') ORDER BY 1,2,3"
    ).fetchall()


def save_package_fact(w, corrected):
    selected = {
        "package_id": w["own"]["manifest"]["package_id"],
        "revision_id": w["own"]["manifest"]["revision_id"],
        "package_digest": w["own"]["digest"],
        "inventory": {"id": corrected["manifest"]["id"], "digest": corrected["digest"]},
        "coverage": None,
        "review_run": None,
    }
    scope = (w["scope"].bid_id, selected["package_id"], selected["revision_id"])
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        preview = submissions.prepare(c, scope, selected, bid_etag_fn=bid_etag)
    body = {
        "kind": "offline_fact",
        "selection": selected,
        "input_digest": preview["input_digest"],
        "evidence": {
            "document_version_id": w["member"].document_version_id,
            "digest": sha(RAW),
            "byte_size": len(RAW),
        },
        "submitted_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "explanation": "Synthetic recovery fixture; declared package fact, not platform proof.",
        "expected_head": None,
        "correction_reason": None,
    }
    saved, replay = submissions.register(
        scope, w["actor"], str(uuid4()), body, preview["bid_etag"], bid_etag_fn=bid_etag
    )
    assert not replay and saved["status"] == 201
    return saved["body"]["submission"]


@pytest.fixture
def recovered(exact, monkeypatch):
    w, database = exact, exact["database"]
    correction = apply(w)
    assert correction.status_code == 201, correction.text
    saved_submission = save_package_fact(w, correction.json()["inventory"])
    client = recovery.s3_client(database["native"]["configuration"])
    source_bucket, target_bucket = ("completion-recovery-" + uuid4().hex for _ in range(2))
    created_buckets, objects_by_bucket = [], {source_bucket: set(), target_bucket: set()}
    directory = run.ARCHIVE_ROOT / ("completion-current-" + uuid4().hex)
    run.ARCHIVE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipts = []
    try:
        for bucket in (source_bucket, target_bucket):
            client.create_bucket(Bucket=bucket)
            created_buckets.append(bucket)
        payloads = {}
        for row in (
            database["owner"]
            .execute(
                "SELECT id,object_key,digest,byte_size,media_type FROM design.blobs ORDER BY id"
            )
            .fetchall()
        ):
            raw = RAW if row["digest"] == sha(RAW) else storage.get(row["object_key"])
            assert sha(raw) == row["digest"] and len(raw) == row["byte_size"]
            payloads[row["object_key"]] = raw
            objects_by_bucket[source_bucket].add(row["object_key"])
            client.put_object(
                Bucket=source_bucket, Key=row["object_key"], Body=raw, ContentType=row["media_type"]
            )
        with psycopg.connect(database["reader_dsn"]) as c:
            assert generic.restricted(c) == "completion_backup_reader"
            assert not column_writes(c)
            source_definition = definition(c, database)
        with psycopg.connect(database["api_dsn"]) as c:
            assert column_writes(c), "fixture must contain current column grants"

        def pg_tool(container, tool, dsn, args, **kwargs):
            result = recovery.local_pg_tool(PG_BIN, container, tool, dsn, args, **kwargs)
            if tool == "pg_restore":
                with psycopg.connect(dsn) as c:
                    restored_definition = definition(c, database)
                differences = {
                    key: [
                        [left, right]
                        for left, right in zip(
                            source_definition[key], restored_definition[key], strict=True
                        )
                        if left != right
                    ]
                    for key in source_definition
                    if source_definition[key] != restored_definition[key]
                }
                if differences:
                    run.private_write(
                        directory / "definition-differences.json",
                        json.dumps(differences, indent=2).encode(),
                    )
                assert recovery.equivalent_definitions(source_definition, restored_definition), str(
                    directory / "definition-differences.json"
                )
                receipts.append(
                    {"full_definitions_and_acl_preserved_before_offline_hardening": True}
                )
            return result

        monkeypatch.setattr(run, "pg_tool", pg_tool)
        late_id = str(uuid4())

        def late_commit():
            with connection() as c:
                c.execute(
                    "INSERT INTO design.audit_entries(id,actor_id,bid_id,event_type,payload) VALUES(%s,%s,%s,'completion.recovery.late_commit','{}')",
                    (late_id, w["actor"], w["scope"].bid_id),
                )

        manifest = generic.snapshot(
            {"API_DATABASE_DSN": database["reader_dsn"]},
            directory,
            "explicit-local-pg17",
            after_snapshot=late_commit,
        )
        with psycopg.connect(database["reader_dsn"]) as c:
            source_after_snapshot = generic.inventory(c)
            assert c.execute(
                "SELECT count(*) FROM design.audit_entries WHERE id=%s", (late_id,)
            ).fetchone() == (1,)
        originals = recovery.archive_originals(directory, manifest, client, source_bucket)
        assert recovery.validate_originals(directory) == originals
        values = {
            "API_DATABASE_DSN": database["api_dsn"],
            "OWNER_DATABASE_DSN": database["owner_dsn"],
        }
        receipt = generic.restore(values, directory, "explicit-local-pg17")
        assert (
            receipt["database"] != database["name"]
            and receipt["status"] == "passed_database_component_only"
        )
        objects_by_bucket[target_bucket].update(payloads)
        assert recovery.restore_originals(directory, client, target_bucket) == len(
            manifest["objects"]
        )
        target_dsn = make_conninfo(database["api_dsn"], dbname=receipt["database"])
        with psycopg.connect(target_dsn) as c:
            assert generic.restricted(c) == "fusion_package_requirements_service"
            assert c.execute("SHOW transaction_read_only").fetchone() == ("on",)
            assert generic.inventory(c) == manifest["tables"]
            assert c.execute(
                "SELECT count(*) FROM design.audit_entries WHERE id=%s", (late_id,)
            ).fetchone() == (0,)
            assert not column_writes(c), "offline recovery must also revoke column grants"
            assert (
                c.execute("SELECT count(*) FROM design.bid_package_rule_corrections").fetchone()[0]
                >= 1
            )
            assert (
                c.execute("SELECT count(*) FROM design.bid_package_submission_bindings").fetchone()[
                    0
                ]
                >= 1
            )
        yield {
            "database": database,
            "directory": directory,
            "manifest": manifest,
            "originals": originals,
            "client": client,
            "source_bucket": source_bucket,
            "target_bucket": target_bucket,
            "target_dsn": target_dsn,
            "receipt": receipt,
            "definitions": source_definition,
            "proofs": receipts,
            "payloads": payloads,
            "saved_submission": saved_submission,
            "source_after_snapshot": source_after_snapshot,
        }
    finally:
        for bucket in created_buckets:
            for key in objects_by_bucket[bucket]:
                client.delete_object(Bucket=bucket, Key=key)
            client.delete_bucket(Bucket=bucket)


def failure_controls(r):
    first = r["originals"]["objects"][0]
    raw = r["payloads"][first["key"]]
    with pytest.raises(ClientError) as denied:
        recovery.s3_client(r["database"]["native"]["configuration"], wrong_secret=True).get_object(
            Bucket=r["source_bucket"], Key=first["key"]
        )
    assert denied.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403
    path = r["directory"] / first["file"]
    path.write_bytes(raw + b"corrupt")
    with pytest.raises(run.BackupError, match="ORIGINAL_BYTES_CHANGED"):
        recovery.validate_originals(r["directory"])
    path.write_bytes(raw)
    hidden = path.with_suffix(".missing")
    path.rename(hidden)
    try:
        with pytest.raises(run.BackupError, match="FILE_MISSING"):
            recovery.validate_originals(r["directory"])
    finally:
        hidden.rename(path)
    r["client"].put_object(Bucket=r["target_bucket"], Key=first["key"], Body=raw + b"corrupt")
    with pytest.raises(run.BackupError, match="CHECKSUM_MISMATCH"):
        run.read_object(
            r["client"], r["target_bucket"], first["key"], first["bytes"], first["sha256"]
        )
    r["client"].delete_object(Bucket=r["target_bucket"], Key=first["key"])
    with pytest.raises(ClientError) as missing:
        run.read_object(
            r["client"], r["target_bucket"], first["key"], first["bytes"], first["sha256"]
        )
    assert missing.value.response["ResponseMetadata"]["HTTPStatusCode"] == 404
    r["client"].put_object(
        Bucket=r["target_bucket"], Key=first["key"], Body=raw, ContentType=first["media_type"]
    )
    component = r["directory"].parent / ("completion-incomplete-" + uuid4().hex)
    component.mkdir(mode=0o700)
    (component / "objects").mkdir(mode=0o700)
    for name in ("database.dump", "manifest.json", "manifest.sha256"):
        shutil.copyfile(r["directory"] / name, component / name)
        (component / name).chmod(0o600)
    try:
        r["client"].put_object(Bucket=r["source_bucket"], Key=first["key"], Body=raw + b"corrupt")
        with pytest.raises(run.BackupError, match="CHECKSUM_MISMATCH"):
            recovery.archive_originals(component, r["manifest"], r["client"], r["source_bucket"])
        assert not (component / "originals.json").exists()
        r["client"].delete_object(Bucket=r["source_bucket"], Key=first["key"])
        with pytest.raises(ClientError) as missing_source:
            recovery.archive_originals(component, r["manifest"], r["client"], r["source_bucket"])
        assert missing_source.value.response["ResponseMetadata"]["HTTPStatusCode"] == 404
        assert not (component / "originals.json").exists()
    finally:
        r["client"].put_object(
            Bucket=r["source_bucket"], Key=first["key"], Body=raw, ContentType=first["media_type"]
        )
        shutil.rmtree(component)


def test_latest_complete_schema_rows_acl_originals_and_failure_controls(recovered):
    r = recovered
    with psycopg.connect(r["database"]["native"]["admin_dsn"]) as c:
        databases = c.execute("SELECT datname FROM pg_database ORDER BY datname").fetchall()
    with psycopg.connect(
        make_conninfo(r["target_dsn"], options="-c default_transaction_read_only=off")
    ) as c:
        assert not column_writes(c)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "UPDATE retrieval.knowledge_index_heads SET desired_index_id=desired_index_id WHERE false"
            )
    with psycopg.connect(r["target_dsn"], row_factory=dict_row) as c:
        assert (
            submissions.load(c, r["saved_submission"]["bid_id"], r["saved_submission"]["id"])
            == r["saved_submission"]
        )
    failure_controls(r)
    for item in r["originals"]["objects"]:
        for bucket in (r["source_bucket"], r["target_bucket"]):
            assert (
                run.read_object(r["client"], bucket, item["key"], item["bytes"], item["sha256"])
                == r["payloads"][item["key"]]
            )
    with psycopg.connect(r["database"]["native"]["admin_dsn"]) as c:
        assert c.execute("SELECT datname FROM pg_database ORDER BY datname").fetchall() == databases
    with psycopg.connect(r["database"]["reader_dsn"]) as c:
        assert generic.inventory(c) == r["source_after_snapshot"]
    with psycopg.connect(r["database"]["api_dsn"]) as c:
        assert column_writes(c), "source runtime privileges must remain unchanged"
    proof = {
        "format": "completion-current-schema-recovery-receipt/1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "ordered_sql": recovery.plan_receipt(r["database"]["native"]["plan"]),
        "source_files": {
            path: generic.hash_file(run.ROOT / path)
            for path in (
                "deploy/schema_plan.py",
                "deploy/completion_recovery.py",
                "deploy/completion_recovery_runtime.py",
                "deploy/backups/generic.py",
                "deploy/backups/run.py",
                "deploy/application_recovery/archive.py",
                "deploy/application_recovery/definition_equivalence.py",
                "tests/test_completion_recovery.py",
                "tests/test_completion_recovery_pg.py",
            )
        },
        "pg_server_version": r["database"]["native"]["server_version"],
        "pg_binary_sha256": {
            name: generic.hash_file(Path(PG_BIN) / name)
            for name in ("postgres", "initdb", "pg_dump", "pg_restore")
        },
        "extensions": r["manifest"]["catalog"]["extensions"],
        "schemas": r["manifest"]["catalog"]["schemas"],
        "tables": len(r["manifest"]["tables"]),
        "nonempty_tables": sum(item["rows"] > 0 for item in r["manifest"]["tables"]),
        "all_table_rows_sha256_verified": True,
        "definitions_counts": {key: len(value) for key, value in r["definitions"].items()},
        "all_definitions_and_acl_preserved_before_hardening": len(r["proofs"]) == 1,
        "read_only_nonowner_login_verified": True,
        "table_and_column_write_privileges_removed": True,
        "real_column_update_with_read_only_disabled_denied": True,
        "f04_native_correction_rows_and_f05_native_binding_restored": True,
        "f05_historical_service_response_unchanged": True,
        "concurrent_commit_excluded": True,
        "originals": len(r["originals"]["objects"]),
        "original_bytes": sum(item["bytes"] for item in r["originals"]["objects"]),
        "real_loopback_s3_sha256_and_size_verified": True,
        "failure_controls": [
            "wrong_s3_secret_403",
            "corrupt_archive_original",
            "missing_archive_original",
            "corrupt_restored_object",
            "missing_restored_object_404",
            "corrupt_source_original_prevents_archive_completion",
            "missing_source_original_404_prevents_archive_completion",
        ],
        "source_database": r["database"]["name"],
        "target_database": r["receipt"]["database"],
        "same_disposable_pg_cluster_distinct_databases": True,
        "source_and_target_objects_distinct_buckets": True,
        "source_rows_original_bytes_and_runtime_privileges_unchanged": True,
        "private_archive": str(r["directory"].relative_to(run.ROOT)),
        "database_archive_sha256": r["manifest"]["database_sha256"],
        "database_manifest_sha256": generic.hash_file(r["directory"] / "manifest.json"),
        "originals_manifest_sha256": generic.hash_file(r["directory"] / "originals.json"),
        "model_calls": 0,
        "consumer_started": False,
        "old_queue_resume_qualified": False,
        "native_oss_qualified": False,
        "full_application_restore_qualified": False,
        "production_rpo_rto_qualified": False,
    }
    raw = json.dumps(proof, ensure_ascii=False, indent=2).encode()
    run.private_write(r["directory"] / "completion-proof.json", raw)
    if output := os.environ.get("FUSION_COMPLETION_RECOVERY_RECEIPT"):
        run.private_write(Path(output), raw)
