"""New disposable PG17 + verified offline BGE acceptance, never a shared service.

The model process receives no database credentials. Business tests use distinct
nonowner LOGINs created by the existing fresh bootstrap. A receipt reports actual
tests and synthetic capacity separately; neither grants business quality status.
"""

from __future__ import annotations

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
import traceback
import xml.etree.ElementTree as ET  # nosec B405 -- locally generated pytest XML only
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql

from deploy import bootstrap_fresh as fresh
from deploy.initialize_database import file_configuration

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "deploy/rag_native_acceptance.py",
    "deploy/rag_native_scale.py",
    "packages/rag/numeric.py",
    "packages/rag/search.py",
    "packages/rag/http_port.py",
    "packages/rag/local_models.py",
    "packages/knowledge/rag_search.py",
    "packages/knowledge/rag_api.py",
    "apps/api/rag_routes.py",
    "tests/test_rag_real_integration.py",
    "tests/test_rag_staged_indexing.py",
    "tests/test_rag_staged_api.py",
    "tests/test_rag_numeric_pg.py",
    "tests/test_knowledge_rag_real.py",
)


def source_identity():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def private_file(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)


def free_ports():
    sockets = [socket.socket(), socket.socket()]
    try:
        for listener in sockets:
            listener.bind(("127.0.0.1", 0))
        return tuple(listener.getsockname()[1] for listener in sockets)
    finally:
        for listener in sockets:
            listener.close()


