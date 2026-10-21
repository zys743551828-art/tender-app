"""Fresh PG17 acceptance of explicit package triggers with no external model calls."""

import argparse
import hashlib
import json
import os
import pwd
import secrets
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
import xml.etree.ElementTree as ET  # nosec B405
from datetime import datetime, timezone
from pathlib import Path

from psycopg.conninfo import make_conninfo

from deploy.bootstrap_fresh import BASE_SQL

ROOT = Path(__file__).resolve().parents[1]
DDL = ROOT / "packages/contracts/sql/task-package-triggers.sql"


def identity():
    paths = [
        *sorted((ROOT / "packages/tasks").glob("*.py")),
        DDL,
        ROOT / "apps/api/task_routes.py",
        Path(__file__),
        ROOT / "tests/test_task_package_triggers_pg.py",
        ROOT / "tests/test_task_package_runs_pg.py",
    ]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def sql_identity():
    return [
        {"path": name, "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
        for name in dict.fromkeys([*BASE_SQL, "packages/contracts/sql/task-package-triggers.sql"])
    ]


def run(args):
    if hashlib.sha256(DDL.read_bytes()).hexdigest() != args.reviewed_sql_sha:
        raise ValueError("TASK_TRIGGER_REVIEWED_SQL_CHANGED")
    if args.receipt.exists() or args.receipt.is_symlink():
        raise ValueError("TASK_TRIGGER_NEW_RECEIPT_REQUIRED")
    for binary in ("postgres", "initdb", "pg_ctl"):
        if not args.pg_bin.is_absolute() or not (args.pg_bin / binary).is_file():
            raise ValueError("TASK_TRIGGER_EXPLICIT_PG17_REQUIRED")
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Execute only the explicit local binary, without a shell or inherited provider secrets.
    version_output = subprocess.check_output(
        [str(args.pg_bin / "postgres"), "--version"], env=env, text=True, timeout=10
    )  # nosec B603
    version = version_output.strip()
    if not version.startswith("postgres (PostgreSQL) 17."):
        raise ValueError("TASK_TRIGGER_PG17_REQUIRED")
    if args.http_fixture:
        if not args.http_fixture.is_absolute() or args.http_fixture.exists():
            raise ValueError("TASK_TRIGGER_NEW_ABSOLUTE_HTTP_FIXTURE_DIRECTORY_REQUIRED")
        args.http_fixture.mkdir(parents=True, mode=0o700)
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="task-package-trigger-acceptance-"))
    daemon = root / "daemon"
    daemon.mkdir()
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
    # Keep mkdtemp's private 0700 mode; only the isolated daemon and owner need access.
    os.chown(root, account.pw_uid, account.pw_gid)
    os.chown(daemon, account.pw_uid, account.pw_gid)
    password = secrets.token_urlsafe(36)
    pwfile = daemon / "owner-password"
    pwfile.write_text(password)
    os.chown(pwfile, account.pw_uid, account.pw_gid)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    result = {
        "schema": "task-package-trigger-acceptance/1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "passed": False,
        "paid_calls": 0,
        "model_transport": "explicit synthetic HTTP transport; no external calls",
        "postgres_version": version,
        "python_version": sys.version.split()[0],
        "reviewed_sql_sha256": args.reviewed_sql_sha,
        "source_sha256": identity(),
        "ordered_sql": sql_identity(),
    }
    started = False

    def pg(argv):
        with (root / "postgres-commands.log").open("ab") as log:
            subprocess.run(
                argv,
                cwd=daemon,
                env=env,
                user=account.pw_uid,
                group=account.pw_gid,
                extra_groups=[],
                stdout=log,
                stderr=log,
                timeout=30,
                check=True,
            )  # nosec B603

    try:
        pg(
            [
                str(args.pg_bin / "initdb"),
                "-D",
                str(daemon / "data"),
                "-U",
                "task_owner",
                "--pwfile=" + str(pwfile),
                "--auth-host=scram-sha-256",
                "--auth-local=scram-sha-256",
                "--encoding=UTF8",
                "--no-locale",
            ]
        )
        pg(
            [
                str(args.pg_bin / "pg_ctl"),
                "-D",
                str(daemon / "data"),
                "-l",
                str(daemon / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {port} -k {daemon}",
                "-w",
                "start",
            ]
        )
        started = True
        test_env = env | {
            "FUSION_REQUIREMENTS_ADMIN_DSN": make_conninfo(
                host="127.0.0.1",
                port=port,
                dbname="postgres",
                user="task_owner",
                password=password,
                connect_timeout=5,
            ),
            "TASK_PACKAGE_TRIGGER_REVIEWED_SQL_SHA": args.reviewed_sql_sha,
        }
        if args.http_fixture:
            test_env["TASK_PACKAGE_TRIGGER_HTTP_EXPORT"] = str(args.http_fixture)
        xml = root / "pytest.xml"
        with (root / "pytest.log").open("wb") as log:
            executed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "--junitxml=" + str(xml),
                    "tests/test_task_package_triggers_pg.py",
                    "tests/test_task_package_runs_pg.py",
                ],
                cwd=ROOT,
                env=test_env,
                stdout=log,
                stderr=log,
                timeout=600,
                check=False,
            )  # nosec B603
        suites = ET.parse(xml).getroot().findall("testsuite")  # nosec B314
        result["tests"] = {
            k: sum(int(s.attrib.get(k, 0)) for s in suites)
            for k in ("tests", "errors", "failures", "skipped")
        }
        result["tests"]["seconds"] = sum(float(s.attrib.get("time", 0)) for s in suites)
        result["test_cases"] = [
            {
                "module_class": case.attrib["classname"],
                "name": case.attrib["name"],
                "outcome": next(
                    (tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None),
                    "passed",
                ),
            }
            for suite in suites
            for case in suite.findall("testcase")
        ]
        result["source_unchanged_during_execution"] = result["source_sha256"] == identity()
        result["sql_unchanged_during_execution"] = result["ordered_sql"] == sql_identity()
        result["passed"] = (
            executed.returncode == 0
            and result["source_unchanged_during_execution"]
            and result["sql_unchanged_during_execution"]
        )
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        if args.http_fixture:
            result["synthetic_http_fixtures"] = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(args.http_fixture.glob("*.json"))
            }
    finally:
        if started:
            pg(
                [
                    str(args.pg_bin / "pg_ctl"),
                    "-D",
                    str(daemon / "data"),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ]
            )
        pwfile.unlink(missing_ok=True)
        shutil.rmtree(daemon)
        if not result["passed"]:
            result["private_diagnostics"] = str(root)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {k: result[k] for k in ("passed", "tests", "private_diagnostics") if k in result}
            ),
            flush=True,
        )
        if result["passed"]:
            shutil.rmtree(root)
    return 0 if result["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--reviewed-sql-sha", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--http-fixture", type=Path)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
