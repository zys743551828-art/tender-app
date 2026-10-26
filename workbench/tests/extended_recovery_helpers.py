"""Real local recovery fixture orchestration; all domain content is synthetic."""

import json
import os
import secrets
import shutil
from pathlib import Path
from uuid import uuid4

import boto3
import psycopg
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from psycopg import sql
from psycopg.conninfo import make_conninfo

from deploy import bootstrap_fresh, completion_recovery
from deploy import extended_recovery as recovery
from deploy.application_recovery import archive as definitions
from deploy.backups import generic, run
from packages.domain import storage

REAL_STORAGE_CLIENT = storage.client
REAL_STORAGE_BUCKET = storage.bucket


def install_remaining(owner, installed):
    plan = recovery.frozen_plan()
    for item in plan:
        if item.path not in installed:
            owner.execute(item.content.decode())
    return plan


def s3(*, admin=False):
    return boto3.client(
        "s3",
        endpoint_url=os.environ["OBJECT_STORE_ENDPOINT"],
        aws_access_key_id=os.environ[
            "FUSION_EXTENDED_RECOVERY_S3_ADMIN_ACCESS_KEY" if admin else "OBJECT_STORE_ACCESS_KEY"
        ],
        aws_secret_access_key=os.environ[
            "FUSION_EXTENDED_RECOVERY_S3_ADMIN_SECRET_KEY" if admin else "OBJECT_STORE_SECRET_KEY"
        ],
        region_name=os.environ["OBJECT_STORE_REGION"],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=10,
            retries={"max_attempts": 0},
            proxies={},
        ),
    )


def identity(c):
    return definitions.detail(c, {"accounts": {"owner": {"user": c.info.user}}})


def proof(label, value):
    destination = os.environ.get("FUSION_EXTENDED_RECOVERY_REPORT_DIR")
    if destination:
        temporary = Path(destination) / (label + "-proof-" + uuid4().hex + ".tmp")
        run.private_write(
            temporary,
            json.dumps(value, ensure_ascii=False, indent=2).encode(),
        )
        os.replace(temporary, Path(destination) / (label + "-proof.json"))


