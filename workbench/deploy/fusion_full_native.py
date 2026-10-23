"""Exercise the full profile on new local PG/Kafka/S3 processes with zero model calls.

Only explicitly supplied, already present binaries are executed. No Docker,
downloads, shared database, production bucket or existing Kafka cluster is used.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from confluent_kafka.admin import AdminClient

from deploy import fusion_full_spec as spec
from deploy.fusion_full_configure import configure

SUITES = {
    "native": ("tests/test_fusion_full_native.py", 240),
    "transport-faults": ("tests/test_real_transport_fault_recovery.py", 480),
}


def ports(count):
    sockets = []
    try:
        for _ in range(count):
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            sockets.append(listener)
        selected = [listener.getsockname()[1] for listener in sockets]
        if 55441 in selected:
            raise spec.ConfigurationError("FULL_NATIVE_RESERVED_PORT_REFUSED")
        return selected
    finally:
        for listener in sockets:
            listener.close()


def run(args):
    if args.suite not in SUITES:
        raise spec.ConfigurationError("FULL_NATIVE_SUITE_INVALID")
    for executable in [
        args.weed,
        *(args.pg_bin / name for name in ("postgres", "pg_ctl", "initdb")),
        *(args.kafka_dir / "bin" / name for name in ("kafka-storage.sh", "kafka-server-start.sh")),
    ]:
        if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
            raise spec.ConfigurationError("FULL_NATIVE_EXPLICIT_LOCAL_BINARIES_REQUIRED")
    if args.receipt.exists() or args.receipt.is_symlink():
        raise spec.ConfigurationError("FULL_NATIVE_NEW_RECEIPT_REQUIRED")
    # Operator secrets and daemon data use separate private directories/OS identities.
    operator_root = Path(tempfile.mkdtemp(prefix="tender-full-operator-"))
    daemon_root = Path(tempfile.mkdtemp(prefix="tender-full-daemons-"))
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
    os.chown(daemon_root, account.pw_uid, account.pw_gid)
    allocated = ports(11)
    (
        postgres,
        broker,
        controller,
        master,
        master_grpc,
        volume,
        volume_grpc,
        filer,
        filer_grpc,
        s3,
        s3_grpc,
    ) = allocated
    name = "full_" + uuid4().hex[:12]
    directory = operator_root / "profile"
    configure(
        directory,
        name=name,
        origin="http://127.0.0.1:5189",
        # Native execution deliberately makes no claim to have run these container images.
        python_image="synthetic-unexecuted-python@sha256:" + "a" * 64,
        web_image="synthetic-unexecuted-web@sha256:" + "b" * 64,
        admin_password="native-synthetic-" + uuid4().hex,
        topology={
            "mode": "loopback",
            "postgres_host": "127.0.0.1",
            "postgres_port": postgres,
            "kafka_bootstrap": "127.0.0.1:" + str(broker),
            "s3_endpoint": "http://127.0.0.1:" + str(s3),
        },
    )
    operator = spec.load_private_json(directory / "operator.json")
    for name_on_disk, raw in (
        ("postgres-password", operator["owner_password"].encode()),
        ("s3-identities.json", (directory / "s3-identities.json").read_bytes()),
    ):
        destination = daemon_root / name_on_disk
        spec.write_private(destination, raw)
        os.chown(destination, account.pw_uid, account.pw_gid)
    kafka_config = {
        "process.roles": "broker,controller",
        "node.id": "1",
        "controller.quorum.voters": "1@127.0.0.1:" + str(controller),
        "listeners": f"INTERNAL://127.0.0.1:{broker},CONTROLLER://127.0.0.1:{controller}",
        "advertised.listeners": f"INTERNAL://127.0.0.1:{broker}",
        "listener.security.protocol.map": "INTERNAL:PLAINTEXT,CONTROLLER:PLAINTEXT",
        "inter.broker.listener.name": "INTERNAL",
        "controller.listener.names": "CONTROLLER",
        "log.dirs": str(daemon_root / "kafka-data"),
        "num.partitions": "6",
        "offsets.topic.replication.factor": "1",
        "transaction.state.log.replication.factor": "1",
        "transaction.state.log.min.isr": "1",
        "auto.create.topics.enable": "false",
        "group.initial.rebalance.delay.ms": "0",
        "num.network.threads": "2",
        "num.io.threads": "4",
    }
    config_path = daemon_root / "kafka.properties"
    spec.write_private(
        config_path,
        "".join(key + "=" + value + "\n" for key, value in kafka_config.items()).encode(),
    )
    os.chown(config_path, account.pw_uid, account.pw_gid)
    environment = {
        key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL"}
    }
    environment.update(
        KAFKA_HEAP_OPTS="-Xms256m -Xmx512m", LOG_DIR=str(daemon_root / "kafka-process-logs")
    )
    children, log_handles = [], []
    pg_started = False
    completed = False

    def command(argv, *, timeout=30):
        result = subprocess.run(
            argv,
            cwd=daemon_root,
            env=environment,
            user=account.pw_uid,
            group=account.pw_gid,
            extra_groups=[],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )  # nosec B603
        if result.returncode:
            # Output can include a command/configuration path. Keep it private for diagnosis.
            path = daemon_root / ("failed-command-" + uuid4().hex + ".log")
            spec.write_private(path, result.stdout + result.stderr or b"failed without output")
            raise spec.ConfigurationError("FULL_NATIVE_DAEMON_COMMAND_FAILED")
        return result

    def spawn(argv, log_name):
        path = daemon_root / log_name
        log = os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")
        log_handles.append(log)
        child = subprocess.Popen(
            argv,
            cwd=daemon_root,
            env=environment,
            user=account.pw_uid,
            group=account.pw_gid,
            extra_groups=[],
            stdout=log,
            stderr=log,
        )  # nosec B603
        children.append(child)
        return child

    try:
        command(
            [
                str(args.pg_bin / "initdb"),
                "-D",
                str(daemon_root / "pgdata"),
                "-U",
                "postgres",
                "--pwfile=" + str(daemon_root / "postgres-password"),
                "--auth-host=scram-sha-256",
                "--auth-local=scram-sha-256",
                "--encoding=UTF8",
                "--no-locale",
            ]
        )
        command(
            [
                str(args.pg_bin / "pg_ctl"),
                "-D",
                str(daemon_root / "pgdata"),
                "-l",
                str(daemon_root / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {postgres} -k {daemon_root} -c shared_buffers=32MB -c max_connections=40 -c max_wal_size=128MB",
                "-w",
                "-t",
                "15",
                "start",
            ]
        )
        pg_started = True
        command(
            [
                str(args.kafka_dir / "bin/kafka-storage.sh"),
                "format",
                "-t",
                operator["plan"]["kafka_cluster_id"],
                "-c",
                str(config_path),
            ]
        )
        kafka = spawn(
            [str(args.kafka_dir / "bin/kafka-server-start.sh"), str(config_path)], "kafka.log"
        )
        weed = spawn(
            [
                str(args.weed),
                "server",
                "-dir=" + str(daemon_root),
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
                "-filer.localSocket=" + str(daemon_root / "filer.sock"),
                "-s3",
                "-s3.port=" + str(s3),
                "-s3.port.grpc=" + str(s3_grpc),
                "-s3.ip.bind=127.0.0.1",
                "-s3.localSocket=" + str(daemon_root / "s3.sock"),
                "-s3.config=" + str(daemon_root / "s3-identities.json"),
                "-s3.iam=false",
                "-s3.port.iceberg=0",
                "-s3.port.lance=0",
                "-s3.autoCreateBucket=false",
                "-s3.allowDeleteBucketNotEmpty=false",
            ],
            "seaweed.log",
        )
        admin = AdminClient(
            {"bootstrap.servers": operator["plan"]["topology"]["kafka_bootstrap"], "log_level": 0}
        )
        deadline = time.monotonic() + 45
        while True:
            if kafka.poll() is not None or weed.poll() is not None:
                raise spec.ConfigurationError("FULL_NATIVE_DAEMON_EXITED")
            try:
                if admin.list_topics(timeout=1).cluster_id == operator["plan"]["kafka_cluster_id"]:
                    break
            except Exception:
                if time.monotonic() >= deadline:
                    raise spec.ConfigurationError("FULL_NATIVE_KAFKA_NOT_READY") from None
            time.sleep(0.2)
        test_environment = environment | {
            "FUSION_FULL_NATIVE_SUITE": args.suite,
            "FUSION_FULL_NATIVE_DIRECTORY": str(directory),
            "FUSION_FULL_NATIVE_RECEIPT": str(args.receipt.absolute()),
            "FUSION_FULL_NATIVE_TOOLS": json.dumps(
                {
                    "pg_bin": str(args.pg_bin),
                    "weed": str(args.weed),
                    "kafka_dir": str(args.kafka_dir),
                }
            ),
            "WORKBENCH_ENV_FILE": "explicit-native-full-profile-no-business-environment",
        }
        resources_path = operator_root / "native-resources.json"
        spec.write_private(
            resources_path,
            {
                "kafka_pid": kafka.pid,
                "s3_pid": weed.pid,
                "daemon_directory": str(daemon_root),
                "uid": account.pw_uid,
                "gid": account.pw_gid,
            },
        )
        test_environment["FUSION_FULL_NATIVE_RESOURCES"] = str(resources_path)
        test_module, test_timeout = SUITES[args.suite]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *(["-s"] if args.suite == "transport-faults" else []),
                test_module,
                "-x",
                "--tb=short",
            ],
            cwd=spec.fresh.ROOT,
            env=test_environment,
            timeout=test_timeout,
            check=False,
        )  # nosec B603
        completed = result.returncode == 0
        return result.returncode
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for log in log_handles:
            log.close()
        if pg_started:
            command(
                [
                    str(args.pg_bin / "pg_ctl"),
                    "-D",
                    str(daemon_root / "pgdata"),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ]
            )
        if not completed:
            diagnostics = args.receipt.absolute().with_suffix(".private-diagnostics")
            diagnostics.mkdir(mode=0o700)
            for index, root in enumerate((daemon_root, directory)):
                for path in root.glob("*.log"):
                    if path.is_file() and not path.is_symlink():
                        content = path.read_bytes()
                        spec.write_private(
                            diagnostics / (str(index) + "-" + path.name),
                            content[-1024 * 1024 :] or b"no output",
                        )
        # bootstrap_fresh creates only this task's named private files under .local.
        for root in (spec.fresh.ROOT / ".local",):
            for path in root.glob("*" + operator["plan"]["name"] + "*"):
                if path.is_file() and not path.is_symlink():
                    path.unlink()
        shutil.rmtree(daemon_root)
        shutil.rmtree(operator_root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--weed", required=True, type=Path)
    parser.add_argument("--kafka-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--suite", choices=sorted(SUITES), default="native")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        return run(args)
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, spec.ConfigurationError)
            else "FULL_NATIVE_ACCEPTANCE_FAILED_PRIVATE_DETAILS_SUPPRESSED"
        )
        print(code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
