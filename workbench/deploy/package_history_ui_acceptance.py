"""Fresh PG17 public-history UI contracts; synthetic evidence and zero model calls."""

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

from deploy.schema_plan import BASE_SQL

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/test_package_history_ui_pg.py"
EXTENSIONS = (
    "deploy/sql/model-governance.sql",
    "deploy/sql/package-historical-admission.sql",
    "deploy/sql/package-historical-research.sql",
    "deploy/sql/package-history-exposure-bridge.sql",
    "deploy/sql/package-history-directory.sql",
)


def source_identity():
    paths = {
        path
        for directory in ("apps/api", "apps/worker", "packages", "deploy", "tests")
        for path in (ROOT / directory).rglob("*.py")
    }
    paths.update(
        ROOT / name for name in ("requirements.lock.txt", "requirements-package-history.txt")
    )
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def sql_identity():
    return [
        {"path": name, "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
        for name in (*BASE_SQL, *EXTENSIONS)
    ]


def fresh_output(path, code):
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError(code)


def run(args):
    fresh_output(args.receipt, "PACKAGE_HISTORY_UI_NEW_ABSOLUTE_RECEIPT_REQUIRED")
    fresh_output(args.fixture_dir, "PACKAGE_HISTORY_UI_NEW_ABSOLUTE_FIXTURE_DIRECTORY_REQUIRED")
    if not args.pg_bin.is_absolute() or any(
        not (args.pg_bin / name).is_file() for name in ("postgres", "initdb", "pg_ctl")
    ):
        raise ValueError("PACKAGE_HISTORY_UI_EXPLICIT_PG17_REQUIRED")
    if any(name in BASE_SQL for name in EXTENSIONS):
        raise ValueError("PACKAGE_HISTORY_UI_EXTENSIONS_MUST_REMAIN_OPTIONAL")
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    version = subprocess.check_output(  # nosec B603
        [str(args.pg_bin / "postgres"), "--version"], env=env, text=True, timeout=10
    ).strip()
    if not version.startswith("postgres (PostgreSQL) 17."):
        raise ValueError("PACKAGE_HISTORY_UI_PG17_REQUIRED")
    os.umask(0o077)
    args.fixture_dir.mkdir(parents=True, mode=0o700)
    root = Path(tempfile.mkdtemp(prefix="package-history-ui-acceptance-"))
    daemon = root / "daemon"
    daemon.mkdir()
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
    for path in (root, daemon):
        os.chown(path, account.pw_uid, account.pw_gid)
    password = secrets.token_urlsafe(36)
    pwfile = daemon / "owner-password"
    pwfile.write_text(password)
    os.chown(pwfile, account.pw_uid, account.pw_gid)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    test_command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "--junitxml=" + str(root / "pytest.xml"),
        TEST,
    ]
    result = {
        "schema": "package-history-ui-acceptance/1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "passed": False,
        "paid_calls": 0,
        "provider_requests": 0,
        "postgres_version": version,
        "postgres_binary_sha256": hashlib.sha256(
            (args.pg_bin / "postgres").read_bytes()
        ).hexdigest(),
        "python_version": sys.version.split()[0],
        "test_command": test_command,
        "source_before": source_identity(),
        "ordered_sql": sql_identity(),
        "scope": "actual public FastAPI main and complete exposure bridge; actual independent verifier/train/evaluate LOGINs and fixed CPU subprocesses",
        "boundaries": [
            "All original bytes, official results, time assertions, page coverage and proof issuers are explicit synthetic fixtures.",
            "No real qualification, model accuracy, formal score or release eligibility is asserted.",
            "Original-object transport is an explicit in-memory adapter, not S3 or a PDF renderer.",
            "CPU workers are explicitly run for exact job/generation identities; no automatic polling or Kafka transport is tested.",
            "This launcher only creates a new disposable local cluster and never attaches to a business database.",
        ],
    }
    started = False

    def pg(argv):
        with (root / "postgres-commands.log").open("ab") as log:
            subprocess.run(  # nosec B603
                argv,
                cwd=daemon,
                env=env,
                user=account.pw_uid,
                group=account.pw_gid,
                extra_groups=[],
                stdout=log,
                stderr=log,
                timeout=45,
                check=True,
            )

    try:
        pg(
            [
                str(args.pg_bin / "initdb"),
                "-D",
                str(daemon / "data"),
                "-U",
                "package_history_ui_owner",
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
                user="package_history_ui_owner",
                password=password,
                connect_timeout=5,
            ),
            "FUSION_PACKAGE_HISTORY_UI_PG": "1",
            "FUSION_PACKAGE_HISTORY_UI_FIXTURE_DIR": str(args.fixture_dir),
            "WORKBENCH_ENV_FILE": "explicit-package-history-ui-no-business-profile",
        }
        with (root / "pytest.log").open("wb") as log:
            completed = subprocess.run(  # nosec B603
                test_command,
                cwd=ROOT,
                env=test_env,
                stdout=log,
                stderr=log,
                timeout=600,
                check=False,
            )
        suites = ET.parse(root / "pytest.xml").getroot().findall("testsuite")  # nosec B314
        result["tests"] = {
            key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
            for key in ("tests", "errors", "failures", "skipped")
        }
        result["tests"]["seconds"] = sum(float(suite.attrib.get("time", 0)) for suite in suites)
        result["test_cases"] = [
            {
                "name": case.attrib["name"],
                "outcome": next(
                    (tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None),
                    "passed",
                ),
            }
            for suite in suites
            for case in suite.findall("testcase")
        ]
        result["pytest_returncode"] = completed.returncode
        result["source_unchanged_during_execution"] = result["source_before"] == source_identity()
        result["sql_unchanged_during_execution"] = result["ordered_sql"] == sql_identity()
        result["log_sha256"] = hashlib.sha256((root / "pytest.log").read_bytes()).hexdigest()
        result["http_fixtures"] = {
            path.name: {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in sorted(args.fixture_dir.glob("*.json"))
        }
        result["passed"] = (
            completed.returncode == 0
            and result["tests"]["tests"] > 0
            and result["tests"]["skipped"] == 0
            and result["source_unchanged_during_execution"]
            and result["sql_unchanged_during_execution"]
        )
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
        result["own_services_stopped"] = True
        pwfile.unlink(missing_ok=True)
        shutil.rmtree(daemon)
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        result["private_diagnostics"] = str(root)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in ("passed", "tests", "private_diagnostics", "own_services_stopped")
                    if key in result
                }
            ),
            flush=True,
        )
    return 0 if result["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