def drill(database, label, expected_nonempty, *, synthetic_original=None, extra_login_dsn=None):
    owner = database["owner"]
    admin_dsn = os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"]
    owner_dsn = make_conninfo(admin_dsn, dbname=owner.info.dbname)
    api_dsn = database["api_dsn"]
    client, bucket = s3(), os.environ["OBJECT_STORE_BUCKET"]
    reader = "extended_backup_reader_" + uuid4().hex[:16]
    password = secrets.token_urlsafe(36)
    owner.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(sql.Identifier(reader), sql.Literal(password))
    )
    with psycopg.connect(owner_dsn) as c:
        description = generic.catalog(c)
    for name in description["schemas"]:
        schema = sql.Identifier(name)
        owner.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, sql.Identifier(reader))
        )
        owner.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                schema, sql.Identifier(reader)
            )
        )
        owner.execute(
            sql.SQL("GRANT SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                schema, sql.Identifier(reader)
            )
        )
    reader_dsn = make_conninfo(owner_dsn, user=reader, password=password)
    tool = recovery.local_tool(
        os.environ["FUSION_EXTENDED_RECOVERY_PG_BIN"],
        os.environ.get("FUSION_EXTENDED_RECOVERY_PG_LIBRARY_DIR"),
    )
    directory = run.ARCHIVE_ROOT / ("extended-" + uuid4().hex)
    run.ARCHIVE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = None
    restored_objects = None
    with psycopg.connect(owner_dsn) as c:
        before_definition = identity(c)
        before_memberships = c.execute(
            "SELECT roleid::regrole::text,member::regrole::text,admin_option,inherit_option,set_option FROM pg_auth_members ORDER BY 1,2"
        ).fetchall()
    if synthetic_original is not None:
        for row in owner.execute(
            "SELECT object_key,digest,byte_size,media_type FROM design.blobs ORDER BY id"
        ).fetchall():
            assert row["digest"] == run.digest(synthetic_original) and row["byte_size"] == len(
                synthetic_original
            )
            client.put_object(
                Bucket=bucket,
                Key=row["object_key"],
                Body=synthetic_original,
                ContentType=row["media_type"],
            )
    late_id = str(uuid4())
    actor = owner.execute("SELECT id FROM design.members ORDER BY id LIMIT 1").fetchone()["id"]

    def late_commit():
        with psycopg.connect(api_dsn) as c:
            c.execute(
                "INSERT INTO design.audit_entries(id,actor_id,event_type,payload) VALUES(%s,%s,'extended.recovery.concurrent',%s)",
                (late_id, actor, "{}"),
            )

    try:
        manifest = recovery.snapshot(
            {"API_DATABASE_DSN": reader_dsn, "OWNER_DATABASE_DSN": owner_dsn},
            directory,
            recovery.frozen_plan(),
            tool=tool,
            after_snapshot=late_commit,
        )
        found = {(item["schema"], item["name"]): item["rows"] for item in manifest["tables"]}
        assert all(found.get(tuple(name.split(".", 1)), 0) > 0 for name in expected_nonempty), {
            name: found.get(tuple(name.split(".", 1)), 0) for name in expected_nonempty
        }
        originals = completion_recovery.archive_originals(directory, manifest, client, bucket)
        assert originals["objects"]
        with psycopg.connect(reader_dsn) as c:
            source_after_late = generic.inventory(c)
        first = originals["objects"][0]
        path = directory / first["file"]
        raw = path.read_bytes()
        path.write_bytes(raw + b"corrupt")
        with psycopg.connect(admin_dsn) as c:
            databases_before = c.execute(
                "SELECT datname FROM pg_database ORDER BY datname"
            ).fetchall()
        with pytest.raises(run.BackupError, match="ORIGINAL_BYTES_CHANGED"):
            recovery.restore_database(
                {"API_DATABASE_DSN": api_dsn, "OWNER_DATABASE_DSN": owner_dsn}, directory, tool=tool
            )
        with psycopg.connect(admin_dsn) as c:
            assert (
                c.execute("SELECT datname FROM pg_database ORDER BY datname").fetchall()
                == databases_before
            )
        path.write_bytes(raw)
        receipt = recovery.restore_database(
            {"API_DATABASE_DSN": api_dsn, "OWNER_DATABASE_DSN": owner_dsn}, directory, tool=tool
        )
        target = receipt["database"]
        admin_client = s3(admin=True)
        restored_objects = recovery.restore_objects(directory, admin_client, bucket)
        assert restored_objects["database_manifest_sha256"] == generic.hash_file(
            directory / "manifest.json"
        )
        get_requests = []

        def real_target_client():
            port = REAL_STORAGE_CLIENT()
            port.meta.events.register(
                "before-parameter-build.s3.GetObject",
                lambda params, **_: get_requests.append((params["Bucket"], params["Key"])),
            )
            return port

        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("OBJECT_STORE_BUCKET", restored_objects["target_bucket"])
            patch.setenv(
                "OBJECT_STORE_ACCESS_KEY",
                os.environ["FUSION_EXTENDED_RECOVERY_S3_READER_ACCESS_KEY"],
            )
            patch.setenv(
                "OBJECT_STORE_SECRET_KEY",
                os.environ["FUSION_EXTENDED_RECOVERY_S3_READER_SECRET_KEY"],
            )
            patch.setattr(storage, "client", real_target_client)
            patch.setattr(storage, "bucket", REAL_STORAGE_BUCKET)
            with psycopg.connect(make_conninfo(api_dsn, dbname=target)) as c:
                target_references = c.execute(
                    "SELECT id::text,object_key,digest::text,byte_size FROM design.blobs ORDER BY id"
                ).fetchall()
            expected = {item["id"]: item for item in originals["objects"]}
            for blob_id, key, digest, size in target_references:
                actual = storage.get(key)
                assert key == expected[blob_id]["key"]
                assert run.digest(actual) == digest and len(actual) == size
                assert actual == (directory / expected[blob_id]["file"]).read_bytes()
            assert get_requests == [
                (restored_objects["target_bucket"], row[1]) for row in target_references
            ]
            with pytest.raises(ClientError) as denied:
                REAL_STORAGE_CLIENT().put_object(
                    Bucket=restored_objects["target_bucket"],
                    Key="forbidden-write",
                    Body=b"must not exist",
                )
            assert denied.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403
            with pytest.raises(ClientError) as denied_delete:
                REAL_STORAGE_CLIENT().delete_object(
                    Bucket=restored_objects["target_bucket"], Key=target_references[0][1]
                )
            assert denied_delete.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403
        with psycopg.connect(
            make_conninfo(api_dsn, dbname=target, options="-c default_transaction_read_only=off")
        ) as c:
            assert c.execute(
                "SELECT count(*) FROM design.audit_entries WHERE id=%s", (late_id,)
            ).fetchone() == (0,)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("UPDATE design.members SET display_name=display_name WHERE false")
        if extra_login_dsn is not None:
            with psycopg.connect(extra_login_dsn) as c:
                assert c.execute("SELECT current_database()").fetchone() == (owner.info.dbname,)
            with pytest.raises(psycopg.Error):
                psycopg.connect(make_conninfo(extra_login_dsn, dbname=target))
        with psycopg.connect(owner_dsn) as c:
            assert identity(c) == before_definition
            assert (
                c.execute(
                    "SELECT roleid::regrole::text,member::regrole::text,admin_option,inherit_option,set_option FROM pg_auth_members ORDER BY 1,2"
                ).fetchall()
                == before_memberships
            )
        with psycopg.connect(reader_dsn) as c:
            assert generic.inventory(c) == source_after_late
            assert c.execute(
                "SELECT count(*) FROM design.audit_entries WHERE id=%s", (late_id,)
            ).fetchone() == (1,)
        for item in originals["objects"]:
            assert (
                run.read_object(client, bucket, item["key"], item["bytes"], item["sha256"])
                == (directory / item["file"]).read_bytes()
            )
        result = {
            "format": recovery.FORMAT,
            "case": label,
            "ordered_sql": completion_recovery.plan_receipt(recovery.frozen_plan()),
            "table_count": len(manifest["tables"]),
            "nonempty_table_count": sum(item["rows"] > 0 for item in manifest["tables"]),
            "required_nonempty_tables": sorted(expected_nonempty),
            "schema_names": manifest["catalog"]["schemas"],
            "definition_counts": {key: len(value) for key, value in before_definition.items()},
            "quarantined_role_count": len(receipt["quarantined_roles"]),
            "objects": len(originals["objects"]),
            "object_bytes": sum(item["bytes"] for item in originals["objects"]),
            "actual_pg17_dump_restore_and_s3": True,
            "target_database_keys_read_through_actual_domain_storage_from_new_bucket": True,
            "application_object_binding_verified": True,
            "target_object_reader_write_permission_denied": True,
            "target_object_reader_delete_permission_denied": True,
            "source_and_target_objects_in_distinct_buckets": True,
            "immutable_database_keys_and_rows_preserved": True,
            "complete_definition_acl_and_row_hashes_preserved": True,
            "exact_authoring_qualification_view_sha256_verified": receipt[
                "exact_authoring_qualification_view_sha256_verified"
            ],
            "same_snapshot_excludes_concurrent_commit": True,
            "corrupt_original_blocks_before_database_creation": True,
            "source_acl_memberships_rows_and_original_bytes_unchanged": True,
            "readonly_target_rejects_update_when_readonly_default_disabled": True,
            "dedicated_runtime_login_connect_denied": extra_login_dsn is not None,
            "synthetic_business_data_only": True,
            "real_provider_calls": 0,
            "restored_consumer_started": False,
            "old_queue_resume_qualified": False,
            "full_application_restore_qualified": False,
            "native_oss_qualified": False,
            "production_rpo_rto_qualified": False,
        }
        proof(label, result)
        return result
    finally:
        targets = {
            json.loads(path.read_text())["database"]
            for path in directory.glob("restore-attempt-*.json")
        }
        if target is not None:
            targets.add(target)
        with psycopg.connect(admin_dsn, autocommit=True) as c:
            for target in targets:
                c.execute(sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(target)))
        object_attempts = [
            json.loads(path.read_text()) for path in directory.glob("object-restore-attempt-*.json")
        ]
        for restored_objects in object_attempts:
            for item in originals["objects"]:
                s3(admin=True).delete_object(
                    Bucket=restored_objects["target_bucket"], Key=item["key"]
                )
            s3(admin=True).delete_bucket(Bucket=restored_objects["target_bucket"])
        owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(reader)))
        owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(reader)))
        if directory.exists() and os.environ.get("FUSION_EXTENDED_RECOVERY_KEEP_FAILURE") != "1":
            shutil.rmtree(directory)


BASE = set(bootstrap_fresh.BASE_SQL)
