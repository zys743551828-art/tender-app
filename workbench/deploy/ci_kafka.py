"""Own one disposable, loopback-only Kafka 4.1.2 KRaft service for native CI."""

from __future__ import annotations

import re
import socket
import subprocess  # nosec B404
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from confluent_kafka.admin import AdminClient


def verified_release(directory: Path) -> Path:
    """The caller verifies the official archive hash before invoking this helper."""
    directory = directory.resolve()
    for relative in (
        "bin/kafka-storage.sh",
        "bin/kafka-server-start.sh",
        "libs/kafka_2.13-4.1.2.jar",
    ):
        path = directory / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("CI_VERIFIED_KAFKA_4_1_2_RELEASE_REQUIRED")
    return directory


def reserve_ports() -> list[socket.socket]:
    sockets: list[socket.socket] = []
    try:
        for _ in range(2):
            item = socket.socket()
            sockets.append(item)
            item.bind(("127.0.0.1", 0))
        return sockets
    except BaseException:
        for item in sockets:
            item.close()
        raise


def configuration(directory: Path, broker_port: int, controller_port: int) -> str:
    return "\n".join(
        (
            "process.roles=broker,controller",
            "node.id=1",
            f"controller.quorum.bootstrap.servers=127.0.0.1:{controller_port}",
            f"listeners=PLAINTEXT://127.0.0.1:{broker_port},CONTROLLER://127.0.0.1:{controller_port}",
            f"advertised.listeners=PLAINTEXT://127.0.0.1:{broker_port},CONTROLLER://127.0.0.1:{controller_port}",
            "inter.broker.listener.name=PLAINTEXT",
            "controller.listener.names=CONTROLLER",
            "listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
            "num.network.threads=2",
            "num.io.threads=4",
            "num.recovery.threads.per.data.dir=1",
            f"log.dirs={directory / 'data'}",
            f"metadata.log.dir={directory / 'metadata'}",
            "num.partitions=1",
            "default.replication.factor=1",
            "min.insync.replicas=1",
            "offsets.topic.replication.factor=1",
            "offsets.topic.num.partitions=1",
            "transaction.state.log.replication.factor=1",
            "transaction.state.log.min.isr=1",
            "transaction.state.log.num.partitions=1",
            "share.coordinator.state.topic.replication.factor=1",
            "share.coordinator.state.topic.min.isr=1",
            "group.initial.rebalance.delay.ms=0",
            "auto.create.topics.enable=false",
            "delete.topic.enable=true",
            "log.retention.hours=24",
            "log.segment.bytes=16777216",
            "",
        )
    )


def wait_ready(process: subprocess.Popen, bootstrap: str, port: int) -> None:
    client = AdminClient(
        {
            "bootstrap.servers": bootstrap,
            "socket.timeout.ms": 1000,
            "socket.connection.setup.timeout.ms": 1000,
            "log_level": 0,
        }
    )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("CI_KAFKA_EXITED_BEFORE_READY")
        try:
            metadata = client.list_topics(timeout=1)
        except Exception:  # Startup connection errors are retried within this deadline.
            time.sleep(0.2)
            continue
        if len(metadata.brokers) != 1 or any(
            broker.host != "127.0.0.1" or broker.port != port
            for broker in metadata.brokers.values()
        ):
            raise RuntimeError("CI_KAFKA_METADATA_NOT_EXACT_LOOPBACK_BROKER")
        return
    raise RuntimeError("CI_KAFKA_NOT_READY")


@contextmanager
def temporary_kafka(directory: Path, environment: dict[str, str], log_path: Path):
    release = verified_release(directory)
    process = None
    with tempfile.TemporaryDirectory(prefix="tender-ci-kafka-") as name:
        private = Path(name)
        private.chmod(0o700)
        service_log = private / "kafka.log"
        sockets = reserve_ports()
        try:
            broker_port, controller_port = (item.getsockname()[1] for item in sockets)
            for child in ("data", "metadata", "logs"):
                (private / child).mkdir(mode=0o700)
            config = private / "server.properties"
            config.write_text(
                configuration(private, broker_port, controller_port), encoding="utf-8"
            )
            config.chmod(0o600)
            service_environment = environment | {
                "KAFKA_HEAP_OPTS": "-Xms128m -Xmx512m",
                # Do not enable a remote JMX listener.
                "KAFKA_JMX_OPTS": "-Djava.awt.headless=true",
                "LOG_DIR": str(private / "logs"),
            }
            with service_log.open("wb") as output:
                result = subprocess.run(  # nosec B603
                    [str(release / "bin/kafka-storage.sh"), "random-uuid"],
                    env=service_environment,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=30,
                )
                cluster = result.stdout.strip()
                if not re.fullmatch(r"[A-Za-z0-9_-]{22}", cluster):
                    raise RuntimeError("CI_KAFKA_CLUSTER_ID_INVALID")
                subprocess.run(  # nosec B603
                    [
                        str(release / "bin/kafka-storage.sh"),
                        "format",
                        "--standalone",
                        "-t",
                        cluster,
                        "-c",
                        str(config),
                    ],
                    env=service_environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=60,
                )
                for item in sockets:
                    item.close()
                process = subprocess.Popen(  # nosec B603
                    [str(release / "bin/kafka-server-start.sh"), str(config)],
                    cwd=private,
                    env=service_environment,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                bootstrap = f"127.0.0.1:{broker_port}"
                wait_ready(process, bootstrap, broker_port)
                try:
                    yield {"FUSION_MATERIAL_DISPATCH_KAFKA_BOOTSTRAP": bootstrap}
                finally:
                    # Flush the log after stopping the exact process we started.
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
        finally:
            for item in sockets:
                item.close()
            # Startup failures reach this branch before the yield's cleanup.
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_bytes(service_log.read_bytes() if service_log.exists() else b"")
