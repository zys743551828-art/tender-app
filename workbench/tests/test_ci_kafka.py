"""The native Kafka helper owns its process, private files and advertised address."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import ci_kafka


@pytest.fixture
def release(tmp_path):
    root = tmp_path / "kafka"
    for relative in (
        "bin/kafka-storage.sh",
        "bin/kafka-server-start.sh",
        "libs/kafka_2.13-4.1.2.jar",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic unit-test file, never executed")
    return root


@pytest.mark.parametrize("kind", ["missing-version", "symlink-command"])
def test_refuses_wrong_release_before_starting_a_process(release, tmp_path, monkeypatch, kind):
    if kind == "missing-version":
        (release / "libs/kafka_2.13-4.1.2.jar").unlink()
    else:
        command = release / "bin/kafka-server-start.sh"
        command.unlink()
        command.symlink_to(release / "bin/kafka-storage.sh")

    def forbidden(*_, **__):
        raise AssertionError("an unverified release must not launch")

    monkeypatch.setattr(ci_kafka.subprocess, "Popen", forbidden)
    monkeypatch.setattr(ci_kafka.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="VERIFIED_KAFKA_4_1_2"):
        with ci_kafka.temporary_kafka(release, {}, tmp_path / "kafka.log"):
            raise AssertionError("must not yield")


@pytest.fixture
def launch(monkeypatch):
    state = SimpleNamespace(starts=[], signals=[], directory=None, configuration=None)

    class Port:
        def __init__(self, number):
            self.number = number
            self.closed = False

        def getsockname(self):
            return "127.0.0.1", self.number

        def close(self):
            self.closed = True

    state.ports = [Port(19092), Port(19093)]
    monkeypatch.setattr(ci_kafka, "reserve_ports", lambda: state.ports)

    def run(args, **kwargs):
        if args[-1] == "random-uuid":
            return SimpleNamespace(stdout="HLwh2bhrRz-XSJ8CPtVPMw\n", returncode=0)
        assert "--standalone" in args
        kwargs["stdout"].write(b"synthetic format succeeded\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ci_kafka.subprocess, "run", run)

    class Process:
        returncode = None
        refuse_graceful = False

        def poll(self):
            return self.returncode

        def terminate(self):
            state.signals.append("terminate-owned")

        def kill(self):
            state.signals.append("kill-owned")
            self.returncode = -9

        def wait(self, timeout):
            if self.refuse_graceful and self.returncode is None:
                raise subprocess.TimeoutExpired("owned Kafka", timeout)
            self.returncode = self.returncode or 0
            return self.returncode

    state.process = Process()

    def start(args, **kwargs):
        state.starts.append(args)
        state.directory = kwargs["cwd"]
        state.configuration = Path(args[-1]).read_text()
        assert state.directory.stat().st_mode & 0o777 == 0o700
        assert Path(args[-1]).stat().st_mode & 0o777 == 0o600
        assert kwargs["env"]["KAFKA_JMX_OPTS"] == "-Djava.awt.headless=true"
        assert all(port.closed for port in state.ports)
        kwargs["stdout"].write(b"synthetic Kafka launch\n")
        return state.process

    monkeypatch.setattr(ci_kafka.subprocess, "Popen", start)
    monkeypatch.setattr(ci_kafka, "wait_ready", lambda *_: None)
    return state


@pytest.mark.parametrize("failure", ["test-body", "startup", "graceful-timeout"])
def test_exception_stops_only_owned_process_and_keeps_log_before_deleting_private_data(
    release, launch, monkeypatch, tmp_path, failure
):
    if failure == "startup":

        def fail(*_):
            raise RuntimeError("synthetic startup failure")

        monkeypatch.setattr(ci_kafka, "wait_ready", fail)
    elif failure == "graceful-timeout":
        launch.process.refuse_graceful = True
    log = tmp_path / "evidence/kafka.log"
    with pytest.raises(RuntimeError, match="synthetic"):
        with ci_kafka.temporary_kafka(release, {"PATH": "synthetic-path"}, log) as environment:
            assert environment == {"FUSION_MATERIAL_DISPATCH_KAFKA_BOOTSTRAP": "127.0.0.1:19092"}
            assert "listeners=PLAINTEXT://127.0.0.1:19092,CONTROLLER://127.0.0.1:19093" in (
                launch.configuration
            )
            assert "auto.create.topics.enable=false" in launch.configuration
            raise RuntimeError("synthetic test failure")
    assert len(launch.starts) == 1
    assert launch.signals == (
        ["terminate-owned", "kill-owned"] if failure == "graceful-timeout" else ["terminate-owned"]
    )
    assert all(port.closed for port in launch.ports)
    assert not launch.directory.exists()
    assert log.read_bytes() == b"synthetic format succeeded\nsynthetic Kafka launch\n"


@pytest.mark.parametrize("host,port", [("198.51.100.7", 19092), ("127.0.0.1", 29092)])
def test_readiness_rejects_metadata_that_routes_to_a_different_broker(monkeypatch, host, port):
    metadata = SimpleNamespace(brokers={1: SimpleNamespace(host=host, port=port)})
    monkeypatch.setattr(
        ci_kafka, "AdminClient", lambda _: SimpleNamespace(list_topics=lambda **_: metadata)
    )
    with pytest.raises(RuntimeError, match="EXACT_LOOPBACK_BROKER"):
        ci_kafka.wait_ready(SimpleNamespace(poll=lambda: None), "127.0.0.1:19092", 19092)
