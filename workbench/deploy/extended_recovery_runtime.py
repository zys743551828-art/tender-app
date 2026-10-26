"""Run current extended recovery against disposable native PG17 and loopback S3."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import secrets
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

from deploy import ci_checks, extended_recovery
from deploy.backups import run
from deploy.ci_object_store import temporary_object_store

CASES = {
    "schema": "tests/test_extended_recovery_pg.py",
    "authoring": "tests/test_extended_recovery_authoring_pg.py",
    "material": "tests/test_extended_recovery_material_pg.py",
}


def clear_reports(directory):
    names = ["summary.json", "summary.md", "cleanup.json", "s3.log", "reader-rejection-proof.json"]
    names.extend(label + suffix for label in CASES for suffix in ("-junit.xml", "-proof.json"))
    for name in names:
        (directory / name).unlink(missing_ok=True)


@contextmanager
def temporary_postgres(binary_directory, library_directory, environment, cleanup):
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
    owner = "extended_recovery_owner_" + secrets.token_hex(8)
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
