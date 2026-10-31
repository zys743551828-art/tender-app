"""Run current extended recovery against disposable native PG17 and loopback S3."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import secrets
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
from botocore.exceptions import ClientError
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from deploy import ci_checks, completion_recovery, extended_recovery
from deploy.backups import generic, run
from deploy.ci_object_store import temporary_object_store

CASES = {
    "schema": "tests/test_extended_recovery_pg.py",
    "authoring": "tests/test_extended_recovery_authoring_pg.py",
    "material": "tests/test_extended_recovery_material_pg.py",
    "migration": "tests/test_extended_recovery_migration_runtime.py",
}


def clear_reports(directory):
    names = [
        "summary.json",
        "summary.md",
        "cleanup.json",
        "s3.log",
        "reader-rejection-proof.json",
        "api-smoke-proof.json",
    ]
    names.extend(label + suffix for label in CASES for suffix in ("-junit.xml", "-proof.json"))
    for name in names:
        (directory / name).unlink(missing_ok=True)


@contextmanager
def temporary_postgres(
    binary_directory, library_directory, environment, cleanup, *, initial_owner=None
):
    if initial_owner is not None and not re.fullmatch(
        r"extended_recovery_owner_[0-9a-f]{16}", initial_owner
    ):
        raise run.BackupError("EXTENDED_MIGRATION_INITIAL_OWNER_INVALID")
    binary_directory = binary_directory.resolve(strict=True)
    for name in ("postgres", "initdb", "pg_ctl", "pg_dump", "pg_restore"):
        path = binary_directory / name
        if not path.is_file() or path.is_symlink():
            raise run.BackupError("EXTENDED_RECOVERY_EXISTING_PG_BINARIES_REQUIRED")
    if library_directory is not None:
        library_directory = library_directory.resolve(strict=True)
        if not library_directory.is_dir():
            raise run.BackupError("EXTENDED_RECOVERY_PG_LIBRARY_REQUIRED")
    directory = Path(tempfile.mkdtemp(prefix="tender-extended-recovery-pg-"))
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
    if os.geteuid() == 0:
        os.chown(directory, account.pw_uid, account.pw_gid)
    password = secrets.token_urlsafe(36)
    password_file = directory / "initial-password"
    run.private_write(password_file, password.encode())
    if os.geteuid() == 0:
        os.chown(password_file, account.pw_uid, account.pw_gid)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    owner = initial_owner or "extended_recovery_owner_" + secrets.token_hex(8)
    child = {key: value for key, value in environment.items() if key in {"PATH", "LANG", "LC_ALL"}}
    if library_directory is not None:
        child["LD_LIBRARY_PATH"] = str(library_directory)
    identity: dict[str, Any] = (
        {"user": account.pw_uid, "group": account.pw_gid, "extra_groups": []}
        if os.geteuid() == 0
        else {}
    )

    def native(tool, arguments):
        result = subprocess.run(  # nosec B603
            [str(binary_directory / tool), *arguments],
            cwd=directory,
            env=child,
            **identity,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
            check=False,
        )
        if result.returncode:
            raise run.BackupError("EXTENDED_RECOVERY_NATIVE_PROCESS_FAILED_" + tool.upper())

    started = False
    try:
        native(
            "initdb",
            [
                "-D",
                str(directory / "data"),
                "-U",
                owner,
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
                f"-h 127.0.0.1 -p {port} -k {directory} -c timezone=UTC -c shared_buffers=32MB -c max_connections=60 -c max_wal_size=128MB",
                "-w",
                "-t",
                "20",
                "start",
            ],
        )
        started = True
        dsn = make_conninfo(
            host="127.0.0.1", port=port, dbname="postgres", user=owner, password=password
        )
        with psycopg.connect(dsn) as c:
            version = c.execute("SHOW server_version_num").fetchone()
            if version is None or not 170000 <= int(version[0]) < 180000:
                raise run.BackupError("EXTENDED_RECOVERY_PG17_REQUIRED")
        yield dsn
    finally:
        pid_file = directory / "data" / "postmaster.pid"
        if pid_file.exists():
            fields = pid_file.read_text().splitlines()
            if len(fields) < 2 or not fields[0].isdigit() or Path(fields[1]) != directory / "data":
                raise run.BackupError("EXTENDED_RECOVERY_PROCESS_IDENTITY_UNVERIFIED")
            process = Path("/proc") / fields[0]
            if process.exists():
                command = (process / "cmdline").read_bytes().split(b"\x00")
                if (
                    not command
                    or Path(os.fsdecode(command[0])).resolve() != binary_directory / "postgres"
                    or str(directory / "data").encode() not in command
                    or process.stat().st_uid != account.pw_uid
                ):
                    raise run.BackupError("EXTENDED_RECOVERY_PROCESS_IDENTITY_UNVERIFIED")
                # pg_ctl may report a startup timeout after postgres has started.
                started = True
        if started:
            native(
                "pg_ctl", ["-D", str(directory / "data"), "-m", "fast", "-w", "-t", "20", "stop"]
            )
        with socket.socket() as probe:
            closed = probe.connect_ex(("127.0.0.1", port)) != 0
        if not closed:
            raise run.BackupError("EXTENDED_RECOVERY_POSTGRES_PORT_STILL_OPEN")
        shutil.rmtree(directory)
        cleanup.append(
            {
                "postgres_stopped": True,
                "listener_closed": True,
                "private_cluster_and_password_removed": True,
            }
        )


@dataclass(frozen=True)
class MigrationSource:
    """In-memory binding to an archive just produced from this owned test cluster."""

    directory: Path
    owner: str
    reader: str
    system_identifier: str
    role_plan: dict
    fingerprints: dict
    catalog: dict
    rows: list
    definitions: dict
    values: dict = field(repr=False)
    original_bucket: str = field(repr=False)


def validated_role_plan(rows, memberships, roots, *, owner, reader):
    """Only real nonprivileged source ACL roles and their membership closure."""
    for edge in memberships:
        if (
            not isinstance(edge, (list, tuple))
            or len(edge) != 5
            or any(type(v) is not bool for v in edge[2:])
        ):
            raise run.BackupError("EXTENDED_MIGRATION_MEMBERSHIP_INVALID")
    by_name = {}
    for row in rows:
        if (
            not isinstance(row, (list, tuple))
            or len(row) != 8
            or not isinstance(row[0], str)
            or row[0] in by_name
            or any(type(v) is not bool for v in row[1:])
        ):
            raise run.BackupError("EXTENDED_MIGRATION_ROLE_METADATA_INVALID")
        by_name[row[0]] = tuple(row)
    wanted = set(roots) | {reader}
    changed = True
    while changed:
        changed = False
        for group, member, *_ in memberships:
            if member == owner:
                continue
            if group in wanted or member in wanted:
                before = len(wanted)
                wanted.update((group, member))
                changed |= len(wanted) != before
    selected = []
    for name in sorted(wanted):
        row = by_name.get(name)
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name)
            or name.startswith("pg_")
            or name == owner
            or row is None
            or any(row[3:])
        ):
            raise run.BackupError("EXTENDED_MIGRATION_PRIVILEGED_OR_UNKNOWN_ROLE")
        selected.append(list(row[:3]))
    if not by_name[reader][1]:
        raise run.BackupError("EXTENDED_MIGRATION_READER_LOGIN_REQUIRED")
    edges = []
    for edge in memberships:
        if len(edge) != 5 or any(type(v) is not bool for v in edge[2:]):
            raise run.BackupError("EXTENDED_MIGRATION_MEMBERSHIP_INVALID")
        group, member, admin, inherit, setting = edge
        if group in wanted and (member in wanted or member == owner):
            if admin and member != owner:
                raise run.BackupError("EXTENDED_MIGRATION_ROLE_ADMIN_FORBIDDEN")
            edges.append([group, member, admin, inherit, setting])
    return {"roles": selected, "memberships": sorted(edges)}


def migration_role_plan(c, extra, reader):
    rows = c.execute(
        "SELECT rolname,rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreatedb,"
        "rolcreaterole,rolreplication FROM pg_roles WHERE rolname<>%s ORDER BY rolname",
        (extra["source_owner"],),
    ).fetchall()
    memberships = c.execute(
        "SELECT r.rolname,m.rolname,a.admin_option,a.inherit_option,a.set_option "
        "FROM pg_auth_members a JOIN pg_roles r ON r.oid=a.roleid "
        "JOIN pg_roles m ON m.oid=a.member ORDER BY 1,2"
    ).fetchall()
    roots = [r[0] for r in extra["roles"]["runtime_roles"]]
    return validated_role_plan(rows, memberships, roots, owner=extra["source_owner"], reader=reader)


def cluster_identifier(c):
    if not 170000 <= int(c.execute("SHOW server_version_num").fetchone()[0]) < 180000:
        raise run.BackupError("EXTENDED_RECOVERY_PG17_REQUIRED")
    return str(c.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])


def local_migration_owner(dsn):
    fields = {key: str(value) for key, value in conninfo_to_dict(dsn).items() if value is not None}
    if (
        fields.get("host") != "127.0.0.1"
        or not fields.get("port", "").isdigit()
        or not 1024 < int(fields["port"]) < 65536
        or not re.fullmatch(r"extended_recovery_owner_[0-9a-f]{16}", fields.get("user", ""))
        or not fields.get("password")
        or set(fields) - {"host", "port", "dbname", "user", "password", "connect_timeout"}
    ):
        raise run.BackupError("EXTENDED_MIGRATION_OWNED_LOOPBACK_REQUIRED")
    return fields


@contextmanager
def migration_reader(owner_dsn):
    """Temporary read-only source archive login, never a business repair identity."""
    local_migration_owner(owner_dsn)
    reader = "extended_migration_reader_" + secrets.token_hex(8)
    password = secrets.token_urlsafe(36)
    created = False
    try:
        with psycopg.connect(owner_dsn, autocommit=True) as c:
            c.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier(reader), sql.Literal(password))
            )
            created = True
            database = c.execute("SELECT current_database()").fetchone()
            if database is None:
                raise run.BackupError("EXTENDED_MIGRATION_SOURCE_CONNECTIONS_CHANGED")
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database[0]), sql.Identifier(reader)
                )
            )
            c.execute(
                sql.SQL("ALTER ROLE {} SET default_transaction_read_only=on").format(
                    sql.Identifier(reader)
                )
            )
            for name in generic.catalog(c)["schemas"]:
                schema = sql.Identifier(name)
                c.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, sql.Identifier(reader))
                )
                c.execute(
                    sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                        schema, sql.Identifier(reader)
                    )
                )
                c.execute(
                    sql.SQL("GRANT SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                        schema, sql.Identifier(reader)
                    )
                )
        yield {
            "OWNER_DATABASE_DSN": owner_dsn,
            "API_DATABASE_DSN": make_conninfo(owner_dsn, user=reader, password=password),
        }
    finally:
        if created:
            with psycopg.connect(owner_dsn, autocommit=True) as c:
                c.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(reader)))
                c.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(reader)))


def capture_migration(values, directory, *, tool, client, bucket):
    """Create the archive here; this interface never accepts an external dump."""
    fields = local_migration_owner(values["OWNER_DATABASE_DSN"])
    reader_fields = conninfo_to_dict(values["API_DATABASE_DSN"])
    if any(fields.get(k) != reader_fields.get(k) for k in ("host", "port", "dbname")) or fields[
        "user"
    ] == reader_fields.get("user"):
        raise run.BackupError("EXTENDED_MIGRATION_SOURCE_CONNECTIONS_CHANGED")
    if directory.exists() or not re.fullmatch(r"tender-ci-authoring-[0-9a-f]+", bucket):
        raise run.BackupError("EXTENDED_MIGRATION_FRESH_SYNTHETIC_ARCHIVE_REQUIRED")
    endpoint = urlsplit(client.meta.endpoint_url)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port:
        raise run.BackupError("EXTENDED_MIGRATION_LOOPBACK_OBJECTS_REQUIRED")
    plan = extended_recovery.frozen_plan()
    manifest = extended_recovery.snapshot(values, directory, plan, tool=tool)
    completion_recovery.archive_originals(directory, manifest, client, bucket)
    _, extra = extended_recovery.validate(directory)
    reader = conninfo_to_dict(values["API_DATABASE_DSN"]).get("user")
    if not isinstance(reader, str):
        raise run.BackupError("EXTENDED_MIGRATION_READER_LOGIN_REQUIRED")
    with psycopg.connect(values["OWNER_DATABASE_DSN"]) as c:
        identity = cluster_identifier(c)
        roles = migration_role_plan(c, extra, reader)
    with psycopg.connect(values["API_DATABASE_DSN"]) as c:
        generic.restricted(c)
        catalog, rows = generic.catalog(c), generic.inventory(c)
    if rows != manifest["tables"] or not any(r["rows"] for r in rows) or not manifest["objects"]:
        raise run.BackupError("EXTENDED_MIGRATION_NONEMPTY_UNCHANGED_SOURCE_REQUIRED")
    fingerprints = {
        name: generic.hash_file(directory / name)
        for name in ("manifest.json", "extended.json", "originals.json")
    }
    return MigrationSource(
        directory,
        fields["user"],
        reader,
        identity,
        roles,
        fingerprints,
        catalog,
        rows,
        extra["definitions"],
        dict(values),
        bucket,
    )


def verify_migration_source(source):
    for name, expected in source.fingerprints.items():
        if generic.hash_file(source.directory / name) != expected:
            raise run.BackupError("EXTENDED_MIGRATION_ARCHIVE_BINDING_CHANGED")
    _, extra = extended_recovery.validate(source.directory)
    completion_recovery.validate_originals(source.directory)
    with psycopg.connect(source.values["OWNER_DATABASE_DSN"]) as c:
        if (
            cluster_identifier(c) != source.system_identifier
            or migration_role_plan(c, extra, source.reader) != source.role_plan
        ):
            raise run.BackupError("EXTENDED_MIGRATION_SOURCE_IDENTITY_CHANGED")
        actual = extended_recovery.definitions.detail(
            c, {"accounts": {"owner": {"user": source.owner}}}
        )
        if not completion_recovery.equivalent_definitions(source.definitions, actual):
            raise run.BackupError("EXTENDED_MIGRATION_SOURCE_DEFINITIONS_CHANGED")
    with psycopg.connect(source.values["API_DATABASE_DSN"]) as c:
        generic.restricted(c)
        if generic.catalog(c) != source.catalog or generic.inventory(c) != source.rows:
            raise run.BackupError("EXTENDED_MIGRATION_SOURCE_ROWS_CHANGED")


def require_distinct_clusters(source_id, target_id):
    if (
        not str(source_id).isdigit()
        or not str(target_id).isdigit()
        or str(source_id) == str(target_id)
    ):
        raise run.BackupError("EXTENDED_MIGRATION_DISTINCT_CLUSTER_REQUIRED")


def provision_migration_target(source, target_owner_dsn):
    """Same logical role names, real new-cluster identities and brand-new passwords."""
    verify_migration_source(source)
    fields = local_migration_owner(target_owner_dsn)
    if fields["user"] != source.owner or fields.get("dbname") != "postgres":
        raise run.BackupError("EXTENDED_MIGRATION_TARGET_OWNER_CHANGED")
    passwords = {}
    with psycopg.connect(target_owner_dsn, autocommit=True) as c:
        target_id = cluster_identifier(c)
        require_distinct_clusters(source.system_identifier, target_id)
        databases = {r[0] for r in c.execute("SELECT datname FROM pg_database")}
        roles = {
            r[0] for r in c.execute("SELECT rolname FROM pg_roles WHERE left(rolname,3)<>'pg_'")
        }
        if databases != {"postgres", "template0", "template1"} or roles != {source.owner}:
            raise run.BackupError("EXTENDED_MIGRATION_TARGET_NOT_FRESH")
        with c.transaction():
            for name, login, inherit in source.role_plan["roles"]:
                password = secrets.token_urlsafe(36) if login else None
                if login:
                    passwords[name] = password
                c.execute(
                    sql.SQL(
                        "CREATE ROLE {} {} {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                    ).format(
                        sql.Identifier(name),
                        sql.SQL("LOGIN" if login else "NOLOGIN"),
                        sql.SQL("INHERIT" if inherit else "NOINHERIT"),
                        sql.Literal(password),
                    )
                )
            for group, member, admin, inherit, setting in source.role_plan["memberships"]:
                c.execute(
                    sql.SQL("GRANT {} TO {} WITH ADMIN {}, INHERIT {}, SET {}").format(
                        sql.Identifier(group),
                        sql.Identifier(member),
                        sql.Literal(admin),
                        sql.Literal(inherit),
                        sql.Literal(setting),
                    )
                )
    return {
        "values": {
            "OWNER_DATABASE_DSN": target_owner_dsn,
            "API_DATABASE_DSN": make_conninfo(
                target_owner_dsn, user=source.reader, password=passwords[source.reader]
            ),
        },
        "system_identifier": target_id,
        "passwords": passwords,
    }


@contextmanager
def migrated_database(source, target, *, tool, client):
    """Unchanged /3 restore checks; exact per-attempt cleanup while target is owned."""
    verify_migration_source(source)
    originals = completion_recovery.validate_originals(source.directory)
    state = {
        "source_system_identifier": source.system_identifier,
        "target_system_identifier": target["system_identifier"],
        "distinct_clusters": True,
        "full_application_restore_qualified": False,
        "production_rpo_rto_qualified": False,
    }
    try:
        receipt = extended_recovery.restore_database(target["values"], source.directory, tool=tool)
        objects = extended_recovery.restore_objects(
            source.directory, client, source.original_bucket
        )
        for item in originals["objects"]:
            run.read_object(
                client, objects["target_bucket"], item["key"], item["bytes"], item["sha256"]
            )
        verify_migration_source(source)
        state.update(database_receipt=receipt, object_receipt=objects, new_role_passwords=True)
        yield state
        verify_migration_source(source)
        for item in originals["objects"]:
            run.read_object(
                client, source.original_bucket, item["key"], item["bytes"], item["sha256"]
            )
        state["source_unchanged"] = True
    finally:
        with psycopg.connect(target["values"]["OWNER_DATABASE_DSN"], autocommit=True) as c:
            if (
                cluster_identifier(c) != target["system_identifier"]
                or target["system_identifier"] == source.system_identifier
            ):
                raise run.BackupError("EXTENDED_MIGRATION_CLEANUP_IDENTITY_CHANGED")
            for attempt in source.directory.glob("restore-attempt-*.json"):
                database = json.loads(attempt.read_text())["database"]
                if not re.fullmatch(r"tender_extended_restore_[0-9a-f]{32}", database):
                    raise run.BackupError("EXTENDED_MIGRATION_ATTEMPT_INVALID")
                c.execute(sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(database)))
                if c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
                    raise run.BackupError("EXTENDED_MIGRATION_DATABASE_REMAINS")
        for attempt in source.directory.glob("object-restore-attempt-*.json"):
            bucket = json.loads(attempt.read_text())["target_bucket"]
            if bucket == source.original_bucket or not re.fullmatch(
                r"tender-extended-restore-[0-9a-f]{32}", bucket
            ):
                raise run.BackupError("EXTENDED_MIGRATION_OBJECT_ATTEMPT_INVALID")
            for item in originals["objects"]:
                client.delete_object(Bucket=bucket, Key=item["key"])
            client.delete_bucket(Bucket=bucket)
            try:
                client.head_bucket(Bucket=bucket)
            except ClientError as error:
                if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                    raise
            else:
                raise run.BackupError("EXTENDED_MIGRATION_BUCKET_REMAINS")
        state["new_database_and_bucket_removed"] = True


_API_PRIVILEGES = {
    "schema": ("USAGE",),
    "table": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "column": ("SELECT", "INSERT", "UPDATE"),
    "sequence": ("USAGE", "SELECT", "UPDATE"),
    "function": ("EXECUTE",),
    "procedure": ("EXECUTE",),
}


def api_acl_grants(records):
    """A projection of measured source privileges, never a guessed grant template."""
    result = []
    for row in records:
        if (
            not isinstance(row, (tuple, list))
            or len(row) != 5
            or any(not isinstance(value, str) for value in row)
        ):
            raise run.BackupError("EXTENDED_MIGRATION_API_ACL_INVALID")
        kind, _schema, _name, _detail, privilege = row
        if kind not in _API_PRIVILEGES:
            raise run.BackupError("EXTENDED_MIGRATION_API_ACL_INVALID")
        if kind == "schema" and privilege == "CREATE":
            raise run.BackupError("EXTENDED_MIGRATION_API_CREATE_FORBIDDEN")
        if privilege in _API_PRIVILEGES[kind]:
            result.append(tuple(row))
    return sorted(set(result))


def require_api_acl_subset(actual, source):
    if not set(map(tuple, actual)) <= set(map(tuple, source)):
        raise run.BackupError("EXTENDED_MIGRATION_API_PRIVILEGE_EXPANSION")


def api_acl_rows(c, login):
    """Effective rights include inherited/PUBLIC rights, with column granularity."""
    extended_recovery.restricted_reader(c, login)
    schemas = c.execute(
        "SELECT 'schema',n.nspname,'','',p.priv FROM pg_namespace n "
        "CROSS JOIN (VALUES('USAGE'),('CREATE')) p(priv) WHERE n.nspname !~ '^pg_' "
        "AND n.nspname<>'information_schema' AND has_schema_privilege(%s,n.oid,p.priv)",
        (login,),
    ).fetchall()
    tables = c.execute(
        "SELECT 'table',n.nspname,t.relname,'',p.priv FROM pg_class t "
        "JOIN pg_namespace n ON n.oid=t.relnamespace CROSS JOIN "
        "(VALUES('SELECT'),('INSERT'),('UPDATE'),('DELETE'),('TRUNCATE'),"
        "('REFERENCES'),('TRIGGER'),('MAINTAIN')) p(priv) "
        "WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' "
        "AND t.relkind IN('r','p','v','m') AND has_table_privilege(%s,t.oid,p.priv)",
        (login,),
    ).fetchall()
    columns = c.execute(
        "SELECT 'column',n.nspname,t.relname,a.attname,p.priv FROM pg_attribute a "
        "JOIN pg_class t ON t.oid=a.attrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "CROSS JOIN (VALUES('SELECT'),('INSERT'),('UPDATE')) p(priv) "
        "WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' "
        "AND t.relkind IN('r','p','v','m') AND a.attnum>0 AND NOT a.attisdropped "
        "AND NOT has_table_privilege(%s,t.oid,p.priv) "
        "AND has_column_privilege(%s,t.oid,a.attnum,p.priv)",
        (login, login),
    ).fetchall()
    sequences = c.execute(
        "SELECT 'sequence',n.nspname,t.relname,'',p.priv FROM pg_class t "
        "JOIN pg_namespace n ON n.oid=t.relnamespace "
        "CROSS JOIN (VALUES('USAGE'),('SELECT'),('UPDATE')) p(priv) "
        "WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' "
        "AND t.relkind='S' AND has_sequence_privilege(%s,t.oid,p.priv)",
        (login,),
    ).fetchall()
    routines = c.execute(
        "SELECT CASE WHEN p.prokind='p' THEN 'procedure' ELSE 'function' END,"
        "n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),'EXECUTE' "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' "
        "AND p.prokind IN('f','p') AND has_function_privilege(%s,p.oid,'EXECUTE')",
        (login,),
    ).fetchall()
    return sorted(set(schemas + tables + columns + sequences + routines))


def activate_migrated_api(source, target, restored, login):
    """Explicit post-quarantine test activation; every other consumer stays closed."""
    verify_migration_source(source)
    receipt = restored.get("database_receipt", {})
    if (
        receipt.get("status") != "passed_extended_offline_database"
        or receipt.get("all_runtime_write_and_execute_privileges_removed") is not True
        or restored.get("target_system_identifier") != target["system_identifier"]
        or restored.get("full_application_restore_qualified") is not False
        or login not in target["passwords"]
    ):
        raise run.BackupError("EXTENDED_MIGRATION_OFFLINE_VERIFICATION_REQUIRED")
    with psycopg.connect(source.values["OWNER_DATABASE_DSN"]) as c:
        capability = c.execute("SELECT pg_has_role(%s,'tender_api','MEMBER')", (login,)).fetchone()
        if capability is None or not capability[0]:
            raise run.BackupError("EXTENDED_MIGRATION_API_CAPABILITY_REQUIRED")
        for role in (
            "tender_worker",
            "tender_research_worker",
            "tender_model_train",
            "tender_model_evaluate",
            "tender_model_score",
            "tender_assistant_budget_admin",
        ):
            if (
                c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
                and (
                    membership := c.execute(
                        "SELECT pg_has_role(%s,%s,'MEMBER')", (login, role)
                    ).fetchone()
                )
                is not None
                and membership[0]
            ):
                raise run.BackupError("EXTENDED_MIGRATION_API_PURPOSE_MIXED")
        source_acl = api_acl_rows(c, login)
        grants = api_acl_grants(source_acl)
        config = c.execute("SELECT rolconfig FROM pg_roles WHERE rolname=%s", (login,)).fetchone()
        if config is None:
            raise run.BackupError("EXTENDED_MIGRATION_API_CAPABILITY_REQUIRED")
        role_config = config[0] or []
        timeout = next(
            (
                item.split("=", 1)[1]
                for item in role_config
                if item.startswith("statement_timeout=")
            ),
            None,
        )
        if timeout is not None and not re.fullmatch(r"[0-9]+(?:ms|s|min)?", timeout):
            raise run.BackupError("EXTENDED_MIGRATION_API_SETTING_INVALID")
    database = receipt["database"]
    admin_dsn = make_conninfo(
        target["values"]["OWNER_DATABASE_DSN"],
        dbname=database,
        options="-c default_transaction_read_only=off",
    )
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        if cluster_identifier(c) != target["system_identifier"]:
            raise run.BackupError("EXTENDED_MIGRATION_TARGET_IDENTITY_CHANGED")
        roles = [row[0] for row in source.role_plan["roles"]]
        if extended_recovery.privilege_violations(
            c, roles, source.catalog["schemas"], reader=source.reader
        ):
            raise run.BackupError("EXTENDED_MIGRATION_OFFLINE_VERIFICATION_REQUIRED")
        before = api_acl_rows(c, login)
        require_api_acl_subset(before, source_acl)
        with c.transaction():
            for kind, schema, name, detail, privilege in grants:
                grantee = sql.Identifier(login)
                if kind == "schema":
                    statement = sql.SQL("GRANT {} ON SCHEMA {} TO {}").format(
                        sql.SQL(privilege), sql.Identifier(schema), grantee
                    )
                elif kind == "column":
                    statement = sql.SQL("GRANT {}({}) ON TABLE {} TO {}").format(
                        sql.SQL(privilege),
                        sql.Identifier(detail),
                        sql.Identifier(schema, name),
                        grantee,
                    )
                elif kind in {"function", "procedure"}:
                    # Identity arguments come only from this verified live source catalog,
                    # whose restored function definitions were checked before activation.
                    statement = sql.SQL("GRANT EXECUTE ON {} {}({}) TO {}").format(
                        sql.SQL(kind.upper()),
                        sql.Identifier(schema, name),
                        sql.SQL(detail),
                        grantee,
                    )
                else:
                    statement = sql.SQL("GRANT {} ON {} {} TO {}").format(
                        sql.SQL(privilege),
                        sql.SQL("SEQUENCE" if kind == "sequence" else "TABLE"),
                        sql.Identifier(schema, name),
                        grantee,
                    )
                c.execute(statement)
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(login)
                )
            )
            c.execute(
                sql.SQL(
                    "ALTER ROLE {} IN DATABASE {} SET default_transaction_read_only=off"
                ).format(sql.Identifier(login), sql.Identifier(database))
            )
            if timeout is not None:
                c.execute(
                    sql.SQL("ALTER ROLE {} IN DATABASE {} SET statement_timeout={}").format(
                        sql.Identifier(login), sql.Identifier(database), sql.Literal(timeout)
                    )
                )
            actual = api_acl_rows(c, login)
            require_api_acl_subset(actual, source_acl)
            if any(row[0] == "schema" and row[-1] == "CREATE" for row in actual):
                raise run.BackupError("EXTENDED_MIGRATION_API_CREATE_FORBIDDEN")
            for role in roles:
                if (
                    role not in {login, source.reader}
                    and (
                        connection := c.execute(
                            "SELECT has_database_privilege(%s,%s,'CONNECT')", (role, database)
                        ).fetchone()
                    )
                    is not None
                    and connection[0]
                ):
                    raise run.BackupError("EXTENDED_MIGRATION_OTHER_LOGIN_REOPENED")

    def digest(value):
        return run.digest(json.dumps(value, separators=(",", ":")).encode())

    public = {
        "offline_verified_before_activation": True,
        "source_effective_acl_sha256": digest(source_acl),
        "source_effective_acl_count": len(source_acl),
        "target_before_acl_sha256": digest(before),
        "target_before_acl_count": len(before),
        "target_after_acl_sha256": digest(actual),
        "target_after_acl_count": len(actual),
        "actual_acl_subset_of_source": True,
        "target_api_login": login,
        "other_purposes_connect_denied": True,
        "api_only_readwrite_setting": True,
        "full_application_restore_qualified": False,
    }
    restored["api_post_activation"] = public
    return make_conninfo(
        target["values"]["OWNER_DATABASE_DSN"],
        dbname=database,
        user=login,
        password=target["passwords"][login],
    ), public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--pg-library-dir", type=Path)
    parser.add_argument("--weed", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--case", choices=("all", *CASES), default="all")
    args = parser.parse_args()
    extended_recovery.frozen_plan()
    directory = args.report_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    clear_reports(directory)
    environment = ci_checks.test_environment()
    cleanup: list[dict] = []
    summaries = []
    exit_code = 0
    try:
        with temporary_object_store(
            args.weed, environment, directory / "s3.log", recovery=True
        ) as storage:
            for label, filename in CASES.items():
                if args.case != "all" and args.case != label:
                    continue
                report = directory / (label + "-junit.xml")
                report.unlink(missing_ok=True)
                (directory / (label + "-proof.json")).unlink(missing_ok=True)
                with temporary_postgres(
                    args.pg_bin, args.pg_library_dir, environment, cleanup
                ) as dsn:
                    test_env = (
                        environment
                        | storage
                        | {
                            "FUSION_EXTENDED_RECOVERY_PG": "1",
                            "FUSION_EXTENDED_RECOVERY_PG_BIN": str(args.pg_bin.resolve()),
                            "FUSION_EXTENDED_RECOVERY_REPORT_DIR": str(directory),
                            "FUSION_REQUIREMENTS_ADMIN_DSN": dsn,
                            "FUSION_AUTHORING_INPUT_ADMIN_DSN": dsn,
                        }
                    )
                    if args.pg_library_dir is not None:
                        test_env["FUSION_EXTENDED_RECOVERY_PG_LIBRARY_DIR"] = str(
                            args.pg_library_dir.resolve()
                        )
                    if os.environ.get("FUSION_EXTENDED_RECOVERY_KEEP_FAILURE") == "1":
                        test_env["FUSION_EXTENDED_RECOVERY_KEEP_FAILURE"] = "1"
                    result = subprocess.run(  # nosec B603
                        [
                            sys.executable,
                            "-m",
                            "pytest",
                            "-q",
                            filename,
                            "-x",
                            "--tb=short",
                            "--junitxml=" + str(report),
                        ],
                        cwd=run.ROOT,
                        env=test_env,
                        check=False,
                        timeout=900,
                    )
                    if report.is_file():
                        summary = ci_checks.junit_summary(report)
                        summaries.append({"case": label, **summary})
                        if (
                            result.returncode
                            or summary["skipped"]
                            or summary["failures"]
                            or summary["errors"]
                        ):
                            exit_code = 1
                    else:
                        exit_code = 1
                    if exit_code:
                        break
        cleanup.append({"s3_process_reaped_and_private_state_removed": True})
    finally:
        descriptor, temporary = tempfile.mkstemp(prefix="cleanup-", dir=directory)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({"format": extended_recovery.FORMAT, "services": cleanup}, output, indent=2)
        os.replace(temporary, directory / "cleanup.json")
    total = {
        key: sum(s[key] for s in summaries)
        for key in ("tests", "passed", "failures", "errors", "skipped")
    }
    total.update(
        {
            "suite": "extended-recovery",
            "cases": summaries,
            "exit_code": exit_code,
            "production_rpo_rto_qualified": False,
            "full_application_restore_qualified": False,
        }
    )
    run.private_write(directory / "summary.json", json.dumps(total, indent=2).encode())
    run.private_write(
        directory / "summary.md",
        ("# Extended offline recovery\n\n" + json.dumps(total, indent=2) + "\n").encode(),
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
