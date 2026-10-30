"""Disposable prediction acceptance with pinned PG/Kafka and verified CI SeaweedFS.

No provider calls or persistent credentials. The caller supplies the official
SeaweedFS 4.48 archive; its repository CI digest is verified before extraction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from confluent_kafka.admin import AdminClient, NewTopic  # noqa: E402

from deploy.ci_object_store import temporary_object_store, unused_ports  # noqa: E402

PG = "pgvector/pgvector@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d"
KAFKA = "apache/kafka@sha256:5cc2a2fd93fa2687b44015eee04fb2c3edd9e526bd64bf8bec5ff1e268772e0e"
WEED_SHA = "4a7d108384d044d95212d1342cdda9533fa55842c1c9b41f606ca3c8a9561124"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)  # nosec B603


def acceptance(archive: Path, output: Path) -> int:
    if archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest() != WEED_SHA:
        raise ValueError("CI_SEAWEED_ARCHIVE_DIGEST_MISMATCH")
    for image in (PG, KAFKA):
        run("docker", "image", "inspect", image, stdout=subprocess.DEVNULL)
    output.mkdir(parents=True, exist_ok=False)
    names: list[str] = []
    token = uuid4().hex[:12]
    pg_name = "prediction-pg-" + token

    def container(name, image, environment, extra):
        command = ["docker", "run", "--rm", "-d", "--name", name, *extra]
        for key in environment:
            command.extend(["-e", key])
        run(*command, image, env=os.environ | environment, stdout=subprocess.DEVNULL)
        names.append(name)

    try:
        password = secrets.token_urlsafe(32)
        container(
            pg_name,
            PG,
            {"POSTGRES_PASSWORD": password},
            [
                "-p",
                "127.0.0.1::5432",
                "--tmpfs",
                "/var/lib/postgresql/data",
            ],
        )
        port = unused_ports(1)[0]
        container(
            "prediction-kafka-" + token,
            KAFKA,
            {
                "CLUSTER_ID": "MkU3OEVBNTcwNTJENDM2Qk",
                "KAFKA_NODE_ID": "1",
                "KAFKA_PROCESS_ROLES": "broker,controller",
                "KAFKA_LISTENERS": "PLAINTEXT://:9092,CONTROLLER://:9093",
                "KAFKA_ADVERTISED_LISTENERS": f"PLAINTEXT://127.0.0.1:{port}",
                "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT",
                "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
                "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
                "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1",
                "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": "1",
                "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": "1",
                "KAFKA_LOG_DIRS": "/tmp/kraft",  # nosec B108: isolated disposable container filesystem
                "KAFKA_AUTO_CREATE_TOPICS_ENABLE": "false",
                "KAFKA_HEAP_OPTS": "-Xms256m -Xmx512m",
            },
            ["-p", f"127.0.0.1:{port}:9092"],
        )
        for _ in range(40):
            ready = subprocess.run(  # nosec B603 B607
                ["docker", "exec", pg_name, "pg_isready", "-U", "postgres"], capture_output=True
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("DISPOSABLE_PG_NOT_READY")
        pgport = (
            subprocess.check_output(  # nosec B603 B607
                ["docker", "port", pg_name, "5432/tcp"]
            )
            .decode()
            .strip()
            .rsplit(":", 1)[1]
        )
        env = os.environ | {
            "FUSION_PREDICTION_NATIVE_PG": "1",
            "FUSION_PREDICTION_PG_CONTAINER": pg_name,
            "FUSION_PREDICTION_NATIVE_TRANSPORT": "1",
            "FUSION_REQUIREMENTS_ADMIN_DSN": f"host=127.0.0.1 port={pgport} user=postgres password={password} dbname=postgres",
            "KAFKA_BOOTSTRAP_SERVERS": f"127.0.0.1:{port}",
        }
        admin = AdminClient({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"], "log_level": 0})
        for _ in range(20):
            try:
                admin.list_topics(timeout=3)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("DISPOSABLE_KAFKA_NOT_READY")
        for future in admin.create_topics([NewTopic("tender.task.review.v1", 1, 1)]).values():
            future.result(30)
        with tempfile.TemporaryDirectory(prefix="prediction-weed-") as directory:
            with tarfile.open(archive) as bundle:
                entry = bundle.getmember("weed")
                if not entry.isfile():
                    raise ValueError("CI_SEAWEED_REGULAR_BINARY_REQUIRED")
                bundle.extract(entry, directory, filter="data")
            with temporary_object_store(
                Path(directory) / "weed", env, output / "s3.log", recovery=True
            ) as s3:
                with (output / "tests.log").open("w") as log:
                    result = subprocess.run(  # nosec B603
                        [
                            sys.executable,
                            "-m",
                            "pytest",
                            "-q",
                            "--tb=short",
                            "tests/test_package_prediction_native_pg.py",
                            "--junitxml=" + str(output / "tests.xml"),
                        ],
                        cwd=ROOT,
                        env=env | s3,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
        (output / "result.json").write_text(
            json.dumps(
                {
                    "exit_code": result.returncode,
                    "pg_image": PG,
                    "kafka_image": KAFKA,
                    "seaweed_archive_sha256": WEED_SHA,
                    "real_model_calls": 0,
                    "scope": "native installation, synthetic test-only publication and refusal/transport; not production qualification",
                },
                indent=2,
            )
            + "\n"
        )
        return result.returncode
    finally:
        for name in reversed(names):
            run("docker", "rm", "-f", name, stdout=subprocess.DEVNULL)
        (output / "cleanup.txt").write_text(
            "Temporary containers removed; no persistent credentials.\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seaweed-archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(acceptance(args.seaweed_archive.resolve(), args.output.resolve()))


if __name__ == "__main__":
    main()
