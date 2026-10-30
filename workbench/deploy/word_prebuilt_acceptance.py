"""Local acceptance using preinstalled immutable Word, PG17 and S3 images.

--report-dir must name a new directory with an existing parent. Images are
never pulled or built. The real API/Worker test exports only synthetic bytes.
"""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import boto3
import psycopg
from botocore.config import Config
from psycopg import sql
from psycopg.conninfo import make_conninfo

from deploy.ci_checks import junit_summary, test_environment
from deploy.disposable_docker import DockerTestRun
from deploy.schema_plan import BASE_SQL
from packages.word_intake import prebuilt

PG = "pgvector/pgvector@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d"
S3 = "chrislusf/seaweedfs@sha256:bb05d66d2963b1cc48073190781c3dd29e2c4c88a2ae2986bf58e38c86d89c6e"


@contextmanager
def isolated_environment():
    """Parent libraries and child processes see no ambient business settings."""
    allowed = test_environment()
    previous = dict(os.environ)
    mask = os.umask(0o077)
    try:
        os.environ.clear()
        os.environ.update(allowed)
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)
        os.umask(mask)


def private_directory(path: Path):
    """Restrict the directory and inherited artifacts to this user and SYSTEM."""
    if os.name != "nt":
        path.chmod(0o700)
        return
    identity = subprocess.run(  # nosec B603 - fixed local identity query
        ["whoami", "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    values = list(csv.reader(identity.stdout.splitlines()))
    sid = values[0][-1] if len(values) == 1 and values[0] else ""
    if identity.returncode or not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise RuntimeError("WORD_ACCEPTANCE_PRIVATE_IDENTITY_FAILED")
    permissions = subprocess.run(  # nosec B603 - literal arguments, no shell
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(OI)(CI)F",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if permissions.returncode:
        raise RuntimeError("WORD_ACCEPTANCE_PRIVATE_PERMISSIONS_FAILED")


def write_private(path: Path, text: str):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8"
    ) as stream:
        stream.write(text)


def redact(text: str, sensitive: list[str]) -> str:
    for value in sensitive:
        if value:
            text = text.replace(value, "[redacted]")
    return re.sub(
        r"(X-Amz-(?:Signature|Credential|Security-Token)=)[^&\s<>\"']+",
        r"\1[redacted]",
        text,
        flags=re.IGNORECASE,
    )


class LocalRun(DockerTestRun):
    @staticmethod
    def _call(*args, timeout=60, env=None):
        value = prebuilt._call(list(args), timeout=timeout)
        return subprocess.CompletedProcess(
            value.args,
            value.returncode,
            value.stdout.decode("utf8", errors="replace"),
            value.stderr.decode("utf8", errors="replace"),
        )


def call(*args):
    value = prebuilt._call(list(args), timeout=60)
    if value.returncode:
        raise RuntimeError("WORD_PG_DOCKER_COMMAND_FAILED")
    return value.stdout.decode("utf8")


def port(identity, container_port):
    data = json.loads(call("container", "inspect", identity))[0]
    bindings = data["NetworkSettings"]["Ports"].get(str(container_port) + "/tcp")
    if not bindings:
        raise RuntimeError("WORD_PG_LOOPBACK_PORT_NOT_PUBLISHED")
    binding = bindings[0]
    assert binding["HostIp"] == "127.0.0.1"
    return int(binding["HostPort"])


def stop_test_process(process):
    """Stop only the process group created by this entry, before Docker recovery."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", 1))
        else:
            os.killpg(process.pid, signal.SIGINT)
        process.communicate(timeout=80)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    if os.name == "nt":
        subprocess.run(  # nosec B603 - exact owned process tree, never a name/global scan
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        raise RuntimeError("WORD_ACCEPTANCE_CHILD_STOP_INCOMPLETE") from None
    if process.poll() is None:
        raise RuntimeError("WORD_ACCEPTANCE_CHILD_STOP_INCOMPLETE")


def wait_test_process(process, *, timeout=360):
    try:
        return process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_test_process(process)
        raise RuntimeError("WORD_ACCEPTANCE_TEST_TIMEOUT") from None
    except BaseException:
        stop_test_process(process)
        raise


def recover_conversion_receipts(directory: Path):
    """Recover only exact resources in this parent's private receipt directory."""
    if directory.is_symlink() or not directory.is_dir():
        return [
            {
                "receipt": None,
                "closed": False,
                "error_code": "WORD_ACCEPTANCE_RECEIPT_DIRECTORY_INVALID",
            }
        ]
    results = []
    for path in sorted(directory.glob("conversion-*.json")):
        item = {"receipt": path.name, "closed": False}
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError("receipt")
            record = json.loads(path.read_text(encoding="utf-8"))
            run_id = record["run_id"]
            if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
                raise ValueError("run")
            resources = record["resources"]
            if not isinstance(resources, list) or len(resources) > 1:
                raise ValueError("resources")
            for resource in resources:
                if (
                    not isinstance(resource, dict)
                    or resource.get("kind") != "container"
                    or not re.fullmatch(
                        rf"tender-test-{run_id[:12]}-[1-9][0-9]*", resource.get("name", "")
                    )
                    or resource.get("state") not in {"creating", "created", "removed"}
                    or (
                        resource.get("id") is not None
                        and not re.fullmatch(r"[0-9a-f]{64}", resource["id"])
                    )
                ):
                    raise ValueError("resource")
            # Rehydrate this exact durable record, retaining the helper's ID and
            # both-label checks. Even already-closed records are inspected again.
            recovery = LocalRun.__new__(LocalRun)
            recovery.receipt = path
            recovery.run_id = run_id
            recovery.resources = [resource | {"state": "created"} for resource in resources]
            recovery.closed = False
            for resource in recovery.resources:
                if resource["id"] is None:
                    observed = recovery._owned(resource)
                    if observed is None:
                        # A killed Docker create may have an uncertain daemon
                        # outcome. Do not claim that an unobserved creation was
                        # removed, or search unrelated resources to guess it.
                        raise RuntimeError("WORD_ACCEPTANCE_CREATION_OUTCOME_UNCERTAIN")
                    resource["id"] = observed["Id"]
            recovery._save()
            recovery.cleanup()
            item.update(run_id=run_id, closed=recovery.closed)
        except (
            KeyError,
            TypeError,
            ValueError,
            RuntimeError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            item["error_code"] = (
                str(error)
                if isinstance(error, RuntimeError) and str(error).startswith("WORD_ACCEPTANCE_")
                else "WORD_ACCEPTANCE_CONVERSION_RECOVERY_FAILED"
            )
        results.append(item)
    return results


def acceptance(out: Path):
    status = {"state": "starting", "stage": "dependencies", "kafka_broker_tested": False}
    stage = "dependencies"
    code = 1
    run = LocalRun(out / "resources.json")
    sensitive = []
    test_process = None
    receipts = out / "conversion-receipts"
    receipts.mkdir(mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix="word-prebuilt-pg-") as temporary, run:
            private = Path(temporary)
            private_directory(private)
            # This absolute nonexistent path prevents implicit profile discovery.
            os.environ["WORKBENCH_ENV_FILE"] = str(private / "no-business.env")
            stage = "preinstalled_images"
            for image in (PG, S3, prebuilt.IMAGE):
                result = prebuilt._call(["image", "inspect", image])
                if result.returncode:
                    raise RuntimeError("WORD_ACCEPTANCE_LOCAL_IMAGE_REQUIRED")
            stage = "dependencies"
            # Docker Desktop does not publish host ports for an internal bridge.
            # This run-owned bridge has only explicit 127.0.0.1 host bindings;
            # services never make external requests.
            network = run._create("network", ["--driver", "bridge"])
            pg_password, access, secret = (secrets.token_urlsafe(30) for _ in range(3))
            sensitive.extend([pg_password, access, secret])
            pg_password_file = private / "postgres-password"
            write_private(pg_password_file, pg_password)
            credentials = private / "s3-identities.json"
            write_private(
                credentials,
                json.dumps(
                    {
                        "identities": [
                            {
                                "name": "word-prebuilt-disposable",
                                "credentials": [{"accessKey": access, "secretKey": secret}],
                                "actions": ["Admin", "Read", "Write", "List", "Tagging"],
                            }
                        ]
                    }
                ),
            )
            # Random credentials stay in private temporary files/memory, never
            # Docker command arguments, receipts or test reports.
            pg = run.container(
                PG,
                [
                    "--network",
                    network,
                    "--publish",
                    "127.0.0.1::5432",
                    "--memory",
                    "1g",
                    "--tmpfs",
                    "/var/run/postgresql",
                    "--env",
                    "POSTGRES_HOST_AUTH_METHOD=scram-sha-256",
                    "--env",
                    "POSTGRES_PASSWORD_FILE=/tmp/bootstrap-password",
                    "--env",
                    "POSTGRES_DB=postgres",
                ],
                ["postgres", "-c", "log_statement=none", "-c", "log_min_error_statement=panic"],
            )
            s3 = run.container(
                S3,
                [
                    "--network",
                    network,
                    "--network-alias",
                    "object-store",
                    "--publish",
                    "127.0.0.1::8333",
                    "--memory",
                    "768m",
                ],
                [
                    "server",
                    "-dir=/data",
                    "-ip=object-store",
                    "-ip.bind=0.0.0.0",
                    "-master.volumeSizeLimitMB=64",
                    "-volume.max=4",
                    "-s3",
                    "-s3.port=8333",
                    "-s3.config=/tmp/s3-identities.json",
                ],
            )
            call("cp", str(credentials), s3 + ":/tmp/s3-identities.json")
            call("cp", str(pg_password_file), pg + ":/tmp/bootstrap-password")
            run.start(pg)
            run.start(s3)
            stage = "loopback_port_bindings"
            pg_port, s3_port = port(pg, 5432), port(s3, 8333)
            admin_dsn = make_conninfo(
                host="127.0.0.1",
                port=pg_port,
                dbname="postgres",
                user="postgres",
                password=pg_password,
                connect_timeout=2,
            )
            for _ in range(45):
                try:
                    with psycopg.connect(admin_dsn, autocommit=True) as c:
                        c.execute("SELECT 1")
                    break
                except psycopg.OperationalError:
                    time.sleep(1)
            else:
                raise RuntimeError("WORD_PG_READY_TIMEOUT")
            admin_dsn = make_conninfo(admin_dsn, password=pg_password)
            stage = "schema"
            owner_dsn = make_conninfo(admin_dsn, dbname="word_prebuilt_disposable")
            api_password, worker_password = secrets.token_urlsafe(30), secrets.token_urlsafe(30)
            sensitive.extend([api_password, worker_password])
            with psycopg.connect(admin_dsn, autocommit=True) as c:
                version = c.execute("SHOW server_version_num").fetchone()
                if version is None or int(version[0]) // 10000 != 17:
                    raise RuntimeError("WORD_PG_VERSION_MISMATCH")
                c.execute("CREATE DATABASE word_prebuilt_disposable TEMPLATE template0")
            with psycopg.connect(owner_dsn, autocommit=True) as owner:
                for name in [*BASE_SQL, "packages/word_intake/schema.sql"]:
                    status["schema_file"] = name
                    owner.execute((APP / name).read_text(encoding="utf8"))
                for role, capability, password in [
                    ("word_prebuilt_api", "tender_api", api_password),
                    ("word_prebuilt_worker", "tender_worker", worker_password),
                ]:
                    owner.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                        ).format(sql.Identifier(role), sql.Literal(password))
                    )
                    owner.execute(
                        sql.SQL("GRANT {} TO {}").format(
                            sql.Identifier(capability), sql.Identifier(role)
                        )
                    )
                    # Match bootstrap_fresh's LOGIN configuration: API commit
                    # deliberately rolls back the preflight transaction.
                    owner.execute(
                        sql.SQL("ALTER ROLE {} SET search_path TO design, public").format(
                            sql.Identifier(role)
                        )
                    )
            (out / "schema-plan.json").write_text(
                json.dumps(
                    {
                        "postgres_major": 17,
                        "sql_order": [*BASE_SQL, "packages/word_intake/schema.sql"],
                        "api_nonowner_login": True,
                        "worker_nonowner_login": True,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf8",
            )
            stage = "s3"
            endpoint = f"http://127.0.0.1:{s3_port}"
            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access,
                aws_secret_access_key=secret,
                region_name="us-east-1",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=2,
                    read_timeout=3,
                    retries={"max_attempts": 0},
                ),
            )
            bucket = "word-prebuilt-" + run.run_id
            for _ in range(50):
                try:
                    client.create_bucket(Bucket=bucket)
                    client.put_object(
                        Bucket=bucket,
                        Key="readiness/" + run.run_id,
                        Body=b"synthetic-private-readiness",
                    )
                    break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError("WORD_S3_READY_TIMEOUT")
            stage = "profile"
            profile = prebuilt.build_profile(receipt=out / "profile-resources.json")
            profile_path = out / "profile.json"
            profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf8")
            env = test_environment()
            env.update(
                {
                    "API_DATABASE_DSN": make_conninfo(
                        owner_dsn, user="word_prebuilt_api", password=api_password
                    ),
                    "WORKER_DATABASE_DSN": make_conninfo(
                        owner_dsn, user="word_prebuilt_worker", password=worker_password
                    ),
                    "OBJECT_STORE_BACKEND": "s3",
                    "OBJECT_STORE_ENDPOINT": endpoint,
                    "OBJECT_STORE_ACCESS_KEY": access,
                    "OBJECT_STORE_SECRET_KEY": secret,
                    "OBJECT_STORE_REGION": "us-east-1",
                    "OBJECT_STORE_BUCKET": bucket,
                    "RUN_WORD_PREBUILT_PG": "1",
                    "WORD_PREBUILT_PG_PROFILE": str(profile_path),
                    "WORD_PREBUILT_PG_RESULT_DIRECTORY": str(out),
                    "WORD_RENDER_TEST_RECEIPT_DIRECTORY": str(receipts),
                    "PYTHONPATH": str(APP),
                    "WORKBENCH_ENV_FILE": str(private / "no-business.env"),
                    "NO_PROXY": "localhost,127.0.0.1",
                    "no_proxy": "localhost,127.0.0.1",
                }
            )
            stage = "pytest"
            test_process = subprocess.Popen(  # nosec B603 - fixed test and filtered environment
                [
                    sys.executable,
                    "-B",
                    "-X",
                    "utf8",
                    "-m",
                    "pytest",
                    "tests/test_word_prebuilt_pg.py",
                    "-q",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                    "--junitxml=" + str(out / "junit.xml"),
                ],
                cwd=APP,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf8",
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                if os.name == "nt"
                else 0,
                start_new_session=os.name != "nt",
            )
            stdout, stderr = wait_test_process(test_process)
            write_private(out / "pytest.txt", redact(stdout + stderr, sensitive))
            junit_path = out / "junit.xml"
            if junit_path.is_file():
                junit_path.write_text(
                    redact(junit_path.read_text(encoding="utf-8"), sensitive), encoding="utf-8"
                )
            if test_process.returncode is None:
                raise RuntimeError("WORD_ACCEPTANCE_CHILD_RESULT_MISSING")
            code = test_process.returncode
            totals = junit_summary(junit_path)
            if totals["tests"] != 1 or totals["passed"] != 1 or totals["skipped"]:
                code = 1
            status = {
                "state": "passed" if code == 0 else "failed",
                "stage": stage,
                "exit_code": code,
                "kafka_broker_tested": False,
                "loopback_ports_only": True,
                "private_bucket": True,
                "test_totals": totals,
            }
    except BaseException as error:
        schema_file = status.get("schema_file")
        status = {
            "state": "failed",
            "stage": stage,
            "error_type": type(error).__name__,
            "kafka_broker_tested": False,
        }
        status["error_frames"] = [
            {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
            for f in traceback.extract_tb(error.__traceback__)
        ]
        if schema_file:
            status["schema_file"] = schema_file
        if isinstance(error, psycopg.Error):
            status["sqlstate"] = error.sqlstate
        code = 130 if isinstance(error, KeyboardInterrupt) else 1
        if code == 130:
            status["state"] = "cancelled"
        if isinstance(error, RuntimeError) and str(error).startswith("WORD_"):
            status["error_code"] = str(error)
    finally:
        child_closed = True
        if test_process is not None and test_process.poll() is None:
            try:
                stop_test_process(test_process)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                child_closed = False
        conversions = recover_conversion_receipts(receipts) if child_closed else []
        # A cancelled/timed-out pytest may have written partial XML before the
        # ordinary reporting branch. Redact only after its process has stopped.
        if child_closed:
            for name in ("pytest.txt", "junit.xml"):
                path = out / name
                if path.is_file() and not path.is_symlink():
                    path.write_text(
                        redact(path.read_text(encoding="utf-8", errors="replace"), sensitive),
                        encoding="utf-8",
                    )
        if not run.closed:
            try:
                run.cleanup()
            except (RuntimeError, OSError, subprocess.SubprocessError):
                status["state"] = "failed"
                status["error_code"] = "WORD_ACCEPTANCE_CLEANUP_INCOMPLETE"
                code = 1
        conversion_closed = child_closed and all(item["closed"] for item in conversions)
        status["test_process_stopped"] = child_closed
        status["conversion_receipts"] = conversions
        status["cleanup_closed"] = run.closed and conversion_closed
        if not status["cleanup_closed"]:
            status["state"] = "failed"
            status["error_code"] = "WORD_ACCEPTANCE_CLEANUP_INCOMPLETE"
            code = 1
        write_private(out / "summary.json", json.dumps(status, indent=2) + "\n")
        print(json.dumps(status))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.report_dir.expanduser().resolve()
    try:
        # Atomic and intentionally no exist_ok: never overwrite an earlier run.
        out.mkdir(mode=0o700)
    except FileExistsError:
        print(json.dumps({"state": "failed", "error_code": "WORD_ACCEPTANCE_REPORT_EXISTS"}))
        return 2
    except OSError:
        print(json.dumps({"state": "failed", "error_code": "WORD_ACCEPTANCE_REPORT_CREATE_FAILED"}))
        return 2
    try:
        with isolated_environment():
            private_directory(out)
            return acceptance(out)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        print(
            json.dumps({"state": "failed", "error_code": "WORD_ACCEPTANCE_INITIALIZATION_FAILED"})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