def run(args):
    for executable in [
        args.model_python,
        *(args.pg_bin / n for n in ("postgres", "initdb", "pg_ctl")),
    ]:
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("RAG_NATIVE_EXPLICIT_BINARIES_REQUIRED")
    if args.receipt.exists() or args.receipt.is_symlink():
        raise ValueError("RAG_NATIVE_NEW_RECEIPT_REQUIRED")
    operator = Path(tempfile.mkdtemp(prefix="tender-rag-operator-"))
    daemons = Path(tempfile.mkdtemp(prefix="tender-rag-daemons-"))
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
    os.chown(daemons, account.pw_uid, account.pw_gid)
    pg_port, model_port = free_ports()
    password, token = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    pwfile = daemons / "postgres-password"
    private_file(pwfile, password.encode())
    os.chown(pwfile, account.pw_uid, account.pw_gid)
    minimal = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}
    minimal["PYTHONDONTWRITEBYTECODE"] = "1"
    model = None
    model_log = None
    pg_started = False
    bootstrap = None
    result: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "passed": False,
        "paid_generation_calls": 0,
        "business_quality_accepted": False,
        "source_sha256": source_identity(),
        "scope": "Actual offline BGE, new PG17/pgvector, synthetic parse fixtures; not original-document or business relevance acceptance",
    }

    def daemon_command(argv):
        completed = subprocess.run(
            argv,
            cwd=daemons,
            env=minimal,
            user=account.pw_uid,
            group=account.pw_gid,
            extra_groups=[],
            capture_output=True,
            timeout=30,
            check=False,
        )  # nosec B603 -- explicit local binaries, no shell
        if completed.returncode:
            private_file(operator / (uuid4().hex + ".log"), completed.stdout + completed.stderr)
            raise ValueError("RAG_NATIVE_POSTGRES_COMMAND_FAILED")

    try:
        daemon_command(
            [
                str(args.pg_bin / "initdb"),
                "-D",
                str(daemons / "pgdata"),
                "-U",
                "postgres",
                "--pwfile=" + str(pwfile),
                "--auth-host=scram-sha-256",
                "--auth-local=scram-sha-256",
                "--encoding=UTF8",
                "--no-locale",
            ]
        )
        daemon_command(
            [
                str(args.pg_bin / "pg_ctl"),
                "-D",
                str(daemons / "pgdata"),
                "-l",
                str(daemons / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {pg_port} -k {daemons} -c shared_buffers=64MB -c max_connections=30 -c max_wal_size=256MB",
                "-w",
                "-t",
                "15",
                "start",
            ]
        )
        pg_started = True
        owner_dsn = f"postgresql://postgres:{password}@127.0.0.1:{pg_port}/postgres"
        with psycopg.connect(owner_dsn, autocommit=True) as c:
            for group in fresh.GROUPS:
                c.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
        profile = operator / "base.env"
        fresh.write_private(
            profile, {"OWNER_DATABASE_DSN": owner_dsn, "OBJECT_STORE_PREFIX": "synthetic-rag-local"}
        )
        extension = ROOT / "packages/knowledge/sql/rag.sql"
        bootstrap = fresh.bootstrap(
            base_profile=profile,
            name="rag_" + uuid4().hex[:10],
            extensions=((extension, hashlib.sha256(extension.read_bytes()).hexdigest()),),
            app_origin="http://127.0.0.1:5188",
        )
        values = file_configuration(ROOT / bootstrap["profiles"]["business"])
        result["ordered_sql"] = bootstrap["ordered_sql"]
        result["nonowner_logins_verified"] = bootstrap[
            "all_created_login_connections_verified_before_business_profiles"
        ]
        model_env = minimal | {"RAG_RUNTIME_TOKEN": token, "RAG_ASSET_DIRECTORY": str(args.assets)}
        model_log = (operator / "model.log").open("wb")
        model = subprocess.Popen(
            [str(args.model_python), "-m", "packages.rag.server", "--port", str(model_port)],
            cwd=ROOT,
            env=model_env,
            stdout=model_log,
            stderr=model_log,
        )  # nosec B603 -- explicit offline model runtime
        model_url = f"http://127.0.0.1:{model_port}"
        deadline = time.monotonic() + 180
        while True:
            if model.poll() is not None:
                raise ValueError("RAG_NATIVE_MODEL_START_FAILED")
            try:
                with httpx.Client(trust_env=False, timeout=2) as client:
                    response = client.get(
                        model_url + "/identity", headers={"Authorization": "Bearer " + token}
                    )
                if response.status_code == 200:
                    result["runtime"] = response.json()
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise ValueError("RAG_NATIVE_MODEL_START_TIMEOUT")
            time.sleep(0.25)
        print(
            json.dumps(
                {"stage": "real_bge_and_pg_ready", "dimensions": result["runtime"]["dimensions"]}
            ),
            flush=True,
        )
        test_env = (
            minimal
            | values
            | {
                "RAG_RUNTIME_URL": model_url,
                "RAG_RUNTIME_TOKEN": token,
                "RUN_RAG_REAL": "1",
                "SESSION_SECRET": secrets.token_urlsafe(48),
                "CSRF_SECRET": secrets.token_urlsafe(48),
                "WORKBENCH_ENV_FILE": "explicit-new-isolated-rag-acceptance",
            }
        )
        xml_path = operator / "pytest.xml"
        with (operator / "tests.log").open("wb") as log:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "-x",
                    "--junitxml=" + str(xml_path),
                    "tests/test_rag_real_integration.py",
                    "tests/test_rag_staged_indexing.py",
                    "tests/test_rag_staged_api.py",
                    "tests/test_rag_numeric_pg.py",
                    "tests/test_knowledge_rag_real.py",
                ],
                cwd=ROOT,
                env=test_env,
                stdout=log,
                stderr=log,
                timeout=900,
                check=False,
            )  # nosec B603
        tree = ET.parse(xml_path)  # nosec B314 -- only output from local pytest process
        suites = tree.getroot().findall("testsuite")
        result["tests"] = {
            key: sum(int(s.attrib.get(key, 0)) for s in suites)
            for key in ("tests", "errors", "failures", "skipped")
        }
        result["tests"]["seconds"] = sum(float(s.attrib.get("time", 0)) for s in suites)
        print(json.dumps({"stage": "real_tests_completed", **result["tests"]}), flush=True)
        if completed.returncode:
            raise ValueError("RAG_NATIVE_TESTS_FAILED")
        if args.scales:
            from deploy.rag_native_scale import measure

            # Explicit child-process environment is passed as data; no inherited business profile.
            result["scale"] = measure(test_env, args.scales, args.unique_texts)
        result["source_unchanged_during_execution"] = source_identity() == result["source_sha256"]
        if not result["source_unchanged_during_execution"]:
            raise ValueError("RAG_NATIVE_SOURCE_CHANGED_DURING_EXECUTION")
        result["passed"] = True
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        return 0
    except Exception as error:
        private_file(operator / "failure.log", traceback.format_exc().encode())
        result["failure_code"] = str(error) if type(error) is ValueError else type(error).__name__
        result["private_diagnostics"] = str(operator)
        return 1
    finally:
        if model is not None and model.poll() is None:
            model.terminate()
            try:
                model.wait(timeout=20)
            except subprocess.TimeoutExpired:
                model.kill()
                model.wait(timeout=5)
        if model_log is not None:
            model_log.close()
        if pg_started:
            daemon_command(
                [
                    str(args.pg_bin / "pg_ctl"),
                    "-D",
                    str(daemons / "pgdata"),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ]
            )
        if bootstrap:
            for path in bootstrap["profiles"].values():
                (ROOT / path).unlink(missing_ok=True)
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        private_file(
            args.receipt, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
        )
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in ("passed", "failure_code", "private_diagnostics")
                    if key in result
                }
            ),
            flush=True,
        )
        shutil.rmtree(daemons)
        if result["passed"]:
            shutil.rmtree(operator)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--model-python", required=True, type=Path)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--scales", type=int, nargs="*", default=[])
    parser.add_argument("--unique-texts", type=int, default=128)
    args = parser.parse_args()
    if any(size not in (1000, 10000, 50000) for size in args.scales) or len(args.scales) != len(
        set(args.scales)
    ):
        parser.error("Choose distinct explicit scale sizes: 1000, 10000, 50000")
    if not 16 <= args.unique_texts <= 1000:
        parser.error("Unique synthetic texts must be between 16 and 1000")
    os.umask(0o077)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
