"""Extended-schema, complete-byte offline recovery; never resume application traffic.

This successor binds a catalog snapshot to all B1–B5 and native material SQL,
captures definitions in the same exported snapshot, and quarantines every
database-local ACL grantee (including new purpose-specific workers). The old
backup formats and their evidence are not rewritten or promoted.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess  # nosec B404
from pathlib import Path
from uuid import uuid4

import psycopg
from botocore.exceptions import ClientError
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from deploy import (
    authoring_candidate,
    bootstrap_fresh,
    completion_recovery,
    prediction_recovery_profile,
)
from deploy.application_recovery import archive as definitions
from deploy.backups import generic, run

FORMAT = "tender-extended-offline-recovery/1"
REQUIRED_RELATIONS = tuple("design." + name for name in authoring_candidate.TABLES) + (
    "technical_material_store.objects",
    "technical_material_store.records",
    "material_judgment_job.jobs",
    "material_judgment_job.outbox",
    "material_preparation.leases",
    "material_execution.attempts",
    "material_execution.outcomes",
    "material_dispatch.leases",
    "material_dispatch.states",
    "material_dispatch.results",
)
DERIVED_VIEWS = {
    "relations": [{"schema": "design", "name": "authoring_exact_revision_records", "kind": "v"}]
}
MATERIAL_SQL = (
    "deploy/sql/package-current-scope-runtime.sql",
    "deploy/sql/package-current-original-runtime.sql",
    "deploy/sql/package-current-source-grants.sql",
    "deploy/sql/package-material-registration.sql",
    "deploy/sql/package-scope-review-issuers.sql",
    "deploy/sql/package-native-material-store.sql",
    "deploy/sql/package-native-evidence-registration.sql",
    "deploy/sql/package-native-evidence-issuers.sql",
    "deploy/sql/material-verification-commands.sql",
    "deploy/sql/material-verification-program.sql",
    "deploy/sql/material-input-authority.sql",
    "deploy/sql/material-input-seals.sql",
    "deploy/sql/material-cost-quotes.sql",
    "deploy/sql/material-input-renewals.sql",
    "deploy/sql/material-judgment-jobs.sql",
    "deploy/sql/material-preparation-leases.sql",
    "deploy/sql/material-execution-attempts.sql",
    "deploy/sql/material-execution-dispatch.sql",
)


def frozen_plan(*, prediction=False):
    previous = completion_recovery.frozen_plan()
    names = list(
        dict.fromkeys(
            [
                *(i.path for i in previous),
                *authoring_candidate.OPTIONAL_SQL,
                *MATERIAL_SQL,
                *(prediction_recovery_profile.SQL if prediction else ()),
            ]
        )
    )
    return tuple(bootstrap_fresh.reviewed_sql(run.ROOT / name) for name in names)


def checked_plan(plan, *, prediction=False):
    actual = frozen_plan(prediction=prediction)
    if len(plan) != len(actual) or any(
        left.path != right.path or left.sha256 != right.sha256 or left.content != right.content
        for left, right in zip(plan, actual, strict=True)
    ):
        raise run.BackupError("EXTENDED_RECOVERY_SQL_PLAN_CHANGED")
    return plan


def local_tool(binary_directory, library_directory=None):
    """Explicit local PG executables; credentials never enter argv or diagnostics."""
    binary_directory = Path(binary_directory).resolve(strict=True)
    if library_directory is not None:
        library_directory = Path(library_directory).resolve(strict=True)
        if not library_directory.is_dir():
            raise run.BackupError("EXTENDED_RECOVERY_PG_LIBRARY_REQUIRED")

    def execute(_container, tool, dsn, arguments, **kwargs):
        if tool not in {"pg_dump", "pg_restore"}:
            raise run.BackupError("POSTGRES_TOOL_INVALID")
        executable = binary_directory / tool
        fields = {
            key: str(value) for key, value in conninfo_to_dict(dsn).items() if value is not None
        }
        if (
            not executable.is_file()
            or executable.is_symlink()
            or fields.get("host") != "127.0.0.1"
            or not str(fields.get("port", "")).isdigit()
            or not 1024 < int(fields["port"]) < 65536
            or set(fields) - {"host", "port", "dbname", "user", "password", "connect_timeout"}
            or not fields.get("user")
            or not fields.get("dbname")
        ):
            raise run.BackupError("EXPLICIT_LOCAL_PG_TOOLS_REQUIRED")
        environment = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}
        environment.update(
            PGHOST="127.0.0.1",
            PGPORT=fields["port"],
            PGDATABASE=fields["dbname"],
            PGUSER=fields["user"],
            PGPASSWORD=fields.get("password", ""),
            PGCONNECT_TIMEOUT="5",
        )
        if library_directory is not None:
            environment["LD_LIBRARY_PATH"] = str(library_directory)
        result = subprocess.run(  # nosec B603
            [str(executable), *arguments],
            env=environment,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
            **kwargs,
        )
        if result.returncode:
            raise run.BackupError("EXTENDED_RECOVERY_PG_TOOL_FAILED_PRIVATE_DETAILS_SUPPRESSED")
        return result

    return execute


def _private_json(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()
    if len(raw) > generic.MAX_MANIFEST_BYTES:
        raise run.BackupError("MANIFEST_BUDGET_EXCEEDED")
    run.private_write(path, raw)
    run.private_write(path.with_suffix(".sha256"), run.digest(raw).encode())


def _role_evidence(c, owner):
    """Actual local ACL dependencies, then every non-admin transitive member."""
    roots = [
        r[0]
        for r in c.execute(
            "SELECT DISTINCT r.rolname FROM pg_shdepend d JOIN pg_roles r ON r.oid=d.refobjid "
            "WHERE d.dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) "
            "AND d.refclassid='pg_authid'::regclass AND d.deptype IN('a','r') AND r.rolname<>%s ORDER BY 1",
            (owner,),
        ).fetchall()
    ]
    rows = c.execute(
        "SELECT r.rolname,r.rolcanlogin,r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole "
        "FROM pg_roles r WHERE r.rolname<>%s AND NOT r.rolsuper AND "
        "(r.rolname=ANY(%s) OR EXISTS(SELECT FROM pg_roles base WHERE base.rolname=ANY(%s) "
        "AND pg_has_role(r.oid,base.oid,'MEMBER'))) ORDER BY r.rolname",
        (owner, roots, roots),
    ).fetchall()
    if any(any(row[2:]) for row in rows):
        raise run.BackupError("EXTENDED_RECOVERY_RUNTIME_ROLE_NOT_RESTRICTED")
    return {"acl_roots": roots, "runtime_roles": [list(row) for row in rows]}


def snapshot(
    values,
    output,
    plan,
    *,
    tool=run.pg_tool,
    container="explicit-local-pg17",
    after_snapshot=None,
    prediction=False,
    object_client=None,
    object_bucket=None,
):
    """Freeze rows, ACLs and definitions together; dump uses the same nonowner."""
    checked_plan(plan, prediction=prediction)
    run.private_archive(output, existing=False)
    output.mkdir(mode=0o700)
    (output / "objects").mkdir(mode=0o700)
    owner = str(conninfo_to_dict(values["OWNER_DATABASE_DSN"])["user"])
    with psycopg.connect(values["API_DATABASE_DSN"]) as c:
        c.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        login = generic.restricted(c)
        exported = c.execute(
            "SELECT pg_export_snapshot(),current_database(),current_setting('server_version'),clock_timestamp()"
        ).fetchone()
        if exported is None:
            raise run.BackupError("SNAPSHOT_EXPORT_FAILED")
        snap, database, version, at = exported
        if after_snapshot is not None:
            after_snapshot()
        description = generic.catalog(c)
        if c.execute(
            "SELECT count(*) FROM unnest(%s::text[]) name WHERE to_regclass(name) IS NULL",
            (
                list(REQUIRED_RELATIONS)
                + list(prediction_recovery_profile.RELATIONS if prediction else ()),
            ),
        ).fetchone() != (0,):
            raise run.BackupError("EXTENDED_RECOVERY_REQUIRED_RELATION_MISSING")
        tables = generic.inventory(c, description)
        derived_views = generic.inventory(c, DERIVED_VIEWS)
        detail = definitions.detail(c, {"accounts": {"owner": {"user": owner}}})
        roles = _role_evidence(c, owner)
        references = c.execute(
            "SELECT id::text,digest::text,object_key,byte_size,media_type FROM design.blobs ORDER BY id"
        ).fetchall()
        private_refs = prediction_recovery_profile.private_references(c) if prediction else []
        if sum(r[3] for r in references) > run.MAX_ARCHIVE_BYTES:
            raise run.BackupError("ARCHIVE_OBJECT_BUDGET_EXCEEDED")
        with (output / "database.dump").open("xb") as dump:
            os.chmod(dump.name, 0o600)
            tool(
                container,
                "pg_dump",
                values["API_DATABASE_DSN"],
                ["--format=custom", "--snapshot=" + snap, "--lock-wait-timeout=10s"],
                stdout=dump,
            )
    if prediction:
        references += prediction_recovery_profile.object_rows(
            private_refs, object_client, object_bucket, references
        )
    manifest = {
        "format": generic.FORMAT,
        "source": {
            "database": database,
            "login": login,
            "server_version": version,
            "snapshot": snap,
            "captured_at": at.isoformat(),
            "isolation": "repeatable_read_read_only",
        },
        "catalog": description,
        "tables": tables,
        "objects": [
            {"id": i, "sha256": h, "key": k, "bytes": b, "media_type": m}
            for i, h, k, b, m in references
        ],
        "objects_included": False,
        "object_store": run.locator(values),
        "database_sha256": generic.hash_file(output / "database.dump"),
    }
    _private_json(output / "manifest.json", manifest)
    _private_json(
        output / "extended.json",
        {
            "format": prediction_recovery_profile.FORMAT if prediction else FORMAT,
            "database_manifest_sha256": generic.hash_file(output / "manifest.json"),
            "ordered_sql": completion_recovery.plan_receipt(plan),
            "definitions": detail,
            "derived_views": derived_views,
            "source_owner": owner,
            "roles": roles,
            "full_application_restore_qualified": False,
            "production_rpo_rto_qualified": False,
        },
    )
    return manifest


def validate(directory):
    database = generic.validate(directory)
    for name in ("extended.json", "extended.sha256"):
        path = directory / name
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise run.BackupError("EXTENDED_RECOVERY_PRIVATE_MANIFEST_REQUIRED")
    raw = (directory / "extended.json").read_bytes()
    if (
        len(raw) > generic.MAX_MANIFEST_BYTES
        or run.digest(raw) != (directory / "extended.sha256").read_text()
    ):
        raise run.BackupError("EXTENDED_RECOVERY_MANIFEST_CHANGED")
    value = json.loads(raw)
    if (
        value.get("format") not in (FORMAT, prediction_recovery_profile.FORMAT)
        or value.get("database_manifest_sha256") != generic.hash_file(directory / "manifest.json")
        or value.get("full_application_restore_qualified") is not False
        or value.get("production_rpo_rto_qualified") is not False
        or value.get("ordered_sql")
        != completion_recovery.plan_receipt(
            frozen_plan(prediction=value.get("format") == prediction_recovery_profile.FORMAT)
        )
    ):
        raise run.BackupError("EXTENDED_RECOVERY_BINDING_CHANGED")
    return database, value


def privilege_violations(c, roles, schemas, *, reader):
    result = {}
    for role in roles:
        result[role] = c.execute(
            "SELECT "
            "(SELECT count(*) FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=ANY(%s) "
            "AND t.relkind IN('r','p','m','v') AND (has_table_privilege(%s,t.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') "
            "OR has_any_column_privilege(%s,t.oid,'INSERT,UPDATE,REFERENCES'))),"
            "(SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=ANY(%s) AND has_function_privilege(%s,p.oid,'EXECUTE')),"
            "(SELECT count(*) FROM pg_namespace n WHERE n.nspname=ANY(%s) AND has_schema_privilege(%s,n.oid,'CREATE')),"
            "(SELECT count(*) FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=ANY(%s) AND CASE WHEN t.relkind='S' THEN has_sequence_privilege(%s,t.oid,'USAGE,UPDATE') ELSE false END),"
            "has_database_privilege(%s,current_database(),'CREATE,TEMPORARY'),"
            "CASE WHEN %s=%s THEN false ELSE has_database_privilege(%s,current_database(),'CONNECT') END",
            (
                schemas,
                role,
                role,
                schemas,
                role,
                schemas,
                role,
                schemas,
                role,
                role,
                role,
                reader,
                role,
            ),
        ).fetchone()
    return {key: list(value) for key, value in result.items() if any(value)}


def quarantine(c, description, roles, database, reader):
    # Visibility of CONNECT and all restored permissions is atomic. A failed
    # proof rolls back this transaction while the fresh database stays closed.
    with c.transaction():
        _quarantine(c, description, roles, database, reader)


def restricted_reader(c, reader):
    """Local ACL revocation cannot remove global capabilities or SET ROLE to owner."""
    attributes = c.execute(
        "SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication "
        "FROM pg_roles WHERE rolname=%s",
        (reader,),
    ).fetchone()
    if attributes is None or attributes[0] is not True or any(attributes[1:]):
        raise run.BackupError("EXTENDED_RECOVERY_READER_NOT_RESTRICTED")
    privileged = c.execute(
        "SELECT EXISTS(SELECT FROM pg_roles r WHERE pg_has_role(%s,r.oid,'MEMBER') AND "
        "(left(r.rolname,3)='pg_' OR r.rolsuper OR r.rolbypassrls OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication)) "
        "OR EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND pg_has_role(%s,t.relowner,'MEMBER')) "
        "OR EXISTS(SELECT FROM pg_namespace n WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND pg_has_role(%s,n.nspowner,'MEMBER')) "
        "OR EXISTS(SELECT FROM pg_database d WHERE d.datname=current_database() AND pg_has_role(%s,d.datdba,'MEMBER'))",
        (reader, reader, reader, reader),
    ).fetchone()
    if privileged != (False,):
        raise run.BackupError("EXTENDED_RECOVERY_READER_NOT_RESTRICTED")


def _quarantine(c, description, roles, database, reader):
    restricted_reader(c, reader)
    audited_roles = sorted(set(roles) | {reader})
    names = sql.SQL(",").join(map(sql.Identifier, audited_roles))
    for schema in description["schemas"]:
        namespace = sql.Identifier(schema)
        for kind in ("TABLES", "FUNCTIONS", "SEQUENCES"):
            c.execute(
                sql.SQL("REVOKE ALL ON ALL {} IN SCHEMA {} FROM PUBLIC,{}").format(
                    sql.SQL(kind), namespace, names
                )
            )
        for table, columns in c.execute(
            "SELECT t.relname,array_agg(a.attname ORDER BY a.attnum) FROM pg_class t "
            "JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_attribute a ON a.attrelid=t.oid "
            "WHERE n.nspname=%s AND t.relkind IN('r','p','v','m') AND a.attnum>0 AND NOT a.attisdropped "
            "GROUP BY t.relname ORDER BY t.relname",
            (schema,),
        ).fetchall():
            c.execute(
                sql.SQL("REVOKE ALL({}) ON TABLE {}.{} FROM PUBLIC,{}").format(
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    namespace,
                    sql.Identifier(table),
                    names,
                )
            )
        c.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC,{}").format(namespace, names))
        c.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(namespace, sql.Identifier(reader))
        )
        c.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                namespace, sql.Identifier(reader)
            )
        )
    c.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC,{}").format(sql.Identifier(database), names)
    )
    c.execute(
        sql.SQL("ALTER DATABASE {} SET default_transaction_read_only=on").format(
            sql.Identifier(database)
        )
    )
    failures = privilege_violations(c, audited_roles, description["schemas"], reader=reader)
    if failures:
        raise run.BackupError("EXTENDED_RECOVERY_QUARANTINE_INCOMPLETE")
    c.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), sql.Identifier(reader)
        )
    )


def restore_database(values, directory, *, tool=run.pg_tool, container="explicit-local-pg17"):
    """Create one fresh, disconnected database; verify before granting read-only access."""
    manifest, extra = validate(directory)
    completion_recovery.validate_originals(directory)
    owner = {
        key: str(value)
        for key, value in conninfo_to_dict(values["OWNER_DATABASE_DSN"]).items()
        if value is not None
    }
    reader = {
        key: str(value)
        for key, value in conninfo_to_dict(values["API_DATABASE_DSN"]).items()
        if value is not None
    }
    if owner.get("user") != extra["source_owner"] or any(
        owner.get(k) != reader.get(k) for k in ("host", "port", "dbname")
    ):
        raise run.BackupError("EXTENDED_RECOVERY_INSTANCE_OR_OWNER_CHANGED")
    if owner.get("user") == reader.get("user"):
        raise run.BackupError("EXTENDED_RECOVERY_INDEPENDENT_READER_REQUIRED")
    attempt_id = uuid4().hex
    database = "tender_extended_restore_" + attempt_id
    target_owner = make_conninfo(values["OWNER_DATABASE_DSN"], dbname=database)
    target_reader = make_conninfo(values["API_DATABASE_DSN"], dbname=database)
    with psycopg.connect(values["OWNER_DATABASE_DSN"], autocommit=True) as c:
        restricted_reader(c, reader["user"])
        c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
        c.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
    _private_json(
        directory / ("restore-attempt-" + attempt_id + ".json"),
        {"database": database, "state": "new_offline_database_created"},
    )
    with (directory / "database.dump").open("rb") as dump:
        tool(
            container,
            "pg_restore",
            target_owner,
            ["--dbname=" + database, "--no-owner", "--exit-on-error", "--single-transaction"],
            stdin=dump,
            stdout=subprocess.DEVNULL,
        )
    with psycopg.connect(target_owner, autocommit=True) as c:
        description = generic.catalog(c)
        actual = definitions.detail(c, {"accounts": {"owner": {"user": extra["source_owner"]}}})
        if description != manifest["catalog"] or not completion_recovery.equivalent_definitions(
            extra["definitions"], actual
        ):
            _private_json(
                directory / "definition-difference.json",
                {"expected": extra["definitions"], "actual": actual},
            )
            raise run.BackupError("EXTENDED_RECOVERY_DEFINITION_OR_ACL_CHANGED")
        roles = sorted({r[0] for r in extra["roles"]["runtime_roles"]} | {reader["user"]})
        quarantine(c, description, roles, database, reader["user"])
    with psycopg.connect(target_reader) as c:
        c.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        generic.restricted(c)
        if (
            generic.catalog(c) != manifest["catalog"]
            or generic.inventory(c) != manifest["tables"]
            or generic.inventory(c, DERIVED_VIEWS) != extra["derived_views"]
        ):
            raise run.BackupError("EXTENDED_RECOVERY_RESTORED_ROWS_CHANGED")
    receipt = {
        "format": extra["format"],
        "database": database,
        "status": "passed_extended_offline_database",
        "tables": len(manifest["tables"]),
        "nonempty_tables": sum(t["rows"] > 0 for t in manifest["tables"]),
        "quarantined_roles": roles,
        "definitions_and_acl_preserved_before_quarantine": True,
        "all_table_rows_sha256_verified": True,
        "exact_authoring_qualification_view_sha256_verified": True,
        "all_runtime_write_and_execute_privileges_removed": True,
        "old_queue_resume_qualified": False,
        "full_application_restore_qualified": False,
        "production_rpo_rto_qualified": False,
    }
    _private_json(directory / ("restore-receipt-" + attempt_id + ".json"), receipt)
    return receipt


def restore_objects(directory, client, bucket):
    """New isolated synthetic bucket; preserve the exact immutable database keys."""
    value = completion_recovery.validate_originals(directory)
    if bucket != value["source_bucket"]:
        raise run.BackupError("EXTENDED_RECOVERY_EXPLICIT_SOURCE_BUCKET_REQUIRED")
    attempt_id = uuid4().hex
    target_bucket = "tender-extended-restore-" + attempt_id
    if target_bucket == bucket:
        raise run.BackupError("EXTENDED_RECOVERY_TARGET_MUST_BE_DISTINCT")
    try:
        client.head_bucket(Bucket=target_bucket)
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
    else:
        raise run.BackupError("EXTENDED_RECOVERY_TARGET_ALREADY_EXISTS")
    client.create_bucket(Bucket=target_bucket)
    _private_json(
        directory / ("object-restore-attempt-" + attempt_id + ".json"),
        {
            "source_bucket": bucket,
            "target_bucket": target_bucket,
            "database_manifest_sha256": generic.hash_file(directory / "manifest.json"),
            "originals_manifest_sha256": generic.hash_file(directory / "originals.json"),
            "created_new_synthetic_bucket": True,
        },
    )
    for item in value["objects"]:
        raw = (directory / item["file"]).read_bytes()
        if len(raw) != item["bytes"] or run.digest(raw) != item["sha256"]:
            raise run.BackupError("EXTENDED_RECOVERY_ORIGINAL_CHANGED_BEFORE_PUT")
        client.put_object(
            Bucket=target_bucket, Key=item["key"], Body=raw, ContentType=item["media_type"]
        )
        run.read_object(client, target_bucket, item["key"], item["bytes"], item["sha256"])
    return {
        "source_bucket": bucket,
        "target_bucket": target_bucket,
        "database_manifest_sha256": generic.hash_file(directory / "manifest.json"),
        "objects": len(value["objects"]),
        "all_original_bytes_verified": True,
        "native_oss_qualified": False,
        "full_application_restore_qualified": False,
    }
