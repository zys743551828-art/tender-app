"""Isolated B3 adoption: real PG17/S3, protected revisions and MockTransport generation."""

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
import time
import xml.etree.ElementTree as ET  # nosec B405
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from psycopg.conninfo import make_conninfo

from deploy.bootstrap_fresh import BASE_SQL

ROOT = Path(__file__).resolve().parents[1]
DDL = "packages/contracts/sql/authoring-package-inputs.sql"
GRANTS = "deploy/sql/bid-package-requirement-runtime-grants.sql"
EXTENSIONS = (
    "packages/assistant/sql/assistant.sql",
    "packages/assistant/sql/live-facts.sql",
    "packages/assistant/sql/intent-budget.sql",
    "packages/contracts/sql/authoring-package-jobs.sql",
    "packages/contracts/sql/authoring-exact-revisions.sql",
)


def source_identity(test_files=("tests/test_authoring_exact_revisions_pg.py",), extra_sources=()):
    paths = [
        *sorted((ROOT / "packages/authoring").glob("*.py")),
        ROOT / "apps/api/authoring_package_inputs.py",
        ROOT / "tests/authoring_package_input_fixtures.py",
        ROOT / "tests/authoring_package_job_fixtures.py",
        *[ROOT / name for name in test_files],
        *[ROOT / name for name in extra_sources],
        ROOT / "apps/api/authoring_exact_revisions.py",
        ROOT / "apps/api/assistant_routes.py",
        ROOT / "apps/api/work_context_catalog_routes.py",
        ROOT / "apps/api/authoring_input_catalog_routes.py",
        ROOT / "packages/contracts/work_context_catalog_api.py",
        ROOT / "packages/contracts/authoring_input_catalog_api.py",
        *sorted((ROOT / "packages/work_contexts").glob("*.py")),
        *sorted((ROOT / "packages/authoring_input_catalog").glob("*.py")),
        *sorted((ROOT / "packages/tasks").glob("*.py")),
        *sorted((ROOT / "packages/assistant").glob("*.py")),
        ROOT / "apps/api/task_routes.py",
        ROOT / "apps/worker/engine.py",
        Path(__file__),
    ]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def sql_identity(extensions=EXTENSIONS):
    return [
        {"path": name, "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
        for name in [*BASE_SQL, GRANTS, DDL, *extensions]
    ]


def free_ports(count):
    probes = []
    try:
        for _ in range(count):
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            probes.append(probe)
        return [probe.getsockname()[1] for probe in probes]
    finally:
        for probe in probes:
            probe.close()


def run(
    args,
    *,
    test_files=("tests/test_authoring_exact_revisions_pg.py",),
    stage="B3 published exact action adoption and immutable revision qualification; build unavailable",
    extensions=EXTENSIONS,
    extra_sources=(),
    schema="authoring-exact-revision-acceptance/1",
    pytest_args=(),
):
    if args.receipt.exists() or args.receipt.is_symlink():
        raise ValueError("AUTHORING_INPUT_NEW_RECEIPT_REQUIRED")
    if args.fixture_dir is not None:
        if not args.fixture_dir.is_absolute() or args.fixture_dir.exists():
            raise ValueError("AUTHORING_JOB_NEW_FIXTURE_DIRECTORY_REQUIRED")
        args.fixture_dir.mkdir(parents=True)
    for binary in [args.weed, *(args.pg_bin / name for name in ("postgres", "initdb", "pg_ctl"))]:
        if not binary.is_absolute() or not binary.is_file():
            raise ValueError("AUTHORING_INPUT_EXPLICIT_LOCAL_BINARIES_REQUIRED")
    if DDL in BASE_SQL:
        raise ValueError("AUTHORING_INPUT_B1_MUST_REMAIN_OPTIONAL")
    environment = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    version = subprocess.check_output(  # nosec B603
        [str(args.pg_bin / "postgres"), "--version"], env=environment, text=True, timeout=10
    ).strip()
    if not version.startswith("postgres (PostgreSQL) 17."):
        raise ValueError("AUTHORING_INPUT_PG17_REQUIRED")
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="authoring-exact-revisions-"))
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
    os.chown(root, account.pw_uid, account.pw_gid)
    pg_root, s3_root = root / "pg", root / "s3"
    for directory in (pg_root, s3_root):
        directory.mkdir()
        os.chown(directory, account.pw_uid, account.pw_gid)
    password = secrets.token_urlsafe(36)
    pwfile = pg_root / "owner-password"
    pwfile.write_text(password)
    os.chown(pwfile, account.pw_uid, account.pw_gid)
    access_key, secret_key = "synthetic-" + secrets.token_hex(12), secrets.token_urlsafe(36)
    identity = s3_root / "identity.json"
    identity.write_text(
        json.dumps(
            {
                "identities": [
                    {
                        "name": "synthetic-authoring-input",
                        "credentials": [{"accessKey": access_key, "secretKey": secret_key}],
                        "actions": ["Admin", "Read", "Write", "List", "Tagging"],
                    }
                ]
            }
        )
    )
    os.chown(identity, account.pw_uid, account.pw_gid)
    pg_port, master, master_grpc, volume, volume_grpc, filer, filer_grpc, s3, s3_grpc = free_ports(
        9
    )
    endpoint = f"http://127.0.0.1:{s3}"
    result = {
        "schema": schema,
        "stage": stage,
        "pytest_args": list(pytest_args),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "passed": False,
        "paid_calls": 0,
        "postgres_version": version,
        "python_version": sys.version.split()[0],
        "s3_binary_sha256": hashlib.sha256(args.weed.read_bytes()).hexdigest(),
        "upstream_evidence": "explicit synthetic parse, original bytes and extraction completion; no extraction quality claim",
        "object_transport": "real isolated loopback SeaweedFS S3 HTTP",
        "model_transport": "explicit httpx.MockTransport; zero paid provider calls",
        "source_sha256": source_identity(test_files, extra_sources),
        "ordered_sql": sql_identity(extensions),
    }
    pg_started, s3_process = False, None

    def pg(argv):
        with (root / "pg-commands.log").open("ab") as log:
            subprocess.run(  # nosec B603
                argv,
                cwd=pg_root,
                env=environment,
                user=account.pw_uid,
                group=account.pw_gid,
                extra_groups=[],
                stdout=log,
                stderr=log,
                timeout=30,
                check=True,
            )

    try:
        pg(
            [
                str(args.pg_bin / "initdb"),
                "-D",
                str(pg_root / "data"),
                "-U",
                "authoring_input_owner",
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
                str(pg_root / "data"),
                "-l",
                str(pg_root / "server.log"),
                "-o",
                f"-h 127.0.0.1 -p {pg_port} -k {pg_root}",
                "-w",
                "start",
            ]
        )
        pg_started = True
        with (root / "s3.log").open("wb") as log:
            s3_process = subprocess.Popen(  # nosec B603
                [
                    str(args.weed),
                    "server",
                    "-dir=" + str(s3_root),
                    "-ip=127.0.0.1",
                    "-ip.bind=127.0.0.1",
                    "-master.port=" + str(master),
                    "-master.port.grpc=" + str(master_grpc),
                    "-master.telemetry=false",
                    "-master.volumeSizeLimitMB=32",
                    "-volume.port=" + str(volume),
                    "-volume.port.grpc=" + str(volume_grpc),
                    "-volume.max=32",
                    "-filer",
                    "-filer.port=" + str(filer),
                    "-filer.port.grpc=" + str(filer_grpc),
                    "-filer.localSocket=" + str(s3_root / "filer.sock"),
                    "-s3",
                    "-s3.port=" + str(s3),
                    "-s3.port.grpc=" + str(s3_grpc),
                    "-s3.ip.bind=127.0.0.1",
                    "-s3.localSocket=" + str(s3_root / "s3.sock"),
                    "-s3.config=" + str(identity),
                    "-s3.iam=false",
                    "-s3.port.iceberg=0",
                    "-s3.port.lance=0",
                    "-s3.autoCreateBucket=false",
                    "-s3.allowDeleteBucketNotEmpty=false",
                ],
                cwd=s3_root,
                env=environment,
                user=account.pw_uid,
                group=account.pw_gid,
                extra_groups=[],
                stdout=log,
                stderr=log,
            )
            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name="us-east-1",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=1,
                    read_timeout=2,
                ),
            )
            deadline = time.monotonic() + 45
            while True:
                if s3_process.poll() is not None:
                    raise RuntimeError("AUTHORING_INPUT_S3_EXITED")
                try:
                    client.list_buckets()
                    break
                except (BotoCoreError, ClientError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("AUTHORING_INPUT_S3_NOT_READY") from None
                    time.sleep(0.2)
            bucket = "synthetic-authoring-" + secrets.token_hex(8)
            client.create_bucket(Bucket=bucket)
            test_env = environment | {
                "FUSION_AUTHORING_INPUT_ADMIN_DSN": make_conninfo(
                    host="127.0.0.1",
                    port=pg_port,
                    dbname="postgres",
                    user="authoring_input_owner",
                    password=password,
                    connect_timeout=5,
                ),
                "OBJECT_STORE_BACKEND": "s3",
                "OBJECT_STORE_ENDPOINT": endpoint,
                "OBJECT_STORE_ACCESS_KEY": access_key,
                "OBJECT_STORE_SECRET_KEY": secret_key,
                "OBJECT_STORE_BUCKET": bucket,
                "OBJECT_STORE_REGION": "us-east-1",
                "WORKBENCH_ENV_FILE": "explicit-authoring-input-no-business-profile",
            }
            if args.fixture_dir is not None:
                test_env["FUSION_AUTHORING_EXACT_FIXTURE_DIR"] = str(args.fixture_dir)
            xml = root / "pytest.xml"
            with (root / "pytest.log").open("wb") as test_log:
                executed = subprocess.run(  # nosec B603
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "--tb=short",
                        "--junitxml=" + str(xml),
                        *test_files,
                        *pytest_args,
                    ],
                    cwd=ROOT,
                    env=test_env,
                    stdout=test_log,
                    stderr=test_log,
                    timeout=900,
                    check=False,
                )
            suites = ET.parse(xml).getroot().findall("testsuite")  # nosec B314
            result["tests"] = {
                k: sum(int(s.attrib.get(k, 0)) for s in suites)
                for k in ("tests", "errors", "failures", "skipped")
            }
            result["tests"]["seconds"] = sum(float(s.attrib.get("time", 0)) for s in suites)
            result["test_cases"] = [
                {
                    "name": case.attrib["name"],
                    "outcome": next(
                        (
                            tag
                            for tag in ("failure", "error", "skipped")
                            if case.find(tag) is not None
                        ),
                        "passed",
                    ),
                }
                for suite in suites
                for case in suite.findall("testcase")
            ]
            result["source_unchanged_during_execution"] = result[
                "source_sha256"
            ] == source_identity(test_files, extra_sources)
            result["sql_unchanged_during_execution"] = result["ordered_sql"] == sql_identity(
                extensions
            )
            result["passed"] = (
                executed.returncode == 0
                and result["source_unchanged_during_execution"]
                and result["sql_unchanged_during_execution"]
            )
            result["completed_at"] = datetime.now(timezone.utc).isoformat()
            if args.fixture_dir is not None:
                result["api_fixture_sha256"] = {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(args.fixture_dir.glob("*.json"))
                }
    finally:
        if s3_process is not None and s3_process.poll() is None:
            s3_process.terminate()
            try:
                s3_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                s3_process.kill()
                s3_process.wait(timeout=5)
        if pg_started:
            pg(
                [
                    str(args.pg_bin / "pg_ctl"),
                    "-D",
                    str(pg_root / "data"),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ]
            )
        result["own_services_stopped"] = True
        if not result["passed"] and (pg_root / "server.log").exists():
            shutil.copyfile(pg_root / "server.log", root / "postgres-private.log")
        pwfile.unlink(missing_ok=True)
        identity.unlink(missing_ok=True)
        shutil.rmtree(pg_root)
        shutil.rmtree(s3_root)
        if not result["passed"]:
            result["private_diagnostics"] = str(root)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in ("passed", "tests", "private_diagnostics", "own_services_stopped")
                    if k in result
                }
            )
        )
    return 0 if result["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--weed", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
